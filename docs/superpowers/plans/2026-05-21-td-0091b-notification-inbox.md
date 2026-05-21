# TD-0091b — Notification inbox: UX, observability & test coverage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five notification-inbox quality gaps from the 2026-05-21 QA audit — stale polling, swallowed errors, no history page / retention, no deep-linking, no test coverage.

**Architecture:** Frontend-only changes for smarter polling, error toasts, deep-linking, and a new `/notifications` history route; backend changes for an `include_total` query flag, a chunked retention sweep wired into the existing recovery loop, and a new partial index. Notification API types move to Zod schemas; a shared `NotificationRow` component serves both the bell dropdown and the history page.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async / Alembic / pytest (backend); SvelteKit + Svelte 5 runes / TailwindCSS 4 / shadcn-svelte / Zod / Vitest + @testing-library/svelte (frontend).

**Base branch:** `main`. The prerequisite task TD-0091a (recovery-loop delivery-retry wiring) is merged to `main` but **not** to `td-0083-split-science-module`. All work branches from `main`.

**Spec:** `docs/superpowers/specs/2026-05-21-td-0091b-notification-inbox-ux-design.md` is authoritative — read it before starting.

---

## File Structure

**Backend**
- `backend/app/core/config.py` — modify: add `notification_retention_days` setting.
- `backend/app/models/notifications.py` — modify: add `ix_notif_read_at` partial index to `Notification.__table_args__`.
- `backend/alembic/versions/<rev>_add_ix_notif_read_at_*.py` — create: `CREATE INDEX CONCURRENTLY ix_notif_read_at`.
- `backend/app/services/core/notifications/retention.py` — create: `purge_read_notifications`.
- `backend/app/api/endpoints/notifications.py` — modify: add `include_total` to `list_notifications`.
- `backend/app/main.py` — modify: add `_purge_old_notifications()` step to `_recovery_loop`.
- `backend/tests/unit/test_notifications.py` — modify: add purge / dispatch / sweep-wiring tests.
- `backend/tests/integration/test_notification_api.py` — modify: cover `include_total`.

**Frontend**
- `frontend/src/lib/schemas/notifications.ts` — create: Zod schemas + inferred types.
- `frontend/src/lib/schemas/index.ts` — modify: barrel-export the new schema file.
- `frontend/src/lib/notifications.ts` — create: `eventIcon`, `notificationHref`, page-size constants.
- `frontend/src/lib/components/notifications/NotificationRow.svelte` — create: shared row, compact + full variants.
- `frontend/src/lib/components/layout/NotificationBell.svelte` — rewrite: smarter polling, concurrency guard, error handling, deep-link, "View all" link.
- `frontend/src/routes/notifications/+page.ts` — create: reads `offset` from the URL.
- `frontend/src/routes/notifications/+page.svelte` — create: paginated history page.
- Test files (create): `frontend/src/lib/schemas/notifications.test.ts`, `frontend/src/lib/notifications.test.ts`, `frontend/src/lib/components/notifications/NotificationRow.test.ts`, `frontend/src/lib/components/layout/NotificationBell.test.ts`, `frontend/src/routes/notifications/page.test.ts`.

**Docs / rules**
- `.claude/rules/conventions.md` — modify: add the `notifications/` component bucket.
- `CLAUDE.md` — modify: document `BATCHRITE_NOTIFICATION_RETENTION_DAYS`.

---

## Task 1: Add the `notification_retention_days` setting

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add the setting to the `Settings` class**

In `backend/app/core/config.py`, find the line `recovery_interval_seconds: int = 90` inside `class Settings(BaseSettings)`. Immediately after it (after the trailing blank line of that block, before the `# Docling extractor` comment), add:

```python
    # TD-0091b: read in-app notifications older than this many days are
    # hard-deleted by the recovery-loop retention sweep. Unread
    # notifications are kept regardless of age. Set to 0 (or negative) to
    # disable the sweep entirely. Env: BATCHRITE_NOTIFICATION_RETENTION_DAYS.
    notification_retention_days: int = 90
```

- [ ] **Step 2: Verify the setting loads**

Run: `cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; print(settings.notification_retention_days)"`
Expected: prints `90`.

- [ ] **Step 3: Verify the env override works**

Run: `cd backend && source .venv/bin/activate && BATCHRITE_NOTIFICATION_RETENTION_DAYS=30 python -c "from app.core.config import settings; print(settings.notification_retention_days)"`
Expected: prints `30`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat(TD-0091b): add notification_retention_days setting"
```

---

## Task 2: Add the `ix_notif_read_at` partial index

The retention sweep filters `notifications` on `read_at` alone. The existing `(user_id, read_at)` index cannot serve a `read_at`-only predicate, so add a partial index `WHERE read_at IS NOT NULL`. It is declared on the model (so the ORM-metadata-built test DB has it) **and** created by an Alembic migration using `CREATE INDEX CONCURRENTLY` (a plain `op.create_index` would fail `CONCURRENTLY` inside Alembic's per-migration transaction on a populated table).

**Files:**
- Modify: `backend/app/models/notifications.py`
- Create: `backend/alembic/versions/<rev>_add_ix_notif_read_at_partial_index.py`

- [ ] **Step 1: Add the index to the model**

In `backend/app/models/notifications.py`, the top-level `sqlalchemy` import is:

```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
```

Add `text` to it (alphabetical order keeps `Text` and `text` adjacent — put `text` after `Text`):

```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
```

Then in the `Notification` class, replace the existing `__table_args__`:

```python
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_user_created", "user_id", "created_at"),
        Index("ix_notif_user_unread", "user_id", "read_at"),
    )
```

with:

```python
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_user_created", "user_id", "created_at"),
        Index("ix_notif_user_unread", "user_id", "read_at"),
        # TD-0091b: serves the read_at-only predicate of the retention sweep.
        Index(
            "ix_notif_read_at",
            "read_at",
            postgresql_where=text("read_at IS NOT NULL"),
        ),
    )
```

- [ ] **Step 2: Generate the migration scaffold**

Run: `cd backend && source .venv/bin/activate && alembic revision -m "add ix_notif_read_at partial index"`
Expected: prints `Generating .../alembic/versions/<rev>_add_ix_notif_read_at_partial_index.py ... done`. This auto-fills `revision` and `down_revision` (the current head) — do not edit those.

If Alembic reports multiple heads, stop and resolve the pre-existing head split first (`alembic heads`); do not invent a `down_revision`.

- [ ] **Step 3: Fill in the migration body**

Open the generated file. Replace the empty `def upgrade()` and `def downgrade()` with:

```python
def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block;
    # autocommit_block suspends Alembic's per-migration transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notif_read_at "
            "ON notifications (read_at) WHERE read_at IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notif_read_at")
```

Leave the generated `revision`, `down_revision`, `branch_labels`, `depends_on`, and the `from alembic import op` import untouched.

> **Operator note — recovering from a cancelled index build.** `CREATE INDEX CONCURRENTLY` is not transactional: an interrupted build (migration pod OOM-killed, `statement_timeout`, `pg_cancel_backend`) leaves an **INVALID** index behind. `IF NOT EXISTS` then matches that invalid index by name on the next `alembic upgrade head`, so the migration "succeeds" while the sweep silently runs against an index the planner ignores. Before re-running a failed migration, check validity and drop a bad index manually:
> ```sql
> SELECT i.indisvalid FROM pg_index i
>   JOIN pg_class c ON c.oid = i.indexrelid
>   WHERE c.relname = 'ix_notif_read_at';
> -- if indisvalid is false:
> DROP INDEX CONCURRENTLY IF EXISTS ix_notif_read_at;
> ```
> Then re-run `alembic upgrade head`.

- [ ] **Step 4: Apply the migration**

Run: `cd backend && source .venv/bin/activate && alembic upgrade head`
Expected: completes without error, ending at the new revision.

- [ ] **Step 5: Verify the index exists**

Run: `psql "$BATCHRITE_DATABASE_URL" -c "\d notifications" 2>/dev/null || psql -U postgres -h localhost -d batchrite_wt<N> -c "\d notifications"`
Expected: the index list includes `ix_notif_read_at` with `WHERE (read_at IS NOT NULL)`.

- [ ] **Step 6: Verify existing notification tests still pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py tests/integration/test_notification_api.py -q`
Expected: all pass (the test DB schema, rebuilt from ORM metadata, now includes the index).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/notifications.py backend/alembic/versions/
git commit -m "feat(TD-0091b): add ix_notif_read_at partial index"
```

---

## Task 3: Retention sweep — `purge_read_notifications`

**Files:**
- Create: `backend/app/services/core/notifications/retention.py`
- Test: `backend/tests/unit/test_notifications.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/unit/test_notifications.py`, the current top-of-file imports include:

```python
from datetime import datetime, timedelta, timezone

from app.models.notifications import (
    DeliveryStatus,
    NotificationChannel,
    NotificationDelivery,
)
```

Add `uuid4` and `Notification` (and `NotificationSubscription`, used by Task 6) so the import block reads:

```python
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.notifications import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
)
```

Then append this test class to the end of the file:

```python
# ── purge_read_notifications Tests (TD-0091b) ────────────────────────────


