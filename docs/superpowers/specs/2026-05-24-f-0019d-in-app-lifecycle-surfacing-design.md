# F-0019d — In-App Lifecycle Surfacing (Loops webhook + Trial banner) — Design

**Status:** Hardened after review panel
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

`POST /webhooks/loops/notification` — new router file `backend/app/api/endpoints/webhooks.py`, mounted at prefix `/webhooks` in `app/main.py`. Future inbound webhooks from other vendors land in the same router file.

### AuthMiddleware exemption

`backend/app/core/middleware.py` uses exact-string matching against `PUBLIC_PATHS` plus a few `startswith` prefixes. Add the exact path to `PUBLIC_PATHS`:

```python
PUBLIC_PATHS = {
    ...,
    "/billing/webhook",
    "/webhooks/loops/notification",   # F-0019d
}
```

**Deliberately exact-match, not a prefix.** A `startswith("/webhooks/")` exemption would auto-exempt every future route under `/webhooks/*`, including any dev/admin endpoint someone adds later without realizing. Each new inbound webhook adds its own exact entry. (One-line cost, no foot-gun.)

### HMAC verification helper

Extract a small helper instead of inlining verification — adversarial review noted this is the third occurrence of `hmac.new(..., sha256).hexdigest()` in the codebase:

```python
# backend/app/core/webhook_auth.py
import hmac, hashlib
def verify_hmac_sha256(raw_body: bytes, header_value: str, secret: str) -> bool:
    """Constant-time compare hex digest. Strips a leading "sha256=" prefix
    if present (some providers, e.g. GitHub, send `sha256=<hex>`). Lower-
    cases both sides to absorb provider-side casing drift."""
    if not header_value or not secret:
        return False
    candidate = header_value.lower().removeprefix("sha256=")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate, expected)
```

Unit-tested in isolation. Used by the Loops endpoint; future inbound webhooks reuse it.

### Settings

New entry in `Settings`:

```python
loops_webhook_secret: str = ""
```

Behavior:

- Secret unset → `503 {"detail": "Loops webhook is not configured"}`. App boots either way (matches Stripe pattern).
- Header missing or comparison fails → `400 {"detail": "Invalid signature"}`. Log WARNING with remote_addr + header-presence flag (no body content).
- Signature OK → proceed.

Add `BATCHRITE_LOOPS_WEBHOOK_SECRET` to the env-var table in root `CLAUDE.md` alongside the existing notification-related env vars.

### Body & size cap

Body is read raw, then validated:

```python
MAX_BODY_BYTES = 64 * 1024  # 64 KB; lifecycle payloads are tiny

raw = await request.body()
if len(raw) > MAX_BODY_BYTES:
    raise HTTPException(413, "Payload too large")

# IMPORTANT: do NOT refactor this to `payload: LoopsNotificationPayload`
# parameter — FastAPI would consume the body before we can hash it, and
# `await request.body()` would return b"" on the second read, silently
# bypassing signature verification. Raw-body-first, parse-second.
```

Schema:

```python
class LoopsNotificationPayload(BaseModel):
    user_email: EmailStr
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    # link_url capped to 300 chars so payload (link_url + category + JSON
    # overhead) fits inside notifications.payload's 512-byte CHECK. A
    # longer URL would trip the CHECK *after* loops_events committed —
    # see "Atomic transaction" below.
    link_url: Optional[HttpUrl] = Field(default=None, max_length=300)
    category: Optional[str] = Field(default=None, max_length=64)
    loops_message_id: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")
```

### Idempotency

New model in a new file `backend/app/models/lifecycle.py`:

```python
class LoopsEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "loops_events"
    __table_args__ = (
        # Composite unique: same loops_message_id can recur globally
        # without colliding with another user's record. Mitigates the
        # cross-user-collision scenario flagged in adversarial review.
        UniqueConstraint("loops_message_id", "user_id",
                         name="uq_loops_events_msg_user"),
        Index("ix_loops_events_msg_user", "loops_message_id", "user_id"),
    )
    loops_message_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
```

