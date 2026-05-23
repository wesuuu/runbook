# TD-0091c — Notification Delivery Model (sequenced email & cleanup)

**Date:** 2026-05-22
**ClickUp:** TD-0091c (`86e1g9zm3`), subtask of TD-0091 — 2026-05-21 in-app notification system QA audit
**Type:** Tech debt — delivery-orchestration gaps

## Summary

The 2026-05-21 notification audit found that Batchrite has no notion of
"send an in-app notification + an email together for a standard event."
`send_notification` always writes an in-app `Notification` row, but email
only fires if the recipient has personally created an `EMAIL` channel and
subscribed it to that event — out of the box, nobody receives email for
anything. Invitations bypass the notification system entirely (direct
`email_service.send_invitation_email`) and produce no paired in-app row.
Five event types in the enum have zero emit call sites. The
`require_active_subscription()` dependency is applied inconsistently on
read endpoints.

This spec covers all three groups of fixes. Provider plumbing
(unifying `EmailChannel` with `EmailService`) is **out of scope** —
that work lives in TD-0062.

## Goals

1. Standard events (invites, run started, role assigned, approvals,
   role unassigned) deliver in-app + email **by default** for every
   recipient, without each user having to hand-configure a channel.
2. Users can opt out of email per event through the existing
   channel-subscriptions UI (no parallel preferences surface).
3. Five dead event types are either wired to a real producer or
   removed from the enum.
4. Subscription gating across notification endpoints is consistent
   and defensible.

## Non-goals

- Provider unification (`EmailService` ↔ `EmailChannel`) — TD-0062.
- Org-level EMAIL channel broadcast targeting — pre-existing bug, no
  producer asks for it; left untouched.
- Admin-configurable delivery policy editor.
- Re-introducing `OFFLINE_VALUE_DISCREPANCY` — waits for an offline
  reconciliation feature that produces it.
- Real-time email push, per-org overrides, digest batching.

## Architecture overview

Three independent pieces, layered on the existing model:

1. A **per-event delivery policy** in code — single source of truth
   for "what does Batchrite send by default."
2. An **auto-provisioned personal EMAIL channel** for every user
   (new + existing), pre-subscribed to default-email events. The
   existing `notification_channels` + `notification_subscriptions`
   tables *are* the preferences substrate — opt-out is just disabling
   a subscription. Provisioning hangs off a SQLAlchemy `after_insert`
   event on `User` so every user-creation path (register,
   accept-invitation, future OAuth/SSO) is covered identically.
3. **Producer wiring** for the four (of five) dead events with real
   surfaces, plus invite reroute.

A new `is_default` boolean on `NotificationChannel` distinguishes
backfilled / auto-provisioned rows from user-created ones, used by the
backfill downgrade and reserved for future "reset to defaults" flows.

## Detailed design

### 1. Delivery policy module

New file `backend/app/services/core/notifications/policy.py`:

```python
from dataclasses import dataclass
from app.models.notifications import NotificationEventType

@dataclass(frozen=True)
class DeliveryPolicy:
    in_app: bool = True
    email: bool = False

# Default policy: what channels each event fans to out of the box.
DEFAULT_POLICY: dict[str, DeliveryPolicy] = {
    NotificationEventType.RUN_STARTED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_ASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_REASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_UNASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.INVITE_SENT.value: DeliveryPolicy(True, True),
    NotificationEventType.INVITE_ACCEPTED.value: DeliveryPolicy(True, False),
    NotificationEventType.PROTOCOL_APPROVAL_REQUESTED.value: DeliveryPolicy(True, True),
    NotificationEventType.PROTOCOL_APPROVED.value: DeliveryPolicy(True, True),
    NotificationEventType.PROTOCOL_REVERTED.value: DeliveryPolicy(True, False),
    NotificationEventType.RUN_SIGNOFF_REQUESTED.value: DeliveryPolicy(True, True),
    NotificationEventType.RUN_SIGNOFF_CANCELLED.value: DeliveryPolicy(True, False),
    NotificationEventType.RUN_COMPLETED.value: DeliveryPolicy(True, False),
    NotificationEventType.STEP_DEVIATION.value: DeliveryPolicy(True, False),
    NotificationEventType.PENDING_IMAGE_ANALYSIS.value: DeliveryPolicy(True, False),
    NotificationEventType.OFFLINE_SYNC_PENDING.value: DeliveryPolicy(True, False),
}

def policy_for(event_type: str) -> DeliveryPolicy:
    return DEFAULT_POLICY.get(event_type, DeliveryPolicy())
```

