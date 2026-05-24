# F-0019d — In-App Lifecycle Surfacing (Loops webhook + Trial banner) — Design

**Status:** Proposed
**Depends on:** F-0019a (Stripe billing, merged), F-0019c (Loops integration, merged)
**Scope:** Thin backend + small frontend.

## Goal

Add the two pieces of in-app lifecycle surfacing that F-0019a deliberately kept out of scope:

1. An inbound webhook that Loops workflows POST to, creating in-app NotificationBell entries for the addressed user.
2. A global trial / lockout / cancel banner in the app header, driven by the existing subscription store, with escalating copy at 14 / 7 / 3 / 1 / 0 days.

The Stripe + Loops outbound integrations already in production handle billing enforcement and outbound email. This task layers the in-app visibility on top.

---

## Part 1 — Loops inbound webhook

### Route

`POST /webhooks/loops/notification` — new top-level router (`backend/app/api/endpoints/webhooks.py`), mounted at prefix `/webhooks` in `app/main.py`. It sits outside `/billing` because it is not a Stripe event; future inbound webhooks from other vendors land in the same router file.

**No auth middleware on this route.** Signature-based instead. Add `/webhooks/*` to whatever public-path list `AuthMiddleware` consults (mirror how `/billing/webhook` is exempted).

### Signature verification

HMAC-SHA256 of the raw request body, hex-encoded, compared to the `X-Loops-Signature` header via `hmac.compare_digest`. Secret comes from a new setting:

```python
loops_webhook_secret: str = ""
```

Behavior:

- Secret unset → `503 {"detail": "Loops webhook is not configured"}`. App boots either way (matches Stripe pattern).
- Header missing or comparison fails → `400 {"detail": "Invalid signature"}`. Verification log entry at WARNING.
- Signature OK → proceed.

### Request body

```python
class LoopsNotificationPayload(BaseModel):
    user_email: EmailStr
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    link_url: Optional[HttpUrl] = None
    category: Optional[str] = Field(default=None, max_length=64)
    loops_message_id: Optional[str] = Field(default=None, max_length=128)
```

- Pydantic v2; `model_config = ConfigDict(extra="forbid")` so Loops misconfiguration surfaces as 422.
- `HttpUrl` only accepts `http`/`https` schemes. We additionally gate to an allowlist (own origin + Loops domain) inside the resolver to avoid open-redirect risk; see "Deep-link routing" below.

### Idempotency

New table:

```python
class LoopsEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "loops_events"
    loops_message_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
```

When `loops_message_id` is present:

1. `INSERT INTO loops_events (loops_message_id, user_id) VALUES (...) ON CONFLICT (loops_message_id) DO NOTHING RETURNING id`.
2. If RETURNING returns a row → insert the notification.
3. If RETURNING is empty → already processed, return `200` with no notification insert.

When `loops_message_id` is absent → no dedupe, best-effort. The spec calls this out as an "if Loops includes a message ID" feature.

### User lookup

```python
result = await db.execute(select(User).where(User.email == payload.user_email))
user = result.scalar_one_or_none()
if user is None:
    raise HTTPException(404, "User not found")
```

No fuzzy match. No org disambiguation — user is global.

### Notification insertion

The existing `send_notification(...)` requires a `template_fn` registered for the event type and emits to outbound channels. Neither fits here:

- Loops already sent the email upstream — re-emitting to EMAIL channels would double-send.
- Loops provides ready-made copy; a template that just echoes context is pure ceremony.

Solution: **new sibling helper** in `services/core/notifications/external.py`:

```python
async def insert_external_notification(
    *,
    user_id: UUID,
    title: str,
    body: str,
    link_url: Optional[str] = None,
    category: Optional[str] = None,
) -> Notification:
    """Insert a single in-app notification from an external source (Loops, etc).
    No template lookup, no channel dispatch. Opens its own AsyncSessionLocal
    so it's safe from BackgroundTasks contexts.
    """
```

Inserts directly with:

- `event_type = NotificationEventType.LIFECYCLE`
- `entity_type = "lifecycle"`
- `entity_id = user_id` (synthetic; the notification is user-scoped, not entity-scoped)
- `title`, `message = body`
- `payload = {"link_url": link_url, "category": category}` (omit keys with None values to stay tidy)

Add new enum value:

```python
class NotificationEventType(str, Enum):
    # ... existing values ...
    LIFECYCLE = "LIFECYCLE"
```

### Deep-link routing

Extend `services/core/notifications/links.py` to honor `payload.link_url` when `entity_type == "lifecycle"`. URL validation runs at *resolve* time as defense-in-depth (input validation already restricts to http/https):

- Allowed: same-origin (no host or starts with `/`), or hostname in `{settings.app_host, "app.loops.so"}` (configurable later — start with the host the app is mounted at).
- Rejected → fall back to a bare `/notifications` link so the user can still see the entry.