**Must add `from app.models.lifecycle import LoopsEvent` to `backend/app/db/base.py`**, otherwise Alembic autogenerate produces an empty migration.

When `loops_message_id` is present:

1. `INSERT INTO loops_events (...) VALUES (...) ON CONFLICT (loops_message_id, user_id) DO NOTHING RETURNING id`.
2. If RETURNING returns a row → continue to notification insert.
3. If RETURNING is empty → already processed; return `200` without re-inserting.

When `loops_message_id` is absent → no dedupe.

Retention: none, matching `stripe_events`. Growth is bounded by Loops campaign volume; revisit if it exceeds a few million rows.

### Atomic transaction

**Both the `loops_events` row and the `notifications` row must commit in a single transaction.** Adversarial + ops + db reviews all flagged the split-commit race: if the notification insert fails after `loops_events` committed (CHECK violation, DB hiccup), Loops retries dedupe to the dropped row and the user never receives the notification.

The endpoint passes its own `db` session into `insert_external_notification`:

```python
async def insert_external_notification(
    *,
    db: AsyncSession,         # caller's session; commit not called here
    user_id: UUID,
    title: str,
    body: str,
    link_url: Optional[str] = None,
    category: Optional[str] = None,
) -> Notification: ...
```

Helper inserts the `Notification` row + `db.flush()` only. The endpoint commits both writes together. (If a future producer needs the BackgroundTasks-safe variant, add a separate `insert_external_notification_async` that opens its own session — don't conflate the two contracts here.)

### User lookup

```python
async with timeout(5.0):
    result = await db.execute(
        select(User).where(User.email == payload.user_email)
    )
user = result.scalar_one_or_none()
if user is None:
    logger.info(
        "Loops webhook user not found: email=%s", _mask_email(payload.user_email),
    )
    raise HTTPException(404, "User not found")
```

`User.email` already has a unique index; no schema change needed. Wrapping in `asyncio.timeout(5.0)` bounds hang time under DB load.

**Enumeration mitigation:** keep the 404 (a leaked HMAC secret is the broader concern), but ensure logs mask the email (`u**@example.com`). If the secret is ever rotated, the oracle closes.

### Notification insertion

Existing `send_notification(...)` requires a `template_fn` and emits to outbound channels. Neither fits — Loops already sent the email upstream, and a template that echoes context is ceremony. **Sibling helper** in `services/core/notifications/external.py`:

```python
async def insert_external_notification(...) -> Notification:
    """Insert one in-app notification from an external source (Loops).
    Caller owns commit ordering. No template lookup, no channel dispatch.
    """
    payload_dict: dict[str, Any] = {}
    if link_url is not None:
        payload_dict["link_url"] = link_url
    if category is not None:
        payload_dict["category"] = category

    notif = Notification(
        user_id=user_id,
        event_type=NotificationEventType.LIFECYCLE.value,
        entity_type="lifecycle",
        entity_id=user_id,   # synthetic: notification is user-scoped
        title=title,
        message=body,
        payload=payload_dict,
    )
    db.add(notif)
    await db.flush()
    return notif
```

New enum value `LIFECYCLE` in `NotificationEventType` (`backend/app/models/notifications.py`).

### Required coupling-site edits (audit found these in addition to the obvious ones)

- **`backend/app/services/core/notifications/templates.py`** — `TEMPLATES` dict is checked for exact-set equality against the enum (`test_notifications.py:34–43`). Add `TEMPLATES["LIFECYCLE"]` returning a marker `TemplateResult` whose body simply echoes `context["title"]` / `context["body"]`. The path is dead in practice because the Loops webhook bypasses `send_notification`, but the entry keeps CI green and documents the intent.
- **`backend/app/services/core/notifications/policy.py`** — `DEFAULT_POLICY` is checked for exact-set equality against the enum (`test_notification_policy.py:7–15`) and is iterated by the per-user subscription provisioner (`provisioning.py:88`). Add `DEFAULT_POLICY[NotificationEventType.LIFECYCLE] = DeliveryPolicy(in_app=False, email=False)` — the in-app row is created directly by the webhook, not via the subscription system, and outbound email is owned by Loops.
- **`frontend/src/lib/notifications.ts`** — `EVENT_ICONS` and `EVENT_TONES` fall back to `Bell` / muted for unknown event types. Add a `LIFECYCLE` entry: icon `CreditCard` (lucide-svelte), tone `amber`. The bell already handles unknown types gracefully so this is a polish/discoverability fix, not a bug.

### Deep-link routing

Extend `services/core/notifications/links.py` to honor `payload.link_url` for `entity_type == "lifecycle"`.

**The new branch runs *before* the `_ROUTABLE` short-circuit at line 68**, because lifecycle has no DB entity to look up.

Allowlist is **same-origin path-only**: `link_url` must start with `/` and not start with `//` (which would let through protocol-relative URLs). Reject anything else; fall back to a bare `/notifications` link. This removes the `settings.app_host` dependency entirely (the setting doesn't exist today and adding it just for the allowlist is overkill).

Rejecting cross-origin links — including `app.loops.so` — is the conservative v1: bell entries deep-link inside our app or nowhere. If a future campaign needs a third-party link, widen the allowlist deliberately at that point.

`NotificationResponse` continues to surface only the resolved URL; raw payload stays server-side (`.claude/rules/backend-services.md`).

### Endpoint sketch (final)

```python
@router.post("/loops/notification", status_code=200)
async def loops_notification_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.loops_webhook_secret:
        raise HTTPException(503, "Loops webhook is not configured")

    raw = await request.body()           # raw-body-first; do NOT refactor
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Payload too large")

    sig = request.headers.get("X-Loops-Signature", "")
    if not verify_hmac_sha256(raw, sig, settings.loops_webhook_secret):
        logger.warning(
            "Loops webhook signature failed: ip=%s sig_present=%s",
            request.client.host if request.client else "?",
            bool(sig),
        )
        raise HTTPException(400, "Invalid signature")

    try:
        payload = LoopsNotificationPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors())

    async with asyncio.timeout(5.0):
        user = (await db.execute(
            select(User).where(User.email == payload.user_email)
        )).scalar_one_or_none()
    if user is None:
        logger.info(
            "Loops webhook user not found: email=%s",
            _mask_email(payload.user_email),
        )
        raise HTTPException(404, "User not found")

    if payload.loops_message_id:
        stmt = (
            pg_insert(LoopsEvent)
            .values(loops_message_id=payload.loops_message_id, user_id=user.id)
            .on_conflict_do_nothing(constraint="uq_loops_events_msg_user")
            .returning(LoopsEvent.id)
        )
        inserted = (await db.execute(stmt)).scalar_one_or_none()
        if inserted is None:
            await db.commit()
            logger.info(
                "Loops webhook deduped: message_id=%s user_id=%s",
                payload.loops_message_id, user.id,
            )
            return {"received": True, "deduped": True}

    try:
        await insert_external_notification(
            db=db,
            user_id=user.id,
            title=payload.title,
            body=payload.body,
            link_url=str(payload.link_url) if payload.link_url else None,
            category=payload.category,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Loops webhook notification insert failed: user_id=%s message_id=%s",
            user.id, payload.loops_message_id,
        )
        raise HTTPException(500, "Notification insert failed")

    return {"received": True}
```

### Tests

- `test_loops_webhook_unconfigured_503`
- `test_loops_webhook_bad_signature_400`
- `test_loops_webhook_missing_user_404` — assert logger.info call masks email
- `test_loops_webhook_oversize_body_413`
- `test_loops_webhook_invalid_body_422`
- `test_loops_webhook_creates_notification_200` — assert row inserted, payload populated, single transaction (no orphan loops_events row)
- `test_loops_webhook_idempotent` — fire twice with same `(loops_message_id, user_id)`, assert exactly one notification
- `test_loops_webhook_concurrent_duplicates` — two requests in flight (`asyncio.gather`) with same `(message_id, user_id)`, assert exactly one notification
- `test_loops_webhook_message_id_collision_different_users` — same `loops_message_id`, two different users → both notifications created (composite uniqueness)
- `test_loops_webhook_uppercase_signature` — header sent as `SHA256=ABC...` (Loops casing drift), still verifies
- `test_loops_webhook_link_url_too_long_422`
- `test_loops_webhook_payload_check_violation_rolls_back` — force-craft a notification payload that overflows 512 B; assert both `loops_events` and `notifications` are rolled back
- `test_insert_external_notification_caller_owns_commit` — unit test for the helper
- `test_resolve_link_url_for_lifecycle_same_origin_pass`
- `test_resolve_link_url_for_lifecycle_external_host_reject`
- `test_resolve_link_url_for_lifecycle_protocol_relative_reject` (`//evil.com/path`)
- `test_verify_hmac_sha256_helper` — covers prefix-stripping, casing, empty inputs

### Docs

Append to `docs/loops-campaigns.md`:

1. Endpoint URL + payload schema + curl example.
2. `X-Loops-Signature` computation (bare hex of HMAC-SHA256(body, secret), lowercase). Note: helper also accepts `sha256=<hex>` and uppercase.
3. `BATCHRITE_LOOPS_WEBHOOK_SECRET` configuration + rotation procedure: (a) generate new secret in Loops; (b) set env var; (c) redeploy; (d) revoke old secret in Loops UI. Brief downtime window of 400s during rotation is expected.
4. `loops_message_id` enables idempotency; recommend including a stable per-message UUID.

---

## Part 2 — Global subscription banner

### Component

`frontend/src/lib/components/layout/SubscriptionBanner.svelte` — per `.claude/rules/conventions.md` (`layout/` is the bucket for global app chrome).

Renders one of three banner variants, chosen by priority (only one shows at a time):

1. **Locked-out** — `subscription.state.is_locked_out === true`.
   - Surface: `bg-red-500 text-white` (matches existing red banners).
   - Copy: *"Your subscription is not active. Reads and exports remain available, but new changes are blocked."*
   - CTA label: **"Manage billing"** (covers both `canceled` and `past_due`; UX review flagged that "Re-subscribe" misframes past-due as canceled). Action: `openPortal()`.
   - **Not dismissible.**

2. **Cancel-at-period-end** — `subscription.state.cancel_at_period_end === true`.
   - Surface: `bg-amber-500 text-white`.
   - Copy: *"Subscription ends {Mon D}."* (active voice; punchier than the spec's first draft).
   - Date formatted via `Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })` from `current_period_end`.
   - CTA: **"Manage billing"** → `openPortal()`.
   - **Not dismissible.**

3. **Trial countdown** — `subscription.state.days_remaining_in_trial != null && days <= 14`.

   Two visual registers (informational vs urgent — UX review collapsed the undefined "amber-red" intermediate tier):

   | Days | Surface | Copy |
   | --- | --- | --- |
   | 14–8 | `bg-blue-50 border-b border-blue-200 text-blue-900` (soft, matches BillingTab "trialing" badge) | *"Trial ends {Mon D}. Add a payment method when ready."* (absolute date — softer than countdown at this range) |
   | 7–4 | `bg-amber-500 text-white` | *"Trial ends {Mon D} — add a payment method to continue without interruption."* |
   | 3 | `bg-amber-500 text-white` | *"Trial ends in 3 days. Add a payment method."* |
   | 2 | `bg-red-500 text-white` | *"Trial ends in 2 days. Add a payment method."* |
   | 1 | `bg-red-500 text-white` | *"Trial ends tomorrow. Add a payment method."* |
   | 0 | `bg-red-500 text-white` | *"Trial ends at midnight tonight. Add a payment method to maintain access."* |
   | <0 (defensive) | `bg-red-500 text-white` | render same as `0` |

   CTA: **"Add payment method"** → `openPortal()`.

   **Dismissible** via a `<Button variant="ghost" size="icon-sm">` wrapping `<X />` from lucide-svelte (matches `ExpiryWarningBanner`). Dismissal stored at `localStorage["subscription-banner-dismissed-trial-YYYY-MM-DD"] = "true"` — a daily key so:

   - Dismissed banner stays dismissed across reloads *today*.
   - Reappears tomorrow without manual cleanup (different key, no entry).
   - Tier-escalation (e.g. day 8 → day 7) crosses a date boundary on the natural calendar; since today's dismiss key only suppresses *today*, the new tier shows next time.

   On auth state change (logout) the banner component clears all `subscription-banner-dismissed-*` keys from localStorage to prevent leakage across user switches in the same browser.

   Higher-priority banner states bypass the dismissal check entirely (a locked-out user always sees the locked-out banner regardless of prior trial dismissal).

### Subscription store integration

The store at `frontend/src/lib/stores/subscription.svelte.ts` exposes everything we need: `state.is_locked_out`, `state.cancel_at_period_end`, `state.days_remaining_in_trial`, `state.current_period_end`. The banner imports `subscription` (reactive accessor) and `openPortal` directly.

**Reload on focus.** Adversarial review flagged that the store goes stale after a Stripe portal redirect — user toggles cancel-at-period-end, returns to the tab, store still says trial. Add a `visibilitychange` listener (in the banner's `$effect` or in the existing subscription store init) that calls `loadSubscription()` on tab-refocus. Throttle to once per minute to avoid hammering on rapid tab-flipping.

`subscription.state === null` → banner renders nothing (no skeleton — `+layout.svelte` already gates `showNav` on `isAuthenticated()`, so a null state during initial load is brief and inside the auth-loading shell).

### Layout integration

```svelte
{#if showNav}
    {#if OFFLINE_ENABLED}
        <ConnectivityBanner />
    {/if}
    <SubscriptionBanner />
{/if}
```

The existing `showNav` derived (`!isPublicRoute && !isFieldMode && isAuthenticated() && pathname !== '/legal/accept'`) honors the spec's "hidden on /auth/* routes" intent. `PUBLIC_ROUTES` (`/login`, `/register`, `/check-email`, `/legal/*`) is the project's source of truth for unauthenticated pages.

### Interplay with `SubscriptionLockoutModal`

Modal is the interrupt on write attempts; banner is always-on ambient awareness. Both can co-exist. When locked out:

- Reading → banner only.
- Attempting to write → modal opens on top.

UX review validated this. The modal's "Dismiss and continue reading" already gives a locked-out user the escape hatch; the banner stays as ambient reminder.

### Tests (Vitest + @testing-library/svelte)

`frontend/src/lib/components/layout/SubscriptionBanner.test.ts`:

- Each of the three states (locked-out / cancel-at-period-end / trial countdown) renders correctly.
- Each copy threshold (14, 8, 7, 4, 3, 2, 1, 0).
- Locked-out priority over trial countdown when both are set.
- `state === null` → no banner.
- `days_remaining_in_trial === null` and no other state → no banner.
- Defensive negative `days_remaining_in_trial` → renders `0` copy.
- Trial dismiss writes the daily localStorage key; remount with key set → banner hidden.
- Dismiss key from yesterday → banner shows (today is a new key).
- Logout clears all `subscription-banner-dismissed-*` keys.
- Visibility-change refresh path calls `loadSubscription()`.

Mock the store by stubbing the `subscription.state` getter; no need to mock `loadSubscription`.

---

## Files touched

**Backend (new):**
- `backend/app/api/endpoints/webhooks.py`
- `backend/app/core/webhook_auth.py` (HMAC helper)
- `backend/app/models/lifecycle.py` (`LoopsEvent`)
- `backend/app/services/core/notifications/external.py` (`insert_external_notification`)
- `backend/alembic/versions/<auto>_add_loops_events.py`
- `backend/tests/unit/api/test_loops_webhook.py`
- `backend/tests/unit/core/test_webhook_auth.py`
- `backend/tests/unit/services/test_external_notification.py`

**Backend (edits):**
- `backend/app/core/config.py` — `loops_webhook_secret: str = ""`
- `backend/app/core/middleware.py` — add `"/webhooks/loops/notification"` to `PUBLIC_PATHS`
- `backend/app/db/base.py` — `from app.models.lifecycle import LoopsEvent`
- `backend/app/main.py` — `app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])`
- `backend/app/models/notifications.py` — add `LIFECYCLE` enum value
- `backend/app/services/core/notifications/links.py` — lifecycle branch with same-origin allowlist, runs before `_ROUTABLE` short-circuit
- `backend/app/services/core/notifications/templates.py` — `TEMPLATES["LIFECYCLE"]` stub entry
- `backend/app/services/core/notifications/policy.py` — `DEFAULT_POLICY[LIFECYCLE] = DeliveryPolicy(in_app=False, email=False)`
- `docs/loops-campaigns.md` — append Inbound section with curl + rotation procedure

**Frontend (new):**
- `frontend/src/lib/components/layout/SubscriptionBanner.svelte`
- `frontend/src/lib/components/layout/SubscriptionBanner.test.ts`

**Frontend (edits):**
- `frontend/src/lib/notifications.ts` — `EVENT_ICONS.LIFECYCLE = CreditCard`, `EVENT_TONES.LIFECYCLE = "amber"`
- `frontend/src/lib/stores/subscription.svelte.ts` — visibility-change reload (throttled)
- `frontend/src/routes/+layout.svelte` — render `<SubscriptionBanner />` below `<ConnectivityBanner />`
- `CLAUDE.md` — add `BATCHRITE_LOOPS_WEBHOOK_SECRET` to env-var section

---

## Out of scope (this task)

- **Per-IP rate limit on `/webhooks/loops/notification`.** Ops review wanted it; existing `RateLimitService` is chat-scoped only. Tracked as a TD follow-up: "TD-XXXX: app-wide HTTP rate limiter for webhook routes." For now, the HMAC gate + Loops' own delivery rate is the protection.
- Outbound channels for lifecycle notifications (Slack/Teams/Discord). Loops already sent the email; the bell is the only side effect.
- Loops sender logic in our app (still Loops' job).
- Grouping/digest of lifecycle entries in the bell — list them flat like any other event type.
- A second banner slot for non-billing announcements; if needed later, generalize then.
- Generalizing `ConnectivityBanner` / `SubscriptionBanner` / `ExpiryWarningBanner` into a shared `<Banner variant=...>` primitive — three call sites, very different chrome; not worth the abstraction yet.

---

## Residual risks

- **Misconfigured Loops workflow loop** firing hundreds of webhook calls — un-rate-limited. Acceptable for v1; the DB writes are tiny and the HMAC gate keeps unauthenticated traffic out. Monitor `loops_events` row growth as the canary.
- **Secret leak** turns the 404 user-lookup into an enumeration oracle. Documented rotation procedure mitigates. Logs mask email so a stolen secret + log access doesn't compound.
- **HMAC format ambiguity:** the helper accepts bare hex, `sha256=`-prefixed, lowercase, or uppercase — covers known SaaS conventions. If Loops uses something exotic (base64, JWT-style), tests will surface it before prod.
