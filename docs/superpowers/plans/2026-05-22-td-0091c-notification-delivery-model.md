# TD-0091c — Notification Delivery Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Batchrite send sequenced in-app + email for standard events out of the box, wire up four dead event types (delete the fifth), and make `require_active_subscription` gating consistent on the notifications API.

**Architecture:** Three independent layers on top of the existing notifications model — (1) a per-event delivery policy module, (2) an auto-provisioned per-user EMAIL channel created via a SQLAlchemy `after_insert` hook on `User` and seeded with default subscriptions, (3) producer wiring at the four dead-event call sites. EmailChannel gains an unsubscribe header, footer, and SMTP timeout; the dispatcher gains a `verified_email` gate and batch subscription lookup; invites route through the channel pipeline for existing users and stay direct for new emails.

**Tech Stack:** FastAPI async, SQLAlchemy 2.0 async/asyncpg, Alembic (with `autocommit_block` for the backfill), aiosmtplib, pytest.

**Spec:** `docs/superpowers/specs/2026-05-22-td-0091c-notification-delivery-model-design.md` (commit 69da77e).

**Phase ordering:** Phases 1-2 are independent. Phase 3 (model change + DDL migration) must land before Phase 4 (provisioning needs `is_default`). Phase 5 (backfill migration) needs Phase 3's DDL. Phase 6 (dispatcher) is independent of 3-5. Phase 7 (EmailChannel) is independent of all others. Phases 8-9 (producers) need Phases 2, 4, 6 in place. Phase 10 (enum cleanup) and Phase 11 (gating) are independent.

---

## Affected file map

**New files:**

- `backend/app/services/core/notifications/policy.py` — DEFAULT_POLICY, DeliveryPolicy, policy_for
- `backend/app/services/core/notifications/provisioning.py` — ensure_default_user_channel, provision_default_channel_for_user
- `backend/alembic/versions/td0091c_a_merge_notif_signoff_heads.py` — merge migration (two heads → one)
- `backend/alembic/versions/td0091c_b_add_is_default_and_user_email_unique.py` — DDL only (column + partial index)
- `backend/alembic/versions/td0091c_c_backfill_default_channels.py` — data backfill in autocommit_block
- `backend/tests/unit/test_notification_policy.py`
- `backend/tests/unit/test_notification_provisioning.py`
- `backend/tests/unit/test_dispatcher_email_recipient.py`
- `backend/tests/unit/test_dispatcher_email_verified_gate.py`
- `backend/tests/unit/test_subscriptions_batch_lookup.py`
- `backend/tests/unit/test_migration_policy_alignment.py`
- `backend/tests/unit/test_step_index.py`
- `backend/tests/unit/test_email_channel_unsubscribe_header.py`
- `backend/tests/unit/test_email_channel_smtp_timeout.py`
- `backend/tests/integration/test_register_provisions_channel.py`
- `backend/tests/integration/test_after_insert_covers_invite_path.py`
- `backend/tests/integration/test_invite_existing_user.py`
- `backend/tests/integration/test_invite_new_email.py`
- `backend/tests/integration/test_invite_accepted.py`
- `backend/tests/integration/test_role_unassigned_notification.py`
- `backend/tests/integration/test_step_deviation_notification.py`
- `backend/tests/integration/test_notifications_gating.py`

**Modified files:**

- `backend/app/services/runs/graph.py` — add `index_steps(graph) -> StepIndex` (deviation from spec: co-located with `iter_unit_op_nodes` rather than separate `graph_index.py`; DRY improvement)
- `backend/app/api/endpoints/runs.py` — use `index_steps` in two places; emit STEP_DEVIATION; emit ROLE_UNASSIGNED in `delete_run_role_assignment`
- `backend/app/models/notifications.py` — `is_default` column, unique partial index, remove `OFFLINE_VALUE_DISCREPANCY` from enum
- `backend/app/models/iam.py` — SQLAlchemy `after_insert` listener on User
- `backend/app/core/deps.py` — drain `pending_default_channels` after request
- `backend/app/services/core/notifications/dispatcher.py` — `_get_subscribed_channels` batch form, `_resolve_personal_recipient`, `_get_user_cached`, verified-email gate
- `backend/app/services/core/notifications/__init__.py` — wire `html_body` through dispatch
- `backend/app/services/core/notifications/channels/base.py` — `html_body: str | None` on FormattedMessage
- `backend/app/services/core/notifications/channels/email.py` — html_body fallback, footer helper, List-Unsubscribe header, SMTP timeout
- `backend/app/services/core/notifications/templates.py` — `_invite_html` helper, `invite_sent` returns html_body too, remove `offline_value_discrepancy`
- `backend/app/services/core/email_service.py` — refactor invite HTML to call shared `_invite_html` (or import from templates)
- `backend/app/api/endpoints/iam.py` — branch on `invited_user_id`; INVITE_SENT for existing-user path
- `backend/app/api/endpoints/auth.py` — INVITE_ACCEPTED in `accept_invitation`
- `backend/app/api/endpoints/notifications.py` — remove `require_active_subscription` from `mark_read`/`mark_all_read`
- `backend/app/core/config.py` — add `BATCHRITE_NOTIFICATION_EMAIL_ENABLED` setting; plan re-uses `settings.frontend_url`

**Additional new files from the review-panel addendum:**

- `backend/tests/integration/test_step_deviation_recipients_negative.py` — non-assignee with VIEW is NOT notified
- `backend/migrations/versions/td0091c_b2_add_run_role_assign_run_id_index.py` — additive index on `run_role_assignments(run_id)` (folded into Task 5)

---

## Review-Panel Amendments (READ BEFORE IMPLEMENTING)

Four parallel review agents (adversarial-risk, dry/reuse, db-scalability, production-ops) hardened the original plan. The amendments below override anything that contradicts them in the per-task code blocks. Each amendment names the task it modifies.

### A. Session lifecycle — `send_notification` opens its own session

**Amends:** Tasks 18, 19, 20 (background_tasks producers); the existing call sites in `send_notification`.

**Problem:** `send_notification` currently accepts the request `AsyncSession` and is invoked via `background_tasks.add_task(send_notification, db, ...)`. After the response returns, `get_db`'s `finally` closes that session — the background task then operates on a closed session.

**Fix:**
1. Change `send_notification` signature in `backend/app/services/core/notifications/__init__.py` to take primitives — `event_type, org_id, recipients, entity_type, entity_id, context` — and open its own session with `AsyncSessionLocal()` from `app.db.session`:

   ```python
   from app.db.session import AsyncSessionLocal

   async def send_notification(
       event_type: str,
       org_id: UUID,
       recipients: list[UUID],
       entity_type: str,
       entity_id: UUID,
       context: dict | None = None,
   ) -> list[NotificationDelivery]:
       async with AsyncSessionLocal() as db:
           try:
               ... existing body, using local db ...
               await db.commit()
           except Exception:
               await db.rollback()
               raise
   ```

2. Every call site in this plan (Tasks 18, 19, 20) and the pre-existing call sites must stop passing `db`:

   ```python
   background_tasks.add_task(
       send_notification,
       event_type="ROLE_UNASSIGNED",
       org_id=run.org_id,
       recipients=[unassigned_user_id],
       entity_type="RUN",
       entity_id=run.id,
       context={"run_name": run.name, ...},
   )
   ```

3. Pre-existing callers (RUN_STARTED, RUN_COMPLETED, ROLE_ASSIGNED, etc.) must be migrated in the same PR — they share the bug. Add a step in **Task 23** (full suite run) to grep `send_notification(` and fix any callers still passing `db`.

### B. Wrong-file `get_db` edit — request-end drain target

**Amends:** Task 7 Step 4.

**Problem:** Plan modifies `backend/app/core/deps.py:get_db`. The real `get_db` lives in `backend/app/db/session.py`. `core/deps.py` only re-exports it. Editing the wrong file leaves the listener queue undrained — auto-provisioning silently never fires.

**Fix:** In Task 7 Step 4, replace every reference to `app/core/deps.py:get_db` with `app/db/session.py:get_db`. Modify the existing function there. Update the Affected-file-map line: `backend/app/db/session.py` (not `core/deps.py`).

### C. Use `session.info`, not `connection.info` — request scope

**Amends:** Task 7 Step 3 (`after_insert` listener) and Step 4 (drain).

**Problem:** `connection.info` is per-connection, not per-request. With pool reuse, pending IDs leak across requests; rolled-back requests still drain.

**Fix:**
- In the `after_insert` listener (Step 3), append the user_id to a list on `target.__dict__` or — cleaner — emit a SQLAlchemy `do_orm_execute`-adjacent path. The reliable pattern is: in the listener, walk to the Session via `Session.object_session(target).info`. Append to `session.info.setdefault("pending_default_channels", []).append(target.id)`.
- In the drain (Step 4), after the request completes successfully, read `session.info.get("pending_default_channels", [])`. Drain **only after `session.commit()` succeeded**; skip on rollback. Wrap the drain body in `try/except` with `logger.exception("default-channel drain failed for user %s", uid)` — never let the drain break request teardown.

### D. `await runner.submit(...)` — submit is sync

**Amends:** Task 7 Step 4.

**Fix:** `get_task_runner().submit(...)` returns `None`. Drop the `await`:

```python
runner = get_task_runner()
for uid in user_ids:
    runner.submit(provision_default_channel_for_user(uid))
```

### E. `async_session_factory` → `AsyncSessionLocal`

**Amends:** Task 6 Step 3 (`provision_default_channel_for_user`).

**Fix:** The actual export from `backend/app/db/session.py` is `AsyncSessionLocal`. Replace:

```python
from app.db.session import AsyncSessionLocal

async def provision_default_channel_for_user(user_id: UUID) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await ensure_default_user_channel(session, user_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to provision default channel for user %s", user_id)
```

### F. `ensure_default_user_channel` — SAVEPOINT, not `db.rollback()`

**Amends:** Task 6 Step 3.

**Problem:** The `IntegrityError` branch calls `await db.rollback()` on the caller's session. That discards the caller's prior uncommitted work (the User INSERT that triggered the listener, anything in scope).

**Fix:** Wrap the INSERT in a SAVEPOINT (`async with db.begin_nested()`). On `IntegrityError`, only the SAVEPOINT rolls back; the outer transaction is untouched. Then re-SELECT to return the now-existing channel:

```python
from sqlalchemy.exc import IntegrityError

async def ensure_default_user_channel(db: AsyncSession, user_id: UUID) -> NotificationChannel:
    existing = (await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id,
            NotificationChannel.channel_type == "EMAIL",
            NotificationChannel.is_default == True,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    channel = NotificationChannel(
        user_id=user_id,
        org_id=None,
        name="Email",
        channel_type="EMAIL",
        config={"to": user.email},
        enabled=True,
        is_default=True,
    )
    try:
        async with db.begin_nested():
            db.add(channel)
            await db.flush()
    except IntegrityError:
        logger.warning("Default channel race for user %s; re-fetching", user_id)
        return (await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.channel_type == "EMAIL",
                NotificationChannel.is_default == True,
            )
        )).scalar_one()

    for event_type, policy in DEFAULT_POLICY.items():
        if not policy.email:
            continue
        try:
            async with db.begin_nested():
                db.add(NotificationSubscription(
                    channel_id=channel.id,
                    event_type=event_type.value,
                    enabled=True,
                ))
                await db.flush()
        except IntegrityError:
            pass
    return channel
```

### G. EMAIL `config["to"]` tampering — prefer `User.email` for `is_default=True`

**Amends:** Task 10 (`_resolve_personal_recipient`); Task 11 (verified-email gate).

**Problem:** Users (or any code path) can PATCH `notification_channels.config.to` to an attacker's address. The verified-email gate only checks `User.email_verified`, not address ownership — so a verified Alice has emails delivered to `attacker@elsewhere.com`.

**Fix:** For `channel.is_default=True`, ignore `channel.config["to"]` entirely; resolve from `User.email`. For user-created non-default EMAIL channels, allow `config.to` but require either an account-level verification flow (out of scope here) or treat as "best effort, no liability." Document the latter in §5b of the spec.

```python
async def _resolve_personal_recipient(
    db: AsyncSession,
    channel: NotificationChannel,
    user_cache: dict,
) -> tuple[str, User | None]:
    if channel.user_id is None:
        return channel.config.get("to", ""), None
    user = await _get_user_cached(db, channel.user_id, user_cache)
    if channel.is_default:
        return (user.email if user else ""), user
    return channel.config.get("to", ""), user
```

The verified-email gate then becomes:

```python
if channel.channel_type == "EMAIL":
    recipient, user = await _resolve_personal_recipient(db, channel, user_cache)
    if not channel.is_default:
        pass  # user-managed channels skip the gate
    elif user is None or not (user.email_verified or getattr(user, "oauth_email_verified", False)):
        logger.info("Skipping email for unverified user %s", channel.user_id)
        continue
```

### H. SSO users — gate on `email_verified OR oauth_email_verified`

