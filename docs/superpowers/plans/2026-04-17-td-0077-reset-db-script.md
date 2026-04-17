# TD-0077 Reset-DB Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-shot dev DB reset that wipes user-generated tables and re-seeds the baseline, guarded against accidental prod use.

**Architecture:** Python module `backend/app/db/reset.py` hosts a pure `assert_local_dev_db` + `mask_database_url`, a transactional `reset_database(session)` (wraps `TRUNCATE ... CASCADE` + existing idempotent `seed_*` functions), an interactive `confirm_reset`, and a `_run()` CLI entry point (`python -m app.db.reset`). Shell wrapper `scripts/reset-db.sh` activates the venv and invokes the module. Tests split between unit (pure functions + constant sanity) and integration (real DB via `db_session` fixture).

**Tech Stack:** Python 3, SQLAlchemy 2.0 async, asyncpg, pytest-asyncio, bash.

**Spec:** [docs/superpowers/specs/2026-04-17-td-0077-reset-db-script-design.md](../specs/2026-04-17-td-0077-reset-db-script-design.md)

---

## File Structure

Files to create:
- `backend/app/db/reset.py` — module + `__main__` CLI. Single file (~90 LOC) since surface is small and everything is tightly coupled to the same transactional flow.
- `backend/tests/unit/test_reset_db.py` — pure-function tests.
- `backend/tests/integration/test_reset_db.py` — real-DB transactional tests.
- `scripts/reset-db.sh` — executable shell wrapper (~15 LOC).

Files to modify:
- `CLAUDE.md` — add one line under the Backend commands block.

---

## Task 1: `WIPE_TABLES` constant + sanity test

**Files:**
- Create: `backend/app/db/reset.py` (stub with just the constant)
- Create: `backend/tests/unit/test_reset_db.py`

- [ ] **Step 1: Write the failing test**

Write `backend/tests/unit/test_reset_db.py`:

```python
"""Unit tests for app.db.reset (pure functions + constant sanity)."""
from app.db.reset import WIPE_TABLES


EXPECTED_WIPE = {
    "experiments",
    "protocols",
    "protocol_roles",
    "protocol_versions",
    "runs",
    "run_role_assignments",
    "equipment",
    "documents",
    "document_chunks",
    "document_templates",
    "batch_record_imports",
    "chat_sessions",
    "chat_messages",
    "run_images",
    "image_conversations",
    "audit_logs",
    "background_jobs",
    "notifications",
    "notification_channels",
    "notification_subscriptions",
    "notification_deliveries",
    "revoked_offline_tokens",
    "invitations",
    "verification_tokens",
}

PRESERVE_TABLES = {
    "users",
    "organizations",
    "organization_members",
    "teams",
    "team_members",
    "projects",
    "object_permissions",
    "unit_op_definitions",
    "ai_provider_configs",
}


def test_wipe_tables_matches_expected_set():
    assert set(WIPE_TABLES) == EXPECTED_WIPE


def test_wipe_tables_excludes_preserve_tables():
    assert set(WIPE_TABLES).isdisjoint(PRESERVE_TABLES)


def test_wipe_tables_has_no_duplicates():
    assert len(WIPE_TABLES) == len(set(WIPE_TABLES))
```

- [ ] **Step 2: Run tests to verify they fail**

