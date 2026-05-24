# F-0019d — In-App Lifecycle Surfacing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a Loops inbound webhook (`POST /webhooks/loops/notification`) that creates in-app NotificationBell entries, and a global subscription banner above the nav that surfaces trial countdown / cancel-at-period-end / locked-out states.

**Architecture:** A new `webhooks` router (HMAC-verified, idempotent via composite-unique `loops_events`, atomic single-transaction with the `notifications` insert via a sibling `insert_external_notification` helper). On the frontend, a single `SubscriptionBanner.svelte` reads the existing `subscription` store, renders one of three priority-ordered variants (lock > cancel > trial), and is rendered above the nav from `+layout.svelte`. Trial banner only is dismissible via a daily localStorage key.

**Tech Stack:** FastAPI + asyncpg + SQLAlchemy 2.0, Alembic, Pydantic v2, pytest+httpx; Svelte 5 Runes, shadcn-svelte (Button, lucide-svelte icons), Vitest + @testing-library/svelte, Tailwind v4 with `lab-glass` HSL tokens from `frontend/src/app.css`.

**Source spec:** `docs/superpowers/specs/2026-05-24-f-0019d-in-app-lifecycle-surfacing-design.md`
**UI direction (locked):** `docs/superpowers/mockups/2026-05-24-f-0019d-subscription-banner.html`

---

## Task layout

Backend (Tasks 1–10) then Frontend (Tasks 11–15) then Docs (Task 16). Each task includes TDD steps. Commit after each task.

---

### Task 1: HMAC verification helper

**Files:**
- Create: `backend/app/core/webhook_auth.py`
- Test: `backend/tests/unit/core/test_webhook_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/core/test_webhook_auth.py
import hashlib
import hmac
import pytest

from app.core.webhook_auth import verify_hmac_sha256


SECRET = "test-secret"
BODY = b'{"hello":"world"}'


def _sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_bare_hex_lowercase_passes():
    assert verify_hmac_sha256(BODY, _sig(BODY, SECRET), SECRET) is True


def test_valid_uppercase_passes():
    assert verify_hmac_sha256(BODY, _sig(BODY, SECRET).upper(), SECRET) is True


def test_sha256_prefix_stripped():
    sig = "sha256=" + _sig(BODY, SECRET)
    assert verify_hmac_sha256(BODY, sig, SECRET) is True


def test_empty_header_rejected():
    assert verify_hmac_sha256(BODY, "", SECRET) is False


def test_empty_secret_rejected():
    assert verify_hmac_sha256(BODY, _sig(BODY, SECRET), "") is False


def test_wrong_signature_rejected():
    assert verify_hmac_sha256(BODY, "deadbeef" * 8, SECRET) is False


def test_tampered_body_rejected():
    sig = _sig(BODY, SECRET)
    assert verify_hmac_sha256(b'{"hello":"mars"}', sig, SECRET) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/core/test_webhook_auth.py -v`
Expected: `ModuleNotFoundError: No module named 'app.core.webhook_auth'`.

- [ ] **Step 3: Write the helper**

```python
# backend/app/core/webhook_auth.py
"""HMAC-SHA256 verification for inbound webhook signatures.

Shared by every signed-webhook entry point so the verification path stays
identical across vendors (Loops today, future others). Tolerant of common
provider casing/prefix conventions; the only thing it commits to is the
underlying HMAC-SHA256(body, secret).
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_sha256(raw_body: bytes, header_value: str, secret: str) -> bool:
    """Return True iff ``header_value`` is a valid HMAC-SHA256 of
    ``raw_body`` using ``secret``.

    Tolerates an optional ``sha256=`` prefix (GitHub-style) and any
    casing on the hex digest (some providers send uppercase). Both inputs
    are compared in constant time via ``hmac.compare_digest``.
    """
    if not header_value or not secret:
        return False
    candidate = header_value.lower().removeprefix("sha256=")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate, expected)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/core/test_webhook_auth.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/webhook_auth.py backend/tests/unit/core/test_webhook_auth.py
git commit -m "feat(F-0019d): add HMAC-SHA256 webhook verification helper"
```

---

### Task 2: Settings + middleware exemption

**Files:**
- Modify: `backend/app/core/config.py` (add `loops_webhook_secret`)
- Modify: `backend/app/core/middleware.py:7-17` (add exact path to `PUBLIC_PATHS`)

No tests added here — exercised end-to-end by the webhook tests in Task 7.

- [ ] **Step 1: Add the setting**

In `backend/app/core/config.py`, find the Loops block (search for `loops_api_key`) and add directly after `loops_request_timeout_seconds`:

```python
    loops_webhook_secret: str = ""
```

- [ ] **Step 2: Add the exact-match exemption**

In `backend/app/core/middleware.py`, edit the `PUBLIC_PATHS` set so it reads:

```python
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/register",
    "/auth/verify-email",
    "/auth/accept-invite",
    "/billing/webhook",
    "/webhooks/loops/notification",  # F-0019d
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
}
```

**Do not** add a `request.url.path.startswith("/webhooks/")` exemption — exact-match only. Each new inbound webhook adds its own exact entry.

- [ ] **Step 3: Sanity check imports still resolve**

Run: `cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; print(settings.loops_webhook_secret)"`
Expected: prints an empty line (default `""`).

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py backend/app/core/middleware.py
git commit -m "feat(F-0019d): add loops_webhook_secret setting + middleware exemption"
```

---

### Task 3: `LoopsEvent` model + Alembic migration

**Files:**
- Create: `backend/app/models/lifecycle.py`
- Modify: `backend/app/db/base.py` (add import)
- Create: `backend/alembic/versions/<auto>_add_loops_events.py` (autogenerated)
- Test: `backend/tests/unit/models/test_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/models/test_lifecycle.py
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.iam import Organization, User
from app.models.lifecycle import LoopsEvent