**Amends:** Task 11.

**Problem:** OAuth/SSO users have `oauth_email_verified=True` but `email_verified=False`. Strict gate locks them out of all email forever.

**Fix:** see snippet in §G. Add an integration test fixture for an OAuth-registered user.

### I. STEP_DEVIATION recipients — query-first batch

**Amends:** Task 20 (`_collect_step_deviation_recipients`).

**Problem:** Plan loops `await check_permission(...)` per assignee. With `check_permission` issuing up to 6 queries each, a 10-assignee run runs ~60 queries on the hot `update_run` path.

**Fix:** Replace the helper body with a 4-query batch:

```python
async def _collect_step_deviation_recipients(
    db: AsyncSession,
    run_obj: Run,
    actor_user_id: UUID,
) -> list[UUID]:
    # 1. distinct assignees minus actor
    rows = (await db.execute(
        select(RunRoleAssignment.user_id)
        .where(RunRoleAssignment.run_id == run_obj.id)
        .distinct()
    )).scalars().all()
    candidates = [uid for uid in rows if uid != actor_user_id]
    if not candidates:
        return []

    org_id = run_obj.org_id  # confirm attribute path before implementing

    # 2. org admins get blanket access
    admin_rows = (await db.execute(
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id.in_(candidates),
            OrganizationMember.roles.contains(["ADMIN"]),
        )
    )).scalars().all()
    admin_set = set(admin_rows)

    # 3. project permissions_enabled? if False, every candidate qualifies
    proj_settings = (await db.execute(
        select(Project.settings).where(Project.id == run_obj.project_id)
    )).scalar_one_or_none() or {}
    if not proj_settings.get("permissions_enabled", False):
        return candidates

    # 4. explicit USER-level VIEW (or higher) permissions for non-admins
    non_admins = [uid for uid in candidates if uid not in admin_set]
    explicit = (await db.execute(
        select(ObjectPermission.principal_id).where(
            ObjectPermission.principal_type == PrincipalType.USER,
            ObjectPermission.principal_id.in_(non_admins),
            ObjectPermission.object_type == ObjectType.RUN.value,
            ObjectPermission.object_id == run_obj.id,
        )
    )).scalars().all()
    return list(admin_set | set(explicit))
```

Add a `# NOTE` documenting that team-permission inheritance is intentionally omitted — `RunRoleAssignment` filters to direct assignees already, and teams should be revisited only if VIEW-via-team becomes a recipient source.

### J. Add `ix_run_role_assign_run_id`

**Amends:** Task 5 (DDL migration) — add the index alongside `is_default`.

**Problem:** `run_role_assignments` has no index on `run_id`; the new Step I query Seq Scans the table.

**Fix:** In the DDL migration (`td0091c_b`), add:

```python
op.create_index(
    "ix_run_role_assign_run_id",
    "run_role_assignments",
    ["run_id"],
)
```

(no `CONCURRENTLY` — small table; pre-production).

### K. Batched `_get_subscribed_channels` — call OUTSIDE the per-user loop

**Amends:** Tasks 10 and 12 — the dispatcher's user-channel branch.

**Problem:** Task 10's call site passes `user_ids=[user_id]` inside `for user_id in recipients:` — single-element batches, zero scalability benefit for STEP_DEVIATION.

**Fix:** Use the batch form ONCE, then group:

```python
# Single IN-query for all recipients at once
all_user_channels = await _get_subscribed_channels(
    db, event_type, user_ids=recipients
)
channels_by_user: dict[UUID, list[NotificationChannel]] = {}
for ch in all_user_channels:
    channels_by_user.setdefault(ch.user_id, []).append(ch)

user_cache: dict[UUID, User] = {}
for user_id in recipients:
    for channel_model in channels_by_user.get(user_id, []):
        if channel_model.channel_type == "EMAIL":
            recipient, user = await _resolve_personal_recipient(
                db, channel_model, user_cache
            )
            if channel_model.is_default and (
                user is None
                or not (user.email_verified or getattr(user, "oauth_email_verified", False))
            ):
                continue
        msg = FormattedMessage(...)
        delivery = await _dispatch_to_channel(db, channel_model, msg, event_type)
        deliveries.append(delivery)
```

**Task ordering note:** Task 12 (batch parameter) must commit **before** Task 10 starts using `user_ids=[...]`. If implementing in Task 10 → Task 12 order, keep the existing `user_id=user_id` call in Task 10 and migrate to the batch form in Task 12 Step 3.

### L. Narrow partial unique index — `is_default=TRUE`

**Amends:** Task 5 (DDL migration); Task 6 (provisioning lookup).

**Problem:** As planned, the partial index forbids a user from EVER having more than one EMAIL channel (even a personal alias).

**Fix:** Predicate becomes:

```sql
CREATE UNIQUE INDEX ix_notif_channel_user_email_unique
ON notification_channels(user_id)
WHERE channel_type = 'EMAIL' AND is_default = TRUE AND user_id IS NOT NULL;
```

SQLAlchemy form:

```python
Index(
    "ix_notif_channel_user_email_unique",
    "user_id",
    unique=True,
    postgresql_where=text(
        "channel_type = 'EMAIL' AND is_default = TRUE AND user_id IS NOT NULL"
    ),
)
```

`ensure_default_user_channel`'s existence-check filter also gains `is_default == True` (already in the §F snippet).

### M. `_invite_html` — escape all dynamic values; validate `accept_url`

**Amends:** Task 16.

**Problem:** f-string interpolation in `_invite_html(org_name, invited_by, accept_url, expires_at)` leaks HTML/JS via `org_name` (admin-set), `invited_by` (`user.full_name`, user-controlled), `accept_url` (link-injection risk).

**Fix:**

```python
import html
from urllib.parse import urlparse
from app.core.config import settings

def invite_html(  # renamed from _invite_html — intentionally shared cross-module
    org_name: str,
    invited_by: str,
    accept_url: str,
    expires_at: str | None = None,
) -> str:
    parsed = urlparse(accept_url)
    base = urlparse(settings.backend_url)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"Invalid accept_url host: {parsed.netloc}")

    safe_org = html.escape(org_name)
    safe_inviter = html.escape(invited_by)
    safe_url = html.escape(accept_url)
    safe_expires = html.escape(expires_at) if expires_at else ""

    expiry_block = f"<p>Expires {safe_expires}.</p>" if safe_expires else ""
    return f"""
    <p>{safe_inviter} invited you to join <strong>{safe_org}</strong> on Batchrite.</p>
    <p><a href="{safe_url}" style="...">Accept invitation</a></p>
    {expiry_block}
    """
```

Note the rename `_invite_html` → `invite_html` — it is intentionally cross-module (imported by `email_service.py`). Drop the underscore convention.

### N. List-Unsubscribe — `mailto:` only; drop One-Click POST header

**Amends:** Task 15.

**Problem:** `List-Unsubscribe-Post: List-Unsubscribe=One-Click` requires an authenticated POST endpoint per RFC 8058. Plan points at `/settings/notifications` (a GET page). Gmail/Outlook penalize broken one-click.

**Fix:** Ship only the `mailto:` form for now. Drop the `List-Unsubscribe-Post` header entirely. CAN-SPAM compliant via:

```python
unsubscribe_email = settings.notification_unsubscribe_mailto or "unsubscribe@batchrite.com"
headers["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}>"
# DO NOT set List-Unsubscribe-Post until a signed-token POST endpoint exists.
```

Add a follow-up TECH_DEBT ticket: "Build signed-token POST `/api/notifications/unsubscribe` and re-enable List-Unsubscribe-Post: One-Click."

### O. Kill switch — `BATCHRITE_NOTIFICATION_EMAIL_ENABLED`

**Amends:** Task 14 (EmailChannel.send), Task 5 (config).

**Fix:**

1. In `backend/app/core/config.py`:

   ```python
   notification_email_enabled: bool = Field(
       default=True, alias="BATCHRITE_NOTIFICATION_EMAIL_ENABLED"
   )
   ```

2. In `EmailChannel.send` (Task 14 Step 1), top of function:

   ```python
   from app.core.config import settings
   if not settings.notification_email_enabled:
       raise PermanentError("Email delivery disabled by ops kill-switch")
   ```

   PermanentError records a `FAILED` delivery with `status_detail="...kill-switch"`. Single env-var flip silences all email without DB access. Add to the CLAUDE.md feature-flags table at task close (Step 7 — refresh project rules).

### P. Template return shape — typed result, not 3-tuple polymorphism

**Amends:** Tasks 13, 16, 21 (and any 2/3-tuple callers).

**Problem:** `if len(result) == 3` dispatch is fragile; a future template returning a 3-tuple for an unrelated reason silently mis-routes.

**Fix:** Introduce a small dataclass in `templates.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class TemplateResult:
    title: str
    body: str
    html_body: str | None = None
```

Migrate every template to return `TemplateResult(...)`. The dispatcher reads `.title`, `.body`, `.html_body` directly — no polymorphism.

For backward-compat with the 2-tuple call sites in `__init__.py`:

```python
result = template_fn(context, personal=True)
if isinstance(result, tuple):
    title, body = result
    html_body = None
else:
    title, body, html_body = result.title, result.body, result.html_body
```

Migrate all templates in the same PR; remove the isinstance branch before merge.

### Q. Migration alignment regex — anchor to enum names

**Amends:** Task 8.

**Fix:** Replace `re.findall(r"'([A-Z_]+)'", ...)` with an enum-anchored extraction:

```python
import re
from app.models.notifications import NotificationEventType

EVENT_NAMES = {e.value for e in NotificationEventType}
matches = set(re.findall(r"'([A-Z_]+)'", migration_text)) & EVENT_NAMES
expected = {ev.value for ev, p in DEFAULT_POLICY.items() if p.email}
assert matches == expected, f"Migration drift: {matches ^ expected}"
```

### R. Backfill — log row counts per pass

**Amends:** Task 9.

**Fix:** After each `autocommit_block`, emit:

```python
inserted = bind.execute(text("""
    SELECT COUNT(*) FROM notification_channels WHERE is_default = TRUE
""")).scalar()
print(f"[td0091c_c] Pass 1 complete: {inserted} default channels exist", flush=True)
```

Same for Pass 2 against `notification_subscriptions` joined to `is_default` channels. Operators can sanity-check against user count.

### S. STEP_DEVIATION negative test — non-assignee with VIEW is NOT notified

**Amends:** Task 20 test file list.

**Fix:** Add a new integration test `backend/tests/integration/test_step_deviation_recipients_negative.py`:
- Set up a run with assignees A, B.
- Grant user C a VIEW ObjectPermission on the run but NO RunRoleAssignment.
- Trigger STEP_DEVIATION; assert A and B receive Notification rows; assert C does NOT.

### T. Task-ordering matrix (overrides plan's "Phase ordering" line)

The amendments above introduce strict ordering inside Phase 6:

1. Task 12 (batch `_get_subscribed_channels`) **before** Task 10's batched call site.
2. Task 13 (`TemplateResult` dataclass — replacing the 3-tuple shape) **before** Task 16 (`invite_sent` returns html_body).
3. Task 5 (DDL: `is_default`, narrowed unique index, `ix_run_role_assign_run_id`) **before** Task 6 (provisioning) **before** Task 9 (backfill).

### U. Sanity checks during implementation

- **Confirm `accept_invitation` signature** (Task 18) — verify `invited_user` and `background_tasks` are in scope before the emit. If `accept_invitation` does not currently accept `background_tasks: BackgroundTasks`, add it to the signature and update the route binding.
- **Confirm `update_run` injects `BackgroundTasks`** (Task 20) — if not, add it. Other producer changes in this plan assume it is injected.
- **Confirm `Run.org_id` attribute path** — the `_collect_step_deviation_recipients` helper assumes `run_obj.org_id`. If org_id is reached via `run.project.organization_id`, adjust.

---

## Phase 1: Preparatory DRY refactor (graph step index)

Pulls the twin `_node_map` / `_name_map` traversals in `update_run` into a single `index_steps(graph)` helper so STEP_DEVIATION (Phase 9) can reuse it without becoming the third repetition.

### Task 1: Add `index_steps` helper

**Files:**
- Modify: `backend/app/services/runs/graph.py`
- Test: `backend/tests/unit/test_step_index.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_step_index.py
from app.services.runs.graph import index_steps


def test_index_steps_returns_node_and_name_maps_in_one_pass():
    graph = {
        "nodes": [
            {"id": "n1", "type": "unitOp", "data": {"label": "Mix Buffer",
                                                     "paramSchema": {"properties": {"k": {"title": "K"}}}}},
            {"id": "n2", "type": "unitOp", "data": {"label": "Seed Bioreactor"}},
            {"id": "lane1", "type": "swimLane", "data": {"label": "Lane"}},
        ]
    }
    index = index_steps(graph)
    assert index.nodes["n1"]["label"] == "Mix Buffer"
    assert index.names == {"n1": "Mix Buffer", "n2": "Seed Bioreactor"}
    assert "lane1" not in index.nodes
    assert index.name_for("n1") == "Mix Buffer"
    assert index.name_for("unknown") == "unknown"  # falls back to step_id


def test_index_steps_tolerates_empty_graph():
    index = index_steps(None)
    assert index.nodes == {}
    assert index.names == {}
    assert index.name_for("x") == "x"


def test_index_steps_uses_id_when_label_missing():
    graph = {"nodes": [{"id": "n1", "type": "unitOp", "data": {}}]}
    index = index_steps(graph)
    assert index.names["n1"] == "n1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_step_index.py -v`