The policy dict is exhaustive over `NotificationEventType` (after
removing `OFFLINE_VALUE_DISCREPANCY`); a unit test enforces that
membership.

**What policy drives:** the default-subscription seed set for new and
existing users (step 2 below). Once provisioned, dispatch is governed
by the rows in `notification_subscriptions` — the policy is not
consulted at dispatch time. This means a user who disables a default
sub stays opted out across restarts and is not "fixed up" silently.

### 2. Auto-provisioned user EMAIL channel

**Model change.** Add `is_default: bool` to `NotificationChannel`
(default `False`, `server_default='false'`, `nullable=False`).
Backfilled and auto-provisioned channels carry `is_default=True`;
user-created channels stay `False`. This replaces a fragile
`name='Email'` identity check on downgrade and gives future
"reset-to-defaults" flows an unambiguous selector.

**Unique partial index.** Add a unique partial index
`ix_notif_channel_user_email_unique` on `(user_id) WHERE
channel_type='EMAIL' AND user_id IS NOT NULL`. This prevents a race
between the backfill migration and concurrent register from creating
duplicate per-user EMAIL channels, and makes the dispatcher's
"resolve this user's email channel" lookup O(1).

New file `backend/app/services/core/notifications/provisioning.py`:

```python
async def ensure_default_user_channel(
    db: AsyncSession, user: User
) -> NotificationChannel:
    """Ensure the user has a default EMAIL channel + default subscriptions.

    Idempotent. Called from a SQLAlchemy after_insert event on User and
    from the backfill migration. Subscription set is policy-driven:
    any DEFAULT_POLICY entry with email=True yields a subscription row.
    """
```

Behavior:

- Look for any EMAIL channel where `user_id == user.id` (uses the new
  unique partial index). If absent, create one with `name="Email"`,
  `config={"to": user.email}`, `enabled=True`, `is_default=True`.
- For each event type in `DEFAULT_POLICY` with `email=True`, add a
  `NotificationSubscription(channel_id=..., event_type=..., enabled=True)`
  if not already present.
- Re-running the function is a no-op (existence checks on both rows).
- On `IntegrityError` from a concurrent insert losing the unique-index
  race, swallow and re-fetch; this keeps the function idempotent under
  concurrency.

**SQLAlchemy after_insert hook.** In `app/models/user.py`:

```python
from sqlalchemy import event

@event.listens_for(User, "after_insert")
def _schedule_default_channel(mapper, connection, target):
    connection.info.setdefault(
        "pending_default_channels", []
    ).append(target.id)
```

A FastAPI middleware (or end-of-request hook in `deps.get_db`) drains
`connection.info["pending_default_channels"]` after the user's
transaction commits and schedules `ensure_default_user_channel`
through `BackgroundTasks` so signup latency is unaffected. Provisioning
runs in its own transaction (own `AsyncSession`), matching the
existing background-task pattern in `services/core/notifications/`.

**Coverage.** This covers all current and future user-creation paths
(`auth.py:register`, accept-invitation if it goes through register,
admin invite, future OAuth/SSO) without per-call-site wiring.

**Why store `to` in config:** the dispatcher loop already knows the
recipient `user_id`; resolving `User.email` per send adds a query on
the hot path. Storing in `config.to` matches existing channel
conventions (slack/teams/webhook all keep their target in `config`).
Batchrite has no email-change endpoint today (verified via `grep`); if
one lands later, a one-line update to `config.to` at that site keeps
the channel in sync. (No pre-existing-channel fallback needed —
Batchrite has no production tenants yet, so every user's EMAIL channel
will be created with `config.to` populated by this work.)

### 3. Backfill migration

