# TD-0091a — Notification System Critical Bug Fixes (P0/P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four P0/P1 defects from the 2026-05-21 notification-system QA audit — the Settings infinite request loop, the orphaned delivery retry path, the missing `PROTOCOL_APPROVAL_REQUESTED` enum value, and `_get_user_org_id` ignoring `selected_org_id`.

**Architecture:** Four independent bug fixes. Backend: add one enum value, harden + wire the `retry_pending` sweep into the existing recovery loop, and make org resolution honor `selected_org_id`. Frontend: replace a self-retriggering `$effect` guard with a one-shot latch and add a missing event type to the picker. No DB migration, no new dependencies, no new config or feature flags.

**Tech Stack:** FastAPI (async) + SQLAlchemy 2.0 (async/asyncpg) backend; Svelte 5 Runes frontend; pytest-asyncio; PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-05-21-td-0091a-notification-critical-bug-fixes-design.md`

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `backend/app/models/notifications.py` | ORM models + enums | Add `PROTOCOL_APPROVAL_REQUESTED` to `NotificationEventType` |
| `backend/app/services/core/notifications/dispatcher.py` | Dispatch + retry engine | Harden `retry_pending`: `selectinload`, `ORDER BY`, per-row error isolation |
| `backend/app/main.py` | App lifespan + recovery loop | Add `_retry_pending_deliveries()`, wire it into `_recovery_loop()` |
| `backend/app/core/config.py` | Settings | Docstring: `recovery_interval_seconds <= 0` also disables delivery retries |
| `backend/app/api/endpoints/notifications.py` | Notification API | `_get_user_org_id(db, user)` honors `selected_org_id`; update 3 callers |
| `frontend/src/routes/settings/+page.svelte` | Settings page | `channelsLoaded` latch; effect + loading-branch guard; dedupe tab `onclick`; add event type |
| `backend/tests/unit/test_notifications.py` | Service-layer unit tests | Bidirectional enum↔TEMPLATES test; `retry_pending` happy/failure/batch tests; `_retry_pending_deliveries` sweep test |
| `backend/tests/integration/test_notification_api.py` | API integration tests | `selected_org_id` resolution tests; `PROTOCOL_APPROVAL_REQUESTED` subscription test |

Tasks 1, 3, 4, 5 are backend with automated tests (TDD). Task 5 additionally has an import smoke check for the recovery-loop wiring (the loop itself is not unit-tested). Tasks 2 and 6 are frontend with no automated test — verified in the `/implement-task` browser-QA step.

Recommended execution order: Task 1 → 2 → 3 → 4 → 5 → 6. Tasks are independent; this order does easy/low-risk first and groups the two `retry_pending` tasks (4 then 5) together.

---

## Task 1: Fix 3 — Add `PROTOCOL_APPROVAL_REQUESTED` to the event-type enum

**Files:**
- Modify: `backend/app/models/notifications.py:31-44`
- Test: `backend/tests/unit/test_notifications.py:20-25`

The `TEMPLATES` registry has 14 entries; `NotificationEventType` has 13 — missing `PROTOCOL_APPROVAL_REQUESTED`. The event is emitted by `protocol_versions.py` and renders in-app, but `_validate_event_type` rejects it, so no external channel can subscribe to it.

- [ ] **Step 1: Rewrite the template-sync test as a bidirectional set-equality assertion**

In `backend/tests/unit/test_notifications.py`, replace the existing `test_all_event_types_have_templates` method (currently lines 21-25) inside `class TestTemplates`:

```python
    def test_all_event_types_have_templates(self):
        """Enum and TEMPLATES must stay in exact sync — drift either way fails."""
        from app.models.notifications import NotificationEventType

        enum_values = {e.value for e in NotificationEventType}
        template_keys = set(TEMPLATES.keys())
        assert enum_values == template_keys, (
            f"enum-only: {enum_values - template_keys}; "
            f"template-only: {template_keys - enum_values}"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestTemplates::test_all_event_types_have_templates -v`
Expected: FAIL — `AssertionError` with `template-only: {'PROTOCOL_APPROVAL_REQUESTED'}` (the enum is missing the value present in TEMPLATES).

- [ ] **Step 3: Add the enum value**

In `backend/app/models/notifications.py`, add the new member to `NotificationEventType` immediately after `PROTOCOL_REVERTED` (line 40):

```python
class NotificationEventType(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    ROLE_UNASSIGNED = "ROLE_UNASSIGNED"
    ROLE_REASSIGNED = "ROLE_REASSIGNED"
    INVITE_SENT = "INVITE_SENT"
    INVITE_ACCEPTED = "INVITE_ACCEPTED"
    PROTOCOL_APPROVED = "PROTOCOL_APPROVED"
    PROTOCOL_REVERTED = "PROTOCOL_REVERTED"
    PROTOCOL_APPROVAL_REQUESTED = "PROTOCOL_APPROVAL_REQUESTED"
    STEP_DEVIATION = "STEP_DEVIATION"
    PENDING_IMAGE_ANALYSIS = "PENDING_IMAGE_ANALYSIS"
    OFFLINE_SYNC_PENDING = "OFFLINE_SYNC_PENDING"
    OFFLINE_VALUE_DISCREPANCY = "OFFLINE_VALUE_DISCREPANCY"
```

No migration: the `event_type` columns on `NotificationSubscription`, `Notification`, and `NotificationDelivery` are `String`, not a Postgres enum type — the enum is a Python-side value set only.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestTemplates -v`
Expected: PASS — enum and TEMPLATES sets are now equal.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/notifications.py backend/tests/unit/test_notifications.py
git commit -m "fix(TD-0091a): add PROTOCOL_APPROVAL_REQUESTED to NotificationEventType"
```

---

## Task 2: Fix 3 — Add `PROTOCOL_APPROVAL_REQUESTED` to the frontend event picker

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte:79-90`

The backend fix alone leaves the event unsubscribable in the UI: the `EVENT_TYPES` array drives the subscription checkboxes, and it stops at `STEP_DEVIATION`. Without this entry the backend would accept the subscription but the UI would never render the checkbox.

This task has no automated test — it is verified in the browser-QA step (Task 6's QA pass covers the Notifications tab).

- [ ] **Step 1: Add the event type to `EVENT_TYPES`**

In `frontend/src/routes/settings/+page.svelte`, add the entry to the `EVENT_TYPES` array immediately after `PROTOCOL_REVERTED` (line 88):

```javascript
    const EVENT_TYPES = [
        { value: 'RUN_STARTED', label: 'Run Started' },
        { value: 'RUN_COMPLETED', label: 'Run Completed' },
        { value: 'ROLE_ASSIGNED', label: 'Role Assigned' },
        { value: 'ROLE_UNASSIGNED', label: 'Role Unassigned' },
        { value: 'ROLE_REASSIGNED', label: 'Role Reassigned' },
        { value: 'INVITE_SENT', label: 'Invite Sent' },
        { value: 'INVITE_ACCEPTED', label: 'Invite Accepted' },
        { value: 'PROTOCOL_APPROVED', label: 'Protocol Approved' },
        { value: 'PROTOCOL_REVERTED', label: 'Protocol Reverted' },
        { value: 'PROTOCOL_APPROVAL_REQUESTED', label: 'Protocol Approval Requested' },
        { value: 'STEP_DEVIATION', label: 'Step Deviation' },
    ] as const;
```

Note: `EVENT_TYPES` is *also* missing `PENDING_IMAGE_ANALYSIS`, `OFFLINE_SYNC_PENDING`, and `OFFLINE_VALUE_DISCREPANCY`. That broader parity gap is out of scope for TD-0091a (routed to a follow-up ticket) — do **not** add those three here.

- [ ] **Step 2: Verify the frontend type-checks**

Run: `cd frontend && npm run check`
Expected: PASS — no new svelte-check or tsc errors introduced by this change.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "fix(TD-0091a): expose PROTOCOL_APPROVAL_REQUESTED in notification event picker"
```

---

## Task 3: Fix 4 — `_get_user_org_id` honors `selected_org_id`

**Files:**
- Modify: `backend/app/api/endpoints/notifications.py:55-66` (helper) and lines 125, 147, 498 (callers)
- Test: `backend/tests/integration/test_notification_api.py`

`_get_user_org_id` returns the user's *first* org membership, ignoring `User.selected_org_id` (the codebase's standard org-context field). A multi-org user whose active org is not their first membership sees the wrong org's channels and delivery log.

- [ ] **Step 1: Write the failing integration tests**

Append a new test class to the end of `backend/tests/integration/test_notification_api.py`:

```python
# ── Fix 4: _get_user_org_id honors selected_org_id ───────────────────────


class TestOrgResolution:
    """A multi-org user's channels/deliveries resolve to selected_org_id."""

    async def _make_multi_org_user(
        self,
        db_session,
        email,
        first_org,
        second_org,
        selected_org_id,
        first_org_roles=("MEMBER", "ADMIN"),
        second_org_roles=("MEMBER", "ADMIN"),
    ):
        """Create a user who joins first_org then second_org, with the given
        selected_org_id and per-org roles. Returns auth headers.

        Both memberships are inserted inside one transaction, so PostgreSQL's
        transaction-fixed now() stamps them with the *same* created_at —
        there is no "older" membership. Every test using this helper sets a
        valid selected_org_id, so _get_user_org_id resolves via the
        selected-org re-check and never reaches the created_at fallback; the
        fallback tie-break is therefore not exercised here.
        """
        from app.core.security import create_access_token, hash_password
        from app.models.iam import OrganizationMember, User

        user = User(
            email=email,
            hashed_password=hash_password("testpass"),
            full_name="Multi Org User",
            selected_org_id=selected_org_id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=first_org.id,
                roles=list(first_org_roles),
            )
        )
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=second_org.id,
                roles=list(second_org_roles),
            )
        )
        await db_session.flush()
        token = create_access_token(
            user.id,
            org_id=selected_org_id or first_org.id,
            subscription_tier=first_org.subscription_tier,
            email_verified=True,
        )
        return {"Authorization": f"Bearer {token}"}

    async def _make_single_org_user(
        self, db_session, email, org, selected_org_id,
        roles=("MEMBER", "ADMIN"),
    ):
        """Create a single-org user with the given selected_org_id — which
        may intentionally point at an org they do NOT belong to. Returns
        auth headers. Shared by the two fallback regression-guard tests so
        they do not inline duplicated user-creation."""
        from app.core.security import create_access_token, hash_password
        from app.models.iam import OrganizationMember, User

        user = User(
            email=email,
            hashed_password=hash_password("testpass"),
            full_name="Single Org User",
            selected_org_id=selected_org_id,
            email_verified=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=user.id,
                organization_id=org.id,
                roles=list(roles),
            )
        )
        await db_session.flush()
        token = create_access_token(
            user.id,
            org_id=org.id,
            subscription_tier=org.subscription_tier,
            email_verified=True,
        )
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_list_channels_honors_selected_org_id(
        self, client, test_org, second_org, db_session
    ):
        """selected_org_id points at the SECOND org => list its channels,
        not the first membership's."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="First Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        db_session.add(
            NotificationChannel(
                org_id=second_org.id, name="Second Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_multi_org_user(
            db_session, "multiorg1@example.com", test_org, second_org,
            selected_org_id=second_org.id,
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Second Org Ch"}

    @pytest.mark.asyncio
    async def test_list_deliveries_honors_selected_org_id(
        self, client, test_org, second_org, db_session
    ):
        """A multi-org admin sees the selected org's delivery log."""
        second_channel = NotificationChannel(
            org_id=second_org.id, name="Second Org Ch",
            channel_type="CONSOLE", config={},
        )
        db_session.add(second_channel)
        await db_session.flush()
        db_session.add(
            NotificationDelivery(
                channel_id=second_channel.id,
                event_type="RUN_STARTED",
                recipient_info={"recipient": "x@example.com"},
                status="SENT",
                attempts=1,
            )
        )
        await db_session.flush()
        headers = await self._make_multi_org_user(
            db_session, "multiorg2@example.com", test_org, second_org,
            selected_org_id=second_org.id,
        )
        resp = await client.get("/notifications/deliveries", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_create_channel_admin_check_uses_selected_org(
        self, client, test_org, second_org, db_session
    ):
        """User is only a MEMBER of their first org but an ADMIN of the
        selected (second) org. Before the fix, _get_user_org_id resolves to
        the first org and _require_org_admin returns 403; after the fix it
        resolves to the selected org and the create succeeds (201)."""
        headers = await self._make_multi_org_user(
            db_session, "multiadmin1@example.com", test_org, second_org,
            selected_org_id=second_org.id,
            first_org_roles=("MEMBER",),
            second_org_roles=("MEMBER", "ADMIN"),
        )
        resp = await client.post(
            "/notifications/channels",
            json={"name": "Sel Org Ch", "channel_type": "CONSOLE",
                  "config": {}},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["org_id"] == str(second_org.id)

    @pytest.mark.asyncio
    async def test_list_deliveries_admin_check_uses_selected_org(
        self, client, test_org, second_org, db_session
    ):
        """Same MEMBER-of-first / ADMIN-of-selected user: the admin-gated
        deliveries log resolves to the selected org and returns 200, not the
        403 the first-membership resolution would produce."""
        headers = await self._make_multi_org_user(
            db_session, "multiadmin2@example.com", test_org, second_org,
            selected_org_id=second_org.id,
            first_org_roles=("MEMBER",),
            second_org_roles=("MEMBER", "ADMIN"),
        )
        resp = await client.get(
            "/notifications/deliveries", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_fallback_when_selected_org_id_unset(
        self, client, test_org, db_session
    ):
        """A single-org user with selected_org_id=None resolves to their
        one membership (regression guard)."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="Only Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_single_org_user(
            db_session, "noselected@example.com", test_org,
            selected_org_id=None,
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Only Org Ch"}

    @pytest.mark.asyncio
    async def test_stale_selected_org_id_falls_back(
        self, client, test_org, second_org, db_session
    ):
        """selected_org_id points at an org the user does NOT belong to =>
        fall back to a real membership; no 403, no cross-org leak."""
        db_session.add(
            NotificationChannel(
                org_id=test_org.id, name="Real Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        db_session.add(
            NotificationChannel(
                org_id=second_org.id, name="Other Org Ch",
                channel_type="CONSOLE", config={},
            )
        )
        await db_session.flush()
        headers = await self._make_single_org_user(
            db_session, "staleselected@example.com", test_org,
            selected_org_id=second_org.id,  # not a member of second_org
        )
        resp = await client.get("/notifications/channels", headers=headers)
        assert resp.status_code == 200
        assert {c["name"] for c in resp.json()} == {"Real Org Ch"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_notification_api.py::TestOrgResolution -v`
Expected: four tests FAIL. `test_list_channels_honors_selected_org_id` and `test_list_deliveries_honors_selected_org_id` return the first membership's data (`test_org`), so the wrong channels/deliveries come back. `test_create_channel_admin_check_uses_selected_org` and `test_list_deliveries_admin_check_uses_selected_org` get a `403` — the admin check runs against `test_org`, where the user is only a `MEMBER`. `test_fallback_when_selected_org_id_unset` and `test_stale_selected_org_id_falls_back` already PASS — they are regression guards for the fallback path, which this change preserves.

- [ ] **Step 3: Rewrite `_get_user_org_id` to honor `selected_org_id`**

In `backend/app/api/endpoints/notifications.py`, replace the helper at lines 55-66:

```python
async def _get_user_org_id(db: AsyncSession, user: User) -> UUID:
    """Resolve the user's active org id.

    Honors ``user.selected_org_id`` when the user is still a member of that
    org; otherwise falls back to their oldest membership. Raises 400 if the
    user belongs to no organization.
    """
    if user.selected_org_id is not None:
        stmt = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == user.selected_org_id,
        )
        if (await db.execute(stmt)).scalar_one_or_none() is not None:
            return user.selected_org_id

    stmt = (
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.created_at, OrganizationMember.id)
        .limit(1)
    )
    org_id = (await db.execute(stmt)).scalar_one_or_none()
    if not org_id:
        raise HTTPException(400, "User is not a member of any organization")
    return org_id
```

The membership re-check is required, not cosmetic: `list_org_channels` queries channels by `org_id` with no downstream membership gate, so blindly trusting a stale `selected_org_id` could leak another org's channel list. The check matches the existing `_require_org_member` helper — it does **not** filter on `OrganizationMember.archived` (pre-existing behavior, unchanged). The fallback `ORDER BY created_at, OrganizationMember.id` is deterministic: PostgreSQL's `now()` is transaction-fixed, so memberships created in one transaction share a `created_at` — the `id` column breaks that tie so the query never returns an arbitrary row. `User` is already imported at line 21; no new import needed.

- [ ] **Step 4: Update the three callers to pass the `User` object**

In `backend/app/api/endpoints/notifications.py`, change all three call sites from `current_user.id` to `current_user`:

`create_org_channel` (line 125):
```python
    org_id = await _get_user_org_id(db, current_user)
```

`list_org_channels` (line 147):
```python
    org_id = await _get_user_org_id(db, current_user)
```

`list_deliveries` (line 498):
```python
    org_id = await _get_user_org_id(db, current_user)
```

`_get_user_org_id` is a module-private helper — these are the only three callers, so there are no other call sites to update.

- [ ] **Step 5: Run the new tests and the full notification API suite to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_notification_api.py -v`
Expected: PASS — all `TestOrgResolution` tests pass, and the pre-existing notification API tests still pass (single-org fixtures resolve via the membership re-check on `selected_org_id`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/notifications.py backend/tests/integration/test_notification_api.py
git commit -m "fix(TD-0091a): _get_user_org_id honors selected_org_id for multi-org users"
```

---

## Task 4: Fix 2 — Harden `retry_pending` (N+1, ordering, batch isolation)

**Files:**
- Modify: `backend/app/services/core/notifications/dispatcher.py:78-110`
- Test: `backend/tests/unit/test_notifications.py`

Wiring the orphaned `retry_pending` into a loop that runs every 90s makes three latent defects live: an N+1 channel fetch (`db.get` per row), a non-deterministic drain (no `ORDER BY` under the `.limit(50)` cap), and batch poisoning (an uncaught exception on one row — e.g. `get_channel` raising `ValueError` for an unregistered `channel_type` — escapes the function, skips the caller's `commit()`, and rolls back already-completed re-sends in the same batch, causing duplicate external messages).

This task hardens `retry_pending` itself. Task 5 wires it into the recovery loop.

- [ ] **Step 1: Add a failing-channel test double and the `retry_pending` tests**

In `backend/tests/unit/test_notifications.py`, first extend the imports at the top of the file (lines 1-15) so the new tests have what they need. Add these imports after the existing import block:

```python
from datetime import datetime, timedelta, timezone

from app.models.notifications import (
    DeliveryStatus,
    NotificationChannel,
    NotificationDelivery,
)
from app.services.core.notifications import dispatcher
from app.services.core.notifications.dispatcher import retry_pending
```

(`patch` and `AsyncMock` are already imported on line 3 via `from unittest.mock import AsyncMock, patch` — do not duplicate them. The `dispatcher` module is imported whole so the poison-row test can patch and reference `dispatcher._execute_send`; `retry_pending` keeps its direct import for the call sites.)

Then append a failing-channel double and a new test class to the end of the file (after `class FakeChannel`):

```python
# ── FailingChannel for retry_pending tests ───────────────────────────────


class FailingChannel(BaseChannel):
    """Channel double that always raises the configured error on send."""

    def __init__(self, error: Exception):
        super().__init__({})
        self._error = error

    async def send(self, message: FormattedMessage) -> str:
        raise self._error


# ── retry_pending Tests (Fix 2) ──────────────────────────────────────────


class TestRetryPending:
    """retry_pending drains due RETRYING deliveries with batch isolation."""

    async def _make_channel(self, db_session, test_user, channel_type="CONSOLE",
                            enabled=True):
        channel = NotificationChannel(
            user_id=test_user.id,
            name="Retry Test Channel",
            channel_type=channel_type,
            config={},
            enabled=enabled,
        )
        db_session.add(channel)
        await db_session.flush()
        return channel

    async def _make_delivery(self, db_session, channel, attempts=1,
                             due_offset_seconds=-30):
        delivery = NotificationDelivery(
            channel_id=channel.id,
            event_type="RUN_STARTED",
            recipient_info={"recipient": "x@example.com"},
            status=DeliveryStatus.RETRYING,
            attempts=attempts,
            next_retry_at=datetime.now(timezone.utc)
            + timedelta(seconds=due_offset_seconds),
        )
        db_session.add(delivery)
        await db_session.flush()
        return delivery

    @pytest.mark.asyncio
    async def test_due_delivery_is_retried_and_sent(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.SENT

    @pytest.mark.asyncio
    async def test_not_yet_due_delivery_is_skipped(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(
            db_session, channel, due_offset_seconds=3600
        )

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.RETRYING

    @pytest.mark.asyncio
    async def test_transient_failure_stays_retrying(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(db_session, channel, attempts=1)
        original_retry_at = delivery.next_retry_at

        with patch(
            "app.services.core.notifications.dispatcher.get_channel",
            return_value=FailingChannel(TransientError("network blip")),
        ):
            count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.RETRYING
        assert delivery.attempts == 2
        assert delivery.next_retry_at > original_retry_at

    @pytest.mark.asyncio
    async def test_transient_failure_on_last_attempt_fails(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        # attempts=2 => _execute_send increments to 3 => not < MAX_RETRIES.
        delivery = await self._make_delivery(db_session, channel, attempts=2)

        with patch(
            "app.services.core.notifications.dispatcher.get_channel",
            return_value=FailingChannel(TransientError("still down")),
        ):
            count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_disabled_channel_marks_failed_without_send(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user, enabled=False)
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.status_detail == "Channel disabled or deleted"

    @pytest.mark.asyncio
    async def test_unknown_channel_type_is_isolated(
        self, db_session, test_user
    ):
        """A channel_type not in the registry makes get_channel raise
        ValueError — the row is marked FAILED, the batch is not aborted."""
        channel = await self._make_channel(
            db_session, test_user, channel_type="PIGEON"
        )
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_poison_row_does_not_abort_batch(
        self, db_session, test_user
    ):
        """One poison row plus good rows: good rows still SEND and are not
        re-selected on a second sweep."""
        good_channel = await self._make_channel(db_session, test_user)
        poison_channel = await self._make_channel(
            db_session, test_user, channel_type="PIGEON"
        )
        good1 = await self._make_delivery(db_session, good_channel)
        good2 = await self._make_delivery(db_session, good_channel)
        poison = await self._make_delivery(db_session, poison_channel)

        count = await retry_pending(db_session)

        assert count == 2  # two good rows sent; poison row not counted
        for d in (good1, good2):
            await db_session.refresh(d)
            assert d.status == DeliveryStatus.SENT
        await db_session.refresh(poison)
        assert poison.status == DeliveryStatus.FAILED

        # A second sweep finds nothing still RETRYING.
        second_count = await retry_pending(db_session)
        assert second_count == 0

    @pytest.mark.asyncio
    async def test_execute_send_failure_does_not_poison_batch(
        self, db_session, test_user
    ):
        """If _execute_send raises on one row, the per-row SAVEPOINT isolates
        it: that row is marked FAILED and the remaining good rows still SEND
        in the same sweep — no session poisoning, no aborted batch."""
        channel = await self._make_channel(db_session, test_user)
        good1 = await self._make_delivery(db_session, channel)
        poison = await self._make_delivery(db_session, channel)
        good2 = await self._make_delivery(db_session, channel)

        real_execute_send = dispatcher._execute_send

        async def flaky_execute_send(db, delivery, ch, msg):
            # Fail only the poison row; identified by id so the result does
            # not depend on the order rows are processed.
            if delivery.id == poison.id:
                raise RuntimeError("simulated delivery-row failure")
            return await real_execute_send(db, delivery, ch, msg)

        with patch(
            "app.services.core.notifications.dispatcher._execute_send",
            side_effect=flaky_execute_send,
        ):
            count = await retry_pending(db_session)

        assert count == 2  # both good rows sent; poison row not counted
        for d in (good1, good2):
            await db_session.refresh(d)
            assert d.status == DeliveryStatus.SENT
        await db_session.refresh(poison)
        assert poison.status == DeliveryStatus.FAILED
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestRetryPending -v`
Expected: most tests PASS against the current implementation, but `test_unknown_channel_type_is_isolated`, `test_poison_row_does_not_abort_batch`, and `test_execute_send_failure_does_not_poison_batch` ERROR/FAIL — the current loop has no per-row isolation, so the `ValueError` from `get_channel("PIGEON", ...)` and the `RuntimeError` from the patched `_execute_send` escape `retry_pending` and abort the whole sweep before the assertions run. These three are the regression tests for the hardening.

- [ ] **Step 3: Harden `retry_pending`**

In `backend/app/services/core/notifications/dispatcher.py`, replace the `retry_pending` function (lines 78-110):

```python
async def retry_pending(db: AsyncSession) -> int:
    """Retry deliveries that are due. Returns count of retried deliveries.

    Each delivery is processed inside its own SAVEPOINT (``begin_nested``),
    so a failure on one row — including a DB-level error that would poison
    the session — is rolled back to the savepoint and the row marked FAILED
    on the still-healthy outer transaction. The batch is never aborted, so
    the caller's single commit is always reached. Most-overdue deliveries
    drain first.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.status == DeliveryStatus.RETRYING)
        .where(NotificationDelivery.next_retry_at <= now)
        .order_by(NotificationDelivery.next_retry_at, NotificationDelivery.id)
        .limit(50)
        .options(selectinload(NotificationDelivery.channel))
    )
    result = await db.execute(stmt)
    pending = result.scalars().all()

    count = 0
    for delivery in pending:
        try:
            async with db.begin_nested():
                channel_model = delivery.channel
                if not channel_model or not channel_model.enabled:
                    delivery.status = DeliveryStatus.FAILED
                    delivery.status_detail = "Channel disabled or deleted"
                else:
                    channel = get_channel(
                        channel_model.channel_type, channel_model.config
                    )
                    msg = FormattedMessage(
                        event_type=delivery.event_type,
                        title="(retry)",
                        body="",
                        recipient=delivery.recipient_info.get(
                            "recipient", "unknown"
                        ),
                    )
                    await _execute_send(db, delivery, channel, msg)
                    count += 1
        except Exception as e:  # noqa: BLE001 — per-row batch isolation
            logger.exception(
                "Retry sweep: unexpected error on delivery %s", delivery.id
            )
            delivery.status = DeliveryStatus.FAILED
            delivery.status_detail = f"Retry aborted: {e}"

    await db.flush()
    return count
```

Four changes from the original. (1) `selectinload(NotificationDelivery.channel)` replaces the per-row `await db.get(NotificationChannel, ...)` N+1 — `delivery.channel` is now eager-loaded. (2) `ORDER BY next_retry_at, id` drains the most-overdue first under the `.limit(50)` cap, with `id` as a deterministic tie-break for rows sharing a `next_retry_at` (covered by the existing `ix_notif_del_status (status, next_retry_at)` index — no new index). (3) Each row runs inside `async with db.begin_nested()` — a SAVEPOINT. A plain `try/except` is **not** enough: `_execute_send` ends with `await db.flush()`, and a flush-level DB error poisons the whole `AsyncSession` (`PendingRollbackError` on every subsequent statement), which would silently roll back the good rows already re-sent in this batch and cause duplicate external messages. The SAVEPOINT confines a failure to the one row; the `except` then marks that row FAILED on the (still-usable) outer transaction. Note the `if/else` replaces the original `continue` — `continue` inside `async with` would still exit the block cleanly, but an explicit `else` keeps the disabled-channel path and the send path symmetric inside one savepoint. (4) `get_channel` raising `ValueError` for an unregistered `channel_type` is now caught by the same `except` instead of escaping the function. `selectinload`, `select`, `NotificationDelivery`, `DeliveryStatus`, `get_channel`, and `FormattedMessage` are all already imported in this module; `db.begin_nested()` needs no import. The per-test `db_session` fixture itself runs inside a SAVEPOINT — SQLAlchemy nests savepoints, so `begin_nested()` works unchanged under the test harness.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py -v`
Expected: PASS — all `TestRetryPending` tests pass (poison rows are isolated, good rows still send), and the pre-existing notification unit tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/dispatcher.py backend/tests/unit/test_notifications.py
git commit -m "fix(TD-0091a): harden retry_pending — selectinload, ordering, batch isolation"
```

---

## Task 5: Fix 2 — Wire `_retry_pending_deliveries()` into the recovery loop

**Files:**
- Modify: `backend/app/main.py:290-314` (`_recovery_loop`) and add `_retry_pending_deliveries()`
- Modify: `backend/app/core/config.py:141-145` (docstring)
- Test: `backend/tests/unit/test_notifications.py`

`retry_pending` is now hardened (Task 4) but still orphaned — nothing calls it. Wire it into the existing `_recovery_loop` as a third independent sweep, mirroring the job/document recovery pattern.

The recovery loop itself is not unit-tested (it runs against the app's shared engine, not the test DB). But the new `_retry_pending_deliveries()` *sweep function* is unit-testable in isolation: its `AsyncSessionLocal` and `retry_pending` dependencies are local imports, so they can be patched. The loop wiring is verified by an import smoke check.

- [ ] **Step 1: Write the failing sweep test**

In `backend/tests/unit/test_notifications.py`, first extend the `unittest.mock` import on line 3 to add `MagicMock`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
```

Then append a new test class to the end of the file:

```python
# ── _retry_pending_deliveries sweep wiring (Fix 2) ───────────────────────


class TestRetryPendingDeliveriesSweep:
    """The recovery-loop sweep opens a session, calls retry_pending, commits."""

    @pytest.mark.asyncio
    async def test_sweep_calls_retry_pending_and_commits(self):
        from app.main import _retry_pending_deliveries

        fake_session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = fake_session
        session_cm.__aexit__.return_value = False
        session_factory = MagicMock(return_value=session_cm)
        retry_mock = AsyncMock(return_value=3)

        with patch(
            "app.db.session.AsyncSessionLocal", session_factory
        ), patch(
            "app.services.core.notifications.dispatcher.retry_pending",
            retry_mock,
        ):
            await _retry_pending_deliveries()

        # Sweep opened exactly one session, ran the retry, and committed.
        session_factory.assert_called_once()
        retry_mock.assert_awaited_once_with(fake_session)
        fake_session.commit.assert_awaited_once()
```

`_retry_pending_deliveries` does its imports *inside the function body* (`from app.db.session import AsyncSessionLocal`, `from ...dispatcher import retry_pending`), so patching those module attributes is what the patched names resolve to at call time.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestRetryPendingDeliveriesSweep -v`
Expected: FAIL — `ImportError: cannot import name '_retry_pending_deliveries' from 'app.main'` (the function does not exist yet).

- [ ] **Step 3: Add `_retry_pending_deliveries()` to `main.py`**

In `backend/app/main.py`, add this function immediately before `_recovery_loop` (before line 290):

```python
async def _retry_pending_deliveries() -> None:
    """Retry due notification deliveries (transient external-delivery failures).

    Runs as a sweep inside the recovery loop. Uses the shared session pool;
    the ``async with`` block rolls back automatically if a SQLAlchemy-level
    error escapes, so no partial state is committed.
    """
    from app.db.session import AsyncSessionLocal
    from app.services.core.notifications.dispatcher import retry_pending

    async with AsyncSessionLocal() as session:
        count = await retry_pending(session)
        await session.commit()
    if count:
        logger.info("Delivery retry sweep: retried %d deliveries", count)
    else:
        logger.debug("Delivery retry sweep: no deliveries due")
```

`AsyncSessionLocal` and `retry_pending` are imported locally inside the function — consistent with the `lifespan` seeding block (line 350), which also imports `AsyncSessionLocal` locally, and it avoids any import-ordering concern with the notifications service package. The retried count is logged at `INFO` only when there is something to report; an idle sweep — the common case, every 90s — logs at `DEBUG` so it does not flood steady-state logs.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestRetryPendingDeliveriesSweep -v`
Expected: PASS — the sweep opens one session, awaits `retry_pending` with it, and commits.

- [ ] **Step 5: Add the third sweep to `_recovery_loop()` and update its docstring**

In `backend/app/main.py`, replace the `_recovery_loop` function (lines 290-314):

```python
async def _recovery_loop() -> None:
    """Periodically re-run the stalled-jobs/stalled-docs sweeps and retry
    due notification deliveries.

    The startup sweep covers cold boots for job/document recovery; this loop
    covers steady-state autoscaled deployments where new pods don't boot for
    hours. The delivery-retry sweep is loop-only (no startup sweep — it does
    outbound network I/O and must not block boot). Each sweep is independent
    — exceptions inside one don't kill the others, and don't kill the loop.

    Set BATCHRITE_RECOVERY_INTERVAL_SECONDS=0 to disable — this also
    disables notification delivery retries.
    """
    interval = settings.recovery_interval_seconds
    if not interval or interval <= 0:
        logger.warning(
            "Recovery loop disabled (interval <= 0) — notification "
            "delivery retries are also OFF"
        )
        return

    while True:
        try:
            await _recover_stalled_jobs()
        except Exception:
            logger.exception("Recovery loop: job sweep failed")
        try:
            await _recover_stalled_documents()
        except Exception:
            logger.exception("Recovery loop: doc sweep failed")
        try:
            await _retry_pending_deliveries()
        except Exception:
            logger.exception("Recovery loop: delivery retry sweep failed")
        await asyncio.sleep(interval)
```

Two things beyond wiring the new sweep. The `delivery retry sweep failed` `try/except` matches the existing two — one failing sweep never kills the others or the loop. And the disabled-loop log is raised from `INFO` to `WARNING` with an explicit note that delivery retries are off too: a disabled recovery loop is now also a silently disabled retry path, and operators must not mistake that for a healthy idle one. The loop runs its first iteration immediately (before the first `sleep`), so first-retry latency after boot is bounded by one interval — no before-`yield` startup sweep is added.

- [ ] **Step 6: Update the `recovery_interval_seconds` docstring in `config.py`**

In `backend/app/core/config.py`, replace the comment block above `recovery_interval_seconds` (lines 141-145):

```python
    # Phase 3: how often the recovery loop sweeps for stalled jobs/docs
    # and retries due notification deliveries. The startup sweep still
    # runs once on lifespan boot for job/doc recovery; the delivery-retry
    # sweep is loop-only. Set to 0 to disable the loop entirely — this
    # also disables notification delivery retries.
    recovery_interval_seconds: int = 90
```

- [ ] **Step 7: Smoke-check the wiring imports cleanly**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "
from app.main import _retry_pending_deliveries, _recovery_loop
import inspect
src = inspect.getsource(_recovery_loop)
assert '_retry_pending_deliveries()' in src, 'sweep not wired into loop'
assert 'delivery retry sweep failed' in src, 'error handler missing'
print('OK: _retry_pending_deliveries wired into _recovery_loop')
"
```
Expected: `OK: _retry_pending_deliveries wired into _recovery_loop`

- [ ] **Step 8: Run the notification suites to confirm nothing regressed**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py tests/integration/test_notification_api.py -v`
Expected: PASS — no regressions from the `main.py`/`config.py` changes.

- [ ] **Step 9: Commit**

```bash
git add backend/app/main.py backend/app/core/config.py backend/tests/unit/test_notifications.py
git commit -m "fix(TD-0091a): wire delivery retry sweep into the recovery loop"
```

---

## Task 6: Fix 1 — Stop the Settings → Notifications infinite request loop

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte` — lines 60-61 (state), 111-120 (`loadChannels`), 789-793 (`$effect`), 847 (tab `onclick`), 1344 (loading-state template branch)

The `$effect` guard `channels.length === 0 && !channelsLoading` is satisfied again every time a channel-less user's `loadChannels()` reassigns `channels = []` and clears `channelsLoading` — the effect re-fires unbounded (the audit observed 753+ requests from one visit). Replace the `channels.length`-based guard with a one-shot `channelsLoaded` latch that the API result never mutates.

This task has no automated test — it is verified in the browser-QA step below.

- [ ] **Step 1: Add the `channelsLoaded` state flag**

In `frontend/src/routes/settings/+page.svelte`, add the flag alongside the existing channel state (after line 61):

```javascript
    // Notifications
    let channels = $state<any[]>([]);
    let channelsLoading = $state(false);
    let channelsLoaded = $state(false);
```

- [ ] **Step 2: Set the latch in `loadChannels()`'s `finally`**

In `frontend/src/routes/settings/+page.svelte`, update `loadChannels()` (lines 111-120):

```javascript
    async function loadChannels() {
        channelsLoading = true;
        try {
            channels = await api.get('/notifications/channels/me');
        } catch {
            channels = [];
        } finally {
            channelsLoading = false;
            channelsLoaded = true;
        }
    }
```

Setting `channelsLoaded = true` in `finally` (not in `try`) means a failed load is also one-shot — it does not auto-retry, which prevents the loop under a persistently-failing API too. `addChannel` / `deleteChannel` / `toggleChannelEnabled` still call `loadChannels()` directly, so post-mutation refreshes are unaffected by the latch.

- [ ] **Step 3: Change the `$effect` guard to use the latch**

In `frontend/src/routes/settings/+page.svelte`, update the `$effect` (lines 788-793):

```javascript
    // Auto-load notifications channel list once when the notifications tab
    // is active. Guarded by a one-shot `channelsLoaded` latch — the effect
    // must never read `channels`, or reassigning it to [] re-triggers the load.
    $effect(() => {
        if (activeTab === 'notifications' && !channelsLoaded && !channelsLoading) {
            loadChannels();
        }
    });
```

The effect now reads only `activeTab`, `channelsLoaded`, and `channelsLoading` — never `channels`. After one load, `channelsLoaded` is `true` and the guard fails permanently. `channelsLoaded` is a one-shot latch with no reset path: this is correct because `GET /notifications/channels/me` is user-scoped (served by `list_user_channels`, filtered by `current_user.id`), so switching the active org does not change this tab's data.

- [ ] **Step 4: Hold the loading state until the first load resolves**

In `frontend/src/routes/settings/+page.svelte`, widen the loading-branch condition in the Notification Channels card (line 1344):

```svelte
                {#if channelsLoading || !channelsLoaded}
                    <p in:fade={{ duration: blockDuration() }} class="text-sm text-muted-foreground py-4 text-center">Loading channels...</p>
                {:else if channels.length === 0 && !showAddChannel}
```

Between mount and the first `loadChannels()` resolving, `channelsLoading` is briefly still `false` (the `$effect` has not run on this frame yet) while `channels` is `[]`. Without `!channelsLoaded` the `{:else if channels.length === 0}` branch wins for that frame and the "No notification channels configured yet." empty state flashes before the load. Gating the loading branch on the latch shows "Loading channels..." continuously from mount until the first load resolves. The `{:else if}` and `{:else}` branches are unchanged.

- [ ] **Step 5: Remove the redundant inline `loadChannels()` from the tab `onclick`**

In `frontend/src/routes/settings/+page.svelte`, simplify the Notifications tab button handler (line 847):

```javascript
            onclick={() => setTab('notifications')}
```

Changing `activeTab` (via `setTab`) already fires the `$effect`, which loads channels for both URL navigation and click navigation. The inline `if (channels.length === 0 && !channelsLoading) loadChannels()` was duplicate logic — and it read `channels.length`, the very guard that loops.

- [ ] **Step 6: Verify the frontend type-checks**

Run: `cd frontend && npm run check`
Expected: PASS — no new svelte-check or tsc errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "fix(TD-0091a): stop infinite request loop on Settings notifications tab"
```

- [ ] **Step 8: Browser verification (handled by the qa-verify agent in `/implement-task`)**

The `/implement-task` browser-QA step exercises these cases against the worktree's dev servers:
- A channel-**less** user opens Settings → Notifications both by clicking the tab and via direct URL `?tab=notifications`; the `GET /notifications/channels/me` request count stays at exactly **one** per visit and the tab renders "No notification channels configured yet." with no empty-state flash before it.
- A user **with** at least one channel opens the tab via both paths; channels render and the request count stays at one.
- With `GET /notifications/channels/me` failing (backend stopped, or a forced network error in DevTools), opening Settings → Notifications issues **exactly one** request and does **not** loop — the `catch` sets `channels = []` and the `finally` still sets the `channelsLoaded` latch, so the `$effect` guard fails permanently. The tab settles on the empty state.
- The Notifications event-subscription picker shows the **Protocol Approval Requested** checkbox (Task 2), and subscribing a channel to it succeeds.

---

## Final Verification

- [ ] **Run the full backend test suite**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py tests/integration/test_notification_api.py -v`
Expected: PASS — all notification unit and integration tests green.

- [ ] **Run the broader backend suite to confirm no cross-module regressions**

Run: `cd backend && source .venv/bin/activate && pytest tests/ -q`
Expected: PASS — the enum addition, `_get_user_org_id` signature change, `retry_pending` hardening, and recovery-loop wiring do not regress other suites.

- [ ] **Frontend type-check**

Run: `cd frontend && npm run check`
Expected: PASS.

---

## Spec Coverage Check

| Spec section | Covered by |
| --- | --- |
| Fix 1 — infinite request loop | Task 6 (`channelsLoaded` latch, effect guard, dedupe `onclick`) |
| Fix 2 — orphaned `retry_pending` (wiring) | Task 5 (`_retry_pending_deliveries`, `_recovery_loop`, config docstring) |
| Fix 2 — hardening `retry_pending` (N+1, ordering, isolation) | Task 4 (`selectinload`, `ORDER BY`, per-row `try/except`) |
| Fix 3 — `PROTOCOL_APPROVAL_REQUESTED` enum | Task 1 (enum value + bidirectional test) |
| Fix 3 — frontend `EVENT_TYPES` entry | Task 2 |
| Fix 4 — `_get_user_org_id` honors `selected_org_id` | Task 3 (helper rewrite + 3 callers + 4 integration tests) |
| Testing — enum↔TEMPLATES sync | Task 1 Step 1 |
| Testing — `retry_pending` happy/not-due/failure/batch + SAVEPOINT isolation | Task 4 Step 1 (`TestRetryPending`, `FailingChannel`, poison + `_execute_send`-failure tests) |
| Testing — `_retry_pending_deliveries` sweep opens session, retries, commits | Task 5 Step 1 (`TestRetryPendingDeliveriesSweep`) |
| Testing — `selected_org_id` resolution + admin-check + stale + fallback | Task 3 Step 1 (`TestOrgResolution`, incl. MEMBER-of-first/ADMIN-of-selected 403→200 tests) |
| Testing — `PROTOCOL_APPROVAL_REQUESTED` subscribable | Task 6 Step 8 (browser QA) |
| Testing — Fix 1 browser QA (both nav paths, with/without channels, API-down) | Task 6 Step 8 |

**Out of scope (routed to follow-up tickets, per spec "Deferred follow-ups"):** unifying `library.py`'s parallel `_get_user_org_id`; the `RETRY_BACKOFF`/`MAX_RETRIES` off-by-one; the broader frontend `EVENT_TYPES` parity gap (`PENDING_IMAGE_ANALYSIS`, `OFFLINE_SYNC_PENDING`, `OFFLINE_VALUE_DISCREPANCY`); `FOR UPDATE SKIP LOCKED` on `retry_pending`; degraded retry message content; consolidating `main.py`'s recovery sweeps onto the shared pool; a delivery-retry operations runbook (a "RETRYING backlog depth" query plus an alert threshold so operators can spot a stuck retry queue — surfaced by the production-ops review of this plan); surfacing channel-load errors with a retry affordance on the Settings → Notifications tab (deferred to TD-0091b, per spec). These are created via `/add_task` after the task closes — not implemented here.

---

## Review Notes — changes made after the subagent review panel

The panel (`adversarial-risk-auditor`, `production-ops-reviewer`, `dry-reuse-auditor`, `db-scalability-reviewer`, `uiux-design-reviewer`) reviewed this plan. Applied changes:

- **`retry_pending` SAVEPOINT isolation (Task 4).** A plain per-row `try/except` does not isolate a *DB-level* failure: `_execute_send` ends in `await db.flush()`, and a flush error poisons the whole `AsyncSession`, which would silently roll back good rows already re-sent in the batch and cause duplicate external sends. Each row now runs inside `async with db.begin_nested()` (a SAVEPOINT). Verified against `conftest.py` that nested savepoints work under the per-test `db_session` fixture. Added `test_execute_send_failure_does_not_poison_batch`.
- **Deterministic ordering (Task 4).** `retry_pending`'s `ORDER BY` gained `NotificationDelivery.id` as a tie-break — rows sharing a `next_retry_at` (the test creates them that way) now drain in a stable order under the `.limit(50)` cap.
- **Task 5 is now TDD.** `_retry_pending_deliveries()` is unit-testable in isolation (local-import dependencies are patchable); added `TestRetryPendingDeliveriesSweep` with a fail-first test asserting the sweep opens a session, awaits `retry_pending`, and commits. The recovery-loop *wiring* remains verified by the import smoke check.
- **`_get_user_org_id` fallback ordering (Task 3).** Fallback `ORDER BY` gained `OrganizationMember.id` — PostgreSQL's `now()` is transaction-fixed, so same-transaction memberships share `created_at`; `id` breaks the tie. The false "older `created_at`" comment in the test helper was corrected.
- **403→200 admin-check coverage (Task 3).** `_make_multi_org_user` now takes per-org roles; added `test_create_channel_admin_check_uses_selected_org` and `test_list_deliveries_admin_check_uses_selected_org` for the MEMBER-of-first / ADMIN-of-selected case (the admin-gated endpoints would 403 before the fix, 200/201 after).
- **DRY in `TestOrgResolution` (Task 3).** Added `_make_single_org_user` so the two fallback regression-guard tests no longer inline duplicated user-creation; `email_verified=True` is set consistently in every helper path.
- **Observability (Task 5).** `_retry_pending_deliveries()` logs the retried count at `INFO` only when `count > 0`; an idle sweep logs at `DEBUG` to avoid flooding steady-state logs. The disabled-loop log was raised from `INFO` to `WARNING` with an explicit note that delivery retries are off too.
- **UI loading-state flash (Task 6).** Added Step 4 — the loading-branch condition becomes `{#if channelsLoading || !channelsLoaded}` so the empty-state branch cannot flash for one frame before the first load resolves.
- **Browser QA (Task 6).** Added an API-down case: a failing `/channels/me` must still issue exactly one request and not loop.

Recommendation considered and **rejected** — argument order of `_get_user_org_id`. `dry-reuse-auditor` suggested matching `library.py`'s `(user, db)` signature. Rejected: this helper lives in `notifications.py`, whose sibling private helpers (`_require_org_admin`, `_require_org_member`, `_get_channel_or_404`) all take `db` first. Consistency *within the file the reader is in* outweighs consistency with a helper in another module; `(db, user)` is kept. Unifying the two `_get_user_org_id` implementations is itself a deferred follow-up.

Deferred to follow-up tickets (see "Out of scope" above): the delivery-retry operations runbook (production-ops) and surfacing channel-load errors with a retry affordance on the Notifications tab (uiux-design-reviewer; already deferred to TD-0091b by the spec).