Expected: FAIL with `ImportError: cannot import name 'index_steps'`

- [ ] **Step 3: Implement the helper**

Append to `backend/app/services/runs/graph.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StepIndex:
    """One-pass lookup over a run/protocol graph's unitOp nodes."""

    nodes: dict[str, dict] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    def name_for(self, step_id: str) -> str:
        return self.names.get(step_id, step_id)


def index_steps(graph: Optional[dict]) -> StepIndex:
    """Build node-data and step-name lookups from a graph in a single pass."""
    nodes: dict[str, dict] = {}
    names: dict[str, str] = {}
    for node in iter_unit_op_nodes(graph):
        node_id = node["id"]
        data = node.get("data", {}) or {}
        nodes[node_id] = data
        names[node_id] = data.get("label", node_id)
    return StepIndex(nodes=nodes, names=names)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_step_index.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/runs/graph.py backend/tests/unit/test_step_index.py
git commit -m "refactor(TD-0091c): add index_steps helper for graph step lookups"
```

### Task 2: Switch `update_run` call sites to `index_steps`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:652-654` and `:763-766`
- Test: existing run-update integration tests (`backend/tests/integration/test_runs*.py`)

- [ ] **Step 1: Run existing run-update tests as baseline**

Run: `cd backend && pytest tests/integration -k "update_run or run_update or step" -v`
Expected: All currently passing — record the pass count.

- [ ] **Step 2: Replace the two traversals**

At `backend/app/api/endpoints/runs.py:651-654`, change:

```python
            # Build step name + param schema lookup from graph
            _node_map: dict[str, dict] = {
                n["id"]: n.get("data", {}) for n in iter_unit_op_nodes(run_obj.graph)
            }
```

to:

```python
            step_index = index_steps(run_obj.graph)
```

Then within the same block, replace `_node_map.get(step_id, {})` with `step_index.nodes.get(step_id, {})` (one occurrence around line 663). And `step_name = node_data.get("label", step_id)` stays as is — it reads off `node_data`.

At `backend/app/api/endpoints/runs.py:762-766`, change:

```python
        # Build step name lookup from graph
        _name_map: dict[str, str] = {
            n["id"]: n.get("data", {}).get("label", n["id"])
            for n in iter_unit_op_nodes(run_obj.graph)
        }
```

to:

```python
        step_index = index_steps(run_obj.graph)
```

Then replace every `_name_map.get(step_id, step_id)` (three occurrences in this block, lines ~783, 794, 812) with `step_index.name_for(step_id)`.

Add to imports at the top of `runs.py`:

```python
from app.services.runs.graph import derive_field_label, index_steps, iter_unit_op_nodes
```

(Replaces the existing `from app.services.runs.graph import derive_field_label, iter_unit_op_nodes`.)

- [ ] **Step 3: Run the same tests to verify no regression**

Run: `cd backend && pytest tests/integration -k "update_run or run_update or step" -v`
Expected: Same pass count, zero failures.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/endpoints/runs.py
git commit -m "refactor(TD-0091c): use index_steps in update_run audit traversals"
```

---

## Phase 2: Delivery policy module

Code-only, no DB. Single source of truth for "what events fan to email by default."

### Task 3: Create `policy.py` with tests

**Files:**
- Create: `backend/app/services/core/notifications/policy.py`
- Test: `backend/tests/unit/test_notification_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_notification_policy.py
from app.models.notifications import NotificationEventType
from app.services.core.notifications.policy import (
    DEFAULT_POLICY,
    DeliveryPolicy,
    policy_for,
)


def test_default_policy_is_exhaustive_over_event_types():
    """Every NotificationEventType has an entry, except OFFLINE_VALUE_DISCREPANCY (deleted in Phase 10)."""
    expected = {e.value for e in NotificationEventType} - {"OFFLINE_VALUE_DISCREPANCY"}
    assert set(DEFAULT_POLICY.keys()) == expected


def test_policy_for_returns_email_true_for_invite_sent():
    p = policy_for("INVITE_SENT")
    assert p.in_app is True
    assert p.email is True


def test_policy_for_returns_email_false_for_run_completed():
    p = policy_for("RUN_COMPLETED")
    assert p.email is False


def test_policy_for_unknown_event_returns_safe_defaults():
    p = policy_for("UNKNOWN_FUTURE_EVENT")
    assert p == DeliveryPolicy()  # in_app=True, email=False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_notification_policy.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

Create `backend/app/services/core/notifications/policy.py`:

```python
"""Per-event default delivery policy.

Single source of truth for which channels Batchrite uses for each event
out of the box. Drives the seed set of NotificationSubscription rows that
are created when a user is provisioned (see provisioning.py). Not
consulted at dispatch time — once subscriptions exist, the subscription
table is authoritative, so a user opting out stays opted out.
"""

from dataclasses import dataclass

from app.models.notifications import NotificationEventType


@dataclass(frozen=True)
class DeliveryPolicy:
    in_app: bool = True
    email: bool = False


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
    """Look up the delivery policy for an event type. Unknown → safe default."""
    return DEFAULT_POLICY.get(event_type, DeliveryPolicy())
```

Note: the exhaustiveness test currently fails because `OFFLINE_VALUE_DISCREPANCY` is still in the enum. That's intentional — the test is the canary that Phase 10 (enum cleanup) must land before this passes. To allow Phase 2 to commit independently, the exhaustiveness test should skip with a TODO until Phase 10:

```python
import pytest

@pytest.mark.skip(reason="Enabled after Phase 10 removes OFFLINE_VALUE_DISCREPANCY")
def test_default_policy_is_exhaustive_over_event_types():
    ...
```

Phase 10 will un-skip it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_notification_policy.py -v`
Expected: PASS (with the exhaustiveness test skipped).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/policy.py backend/tests/unit/test_notification_policy.py
git commit -m "feat(TD-0091c): add notification delivery policy module"
```

---

## Phase 3: Model change + DDL migration

Adds the `is_default` boolean and the unique partial index on per-user EMAIL channels. Schema-only — no data writes. Lands before Phase 4 because provisioning writes `is_default=True`.

### Task 4: Add merge migration (two heads → one)

**Files:**
- Create: `backend/alembic/versions/td0091c_a_merge_notif_signoff_heads.py`

- [ ] **Step 1: Verify current heads**

Run: `cd backend && source .venv/bin/activate && alembic heads`
Expected: `3cbfb1725385 (head)` and `acc00af3cd19 (head)`.

- [ ] **Step 2: Create the merge migration**

Create `backend/alembic/versions/td0091c_a_merge_notif_signoff_heads.py`:

```python
"""TD-0091c: merge notif-retention and signoff heads.

Revision ID: td0091c_a_merge
Revises: 3cbfb1725385, acc00af3cd19
Create Date: 2026-05-22
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "td0091c_a_merge"
down_revision: Union[str, Sequence[str], None] = ("3cbfb1725385", "acc00af3cd19")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

- [ ] **Step 3: Run alembic and verify heads collapsed**

Run: `cd backend && alembic upgrade head && alembic heads`
Expected: single head `td0091c_a_merge (head)`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/td0091c_a_merge_notif_signoff_heads.py
git commit -m "chore(TD-0091c): merge notif-retention and signoff alembic heads"
```

### Task 5: Add `is_default` column + unique partial index

**Files:**
- Modify: `backend/app/models/notifications.py`
- Create: `backend/alembic/versions/td0091c_b_add_is_default_and_user_email_unique.py`

- [ ] **Step 1: Update the model**

In `backend/app/models/notifications.py`, modify the `NotificationChannel` class:

```python
class NotificationChannel(Base, UUIDMixin, TimestampMixin):
    """A configured delivery channel, owned by either an org or a user."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint(
            "(org_id IS NOT NULL AND user_id IS NULL) OR "
            "(org_id IS NULL AND user_id IS NOT NULL)",
            name="ck_channel_scope",
        ),
        Index("ix_notif_channels_org", "org_id"),
        Index("ix_notif_channels_user", "user_id"),
        # TD-0091c: at most one default (auto-provisioned) EMAIL channel per user.
        # Partial index ⇒ doesn't affect user-created or org-level EMAIL channels.
        Index(
            "ix_notif_channel_user_email_unique",
            "user_id",
            unique=True,
            postgresql_where=text("channel_type = 'EMAIL' AND user_id IS NOT NULL"),
        ),
    )

    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    channel_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # TD-0091c: marks rows created by the backfill / after_insert provisioner.
    # Used by migrations for clean rollback and by future "reset to defaults" flows.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # ... relationships unchanged
```

- [ ] **Step 2: Create the DDL migration**

Create `backend/alembic/versions/td0091c_b_add_is_default_and_user_email_unique.py`:

```python
"""TD-0091c: add is_default column + unique partial index on user EMAIL channels.

Revision ID: td0091c_b_ddl
Revises: td0091c_a_merge
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "td0091c_b_ddl"
down_revision: Union[str, Sequence[str], None] = "td0091c_a_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_channels",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_notif_channel_user_email_unique",
        "notification_channels",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "channel_type = 'EMAIL' AND user_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notif_channel_user_email_unique",
        table_name="notification_channels",
    )
    op.drop_column("notification_channels", "is_default")
```

- [ ] **Step 3: Apply and verify**

Run: `cd backend && alembic upgrade head`
Expected: applies cleanly.

Run: `psql -U postgres -h localhost -d batchrite_wt<N> -c "\d notification_channels"`
Expected: shows `is_default` boolean NOT NULL and `ix_notif_channel_user_email_unique` partial index.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/notifications.py backend/alembic/versions/td0091c_b_add_is_default_and_user_email_unique.py
git commit -m "feat(TD-0091c): add is_default flag and unique per-user EMAIL channel index"
```

---

## Phase 4: Auto-provisioning + after_insert hook

The provisioning module + the SQLAlchemy event hook + the request-end drain.

### Task 6: Implement `ensure_default_user_channel` + `provision_default_channel_for_user`

**Files:**
- Create: `backend/app/services/core/notifications/provisioning.py`
- Test: `backend/tests/unit/test_notification_provisioning.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_notification_provisioning.py
import pytest
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
)
from app.services.core.notifications.policy import DEFAULT_POLICY
from app.services.core.notifications.provisioning import (
    ensure_default_user_channel,
)


@pytest.mark.asyncio
async def test_new_user_gets_channel_and_subscriptions(db_session):
    user = User(email="newbie@example.com", email_verified=True, full_name="Newbie")
    db_session.add(user)
    await db_session.flush()

    channel = await ensure_default_user_channel(db_session, user)
    await db_session.flush()

    assert channel.user_id == user.id
    assert channel.channel_type == "EMAIL"
    assert channel.config == {"to": "newbie@example.com"}
    assert channel.is_default is True

    subs = (
        await db_session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.channel_id == channel.id
            )
        )
    ).scalars().all()
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    assert {s.event_type for s in subs} == expected


@pytest.mark.asyncio
async def test_re_call_is_no_op(db_session):
    user = User(email="repeat@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()

    await ensure_default_user_channel(db_session, user)
    await db_session.flush()
    await ensure_default_user_channel(db_session, user)
    await db_session.flush()

    channels = (
        await db_session.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id,
                NotificationChannel.channel_type == "EMAIL",
            )
        )
    ).scalars().all()
    assert len(channels) == 1

    subs = (
        await db_session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.channel_id == channels[0].id
            )
        )
    ).scalars().all()
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    assert {s.event_type for s in subs} == expected