Per `.claude/rules/backend-services.md`, `NotificationResponse` continues to surface the resolved URL, not the raw payload. The resolver is the only place that touches `link_url`.

### Endpoint sketch

```python
@router.post("/loops/notification", status_code=200)
async def loops_notification_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.loops_webhook_secret:
        raise HTTPException(503, "Loops webhook is not configured")

    raw = await request.body()
    sig = request.headers.get("X-Loops-Signature", "")
    expected = hmac.new(
        settings.loops_webhook_secret.encode(),
        raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("Loops webhook signature verification failed")
        raise HTTPException(400, "Invalid signature")

    try:
        payload = LoopsNotificationPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors())

    user = (await db.execute(
        select(User).where(User.email == payload.user_email)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")

    if payload.loops_message_id:
        stmt = (
            insert(LoopsEvent)
            .values(loops_message_id=payload.loops_message_id, user_id=user.id)
            .on_conflict_do_nothing(index_elements=["loops_message_id"])
            .returning(LoopsEvent.id)
        )
        inserted = (await db.execute(stmt)).scalar_one_or_none()
        if inserted is None:
            await db.commit()
            return {"received": True, "deduped": True}
        await db.commit()

    await insert_external_notification(
        user_id=user.id,
        title=payload.title,
        body=payload.body,
        link_url=str(payload.link_url) if payload.link_url else None,
        category=payload.category,
    )
    return {"received": True}
```

### Tests

Mirror `backend/tests/unit/api/` patterns (or create the file if absent):

- `test_loops_webhook_unconfigured_503` — secret unset.
- `test_loops_webhook_bad_signature_400`.
- `test_loops_webhook_missing_user_404`.
- `test_loops_webhook_creates_notification_200` — verify row inserted, payload populated.
- `test_loops_webhook_idempotent` — fire twice with same `loops_message_id`, assert exactly one notification.
- `test_loops_webhook_invalid_body_422`.
- `test_insert_external_notification` — unit test for the helper.
- `test_resolve_link_url_for_lifecycle` — same-origin pass, foreign-host reject, malformed reject.

### Docs

Append section "Inbound: Loops → in-app NotificationBell" to `docs/loops-campaigns.md` covering:

- Endpoint URL.
- Payload schema (one example body, one curl).
- How to compute `X-Loops-Signature` in a Loops "Send Webhook" step.
- The setting `BATCHRITE_LOOPS_WEBHOOK_SECRET`.
- The fact that `loops_message_id` enables idempotency under Loops retries.

---

## Part 2 — Global subscription banner

### Component

`frontend/src/lib/components/layout/SubscriptionBanner.svelte` — new file, per `.claude/rules/conventions.md` (`layout/` is the bucket for global app chrome).

Renders one of three banner variants, chosen by priority (only one shows at a time):

1. **Locked-out** — `subscription.state.is_locked_out === true`. Red surface. Copy: *"Your subscription is not active. Reads and exports remain available, but new changes are blocked."* CTA: `Re-subscribe` → `openPortal()`. **Not dismissible.**
2. **Cancel-at-period-end** — `subscription.state.cancel_at_period_end === true`. Amber surface. Copy: *"Your subscription will end on {date}."* CTA: `Manage billing` → `openPortal()`. Date formatted from `current_period_end` (ISO string) via `Intl.DateTimeFormat`. **Not dismissible.**
3. **Trial countdown** — `subscription.state.days_remaining_in_trial != null && days <= 14`. Escalating surface and copy:
   - `14–8` → blue surface, *"Your trial ends in {N} days. Add a payment method to keep access."*
   - `7–4` → amber surface, *"Only {N} days left in your trial. Add a payment method to avoid interruption."*
   - `3` → amber-red surface, *"Your trial ends in 3 days. Add a payment method now."*
   - `2` → amber-red, *"Your trial ends in 2 days. Add a payment method now."*
   - `1` → red, *"Your trial ends tomorrow. Add a payment method now."*
   - `0` → red, *"Your trial ends today."*

   CTA: `Add payment method` → `openPortal()`. **Dismissible** via a `×` button. Dismissal stores `"true"` at sessionStorage key `subscription-banner-dismissed-trial`. Clearing the key on a state transition (e.g. cancel_at_period_end newly becoming true) isn't needed because higher-priority states bypass the dismissal check entirely.

Negative `days_remaining_in_trial` should never appear, but if it does the banner renders the `0` copy as a defensive fallback.

### Layout integration

Render in `+layout.svelte` below the existing `ConnectivityBanner`:

```svelte
{#if showNav}
    {#if OFFLINE_ENABLED}
        <ConnectivityBanner />
    {/if}
    <SubscriptionBanner />
{/if}
```

The existing `showNav` derived already evaluates to `!isPublicRoute && !isFieldMode && isAuthenticated() && pathname !== '/legal/accept'`. `PUBLIC_ROUTES` (`/login`, `/register`, `/check-email`, `/legal/*`) is the project's source of truth for unauthenticated pages — gating on `showNav` honors the spec's "hidden on /auth/* routes" intent while staying consistent with the rest of the app.