@pytest.fixture
async def user(db_session):
    org = Organization(name="LE Test")
    db_session.add(org)
    await db_session.flush()
    u = User(
        email=f"lifecycle-{uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="LE",
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_insert_loops_event(db_session, user):
    ev = LoopsEvent(loops_message_id="msg-abc", user_id=user.id)
    db_session.add(ev)
    await db_session.flush()
    row = (await db_session.execute(select(LoopsEvent))).scalar_one()
    assert row.loops_message_id == "msg-abc"
    assert row.user_id == user.id


@pytest.mark.asyncio
async def test_unique_constraint_msg_user_pair(db_session, user):
    db_session.add(LoopsEvent(loops_message_id="dup", user_id=user.id))
    await db_session.flush()
    db_session.add(LoopsEvent(loops_message_id="dup", user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_same_message_id_different_users_allowed(db_session, user):
    other = User(email=f"other-{uuid4().hex[:6]}@example.com", hashed_password="x", full_name="O")
    db_session.add(other)
    await db_session.flush()
    db_session.add(LoopsEvent(loops_message_id="shared", user_id=user.id))
    db_session.add(LoopsEvent(loops_message_id="shared", user_id=other.id))
    await db_session.flush()
    rows = (await db_session.execute(select(LoopsEvent))).scalars().all()
    assert len(rows) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/models/test_lifecycle.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models.lifecycle'`.

- [ ] **Step 3: Write the model**

```python
# backend/app/models/lifecycle.py
"""Idempotency records for inbound lifecycle webhooks.

F-0019d: Loops campaign workflows POST to ``/webhooks/loops/notification``;
each delivery may include an optional ``loops_message_id``. When set, we
record a ``(loops_message_id, user_id)`` row here under
ON CONFLICT DO NOTHING. A duplicate delivery hits the unique constraint
and is acked as ``deduped`` without re-inserting the notification.

Composite uniqueness lets the same campaign message id appear for two
different recipients (a single Loops campaign can fan out to many users)
without colliding. The UNIQUE constraint creates its own btree index — no
separate Index() declaration is needed.

Retention: none. Growth is bounded by Loops campaign volume; revisit once
row count exceeds a few million.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class LoopsEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "loops_events"
    __table_args__ = (
        UniqueConstraint(
            "loops_message_id", "user_id", name="uq_loops_events_msg_user"
        ),
    )

    loops_message_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
```

- [ ] **Step 4: Register the model in `db/base.py`**

In `backend/app/db/base.py`, add (keeping alphabetic-ish order with neighbours):

```python
from app.models.lifecycle import LoopsEvent  # noqa: F401
```

Place it next to the other model imports (after `from app.models.library import ...` is a good slot).

- [ ] **Step 5: Generate the migration**

Run (with `.env` sourced — see `[[alembic_needs_env_in_worktrees]]`):

```bash
cd backend && source .env && source .venv/bin/activate
alembic revision --autogenerate -m "add loops_events"
```

Expected: prints `Generating /…/<rev>_add_loops_events.py`.

- [ ] **Step 6: Review the migration**

Open the file Alembic just wrote. Confirm:
- `op.create_table("loops_events", ...)` with `id`, `loops_message_id`, `user_id`, `created_at`, `updated_at`.
- `op.create_unique_constraint("uq_loops_events_msg_user", "loops_events", ["loops_message_id", "user_id"])`.
- `op.f("fk_loops_events_user_id_users")` FK with `ondelete="CASCADE"`.

Confirm there is **no** `op.create_index("ix_loops_events_msg_user", ...)` — the UNIQUE constraint already implies a btree index, so an explicit Index would duplicate it (doubles write cost). If autogenerate added one, delete it.

If anything else is missing, hand-edit it in.

- [ ] **Step 7: Apply the migration & run tests**

```bash
alembic upgrade head
pytest tests/unit/models/test_lifecycle.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/lifecycle.py backend/app/db/base.py \
        backend/alembic/versions/*add_loops_events*.py \
        backend/tests/unit/models/test_lifecycle.py
git commit -m "feat(F-0019d): add LoopsEvent model + migration for inbound dedupe"
```

---

### Task 4: Add `LIFECYCLE` enum value to `NotificationEventType`

**Files:**
- Modify: `backend/app/models/notifications.py:32-47`
- Test: extend `backend/tests/unit/models/test_lifecycle.py`

- [ ] **Step 1: Write the failing test (extend existing test file)**

Append to `backend/tests/unit/models/test_lifecycle.py`:

```python
def test_notification_event_type_has_lifecycle():
    from app.models.notifications import NotificationEventType
    assert NotificationEventType.LIFECYCLE.value == "LIFECYCLE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/models/test_lifecycle.py::test_notification_event_type_has_lifecycle -v`
Expected: `AttributeError: LIFECYCLE`.

- [ ] **Step 3: Add the enum value**

In `backend/app/models/notifications.py`, append to the `NotificationEventType` class (after `RUN_SIGNOFF_CANCELLED`):

```python
    LIFECYCLE = "LIFECYCLE"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/models/test_lifecycle.py::test_notification_event_type_has_lifecycle -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/notifications.py backend/tests/unit/models/test_lifecycle.py
git commit -m "feat(F-0019d): add LIFECYCLE NotificationEventType"
```

---

### Task 5: Coupling-site stubs (TEMPLATES + DEFAULT_POLICY)

These keep `test_notifications.py` and `test_notification_policy.py` passing — they assert exact set-equality between the enum and these maps.

**Files:**
- Modify: `backend/app/services/core/notifications/templates.py:265-282`
- Modify: `backend/app/services/core/notifications/policy.py:21-44`

- [ ] **Step 1: Run the coupling tests first to see them fail**

Run: `pytest tests/unit/services/test_notifications.py tests/unit/services/test_notification_policy.py -v`
Expected: failures referencing `LIFECYCLE` not present in `TEMPLATES` / `DEFAULT_POLICY` (existence-of-each-enum assertion).

(If for any reason those tests don't fail yet, that's fine — the stubs are still required by the spec and the tests added later will exercise them.)

- [ ] **Step 2: Add the TEMPLATES stub**

In `backend/app/services/core/notifications/templates.py`, above the `TEMPLATES = {...}` dict. **The signature must match the other entries in that module: `(ctx: dict, personal: bool = True) -> tuple[str, str]`.** The coupling test calls every template with `(ctx, personal=True)` — any other signature TypeErrors at test time:

```python
def lifecycle(ctx: dict, personal: bool = True) -> tuple[str, str]:
    """Stub template for LIFECYCLE events.

    F-0019d: Loops campaigns POST directly to /webhooks/loops/notification,
    which inserts notifications via insert_external_notification — bypassing
    send_notification entirely. This entry exists only to satisfy the
    coupling-site test that asserts every NotificationEventType has a
    template; if it ever fires it just echoes the externally supplied
    title/body. `personal` is accepted but unused for the same reason.
    """
    return (
        str(ctx.get("title", "Lifecycle update")),
        str(ctx.get("body", "")),
    )
```

Then add it to the `TEMPLATES` map, after `"RUN_SIGNOFF_CANCELLED": run_signoff_cancelled,`:

```python
    "LIFECYCLE": lifecycle,
```

- [ ] **Step 3: Add the DEFAULT_POLICY stub**

In `backend/app/services/core/notifications/policy.py`, append inside the `DEFAULT_POLICY` dict (use whichever entry-ordering pattern is already there; the last entry is fine):

```python
    # F-0019d: in-app row is inserted directly by the Loops webhook via
    # external.py/insert_external_notification, and outbound email is owned by
    # Loops. Changing this DeliveryPolicy has NO effect — delivery never flows
    # through send_notification.
    NotificationEventType.LIFECYCLE.value: DeliveryPolicy(in_app=False, email=False),
```

- [ ] **Step 4: Re-run the coupling tests**

Run: `pytest tests/unit/services/test_notifications.py tests/unit/services/test_notification_policy.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/templates.py \
        backend/app/services/core/notifications/policy.py
git commit -m "feat(F-0019d): add LIFECYCLE stubs for TEMPLATES + DEFAULT_POLICY coupling sites"
```

---

### Task 6: `insert_external_notification` sibling helper

**Files:**
- Create: `backend/app/services/core/notifications/external.py`
- Test: `backend/tests/unit/services/test_external_notification.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/test_external_notification.py
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.iam import Organization, User
from app.models.notifications import Notification, NotificationEventType
from app.services.core.notifications.external import insert_external_notification


@pytest.fixture
async def user(db_session):
    org = Organization(name="Ext Test")
    db_session.add(org)
    await db_session.flush()
    u = User(
        email=f"ext-{uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="Ext",
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_inserts_basic_row(db_session, user):
    notif = await insert_external_notification(
        db=db_session,
        user_id=user.id,
        title="Trial ends soon",
        body="3 days left",
    )
    assert notif.id is not None
    row = (await db_session.execute(select(Notification))).scalar_one()
    assert row.event_type == NotificationEventType.LIFECYCLE.value
    assert row.entity_type == "lifecycle"
    assert row.entity_id == user.id
    assert row.title == "Trial ends soon"
    assert row.message == "3 days left"
    assert row.payload == {}


@pytest.mark.asyncio
async def test_payload_link_and_category(db_session, user):
    await insert_external_notification(
        db=db_session,
        user_id=user.id,
        title="X",
        body="Y",
        link_url="/settings?tab=billing",
        category="trial-warning",
    )
    row = (await db_session.execute(select(Notification))).scalar_one()
    assert row.payload == {
        "link_url": "/settings?tab=billing",
        "category": "trial-warning",
    }


@pytest.mark.asyncio
async def test_caller_owns_commit(db_session, user):
    """Helper must only flush — not commit. Rolling back after the call
    must wipe the row."""
    await insert_external_notification(
        db=db_session, user_id=user.id, title="t", body="b",
    )
    # row visible in this session pre-commit:
    rows_before = (await db_session.execute(select(Notification))).scalars().all()
    assert len(rows_before) == 1
    await db_session.rollback()
    rows_after = (await db_session.execute(select(Notification))).scalars().all()
    assert rows_after == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/services/test_external_notification.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.core.notifications.external'`.

- [ ] **Step 3: Write the helper**

```python
# backend/app/services/core/notifications/external.py
"""Sibling helper for inserting in-app notifications from external sources.

F-0019d: The main ``send_notification`` entry point requires a template
and emits to outbound channels. For Loops webhooks, Loops already sent
the email and the title/body come pre-rendered — both ceremonies are
counter-productive. This helper writes one row to ``notifications``,
flushes (no commit), and returns. The caller owns the transaction so the
caller can write more rows in the same unit of work (e.g. ``loops_events``
+ ``notifications`` in one commit).
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification, NotificationEventType


async def insert_external_notification(
    *,
    db: AsyncSession,
    user_id: UUID,
    title: str,
    body: str,
    link_url: Optional[str] = None,
    category: Optional[str] = None,
) -> Notification:
    """Insert one in-app notification from an external source.

    The caller passes its own session and is responsible for committing
    or rolling back. This helper only ``db.add(...)`` + ``await db.flush()``.

    The flat 5-param signature (excluding ``db``) is intentional: each param
    maps 1:1 to a column on ``Notification`` and is what every conceivable
    external caller (Loops, future vendors) would naturally pass. Grouping
    into a ``NotificationContent`` dataclass adds a type dependency callers
    must import without removing any complexity. Revisit if a 6th content
    param appears.
    """
    payload: dict[str, Any] = {}
    if link_url is not None:
        payload["link_url"] = link_url
    if category is not None:
        payload["category"] = category

    notif = Notification(
        user_id=user_id,
        event_type=NotificationEventType.LIFECYCLE.value,
        entity_type="lifecycle",
        entity_id=user_id,  # synthetic — notification is user-scoped
        title=title,
        message=body,
        payload=payload,
    )
    db.add(notif)
    await db.flush()
    return notif
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/services/test_external_notification.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/external.py \
        backend/tests/unit/services/test_external_notification.py
git commit -m "feat(F-0019d): add insert_external_notification helper"
```

---

### Task 7: `webhooks` router + Loops endpoint (the big one)

**Files:**
- Create: `backend/app/api/endpoints/webhooks.py`
- Modify: `backend/app/main.py:582-604` (mount the router)
- Test: `backend/tests/integration/test_loops_webhook.py`

- [ ] **Step 1: Write the failing tests (full end-to-end)**

Create `backend/tests/integration/test_loops_webhook.py`:

```python
import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.models.iam import Organization, User
from app.models.lifecycle import LoopsEvent
from app.models.notifications import Notification, NotificationEventType


SECRET = "loops-test-secret"


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def configure_secret(monkeypatch):
    monkeypatch.setattr(
        "app.api.endpoints.webhooks.settings.loops_webhook_secret", SECRET,
    )


@pytest.fixture
async def user(db_session):
    org = Organization(name="Webhook Test")
    db_session.add(org)
    await db_session.flush()
    u = User(
        email=f"hook-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        full_name="Hook User",
    )
    db_session.add(u)
    await db_session.commit()
    return u


def _payload(user_email: str, **overrides):
    p = {
        "user_email": user_email,
        "title": "Trial ending soon",
        "body": "You have 3 days left in your trial.",
        "category": "trial-warning",
    }
    p.update(overrides)
    return p


@pytest.mark.asyncio
async def test_unconfigured_503(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(
        "app.api.endpoints.webhooks.settings.loops_webhook_secret", "",
    )
    resp = await client.post(
        "/webhooks/loops/notification",
        json=_payload("anyone@example.com"),
        headers={"X-Loops-Signature": "deadbeef"},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_bad_signature_400(client, configure_secret, user):
    body = json.dumps(_payload(user.email)).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": "deadbeef" * 8, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_oversize_body_413(client, configure_secret):
    body = ("x" * (64 * 1024 + 1)).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_invalid_body_422(client, configure_secret):
    body = b'{"user_email":"not-an-email","title":"t","body":"b"}'
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_user_404(client, configure_secret):
    body = json.dumps(_payload("nobody@example.com")).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_creates_notification_200(client, configure_secret, db_session, user):
    body = json.dumps(_payload(user.email, loops_message_id="msg-1")).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    # Notification row
    notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].title == "Trial ending soon"
    assert notifs[0].event_type == NotificationEventType.LIFECYCLE.value
    assert notifs[0].payload.get("category") == "trial-warning"
    # loops_events row
    events = (await db_session.execute(
        select(LoopsEvent).where(LoopsEvent.user_id == user.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].loops_message_id == "msg-1"


@pytest.mark.asyncio
async def test_idempotent_same_message_id(client, configure_secret, db_session, user):
    body = json.dumps(_payload(user.email, loops_message_id="dup-1")).encode()
    sig = _sign(body)
    headers = {"X-Loops-Signature": sig, "Content-Type": "application/json"}

    r1 = await client.post("/webhooks/loops/notification", content=body, headers=headers)
    r2 = await client.post("/webhooks/loops/notification", content=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json().get("deduped") is True

    notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_same_message_id_different_users(
    client, configure_secret, db_session, user
):
    other = User(
        email=f"other-{uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        full_name="O",
    )
    db_session.add(other)
    await db_session.commit()

    for email in (user.email, other.email):
        body = json.dumps(_payload(email, loops_message_id="campaign-7")).encode()
        resp = await client.post(
            "/webhooks/loops/notification",
            content=body,
            headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    notifs = (await db_session.execute(select(Notification))).scalars().all()
    assert {n.user_id for n in notifs} == {user.id, other.id}


@pytest.mark.asyncio
async def test_uppercase_signature_accepted(client, configure_secret, db_session, user):
    body = json.dumps(_payload(user.email)).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body).upper(), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_link_url_must_be_same_origin_path(client, configure_secret, user):
    """Reject anything that isn't a same-origin path: full URLs, protocol-
    relative URLs, schemes — all 422 before they reach the DB.
    """
    for bad_url in [
        "https://example.com/runs/abc",   # full URL — Loops should send paths
        "//evil.com/phish",                # protocol-relative
        "javascript:alert(1)",             # scheme
        "runs/abc",                        # missing leading /
    ]:
        body = json.dumps(_payload(user.email, link_url=bad_url)).encode()
        resp = await client.post(
            "/webhooks/loops/notification",
            content=body,
            headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
        )
        assert resp.status_code == 422, f"Expected 422 for {bad_url!r}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_link_url_path_accepted(client, configure_secret, db_session, user):
    """A same-origin path like ``/runs/abc-123`` round-trips into payload."""
    body = json.dumps(_payload(user.email, link_url="/runs/abc-123")).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    notif = (await db_session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalar_one()
    assert notif.payload.get("link_url") == "/runs/abc-123"


@pytest.mark.asyncio
async def test_payload_check_violation_rolls_back(
    client, configure_secret, db_session, user, monkeypatch
):
    """Spec requirement: if the notifications.payload 512-byte CHECK fires,
    BOTH the loops_events row and the notification row must be rolled back.
    Otherwise an orphan loops_events row would silently swallow a retry."""
    # Patch the CHECK ceiling down to a tiny value so even the small test
    # payload trips it. Apply via monkeypatching the helper to inject
    # oversized JSON we can't otherwise generate within the Pydantic caps.
    from app.services.core.notifications import external as ext

    async def boom(*args, **kwargs):
        raise __import__("sqlalchemy").exc.IntegrityError(
            "payload check", {}, Exception("ck_notifications_payload_size"),
        )

    monkeypatch.setattr(ext, "insert_external_notification", boom)

    body = json.dumps(_payload(user.email, loops_message_id="rollback-1")).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert resp.status_code == 500

    # Neither row survives the rollback.
    notifs = (await db_session.execute(select(Notification))).scalars().all()
    events = (await db_session.execute(select(LoopsEvent))).scalars().all()
    assert notifs == []
    assert events == []


@pytest.mark.asyncio
async def test_oversized_signature_header_400(client, configure_secret, user):
    """Header values > MAX_SIGNATURE_HEADER_BYTES short-circuit to 400
    before HMAC compute — protects against DoS via gigantic header values."""
    body = json.dumps(_payload(user.email)).encode()
    resp = await client.post(
        "/webhooks/loops/notification",
        content=body,
        headers={"X-Loops-Signature": "a" * 201, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_loops_webhook.py -v`
Expected: `404` on every request (the route doesn't exist yet).

- [ ] **Step 3: Implement the router**

Create `backend/app/api/endpoints/webhooks.py`:

```python
"""Inbound vendor webhooks (currently: Loops lifecycle notifications).

Each route in this file authenticates via a vendor-specific HMAC and
inserts side-effect rows. The router is mounted at ``/webhooks`` and
each route adds its exact path to ``PUBLIC_PATHS`` in middleware.py so
the auth middleware does not redirect-to-login on what should be a 401-
unauthenticated, signature-authenticated call.

F-0019d adds the Loops notification endpoint. Future inbound webhooks
land in this same file.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db
from app.core.webhook_auth import verify_hmac_sha256
from app.models.iam import User
from app.models.lifecycle import LoopsEvent
from app.services.core.notifications.external import insert_external_notification

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_BODY_BYTES = 64 * 1024  # 64 KB; lifecycle payloads are tiny
# An honest sha256 hex digest is 64 chars. We allow a small slop for the
# optional ``sha256=`` prefix and casing drift. Anything beyond cap is
# rejected before we waste time HMAC'ing — protects against attackers
# spamming the endpoint with megabyte-long header strings.
MAX_SIGNATURE_HEADER_BYTES = 200


def _mask_email(email: str) -> str:
    """``user@example.com`` -> ``u**@example.com``.

    Sufficient to keep info-level logs from leaking the enumeration
    oracle while a leaked secret is still being rotated.
    """
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "***"
    if len(local) <= 1:
        return f"{local}**@{domain}"
    return f"{local[0]}**@{domain}"


class LoopsNotificationPayload(BaseModel):
    user_email: EmailStr
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    # Same-origin path only. Loops campaigns send strings like "/runs/abc-123"
    # or "/settings?tab=billing". The pattern enforces "starts with a single
    # /, not //" — blocks protocol-relative URLs (//evil.com/path) that would
    # let an attacker phish via the deep-link router. 300-char cap keeps the
    # serialized payload inside notifications.payload's 512-byte CHECK.
    link_url: Optional[str] = Field(
        default=None, max_length=300, pattern=r"^/[^/].*"
    )
    category: Optional[str] = Field(default=None, max_length=64)
    loops_message_id: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")


@router.post("/loops/notification", status_code=200)
async def loops_notification_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.loops_webhook_secret:
        raise HTTPException(503, "Loops webhook is not configured")

    # IMPORTANT: do NOT refactor this to a `payload: LoopsNotificationPayload`
    # parameter — FastAPI would consume the body before we can hash it,
    # and `await request.body()` would return b"" on the second read,
    # silently bypassing signature verification. Raw-body-first.
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Payload too large")

    sig = request.headers.get("X-Loops-Signature", "")
    if len(sig) > MAX_SIGNATURE_HEADER_BYTES:
        # Reject monstrously long header values before spending CPU on HMAC.
        raise HTTPException(400, "Invalid signature")
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

    try:
        async with asyncio.timeout(5.0):
            user = (
                await db.execute(
                    select(User).where(User.email == payload.user_email)
                )
            ).scalar_one_or_none()
    except asyncio.TimeoutError:
        logger.warning("Loops webhook user lookup timed out")
        raise HTTPException(504, "User lookup timed out")

    if user is None:
        logger.info(
            "Loops webhook user not found: email=%s",
            _mask_email(payload.user_email),
        )
        raise HTTPException(404, "User not found")

    if payload.loops_message_id:
        # pg_insert(...).on_conflict_do_nothing().returning(id) returns:
        #   - a single row containing the new id when the insert succeeded
        #   - no rows (scalar_one_or_none -> None) when the UNIQUE
        #     constraint fired (DO NOTHING). That is the ONLY way None can
        #     be returned here within an active transaction; an actual DB
        #     error would raise, not silently no-op. So `inserted is None`
        #     is the unambiguous duplicate-delivery signal.
        stmt = (
            pg_insert(LoopsEvent)
            .values(
                loops_message_id=payload.loops_message_id,
                user_id=user.id,
            )
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
            link_url=payload.link_url,
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

    logger.info(
        "Loops webhook processed: user_id=%s message_id=%s",
        user.id, payload.loops_message_id,
    )
    return {"received": True}
```

- [ ] **Step 4: Mount the router**

In `backend/app/main.py`, add the import alongside the **other endpoint imports** (currently around line 555 — where `billing` is imported, NOT inline at the include_router block around line 582):

```python
from app.api.endpoints import webhooks  # add to the endpoint-imports block
```

Then add the mount near the other `app.include_router(...)` calls (around line 582), placed next to the `billing.router` mount:

```python
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
```

Verify via `grep -n "billing.router" backend/app/main.py` and `grep -n "from app.api.endpoints import billing" backend/app/main.py` — put the new lines adjacent to those, in their respective sections.

- [ ] **Step 5: Run integration tests**

Run: `pytest tests/integration/test_loops_webhook.py -v`
Expected: 13 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/webhooks.py backend/app/main.py \
        backend/tests/integration/test_loops_webhook.py
git commit -m "feat(F-0019d): add POST /webhooks/loops/notification endpoint"
```

---

### Task 8: Concurrent-duplicate test (race coverage)

Separate task because it's flaky if rolled into Task 7's test class — fix here.

**Files:**
- Modify: `backend/tests/integration/test_loops_webhook.py` (append)

- [ ] **Step 1: Append test**

```python
@pytest.mark.asyncio
async def test_concurrent_duplicates_create_one_notification(
    client, configure_secret, db_session, user
):
    """Two requests in flight with the same (message_id, user_id) must
    resolve to exactly one notification row. The composite UNIQUE on
    loops_events + ON CONFLICT DO NOTHING is what enforces this.

    PRECONDITION: ``client`` must dispatch each request through its own
    ``get_db`` dependency (which is the default — FastAPI calls the
    dependency per-request). If a conftest override pins all requests to
    one SQLAlchemy session, the requests will serialize and the test
    becomes meaningless. Verify by grepping conftest.py for
    ``app.dependency_overrides[get_db]`` — there should be no override
    that returns a shared session.
    """
    body = json.dumps(_payload(user.email, loops_message_id="race-1")).encode()
    headers = {"X-Loops-Signature": _sign(body), "Content-Type": "application/json"}

    r1, r2 = await asyncio.gather(
        client.post("/webhooks/loops/notification", content=body, headers=headers),
        client.post("/webhooks/loops/notification", content=body, headers=headers),
    )
    assert {r1.status_code, r2.status_code} == {200}
    # Exactly one of the two must have been deduped (the other got the
    # insert through). Both deduping is also acceptable IF some interleaving
    # had one request commit before the other reached the insert.
    deduped_flags = [r.json().get("deduped", False) for r in (r1, r2)]
    assert sum(deduped_flags) >= 1, (
        "Expected at least one response to report deduped=True; got "
        f"{deduped_flags}. Likely a conftest get_db override is serializing requests."
    )

    notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == user.id)
    )).scalars().all()
    assert len(notifs) == 1
```

- [ ] **Step 2: Run the new test**

Run: `pytest tests/integration/test_loops_webhook.py::test_concurrent_duplicates_create_one_notification -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_loops_webhook.py
git commit -m "test(F-0019d): assert concurrent duplicates dedupe to single notification"
```

---

### Task 9: Lifecycle deep-link branch in `links.py`

**Files:**
- Modify: `backend/app/services/core/notifications/links.py` (insert lifecycle branch above the `_ROUTABLE` short-circuit at line 68)
- Test: `backend/tests/unit/services/test_notification_links.py` (extend, or create if not present)

- [ ] **Step 1: Locate the test file**

```bash
find backend/tests -name "test_notification_links*" -o -name "test_links*" | head
```

Use the existing file if present; otherwise create `backend/tests/unit/services/test_notification_links.py`.

- [ ] **Step 2: Write failing tests**

Append (or create) the following:

```python
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.iam import Organization, User
from app.models.notifications import Notification, NotificationEventType
from app.services.core.notifications.links import resolve_notification_urls


async def _make_user(db_session):
    org = Organization(name="Lk")
    db_session.add(org)
    await db_session.flush()
    u = User(
        email=f"l-{uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="L",
    )
    db_session.add(u)
    await db_session.flush()
    return u


def _notif(user_id, link_url=None):
    return Notification(
        user_id=user_id,
        event_type=NotificationEventType.LIFECYCLE.value,
        entity_type="lifecycle",
        entity_id=user_id,
        title="t",
        message="b",
        payload={"link_url": link_url} if link_url else {},
    )


@pytest.mark.asyncio
async def test_lifecycle_same_origin_path_pass(db_session):
    u = await _make_user(db_session)
    n = _notif(u.id, "/settings?tab=billing")
    db_session.add(n)
    await db_session.flush()
    urls = await resolve_notification_urls(db_session, [n], u.id)
    assert urls[n.id] == "/settings?tab=billing"


@pytest.mark.asyncio
async def test_lifecycle_external_host_rejected(db_session):
    u = await _make_user(db_session)
    n = _notif(u.id, "https://evil.example.com/foo")
    db_session.add(n)
    await db_session.flush()
    urls = await resolve_notification_urls(db_session, [n], u.id)
    assert urls[n.id] == "/notifications"


@pytest.mark.asyncio
async def test_lifecycle_protocol_relative_rejected(db_session):
    u = await _make_user(db_session)
    n = _notif(u.id, "//evil.example.com/foo")
    db_session.add(n)
    await db_session.flush()
    urls = await resolve_notification_urls(db_session, [n], u.id)
    assert urls[n.id] == "/notifications"


@pytest.mark.asyncio
async def test_lifecycle_no_link_falls_back(db_session):
    u = await _make_user(db_session)
    n = _notif(u.id)  # no link_url
    db_session.add(n)
    await db_session.flush()
    urls = await resolve_notification_urls(db_session, [n], u.id)
    assert urls[n.id] == "/notifications"


@pytest.mark.asyncio
async def test_all_lifecycle_batch_still_resolves(db_session):
    """REGRESSION: a batch containing ONLY lifecycle notifications must
    not get swallowed by the ``if not targets: return {n.id: None ...}``
    short-circuit in resolve_notification_urls. The lifecycle entries
    must survive the merge."""
    u = await _make_user(db_session)
    a = _notif(u.id, "/runs/abc")
    b = _notif(u.id, "/settings?tab=billing")
    db_session.add_all([a, b])
    await db_session.flush()
    urls = await resolve_notification_urls(db_session, [a, b], u.id)
    assert urls[a.id] == "/runs/abc"
    assert urls[b.id] == "/settings?tab=billing"
    # NOT {a.id: None, b.id: None} — that would mean the short-circuit fired.
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/services/test_notification_links.py -v -k lifecycle`
Expected: assertion failures or `None`/missing-key errors (lifecycle branch doesn't exist).

- [ ] **Step 4: Edit `links.py` — insert the lifecycle branch and merge into ALL return paths**

Open `backend/app/services/core/notifications/links.py`. The function `resolve_notification_urls` builds `ids_by_type` (around line 63-69) by grouping notifications by `_ROUTABLE` entity-types, then short-circuits at line ~123 with `if not targets: return {n.id: None for n in notifications}`.

The lifecycle branch must run **first** so lifecycle notifications get stripped out before the `_ROUTABLE` grouping. Insert right after the early-return `if not notifications: return {}`:

```python
    # F-0019d: lifecycle notifications carry their destination in
    # payload["link_url"] — no DB entity to look up. Allowlist is same-
    # origin path-only: must start with "/" and not "//" (which would let
    # protocol-relative URLs through). Anything else falls back to
    # /notifications.
    out: dict[UUID, Optional[str]] = {}
    remaining: list[Notification] = []
    for n in notifications:
        if (n.entity_type or "").lower() == "lifecycle":
            link = (n.payload or {}).get("link_url")
            if isinstance(link, str) and link.startswith("/") and not link.startswith("//"):
                out[n.id] = link
            else:
                out[n.id] = "/notifications"
        else:
            remaining.append(n)

    if not remaining:
        return out
    notifications = remaining
```

Now patch **every** subsequent return path in `resolve_notification_urls` to merge `out` into it. Specifically:

1. **The early-return when `targets` is empty** (line ~123): `return {n.id: None for n in notifications}` becomes `return {**out, **{n.id: None for n in notifications}}`. Without this fix, an all-lifecycle batch (which empties `targets`) returns `None` for every lifecycle notification, ignoring the carefully-built `out` dict.

2. **The final return** at the end of the function: whatever the existing `return result_map` is, change to `return {**out, **result_map}` (or `result_map.update(out); return result_map`).

Grep first to enumerate all `return` statements in the function before editing:

```bash
grep -n "return" backend/app/services/core/notifications/links.py | sed -n '1,30p'
```

Every return inside `resolve_notification_urls` must produce a dict that includes the lifecycle entries from `out`. Add a unit test (Step 2) for the all-lifecycle batch specifically — that's the case that catches the missed merge.

- [ ] **Step 5: Run all link tests to verify**

Run: `pytest tests/unit/services/test_notification_links.py -v`
Expected: green, including the existing non-lifecycle tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/core/notifications/links.py \
        backend/tests/unit/services/test_notification_links.py
git commit -m "feat(F-0019d): lifecycle deep-link with same-origin allowlist"
```

---

### Task 10: Frontend `EVENT_ICONS` + `EVENT_TONES` entries

**Files:**
- Modify: `frontend/src/lib/notifications.ts`
- Test: `frontend/src/lib/notifications.test.ts` (create if not present)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/notifications.test.ts
import { describe, it, expect } from 'vitest';
import { CreditCard, Bell } from 'lucide-svelte';
import { eventIcon, eventTone } from './notifications';

describe('lifecycle event maps', () => {
    it('LIFECYCLE icon is CreditCard', () => {
        expect(eventIcon('LIFECYCLE')).toBe(CreditCard);
    });
    it('LIFECYCLE tone uses amber', () => {
        expect(eventTone('LIFECYCLE')).toContain('amber');
    });
    it('unknown type still falls back to Bell', () => {
        expect(eventIcon('UNKNOWN_TYPE_XYZ')).toBe(Bell);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/notifications.test.ts`
Expected: assertion failures for LIFECYCLE entries.

- [ ] **Step 3: Add the entries**

In `frontend/src/lib/notifications.ts`:

1. Add `CreditCard` to the lucide-svelte import (alphabetically):

```ts
import {
    AlertTriangle,
    ArrowLeft,
    ArrowLeftRight,
    ArrowRight,
    BadgeCheck,
    Bell,
    CheckCircle2,
    CreditCard,
    FileCheck2,
    Mail,
    Play,
    Undo2,
} from 'lucide-svelte';
```

2. Add to the `EVENT_ICONS` map (after `STEP_DEVIATION`):

```ts
    LIFECYCLE: CreditCard,
```

3. Add to the `EVENT_TONES` map (after `STEP_DEVIATION`):

```ts
    LIFECYCLE: 'bg-amber-500/15 text-amber-600',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/notifications.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/notifications.ts frontend/src/lib/notifications.test.ts
git commit -m "feat(F-0019d): map LIFECYCLE notification to CreditCard + amber tone"
```

---

### Task 11: Visibility-change reload for subscription store

**Files:**
- Modify: `frontend/src/lib/stores/subscription.svelte.ts`
- Test: extend or add to `frontend/src/lib/stores/subscription.test.ts`

- [ ] **Step 1: Locate or create the test file**

```bash
find frontend/src -name "subscription*test*" | head
```

If none exists, create `frontend/src/lib/stores/subscription.test.ts`.

- [ ] **Step 2: Write the failing test**

```ts
// frontend/src/lib/stores/subscription.test.ts (add to whatever already exists)
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('initSubscriptionRefresh', () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

    it('reloads on visibilitychange when document becomes visible', async () => {
        const mod = await import('./subscription.svelte');
        const spy = vi.spyOn(mod, 'loadSubscription').mockResolvedValue();
        const cleanup = mod.initSubscriptionRefresh();
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
        expect(spy).toHaveBeenCalledTimes(1);
        cleanup();
    });

    it('throttles to at most one call per minute', async () => {
        const mod = await import('./subscription.svelte');
        const spy = vi.spyOn(mod, 'loadSubscription').mockResolvedValue();
        const cleanup = mod.initSubscriptionRefresh();
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
        document.dispatchEvent(new Event('visibilitychange'));
        expect(spy).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(60_001);
        document.dispatchEvent(new Event('visibilitychange'));
        expect(spy).toHaveBeenCalledTimes(2);
        cleanup();
    });

    it('does nothing while document is hidden', async () => {
        const mod = await import('./subscription.svelte');
        const spy = vi.spyOn(mod, 'loadSubscription').mockResolvedValue();
        const cleanup = mod.initSubscriptionRefresh();
        Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
        expect(spy).not.toHaveBeenCalled();
        cleanup();
    });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/stores/subscription.test.ts`
Expected: `initSubscriptionRefresh is not a function`.

- [ ] **Step 4: Implement `initSubscriptionRefresh`**

Append to `frontend/src/lib/stores/subscription.svelte.ts`:

```ts
let lastRefreshAt = 0;
const REFRESH_THROTTLE_MS = 60_000;

/** Reload subscription state when the tab regains focus (e.g. user
 * returns from Stripe portal). Throttled to once per minute so rapid
 * tab-flipping doesn't hammer the API. Returns a cleanup function. */
export function initSubscriptionRefresh(): () => void {
    function onVisibility() {
        if (typeof document === 'undefined') return;
        if (document.visibilityState !== 'visible') return;
        const now = Date.now();
        if (now - lastRefreshAt < REFRESH_THROTTLE_MS) return;
        lastRefreshAt = now;
        void loadSubscription();
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
}
```

- [ ] **Step 5: Wire init in `+layout.svelte`**

In `frontend/src/routes/+layout.svelte`:

1. Add the import next to existing store imports:

```ts
import { initSubscriptionRefresh, loadSubscription } from '$lib/stores/subscription.svelte';
```

2. In the `<script>` block at component scope (NOT inside any function), declare:

```ts
let cleanupSubRefresh: (() => void) | undefined;
```

This MUST be at module/component scope, not inside `onMount`. A `const`/`let` declared inside `onMount` is invisible to `onDestroy`, so the listener would leak. The plan reviewer flagged this explicitly — do not skip the scope hoist.

3. In `onMount`, after `await ensureInitialized()` (so we know the user is logged in), call:

```ts
await loadSubscription();
cleanupSubRefresh = initSubscriptionRefresh();
```

4. In `onDestroy`, call:

```ts
cleanupSubRefresh?.();
```

- [ ] **Step 6: Run tests to verify**

Run: `npx vitest run src/lib/stores/subscription.test.ts`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/stores/subscription.svelte.ts \
        frontend/src/lib/stores/subscription.test.ts \
        frontend/src/routes/+layout.svelte
git commit -m "feat(F-0019d): refresh subscription on tab-refocus (throttled 60s)"
```

---

### Task 12: `SubscriptionBanner.svelte` — locked-out variant

Start with the highest-priority variant; layer the others on in subsequent tasks. Each variant is a separate task so the diff is small and the tests grow with the feature.

**Files:**
- Create: `frontend/src/lib/components/layout/SubscriptionBanner.svelte`
- Create: `frontend/src/lib/components/layout/SubscriptionBanner.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/components/layout/SubscriptionBanner.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import SubscriptionBanner from './SubscriptionBanner.svelte';

// We'll stub the subscription store module. The component imports
// `subscription` and `openPortal` from it.
vi.mock('$lib/stores/subscription.svelte', () => {
    let state: any = null;
    return {
        subscription: {
            get state() { return state; },
        },
        openPortal: vi.fn(),
        __setState: (next: any) => { state = next; },
    };
});

// Convenience helper to set the mocked state
async function setState(next: any) {
    const mod: any = await import('$lib/stores/subscription.svelte');
    mod.__setState(next);
}

describe('SubscriptionBanner — locked-out', () => {
    beforeEach(async () => {
        await setState(null);
        localStorage.clear();
    });

    it('renders nothing when state is null', async () => {
        await setState(null);
        const { container } = render(SubscriptionBanner);
        expect(container.textContent?.trim()).toBe('');
    });

    it('renders the locked-out banner when is_locked_out=true', async () => {
        await setState({
            is_locked_out: true,
            cancel_at_period_end: false,
            days_remaining_in_trial: null,
            current_period_end: null,
        });
        const { getByText } = render(SubscriptionBanner);
        expect(getByText(/not active/i)).toBeTruthy();
        expect(getByText(/Manage billing/i)).toBeTruthy();
    });

    it('locked-out wins over trial countdown when both set', async () => {
        await setState({
            is_locked_out: true,
            cancel_at_period_end: false,
            days_remaining_in_trial: 3,
            current_period_end: null,
        });
        const { queryByText } = render(SubscriptionBanner);
        expect(queryByText(/not active/i)).toBeTruthy();
        expect(queryByText(/Trial ends/i)).toBeNull();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: `Cannot find module './SubscriptionBanner.svelte'`.

- [ ] **Step 3: Implement the component (locked-out branch only for now)**

```svelte
<!-- frontend/src/lib/components/layout/SubscriptionBanner.svelte -->
<script lang="ts">
    import { subscription, openPortal } from '$lib/stores/subscription.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Lock } from 'lucide-svelte';

    const state = $derived(subscription.state);
    const isLockedOut = $derived(!!state?.is_locked_out);
</script>

{#if isLockedOut}
    <div
        class="bg-red-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
        role="alert"
    >
        <Lock class="w-4 h-4 flex-shrink-0" />
        <span>Your subscription is not active. Reads and exports remain available, but new changes are blocked.</span>
        <Button
            variant="secondary"
            size="sm"
            class="bg-white text-red-700 hover:bg-red-50"
            onclick={() => openPortal()}
        >
            Manage billing
        </Button>
    </div>
{/if}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/layout/SubscriptionBanner.svelte \
        frontend/src/lib/components/layout/SubscriptionBanner.test.ts
git commit -m "feat(F-0019d): add SubscriptionBanner with locked-out variant"
```

---

### Task 13: `SubscriptionBanner` — cancel-at-period-end variant

**Files:**
- Modify: `frontend/src/lib/components/layout/SubscriptionBanner.svelte`
- Modify: `frontend/src/lib/components/layout/SubscriptionBanner.test.ts`

- [ ] **Step 1: Write the failing test (append)**

```ts
describe('SubscriptionBanner — cancel-at-period-end', () => {
    beforeEach(async () => {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState(null);
        localStorage.clear();
    });

    it('renders the cancel banner when cancel_at_period_end=true', async () => {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState({
            is_locked_out: false,
            cancel_at_period_end: true,
            days_remaining_in_trial: null,
            current_period_end: '2026-06-18T00:00:00Z',
        });
        const { getByText } = render(SubscriptionBanner);
        expect(getByText(/Subscription ends Jun 18/i)).toBeTruthy();
        expect(getByText(/Manage billing/i)).toBeTruthy();
    });

    it('cancel wins over trial countdown', async () => {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState({
            is_locked_out: false,
            cancel_at_period_end: true,
            days_remaining_in_trial: 3,
            current_period_end: '2026-06-18T00:00:00Z',
        });
        const { queryByText } = render(SubscriptionBanner);
        expect(queryByText(/Subscription ends/i)).toBeTruthy();
        expect(queryByText(/Trial ends/i)).toBeNull();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: `Subscription ends Jun 18` not found.

- [ ] **Step 3: Add the variant**

Edit `SubscriptionBanner.svelte`. Update the script:

```svelte
<script lang="ts">
    import { subscription, openPortal } from '$lib/stores/subscription.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Lock, CalendarX } from 'lucide-svelte';

    const state = $derived(subscription.state);
    const isLockedOut = $derived(!!state?.is_locked_out);
    const isCancelling = $derived(!isLockedOut && !!state?.cancel_at_period_end);

    function formatPeriodEnd(iso: string | null | undefined): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric',
        }).format(d);
    }
</script>
```

Append the new branch after the locked-out block:

```svelte
{:else if isCancelling}
    <div
        class="bg-amber-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
        role="status"
    >
        <CalendarX class="w-4 h-4 flex-shrink-0" />
        <span>Subscription ends {formatPeriodEnd(state?.current_period_end)}.</span>
        <Button
            variant="secondary"
            size="sm"
            class="bg-white text-amber-700 hover:bg-amber-50"
            onclick={() => openPortal()}
        >
            Manage billing
        </Button>
    </div>
```

(Note: the existing `{#if isLockedOut}` needs to become `{#if isLockedOut} ... {:else if isCancelling} ...` — single if/elseif/elseif chain. Don't write two separate `{#if}` blocks or both could render.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/layout/SubscriptionBanner.svelte \
        frontend/src/lib/components/layout/SubscriptionBanner.test.ts
git commit -m "feat(F-0019d): add cancel-at-period-end variant to SubscriptionBanner"
```

---

### Task 14: `SubscriptionBanner` — trial countdown variant + dismissal

This is the largest variant — five copy thresholds, two surface treatments, daily-key dismissal.

**Files:**
- Modify: `frontend/src/lib/components/layout/SubscriptionBanner.svelte`
- Modify: `frontend/src/lib/components/layout/SubscriptionBanner.test.ts`

- [ ] **Step 1: Write the failing tests (append)**

```ts
describe('SubscriptionBanner — trial countdown', () => {
    beforeEach(async () => {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState(null);
        localStorage.clear();
    });

    async function mountWithTrial(days: number, end: string = '2026-06-08T00:00:00Z') {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState({
            is_locked_out: false,
            cancel_at_period_end: false,
            days_remaining_in_trial: days,
            current_period_end: null,
            trial_end: end,
        });
        return render(SubscriptionBanner);
    }

    it('day 14 shows soft blue informational copy with absolute date', async () => {
        const { getByText, container } = await mountWithTrial(14);
        expect(getByText(/Trial ends/i)).toBeTruthy();
        expect(getByText(/Add a payment method when ready/i)).toBeTruthy();
        expect(container.querySelector('.bg-blue-50')).toBeTruthy();
    });

    it('day 8 still in soft blue informational tier', async () => {
        const { container } = await mountWithTrial(8);
        expect(container.querySelector('.bg-blue-50')).toBeTruthy();
    });

    it('day 7 escalates to amber', async () => {
        const { container } = await mountWithTrial(7);
        expect(container.querySelector('.bg-amber-500')).toBeTruthy();
    });

    it('day 3 amber with "in 3 days" copy', async () => {
        const { getByText } = await mountWithTrial(3);
        expect(getByText(/Trial ends in 3 days/i)).toBeTruthy();
    });

    it('day 2 escalates to red', async () => {
        const { container, getByText } = await mountWithTrial(2);
        expect(container.querySelector('.bg-red-500')).toBeTruthy();
        expect(getByText(/Trial ends in 2 days/i)).toBeTruthy();
    });

    it('day 1 says "tomorrow"', async () => {
        const { getByText } = await mountWithTrial(1);
        expect(getByText(/Trial ends tomorrow/i)).toBeTruthy();
    });

    it('day 0 says "at midnight tonight"', async () => {
        const { getByText } = await mountWithTrial(0);
        expect(getByText(/at midnight tonight/i)).toBeTruthy();
    });

    it('negative days renders the day-0 copy (defensive)', async () => {
        const { getByText } = await mountWithTrial(-1);
        expect(getByText(/at midnight tonight/i)).toBeTruthy();
    });

    it('null days renders no banner', async () => {
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState({
            is_locked_out: false,
            cancel_at_period_end: false,
            days_remaining_in_trial: null,
            current_period_end: null,
        });
        const { container } = render(SubscriptionBanner);
        expect(container.textContent?.trim()).toBe('');
    });

    it('dismiss writes daily key and hides banner on remount', async () => {
        const { getByLabelText, unmount } = await mountWithTrial(5);
        const btn = getByLabelText(/dismiss/i);
        btn.click();
        const today = new Date().toISOString().slice(0, 10);
        expect(localStorage.getItem(`subscription-banner-dismissed-trial-${today}`)).toBe('true');
        unmount();
        const { container } = await mountWithTrial(5);
        expect(container.textContent?.trim()).toBe('');
    });

    it('yesterday-keyed dismissal does not suppress today', async () => {
        const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
        localStorage.setItem(`subscription-banner-dismissed-trial-${yesterday}`, 'true');
        const { getByText } = await mountWithTrial(5);
        expect(getByText(/Trial ends/i)).toBeTruthy();
    });

    it('locked-out bypasses prior dismissal', async () => {
        const today = new Date().toISOString().slice(0, 10);
        localStorage.setItem(`subscription-banner-dismissed-trial-${today}`, 'true');
        const mod: any = await import('$lib/stores/subscription.svelte');
        mod.__setState({
            is_locked_out: true,
            cancel_at_period_end: false,
            days_remaining_in_trial: 5,
            current_period_end: null,
        });
        const { getByText } = render(SubscriptionBanner);
        expect(getByText(/not active/i)).toBeTruthy();
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: many failures (trial branch not implemented).

- [ ] **Step 3: Implement the trial variant + dismissal**

Replace the full `SubscriptionBanner.svelte` script with:

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { subscription, openPortal } from '$lib/stores/subscription.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Lock, CalendarX, AlertCircle, AlertTriangle, Info, X } from 'lucide-svelte';

    const state = $derived(subscription.state);
    const isLockedOut = $derived(!!state?.is_locked_out);
    const isCancelling = $derived(!isLockedOut && !!state?.cancel_at_period_end);

    // `now` is reactive state that we tick every minute. todayKey, dismissed
    // status, and copy thresholds all derive from it, so the banner correctly
    // re-evaluates after midnight if the tab is left open overnight.
    // Without this, a user who opens the app at 11:55pm and is still on the
    // page at 12:05am sees the previous day's banner state (stale dismissal,
    // stale day count).
    let now = $state(Date.now());
    let tickHandle: ReturnType<typeof setInterval> | undefined;
    onMount(() => {
        tickHandle = setInterval(() => { now = Date.now(); }, 60_000);
    });
    onDestroy(() => {
        if (tickHandle != null) clearInterval(tickHandle);
    });

    const todayKey = $derived(
        `subscription-banner-dismissed-trial-${new Date(now).toISOString().slice(0, 10)}`,
    );
    let dismissedToday = $state(false);

    // Re-read dismissal whenever todayKey changes (initial mount, date
    // rollover, or dismiss() flips it within the same day).
    $effect(() => {
        try {
            dismissedToday = localStorage.getItem(todayKey) === 'true';
        } catch {
            dismissedToday = false;
        }
    });

    // Trial visible iff days_remaining_in_trial is defined, <= 14, and
    // not dismissed today. Higher-priority variants bypass this check.
    const days = $derived(state?.days_remaining_in_trial);
    const showTrial = $derived(
        !isLockedOut &&
        !isCancelling &&
        days != null &&
        days <= 14 &&
        !dismissedToday,
    );

    type TrialTier = 'info' | 'warn' | 'crit';
    const trialTier: TrialTier = $derived.by(() => {
        if (days == null) return 'info';
        if (days >= 8) return 'info';
        if (days >= 3) return 'warn';
        return 'crit';
    });

    function formatDate(iso: string | null | undefined): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        return new Intl.DateTimeFormat(undefined, {
            month: 'short', day: 'numeric',
        }).format(d);
    }

    function trialCopy(d: number, trialEnd: string | null | undefined): string {
        const dateStr = formatDate(trialEnd);
        if (d >= 8) return `Trial ends ${dateStr}. Add a payment method when ready.`;
        if (d >= 4) return `Trial ends ${dateStr} — add a payment method to continue without interruption.`;
        if (d === 3) return 'Trial ends in 3 days. Add a payment method.';
        if (d === 2) return 'Trial ends in 2 days. Add a payment method.';
        if (d === 1) return 'Trial ends tomorrow. Add a payment method.';
        return 'Trial ends at midnight tonight. Add a payment method to maintain access.';
    }

    function dismiss() {
        try {
            localStorage.setItem(todayKey, 'true');
        } catch { /* ignore quota errors */ }
        dismissedToday = true;
    }
</script>

{#if isLockedOut}
    <div
        class="bg-red-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
        role="alert"
    >
        <Lock class="w-4 h-4 flex-shrink-0" />
        <span>Your subscription is not active. Reads and exports remain available, but new changes are blocked.</span>
        <Button
            variant="secondary"
            size="sm"
            class="bg-white text-red-700 hover:bg-red-50"
            onclick={() => openPortal()}
        >
            Manage billing
        </Button>
    </div>
{:else if isCancelling}
    <div
        class="bg-amber-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
        role="status"
    >
        <CalendarX class="w-4 h-4 flex-shrink-0" />
        <span>Subscription ends {formatDate(state?.current_period_end) || 'soon'}.</span>
        <Button
            variant="secondary"
            size="sm"
            class="bg-white text-amber-700 hover:bg-amber-50"
            onclick={() => openPortal()}
        >
            Manage billing
        </Button>
    </div>
{:else if showTrial && days != null}
    {#if trialTier === 'info'}
        <div
            class="bg-blue-50 border-b border-blue-200 text-blue-900 px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
            role="status"
        >
            <Info class="w-4 h-4 flex-shrink-0 text-blue-600" />
            <span>{trialCopy(Math.max(0, days), state?.trial_end)}</span>
            <Button
                variant="default"
                size="sm"
                onclick={() => openPortal()}
            >
                Add payment method
            </Button>
            <Button
                variant="ghost"
                size="icon-sm"
                class="min-h-[44px] min-w-[44px] opacity-70 hover:opacity-100 text-blue-900"
                aria-label="Dismiss"
                onclick={dismiss}
            >
                <X class="w-4 h-4" />
            </Button>
        </div>
    {:else if trialTier === 'warn'}
        <div
            class="bg-amber-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
            role="status"
        >
            <AlertTriangle class="w-4 h-4 flex-shrink-0" />
            <span>{trialCopy(Math.max(0, days), state?.trial_end)}</span>
            <Button
                variant="secondary"
                size="sm"
                class="bg-white text-amber-700 hover:bg-amber-50"
                onclick={() => openPortal()}
            >
                Add payment method
            </Button>
            <Button
                variant="ghost"
                size="icon-sm"
                class="min-h-[44px] min-w-[44px] opacity-70 hover:opacity-100 text-white hover:bg-amber-600"
                aria-label="Dismiss"
                onclick={dismiss}
            >
                <X class="w-4 h-4" />
            </Button>
        </div>
    {:else}
        <div
            class="bg-red-500 text-white px-4 py-3 text-sm font-medium flex items-center justify-center gap-3"
            role="alert"
        >
            <AlertCircle class="w-4 h-4 flex-shrink-0" />
            <span>{trialCopy(Math.max(0, days), state?.trial_end)}</span>
            <Button
                variant="secondary"
                size="sm"
                class="bg-white text-red-700 hover:bg-red-50"
                onclick={() => openPortal()}
            >
                Add payment method
            </Button>
            <Button
                variant="ghost"
                size="icon-sm"
                class="min-h-[44px] min-w-[44px] opacity-70 hover:opacity-100 text-white hover:bg-red-600"
                aria-label="Dismiss"
                onclick={dismiss}
            >
                <X class="w-4 h-4" />
            </Button>
        </div>
    {/if}
{/if}
```

- [ ] **Step 4: Run all SubscriptionBanner tests**

Run: `npx vitest run src/lib/components/layout/SubscriptionBanner.test.ts`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/layout/SubscriptionBanner.svelte \
        frontend/src/lib/components/layout/SubscriptionBanner.test.ts
git commit -m "feat(F-0019d): add trial countdown variant + daily-key dismissal"
```

---

### Task 15: Logout cleanup + layout integration

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts` (clear `subscription-banner-dismissed-*` keys on logout)
- Modify: `frontend/src/routes/+layout.svelte` (render `<SubscriptionBanner />`)
- Modify: `frontend/src/lib/components/layout/SubscriptionBanner.test.ts` (add logout-clearing test for the auth function)

- [ ] **Step 1: Locate the logout function**

```bash
grep -n "export function logout\|export async function logout" frontend/src/lib/auth.svelte.ts
```

- [ ] **Step 2: Write failing test for logout cleanup**

Create `frontend/src/lib/auth.test.ts` (or extend if it exists). Mock `localStorage` and assert keys are cleared:

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('$lib/api', () => ({
    api: { post: vi.fn().mockResolvedValue({}) },
    ApiError: class {},
}));

import { logout } from './auth.svelte';

describe('logout — banner dismissal cleanup', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('clears all subscription-banner-dismissed-* keys', async () => {
        localStorage.setItem('subscription-banner-dismissed-trial-2026-05-24', 'true');
        localStorage.setItem('subscription-banner-dismissed-trial-2026-05-25', 'true');
        localStorage.setItem('some-other-key', 'keep');
        await logout();
        expect(localStorage.getItem('subscription-banner-dismissed-trial-2026-05-24')).toBeNull();
        expect(localStorage.getItem('subscription-banner-dismissed-trial-2026-05-25')).toBeNull();
        expect(localStorage.getItem('some-other-key')).toBe('keep');
    });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/auth.test.ts`
Expected: keys remain (not cleared yet).

- [ ] **Step 4: Add cleanup to `logout`**

In `frontend/src/lib/auth.svelte.ts`, inside the `logout` function (after the API call and before any redirect), add:

```ts
    try {
        const toRemove: string[] = [];
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (k && k.startsWith('subscription-banner-dismissed-')) toRemove.push(k);
        }
        for (const k of toRemove) localStorage.removeItem(k);
    } catch { /* ignore quota / private-mode errors */ }
```

- [ ] **Step 5: Render the banner in `+layout.svelte`**

In `frontend/src/routes/+layout.svelte`:

1. Add import next to `ConnectivityBanner`:

```ts
import SubscriptionBanner from '$lib/components/layout/SubscriptionBanner.svelte';
```

2. In the template (around line 224), update the banner block:

```svelte
{#if showNav}
    ...existing nav...
    {#if OFFLINE_ENABLED}
        <ConnectivityBanner />
    {/if}
    <SubscriptionBanner />
{/if}
```

`<SubscriptionBanner />` itself returns nothing when `state` is null or no condition is met, so wrapping in a guard is unnecessary — but the `{#if showNav}` outer block prevents it from rendering on `/auth/*` and field-mode routes (intentional — field mode has `ExpiryWarningBanner` as its lifecycle surface).

3. **Suppress `SubscriptionLockoutModal` while the locked-out banner is showing.** Currently `+layout.svelte` renders both `<SubscriptionLockoutModal />` (around line 254) and would now also render the banner's locked-out variant. A locked-out user would see two overlapping CTAs (banner + 402-triggered modal). Wrap the modal in a guard that suppresses it when the banner already conveys the lockout:

```svelte
<!-- around line 254, replace the bare <SubscriptionLockoutModal /> -->
{#if !subscription.state?.is_locked_out}
    <SubscriptionLockoutModal />
{/if}
```

Import `subscription` at the top of the script block alongside the other subscription imports if it isn't already imported. The banner is now the single ambient signal; the modal is suppressed only because the banner conveys the same information more prominently.

- [ ] **Step 6: Update `.env.example`**

Add the new secret to `backend/.env.example` next to the existing Loops block (search for `LOOPS_API_KEY` or similar):

```
# Shared HMAC secret for inbound Loops campaign webhooks (F-0019d).
# Set to the same value configured in Loops; leave blank to disable the
# /webhooks/loops/notification endpoint (returns 503 until set).
BATCHRITE_LOOPS_WEBHOOK_SECRET=
```

If the file has no Loops block at all, add the entry under a `# === Loops ===` section near the other third-party integration secrets.

- [ ] **Step 7: Run all frontend tests + typecheck**

```bash
cd frontend
npx vitest run src/lib/auth.test.ts src/lib/components/layout/SubscriptionBanner.test.ts
npm run check
```

Expected: all green; `svelte-check` clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts frontend/src/lib/auth.test.ts \
        frontend/src/routes/+layout.svelte backend/.env.example
git commit -m "feat(F-0019d): clear banner dismissals on logout + render SubscriptionBanner"
```

---

### Task 16: Documentation updates

**Files:**
- Modify: `docs/loops-campaigns.md`
- Modify: `CLAUDE.md` (env-var table)

- [ ] **Step 1: Append the Inbound section to `docs/loops-campaigns.md`**

Append at the end of the file:

```markdown
---

## Inbound: receiving notifications from Loops

Loops campaign workflows can POST to Batchrite to create in-app notification-bell entries for a user (e.g. "trial ends in 3 days" appears both in the user's inbox and in Loops-sent email).

### Endpoint

`POST {BATCHRITE_BASE_URL}/webhooks/loops/notification`

### Authentication

Loops signs the raw request body with HMAC-SHA256 using
`BATCHRITE_LOOPS_WEBHOOK_SECRET` and sends the lowercase hex digest in
the `X-Loops-Signature` header. Batchrite also accepts a
`sha256=<hex>` prefix and uppercase hex (provider casing drift).

Set `BATCHRITE_LOOPS_WEBHOOK_SECRET` to the shared secret you configure
in Loops. Until it is set, the endpoint responds `503`.

### Payload

```json
{
    "user_email": "wesu07@gmail.com",
    "title": "Trial ends in 3 days",
    "body": "Add a payment method to keep your team's protocols accessible.",
    "link_url": "/settings?tab=billing",
    "category": "trial-warning",
    "loops_message_id": "<stable per-message uuid>"
}
```

- `user_email` (required) — must match an existing Batchrite user.
- `title` (required, ≤ 200 chars).
- `body` (required, ≤ 2000 chars).
- `link_url` (optional, ≤ 300 chars) — must be an absolute path (`/foo`), same-origin only. External hosts and protocol-relative URLs are silently downgraded to `/notifications`.
- `category` (optional, ≤ 64 chars) — used by the bell UI for grouping/badging.
- `loops_message_id` (optional, ≤ 128 chars) — enables idempotency. Recommended: include a stable per-delivery UUID so retries don't duplicate the bell entry.

### Idempotency

If `loops_message_id` is supplied, Batchrite records a `(loops_message_id, user_id)` row and rejects duplicates with `200 {"received": true, "deduped": true}`. The composite key lets the same message id appear for multiple recipients across one campaign fan-out without colliding.

### Responses

| Status | Meaning |
| --- | --- |
| `200` | Notification created (or already existed and was deduped). |
| `400` | Missing / invalid `X-Loops-Signature`. |
| `404` | `user_email` does not match a known user. |
| `413` | Body exceeds 64 KB. |
| `422` | Payload schema validation failed. |
| `503` | `BATCHRITE_LOOPS_WEBHOOK_SECRET` is not set. |

### Curl example

```bash
BODY='{"user_email":"wesu07@gmail.com","title":"Trial ends in 3 days","body":"Add a payment method.","link_url":"/settings?tab=billing","category":"trial-warning","loops_message_id":"msg-abc-123"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$BATCHRITE_LOOPS_WEBHOOK_SECRET" -hex | awk '{print $2}')
curl -X POST "$BATCHRITE_BASE_URL/webhooks/loops/notification" \
    -H "X-Loops-Signature: $SIG" \
    -H "Content-Type: application/json" \
    --data "$BODY"
```

### Secret rotation

1. Generate a new secret in Loops.
2. `BATCHRITE_LOOPS_WEBHOOK_SECRET=<new>` and redeploy.
3. Revoke the old secret in the Loops UI.

A brief (≤ few seconds) window of `400 Invalid signature` is expected between steps 2 and 3 if a workflow fires during the redeploy.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, find the section that documents notification-related env vars (look for `BATCHRITE_NOTIFICATION_RETENTION_DAYS`). Append:

```markdown
`BATCHRITE_LOOPS_WEBHOOK_SECRET` (default `""`) is the shared HMAC secret Loops campaigns sign with when POSTing to `/webhooks/loops/notification`. Unset → endpoint returns `503` and Loops campaign workflows that drive in-app surfacing are no-ops; outbound Loops email still works. (F-0019d)
```

- [ ] **Step 3: Commit**

```bash
git add docs/loops-campaigns.md CLAUDE.md
git commit -m "docs(F-0019d): document inbound Loops webhook + new env var"
```

---

## Final verification

Before declaring the implementation done:

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend && source .venv/bin/activate && pytest -q
```

Expected: green. Pay attention to `tests/unit/services/test_notifications.py` and `test_notification_policy.py` (the coupling sites) — they must pass without flakes.

- [ ] **Step 2: Run the full frontend test suite + typecheck**

```bash
cd frontend
npx vitest run
npm run check
```

Expected: green.

- [ ] **Step 3: Manual smoke (in the worktree dev environment)**

1. Set `BATCHRITE_LOOPS_WEBHOOK_SECRET=local-test` in `<worktree>/backend/.env`, restart uvicorn.
2. Use the curl example from `docs/loops-campaigns.md` (substitute the worktree's port). Confirm `200`, then re-fire — confirm `{"deduped": true}`.
3. Log in at the frontend URL. Set the seed user's `subscription_status` to trial via psql:
   ```sql
   UPDATE organizations
   SET subscription_status='trialing',
       trial_end = now() + interval '5 days'
   WHERE id = (SELECT organization_id FROM organization_members
               WHERE user_id = (SELECT id FROM users WHERE email='admin@bioprocess.com')
               LIMIT 1);
   ```
   Refresh — amber banner should appear with "Trial ends in 5 days" copy.
4. Dismiss it — refresh — banner stays dismissed today.
5. Update `trial_end = now() + interval '1 day'` → reload subscription store (re-focus the tab) → red "Trial ends tomorrow" banner appears regardless of yesterday's dismiss.
6. Set `subscription_status = 'canceled'` and `is_locked_out` via the lockout flow → locked-out banner appears, overrides trial.
7. Bell: open the notification dropdown — the lifecycle entry from step 2 should render with the credit-card icon and amber chip.

---

## Out of scope reminders

These are not in this plan and should not be added without explicit re-scoping. The TD-tagged ones should become ClickUp tasks at ship time:

- **TD — app-wide per-IP rate limit** on `/webhooks/loops/notification` (and `/billing/webhook`). A runaway Loops workflow could fire thousands of correctly-signed requests/minute; HMAC only stops unauthenticated abuse, not authenticated hammering.
- **TD — ASGI body-size middleware** (or nginx `client_max_body_size`). Current 64KB cap is per-route and enforced after `await request.body()`. A proxy-level cap protects worker memory before the body lands.
- **TD — sticky positioning for lock/cancel banners.** Currently banners scroll out of view with the page. For non-dismissible variants (lock, cancel), losing the ambient signal undermines the warning. `sticky top-[nav-height] z-40` for lock/cancel tiers; trial tiers stay scrollable. Out of scope here because it requires measuring nav height and threading a CSS variable, but a quick follow-up.
- **OPS — Datadog/CloudWatch log alarms.** A drop in `Loops webhook processed` log count for >2h during business hours = Loops outage. Document the alarm definition in `docs/loops-campaigns.md` runbook once monitoring tooling is decided.
- Outbound channels for `LIFECYCLE` notifications (Slack/Teams/Discord) — `DEFAULT_POLICY` keeps them off intentionally.
- Generalizing the three top-of-page banners into a `<Banner variant=...>` primitive.
- Lifecycle notification grouping/digest in the bell.

---

## Spec coverage map (self-review)

| Spec section | Task(s) |
| --- | --- |
| HMAC verification helper | Task 1 |
| Settings (`loops_webhook_secret`) | Task 2 |
| AuthMiddleware exemption (exact-match) | Task 2 |
| `LoopsEvent` model + composite unique | Task 3 |
| Alembic migration + `db/base.py` import | Task 3 |
| `LIFECYCLE` enum value | Task 4 |
| `TEMPLATES["LIFECYCLE"]` stub | Task 5 |
| `DEFAULT_POLICY[LIFECYCLE]` stub | Task 5 |
| `insert_external_notification` helper | Task 6 |
| Webhook endpoint w/ raw-body-first ordering | Task 7 |
| 64 KB body cap | Task 7 |
| 503 / 400 / 404 / 413 / 422 / 200 responses | Task 7 |
| Idempotency via `ON CONFLICT DO NOTHING RETURNING` | Task 7 |
| Atomic single-transaction commit | Task 7 |
| Email-masking in user-not-found log | Task 7 |
| Concurrent-duplicate race coverage | Task 8 |
| Lifecycle deep-link with same-origin allowlist | Task 9 |
| Resolver runs before `_ROUTABLE` short-circuit | Task 9 |
| `EVENT_ICONS["LIFECYCLE"] = CreditCard` | Task 10 |
| `EVENT_TONES["LIFECYCLE"] = amber` | Task 10 |
| `visibilitychange` subscription reload (throttled) | Task 11 |
| `SubscriptionBanner` locked-out variant | Task 12 |
| `SubscriptionBanner` cancel-at-period-end variant | Task 13 |
| Trial countdown — five copy thresholds | Task 14 |
| Trial tier surface: blue (≥8) / amber (3–7) / red (≤2) | Task 14 |
| Daily-key localStorage dismissal | Task 14 |
| Logout-clears-dismissals | Task 15 |
| `+layout.svelte` integration | Task 15 |
| `docs/loops-campaigns.md` inbound section + rotation | Task 16 |
| `CLAUDE.md` env-var entry | Task 16 |