@pytest.mark.asyncio
async def test_integrity_error_on_race_is_swallowed(db_session, monkeypatch):
    """Simulate a parallel insert winning the unique-index race."""
    user = User(email="race@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()

    # Pre-create the channel to force the second insert to violate the index
    pre = NotificationChannel(
        user_id=user.id,
        name="Email",
        channel_type="EMAIL",
        config={"to": user.email},
        enabled=True,
        is_default=True,
    )
    db_session.add(pre)
    await db_session.flush()

    # Now calling ensure_default_user_channel should find the existing row
    channel = await ensure_default_user_channel(db_session, user)
    assert channel.id == pre.id  # returned the pre-existing channel, not a new one
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_notification_provisioning.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

Create `backend/app/services/core/notifications/provisioning.py`:

```python
"""Auto-provisioning of the default per-user EMAIL notification channel.

Called from two places:

1. A SQLAlchemy after_insert event on User, drained by the request-end
   hook in core.deps.get_db. Covers every user-creation path.
2. The backfill migration (td0091c_c) — for any users that exist
   before this feature lands.

Idempotent. Safe to call repeatedly.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.iam import User
from app.models.notifications import NotificationChannel, NotificationSubscription
from app.services.core.notifications.policy import DEFAULT_POLICY

logger = logging.getLogger("notifications.provisioning")


async def ensure_default_user_channel(
    db: AsyncSession, user: User
) -> NotificationChannel:
    """Idempotently create the user's default EMAIL channel + default subs."""

    existing = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id,
                NotificationChannel.channel_type == "EMAIL",
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        channel = NotificationChannel(
            user_id=user.id,
            name="Email",
            channel_type="EMAIL",
            config={"to": user.email},
            enabled=True,
            is_default=True,
        )
        db.add(channel)
        try:
            await db.flush()
        except IntegrityError:
            # Lost the race with a concurrent insert — re-fetch and use that row.
            await db.rollback()
            existing = (
                await db.execute(
                    select(NotificationChannel).where(
                        NotificationChannel.user_id == user.id,
                        NotificationChannel.channel_type == "EMAIL",
                    )
                )
            ).scalar_one()
            channel = existing
    else:
        channel = existing

    # Seed default subscriptions
    existing_event_types = {
        row[0]
        for row in (
            await db.execute(
                select(NotificationSubscription.event_type).where(
                    NotificationSubscription.channel_id == channel.id
                )
            )
        ).all()
    }

    for event_type, policy in DEFAULT_POLICY.items():
        if not policy.email:
            continue
        if event_type in existing_event_types:
            continue
        db.add(
            NotificationSubscription(
                channel_id=channel.id,
                event_type=event_type,
                enabled=True,
            )
        )

    await db.flush()
    return channel


async def provision_default_channel_for_user(user_id: UUID) -> None:
    """Open an isolated session and provision the channel for `user_id`.

    Called from a BackgroundTasks queue drained at request end, so it must
    not depend on the caller's session.
    """
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            logger.warning(
                "provision_default_channel_for_user: user %s not found", user_id
            )
            return
        await ensure_default_user_channel(session, user)
        await session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_notification_provisioning.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/provisioning.py backend/tests/unit/test_notification_provisioning.py
git commit -m "feat(TD-0091c): auto-provision default user EMAIL channel"
```

### Task 7: Wire the SQLAlchemy `after_insert` event + request-end drain

**Files:**
- Modify: `backend/app/models/iam.py` (end of file)
- Modify: `backend/app/core/deps.py:get_db`
- Test: `backend/tests/integration/test_register_provisions_channel.py`, `backend/tests/integration/test_after_insert_covers_invite_path.py`

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/integration/test_register_provisions_channel.py
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import NotificationChannel, NotificationSubscription
from app.services.core.notifications.policy import DEFAULT_POLICY


@pytest.mark.asyncio
async def test_register_provisions_default_channel(
    client: AsyncClient, db_session
):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "fresh@example.com",
            "password": "Password!1234",
            "full_name": "Fresh User",
        },
    )
    assert resp.status_code == 200

    # User exists
    user = (
        await db_session.execute(
            select(User).where(User.email == "fresh@example.com")
        )
    ).scalar_one()

    # Exactly one default EMAIL channel
    channels = (
        await db_session.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id,
                NotificationChannel.channel_type == "EMAIL",
            )
        )
    ).scalars().all()
    assert len(channels) == 1
    assert channels[0].is_default is True
    assert channels[0].config == {"to": "fresh@example.com"}

    # All email-default subscriptions present
    subs = (
        await db_session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.channel_id == channels[0].id
            )
        )
    ).scalars().all()
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    assert {s.event_type for s in subs} == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_register_provisions_channel.py -v`
Expected: FAIL — no channel rows created.

- [ ] **Step 3: Add the after_insert listener in `iam.py`**

Append to `backend/app/models/iam.py` (after all class definitions):

```python
from sqlalchemy import event as _sa_event  # at module top with other imports


@_sa_event.listens_for(User, "after_insert")
def _queue_default_channel_provisioning(mapper, connection, target):
    """Record the new user's ID for post-commit provisioning.

    The request-end hook in core.deps.get_db drains this list and schedules
    provision_default_channel_for_user in the background.
    """
    pending = connection.info.setdefault("pending_default_channels", [])
    pending.append(target.id)
```

- [ ] **Step 4: Drain the queue at request end in `deps.py`**

In `backend/app/core/deps.py`, locate `get_db` and modify the `try/finally` to drain after commit. Sketch (consult the existing function for the exact shape):

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            # TD-0091c: drain pending default-channel provisioning. Runs
            # after the request's transaction committed (or rolled back —
            # the queue is discarded on rollback because connection.info
            # is per-connection).
            try:
                conn = await session.connection()
                pending = list(conn.info.get("pending_default_channels", []))
                conn.info["pending_default_channels"] = []
            except Exception:
                pending = []

            if pending:
                # Lazy import to avoid circular dependency on startup
                from app.services.core.task_runner import get_task_runner
                from app.services.core.notifications.provisioning import (
                    provision_default_channel_for_user,
                )

                runner = get_task_runner()
                for user_id in pending:
                    await runner.submit(
                        provision_default_channel_for_user(user_id)
                    )

            await session.close()
```

Verify `app.services.core.task_runner.get_task_runner` exists and `runner.submit(coroutine)` is the correct API by reading the file before writing this; correct the import path if it lives elsewhere.

- [ ] **Step 5: Verify register test passes**

Run: `cd backend && pytest tests/integration/test_register_provisions_channel.py -v`
Expected: PASS (the background task drains before the test reads channels — ThreadTaskRunner is synchronous in tests; verify by reading task_runner.py).

If the task_runner is genuinely async/threaded, the test must wait for it. Use `await asyncio.sleep(0.1)` after the register call, or expose a `runner.wait_idle()` testing helper.

- [ ] **Step 6: Add the accept-invitation coverage test**

```python
# backend/tests/integration/test_after_insert_covers_invite_path.py
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import NotificationChannel


@pytest.mark.asyncio
async def test_user_created_via_invite_accept_register_gets_channel(
    client: AsyncClient, db_session, seed_invitation
):
    """When a user is created by registering via an invite token, the same
    after_insert path runs and they get a default channel."""
    # seed_invitation is a fixture: creates an Invitation for "newhire@example.com"
    invitation = seed_invitation(email="newhire@example.com")
    # Register from the invite token (mirrors what the redirect flow ends up at)
    resp = await client.post(
        "/auth/register",
        json={
            "email": "newhire@example.com",
            "password": "Password!1234",
            "full_name": "New Hire",
            "invite_token": invitation.token,
        },
    )
    assert resp.status_code == 200

    user = (
        await db_session.execute(
            select(User).where(User.email == "newhire@example.com")
        )
    ).scalar_one()
    channels = (
        await db_session.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id
            )
        )
    ).scalars().all()
    assert len(channels) == 1
```

Run: `cd backend && pytest tests/integration/test_after_insert_covers_invite_path.py -v`
Expected: PASS (after_insert fires regardless of path; if `invite_token` param isn't accepted by register today, drop that field from the body — the assertion still passes because every register creates a user).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/iam.py backend/app/core/deps.py backend/tests/integration/test_register_provisions_channel.py backend/tests/integration/test_after_insert_covers_invite_path.py
git commit -m "feat(TD-0091c): provision default channel via User after_insert event"
```

---

## Phase 5: Backfill migration

Data-only migration. Runs in `autocommit_block` so large user tables don't lock. Since this is a pre-production app, the autocommit pattern is preserved for the next migration that does run against real data.

### Task 8: Add `test_migration_policy_alignment` (canary)

**Files:**
- Test: `backend/tests/unit/test_migration_policy_alignment.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_migration_policy_alignment.py
import re
from pathlib import Path

from app.services.core.notifications.policy import DEFAULT_POLICY

MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "td0091c_c_backfill_default_channels.py"
)


def test_migration_event_list_matches_policy_email_set():
    """The literal event list in the migration must equal the set of
    policy entries with email=True at the time the migration was written.

    If you change DEFAULT_POLICY's email defaults, write a new migration
    rather than mutating this one — old migrations are immutable history.
    """
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    source = MIGRATION_PATH.read_text()
    # Extract single-quoted event-type names that appear in the SQL VALUES tuple
    match = re.search(r"CROSS JOIN \(VALUES(.+?)\) AS e", source, re.S)
    assert match is not None, "Could not locate VALUES tuple in migration"
    found = set(re.findall(r"'([A-Z_]+)'", match.group(1)))
    assert found == expected
```

- [ ] **Step 2: Run — expected fail (migration file does not exist yet)**

Run: `cd backend && pytest tests/unit/test_migration_policy_alignment.py -v`
Expected: FAIL with FileNotFoundError.

### Task 9: Implement the backfill migration

**Files:**
- Create: `backend/alembic/versions/td0091c_c_backfill_default_channels.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/td0091c_c_backfill_default_channels.py`:

```python
"""TD-0091c: backfill default EMAIL channels + subscriptions for existing users.

Revision ID: td0091c_c_backfill
Revises: td0091c_b_ddl
Create Date: 2026-05-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "td0091c_c_backfill"
down_revision: Union[str, Sequence[str], None] = "td0091c_b_ddl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill in two passes, each inside autocommit_block so each row
    commits independently and we don't hold a long lock on either table."""
    bind = op.get_bind()

    # Pass 1: one EMAIL channel per user who lacks one. is_default=true
    # marks the row as owned by the auto-provisioning path.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
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
            ON CONFLICT DO NOTHING
        """))

    # Pass 2: seed default-email subscriptions on every per-user EMAIL channel
    # that's missing them. Re-runnable.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
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
              )
        """))


def downgrade() -> None:
    """Delete only the auto-provisioned channels (is_default=true).
    Cascade clears subscriptions. User-created channels are untouched."""
    bind = op.get_bind()
    with op.get_context().autocommit_block():
        bind.execute(sa.text("""
            DELETE FROM notification_channels
            WHERE is_default = TRUE
        """))
```

- [ ] **Step 2: Apply and verify**

Run: `cd backend && alembic upgrade head`
Expected: applies cleanly.

Run:
```bash
psql -U postgres -h localhost -d batchrite_wt<N> -c "SELECT COUNT(*) FROM notification_channels WHERE is_default = true AND channel_type = 'EMAIL'"
```
Expected: matches the count of users (each existing user got one default channel).

- [ ] **Step 3: Verify the alignment test now passes**

Run: `cd backend && pytest tests/unit/test_migration_policy_alignment.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/td0091c_c_backfill_default_channels.py backend/tests/unit/test_migration_policy_alignment.py
git commit -m "feat(TD-0091c): backfill default notification channels"
```

---

## Phase 6: Dispatcher — verified-email gate + recipient resolution + batch lookup

Three changes to `dispatcher.py`. All independent of the producer wiring, so they can land before Phase 9.

### Task 10: Add `_resolve_personal_recipient` and route through it

**Files:**
- Modify: `backend/app/services/core/notifications/dispatcher.py`
- Test: `backend/tests/unit/test_dispatcher_email_recipient.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_dispatcher_email_recipient.py
import pytest

from app.models.notifications import NotificationChannel
from app.services.core.notifications.dispatcher import _resolve_personal_recipient


def test_email_channel_recipient_from_config_to():
    channel = NotificationChannel(
        channel_type="EMAIL",
        name="Email",
        config={"to": "alice@example.com"},
        enabled=True,
    )
    assert _resolve_personal_recipient(channel) == "alice@example.com"


def test_email_channel_missing_config_to_returns_empty():
    channel = NotificationChannel(
        channel_type="EMAIL",
        name="Email",
        config={},
        enabled=True,
    )
    assert _resolve_personal_recipient(channel) == ""


def test_slack_channel_returns_empty_recipient():
    channel = NotificationChannel(
        channel_type="SLACK",
        name="My Slack",
        config={"webhook_url": "https://hooks.slack.com/..."},
        enabled=True,
    )
    assert _resolve_personal_recipient(channel) == ""
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/unit/test_dispatcher_email_recipient.py -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement**

In `backend/app/services/core/notifications/dispatcher.py`, add:

```python
def _resolve_personal_recipient(channel: NotificationChannel) -> str:
    """Per-channel recipient for a user-level dispatch.

    EMAIL channels carry the recipient in config['to']. Slack/Teams/Webhook/
    Discord all route via their own config (webhook URL, etc.) and ignore the
    message recipient field, so return empty for them.
    """
    if channel.channel_type == "EMAIL":
        return channel.config.get("to", "") if channel.config else ""
    return ""
```

Then modify the user-level loop in `dispatch_event` (lines 67-78). Replace:

```python
    # 2. User-level channels for each recipient
    for user_id in recipients:
        user_channels = await _get_subscribed_channels(db, event_type, user_id=user_id)
        for channel_model in user_channels:
            msg = FormattedMessage(
                event_type=message_personal.event_type,
                title=message_personal.title,
                body=message_personal.body,
                recipient=message_personal.recipient,
                url=message_personal.url,
            )
            delivery = await _dispatch_to_channel(db, channel_model, msg, event_type)
            deliveries.append(delivery)
```

with:

```python
    # 2. User-level channels for each recipient
    user_cache: dict[UUID, "User"] = {}
    for user_id in recipients:
        user_channels = await _get_subscribed_channels(
            db, event_type, user_ids=[user_id]
        )
        for channel_model in user_channels:
            # Verified-email gate (TD-0091c): skip EMAIL send for unverified
            # users; the in-app Notification row is still created upstream.
            if channel_model.channel_type == "EMAIL":
                user = await _get_user_cached(db, user_id, user_cache)
                if user is None or not user.email_verified:
                    continue

            recipient = _resolve_personal_recipient(channel_model)
            msg = FormattedMessage(
                event_type=message_personal.event_type,
                title=message_personal.title,
                body=message_personal.body,
                recipient=recipient,
                url=message_personal.url,
                html_body=message_personal.html_body,
            )
            delivery = await _dispatch_to_channel(db, channel_model, msg, event_type)
            deliveries.append(delivery)
```

Add helper at module level:

```python
from app.models.iam import User


async def _get_user_cached(
    db: AsyncSession,
    user_id: UUID,
    cache: dict[UUID, User],
) -> User | None:
    if user_id in cache:
        return cache[user_id]
    user = await db.get(User, user_id)
    cache[user_id] = user
    return user
```

Note: `html_body` is added to `FormattedMessage` in Task 13. For now keep `html_body=getattr(message_personal, "html_body", None)` so this commit doesn't depend on Task 13 ordering; refactor to direct attribute access after Task 13 lands.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_dispatcher_email_recipient.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/dispatcher.py backend/tests/unit/test_dispatcher_email_recipient.py
git commit -m "feat(TD-0091c): dispatcher resolves EMAIL recipient from channel.config.to"
```

### Task 11: Add verified-email gate

**Files:**
- Modify: `backend/app/services/core/notifications/dispatcher.py` (already done in Task 10 — write tests for it now)
- Test: `backend/tests/unit/test_dispatcher_email_verified_gate.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_dispatcher_email_verified_gate.py
import pytest
from sqlalchemy import select

from app.models.iam import User, Organization, OrganizationMember
from app.models.notifications import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
)
from app.services.core.notifications import send_notification


@pytest.fixture
async def org_and_member(db_session):
    org = Organization(name="Test Org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest.fixture
async def unverified_user_with_channel(db_session, org_and_member):
    user = User(email="unverified@example.com", email_verified=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=org_and_member.id, roles=["MEMBER"]
    ))
    channel = NotificationChannel(
        user_id=user.id,
        name="Email",
        channel_type="EMAIL",
        config={"to": user.email},
        enabled=True,
        is_default=True,
    )
    db_session.add(channel)
    await db_session.flush()
    db_session.add(NotificationSubscription(
        channel_id=channel.id, event_type="ROLE_ASSIGNED", enabled=True,
    ))
    await db_session.commit()
    return user, org_and_member, channel


@pytest.mark.asyncio
async def test_unverified_user_skips_email_keeps_in_app(
    db_session, unverified_user_with_channel
):
    user, org, channel = unverified_user_with_channel
    await send_notification(
        db_session, "ROLE_ASSIGNED", org.id, "run", org.id, [user.id],
        {"run_name": "R1", "role_name": "Operator", "assigned_by": "Alice"},
    )

    notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert len(notifs) == 1  # in-app row still written

    deliveries = (await db_session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.channel_id == channel.id
        )
    )).scalars().all()
    assert len(deliveries) == 0  # no EMAIL delivery attempted


@pytest.mark.asyncio
async def test_verified_user_dispatches_email(
    db_session, unverified_user_with_channel
):
    user, org, channel = unverified_user_with_channel
    user.email_verified = True
    await db_session.commit()

    await send_notification(
        db_session, "ROLE_ASSIGNED", org.id, "run", org.id, [user.id],
        {"run_name": "R1", "role_name": "Operator", "assigned_by": "Alice"},
    )

    deliveries = (await db_session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.channel_id == channel.id
        )
    )).scalars().all()
    assert len(deliveries) == 1
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_dispatcher_email_verified_gate.py -v`
Expected: PASS (logic was implemented in Task 10).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_dispatcher_email_verified_gate.py
git commit -m "test(TD-0091c): cover verified-email dispatch gate"
```

### Task 12: Extend `_get_subscribed_channels` to accept `user_ids`

**Files:**
- Modify: `backend/app/services/core/notifications/dispatcher.py`
- Test: `backend/tests/unit/test_subscriptions_batch_lookup.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_subscriptions_batch_lookup.py
import pytest
from unittest.mock import patch
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
)
from app.services.core.notifications.dispatcher import _get_subscribed_channels


@pytest.mark.asyncio
async def test_batch_lookup_returns_channels_for_multiple_users(db_session):
    users = []
    for i in range(3):
        u = User(email=f"u{i}@example.com", email_verified=True)
        db_session.add(u)
        await db_session.flush()
        c = NotificationChannel(
            user_id=u.id, name="Email", channel_type="EMAIL",
            config={"to": u.email}, enabled=True, is_default=True,
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(NotificationSubscription(
            channel_id=c.id, event_type="STEP_DEVIATION", enabled=True,
        ))
        users.append(u)
    await db_session.commit()

    channels = await _get_subscribed_channels(
        db_session, "STEP_DEVIATION",
        user_ids=[u.id for u in users],
    )
    assert {c.user_id for c in channels} == {u.id for u in users}


@pytest.mark.asyncio
async def test_batch_lookup_single_user_query_count(db_session):
    """One IN query, not N. Use the AsyncEngine's `before_cursor_execute`
    hook to count statements containing 'notification_channels'."""
    counter = {"n": 0}

    from sqlalchemy import event as sa_event
    from app.db.session import async_engine

    def _counter(conn, cursor, statement, parameters, context, executemany):
        if "notification_channels" in statement.lower():
            counter["n"] += 1

    sa_event.listen(async_engine.sync_engine, "before_cursor_execute", _counter)
    try:
        await _get_subscribed_channels(
            db_session, "STEP_DEVIATION",
            user_ids=[u.id for u in (
                await db_session.execute(select(User))
            ).scalars().all()],
        )
        assert counter["n"] == 1  # one IN query, not N
    finally:
        sa_event.remove(async_engine.sync_engine, "before_cursor_execute", _counter)
```

- [ ] **Step 2: Run — expected fail (signature mismatch)**

Run: `cd backend && pytest tests/unit/test_subscriptions_batch_lookup.py -v`
Expected: FAIL — `user_ids` is not a parameter.

- [ ] **Step 3: Extend the function**

In `backend/app/services/core/notifications/dispatcher.py`, replace `_get_subscribed_channels`:

```python
async def _get_subscribed_channels(
    db: AsyncSession,
    event_type: str,
    org_id: UUID | None = None,
    user_id: UUID | None = None,
    user_ids: list[UUID] | None = None,
) -> list[NotificationChannel]:
    """Find enabled channels with an active subscription for this event.

    `user_id` and `user_ids` are mutually exclusive convenience overloads —
    pass either. Both `org_id` and a user filter can be passed in different
    calls; this function does not combine them in one query.
    """
    stmt = (
        select(NotificationChannel)
        .join(NotificationSubscription)
        .where(NotificationChannel.enabled == True)
        .where(NotificationSubscription.event_type == event_type)
        .where(NotificationSubscription.enabled == True)
    )
    if org_id is not None:
        stmt = stmt.where(NotificationChannel.org_id == org_id)
    if user_id is not None:
        stmt = stmt.where(NotificationChannel.user_id == user_id)
    elif user_ids is not None:
        stmt = stmt.where(NotificationChannel.user_id.in_(user_ids))

    result = await db.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_subscriptions_batch_lookup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/dispatcher.py backend/tests/unit/test_subscriptions_batch_lookup.py
git commit -m "feat(TD-0091c): batch user-ids lookup in _get_subscribed_channels"
```

### Task 13: Add `html_body` field to `FormattedMessage` and propagate

**Files:**
- Modify: `backend/app/services/core/notifications/channels/base.py`
- Modify: `backend/app/services/core/notifications/__init__.py`

- [ ] **Step 1: Extend `FormattedMessage`**

In `backend/app/services/core/notifications/channels/base.py`:

```python
@dataclass
class FormattedMessage:
    event_type: str
    title: str
    body: str
    recipient: str
    url: str = ""
    html_body: str | None = None  # TD-0091c: rich-HTML body for EmailChannel
```

- [ ] **Step 2: Plumb through `send_notification`**

In `backend/app/services/core/notifications/__init__.py`, allow the template function to return an optional html body. Pattern: templates that need html return a 3-tuple `(title, body, html_body)`; legacy templates return a 2-tuple. Detect:

```python
result = template_fn(context, personal=True)
if len(result) == 3:
    title_personal, body_personal, html_body_personal = result
else:
    title_personal, body_personal = result
    html_body_personal = None

result = template_fn(context, personal=False)
if len(result) == 3:
    title_broadcast, body_broadcast, html_body_broadcast = result
else:
    title_broadcast, body_broadcast = result
    html_body_broadcast = None
```

And set on the FormattedMessage:

```python
msg_personal = FormattedMessage(
    event_type=event_type,
    title=title_personal,
    body=body_personal,
    recipient="",
    html_body=html_body_personal,
)
msg_broadcast = FormattedMessage(
    event_type=event_type,
    title=title_broadcast,
    body=body_broadcast,
    recipient="broadcast",
    html_body=html_body_broadcast,
)
```

- [ ] **Step 3: Update dispatcher to read direct attribute**

Now that Task 10's `getattr` fallback is no longer needed, in `dispatcher.py` change:

```python
html_body=getattr(message_personal, "html_body", None),
```

to:

```python
html_body=message_personal.html_body,
```

- [ ] **Step 4: Run existing notification tests to confirm no regression**

Run: `cd backend && pytest tests/unit/test_dispatcher_email_recipient.py tests/unit/test_dispatcher_email_verified_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/channels/base.py backend/app/services/core/notifications/__init__.py backend/app/services/core/notifications/dispatcher.py
git commit -m "feat(TD-0091c): plumb optional html_body through notification pipeline"
```

---

## Phase 7: EmailChannel — timeout, List-Unsubscribe, footer, html_body

Independent of all other phases. Can be reordered.

### Task 14: Add SMTP timeout + delivery-failed on timeout

**Files:**
- Modify: `backend/app/services/core/notifications/channels/email.py`
- Test: `backend/tests/unit/test_email_channel_smtp_timeout.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_email_channel_smtp_timeout.py
import asyncio
import pytest
from unittest.mock import patch

from app.services.core.notifications.channels.base import (
    FormattedMessage,
    TransientError,
)
from app.services.core.notifications.channels.email import EmailChannel


@pytest.mark.asyncio
async def test_smtp_timeout_raises_transient_error():
    channel = EmailChannel({"smtp_host": "1.2.3.4", "smtp_port": 25})
    msg = FormattedMessage(
        event_type="TEST", title="t", body="b", recipient="x@y",
    )

    async def boom(*a, **kw):
        raise asyncio.TimeoutError()

    with patch("aiosmtplib.send", side_effect=boom):
        with pytest.raises(TransientError, match="smtp_timeout"):
            await channel.send(msg)


@pytest.mark.asyncio
async def test_smtp_send_passes_timeout_kwarg():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    msg = FormattedMessage(
        event_type="TEST", title="t", body="b", recipient="x@y",
    )

    captured = {}

    async def fake_send(*args, **kwargs):
        captured.update(kwargs)
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(msg)
    assert captured.get("timeout") == 10
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/unit/test_email_channel_smtp_timeout.py -v`
Expected: FAIL — no timeout kwarg, no TimeoutError handler.

- [ ] **Step 3: Modify `EmailChannel.send`**

In `backend/app/services/core/notifications/channels/email.py`, in the `try/except`:

```python
        try:
            response = await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=use_tls,
                timeout=10,  # TD-0091c
            )
            return str(response)
        except aiosmtplib.SMTPAuthenticationError as e:
            raise PermanentError(f"SMTP auth failed: {e}") from e
        except aiosmtplib.SMTPRecipientsRefused as e:
            raise PermanentError(f"Invalid recipient: {e}") from e
        except (aiosmtplib.SMTPConnectError, TimeoutError, asyncio.TimeoutError) as e:
            raise TransientError(f"smtp_timeout: {e}") from e
        except aiosmtplib.SMTPException as e:
            raise TransientError(f"SMTP error: {e}") from e
```