### Subscription store integration

The store at `frontend/src/lib/stores/subscription.svelte.ts` exposes everything we need: `state.is_locked_out`, `state.cancel_at_period_end`, `state.days_remaining_in_trial`, `state.current_period_end`. The banner imports `subscription` (reactive accessor) and `openPortal` (CTA action) directly. No new store APIs.

`subscription.state` is `null` until `loadSubscription()` is called. The banner renders nothing while `state === null` — `+layout.svelte` already invokes `loadSubscription` on auth; nothing additional needed here.

### Interplay with `SubscriptionLockoutModal`

`SubscriptionLockoutModal` is an interrupt: it pops only when a *write* hits the lockout. The banner is the always-on awareness. Both can co-exist. When locked out:

- Reading → banner only (modal stays closed).
- Attempting to write → modal opens on top; banner stays underneath.

This is the desired UX — the banner reminds the user they're locked out *before* they hit a write and trip the modal.

### Tests

`frontend/src/lib/components/layout/SubscriptionBanner.test.ts` (Vitest + @testing-library/svelte). One test per state and one per copy threshold:

- locked_out → renders red banner, no dismiss button.
- cancel_at_period_end → renders amber, no dismiss button, formatted date.
- trial 14, 8 → blue copy "ends in N days".
- trial 7, 4 → amber copy "Only N days left".
- trial 3, 2 → amber-red "ends in N days now".
- trial 1 → red "tomorrow".
- trial 0 → red "today".
- trial dismiss → sessionStorage written, banner unmounts; remount with sessionStorage set → still hidden.
- locked_out takes priority over trial countdown when both are present.
- days_remaining_in_trial null with no other state → no banner.
- `state === null` → no banner.

Mock the store by stubbing the `subscription.state` getter; no need to mock `loadSubscription`.

---

## Files touched

**Backend (new):**
- `backend/app/api/endpoints/webhooks.py`
- `backend/app/models/lifecycle.py` (new sibling file; `LoopsEvent` model lives here, parallel to `billing.py:StripeEvent`)
- `backend/app/services/core/notifications/external.py`
- `backend/alembic/versions/<auto>_add_loops_events.py`
- `backend/tests/unit/api/test_loops_webhook.py`
- `backend/tests/unit/services/test_external_notification.py`

**Backend (edits):**
- `backend/app/core/config.py` — add `loops_webhook_secret: str = ""`.
- `backend/app/models/notifications.py` — add `LIFECYCLE` enum value.
- `backend/app/services/core/notifications/links.py` — honor `payload.link_url` for `entity_type == "lifecycle"` with allowlist validation.
- `backend/app/main.py` — `app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])`.
- `backend/app/middleware/auth.py` (or wherever `AuthMiddleware` lives) — exempt `/webhooks/*` from auth.
- `docs/loops-campaigns.md` — append Inbound section.

**Frontend (new):**
- `frontend/src/lib/components/layout/SubscriptionBanner.svelte`
- `frontend/src/lib/components/layout/SubscriptionBanner.test.ts`

**Frontend (edits):**
- `frontend/src/routes/+layout.svelte` — render `<SubscriptionBanner />` below `<ConnectivityBanner />`.

---

## Settings & flags

| Setting | Default | Purpose |
| --- | --- | --- |
| `BATCHRITE_LOOPS_WEBHOOK_SECRET` | `""` | HMAC secret. Endpoint 503s when empty. |

Update root `CLAUDE.md` to mention `BATCHRITE_LOOPS_WEBHOOK_SECRET` alongside the existing `BATCHRITE_NOTIFICATION_EMAIL_ENABLED` env-var note.

---

## Out of scope

- Outbound channels for lifecycle notifications (Slack/Teams/Discord). Loops already sent the email; the bell is the only side effect.
- Loops sender logic in our app (still Loops' job).
- Grouping/digest of lifecycle entries in the bell — list them flat like any other event type.
- A second banner slot for non-billing announcements; if needed later, generalize then.

---

## Risks & open questions

- **Open-redirect risk on `link_url`.** Mitigated by Pydantic `HttpUrl` plus an origin allowlist in the resolver. If a future Loops campaign needs to link to a third-party site, the allowlist gains an entry — explicit, not silent.
- **Email enumeration via 404.** A bad actor with the webhook secret could probe `user_email` to enumerate registered users. Acceptable because the secret is private; if it leaks, that's a bigger problem. Constant-time treatment isn't worth it here.
- **Banner placement on mobile.** `ConnectivityBanner` is the precedent; the trial banner should match its responsive behavior. Verify in QA.
- **Multi-org users.** The notification is user-scoped, so the bell shows it regardless of which org the user is currently in. That's the desired behavior — trial reminders are personal.