Alembic migration `backfill_default_notification_channels`. The
migration runs in three logical phases, all inside
`op.get_context().autocommit_block()` so each row commits
independently and large orgs don't sit on a long table-level lock.
The migration is preceded by a separate, fast migration that adds the
`is_default` column and the unique partial index (DDL stays in its
own migration so a failed backfill doesn't strand schema changes).

```sql
-- 1. Add is_default column and unique partial index (separate migration).
ALTER TABLE notification_channels
  ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX CONCURRENTLY ix_notif_channel_user_email_unique
  ON notification_channels (user_id)
  WHERE channel_type = 'EMAIL' AND user_id IS NOT NULL;

-- 2. Create the default EMAIL channel per user lacking one. is_default
-- = true marks rows owned by the backfill / auto-provisioning path.
INSERT INTO notification_channels
  (id, user_id, name, channel_type, config, enabled, is_default,
   created_at, updated_at)
SELECT
  gen_random_uuid(), u.id, 'Email', 'EMAIL',
  jsonb_build_object('to', u.email), true, true, now(), now()
FROM users u
WHERE NOT EXISTS (
  SELECT 1 FROM notification_channels c
  WHERE c.user_id = u.id AND c.channel_type = 'EMAIL'
)
ON CONFLICT DO NOTHING;  -- safety net for the unique partial index

-- 3. Seed default-email subscriptions on every per-user EMAIL channel.
INSERT INTO notification_subscriptions
  (id, channel_id, event_type, enabled, created_at, updated_at)
SELECT gen_random_uuid(), c.id, e.event_type, true, now(), now()
FROM notification_channels c
CROSS JOIN (VALUES
  ('RUN_STARTED'),
  ('ROLE_ASSIGNED'),
  ('ROLE_REASSIGNED'),
  ('ROLE_UNASSIGNED'),
  ('INVITE_SENT'),
  ('PROTOCOL_APPROVAL_REQUESTED'),
  ('PROTOCOL_APPROVED'),
  ('RUN_SIGNOFF_REQUESTED')
) AS e(event_type)
WHERE c.channel_type = 'EMAIL'
  AND c.user_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM notification_subscriptions s
    WHERE s.channel_id = c.id AND s.event_type = e.event_type
  );
```

`op.downgrade()` deletes channels with `is_default = TRUE` (cascading
subscriptions), drops the unique partial index, then drops the
`is_default` column. Using `is_default` instead of `name='Email'` means
a user renaming their channel doesn't break rollback.

The event-list literal is duplicated between the Python `DEFAULT_POLICY`
and the migration SQL — intentional, since Alembic migrations should
not import application code (which can drift). A unit test asserts
the migration's list matches the policy at the time of writing; future
policy edits do not require migration changes (new users will pick up
new defaults via `ensure_default_user_channel`).

### 4. User-signup hook (via SQLAlchemy event)

In `app/models/user.py`, register an `after_insert` event on `User`
that queues the user id on the connection's `info` dict. A FastAPI
dependency (or middleware) drains the queue after request commit and
schedules `ensure_default_user_channel(db, user)` via
`BackgroundTasks`, opening its own `AsyncSession`. This keeps signup
latency low and covers every user-creation path
(`auth.py:register`, accept-invitation, admin invite, future OAuth/SSO)
with no per-call-site wiring.

Sketch:

```python
# app/models/user.py
from sqlalchemy import event

@event.listens_for(User, "after_insert")
def _queue_default_channel(mapper, connection, target):
    connection.info.setdefault(
        "pending_default_channels", []
    ).append(target.id)

# app/core/deps.py (or middleware)
async def get_db(...) -> AsyncSession:
    async with session_factory() as session:
        try:
            yield session
        finally:
            pending = session.connection().info.get(
                "pending_default_channels", []
            )
            if pending:
                # Schedule via task_runner so provisioning doesn't
                # block the request response.
                runner = get_task_runner()
                for user_id in pending:
                    await runner.submit(
                        provision_default_channel_for_user(user_id)
                    )
```

`provision_default_channel_for_user` opens its own session (per the
background-task pattern in `.claude/rules/backend-services.md`),
re-fetches the user, and calls `ensure_default_user_channel`.

### 5. Dispatcher fix — recipient resolution + verified gate

`dispatcher._dispatch_to_channel` currently inherits the personal
message's `recipient=""` for every per-user channel. Fix scoped to the
existing per-user loop in `dispatch_event`:

```python
for user_id in recipients:
    user_channels = await _get_subscribed_channels(
        db, event_type, user_ids=[user_id]
    )
    for channel_model in user_channels:
        if channel_model.channel_type == "EMAIL":
            user = await _get_user_cached(db, user_id)
            if not user.email_verified:
                # Drop the email send; in-app row is already written.
                continue
        recipient = _resolve_personal_recipient(channel_model)
        msg = FormattedMessage(
            event_type=message_personal.event_type,
            title=message_personal.title,
            body=message_personal.body,
            recipient=recipient,
            url=message_personal.url,
        )
        ...
```

`_resolve_personal_recipient` returns `channel.config["to"]` for EMAIL
channels (authoritative — no `User.email` lookup), empty for
slack/teams/webhook (which route via their own `config`).

**Verified gate:** EmailChannel send is skipped when the recipient
user's `email_verified` is `False`. The in-app `Notification` row is
still written; the user picks up missed events the next time they
sign in and load the inbox. Once they verify, future dispatches go
through normally. A user cache scoped to `dispatch_event` (per-call
dict keyed by `user_id`) avoids re-fetching across multiple channels
or recipients.

**Batch subscription lookup.** `_get_subscribed_channels` is extended
to accept `user_ids: list[UUID]` (defaulting to `[user_id]` for the
single-recipient cases) and emits one `IN` query. Hot path for
`STEP_DEVIATION` where N run-role assignees fan out — this collapses
N queries into 1.

### 5b. EmailChannel changes

`backend/app/services/core/notifications/channels/email.py`:

- **SMTP timeout.** Pass `timeout=10` to `aiosmtplib.send(...)` so a
  stalled SMTP server can't hang the dispatcher fan-out. On
  `asyncio.TimeoutError`, record the delivery as FAILED with reason
  `"smtp_timeout"`.
- **List-Unsubscribe header.** Add
  `List-Unsubscribe: <https://{base_url}/settings/notifications>` and
  `List-Unsubscribe-Post: List-Unsubscribe=One-Click` to every
  outbound email. `base_url` comes from `settings.app_base_url`.
- **Footer link.** The plain-text and HTML email bodies gain a footer
  block: "You're receiving this because you're subscribed to
  {event_label}. Manage preferences: {base_url}/settings/notifications".
  Rendered once per send by a shared helper in
  `services/core/notifications/templates.py` so every template picks
  it up uniformly.

### 6. Invite handling

`iam.py:create_invitation` and `resend_invitation`:

```python
if invitation.invited_user_id is not None:
    background_tasks.add_task(
        send_notification, db, "INVITE_SENT", org_id, "organization",
        org.id, [invitation.invited_user_id],
        {
            "org_name": org.name,
            "invited_by": user.full_name or user.email,
            "accept_url": f"{settings.app_base_url}/invite/{invitation.token}",
            "expires_at": invitation.expires_at.isoformat(),
        },
    )
else:
    await send_invitation_email(...)  # existing direct path
```

The branch is mutually exclusive — no double-email. For
`invited_user_id is None`, the invite token URL in
`send_invitation_email` is the join path; the email is the only
notification the recipient can receive (they don't yet exist as a
user).

**INVITE_SENT template parity.** Existing-user invites previously got
the styled `send_invitation_email` template (CTA button, expiry
notice). The channel-pipeline route must preserve that for email
deliveries. In `templates.py:invite_sent`:

- HTML body renders the same accept-CTA button and "expires {date}"
  notice from `send_invitation_email` (extract the shared HTML
  fragment into `templates._invite_html(accept_url, expires_at)` so
  both paths render byte-identical markup).
- Plain-text body mirrors the existing text template.
- In-app body stays short ("You have a pending invite from {org}.").

`FormattedMessage.body` carries the in-app body; an optional
`html_body` field (added to the dataclass) carries the rich HTML for
EmailChannel. Other channel types ignore `html_body`.

`auth.py:accept_invitation` (around line 579), after status flips to
`ACCEPTED`:

```python
background_tasks.add_task(
    send_notification, db, "INVITE_ACCEPTED", org_id, "organization",
    org.id, [invitation.invited_by],
    {"org_name": org.name, "accepted_by": invited_user.full_name or invited_user.email},
)
```

### 7. Dead-event wiring

| Event | Producer site | Recipients |
| --- | --- | --- |
| ROLE_UNASSIGNED | `runs.py:delete_run_role_assignment` (line ~1411) | the removed user |
| INVITE_SENT | `iam.py:create_invitation` + `resend_invitation` (existing-user branch only) | invitee |
| INVITE_ACCEPTED | `auth.py:accept_invitation` | original inviter |
| STEP_DEVIATION | `runs.py:update_run`, EDITED-status branch (lines ~656–753) | run role assignees minus the actor; one notification per update, context = first deviated step name |
| OFFLINE_VALUE_DISCREPANCY | — | **deleted from enum + templates** (no producer surface in codebase) |

**STEP_DEVIATION recipient set:** existing run role assignments minus
the actor — but filtered through `check_permission(VIEW, run)`. Raw
`RunRoleAssignment` rows can include users whose permission was
revoked but whose role row wasn't cleaned up; check_permission is the
authoritative gate. Result is a small list (typically ≤5 per run), so
the per-user check is cheap. Pulling project-level recipients (PM,
study director) is left for a later iteration.

**STEP_DEVIATION emission count:** one notification per `update_run`
request, regardless of how many steps were edited in the request body.
Context carries the first edited step's name and a count of additional
deviations. This avoids spamming N notifications per save when an
operator bulk-edits values during a late correction.

### 8. Enum cleanup

In `app/models/notifications.py`:
- Remove `OFFLINE_VALUE_DISCREPANCY = "OFFLINE_VALUE_DISCREPANCY"` from
  `NotificationEventType`.

In `app/services/core/notifications/templates.py`:
- Remove `offline_value_discrepancy` function.
- Remove `"OFFLINE_VALUE_DISCREPANCY": offline_value_discrepancy,` from
  `TEMPLATES`.

Data migration is a no-op (no row in `notifications` carries that
event_type — confirmed by audit; if any drift exists in dev DBs, the
existing row stays but the template lookup is a `logger.warning` and
returns nothing, which is acceptable degradation).

### 9. Gating consistency

In `app/api/endpoints/notifications.py`:

- Remove `_: User = Depends(require_active_subscription())` from
  `mark_read` (line ~495) and `mark_all_read` (line ~513).
- `list_notifications` and `unread_count` already have no gating —
  leave as-is.
- Keep gating on: channel create/update/delete (org + me),
  subscription create/delete, channel test.

Rationale: read-only access (including dismissing notifications) does
not consume billable resources or configure infrastructure. Gating
write/configure actions only. Documented in `.claude/rules/backend-endpoints.md`
during the project-rules refresh step.

### 10. DRY refactor in `runs.py:update_run` (preparatory)

Before wiring STEP_DEVIATION, collapse the existing twin graph
traversals — `_node_map` (line ~652) and `_name_map` (line ~763) —
into a single `_index_steps(graph) -> StepIndex` helper that returns
both id→node and id→name lookups in one pass. STEP_DEVIATION needs
step-name resolution for context payloads; introducing a third
traversal would be the third repetition. Refactor first, emit second.

The helper lives in `app/services/runs/graph_index.py` and is unit-
tested independently of the endpoint.

## Tests

TDD order — write each in red first.

**Unit tests (`backend/tests/unit/`):**

1. `test_notification_policy.py`
   - `DEFAULT_POLICY` is exhaustive over `NotificationEventType` minus
     the removed `OFFLINE_VALUE_DISCREPANCY`.
   - `policy_for(event_type)` returns correct policy for known events.
   - `policy_for("UNKNOWN")` returns `DeliveryPolicy()` defaults.

2. `test_notification_provisioning.py`
   - New user → channel + N subscriptions created, `is_default=True`.
   - Re-call → no duplicate rows (idempotent).
   - Concurrent insert race: simulated `IntegrityError` is swallowed
     and existing channel returned.

3. `test_dispatcher_email_recipient.py`
   - User-level EMAIL channel with `config.to="x@y"` →
     `FormattedMessage.recipient == "x@y"` reaches `EmailChannel.send`.
   - User-level slack channel → recipient resolution untouched.

4. `test_dispatcher_email_verified_gate.py`
   - User with `email_verified=False` → EmailChannel send skipped,
     in-app Notification row still written.
   - Same user with `email_verified=True` → EmailChannel send proceeds.

5. `test_subscriptions_batch_lookup.py`
   - `_get_subscribed_channels(user_ids=[a, b, c])` returns channels
     for all three in one query (mocked counter on engine).

6. `test_migration_policy_alignment.py`
   - The migration's hard-coded event list matches the keys of
     `DEFAULT_POLICY` where `email=True` at the time the migration was
     written. Guards future policy drift from silently leaving the
     migration list stale.

7. `test_step_index.py`
   - `_index_steps(graph)` returns id→node and id→name maps in one pass.
   - Existing call sites in `update_run` switch to the helper without
     behavior change (regression coverage via existing run-update tests).

8. `test_email_channel_unsubscribe_header.py`
   - Outbound `aiosmtplib.send` call carries `List-Unsubscribe` and
     `List-Unsubscribe-Post` headers.
   - HTML body contains the manage-preferences URL.

9. `test_email_channel_smtp_timeout.py`
   - `aiosmtplib.send` patched to raise `asyncio.TimeoutError` →
     delivery recorded as FAILED with reason `"smtp_timeout"`, dispatcher
     loop continues.

**Integration tests (`backend/tests/integration/`):**

10. `test_register_provisions_channel.py`
    - `POST /auth/register` → user has 1 EMAIL channel + N subs (after
      background task drains).
    - `POST /auth/register` followed by acceptance of an invitation
      via the same path → still exactly 1 EMAIL channel for that user
      (unique partial index holds).

11. `test_after_insert_covers_invite_path.py`
    - Create a user via the `accept_invitation` flow (which creates a
      user record outside of `register`) → after_insert event still
      fires and channel is provisioned.

12. `test_invite_existing_user.py`
    - Invite to email matching existing user → in-app row exists for
      that user + one `NotificationDelivery` row marked SENT for their
      EMAIL channel. Direct `send_invitation_email` is not called
      (asserted by patching). HTML body contains the accept-CTA and
      expiry notice.

13. `test_invite_new_email.py`
    - Invite to email not matching any user → direct
      `send_invitation_email` called once, no Notification rows, no
      channel writes.

14. `test_invite_accepted.py`
    - Accept invitation → INVITE_ACCEPTED notification for the original
      inviter; delivery dispatched.

15. `test_role_unassigned_notification.py`
    - `DELETE /runs/{id}/role-assignments/{aid}` → ROLE_UNASSIGNED for
      the removed user.

16. `test_step_deviation_notification.py`
    - Run in EDITED status with step `results` change →
      STEP_DEVIATION for all assignees except the actor.
    - Multi-step edit → exactly one notification, context shows first
      step name + count.
    - Assignee whose VIEW permission was revoked is excluded from
      recipients even though the role row remains.

17. `test_notifications_gating.py`
    - Lapsed subscriber: `mark_read`, `mark_all_read`, `list`,
      `unread-count` all succeed.
    - Lapsed subscriber: `POST /channels/me` returns 402.
    - Lapsed subscriber: `POST /channels/{id}/subscriptions` returns
      402.

## Migration safety / rollout

- Migration is purely additive and idempotent.
- New default-on subscriptions: existing users will start receiving
  email for events they previously didn't. Communicated in the release
  notes; users can disable individual subs from the existing
  Settings → Notifications surface (already shipped in TD-0091b's
  predecessor work).
- Downgrade path: deletes channels with the auto-generated `name =
  'Email'`. Will not affect user-renamed channels.

## Open questions

None at this point — all design decisions converged in brainstorming
and the post-review-panel triage.

## Review notes (2026-05-22 spec review panel)

Dispatched in parallel: adversarial-risk-auditor, dry-reuse-auditor,
db-scalability-reviewer, production-ops-reviewer. Triaged with user.

**Accepted and folded into the spec:**

- **P0 (adversarial):** Gate email dispatch on `User.email_verified`
  to avoid spamming unverified addresses (§5).
- **P0 (adversarial):** Provision the default channel from a
  SQLAlchemy `after_insert` event on `User`, not at the register call
  site, so accept-invitation / future OAuth/SSO are covered (§4).
- **P0 (db):** Migration uses `op.get_context().autocommit_block()`,
  introduces a unique partial index on `(user_id) WHERE
  channel_type='EMAIL' AND user_id IS NOT NULL`, and an `is_default`
  boolean replaces the brittle `name='Email'` downgrade selector (§3).
- **HIGH (ops):** `List-Unsubscribe` header + footer manage-preferences
  link on every outbound email for CAN-SPAM/GDPR (§5b).
- **P1 (adversarial):** STEP_DEVIATION recipient filter uses
  `check_permission(VIEW, run)`, not raw role rows (§7).
- **P1 (db):** `_get_subscribed_channels` gains a batch form keyed by
  `user_ids` to collapse N round-trips on STEP_DEVIATION fan-out (§5).
- **P1 (db):** `ensure_default_user_channel` runs via `BackgroundTasks`
  so signup latency is unaffected (§4).
- **MEDIUM (ops):** INVITE_SENT email body keeps the styled CTA button
  and expiry notice when routed through the channel pipeline (§6).
- **MEDIUM (ops):** SMTP send carries `timeout=10` (§5b).
- **DRY:** Collapse `_node_map` + `_name_map` in `update_run` into a
  single `_index_steps` helper before STEP_DEVIATION emit lands (§10).

**Explicitly rejected:**

- Dispatcher fallback to `User.email` for legacy channels lacking
  `config.to`. Reason: Batchrite has no production tenants yet, so
  every per-user EMAIL channel will be created with `config.to`
  populated by this work — no legacy data to compensate for.
- Feature flag (`BATCHRITE_FEATURES__NOTIFICATION_EMAIL__ENABLED`).
  Reason: pre-production app, single rollout shot; complexity not
  warranted.