Add `import asyncio` at the top of the file if not already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_email_channel_smtp_timeout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/channels/email.py backend/tests/unit/test_email_channel_smtp_timeout.py
git commit -m "feat(TD-0091c): add 10s SMTP timeout on EmailChannel send"
```

### Task 15: Add List-Unsubscribe header + footer

**Files:**
- Modify: `backend/app/services/core/notifications/channels/email.py`
- Test: `backend/tests/unit/test_email_channel_unsubscribe_header.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_email_channel_unsubscribe_header.py
import pytest
from unittest.mock import patch

from app.services.core.notifications.channels.base import FormattedMessage
from app.services.core.notifications.channels.email import EmailChannel


@pytest.mark.asyncio
async def test_send_includes_list_unsubscribe_header():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    msg = FormattedMessage(
        event_type="ROLE_ASSIGNED", title="t", body="b", recipient="x@y",
    )

    captured = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(msg)

    m = captured["message"]
    assert m["List-Unsubscribe"], "List-Unsubscribe header missing"
    assert "settings/notifications" in m["List-Unsubscribe"]
    assert m["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@pytest.mark.asyncio
async def test_send_html_body_contains_manage_preferences():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    msg = FormattedMessage(
        event_type="ROLE_ASSIGNED", title="t", body="b", recipient="x@y",
    )

    captured = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(msg)

    # Walk the MIME parts and find the html part
    html_part = next(
        p for p in captured["message"].walk()
        if p.get_content_type() == "text/html"
    )
    html = html_part.get_payload()
    assert "settings/notifications" in html
    assert "Manage preferences" in html


@pytest.mark.asyncio
async def test_send_uses_html_body_when_provided():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    msg = FormattedMessage(
        event_type="INVITE_SENT",
        title="t",
        body="plain body",
        recipient="x@y",
        html_body="<p>Custom <strong>html</strong> body</p>",
    )

    captured = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(msg)

    html_part = next(
        p for p in captured["message"].walk()
        if p.get_content_type() == "text/html"
    )
    html = html_part.get_payload()
    assert "Custom <strong>html</strong> body" in html
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/unit/test_email_channel_unsubscribe_header.py -v`
Expected: FAIL.

- [ ] **Step 3: Modify `EmailChannel.send`**

Replace the relevant section of `backend/app/services/core/notifications/channels/email.py`:

```python
import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings
from app.services.core.notifications.channels.base import (
    BaseChannel,
    FormattedMessage,
    PermanentError,
    TransientError,
)

logger = logging.getLogger("notifications.email")


def _unsubscribe_url() -> str:
    return f"{settings.frontend_url}/settings/notifications"


def _footer_html() -> str:
    url = _unsubscribe_url()
    return (
        f'<hr style="border: none; border-top: 1px solid #e5e7eb; margin-top: 24px;">'
        f'<p style="color: #9ca3af; font-size: 12px;">'
        f'Batchrite — Laboratory Execution System<br>'
        f'<a href="{url}" style="color: #9ca3af;">Manage preferences</a>'
        f'</p>'
    )


def _footer_text() -> str:
    return f"\n\n—\nManage preferences: {_unsubscribe_url()}"


class EmailChannel(BaseChannel):
    """SMTP email channel.

    Config:
        smtp_host (str): SMTP server hostname. Default: localhost.
        smtp_port (int): SMTP server port. Default: 1025 (Mailpit dev).
        smtp_user (str): Optional. SMTP username.
        smtp_pass (str): Optional. SMTP password.
        use_tls (bool): Use STARTTLS. Default: False.
        from_address (str): Sender address. Default: noreply@batchrite.local.
    """

    async def send(self, message: FormattedMessage) -> str:
        host = self.config.get("smtp_host", "localhost")
        port = self.config.get("smtp_port", 1025)
        user = self.config.get("smtp_user")
        password = self.config.get("smtp_pass")
        use_tls = self.config.get("use_tls", False)
        from_addr = self.config.get("from_address", "noreply@batchrite.local")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.title
        msg["From"] = from_addr
        msg["To"] = message.recipient
        # TD-0091c: CAN-SPAM/GDPR-aligned one-click unsubscribe headers.
        msg["List-Unsubscribe"] = f"<{_unsubscribe_url()}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        text_body = message.body
        if message.url:
            text_body += f"\n\nView in Batchrite: {message.url}"
        text_body += _footer_text()

        if message.html_body:
            html_body = message.html_body + _footer_html()
        else:
            html_body = f"""<div style="font-family: sans-serif; max-width: 600px;">
  <h2 style="color: #1a1a1a;">{message.title}</h2>
  <p style="color: #333; line-height: 1.6;">{message.body}</p>
  {"<p><a href='" + message.url + "' style='color: #2563eb;'>View in Batchrite</a></p>" if message.url else ""}
  {_footer_html()}
</div>"""

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            response = await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=use_tls,
                timeout=10,
            )
            return str(response)
        except aiosmtplib.SMTPAuthenticationError as e:
            raise PermanentError(f"SMTP auth failed: {e}") from e
        except aiosmtplib.SMTPRecipientsRefused as e:
            raise PermanentError(f"Invalid recipient: {e}") from e
        except (aiosmtplib.SMTPConnectError, TimeoutError, asyncio.TimeoutError) as e:
            raise TransientError(f"smtp_timeout: {e}") from e
        except aiosmtplib.SMTPException as e:
            raise TransientError(f"SMTP error: {e}") from e
```

- [ ] **Step 4: Run all email-channel tests**

Run: `cd backend && pytest tests/unit/test_email_channel_unsubscribe_header.py tests/unit/test_email_channel_smtp_timeout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/channels/email.py backend/tests/unit/test_email_channel_unsubscribe_header.py
git commit -m "feat(TD-0091c): add List-Unsubscribe header and manage-preferences footer"
```

---

## Phase 8: Invite handling — reroute existing-user invites + INVITE_ACCEPTED

### Task 16: Shared `_invite_html` template helper

**Files:**
- Modify: `backend/app/services/core/notifications/templates.py`
- Modify: `backend/app/services/core/email_service.py` (use the shared helper)

- [ ] **Step 1: Add the helper + 3-tuple `invite_sent` template**

In `backend/app/services/core/notifications/templates.py`, before `invite_sent`:

```python
from app.core.config import settings


def _invite_html(org_name: str, invited_by: str, accept_url: str, expires_at: str | None) -> str:
    """Shared HTML body for INVITE_SENT. Used by both the in-app channel
    pipeline and the direct send_invitation_email path so the recipient
    sees byte-identical markup."""
    expiry_line = (
        f'<p style="color: #999; font-size: 12px;">'
        f'This invitation expires on {expires_at}.'
        f'</p>'
        if expires_at else ""
    )
    return f"""<div style="font-family: sans-serif; max-width: 600px;">
  <h2 style="color: #1a1a1a;">You've been invited to join {org_name}</h2>
  <p style="color: #333; line-height: 1.6;">
    {invited_by} has invited you to join <strong>{org_name}</strong> on Batchrite.
  </p>
  <p style="margin: 24px 0;">
    <a href="{accept_url}"
       style="background: #2563eb; color: white; padding: 12px 24px;
              border-radius: 6px; text-decoration: none; font-weight: 500;">
      Accept Invitation
    </a>
  </p>
  <p style="color: #666; font-size: 13px;">
    Or copy this link: {accept_url}
  </p>
  {expiry_line}
</div>"""
```

Modify `invite_sent`:

```python
def invite_sent(ctx: dict, personal: bool = True):
    """ctx: org_name, invited_by, accept_url (optional), expires_at (optional)."""
    org_name = ctx["org_name"]
    invited_by = ctx["invited_by"]
    accept_url = ctx.get("accept_url")
    expires_at = ctx.get("expires_at")

    title = f"Invitation to {org_name}"
    body = f"You've been invited to join {org_name} by {invited_by}."

    if accept_url:
        html = _invite_html(org_name, invited_by, accept_url, expires_at)
        return title, body, html
    # Fall back to 2-tuple when no accept_url (e.g. in-app only)
    return title, body
```

- [ ] **Step 2: Refactor `email_service.send_invitation_email` to use the helper**

In `backend/app/services/core/email_service.py`, replace the inline html_body with:

```python
from app.services.core.notifications.templates import _invite_html

# inside send_invitation_email:
expiry = (
    datetime.now(timezone.utc) + timedelta(days=settings.invitation_ttl_days)
).date().isoformat()
html_body = _invite_html(org_name, inviter_name, accept_url, expiry)
```

(Verify `datetime` and `timedelta` are imported in `email_service.py`; add if missing.)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/core/notifications/templates.py backend/app/services/core/email_service.py
git commit -m "refactor(TD-0091c): share INVITE_SENT html between channel pipeline and direct send"
```

### Task 17: Reroute `create_invitation` and `resend_invitation`

**Files:**
- Modify: `backend/app/api/endpoints/iam.py`
- Test: `backend/tests/integration/test_invite_existing_user.py`, `backend/tests/integration/test_invite_new_email.py`

- [ ] **Step 1: Write failing integration tests**

```python
# backend/tests/integration/test_invite_existing_user.py
import pytest
from unittest.mock import patch
from sqlalchemy import select

from app.models.iam import User, Organization
from app.models.notifications import (
    Notification,
    NotificationDelivery,
    DeliveryStatus,
)


@pytest.mark.asyncio
async def test_invite_to_existing_user_creates_in_app_and_email_via_channel(
    authed_admin_client, seed_org_admin, db_session
):
    # seed_org_admin sets up an org and returns the admin user + org
    admin, org = seed_org_admin
    existing = User(email="invitee@example.com", email_verified=True,
                    full_name="Existing User")
    db_session.add(existing)
    await db_session.flush()
    await db_session.commit()

    with patch(
        "app.services.core.email_service.send_invitation_email"
    ) as mock_direct:
        resp = await authed_admin_client.post(
            f"/iam/organizations/{org.id}/invitations",
            json={"email": "invitee@example.com", "role": "MEMBER"},
        )
        assert resp.status_code == 201
    mock_direct.assert_not_called()

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == existing.id,
            Notification.event_type == "INVITE_SENT",
        )
    )).scalars().all()
    assert len(notifs) == 1

    # One delivery for the user's auto-provisioned EMAIL channel
    deliveries = (await db_session.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.event_type == "INVITE_SENT",
        )
    )).scalars().all()
    assert any(d.recipient_info.get("recipient") == "invitee@example.com"
               for d in deliveries)
```

```python
# backend/tests/integration/test_invite_new_email.py
import pytest
from unittest.mock import patch
from sqlalchemy import select

from app.models.notifications import Notification


@pytest.mark.asyncio
async def test_invite_to_new_email_uses_direct_send(
    authed_admin_client, seed_org_admin, db_session
):
    admin, org = seed_org_admin
    with patch(
        "app.services.core.email_service.send_invitation_email"
    ) as mock_direct:
        resp = await authed_admin_client.post(
            f"/iam/organizations/{org.id}/invitations",
            json={"email": "noaccount@example.com", "role": "MEMBER"},
        )
        assert resp.status_code == 201
    mock_direct.assert_called_once()

    notifs = (await db_session.execute(
        select(Notification).where(Notification.event_type == "INVITE_SENT")
    )).scalars().all()
    assert len(notifs) == 0  # no in-app row for non-user
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/integration/test_invite_existing_user.py tests/integration/test_invite_new_email.py -v`
Expected: FAIL (existing-user branch still calls direct send).

- [ ] **Step 3: Modify `create_invitation`**

In `backend/app/api/endpoints/iam.py`, replace lines 582-590 (the `send_invitation_email` call at end of `create_invitation`):

```python
    # TD-0091c: route existing-user invites through the channel pipeline;
    # new-email invites still go direct (recipient has no user, no channel).
    if invitation.invited_user_id is not None:
        from app.services.core.notifications import send_notification

        background_tasks.add_task(
            send_notification,
            db,
            "INVITE_SENT",
            org_id,
            "organization",
            org.id,
            [invitation.invited_user_id],
            {
                "org_name": org.name,
                "invited_by": user.full_name or user.email,
                "accept_url": f"{settings.backend_url}/auth/accept-invite?token={token_str}",
                "expires_at": invitation.expires_at.date().isoformat(),
            },
        )
    else:
        from app.services.core.email_service import send_invitation_email

        await send_invitation_email(
            to_email=body.email,
            org_name=org.name,
            inviter_name=user.full_name or user.email,
            token=token_str,
        )

    return invitation
```

Add `background_tasks: BackgroundTasks` parameter to the endpoint signature:

```python
async def create_invitation(
    org_id: UUID,
    body: InvitationCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
```

Add `from fastapi import BackgroundTasks` to the imports if not already present.

- [ ] **Step 4: Modify `resend_invitation` identically**