class TestPurgeReadNotifications:
    """The retention sweep hard-deletes old read notifications only."""

    async def _notif(self, db, user, *, read_at, title="n"):
        notif = Notification(
            user_id=user.id,
            event_type="RUN_STARTED",
            entity_type="run",
            entity_id=uuid4(),
            title=title,
            message="m",
            read_at=read_at,
        )
        db.add(notif)
        await db.flush()
        return notif

    @pytest.mark.asyncio
    async def test_deletes_old_read_notifications(self, db_session, test_user):
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        old = datetime.now(timezone.utc) - timedelta(days=100)
        notif = await self._notif(db_session, test_user, read_at=old)

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == 1
        assert await db_session.get(Notification, notif.id) is None

    @pytest.mark.asyncio
    async def test_keeps_recent_read_notifications(self, db_session, test_user):
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        recent = datetime.now(timezone.utc) - timedelta(days=10)
        notif = await self._notif(db_session, test_user, read_at=recent)

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == 0
        assert await db_session.get(Notification, notif.id) is not None

    @pytest.mark.asyncio
    async def test_keeps_unread_notifications(self, db_session, test_user):
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        notif = await self._notif(db_session, test_user, read_at=None)

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == 0
        assert await db_session.get(Notification, notif.id) is not None

    @pytest.mark.asyncio
    async def test_returns_exact_count(self, db_session, test_user):
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        old = datetime.now(timezone.utc) - timedelta(days=100)
        recent = datetime.now(timezone.utc) - timedelta(days=5)
        await self._notif(db_session, test_user, read_at=old, title="a")
        await self._notif(db_session, test_user, read_at=old, title="b")
        await self._notif(db_session, test_user, read_at=recent, title="c")
        await self._notif(db_session, test_user, read_at=None, title="d")

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_chunking_across_more_than_chunk_size(
        self, db_session, test_user
    ):
        """Exercises the multi-chunk control flow (the while loop runs
        twice: 500 then 5). The per-chunk ``db.commit()`` resolves to a
        SAVEPOINT release under the test fixture, so this asserts the
        chunk arithmetic, not real per-chunk commit durability.
        """
        from app.services.core.notifications.retention import (
            PURGE_CHUNK_SIZE,
            purge_read_notifications,
        )

        old = datetime.now(timezone.utc) - timedelta(days=100)
        rows = [
            Notification(
                user_id=test_user.id,
                event_type="RUN_STARTED",
                entity_type="run",
                entity_id=uuid4(),
                title=f"n{i}",
                message="m",
                read_at=old,
            )
            for i in range(PURGE_CHUNK_SIZE + 5)
        ]
        db_session.add_all(rows)
        await db_session.flush()

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == PURGE_CHUNK_SIZE + 5

    @pytest.mark.asyncio
    async def test_non_positive_window_is_noop(self, db_session, test_user):
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        old = datetime.now(timezone.utc) - timedelta(days=100)
        notif = await self._notif(db_session, test_user, read_at=old)

        assert await purge_read_notifications(db_session, older_than_days=0) == 0
        assert (
            await purge_read_notifications(db_session, older_than_days=-1) == 0
        )
        assert await db_session.get(Notification, notif.id) is not None

    @pytest.mark.asyncio
    async def test_delivery_survives_purge_with_null_fk(
        self, db_session, test_user
    ):
        """Schema-contract test for the ON DELETE SET NULL FK.

        The production dispatcher (``_dispatch_to_channel``) never sets
        ``NotificationDelivery.notification_id`` — in-app ``Notification``
        rows and external-channel ``NotificationDelivery`` rows are
        decoupled today, so a purge cannot orphan a real delivery. This
        test constructs the linkage artificially to prove the FK's
        ``ON DELETE SET NULL`` holds *if* the two are ever linked, so a
        future change can rely on the contract.
        """
        from app.services.core.notifications.retention import (
            purge_read_notifications,
        )

        old = datetime.now(timezone.utc) - timedelta(days=100)
        notif = await self._notif(db_session, test_user, read_at=old)
        channel = NotificationChannel(
            user_id=test_user.id,
            name="C",
            channel_type="CONSOLE",
            config={},
            enabled=True,
        )
        db_session.add(channel)
        await db_session.flush()
        delivery = NotificationDelivery(
            notification_id=notif.id,
            channel_id=channel.id,
            event_type="RUN_STARTED",
            recipient_info={"recipient": "x"},
            status=DeliveryStatus.RETRYING,
            attempts=1,
        )
        db_session.add(delivery)
        await db_session.flush()

        deleted = await purge_read_notifications(
            db_session, older_than_days=90
        )

        assert deleted == 1
        await db_session.refresh(delivery)
        assert delivery.notification_id is None
        assert delivery.status == DeliveryStatus.RETRYING
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestPurgeReadNotifications -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.core.notifications.retention'`.

- [ ] **Step 3: Write the retention module**

Create `backend/app/services/core/notifications/retention.py`:

```python
"""Retention sweep for in-app notifications.

Read notifications older than the retention window are hard-deleted to
bound the ``notifications`` table's growth. Unread notifications are kept
regardless of age.

This sweep touches only the ``notifications`` (inbox) table. External
``notification_deliveries`` rows are a separate audit trail — the
dispatcher records them with ``notification_id`` left NULL, so they are
not children of inbox rows and a purge cannot affect them. (The FK is
``ON DELETE SET NULL`` purely as a defensive contract should the two
ever be linked; see ``test_delivery_survives_purge_with_null_fk``.)
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification

logger = logging.getLogger("notifications.retention")

# Rows deleted per statement. Bounds lock duration and WAL volume on the
# first sweep against a large unpurged table.
PURGE_CHUNK_SIZE = 500


async def purge_read_notifications(
    db: AsyncSession, *, older_than_days: int
) -> int:
    """Hard-delete read notifications older than ``older_than_days``.

    Deletes in ``PURGE_CHUNK_SIZE`` chunks, committing after each chunk,
    until a chunk deletes fewer than a full batch. Unread rows are never
    deleted. ``older_than_days <= 0`` is a no-op returning 0.

    Args:
        db: Database session.
        older_than_days: Age threshold; read notifications whose
            ``read_at`` is older than this many days are eligible.

    Returns:
        Total number of rows deleted.
    """
    if older_than_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    eligible = (
        select(Notification.id)
        .where(Notification.read_at.is_not(None))
        .where(Notification.read_at < cutoff)
        # Deterministic chunk membership: ix_notif_read_at is already
        # ordered on read_at, so the ORDER BY is free and makes the
        # `deleted < PURGE_CHUNK_SIZE` termination reliable.
        .order_by(Notification.read_at)
        .limit(PURGE_CHUNK_SIZE)
    )
    stmt = delete(Notification).where(Notification.id.in_(eligible))

    total = 0
    try:
        while True:
            result = await db.execute(stmt)
            deleted = result.rowcount or 0
            await db.commit()
            total += deleted
            if deleted < PURGE_CHUNK_SIZE:
                break
    except Exception:
        # Chunks already committed are irreversible — surface how far the
        # sweep got before the failure rather than losing the count.
        logger.exception(
            "Retention sweep interrupted after deleting %d read "
            "notifications",
            total,
        )
        raise

    logger.debug(
        "Retention sweep deleted %d read notifications older than %d days",
        total,
        older_than_days,
    )
    return total
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestPurgeReadNotifications -q`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/retention.py backend/tests/unit/test_notifications.py
git commit -m "feat(TD-0091b): add purge_read_notifications retention sweep"
```

---

## Task 4: `list_notifications` — add `include_total`

The endpoint always runs a `COUNT(*)` subquery. The bell does not use `total` (its badge comes from `unread-count`); only the history page needs it. Add `include_total: bool = Query(False)` and skip the count when false, returning `total=0`.

**Files:**
- Modify: `backend/app/api/endpoints/notifications.py`
- Test: `backend/tests/integration/test_notification_api.py`

- [ ] **Step 1: Write / update the failing tests**

In `backend/tests/integration/test_notification_api.py`, inside `class TestInAppNotifications`, the `test_create_and_read_notification` test currently lists with `GET /notifications/` and asserts `data["total"] == 1`. Change **only that list call** so `total` is requested — find:

```python
        # List
        resp = await client.get("/notifications/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
```

and replace with:

```python
        # List (include_total so the count is populated)
        resp = await client.get(
            "/notifications/?include_total=true", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
```

Also update `test_list_empty` in the same class. With `include_total` defaulting to `False`, `total=0` becomes the "count skipped" sentinel — so this test must request the count for its `total == 0` assertion to genuinely mean "no rows", not pass by accident. Find:

```python
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get("/notifications/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
```

and replace with:

```python
    async def test_list_empty(self, client, auth_headers):
        resp = await client.get(
            "/notifications/?include_total=true", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
```

Then add two new tests at the end of `class TestInAppNotifications` (after `test_cannot_read_other_users_notification`):

```python
    @pytest.mark.asyncio
    async def test_list_total_omitted_by_default(
        self, client, auth_headers, test_user, db_session
    ):
        """Without include_total the count is skipped — total is 0 even
        though items are returned."""
        for i in range(2):
            db_session.add(
                Notification(
                    user_id=test_user.id,
                    event_type="RUN_STARTED",
                    entity_type="run",
                    entity_id=uuid4(),
                    title=f"Notif {i}",
                    message=f"Message {i}",
                )
            )
        await db_session.flush()

        resp = await client.get("/notifications/", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_total_included_when_requested(
        self, client, auth_headers, test_user, db_session
    ):
        """include_total=true runs the COUNT and returns the real total."""
        for i in range(3):
            db_session.add(
                Notification(
                    user_id=test_user.id,
                    event_type="RUN_STARTED",
                    entity_type="run",
                    entity_id=uuid4(),
                    title=f"Notif {i}",
                    message=f"Message {i}",
                )
            )
        await db_session.flush()

        resp = await client.get(
            "/notifications/?include_total=true&limit=2", headers=auth_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2  # limited
        assert data["total"] == 3  # full count
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_notification_api.py::TestInAppNotifications -q`
Expected: FAIL — `test_list_total_omitted_by_default` fails (`total` is currently `2`, not `0`).

- [ ] **Step 3: Add `include_total` to the endpoint**

In `backend/app/api/endpoints/notifications.py`, replace the `list_notifications` function:

```python
@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's in-app notifications."""
    base = select(Notification).where(Notification.user_id == current_user.id)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return NotificationListResponse(items=items, total=total)
```

with:

```python
@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_total: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's in-app notifications.

    ``include_total`` runs a COUNT(*) for pagination UIs (the history
    page). The bell omits it — its badge comes from ``unread-count`` — and
    receives ``total=0``.
    """
    base = select(Notification).where(Notification.user_id == current_user.id)

    total = 0
    if include_total:
        # Direct COUNT on the table (not a subquery wrap of `base`) so
        # PostgreSQL can serve it from ix_notif_user_created without
        # materializing the base select.
        count_stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == current_user.id)
        )
        total = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return NotificationListResponse(items=items, total=total)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_notification_api.py::TestInAppNotifications -q`
Expected: PASS — all tests in the class green, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/notifications.py backend/tests/integration/test_notification_api.py
git commit -m "feat(TD-0091b): add include_total flag to list_notifications"
```

---

## Task 5: Recovery-loop wiring — `_purge_old_notifications`

A new sweep step in `_recovery_loop`, placed after `_retry_pending_deliveries()`, throttled to at most once per 24 h via a module-level last-run timestamp. It logs an `INFO` line on every run (count + window) and a one-time `INFO` when retention is disabled.

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_notifications.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_notifications.py`:

```python
# ── _purge_old_notifications sweep wiring (TD-0091b) ─────────────────────


class TestPurgeOldNotificationsSweep:
    """The recovery-loop purge step is throttled and respects the flag."""

    @pytest.mark.asyncio
    async def test_sweep_calls_purge_when_due(self, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(main_module, "_last_notification_purge_at", None)
        monkeypatch.setattr(
            main_module.settings, "notification_retention_days", 90
        )

        fake_session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = fake_session
        session_cm.__aexit__.return_value = False
        session_factory = MagicMock(return_value=session_cm)
        purge_mock = AsyncMock(return_value=7)

        with patch(
            "app.db.session.AsyncSessionLocal", session_factory
        ), patch(
            "app.services.core.notifications.retention.purge_read_notifications",
            purge_mock,
        ):
            await main_module._purge_old_notifications()

        session_factory.assert_called_once()
        purge_mock.assert_awaited_once_with(fake_session, older_than_days=90)

    @pytest.mark.asyncio
    async def test_sweep_throttled_within_24h(self, monkeypatch):
        import app.main as main_module

        monkeypatch.setattr(
            main_module,
            "_last_notification_purge_at",
            datetime.now(timezone.utc),
        )
        monkeypatch.setattr(
            main_module.settings, "notification_retention_days", 90
        )
        purge_mock = AsyncMock(return_value=0)

        with patch(
            "app.services.core.notifications.retention.purge_read_notifications",
            purge_mock,
        ):
            await main_module._purge_old_notifications()

        purge_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_disabled_when_retention_non_positive(
        self, monkeypatch
    ):
        import app.main as main_module

        monkeypatch.setattr(main_module, "_last_notification_purge_at", None)
        monkeypatch.setattr(
            main_module.settings, "notification_retention_days", 0
        )
        purge_mock = AsyncMock(return_value=0)

        with patch(
            "app.services.core.notifications.retention.purge_read_notifications",
            purge_mock,
        ):
            await main_module._purge_old_notifications()

        purge_mock.assert_not_awaited()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestPurgeOldNotificationsSweep -q`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute '_last_notification_purge_at'`.

- [ ] **Step 3: Add the sweep to `main.py`**

In `backend/app/main.py`, find the `_retry_pending_deliveries` function. Immediately **after** it (before `async def _recovery_loop`), insert:

```python
# TD-0091b: last time the notification retention sweep ran, per process.
# Throttles the sweep to at most once per 24h *within a single worker* —
# the recovery loop ticks far more often than a 90-day-window purge needs.
# NOTE: this is process-local — a multi-worker / multi-pod deployment runs
# one sweep per worker per 24h, and every restart resets it to None. The
# sweep is idempotent, so that is safe (just not globally minimal); a
# distributed throttle lock is tracked as a follow-up. A non-None sentinel
# value also marks "disabled message already logged".
_last_notification_purge_at: datetime | None = None


async def _purge_old_notifications() -> None:
    """Hard-delete read notifications past the retention window.

    Runs as a sweep inside the recovery loop, throttled to at most once
    per 24h. Loop-only (no startup sweep), uses a fresh session like the
    delivery-retry sweep. When retention is disabled it logs once and
    skips on every later tick.
    """
    global _last_notification_purge_at
    from app.db.session import AsyncSessionLocal
    from app.services.core.notifications.retention import (
        purge_read_notifications,
    )

    retention_days = settings.notification_retention_days
    if retention_days <= 0:
        if _last_notification_purge_at is None:
            logger.info(
                "Notification retention sweep disabled "
                "(notification_retention_days <= 0)"
            )
            # Sentinel: suppress the disabled log on every later tick.
            _last_notification_purge_at = datetime.now(timezone.utc)
        return

    now = datetime.now(timezone.utc)
    if _last_notification_purge_at is not None and (
        now - _last_notification_purge_at
    ) < timedelta(hours=24):
        return

    async with AsyncSessionLocal() as session:
        deleted = await purge_read_notifications(
            session, older_than_days=retention_days
        )
    _last_notification_purge_at = now
    logger.info(
        "Retention sweep: deleted %d read notifications older than %d days",
        deleted,
        retention_days,
    )
```

`datetime`, `timedelta`, and `timezone` are already imported at the top of `main.py` — do not re-import.

- [ ] **Step 4: Wire the sweep into `_recovery_loop`**

In `_recovery_loop`, find the `while True:` block. After the `_retry_pending_deliveries()` try/except and before `await asyncio.sleep(interval)`:

```python
        try:
            await _retry_pending_deliveries()
        except Exception:
            logger.exception("Recovery loop: delivery retry sweep failed")
        await asyncio.sleep(interval)
```

insert the purge step so it reads:

```python
        try:
            await _retry_pending_deliveries()
        except Exception:
            logger.exception("Recovery loop: delivery retry sweep failed")
        try:
            await _purge_old_notifications()
        except Exception:
            logger.exception("Recovery loop: notification purge sweep failed")
        await asyncio.sleep(interval)
```

Then update the recovery-loop "disabled" path so it names all three sweeps. Find the disabled `logger.warning` near the top of `_recovery_loop`:

```python
        logger.warning(
            "Recovery loop disabled (interval <= 0) — notification "
            "delivery retries are also OFF"
        )
```

and replace with:

```python
        logger.warning(
            "Recovery loop disabled (interval <= 0) — notification "
            "delivery retries and the retention purge sweep are also OFF"
        )
```

In the `_recovery_loop` docstring, the line `Set BATCHRITE_RECOVERY_INTERVAL_SECONDS=0 to disable — this also disables notification delivery retries.` should read `... this also disables notification delivery retries and the retention purge sweep.`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestPurgeOldNotificationsSweep -q`
Expected: PASS — all 3 tests green.

- [ ] **Step 6: Run the full notification test suite**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py tests/integration/test_notification_api.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_notifications.py
git commit -m "feat(TD-0091b): wire throttled notification retention sweep into recovery loop"
```

---

## Task 6: `dispatch_event` test coverage

The dispatcher's `retry_pending` path is already covered by `TestRetryPending` (TD-0091a). This task adds the missing `dispatch_event` coverage and records the known `MAX_RETRIES` off-by-one in a code comment (the fix itself is a separate follow-up task, not in scope here).

**Files:**
- Modify: `backend/app/services/core/notifications/dispatcher.py`
- Test: `backend/tests/unit/test_notifications.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_notifications.py`:

```python
# ── dispatch_event Tests (TD-0091b) ──────────────────────────────────────


class TestDispatchEvent:
    """dispatch_event fans an event out to subscribed org + user channels."""

    async def _channel_with_sub(
        self,
        db,
        *,
        event_type,
        org_id=None,
        user_id=None,
        sub_enabled=True,
    ):
        channel = NotificationChannel(
            org_id=org_id,
            user_id=user_id,
            name="Dispatch Test Channel",
            channel_type="CONSOLE",
            config={},
            enabled=True,
        )
        db.add(channel)
        await db.flush()
        sub = NotificationSubscription(
            channel_id=channel.id,
            event_type=event_type,
            enabled=sub_enabled,
        )
        db.add(sub)
        await db.flush()
        return channel

    def _messages(self, event_type="RUN_STARTED"):
        personal = FormattedMessage(
            event_type=event_type,
            title="Personal",
            body="personal body",
            recipient="you@example.com",
        )
        broadcast = FormattedMessage(
            event_type=event_type,
            title="Broadcast",
            body="broadcast body",
            recipient="org",
        )
        return personal, broadcast

    @pytest.mark.asyncio
    async def test_org_channel_receives_broadcast(self, db_session, test_org):
        await self._channel_with_sub(
            db_session, event_type="RUN_STARTED", org_id=test_org.id
        )
        personal, broadcast = self._messages()

        deliveries = await dispatcher.dispatch_event(
            db_session, "RUN_STARTED", test_org.id, [], personal, broadcast
        )

        assert len(deliveries) == 1
        assert deliveries[0].status == DeliveryStatus.SENT

    @pytest.mark.asyncio
    async def test_user_channel_receives_personal(
        self, db_session, test_org, test_user
    ):
        await self._channel_with_sub(
            db_session, event_type="RUN_COMPLETED", user_id=test_user.id
        )
        personal, broadcast = self._messages("RUN_COMPLETED")

        deliveries = await dispatcher.dispatch_event(
            db_session,
            "RUN_COMPLETED",
            test_org.id,
            [test_user.id],
            personal,
            broadcast,
        )

        assert len(deliveries) == 1
        assert deliveries[0].status == DeliveryStatus.SENT

    @pytest.mark.asyncio
    async def test_disabled_subscription_yields_no_delivery(
        self, db_session, test_org
    ):
        await self._channel_with_sub(
            db_session,
            event_type="RUN_STARTED",
            org_id=test_org.id,
            sub_enabled=False,
        )
        personal, broadcast = self._messages()

        deliveries = await dispatcher.dispatch_event(
            db_session, "RUN_STARTED", test_org.id, [], personal, broadcast
        )

        assert deliveries == []

    @pytest.mark.asyncio
    async def test_event_with_no_channels_is_noop(
        self, db_session, test_org
    ):
        personal, broadcast = self._messages("STEP_DEVIATION")

        deliveries = await dispatcher.dispatch_event(
            db_session,
            "STEP_DEVIATION",
            test_org.id,
            [],
            personal,
            broadcast,
        )

        assert deliveries == []
```

- [ ] **Step 2: Run the tests to verify they fail or pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py::TestDispatchEvent -q`
Expected: PASS — `dispatch_event` already exists, so these tests should pass immediately. They are regression coverage for previously-untested behavior. If any fail, the test setup is wrong — fix the test, not the dispatcher.

- [ ] **Step 3: Document the `MAX_RETRIES` off-by-one in the dispatcher**

In `backend/app/services/core/notifications/dispatcher.py`, find:

```python
MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 600]  # seconds
```

Replace with:

```python
MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 600]  # seconds
# NOTE (TD-0091b): _execute_send increments `attempts` before the
# `attempts < MAX_RETRIES` check, so a delivery is sent at most 3 times
# and only 2 retries occur — RETRY_BACKOFF[2] (600s) is never used. This
# off-by-one is pre-existing and tracked in a separate TECH_DEBT task; it
# is intentionally NOT changed here (TD-0091b is test-coverage only).
```

- [ ] **Step 4: Verify the full notification suite still passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/notifications/dispatcher.py backend/tests/unit/test_notifications.py
git commit -m "test(TD-0091b): cover dispatch_event; note MAX_RETRIES off-by-one"
```

> **Follow-up for implement-task:** route the `MAX_RETRIES`/`RETRY_BACKOFF` off-by-one fix, and an ops runbook entry for "user reports missing notification history", to `/add_task` as separate TECH_DEBT items.

---

## Task 7: Frontend Zod schemas — `schemas/notifications.ts`

**Files:**
- Create: `frontend/src/lib/schemas/notifications.ts`
- Modify: `frontend/src/lib/schemas/index.ts`
- Test: `frontend/src/lib/schemas/notifications.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/schemas/notifications.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import {
    NotificationSchema,
    NotificationListResponseSchema,
    UnreadCountResponseSchema,
} from './notifications';

const VALID = {
    id: '11111111-1111-1111-1111-111111111111',
    user_id: '22222222-2222-2222-2222-222222222222',
    event_type: 'RUN_STARTED',
    entity_type: 'run',
    entity_id: '33333333-3333-3333-3333-333333333333',
    title: 'Run started',
    message: 'CHO-042 started',
    read_at: null,
    created_at: '2026-05-21T10:00:00Z',
};

describe('notification schemas', () => {
    it('parses a valid notification', () => {
        expect(NotificationSchema.parse(VALID).title).toBe('Run started');
    });

    it('keeps unknown fields (passthrough, forward compat)', () => {
        const parsed = NotificationSchema.parse({ ...VALID, future: 1 });
        expect((parsed as Record<string, unknown>).future).toBe(1);
    });

    it('parses a list response', () => {
        const parsed = NotificationListResponseSchema.parse({
            items: [VALID],
            total: 1,
        });
        expect(parsed.items).toHaveLength(1);
        expect(parsed.total).toBe(1);
    });

    it('parses an unread-count response', () => {
        expect(UnreadCountResponseSchema.parse({ count: 5 }).count).toBe(5);
    });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/schemas/notifications.test.ts`
Expected: FAIL — cannot resolve `./notifications`.

- [ ] **Step 3: Write the schema file**

Create `frontend/src/lib/schemas/notifications.ts`:

```typescript
import { z } from 'zod';

export const NotificationSchema = z
    .object({
        id: z.string(),
        user_id: z.string(),
        event_type: z.string(),
        entity_type: z.string(),
        entity_id: z.string(),
        title: z.string(),
        message: z.string(),
        read_at: z.string().nullable(),
        created_at: z.string(),
    })
    .passthrough();
export type NotificationItem = z.infer<typeof NotificationSchema>;

export const NotificationListResponseSchema = z
    .object({
        items: z.array(NotificationSchema),
        total: z.number(),
    })
    .passthrough();
export type NotificationListResponse = z.infer<
    typeof NotificationListResponseSchema
>;

export const UnreadCountResponseSchema = z
    .object({
        count: z.number(),
    })
    .passthrough();
export type UnreadCountResponse = z.infer<typeof UnreadCountResponseSchema>;
```

- [ ] **Step 4: Barrel-export the new file**

In `frontend/src/lib/schemas/index.ts`, add at the end:

```typescript
export * from './notifications';
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/schemas/notifications.test.ts`
Expected: PASS — 4 tests green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/schemas/notifications.ts frontend/src/lib/schemas/index.ts frontend/src/lib/schemas/notifications.test.ts
git commit -m "feat(TD-0091b): add notification Zod schemas"
```

---

## Task 8: Frontend helpers — `lib/notifications.ts`

`eventIcon` returns a lucide-svelte icon component; `notificationHref` is the pure deep-link resolver; plus the page-size constants.

**Files:**
- Create: `frontend/src/lib/notifications.ts`
- Test: `frontend/src/lib/notifications.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/notifications.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import {
    eventIcon,
    eventTone,
    notificationHref,
    BELL_LIMIT,
    HISTORY_PAGE_SIZE,
} from './notifications';

const UUID = '33333333-3333-3333-3333-333333333333';

describe('notificationHref', () => {
    it('maps known entity types to their routes', () => {
        expect(notificationHref('run', UUID)).toBe(`/runs/${UUID}`);
        expect(notificationHref('protocol', UUID)).toBe(`/protocols/${UUID}`);
        expect(notificationHref('experiment', UUID)).toBe(`/experiments/${UUID}`);
        expect(notificationHref('project', UUID)).toBe(`/projects/${UUID}`);
    });

    it('returns null for an unknown entity type', () => {
        expect(notificationHref('widget', UUID)).toBeNull();
    });

    it('returns null for a falsy or malformed entity id', () => {
        expect(notificationHref('run', '')).toBeNull();
        expect(notificationHref('run', 'not-a-uuid')).toBeNull();
    });
});

describe('eventIcon', () => {
    it('returns a component for a known event type', () => {
        expect(eventIcon('RUN_STARTED')).toBeTruthy();
    });

    it('returns a fallback component for an unknown event type', () => {
        expect(eventIcon('SOMETHING_NEW')).toBeTruthy();
    });
});

describe('eventTone', () => {
    it('returns a tone class for a known event type', () => {
        expect(eventTone('STEP_DEVIATION')).toContain('destructive');
    });

    it('returns the muted fallback for an unknown event type', () => {
        expect(eventTone('SOMETHING_NEW')).toBe(
            'bg-muted text-muted-foreground',
        );
    });
});

describe('constants', () => {
    it('exposes the bell and history page sizes', () => {
        expect(BELL_LIMIT).toBe(20);
        expect(HISTORY_PAGE_SIZE).toBe(25);
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/notifications.test.ts`
Expected: FAIL — cannot resolve `./notifications`.

- [ ] **Step 3: Write the helper module**

Create `frontend/src/lib/notifications.ts`:

```typescript
import {
    AlertTriangle,
    ArrowLeft,
    ArrowLeftRight,
    ArrowRight,
    BadgeCheck,
    Bell,
    CheckCircle2,
    FileCheck2,
    Mail,
    Play,
    Undo2,
} from 'lucide-svelte';

/** Items fetched into the bell dropdown. */
export const BELL_LIMIT = 20;
/** Items per page on the /notifications history route. */
export const HISTORY_PAGE_SIZE = 25;

// `typeof Bell` is a concrete lucide-svelte icon component type; every
// icon below shares it, so the map and the fallback stay type-aligned.
const EVENT_ICONS: Record<string, typeof Bell> = {
    RUN_STARTED: Play,
    RUN_COMPLETED: CheckCircle2,
    ROLE_ASSIGNED: ArrowRight,
    ROLE_UNASSIGNED: ArrowLeft,
    ROLE_REASSIGNED: ArrowLeftRight,
    PROTOCOL_APPROVED: BadgeCheck,
    PROTOCOL_REVERTED: Undo2,
    PROTOCOL_APPROVAL_REQUESTED: FileCheck2,
    INVITE_SENT: Mail,
    INVITE_ACCEPTED: BadgeCheck,
    STEP_DEVIATION: AlertTriangle,
};

/** Resolve the lucide icon for an event type; `Bell` is the fallback. */
export function eventIcon(eventType: string): typeof Bell {
    return EVENT_ICONS[eventType] ?? Bell;
}

// Tonal chip classes (background + foreground) for the icon, so a
// scientist scanning the list can categorise notifications by colour at a
// glance. Theme/utility tokens only — never a raw `bg-white`.
const EVENT_TONES: Record<string, string> = {
    RUN_STARTED: 'bg-primary/10 text-primary',
    RUN_COMPLETED: 'bg-emerald-500/12 text-emerald-600',
    ROLE_ASSIGNED: 'bg-primary/10 text-primary',
    ROLE_UNASSIGNED: 'bg-primary/10 text-primary',
    ROLE_REASSIGNED: 'bg-primary/10 text-primary',
    PROTOCOL_APPROVED: 'bg-emerald-500/12 text-emerald-600',
    PROTOCOL_REVERTED: 'bg-amber-500/15 text-amber-600',
    PROTOCOL_APPROVAL_REQUESTED: 'bg-primary/10 text-primary',
    INVITE_SENT: 'bg-muted text-muted-foreground',
    INVITE_ACCEPTED: 'bg-emerald-500/12 text-emerald-600',
    STEP_DEVIATION: 'bg-destructive/10 text-destructive',
};

/** Tonal chip classes for an event type; neutral muted fallback. */
export function eventTone(eventType: string): string {
    return EVENT_TONES[eventType] ?? 'bg-muted text-muted-foreground';
}

const ENTITY_ROUTES: Record<string, string> = {
    run: '/runs',
    protocol: '/protocols',
    experiment: '/experiments',
    project: '/projects',
};

const UUID_RE =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Resolve a notification's in-app deep link, or `null` when the entity
 * type is unknown or the id is missing / not a UUID. Callers degrade a
 * `null` result to "mark read only".
 */
export function notificationHref(
    entityType: string,
    entityId: string,
): string | null {
    const base = ENTITY_ROUTES[entityType];
    if (!base) return null;
    if (!entityId || !UUID_RE.test(entityId)) return null;
    return `${base}/${entityId}`;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/notifications.test.ts`
Expected: PASS — all tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/notifications.ts frontend/src/lib/notifications.test.ts
git commit -m "feat(TD-0091b): add notification view helpers (eventIcon, notificationHref)"
```

---

## Task 9: Shared `NotificationRow` component

One presentational row used by both the bell dropdown (`compact`) and the history page (full width). Renders as `<a>` when a deep-link resolves (right-click / open-in-new-tab / keyboard for free), otherwise `<button>`. `onSelect` fires for the parent's mark-read + navigation logic in both cases.

**Files:**
- Create: `frontend/src/lib/components/notifications/NotificationRow.svelte`
- Test: `frontend/src/lib/components/notifications/NotificationRow.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/components/notifications/NotificationRow.test.ts`:

```typescript
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import NotificationRow from './NotificationRow.svelte';
import type { NotificationItem } from '$lib/schemas';

const UUID = '33333333-3333-3333-3333-333333333333';

function makeItem(over: Partial<NotificationItem> = {}): NotificationItem {
    return {
        id: '1',
        user_id: 'u',
        event_type: 'RUN_STARTED',
        entity_type: 'run',
        entity_id: UUID,
        title: 'Run started',
        message: 'CHO-042 started by Alice',
        read_at: null,
        created_at: new Date().toISOString(),
        ...over,
    };
}

describe('NotificationRow', () => {
    it('renders an <a> with the deep link when one resolves', () => {
        const { container } = render(NotificationRow, {
            props: { item: makeItem(), compact: true, onSelect: vi.fn() },
        });
        const link = container.querySelector('a');
        expect(link).not.toBeNull();
        expect(link?.getAttribute('href')).toBe(`/runs/${UUID}`);
    });

    it('renders a <button> when no deep link resolves', () => {
        const { container } = render(NotificationRow, {
            props: {
                item: makeItem({ entity_type: 'unknown' }),
                compact: true,
                onSelect: vi.fn(),
            },
        });
        expect(container.querySelector('a')).toBeNull();
        expect(container.querySelector('button')).not.toBeNull();
    });

    it('fires onSelect on click (deep-linkable row)', async () => {
        const onSelect = vi.fn();
        const { getByTestId } = render(NotificationRow, {
            props: { item: makeItem(), compact: false, onSelect },
        });
        await fireEvent.click(getByTestId('notification-row'));
        expect(onSelect).toHaveBeenCalledOnce();
    });

    it('fires onSelect on click (non-linkable row)', async () => {
        const onSelect = vi.fn();
        const { getByTestId } = render(NotificationRow, {
            props: {
                item: makeItem({ entity_type: 'unknown' }),
                compact: false,
                onSelect,
            },
        });
        await fireEvent.click(getByTestId('notification-row'));
        expect(onSelect).toHaveBeenCalledOnce();
    });

    it('shows the title and message', () => {
        const { getByText } = render(NotificationRow, {
            props: { item: makeItem(), compact: true, onSelect: vi.fn() },
        });
        expect(getByText('Run started')).toBeInTheDocument();
        expect(getByText('CHO-042 started by Alice')).toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/components/notifications/NotificationRow.test.ts`
Expected: FAIL — cannot resolve `./NotificationRow.svelte`.

- [ ] **Step 3: Write the component**

Create `frontend/src/lib/components/notifications/NotificationRow.svelte`:

```svelte
<script lang="ts">
    import { ChevronRight } from 'lucide-svelte';
    import { eventIcon, eventTone, notificationHref } from '$lib/notifications';
    import { timeAgo } from '$lib/utils';
    import type { NotificationItem } from '$lib/schemas';

    interface Props {
        item: NotificationItem;
        compact: boolean;
        onSelect: (item: NotificationItem) => void;
    }
    let { item, compact, onSelect }: Props = $props();

    const href = $derived(notificationHref(item.entity_type, item.entity_id));
    const Icon = $derived(eventIcon(item.event_type));
    const tone = $derived(eventTone(item.event_type));
    const unread = $derived(!item.read_at);

    function handleClick(e: MouseEvent) {
        // For an <a>, let modified / non-left clicks open a new tab natively.
        if (href && (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0)) {
            return;
        }
        if (href) e.preventDefault();
        onSelect(item);
    }
</script>

{#snippet body()}
    <span
        class="shrink-0 rounded-lg flex items-center justify-center {tone}
            {compact ? 'size-7' : 'size-9'}"
        title={item.event_type}
    >
        <Icon class={compact ? 'size-4' : 'size-[18px]'} />
    </span>
    <span class="flex-1 min-w-0">
        <span class="flex items-center gap-1.5">
            {#if compact && unread}
                <span class="size-1.5 rounded-full bg-primary shrink-0"></span>
            {/if}
            <span class="text-sm font-medium truncate">{item.title}</span>
        </span>
        <span
            class="block text-xs text-muted-foreground mt-0.5 {compact
                ? 'line-clamp-2'
                : 'line-clamp-3'}"
        >{item.message}</span>
        <span class="block text-[11px] text-muted-foreground/60 mt-1">
            {timeAgo(item.created_at)}
        </span>
    </span>
    {#if href}
        <!-- Hover affordance: only navigable rows get the chevron, so the
             user can tell navigate-vs-mark-read apart before tapping. -->
        <ChevronRight
            class="shrink-0 self-center size-4 text-muted-foreground opacity-0 -translate-x-1 transition-all duration-150 group-hover:opacity-100 group-hover:translate-x-0"
        />
    {/if}
{/snippet}

{#if href}
    <a
        {href}
        onclick={handleClick}
        data-testid="notification-row"
        class="group flex items-start transition-colors duration-150 cursor-pointer hover:bg-accent/50 border-b border-border/30 last:border-b-0
            {compact ? 'gap-2 px-3 py-2.5' : 'gap-3 px-4 py-3.5'}
            {!compact && unread ? 'border-l-2 border-l-primary' : ''}
            {!compact && !unread ? 'border-l-2 border-l-transparent' : ''}
            {!unread ? 'opacity-70 hover:opacity-100' : ''}"
    >
        {@render body()}
    </a>
{:else}
    <button
        type="button"
        onclick={handleClick}
        data-testid="notification-row"
        class="group w-full text-left flex items-start transition-colors duration-150 cursor-pointer hover:bg-accent/50 border-b border-border/30 last:border-b-0
            {compact ? 'gap-2 px-3 py-2.5' : 'gap-3 px-4 py-3.5'}
            {!compact && unread ? 'border-l-2 border-l-primary' : ''}
            {!compact && !unread ? 'border-l-2 border-l-transparent' : ''}
            {!unread ? 'opacity-70 hover:opacity-100' : ''}"
    >
        {@render body()}
    </button>
{/if}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/components/notifications/NotificationRow.test.ts`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/notifications/NotificationRow.svelte frontend/src/lib/components/notifications/NotificationRow.test.ts
git commit -m "feat(TD-0091b): add shared NotificationRow component"
```

---

## Task 10: Rewrite `NotificationBell.svelte`

Smarter polling (refetch the list on each tick while open, and on `visibilitychange`), a request-sequence concurrency guard, explicit error handling (toast on user-initiated failures, silent `console.error` on background polls), deep-linking via `NotificationRow`, and a "View all" footer link. The badge count is always sourced from `unread-count`.

**Files:**
- Rewrite: `frontend/src/lib/components/layout/NotificationBell.svelte`
- Test: `frontend/src/lib/components/layout/NotificationBell.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/components/layout/NotificationBell.test.ts`:

```typescript
import { render, fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/auth.svelte', () => ({ isAuthenticated: () => true }));
vi.mock('$lib/api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('$lib/toast', () => ({
    toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { api } from '$lib/api';
import { toast } from '$lib/toast';
import NotificationBell from './NotificationBell.svelte';

const UUID = '33333333-3333-3333-3333-333333333333';

function makeItem(over: Record<string, unknown> = {}) {
    return {
        id: '1',
        user_id: 'u',
        event_type: 'RUN_STARTED',
        entity_type: 'run',
        entity_id: UUID,
        title: 'Run started',
        message: 'CHO-042 started',
        read_at: null,
        created_at: new Date().toISOString(),
        ...over,
    };
}

/** Default api.get mock: branches on the endpoint. */
function mockApi(opts: {
    count?: number;
    items?: ReturnType<typeof makeItem>[];
} = {}) {
    vi.mocked(api.get).mockImplementation((endpoint: string) => {
        if (endpoint.includes('unread-count')) {
            return Promise.resolve({ count: opts.count ?? 0 });
        }
        return Promise.resolve({ items: opts.items ?? [], total: 0 });
    });
}

function deferred<T>() {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => {
        resolve = r;
    });
    return { promise, resolve };
}

describe('NotificationBell', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers();
        vi.mocked(api.put).mockResolvedValue({});
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('renders the unread badge from unread-count', async () => {
        mockApi({ count: 4 });
        render(NotificationBell);
        await vi.waitFor(() => {
            expect(screen.getByText('4')).toBeInTheDocument();
        });
    });

    it('fetches the list when the dropdown opens', async () => {
        mockApi({ count: 0, items: [makeItem()] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('/notifications/?limit=20'),
            expect.anything(),
        );
    });

    it('refetches list and count on a poll tick while open', async () => {
        mockApi({ count: 0, items: [makeItem()] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        const before = vi.mocked(api.get).mock.calls.length;
        await vi.advanceTimersByTimeAsync(30000);
        const after = vi.mocked(api.get).mock.calls.length;
        // count + list = 2 more calls
        expect(after).toBeGreaterThanOrEqual(before + 2);
    });

    it('does not toast when a background count-poll fails', async () => {
        vi.mocked(api.get).mockRejectedValue(new Error('network'));
        render(NotificationBell);
        await vi.advanceTimersByTimeAsync(30000);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('toasts when opening the dropdown fails', async () => {
        vi.mocked(api.get).mockRejectedValue(new Error('network'));
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await vi.waitFor(() => {
            expect(toast.error).toHaveBeenCalled();
        });
    });

    it('ignores a stale (out-of-sequence) list response', async () => {
        const first = deferred<unknown>();
        const second = deferred<unknown>();
        let listCall = 0;
        vi.mocked(api.get).mockImplementation((endpoint: string) => {
            if (endpoint.includes('unread-count')) {
                return Promise.resolve({ count: 0 });
            }
            listCall += 1;
            return listCall === 1 ? first.promise : second.promise;
        });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications')); // list #1
        await tick();
        await vi.advanceTimersByTimeAsync(30000); // list #2
        // newer response lands first
        second.resolve({ items: [makeItem({ id: 'n', title: 'Newer' })], total: 0 });
        await tick();
        // older response lands last — must be discarded
        first.resolve({ items: [makeItem({ id: 'o', title: 'Older' })], total: 0 });
        await tick();
        expect(screen.getByText('Newer')).toBeInTheDocument();
        expect(screen.queryByText('Older')).not.toBeInTheDocument();
    });

    it('marks all read and clears the badge', async () => {
        mockApi({ count: 2, items: [makeItem(), makeItem({ id: '2' })] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        await fireEvent.click(screen.getByText('Mark all read'));
        await tick();
        expect(api.put).toHaveBeenCalledWith('/notifications/read-all', {});
    });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/components/layout/NotificationBell.test.ts`
Expected: FAIL — current `NotificationBell.svelte` has no `unread-count` schema usage / list refetch / toast wiring, so several assertions fail.

- [ ] **Step 3: Rewrite the component**

Replace the entire contents of `frontend/src/lib/components/layout/NotificationBell.svelte` with:

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { isAuthenticated } from '$lib/auth.svelte';
    import { toast } from '$lib/toast';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { Button } from '$lib/components/ui/button';
    import NotificationRow from '$lib/components/notifications/NotificationRow.svelte';
    import { notificationHref, BELL_LIMIT } from '$lib/notifications';
    import {
        NotificationListResponseSchema,
        UnreadCountResponseSchema,
        type NotificationItem,
    } from '$lib/schemas';

    const POLL_MS = 30000;

    let open = $state(false);
    let unreadCount = $state(0);
    let notifications = $state<NotificationItem[]>([]);
    let loading = $state(false);
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    // Monotonic sequence: a list fetch assigns `notifications` only if its
    // sequence is still the latest, so a slow earlier response cannot
    // clobber a fresh later one.
    let listSeq = 0;

    const hasUnread = $derived(notifications.some((n) => !n.read_at));

    async function fetchUnreadCount(): Promise<void> {
        if (!isAuthenticated()) return;
        try {
            const resp = await api.get('/notifications/unread-count', {
                schema: UnreadCountResponseSchema,
            });
            unreadCount = resp.count;
        } catch (e) {
            // Background poll — log only; the next tick self-heals.
            console.error('Notification unread-count poll failed', e);
        }
    }

    async function fetchNotifications(userInitiated = false): Promise<void> {
        if (!isAuthenticated()) return;
        const seq = ++listSeq;
        loading = true;
        try {
            const resp = await api.get(`/notifications/?limit=${BELL_LIMIT}`, {
                schema: NotificationListResponseSchema,
            });
            if (seq !== listSeq) return; // a newer fetch already landed
            notifications = resp.items;
        } catch (e) {
            console.error('Notification list fetch failed', e);
            if (userInitiated) {
                toast.error('Could not load notifications');
            }
        } finally {
            if (seq === listSeq) loading = false;
        }
    }

    // NOTE: markRead / markAllRead / handleSelect are intentionally
    // duplicated in routes/notifications/+page.svelte (count-2, no shared
    // store yet). Keep the mark-read error semantics in sync across both.
    async function markRead(id: string, navigating: boolean): Promise<void> {
        const idx = notifications.findIndex((n) => n.id === id);
        if (idx === -1 || notifications[idx].read_at) return;
        // Optimistic update first (snappy).
        notifications[idx] = {
            ...notifications[idx],
            read_at: new Date().toISOString(),
        };
        unreadCount = Math.max(0, unreadCount - 1);
        try {
            await api.put(`/notifications/${id}/read`, {});
        } catch (e) {
            console.error('Mark-read failed', e);
            toast.error('Could not mark notification as read');
            // Navigating clicks unmount this component — refetch only for
            // plain (non-navigating) clicks so the UI converges.
            if (!navigating) {
                await fetchNotifications();
                await fetchUnreadCount();
            }
        }
    }

    async function markAllRead(): Promise<void> {
        const snapshot = notifications;
        const prevCount = unreadCount;
        notifications = notifications.map((n) => ({
            ...n,
            read_at: n.read_at ?? new Date().toISOString(),
        }));
        unreadCount = 0;
        try {
            await api.put('/notifications/read-all', {});
        } catch (e) {
            console.error('Mark-all-read failed', e);
            toast.error('Could not mark all as read');
            notifications = snapshot;
            unreadCount = prevCount;
            await fetchNotifications();
            await fetchUnreadCount();
        }
    }

    function handleSelect(item: NotificationItem): void {
        const href = notificationHref(item.entity_type, item.entity_id);
        if (!item.read_at) markRead(item.id, href !== null);
        if (href) {
            open = false;
            goto(href);
        }
    }

    function handleOpenChange(next: boolean): void {
        if (next) {
            fetchNotifications(true);
            fetchUnreadCount();
        }
    }

    function onPollTick(): void {
        fetchUnreadCount();
        if (open) fetchNotifications();
    }

    function onVisibility(): void {
        if (document.visibilityState !== 'visible') return;
        fetchUnreadCount();
        if (open) fetchNotifications();
    }

    onMount(() => {
        fetchUnreadCount();
        pollInterval = setInterval(onPollTick, POLL_MS);
        document.addEventListener('visibilitychange', onVisibility);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
        document.removeEventListener('visibilitychange', onVisibility);
    });
</script>

<DropdownMenu.Root bind:open onOpenChange={handleOpenChange}>
    <DropdownMenu.Trigger>
        <Button
            variant="ghost"
            size="icon-sm"
            rounded="full"
            class="relative text-muted-foreground hover:text-foreground"
            aria-label="Notifications"
        >
            <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                class={`size-5 ${unreadCount > 0 ? 'jingle' : ''}`}
            >
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            {#if unreadCount > 0}
                <span
                    class="absolute -top-1 -right-1 inline-flex items-center justify-center"
                    aria-live="polite"
                    aria-atomic="true"
                >
                    <span
                        class="notif-ping absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"
                    ></span>
                    <span
                        class="relative min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center leading-none"
                    >
                        {unreadCount > 99 ? '99+' : unreadCount}
                    </span>
                </span>
            {/if}
        </Button>
    </DropdownMenu.Trigger>

    <DropdownMenu.Content
        align="end"
        class="w-80 max-w-[calc(100vw-2rem)] z-[100] p-0"
    >
        <div class="flex items-center justify-between px-3 py-2 border-b border-border/60">
            <span class="text-sm font-semibold">Notifications</span>
            {#if hasUnread}
                <Button
                    variant="link"
                    size="sm"
                    class="h-auto p-0 text-xs"
                    onclick={markAllRead}
                >
                    Mark all read
                </Button>
            {/if}
        </div>

        <div class="overflow-y-auto max-h-72">
            {#if loading && notifications.length === 0}
                <div class="px-3 py-6 text-center text-sm text-muted-foreground">
                    Loading...
                </div>
            {:else if notifications.length === 0}
                <div class="px-3 py-6 text-center text-sm text-muted-foreground">
                    No notifications yet
                </div>
            {:else}
                {#each notifications as notif (notif.id)}
                    <NotificationRow
                        item={notif}
                        compact={true}
                        onSelect={handleSelect}
                    />
                {/each}
            {/if}
        </div>

        <DropdownMenu.Separator class="my-0" />
        <DropdownMenu.Item>
            {#snippet child({ props })}
                <a
                    href="/notifications"
                    {...props}
                    class="block w-full text-center px-3 py-2 text-xs font-medium text-primary cursor-pointer"
                >
                    View all notifications
                </a>
            {/snippet}
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>

<style>
    .jingle {
        transform-origin: 50% 10%;
        animation: jingle 2.4s ease-in-out infinite;
    }

    @keyframes jingle {
        0%, 60%, 100% { transform: rotate(0); }
        5%  { transform: rotate(-14deg); }
        10% { transform: rotate(12deg); }
        15% { transform: rotate(-10deg); }
        20% { transform: rotate(8deg); }
        25% { transform: rotate(-5deg); }
        30% { transform: rotate(3deg); }
        35% { transform: rotate(0); }
    }

    @media (prefers-reduced-motion: reduce) {
        .jingle,
        .notif-ping {
            animation: none;
        }
    }
</style>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/components/layout/NotificationBell.test.ts`
Expected: PASS — all tests green.

If the `DropdownMenu.Item` `child` snippet does not type-check (`npm run check` below), fall back to a plain styled `<a href="/notifications">` placed directly inside `DropdownMenu.Content` after the separator — it still gets keyboard focus and right-click/new-tab. Keep the same classes.

- [ ] **Step 5: Type-check**

Run: `cd frontend && npm run check`
Expected: no new errors in `NotificationBell.svelte` or `NotificationRow.svelte`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/layout/NotificationBell.svelte frontend/src/lib/components/layout/NotificationBell.test.ts
git commit -m "feat(TD-0091b): smarter polling, error handling, deep-links in NotificationBell"
```

---

## Task 11: Notification history route — `/notifications`

A paginated history page. `offset` is held in the URL search param so browser back/forward restores the page. Uses the shared `NotificationRow` (non-compact), `LoadingSpinner`, and `EmptyState`. `Mark all read` is server-wide, so it always refetches the current page afterward.

**Files:**
- Create: `frontend/src/routes/notifications/+page.ts`
- Create: `frontend/src/routes/notifications/+page.svelte`
- Test: `frontend/src/routes/notifications/page.test.ts`

- [ ] **Step 1: Write `+page.ts`**

Create `frontend/src/routes/notifications/+page.ts`:

```typescript
import type { PageLoad } from './$types';

/**
 * `offset` lives in the URL so browser back/forward restores the page
 * position. Non-numeric or negative values clamp to 0.
 */
export const load: PageLoad = ({ url }) => {
    const raw = Number(url.searchParams.get('offset') ?? '0');
    const offset = Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
    return { offset };
};
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/routes/notifications/page.test.ts`:

```typescript
import { render, fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('$lib/toast', () => ({
    toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { goto } from '$app/navigation';
import { api } from '$lib/api';
import { load } from './+page';
import NotificationsPage from './+page.svelte';

const UUID = '33333333-3333-3333-3333-333333333333';

function makeItem(over: Record<string, unknown> = {}) {
    return {
        id: '1',
        user_id: 'u',
        event_type: 'RUN_STARTED',
        entity_type: 'run',
        entity_id: UUID,
        title: 'Run started',
        message: 'CHO-042 started',
        read_at: null,
        created_at: new Date().toISOString(),
        ...over,
    };
}

describe('/notifications +page.ts load', () => {
    it('reads offset from the URL', () => {
        const data = load({
            url: new URL('http://x/notifications?offset=50'),
        } as Parameters<typeof load>[0]);
        expect(data).toEqual({ offset: 50 });
    });

    it('clamps a missing or invalid offset to 0', () => {
        const a = load({
            url: new URL('http://x/notifications'),
        } as Parameters<typeof load>[0]);
        const b = load({
            url: new URL('http://x/notifications?offset=-9'),
        } as Parameters<typeof load>[0]);
        expect(a).toEqual({ offset: 0 });
        expect(b).toEqual({ offset: 0 });
    });
});

describe('/notifications page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(api.put).mockResolvedValue({});
    });
    afterEach(() => {
        // nothing
    });

    it('loads the first page on mount', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 1 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('offset=0'),
            expect.anything(),
        );
        await screen.findByText('Run started');
    });

    it('requests the offset from page data', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [], total: 100 });
        render(NotificationsPage, { props: { data: { offset: 25 } } });
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('offset=25'),
            expect.anything(),
        );
    });

    it('Next navigates to the following offset', async () => {
        vi.mocked(api.get).mockResolvedValue({
            items: [makeItem()],
            total: 100,
        });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByText('Next'));
        expect(goto).toHaveBeenCalledWith(
            '/notifications?offset=25',
            expect.objectContaining({ keepFocus: true, noScroll: true }),
        );
    });

    it('shows the empty state when there are no notifications', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('No notifications');
    });

    it('mark all read calls the API and refetches', async () => {
        vi.mocked(api.get).mockResolvedValue({
            items: [makeItem()],
            total: 1,
        });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        const callsBefore = vi.mocked(api.get).mock.calls.length;
        await fireEvent.click(screen.getByText('Mark all read'));
        await tick();
        expect(api.put).toHaveBeenCalledWith('/notifications/read-all', {});
        await vi.waitFor(() => {
            expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(
                callsBefore,
            );
        });
    });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/routes/notifications/page.test.ts`
Expected: FAIL — cannot resolve `./+page.svelte`.

- [ ] **Step 4: Write `+page.svelte`**

Create `frontend/src/routes/notifications/+page.svelte`:

```svelte
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import { Button } from '$lib/components/ui/button';
    import { Bell, ChevronLeft, ChevronRight } from 'lucide-svelte';
    import NotificationRow from '$lib/components/notifications/NotificationRow.svelte';
    import { notificationHref, HISTORY_PAGE_SIZE } from '$lib/notifications';
    import {
        NotificationListResponseSchema,
        type NotificationItem,
    } from '$lib/schemas';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    let items = $state<NotificationItem[]>([]);
    let total = $state(0);
    let loading = $state(true);

    // Sequence guard — see NotificationBell. Page fetches can overlap when
    // the user pages quickly.
    let pageSeq = 0;

    // A handleSelect deep-link navigation unmounts this page while a
    // loadPage fetch may still be in flight. `destroyed` blocks the
    // resolved fetch from toasting / mutating $state on a dead component
    // (Svelte logs a warning for post-unmount state writes).
    let destroyed = false;
    onDestroy(() => {
        destroyed = true;
    });

    async function loadPage(offset: number): Promise<void> {
        const seq = ++pageSeq;
        loading = true;
        try {
            const resp = await api.get(
                `/notifications/?include_total=true&limit=${HISTORY_PAGE_SIZE}&offset=${offset}`,
                { schema: NotificationListResponseSchema },
            );
            if (destroyed || seq !== pageSeq) return;
            items = resp.items;
            total = resp.total;
        } catch (e) {
            console.error('Notification history load failed', e);
            if (!destroyed && seq === pageSeq) {
                toast.error('Could not load notifications');
            }
        } finally {
            if (!destroyed && seq === pageSeq) loading = false;
        }
    }

    // Refetch whenever the URL offset changes (back/forward, Prev/Next).
    $effect(() => {
        loadPage(data.offset);
    });

    function gotoOffset(offset: number): void {
        const query = offset > 0 ? `?offset=${offset}` : '';
        goto(`/notifications${query}`, { keepFocus: true, noScroll: true });
    }

    // NOTE: markRead / markAllRead / handleSelect mirror the same logic in
    // components/layout/NotificationBell.svelte (count-2, no shared store
    // yet). Keep the mark-read error semantics in sync across both.
    async function markRead(id: string, navigating: boolean): Promise<void> {
        const idx = items.findIndex((n) => n.id === id);
        if (idx === -1 || items[idx].read_at) return;
        items[idx] = { ...items[idx], read_at: new Date().toISOString() };
        try {
            await api.put(`/notifications/${id}/read`, {});
        } catch (e) {
            console.error('Mark-read failed', e);
            toast.error('Could not mark notification as read');
            // Navigating clicks unmount the page — refetch only otherwise.
            if (!navigating) await loadPage(data.offset);
        }
    }

    async function markAllRead(): Promise<void> {
        try {
            await api.put('/notifications/read-all', {});
        } catch (e) {
            console.error('Mark-all-read failed', e);
            toast.error('Could not mark all as read');
        }
        // Server-wide action: rows on other pages are now stale too.
        await loadPage(data.offset);
    }

    function handleSelect(item: NotificationItem): void {
        const href = notificationHref(item.entity_type, item.entity_id);
        if (!item.read_at) markRead(item.id, href !== null);
        if (href) goto(href);
    }

    const hasUnread = $derived(items.some((n) => !n.read_at));
    const rangeStart = $derived(items.length ? data.offset + 1 : 0);
    const rangeEnd = $derived(data.offset + items.length);
    const hasPrev = $derived(data.offset > 0);
    const hasNext = $derived(data.offset + HISTORY_PAGE_SIZE < total);
</script>

<div class="max-w-3xl mx-auto px-4 py-8" in:fade={{ duration: 150 }}>
    <div class="flex items-start justify-between mb-6">
        <div>
            <h1 class="text-xl font-semibold">Notifications</h1>
            <p class="text-sm text-muted-foreground mt-0.5">
                Activity from your runs, protocols, and team.
            </p>
        </div>
        {#if hasUnread}
            <Button variant="outline" size="sm" onclick={markAllRead}>
                Mark all read
            </Button>
        {/if}
    </div>

    {#if loading && items.length === 0}
        <LoadingSpinner message="Loading notifications…" />
    {:else if items.length === 0}
        <EmptyState
            title="No notifications"
            description="Activity from your runs and protocols will appear here."
        >
            {#snippet icon()}
                <Bell class="size-7" />
            {/snippet}
        </EmptyState>
    {:else}
        <div class="rounded-lg border border-border/60 overflow-hidden bg-card">
            {#each items as item (item.id)}
                <div animate:flip={{ duration: 150 }} in:fade={{ duration: 120 }}>
                    <NotificationRow
                        {item}
                        compact={false}
                        onSelect={handleSelect}
                    />
                </div>
            {/each}
        </div>

        <div class="flex items-center justify-between mt-4 text-sm text-muted-foreground">
            <span>Showing {rangeStart}–{rangeEnd} of {total}</span>
            <div class="flex gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasPrev}
                    onclick={() =>
                        gotoOffset(Math.max(0, data.offset - HISTORY_PAGE_SIZE))}
                >
                    <ChevronLeft class="size-3.5" />
                    Prev
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasNext}
                    onclick={() => gotoOffset(data.offset + HISTORY_PAGE_SIZE)}
                >
                    Next
                    <ChevronRight class="size-3.5" />
                </Button>
            </div>
        </div>
    {/if}
</div>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/routes/notifications/page.test.ts`
Expected: PASS — all tests green.

- [ ] **Step 6: Type-check**

Run: `cd frontend && npm run check`
Expected: no new errors in the `notifications` route.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/notifications/
git commit -m "feat(TD-0091b): add paginated notification history page"
```

---

## Task 12: Docs & rules

**Files:**
- Modify: `.claude/rules/conventions.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the `notifications/` component bucket**

In `.claude/rules/conventions.md`, under the `### Component placement` bucket list, add a line in domain order (after the `media/` entry, before `document-refinement/` — keep the existing surrounding lines):

```
- `notifications/` — notification inbox surfaces (shared notification row)
```

- [ ] **Step 2: Document the retention env var**

In `CLAUDE.md`, under the `## Feature flags` section's notes — or, if it reads more naturally, in a short adjacent note — there is no flag table row for retention (it is a setting, not a flag). Instead add one line to the backend commands / settings context. Add this line right after the `## Feature flags` table's closing note paragraph:

```markdown
`BATCHRITE_NOTIFICATION_RETENTION_DAYS` (default `90`) bounds the in-app notification table: the recovery loop hard-deletes read notifications older than this window. Set to `0` to disable. (TD-0091b)
```

- [ ] **Step 3: Verify**

Run: `grep -n "notifications/" .claude/rules/conventions.md && grep -n "NOTIFICATION_RETENTION_DAYS" CLAUDE.md`
Expected: both greps return a match.

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/conventions.md CLAUDE.md
git commit -m "docs(TD-0091b): document notifications component bucket and retention env var"
```

---

## Final verification

- [ ] **Backend suite**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_notifications.py tests/integration/test_notification_api.py -q`
Expected: PASS.

- [ ] **Full backend suite (regression)**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: PASS (no regressions).

- [ ] **Frontend unit suite**

Run: `cd frontend && npm run test`
Expected: PASS.

- [ ] **Frontend type-check & build**

Run: `cd frontend && npm run check && npm run build`
Expected: no new errors; build succeeds.

---

## Self-Review Notes

This plan was checked against the spec `2026-05-21-td-0091b-notification-inbox-ux-design.md`:

- **Gap 1 (smarter polling)** — Task 10: poll tick refetches the list while open + `visibilitychange` listener; badge always from `unread-count`; sequence guard.
- **Gap 2 (error observability)** — Task 10 & 11: `console.error` on every catch; `toast.error` on user-initiated failures only; optimistic-update reconciliation refetch on non-navigating failures.
- **Gap 3 (history + retention)** — Task 11 (history route, URL `offset`, `EmptyState`/`LoadingSpinner`, "View all" link in Task 10), Tasks 1–5 (`include_total`, `purge_read_notifications`, partial index, throttled recovery-loop sweep).
- **Gap 4 (deep-linking)** — Task 8 (`notificationHref`), Task 9 (`NotificationRow` `<a>`/`<button>`), Tasks 10–11 (`handleSelect`: PUT before `goto`, navigating-click failures toast-only).
- **Gap 5 (test coverage)** — Tasks 3, 5, 6 (backend), 7–11 (frontend). `retry_pending` is already covered by the existing `TestRetryPending` (TD-0091a); Task 6 adds the missing `dispatch_event` coverage and records the `MAX_RETRIES` off-by-one.

Out of scope per spec, routed to `/add_task` by implement-task: the dispatcher `MAX_RETRIES`/`RETRY_BACKOFF` off-by-one fix; an ops runbook entry for "user reports missing notification history".

---

## Operational Notes / Deploy Checklist

The retention sweep performs an **irreversible hard delete**. Run through this before the first deploy that ships Task 5:

- [ ] **Confirm `BATCHRITE_NOTIFICATION_RETENTION_DAYS` before deploy.** The default is `90`. A too-small value (e.g. a stray `1`) silently destroys recent history on the first sweep — there is no soft-delete and no undo. Verify the resolved value in the target environment: `python -c "from app.core.config import settings; print(settings.notification_retention_days)"`. To ship the feature with the sweep dormant, set it to `0`.
- [ ] **Pre-count the first-sweep blast radius.** The first sweep on a never-purged table can delete a large backlog. Before the recovery loop's first tick, capture the expected count so the `Retention sweep: deleted N …` INFO log can be sanity-checked against it:
  ```sql
  SELECT count(*) FROM notifications
    WHERE read_at IS NOT NULL
      AND read_at < now() - (interval '1 day' * 90);  -- match the configured window
  ```
  If this number is surprisingly large, decide deliberately — the sweep is correct, but a six-figure delete is worth knowing about in advance. `PURGE_CHUNK_SIZE = 500` bounds lock duration and WAL volume per statement, so the delete is incremental, not one giant transaction.
- [ ] **Build the index before the sweep matters.** The Task 2 migration creates `ix_notif_read_at` with `CREATE INDEX CONCURRENTLY`. If that build was interrupted, recover the INVALID index per the Task 2 operator note *before* the sweep runs at scale — otherwise the `read_at` predicate falls back to a sequential scan.
- [ ] **Know the throttle is per-process.** Each worker/pod runs its own 24h-throttled sweep and every restart resets the timer (Task 5). The sweep is idempotent so this is safe; it is just not globally minimal. Do not expect exactly one sweep per day in a multi-worker deployment.

---

## Review Panel Amendments (step 2d)

The implementation plan was hardened by the implement-task review panel — `adversarial-risk-auditor`, `production-ops-reviewer`, `dry-reuse-auditor`, `db-scalability-reviewer`, `uiux-design-reviewer` — dispatched in parallel against this file. Findings reconciled and applied:

**Applied to the plan:**

- **Task 2 — INVALID-index recovery (adversarial, ops).** An interrupted `CREATE INDEX CONCURRENTLY` leaves an INVALID index that `IF NOT EXISTS` then matches by name, so the migration "succeeds" while the planner ignores the index. Added an operator note with the `pg_index.indisvalid` check and the manual `DROP INDEX CONCURRENTLY` recovery.
- **Task 3 — chunk determinism (db-scalability).** Added `ORDER BY Notification.read_at` to the `eligible` subquery so chunk membership is deterministic and the `deleted < PURGE_CHUNK_SIZE` termination is reliable; `ix_notif_read_at` already orders on `read_at`, so the sort is free.
- **Task 3 — partial-progress visibility (adversarial, ops).** Wrapped the chunked-delete loop in `try/except` that logs how many rows were already committed before a mid-sweep failure, since committed chunks are irreversible.
- **Task 3 — corrected the delivery rationale (adversarial Critical, downgraded).** The reviewer flagged `test_delivery_survives_purge_with_null_fk` as asserting a linkage production never creates. Verified against `main`: `_dispatch_to_channel` never sets `NotificationDelivery.notification_id`. The test is kept as an honest **schema-contract** test (FK holds *if* the two are ever linked) with an explanatory docstring; the retention module docstring was corrected to state deliveries are a separate, orthogonal audit trail rather than purge-protected children.
- **Task 4 — `test_list_empty` correctness (adversarial).** With `include_total` defaulting to `False`, `total=0` doubles as the "count skipped" sentinel — `test_list_empty` would pass for the wrong reason. Updated it to request `?include_total=true`. Also rewrote the COUNT as a direct `select(func.count()).select_from(Notification)` rather than a subquery wrap of `base`, so PostgreSQL serves it from `ix_notif_user_created`.
- **Task 5 — per-process throttle honesty (ops).** Reworded the `_last_notification_purge_at` comment to state plainly that the throttle is process-local: one sweep per worker per 24h, reset on every restart. Added the step that updates the recovery-loop disabled-warning and docstring to name the retention sweep.
- **Task 8 / 9 — tonal categorisation (uiux).** Added `eventTone()` + the `EVENT_TONES` map (theme tokens only, no raw `bg-white`) so a scientist can categorise notifications by colour at a glance; `NotificationRow` renders the tonal icon chip and a hover-revealed chevron that distinguishes navigable rows from mark-read-only rows.
- **Task 10 — dropdown polish (uiux).** Removed `bg-white` (broke dark mode) and `max-h-96 overflow-hidden` (clipped the scroll region) from `DropdownMenu.Content`; added `aria-live="polite" aria-atomic="true"` to the unread badge and a `prefers-reduced-motion` suppression for both the bell jingle and the badge ping.
- **Task 11 — history-page polish (uiux).** Widened to `max-w-3xl`, added a subtitle under the heading, gave Prev/Next `ChevronLeft`/`ChevronRight` icons, and added an `onDestroy` post-unmount guard to `loadPage` so a deep-link navigation mid-fetch cannot write `$state` on a dead component.
- **Tasks 10 & 11 — duplication acknowledged (dry-reuse).** `markRead` / `markAllRead` / `handleSelect` appear in both `NotificationBell.svelte` and the history `+page.svelte`. With only two call sites and no shared notification store yet, a cross-reference comment in each file (keep the error semantics in sync) is the proportionate response; a shared store is routed to `/add_task`.

**Reviewed and deliberately not changed:**

- `p-0` on `DropdownMenu.Content` is intentional — the rows are edge-to-edge, so the padding belongs on the row, not the container (uiux suggestion declined).
- `dispatch_event` tests assert `SENT` against the real `CONSOLE` channel — `CONSOLE` is deterministic and side-effect-free, so this is sound regression coverage, not a flaky external dependency (adversarial finding declined).
- `/notifications/read-all` route ordering — there is no path-shape collision with `/{id}/read`, and the existing `read-all` integration test already covers it (adversarial finding declined).

**Routed to `/add_task` (out of scope for TD-0091b):**

- Dispatcher `MAX_RETRIES` / `RETRY_BACKOFF` off-by-one fix (TECH_DEBT).
- Ops runbook entry: "user reports missing notification history" → explain retention window (TECH_DEBT / docs).
- `notifications_purged_total` metric counter so the sweep is observable beyond the INFO log (TECH_DEBT).
- Distributed purge-throttle lock (advisory lock / `BackgroundJob` row) so a multi-worker deployment sweeps once globally rather than once per worker (TECH_DEBT).
- Shared notification store to remove the `markRead`/`markAllRead`/`handleSelect` duplication once a third consumer appears (TECH_DEBT).
- Cursor-based pagination for the history page if `OFFSET` paging degrades on large inboxes (TECH_DEBT).
- Compliance-register note that in-app notifications are now subject to a 90-day retention purge (the external `notification_deliveries` audit trail is unaffected).