From `backend/` with venv activated:

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: FAIL with `ImportError` (reset module doesn't exist yet).

- [ ] **Step 3: Create the module with just the constant**

Create `backend/app/db/reset.py`:

```python
"""Dev DB reset: wipe user-generated data and re-seed the baseline.

Run via: python -m app.db.reset (from backend/)
Or: scripts/reset-db.sh (from repo root)

Guarded to only run against localhost/batchrite to prevent accidental
use against a staging or production database.
"""
from __future__ import annotations

WIPE_TABLES: tuple[str, ...] = (
    # Science graph
    "experiments",
    "protocols",
    "protocol_roles",
    "protocol_versions",
    "runs",
    "run_role_assignments",
    "equipment",
    # Library / documents
    "documents",
    "document_chunks",
    "document_templates",
    "batch_record_imports",
    # Chat
    "chat_sessions",
    "chat_messages",
    # AI / images
    "run_images",
    "image_conversations",
    # Audit / jobs
    "audit_logs",
    "background_jobs",
    # Notifications
    "notifications",
    "notification_channels",
    "notification_subscriptions",
    "notification_deliveries",
    # Auth ephemera
    "revoked_offline_tokens",
    "invitations",
    "verification_tokens",
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/reset.py backend/tests/unit/test_reset_db.py
git commit -m "test(reset-db): WIPE_TABLES constant + sanity tests [TD-0077]"
```

---

## Task 2: `mask_database_url` pure function

**Files:**
- Modify: `backend/app/db/reset.py`
- Modify: `backend/tests/unit/test_reset_db.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/unit/test_reset_db.py`:

```python
from app.db.reset import mask_database_url


def test_mask_database_url_masks_simple_password():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == "postgresql+asyncpg://postgres:***@localhost:5432/batchrite"


def test_mask_database_url_masks_complex_password():
    url = "postgresql+asyncpg://user:p@ss!w0rd#1@db.host.internal:5432/mydb"
    masked = mask_database_url(url)
    # Password runs up to the LAST @ before the host segment.
    assert "p@ss!w0rd#1" not in masked
    assert "***" in masked
    assert "db.host.internal" in masked


def test_mask_database_url_passes_through_url_without_password():
    url = "postgresql+asyncpg://localhost:5432/batchrite"
    masked = mask_database_url(url)
    assert masked == url
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: 3 failures (new tests) with `ImportError: cannot import name 'mask_database_url'`.

- [ ] **Step 3: Implement `mask_database_url`**

Append to `backend/app/db/reset.py`:

```python
from urllib.parse import urlsplit, urlunsplit


def mask_database_url(url: str) -> str:
    """Return url with the password segment replaced by ``***``.

    Leaves the rest of the URL untouched so users can still see the target
    host + database before confirming a destructive action.
    """
    parts = urlsplit(url)
    if parts.password is None:
        return url
    # Rebuild netloc with masked password.
    userinfo = parts.username or ""
    masked_netloc = f"{userinfo}:***@{parts.hostname or ''}"
    if parts.port is not None:
        masked_netloc = f"{masked_netloc}:{parts.port}"
    return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/reset.py backend/tests/unit/test_reset_db.py
git commit -m "feat(reset-db): mask_database_url for safe URL display [TD-0077]"
```

---

## Task 3: `assert_local_dev_db` prod guard

**Files:**
- Modify: `backend/app/db/reset.py`
- Modify: `backend/tests/unit/test_reset_db.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/unit/test_reset_db.py`:

```python
import pytest

from app.db.reset import assert_local_dev_db


def test_assert_local_dev_db_accepts_localhost():
    assert_local_dev_db("postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite")


def test_assert_local_dev_db_accepts_127_0_0_1():
    assert_local_dev_db("postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/batchrite")


def test_assert_local_dev_db_rejects_non_local_host():
    url = "postgresql+asyncpg://postgres:postgres@prod.db.internal:5432/batchrite"
    with pytest.raises(RuntimeError) as exc:
        assert_local_dev_db(url)
    assert "prod.db.internal" in str(exc.value)


def test_assert_local_dev_db_rejects_wrong_db_name():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_prod"
    with pytest.raises(RuntimeError) as exc:
        assert_local_dev_db(url)
    assert "batchrite_prod" in str(exc.value)


def test_assert_local_dev_db_rejects_empty_db_name():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/"
    with pytest.raises(RuntimeError):
        assert_local_dev_db(url)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: 5 new failures with `ImportError: cannot import name 'assert_local_dev_db'`.

- [ ] **Step 3: Implement `assert_local_dev_db`**

Append to `backend/app/db/reset.py`:

```python
ALLOWED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1"})
ALLOWED_DB_NAME: str = "batchrite"


def assert_local_dev_db(url: str) -> None:
    """Raise RuntimeError unless ``url`` points at the local dev DB.

    Hard-coded allow-list (``localhost``/``127.0.0.1`` + ``batchrite``) so a
    misconfigured ``DATABASE_URL`` can't wipe a non-local database. Intentional
    non-local resets require editing this constant.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    # path is like "/batchrite" — strip the leading slash
    db_name = parts.path.lstrip("/")
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"Refusing to reset: DATABASE_URL host is {host!r}, "
            f"not in allow-list {sorted(ALLOWED_HOSTS)}."
        )
    if db_name != ALLOWED_DB_NAME:
        raise RuntimeError(
            f"Refusing to reset: DATABASE_URL database is {db_name!r}, "
            f"expected {ALLOWED_DB_NAME!r}."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/reset.py backend/tests/unit/test_reset_db.py
git commit -m "feat(reset-db): localhost/batchrite prod guard [TD-0077]"
```

---

## Task 4: `reset_database` transactional wipe + re-seed

**Files:**
- Modify: `backend/app/db/reset.py`
- Create: `backend/tests/integration/test_reset_db.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_reset_db.py`:

```python
"""Integration tests for reset_database against a real DB.

Uses the conftest ``db_session`` fixture (per-test SAVEPOINT); the outer
rollback undoes everything at teardown so tests don't leak state.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.reset import reset_database
from app.db.seed import (
    ORG_ID,
    ORG_ID_2,
    PROJECT_MAB,
    PROJECT_VACCINE,
    TEAM_DOWNSTREAM,
    TEAM_QA,
    TEAM_UPSTREAM,
    USER_ADMIN,
    USER_DOWNSTREAM_LEAD,
    USER_SCIENTIST1,
    USER_SCIENTIST2,
    USER_UPSTREAM_LEAD,
    USER_VIEWER,
)
from app.models.execution import AuditLog
from app.models.iam import Organization, Team, User
from app.models.library import Document
from app.models.science import Project, Protocol, Run, UnitOpDefinition


@pytest.mark.asyncio
async def test_reset_wipes_user_generated_data(db_session, test_user, test_org, test_project):
    # Seed some user-generated junk across several wipe-target tables.
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        graph={"nodes": [], "edges": []},
        created_by_id=test_user.id,
    )
    db_session.add(protocol)
    await db_session.flush()

    run = Run(
        name="Test Run",
        protocol_id=protocol.id,
        status="DRAFT",
        graph_snapshot={"nodes": [], "edges": []},
        created_by_id=test_user.id,
    )
    db_session.add(run)

    db_session.add(AuditLog(
        user_id=test_user.id,
        action="TEST_ACTION",
        object_type="PROTOCOL",
        object_id=protocol.id,
        details={},
    ))
    await db_session.flush()

    # Precondition: rows exist.
    assert (await db_session.execute(select(Protocol))).scalars().first() is not None
    assert (await db_session.execute(select(Run))).scalars().first() is not None
    assert (await db_session.execute(select(AuditLog))).scalars().first() is not None

    # Act
    await reset_database(db_session)

    # Postcondition: wipe tables empty.
    assert (await db_session.execute(select(Protocol))).scalars().all() == []
    assert (await db_session.execute(select(Run))).scalars().all() == []
    assert (await db_session.execute(select(AuditLog))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


@pytest.mark.asyncio
async def test_reset_populates_seed_baseline(db_session):
    await reset_database(db_session)

    # Users
    user_ids = {
        USER_ADMIN, USER_UPSTREAM_LEAD, USER_DOWNSTREAM_LEAD,
        USER_SCIENTIST1, USER_SCIENTIST2, USER_VIEWER,
    }
    rows = (await db_session.execute(select(User.id))).scalars().all()
    assert user_ids.issubset(set(rows))

    # Orgs
    orgs = (await db_session.execute(select(Organization.id))).scalars().all()
    assert {ORG_ID, ORG_ID_2}.issubset(set(orgs))

    # Teams
    teams = (await db_session.execute(select(Team.id))).scalars().all()
    assert {TEAM_UPSTREAM, TEAM_DOWNSTREAM, TEAM_QA}.issubset(set(teams))

    # Projects
    projects = (await db_session.execute(select(Project.id))).scalars().all()
    assert {PROJECT_MAB, PROJECT_VACCINE}.issubset(set(projects))

    # Unit ops (at least one)
    ops = (await db_session.execute(select(UnitOpDefinition))).scalars().all()
    assert len(ops) >= 1


@pytest.mark.asyncio
async def test_reset_is_idempotent(db_session):
    await reset_database(db_session)
    # Second call must not raise and must leave state stable.
    await reset_database(db_session)

    users = (await db_session.execute(select(User.id))).scalars().all()
    orgs = (await db_session.execute(select(Organization.id))).scalars().all()
    # Exactly the seed counts — running twice didn't duplicate rows.
    assert len([u for u in users if u in {
        USER_ADMIN, USER_UPSTREAM_LEAD, USER_DOWNSTREAM_LEAD,
        USER_SCIENTIST1, USER_SCIENTIST2, USER_VIEWER,
    }]) == 6
    assert len([o for o in orgs if o in {ORG_ID, ORG_ID_2}]) == 2


@pytest.mark.asyncio
async def test_reset_preserves_baseline_ids(db_session):
    await reset_database(db_session)
    before_users = set((await db_session.execute(select(User.id))).scalars().all())
    before_orgs = set((await db_session.execute(select(Organization.id))).scalars().all())
    before_projects = set((await db_session.execute(select(Project.id))).scalars().all())

    # Add a stray Protocol to trigger a wipe cycle.
    proj_id = next(iter(before_projects))
    admin_id = USER_ADMIN
    db_session.add(Protocol(
        name="ephemeral",
        project_id=proj_id,
        graph={"nodes": [], "edges": []},
        created_by_id=admin_id,
    ))
    await db_session.flush()

    await reset_database(db_session)

    after_users = set((await db_session.execute(select(User.id))).scalars().all())
    after_orgs = set((await db_session.execute(select(Organization.id))).scalars().all())
    after_projects = set((await db_session.execute(select(Project.id))).scalars().all())

    # Baseline UUIDs unchanged — no churn on preserve tables.
    assert before_users == after_users
    assert before_orgs == after_orgs
    assert before_projects == after_projects
```

Note: the Protocol/Run/AuditLog constructors above use the model field names as of this ticket. If field names differ, fix the test to match the current model — not the other way around. Verify with:

```bash
grep -n "__tablename__\|Mapped\[" backend/app/models/science.py backend/app/models/execution.py backend/app/models/library.py
```

- [ ] **Step 2: Run tests to verify failure**

From `backend/`:

```bash
pytest tests/integration/test_reset_db.py -v
```

Expected: all four fail with `ImportError: cannot import name 'reset_database'`.

- [ ] **Step 3: Implement `reset_database`**

Append to `backend/app/db/reset.py`:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.seed import (
    seed_org,
    seed_permissions,
    seed_projects,
    seed_teams,
    seed_unit_ops,
    seed_users,
)


async def reset_database(session: AsyncSession) -> None:
    """Wipe ``WIPE_TABLES`` and re-apply the seed baseline.

    The caller is responsible for the transaction — in the CLI path we wrap
    this in ``async with session.begin()`` for atomicity; in tests we call it
    inside the per-test SAVEPOINT.
    """
    tables = ", ".join(WIPE_TABLES)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await seed_users(session)
    await seed_org(session)
    await seed_teams(session)
    await seed_projects(session)
    await seed_permissions(session)
    await seed_unit_ops(session)
```

- [ ] **Step 4: Run integration tests and fix any field-name mismatches**

```bash
pytest tests/integration/test_reset_db.py -v
```

Expected: 4 passed. If a test fails with a `TypeError` or `InvalidRequestError` about a field, inspect the relevant model and fix the test to match real fields — do not change model code.

- [ ] **Step 5: Run the full unit+integration test file to confirm nothing regressed**

```bash
pytest tests/unit/test_reset_db.py tests/integration/test_reset_db.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/reset.py backend/tests/integration/test_reset_db.py
git commit -m "feat(reset-db): transactional wipe + re-seed [TD-0077]"
```

---

## Task 5: `confirm_reset` + `_run()` CLI entry point

**Files:**
- Modify: `backend/app/db/reset.py`

Note: `confirm_reset` and `_run()` are thin glue around already-tested pieces. We test the guard path (non-TTY → False) with a unit test; the actual `_run()` flow is exercised by manual smoke test in Task 7 since it requires stdin.

- [ ] **Step 1: Add failing unit test for the TTY gate**

Append to `backend/tests/unit/test_reset_db.py`:

```python
from unittest.mock import patch

from app.db.reset import confirm_reset


def test_confirm_reset_aborts_when_stdin_not_tty(capsys):
    with patch("sys.stdin") as fake_stdin:
        fake_stdin.isatty.return_value = False
        result = confirm_reset()
    assert result is False
    captured = capsys.readouterr()
    assert "not a TTY" in captured.err or "not a TTY" in captured.out
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/unit/test_reset_db.py::test_confirm_reset_aborts_when_stdin_not_tty -v
```

Expected: fail with `ImportError: cannot import name 'confirm_reset'`.

- [ ] **Step 3: Implement `confirm_reset`, `_run`, and `__main__`**

Append to `backend/app/db/reset.py`:

```python
import asyncio
import sys

from app.core.config import settings
from app.db.session import AsyncSessionLocal


def confirm_reset() -> bool:
    """Print plan + prompt y/N. Return True only on explicit ``y``.

    Auto-aborts when stdin is not a TTY so the script can't be driven by
    ``yes`` or a forgotten pipe.
    """
    if not sys.stdin.isatty():
        print(
            "[reset-db] stdin is not a TTY; aborting to prevent unattended reset.",
            file=sys.stderr,
        )
        return False

    print()
    print(f"Target database: {mask_database_url(settings.database_url)}")
    print()
    print("The following tables will be WIPED (TRUNCATE ... RESTART IDENTITY CASCADE):")
    for table in WIPE_TABLES:
        print(f"  - {table}")
    print()
    print(
        "Preserved/re-seeded: users, organizations, organization_members, teams, "
        "team_members, projects, object_permissions, unit_op_definitions, "
        "ai_provider_configs."
    )
    print()
    answer = input("Proceed? [y/N]: ").strip().lower()
    return answer == "y"


async def _run() -> int:
    try:
        assert_local_dev_db(settings.database_url)
    except RuntimeError as exc:
        print(f"[reset-db] {exc}", file=sys.stderr)
        return 2

    if not confirm_reset():
        print("[reset-db] Aborted. No changes made.")
        return 1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await reset_database(session)
    print("[reset-db] Reset complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
```

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
pytest tests/unit/test_reset_db.py -v
```

Expected: all pass (12 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/reset.py backend/tests/unit/test_reset_db.py
git commit -m "feat(reset-db): confirm_reset + _run CLI entry [TD-0077]"
```

---

## Task 6: Shell wrapper `scripts/reset-db.sh`

**Files:**
- Create: `scripts/reset-db.sh`

- [ ] **Step 1: Create the wrapper**

Write `scripts/reset-db.sh`:

```bash
#!/usr/bin/env bash
# Reset local dev DB: wipe user-generated data and re-seed baseline.
# Guarded to only run against localhost/batchrite by app.db.reset.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root/backend"

if [[ -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

exec python -m app.db.reset
```

- [ ] **Step 2: Mark executable**

```bash
chmod +x scripts/reset-db.sh
```

- [ ] **Step 3: Verify the non-TTY abort path via smoke test**

Pipe `n` through and expect a graceful abort with a non-zero exit code. Because stdin is now a pipe (not a TTY), the script should exit via the `not a TTY` branch with code 1.

```bash
echo n | scripts/reset-db.sh; echo "exit=$?"
```

Expected output contains `stdin is not a TTY` and `exit=1`. No destructive SQL should have run — no `TRUNCATE` in any backend log.

- [ ] **Step 4: Commit**

```bash
git add scripts/reset-db.sh
git commit -m "feat(reset-db): executable shell wrapper [TD-0077]"
```

---

## Task 7: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the command**

Edit the Backend commands block in `CLAUDE.md` (around line 11-19) to add a new line after the `black ... mypy` line:

```diff
 black app tests && isort app tests && mypy app       # lint
+../scripts/reset-db.sh                               # wipe user data, re-seed baseline (local only)
 ```
```

Exact replacement — use `Edit` tool, `old_string`:

```
black app tests && isort app tests && mypy app       # lint
```

`new_string`:

```
black app tests && isort app tests && mypy app       # lint
../scripts/reset-db.sh                               # wipe user data, re-seed baseline (local only)
```

- [ ] **Step 2: End-to-end sanity — run ALL reset-db tests once more**

```bash
pytest tests/unit/test_reset_db.py tests/integration/test_reset_db.py -v
```

Expected: all pass.

- [ ] **Step 3: Lint check**

```bash
black app/db/reset.py tests/unit/test_reset_db.py tests/integration/test_reset_db.py
isort app/db/reset.py tests/unit/test_reset_db.py tests/integration/test_reset_db.py
mypy app/db/reset.py
```

Expected: clean. If `black` or `isort` reformats, restage before committing.

- [ ] **Step 4: Full backend test suite**

```bash
pytest -q
```

Expected: all pass, no regressions in other tests.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md backend/app/db/reset.py backend/tests/unit/test_reset_db.py backend/tests/integration/test_reset_db.py
git commit -m "docs(reset-db): document scripts/reset-db.sh in CLAUDE.md [TD-0077]"
```

---

## Acceptance verification

Before handing back to the user, verify each ticket AC is satisfied:

1. `scripts/reset-db.sh` exists, executable, callable from repo root → `ls -l scripts/reset-db.sh` shows `x` bit.
2. Prints masked DATABASE_URL + db name → covered by `confirm_reset` calling `mask_database_url`. Smoke: run interactively once, observe the output block.
3. Shows wipe list + y/N, default N → `confirm_reset` prints the loop, any input other than `y` returns False.
4. Single-transaction TRUNCATE + reseed → `_run` uses `async with session.begin()` around `reset_database`.
5. Post-run DB matches `app.db.seed` → `test_reset_populates_seed_baseline`.
6. Idempotent on repeat → `test_reset_is_idempotent`.
7. Safe on empty DB → both `test_reset_populates_seed_baseline` and `test_reset_is_idempotent` start from empty session state.
8. Preserve tables untouched → `test_reset_preserves_baseline_ids`.
9. CLAUDE.md mentions it → Task 7.
10. **Extra: prod guard** → `test_assert_local_dev_db_rejects_non_local_host` + `_rejects_wrong_db_name` + `_run` fast-fails.