In `backend/app/api/endpoints/iam.py:683` add `background_tasks: BackgroundTasks` to the signature and replace the `send_invitation_email` call at line 712 with the same conditional pattern. Use `invitation.invited_user_id` and `invitation.token` and `invitation.expires_at`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_invite_existing_user.py tests/integration/test_invite_new_email.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/iam.py backend/tests/integration/test_invite_existing_user.py backend/tests/integration/test_invite_new_email.py
git commit -m "feat(TD-0091c): route existing-user invites through notification channel pipeline"
```

### Task 18: Emit INVITE_ACCEPTED in `accept_invitation`

**Files:**
- Modify: `backend/app/api/endpoints/auth.py:579` area
- Test: `backend/tests/integration/test_invite_accepted.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_invite_accepted.py
import pytest
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import Notification


@pytest.mark.asyncio
async def test_invite_accepted_notifies_inviter(
    client, seed_pending_invitation, db_session
):
    """seed_pending_invitation creates an invitation; invited_user already exists."""
    invitation, inviter, invited_user = seed_pending_invitation

    resp = await client.get(f"/auth/accept-invite?token={invitation.token}")
    assert resp.status_code in (302, 200)

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == inviter.id,
            Notification.event_type == "INVITE_ACCEPTED",
        )
    )).scalars().all()
    assert len(notifs) == 1
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/integration/test_invite_accepted.py -v`
Expected: FAIL.

- [ ] **Step 3: Emit INVITE_ACCEPTED in `accept_invitation`**

In `backend/app/api/endpoints/auth.py`, at line 579 right after `invitation.status = InvitationStatus.ACCEPTED` and before `await db.commit()`, add:

```python
    invitation.status = InvitationStatus.ACCEPTED
    await db.commit()

    # TD-0091c: notify the inviter that the invitee accepted.
    from app.services.core.notifications import send_notification
    org = await db.get(Organization, invitation.organization_id)
    background_tasks.add_task(
        send_notification,
        db,
        "INVITE_ACCEPTED",
        invitation.organization_id,
        "organization",
        invitation.organization_id,
        [invitation.invited_by],
        {
            "org_name": org.name if org else "your organization",
            "accepted_by": invited_user.full_name or invited_user.email,
        },
    )
```

Add `background_tasks: BackgroundTasks` to the `accept_invitation` signature. This is a GET endpoint that returns `HTMLResponse` or `RedirectResponse` — FastAPI permits `BackgroundTasks` injection on any endpoint.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_invite_accepted.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_invite_accepted.py
git commit -m "feat(TD-0091c): emit INVITE_ACCEPTED notification on invitation acceptance"
```

---

## Phase 9: Dead-event wiring (ROLE_UNASSIGNED, STEP_DEVIATION)

INVITE_SENT and INVITE_ACCEPTED were handled in Phase 8. This phase covers the remaining two.

### Task 19: Emit ROLE_UNASSIGNED

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:1411-1459` (`delete_run_role_assignment`)
- Test: `backend/tests/integration/test_role_unassigned_notification.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_role_unassigned_notification.py
import pytest
from sqlalchemy import select

from app.models.notifications import Notification


@pytest.mark.asyncio
async def test_role_unassigned_emits_notification(
    authed_client, seed_run_with_role_assignment, db_session
):
    """seed_run_with_role_assignment returns (actor, target_user, run, assignment)."""
    actor, target, run, assignment = seed_run_with_role_assignment

    resp = await authed_client.delete(
        f"/science/runs/{run.id}/role-assignments/{assignment.id}",
    )
    assert resp.status_code == 200

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == target.id,
            Notification.event_type == "ROLE_UNASSIGNED",
        )
    )).scalars().all()
    assert len(notifs) == 1
    assert run.name in notifs[0].message
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/integration/test_role_unassigned_notification.py -v`
Expected: FAIL.

- [ ] **Step 3: Emit ROLE_UNASSIGNED in the endpoint**

Modify `backend/app/api/endpoints/runs.py:delete_run_role_assignment`:

```python
@router.delete("/runs/{run_id}/role-assignments/{assignment_id}")
async def delete_run_role_assignment(
    run_id: UUID,
    assignment_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Remove a user's role assignment."""
    allowed = await check_permission(
        db, user.id, ObjectType.RUN, run_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(RunRoleAssignment).where(
            and_(
                RunRoleAssignment.id == assignment_id,
                RunRoleAssignment.run_id == run_id,
            )
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    assignment_data = {
        "run_id": str(assignment.run_id),
        "user_id": str(assignment.user_id),
        "lane_node_id": assignment.lane_node_id,
        "role_name": assignment.role_name,
    }
    removed_user_id = assignment.user_id
    role_name = assignment.role_name

    # Fetch the run for context before we delete the assignment
    run_obj = await db.get(Run, run_id)

    await db.delete(assignment)
    await db.commit()
    await log_audit(
        db, user.id, "DELETE", "RunRoleAssignment", assignment_id, assignment_data,
    )

    # TD-0091c: notify the removed user
    if run_obj is not None:
        from app.services.core.notifications import send_notification
        background_tasks.add_task(
            send_notification,
            db,
            "ROLE_UNASSIGNED",
            run_obj.org_id,
            "run",
            run_obj.id,
            [removed_user_id],
            {
                "run_name": run_obj.name,
                "role_name": role_name,
                "removed_by": user.full_name or user.email,
            },
        )

    return {"ok": True}
```

Add `BackgroundTasks` to imports if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_role_unassigned_notification.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_role_unassigned_notification.py
git commit -m "feat(TD-0091c): emit ROLE_UNASSIGNED on role assignment deletion"
```

### Task 20: Emit STEP_DEVIATION in `update_run`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py` (EDITED branch ~lines 645-753)
- Test: `backend/tests/integration/test_step_deviation_notification.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_step_deviation_notification.py
import pytest
from sqlalchemy import select

from app.models.notifications import Notification
from app.services.permissions import check_permission, PermissionLevel
from app.models.permissions import ObjectType


@pytest.mark.asyncio
async def test_step_deviation_notifies_other_assignees(
    authed_client, seed_edited_run_with_multiple_assignees, db_session
):
    """seed_edited_run_with_multiple_assignees: returns
       (actor, [assignees], run) where the run is already in EDITED status."""
    actor, assignees, run = seed_edited_run_with_multiple_assignees

    new_exec = dict(run.execution_data or {})
    # Pick a step id and tweak a results value
    step_id, step_data = next(iter(new_exec.items()))
    step_data = dict(step_data)
    step_data["results"] = {**step_data.get("results", {}), "ph": "7.5"}
    new_exec[step_id] = step_data

    resp = await authed_client.put(
        f"/science/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200

    recipient_ids = {a.id for a in assignees if a.id != actor.id}
    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.event_type == "STEP_DEVIATION",
            Notification.user_id.in_(recipient_ids),
        )
    )).scalars().all()
    assert {n.user_id for n in notifs} == recipient_ids
    # Actor is not notified
    actor_notifs = (await db_session.execute(
        select(Notification).where(
            Notification.event_type == "STEP_DEVIATION",
            Notification.user_id == actor.id,
        )
    )).scalars().all()
    assert len(actor_notifs) == 0


@pytest.mark.asyncio
async def test_step_deviation_one_notification_per_request(
    authed_client, seed_edited_run_with_multiple_assignees, db_session
):
    actor, assignees, run = seed_edited_run_with_multiple_assignees

    new_exec = dict(run.execution_data or {})
    # Edit two steps
    step_ids = list(new_exec.keys())[:2]
    for sid in step_ids:
        s = dict(new_exec[sid])
        s["results"] = {**s.get("results", {}), "value": "changed"}
        new_exec[sid] = s

    resp = await authed_client.put(
        f"/science/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200

    target = next(a for a in assignees if a.id != actor.id)
    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == target.id,
            Notification.event_type == "STEP_DEVIATION",
        )
    )).scalars().all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_step_deviation_skips_revoked_permission_assignees(
    authed_client, seed_edited_run_with_revoked_assignee, db_session,
    monkeypatch,
):
    """A user whose VIEW permission was revoked is excluded from recipients,
    even if the RunRoleAssignment row still exists."""
    actor, kept, revoked, run = seed_edited_run_with_revoked_assignee

    new_exec = dict(run.execution_data or {})
    sid, s = next(iter(new_exec.items()))
    s = dict(s)
    s["results"] = {**s.get("results", {}), "value": "x"}
    new_exec[sid] = s

    resp = await authed_client.put(
        f"/science/runs/{run.id}",
        json={"execution_data": new_exec},
    )
    assert resp.status_code == 200

    notif_users = {
        n.user_id for n in (await db_session.execute(
            select(Notification).where(Notification.event_type == "STEP_DEVIATION")
        )).scalars().all()
    }
    assert kept.id in notif_users
    assert revoked.id not in notif_users
```

- [ ] **Step 2: Run — expected fail**

Run: `cd backend && pytest tests/integration/test_step_deviation_notification.py -v`
Expected: FAIL — no notification produced.

- [ ] **Step 3: Emit STEP_DEVIATION in the EDITED branch**

In `backend/app/api/endpoints/runs.py:update_run`, near the END of the EDITED-status block (after the field-by-field audit logging completes, before the next sibling block), collect the deviated step IDs as the loop runs. Modify the EDITED block:

```python
        if target_status == "EDITED":
            old_exec = run_obj.execution_data or {}
            new_exec = update_data.execution_data

            step_index = index_steps(run_obj.graph)
            deviated_step_ids: list[str] = []  # TD-0091c

            for step_id, new_step in new_exec.items():
                if not isinstance(new_step, dict):
                    continue
                old_step = old_exec.get(step_id, {})
                if not isinstance(old_step, dict):
                    continue

                node_data = step_index.nodes.get(step_id, {})
                step_name = node_data.get("label", step_id)
                param_schema_props = (node_data.get("paramSchema") or {}).get("properties", {})

                old_results = old_step.get("results", {})
                new_results = new_step.get("results", {})

                # Track any results-level deviation for the notification
                step_changed = (
                    (old_results and new_results != old_results)
                    or (old_step.get("value") and new_step.get("value") != old_step.get("value"))
                    or (old_step.get("notes", "") != new_step.get("notes", ""))
                )
                if step_changed:
                    deviated_step_ids.append(step_id)

                # ... (rest of audit-logging body unchanged)

            # TD-0091c: one STEP_DEVIATION notification per request
            if deviated_step_ids:
                first_step_id = deviated_step_ids[0]
                additional = len(deviated_step_ids) - 1
                recipients = await _collect_step_deviation_recipients(
                    db, run_obj, actor_user_id=user.id,
                )
                if recipients:
                    from app.services.core.notifications import send_notification
                    background_tasks.add_task(
                        send_notification,
                        db,
                        "STEP_DEVIATION",
                        run_obj.org_id,
                        "run",
                        run_obj.id,
                        recipients,
                        {
                            "run_name": run_obj.name,
                            "step_name": step_index.name_for(first_step_id),
                            "edited_by": user.full_name or user.email,
                            "additional_count": additional,
                        },
                    )
```

Add helper near the top of `runs.py`:

```python
async def _collect_step_deviation_recipients(
    db: AsyncSession,
    run_obj: Run,
    actor_user_id: UUID,
) -> list[UUID]:
    """Return run assignees (excluding the actor) who currently have VIEW
    permission on the run. Filters out users whose permission was revoked
    but whose RunRoleAssignment row was not cleaned up."""
    rows = (
        await db.execute(
            select(RunRoleAssignment.user_id)
            .where(RunRoleAssignment.run_id == run_obj.id)
            .distinct()
        )
    ).scalars().all()

    recipients: list[UUID] = []
    for uid in rows:
        if uid == actor_user_id:
            continue
        ok = await check_permission(
            db, uid, ObjectType.RUN, run_obj.id, PermissionLevel.VIEW,
        )
        if ok:
            recipients.append(uid)
    return recipients
```

Ensure `update_run` has `background_tasks: BackgroundTasks` injected (it likely does already given other emit sites in this file; verify and add if missing).

Update `step_deviation` template in `templates.py` to handle `additional_count`:

```python
def step_deviation(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """ctx: run_name, step_name, edited_by, additional_count (optional)"""
    title = f"Step deviation on {ctx['run_name']}"
    body = (
        f"Step \"{ctx['step_name']}\" on run {ctx['run_name']} was edited "
        f"post-completion by {ctx['edited_by']}."
    )
    extra = ctx.get("additional_count", 0)
    if extra:
        body += f" ({extra} other step{'s' if extra != 1 else ''} also changed.)"
    return title, body
```

- [ ] **Step 4: Run the test**

Run: `cd backend && pytest tests/integration/test_step_deviation_notification.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/app/services/core/notifications/templates.py backend/tests/integration/test_step_deviation_notification.py
git commit -m "feat(TD-0091c): emit STEP_DEVIATION on post-completion edits"
```

---

## Phase 10: Enum cleanup — delete `OFFLINE_VALUE_DISCREPANCY`

### Task 21: Remove enum value, template, and registry entry

**Files:**
- Modify: `backend/app/models/notifications.py:46`
- Modify: `backend/app/services/core/notifications/templates.py`
- Modify: `backend/tests/unit/test_notification_policy.py` (un-skip exhaustiveness test)

- [ ] **Step 1: Grep for any remaining references**

Run: `cd backend && grep -rn "OFFLINE_VALUE_DISCREPANCY\|offline_value_discrepancy" app tests 2>/dev/null`
Expected output:
```
app/models/notifications.py:    OFFLINE_VALUE_DISCREPANCY = "OFFLINE_VALUE_DISCREPANCY"
app/services/core/notifications/templates.py:def offline_value_discrepancy(...)
app/services/core/notifications/templates.py:    "OFFLINE_VALUE_DISCREPANCY": offline_value_discrepancy,
```

Verify nothing in `tests/` other than the policy test references it. If a test references the constant, update or delete the test (it cannot be relevant once the constant is gone).

- [ ] **Step 2: Delete the enum member**

In `backend/app/models/notifications.py`, remove line 46:

```python
    OFFLINE_VALUE_DISCREPANCY = "OFFLINE_VALUE_DISCREPANCY"
```

- [ ] **Step 3: Delete the template function and registry entry**

In `backend/app/services/core/notifications/templates.py`, delete the entire `offline_value_discrepancy` function (lines 168-176) and the registry entry `"OFFLINE_VALUE_DISCREPANCY": offline_value_discrepancy,`.

- [ ] **Step 4: Un-skip the policy exhaustiveness test**

In `backend/tests/unit/test_notification_policy.py`, remove the `@pytest.mark.skip(...)` decorator added in Task 3.

- [ ] **Step 5: Run all notification tests**

Run: `cd backend && pytest tests/unit/test_notification_policy.py tests/unit/test_notification_provisioning.py -v`
Expected: PASS (exhaustiveness test now passes).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/notifications.py backend/app/services/core/notifications/templates.py backend/tests/unit/test_notification_policy.py
git commit -m "chore(TD-0091c): remove OFFLINE_VALUE_DISCREPANCY enum + template"
```

---

## Phase 11: Gating consistency on `mark_read` endpoints

### Task 22: Remove `require_active_subscription` from read-side endpoints

**Files:**
- Modify: `backend/app/api/endpoints/notifications.py:491-495`, `:510-513`
- Test: `backend/tests/integration/test_notifications_gating.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_notifications_gating.py
import pytest
from sqlalchemy import select

from app.models.notifications import Notification


@pytest.mark.asyncio
async def test_lapsed_user_can_read_and_dismiss(
    lapsed_subscriber_client, seed_notification_for_user, db_session
):
    """lapsed_subscriber_client is authed as a user whose org is past_due.
    seed_notification_for_user inserts one Notification row for that user.
    """
    user, notif = seed_notification_for_user

    # list_notifications
    resp = await lapsed_subscriber_client.get("/notifications/")
    assert resp.status_code == 200

    # unread_count
    resp = await lapsed_subscriber_client.get("/notifications/unread-count")
    assert resp.status_code == 200

    # mark_read
    resp = await lapsed_subscriber_client.put(f"/notifications/{notif.id}/read")
    assert resp.status_code == 200

    # mark_all_read
    resp = await lapsed_subscriber_client.put("/notifications/read-all")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_lapsed_user_cannot_create_channel(
    lapsed_subscriber_client,
):
    resp = await lapsed_subscriber_client.post(
        "/notifications/channels/me",
        json={"name": "My Slack", "channel_type": "SLACK",
              "config": {"webhook_url": "https://hooks.slack.com/..."}},
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_lapsed_user_cannot_create_subscription(
    lapsed_subscriber_client, seed_user_channel,
):
    channel = seed_user_channel
    resp = await lapsed_subscriber_client.post(
        f"/notifications/channels/{channel.id}/subscriptions",
        json={"event_type": "ROLE_ASSIGNED", "enabled": True},
    )
    assert resp.status_code == 402
```

- [ ] **Step 2: Run — expected fail on the read endpoints**

Run: `cd backend && pytest tests/integration/test_notifications_gating.py -v`
Expected: `test_lapsed_user_can_read_and_dismiss` FAILs on `mark_read` and `mark_all_read` (they currently return 402).

- [ ] **Step 3: Remove gating from mark_read and mark_all_read**

In `backend/app/api/endpoints/notifications.py`, modify both endpoints:

```python
@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a notification as read."""
    # ... body unchanged


@router.put("/read-all", status_code=204)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read."""
    # ... body unchanged
```

Delete the `_: User = Depends(require_active_subscription())` line from each.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_notifications_gating.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/notifications.py backend/tests/integration/test_notifications_gating.py
git commit -m "fix(TD-0091c): allow lapsed subscribers to mark notifications read"
```

---

## Final integration

### Task 23: Run the full backend suite

- [ ] **Step 1: Run all tests**

Run: `cd backend && pytest -v 2>&1 | tail -50`
Expected: All pass. Diagnose any unrelated test that broke (most likely place: existing run-update tests after the `index_steps` refactor; existing notification tests after the `html_body` plumbing).

- [ ] **Step 2: Run the linters**

Run: `cd backend && black --check app tests && isort --check-only app tests && mypy app 2>&1 | tail -20`
Note: per the memory file, this repo is **not black/isort-clean**. Only black/isort-format the files you touched, then commit any formatting changes separately:

```bash
cd backend && black app/services/core/notifications/policy.py \
  app/services/core/notifications/provisioning.py \
  app/services/core/notifications/dispatcher.py \
  app/services/core/notifications/channels/email.py \
  app/services/core/notifications/channels/base.py \
  app/services/core/notifications/templates.py \
  app/services/core/notifications/__init__.py \
  app/services/runs/graph.py \
  app/api/endpoints/notifications.py \
  app/models/notifications.py
```

- [ ] **Step 3: Commit any formatting**

```bash
git add -p
git commit -m "style(TD-0091c): format touched files"
```

### Task 24: Manual browser walk-through (handed off to qa-verify)

The qa-verify agent will be launched in the implement-task step 6b. Prepare the QA handoff context:

- **Login:** `admin@bioprocess.com` / `password123`
- **Worktree URL:** `http://localhost:<5173 + 10*N>` (from `.env` slot N)
- **What was implemented:**
  - Every new user automatically gets an in-app + email notification for invites, role assignments, run starts, approval requests, sign-off requests.
  - Existing-user invites now show up in the in-app inbox AND email.
  - Removing a user from a run notifies them.
  - Post-completion step edits notify other run assignees.
  - Settings → Notifications surface lets you opt out per event.
  - Reading notifications now works even on lapsed subscriptions.
- **Edge cases to walk through:**
  - Invite a new email (no existing account) — must still receive the styled invitation email with CTA button + expiry.
  - Invite an existing user — they get an in-app notification AND an email with CTA + expiry.
  - Disable INVITE_SENT subscription on the user → next invite produces in-app row only, no email.
  - Register a new user → check Settings → Notifications shows the default channel + 8 default subscriptions.
  - As a lapsed-subscription user (set the org to `past_due` in DB), open `/notifications` and dismiss one — should work; click "+ New channel" → should 402.
  - Email pulled from Mailpit (default dev SMTP at port 1025) shows `List-Unsubscribe` header and footer link.

---

## Self-Review

**1. Spec coverage:**

- §1 Delivery policy module → Task 3 ✓
- §2 Auto-provisioned user EMAIL channel → Tasks 5-7 ✓
- §3 Backfill migration → Tasks 4, 5, 9 ✓
- §4 User-signup hook → Task 7 ✓
- §5 Dispatcher fix + verified gate + batch lookup → Tasks 10-13 ✓
- §5b EmailChannel changes → Tasks 14-15 ✓
- §6 Invite handling + INVITE_SENT template parity → Tasks 16-18 ✓
- §7 Dead-event wiring (ROLE_UNASSIGNED, STEP_DEVIATION) → Tasks 19-20 ✓ (INVITE_SENT/ACCEPTED handled in Phase 8)
- §8 Enum cleanup → Task 21 ✓
- §9 Gating consistency → Task 22 ✓
- §10 DRY refactor → Tasks 1-2 ✓
- All 17 spec tests → mapped to Tasks 1, 3, 6, 7, 8, 10-20, 22 ✓

**2. Placeholder scan:** None — every step has explicit code or an explicit command.

**3. Type consistency:**

- `index_steps` returns `StepIndex`, fields `nodes`/`names`, methods `name_for` — consistent across Tasks 1, 2, 20.
- `DeliveryPolicy(in_app, email)`, `policy_for(event_type)` — consistent across Tasks 3, 6, 8.
- `ensure_default_user_channel(db, user)` and `provision_default_channel_for_user(user_id)` — consistent across Tasks 6, 7.
- `_resolve_personal_recipient(channel)`, `_get_user_cached(db, user_id, cache)`, `_get_subscribed_channels(..., user_ids=...)` — consistent across Tasks 10-13.
- `FormattedMessage(..., html_body=...)` — consistent across Tasks 13, 15.
- `_invite_html(org_name, invited_by, accept_url, expires_at)` — consistent across Task 16 and 17's context payload (`accept_url`, `expires_at` keys match).
- `_collect_step_deviation_recipients(db, run_obj, actor_user_id)` — defined and called in Task 20.

**4. Spec deviations called out:**

- The spec mentions `app/services/runs/graph_index.py` (§10) but the plan co-locates `index_steps` in the existing `graph.py` next to `iter_unit_op_nodes`. DRY improvement, kept the same exported name and tests.
- The spec mentions `settings.app_base_url` (§5b); the codebase has `settings.frontend_url` instead. Plan uses `settings.frontend_url`.
- The spec describes draining `pending_default_channels` from `connection.info` after request commit. **Review-panel amendment C** moves this to `session.info` in `app/db/session.py:get_db` (not `core/deps.py`), drains only after commit succeeds, and wraps the drain in try/except so it never breaks teardown.

**5. Review-panel amendments applied (see "Review-Panel Amendments" section above):**

| # | Concern | Resolution |
| --- | --- | --- |
| A | `send_notification` operates on closed request session | Refactor to open `AsyncSessionLocal()` internally; callers pass primitives only. |
| B | Wrong-file `get_db` edit | Modify `app/db/session.py:get_db`, not `core/deps.py`. |
| C | `connection.info` cross-request bleed | Use `session.info`; drain only after successful commit. |
| D | `await runner.submit(...)` TypeError | Drop the `await`. |
| E | `async_session_factory` import error | Use `AsyncSessionLocal` from `app.db.session`. |
| F | `ensure_default_user_channel` rollback bomb | Use `async with db.begin_nested()` SAVEPOINT. |
| G | EMAIL `config["to"]` tampering | For `is_default=True`, read `User.email`; ignore config.to. |
| H | SSO users gated out | Accept `email_verified OR oauth_email_verified`. |
| I | STEP_DEVIATION N+1 check_permission | 4-query batch (admins + ObjectPermission IN-query). |
| J | Missing `run_id` index | Add `ix_run_role_assign_run_id` in Task 5. |
| K | Batched subscription lookup misused | Move call outside per-user loop, group by user_id. |
| L | Partial index too aggressive | Narrow predicate to `is_default = TRUE`. |
| M | `_invite_html` HTML injection | `html.escape()` all dynamic; validate `accept_url` host. Rename to `invite_html`. |
| N | List-Unsubscribe-Post: One-Click broken | Ship `mailto:` only; defer one-click to follow-up. |
| O | No email kill switch | Add `BATCHRITE_NOTIFICATION_EMAIL_ENABLED` env var. |
| P | 3-tuple template polymorphism | Introduce `TemplateResult` dataclass. |
| Q | Migration alignment regex too loose | Anchor to `NotificationEventType` members. |
| R | Backfill silent skips | Log row counts after each pass. |
| S | Recipient-set negative test missing | Add `test_step_deviation_recipients_negative.py`. |
| T | Task ordering inside Phase 6 | Strict order: Task 12 → 10, Task 13 → 16, Task 5 → 6 → 9. |
| U | Unverified scope assumptions | Confirm `accept_invitation` / `update_run` accept `BackgroundTasks` before implementing. |

**Reviewer findings explicitly NOT applied (deferred to follow-up tickets):**

- Structured `user_id`/`entity_id` fields on failure-path logs (TECH_DEBT).
- Prometheus/OTEL counters for SMTP outcomes (TECH_DEBT).
- `asyncio.Semaphore` cap on concurrent SMTP sends per dispatch (TECH_DEBT).
- Bulk-hydrate `User` rows before the channel loop (TECH_DEBT — current PK lookups are fast enough for expected team sizes).
- Signed-token POST endpoint for `List-Unsubscribe-Post: One-Click` (TECH_DEBT — paired with N).
- Tighten retry sweep drain rate (TECH_DEBT — observed need TBD).
- `pg_index.indisvalid` runbook check on the DDL migration (TECH_DEBT).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-td-0091c-notification-delivery-model.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for 24 tasks across 11 phases.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
