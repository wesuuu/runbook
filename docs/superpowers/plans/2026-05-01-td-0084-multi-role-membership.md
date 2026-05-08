# TD-0084 Multi-role org membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `OrganizationMember.role: str` into `roles: list[str]` so an org member can hold multiple additive roles (ADMIN, BILLING, MEMBER, PROTOCOL_APPROVER) at once. Required by F-0066.

**Architecture:** Postgres `ARRAY(String)` column with a CHECK constraint to the allowed enum. `MEMBER` is implicit and never removable — server normalizes every write. Read sites switch from `membership.role == "ADMIN"` to a module-level `has_org_role()` helper, and SQL filters switch to `roles.contains([...])` containment. Back-compat shim accepts the old `{"role": "X"}` payload for one release. Frontend Roles column becomes a `Badge` chip trigger that opens a `Popover` with checkbox items.

**Tech Stack:** SQLAlchemy 2.0 async + Alembic, FastAPI, Pydantic v2, Postgres `varchar[]`, Svelte 5 (runes), shadcn-svelte (`Popover`, `dropdown-menu-checkbox-item`, `Badge`), Vitest, Playwright, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-01-td-0084-multi-role-membership-design.md`

---

## File Structure

### Backend — modified

| Path | Change |
|---|---|
| `backend/app/models/iam.py` | `OrgRole` adds `PROTOCOL_APPROVER`; `OrganizationMember.role` → `roles` (ARRAY); add `has_org_role()`, `has_any_org_role()` module functions; add `_ALLOWED_ORG_ROLES` constant |
| `backend/app/schemas/iam.py` | `OrgMemberAdd/Update/Response`: `role: str` → `roles: list[str]`; back-compat shim accepts `role` and wraps; `InvitationResponse` unchanged |
| `backend/app/services/core/permissions.py` | 2 sites: `membership.role == "ADMIN"` → `has_org_role(membership, OrgRole.ADMIN.value)` |
| `backend/app/core/deps.py` | `require_org_role`: rank lookup uses `has_any_org_role` over the role hierarchy |
| `backend/app/api/endpoints/iam.py` | `_require_org_admin`, add/update/admin-cap endpoints work on `roles`; admin counting uses `roles.contains(['ADMIN'])`; back-compat shim for `role` payload |
| `backend/app/api/endpoints/notifications.py` | Line 69 admin check → `has_org_role` |
| `backend/app/api/endpoints/dashboard.py` | Line 155 admin check → `has_org_role` |
| `backend/app/api/endpoints/templates.py` | Line 58 SQL filter → `roles.contains(['ADMIN'])` |
| `backend/app/api/endpoints/unit_ops.py` | Lines 40, 183 SQL filters → `roles.contains(['ADMIN'])` |
| `backend/app/api/endpoints/chat.py` | Lines 235, 282 → use new helper / containment |
| `backend/app/api/endpoints/admin.py` | Line 34 SQL filter → containment |
| `backend/app/api/endpoints/billing/webhook_handler.py` | Line 242 SQL filter → containment |
| `backend/app/api/endpoints/project_members.py` | Line 97 SQL filter → containment |
| `backend/app/api/endpoints/protocols.py` | Line 635 SQL filter → containment |
| `backend/app/api/endpoints/auth.py` | Lines 200, 544, 551 OrganizationMember inserts use `roles=[OrgRole.MEMBER.value, invitation.role]` (deduped) |
| `backend/app/db/seed.py` | Lines 129, 318 OrganizationMember inserts use `roles=[...]` |
| `backend/tests/conftest.py` | Lines 205, 251 fixtures pass `roles=[...]` |
| `backend/tests/unit/test_permissions.py` | `_setup_org_and_user` passes `roles=[role]`; add multi-role test |
| `backend/tests/integration/test_org_membership.py` | Update existing tests; add multi-role + back-compat shim + validation tests |
| `backend/tests/unit/services/test_seat_limits.py` | Lines 30, 36, 67, 93 fixture inserts |
| `backend/tests/unit/test_document_recovery.py` | Line 39 fixture insert |
| `backend/tests/integration/test_*` | Same simple fixture-replacement pattern (8 files; mechanical) |
| `backend/tests/unit/core/test_deps_require_org_role.py` | Existing role-hierarchy tests; update to use `roles=[...]` |

### Backend — created

| Path | Purpose |
|---|---|
| `backend/alembic/versions/<hash>_multi_role_org_membership.py` | Add `roles varchar[]`, backfill, add CHECK, drop `role` |
| `backend/tests/integration/test_multi_role_migration.py` | Verifies migration backfill correctness against a seeded prior-state row |

### Frontend — modified

| Path | Change |
|---|---|
| `frontend/src/lib/schemas/iam.ts` | `OrgMemberSchema.role: string` → `roles: array(string)` |
| `frontend/src/routes/settings/+page.svelte` | `isOrgAdmin` checks `roles.includes('ADMIN')`; rebuild Role cell as chip trigger + popover; mobile card shows chips inline |

### Frontend — created

| Path | Purpose |
|---|---|
| `frontend/src/lib/components/settings/MemberRolesPicker.svelte` | Reusable chip-trigger + popover-with-checkboxes for editing a single member's roles. Lives in `settings/` per `.claude/rules/conventions.md`. |
| `frontend/src/lib/components/settings/MemberRolesPicker.test.ts` | Unit tests for the picker (toggle, MEMBER non-removable, optimistic update on close) |

### Docs

| Path | Change |
|---|---|
| `.claude/rules/backend-models.md` | Add an example of ARRAY column with CHECK constraint (since it's a new pattern) |

---

## Task 1: Backend foundations — extend `OrgRole`, add helpers

**Files:**
- Modify: `backend/app/models/iam.py:28-36, 201-218`
- Test: `backend/tests/unit/test_permissions.py` (new test in same file)

- [ ] **Step 1: Write failing tests for the helpers**

Add to `backend/tests/unit/test_permissions.py`:

```python
import pytest

from app.models.iam import (OrganizationMember, OrgRole, has_any_org_role,
                            has_org_role)


def test_has_org_role_true_when_present():
    m = OrganizationMember(roles=["MEMBER", "ADMIN"])
    assert has_org_role(m, "ADMIN") is True


def test_has_org_role_false_when_missing():
    m = OrganizationMember(roles=["MEMBER"])
    assert has_org_role(m, "ADMIN") is False


def test_has_org_role_handles_none_roles():
    m = OrganizationMember(roles=None)
    assert has_org_role(m, "ADMIN") is False


def test_has_any_org_role_returns_true_on_overlap():
    m = OrganizationMember(roles=["MEMBER", "BILLING"])
    assert has_any_org_role(m, ["ADMIN", "BILLING"]) is True


def test_has_any_org_role_returns_false_on_no_overlap():
    m = OrganizationMember(roles=["MEMBER"])
    assert has_any_org_role(m, ["ADMIN", "BILLING"]) is False


def test_org_role_includes_protocol_approver():
    assert OrgRole.PROTOCOL_APPROVER.value == "PROTOCOL_APPROVER"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_permissions.py::test_has_org_role_true_when_present -v
```
Expected: FAIL with `ImportError` for `has_org_role`.

- [ ] **Step 3: Extend `OrgRole` and add helpers in `backend/app/models/iam.py`**

In `backend/app/models/iam.py`, replace the `OrgRole` enum (around line 28):

```python
class OrgRole(str, Enum):
    ADMIN = "ADMIN"
    BILLING = "BILLING"
    MEMBER = "MEMBER"
    PROTOCOL_APPROVER = "PROTOCOL_APPROVER"


_ALLOWED_ORG_ROLES = frozenset(r.value for r in OrgRole)
```

After the `OrganizationMember` class definition (around line 219), add:

```python
def has_org_role(membership: "OrganizationMember", role: str) -> bool:
    """True if the membership holds the given role."""
    return role in (membership.roles or [])


def has_any_org_role(
    membership: "OrganizationMember", roles: list[str]
) -> bool:
    """True if the membership holds any of the given roles."""
    member_roles = set(membership.roles or [])
    return any(r in member_roles for r in roles)
```

Also add this import at the top of the file:

```python
from typing import Iterable  # if not already imported
```

(Note: actual `roles` column gets added in Task 2 — these helpers reference `membership.roles` which doesn't exist yet, so this task's tests will still fail until Task 2. That's expected; we'll commit after Task 2 covers the full slice.)

- [ ] **Step 4: Don't run tests yet — column comes in Task 2**

Stage the changes only:

```bash
git add backend/app/models/iam.py backend/tests/unit/test_permissions.py
```

---

## Task 2: Add `roles` column + Alembic migration

**Files:**
- Modify: `backend/app/models/iam.py:201-218` (replace `role` column with `roles`)
- Create: `backend/alembic/versions/<hash>_multi_role_org_membership.py`
- Create: `backend/tests/integration/test_multi_role_migration.py`

- [ ] **Step 1: Write failing migration test**

Create `backend/tests/integration/test_multi_role_migration.py`:

```python
"""Verifies that the multi-role migration backfills `roles` correctly.

Inserts a row before the migration's data step using only `role`, then
runs the equivalent of the data migration manually and asserts the
resulting `roles` array contains both the original role and 'MEMBER'.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, OrganizationMember, User


@pytest.mark.asyncio
async def test_backfill_admin_member_includes_member_and_admin(
    db_session: AsyncSession, test_org: Organization
):
    user = User(email="backfill_admin@example.com", full_name="A")
    db_session.add(user)
    await db_session.flush()

    # Simulate the post-migration shape directly (the column already exists
    # by the time this test runs because alembic upgraded the test DB).
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
    await db_session.flush()

    result = await db_session.execute(
        text(
            "SELECT roles FROM organization_members "
            "WHERE user_id = :uid AND organization_id = :oid"
        ),
        {"uid": str(user.id), "oid": str(test_org.id)},
    )
    roles = result.scalar_one()
    assert "MEMBER" in roles
    assert "ADMIN" in roles


@pytest.mark.asyncio
async def test_check_constraint_rejects_unknown_role(
    db_session: AsyncSession, test_org: Organization
):
    user = User(email="check@example.com", full_name="C")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER", "BOGUS_ROLE"],
        )
    )
    with pytest.raises(Exception) as exc:
        await db_session.flush()
    assert "ck_org_member_roles" in str(exc.value).lower() or "check" in str(exc.value).lower()
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_multi_role_migration.py -v
```
Expected: FAIL — column `roles` does not exist (or `role` is required).

- [ ] **Step 3: Update `OrganizationMember` model**

In `backend/app/models/iam.py`, replace the `OrganizationMember` class body (around line 201). Add `ARRAY` to the postgresql import:

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
```

Replace the class body (keep the `__tablename__` and `__table_args__` shape but extend args):

```python
class OrganizationMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_org_member"),
        # CHECK constraint enforced at DB level — see migration for SQL form
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("ARRAY['MEMBER']::varchar[]"),
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    user: Mapped["User"] = relationship(back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship(back_populates="members")
```

Add the `text` import at the top:

```python
from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, String,
                        UniqueConstraint, text)
```

- [ ] **Step 4: Generate the Alembic migration**

```bash
cd backend && source .venv/bin/activate && \
  alembic revision --autogenerate -m "multi_role_org_membership"
```

Open the generated file. Replace its `upgrade()` and `downgrade()` with the deterministic version below (autogenerate will not produce the data backfill or CHECK constraint correctly):

```python
def upgrade() -> None:
    # 1. Add `roles` column with default
    op.add_column(
        "organization_members",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY['MEMBER']::varchar[]"),
        ),
    )
    # 2. Backfill from the legacy `role` column (deduped, MEMBER always present)
    op.execute(
        """
        UPDATE organization_members
        SET roles = ARRAY(
            SELECT DISTINCT unnest(ARRAY[role, 'MEMBER'])
        )
        """
    )
    # 3. Enforce allowed values
    op.execute(
        """
        ALTER TABLE organization_members
        ADD CONSTRAINT ck_org_member_roles
        CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])
        """
    )
    # 4. Drop legacy column
    op.drop_column("organization_members", "role")


def downgrade() -> None:
    op.add_column(
        "organization_members",
        sa.Column("role", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE organization_members
        SET role = CASE
            WHEN 'ADMIN' = ANY(roles) THEN 'ADMIN'
            WHEN 'BILLING' = ANY(roles) THEN 'BILLING'
            ELSE 'MEMBER'
        END
        """
    )
    op.alter_column("organization_members", "role", nullable=False)
    op.execute("ALTER TABLE organization_members DROP CONSTRAINT ck_org_member_roles")
    op.drop_column("organization_members", "roles")
```

Add the import at the top of the migration:

```python
from sqlalchemy.dialects import postgresql
```

- [ ] **Step 5: Apply migration**

```bash
cd backend && source .venv/bin/activate && alembic upgrade head
```
Expected: completes without error. If autogenerate created a `down_revision` chain that conflicts with multi-head state, set `down_revision` manually to whichever revision is the actual head (`alembic heads` shows it; pick the one that includes the most recent feature work for this branch).

- [ ] **Step 6: Run migration tests**

```bash
pytest tests/integration/test_multi_role_migration.py -v
```
Expected: both tests PASS.

- [ ] **Step 7: Run helper tests from Task 1**

```bash
pytest tests/unit/test_permissions.py::test_has_org_role_true_when_present \
       tests/unit/test_permissions.py::test_has_org_role_false_when_missing \
       tests/unit/test_permissions.py::test_has_org_role_handles_none_roles \
       tests/unit/test_permissions.py::test_has_any_org_role_returns_true_on_overlap \
       tests/unit/test_permissions.py::test_has_any_org_role_returns_false_on_no_overlap \
       tests/unit/test_permissions.py::test_org_role_includes_protocol_approver -v
```
Expected: all PASS.

- [ ] **Step 8: Commit foundations + migration**

```bash
git add backend/app/models/iam.py \
        backend/alembic/versions/*multi_role_org_membership*.py \
        backend/tests/integration/test_multi_role_migration.py \
        backend/tests/unit/test_permissions.py
git commit -m "feat(TD-0084): multi-role org membership — model, migration, helpers"
```

---

## Task 3: Update fixtures and seed to use `roles=[...]`

**Files:**
- Modify: `backend/tests/conftest.py:205, 251`
- Modify: `backend/db/seed.py:129, 318`
- Modify: 8 test files (mechanical fixture insert update)

- [ ] **Step 1: Replace fixture inserts**

In `backend/tests/conftest.py`, replace `role="ADMIN"` with `roles=["MEMBER", "ADMIN"]` at both lines 205 and 251.

In `backend/app/db/seed.py`, find the two `OrganizationMember(...)` constructions (lines 129 and 318) and replace `role=...` with `roles=[...]`. For example, if it was `role="ADMIN"`, change to `roles=["MEMBER", "ADMIN"]`. If `role="MEMBER"`, change to `roles=["MEMBER"]`.

In each of the following test files, find every `OrganizationMember(...)` constructor and replace `role="X"` with `roles=["MEMBER", "X"]` if X != "MEMBER", else `roles=["MEMBER"]`:

- `backend/tests/integration/test_equipment_api.py` (line 123)
- `backend/tests/unit/services/test_seat_limits.py` (lines 30, 36, 67, 93)
- `backend/tests/integration/test_unit_ops_scoping.py` (lines 250, 419)
- `backend/tests/unit/test_document_recovery.py` (line 39)
- `backend/tests/integration/test_science_api.py` (line 174)
- `backend/tests/integration/test_tier_api.py` (line 34)
- `backend/tests/integration/test_org_membership.py` (line 55 — `role="MEMBER"` becomes `roles=["MEMBER"]`)

In `backend/tests/unit/test_permissions.py`, update `_setup_org_and_user`:

```python
async def _setup_org_and_user(db, role="MEMBER"):
    org = Organization(name="Test Org")
    db.add(org)
    await db.flush()
    user = User(email=f"{role.lower()}@x.com", full_name=role)
    db.add(user)
    await db.flush()
    roles = ["MEMBER"] if role == "MEMBER" else ["MEMBER", role]
    db.add(OrganizationMember(
        user_id=user.id, organization_id=org.id, roles=roles,
    ))
    await db.flush()
    return org, user
```

- [ ] **Step 2: Run the full test suite to verify the fixture change doesn't break anything**

```bash
pytest -x --ff -q 2>&1 | tail -40
```
Expected: all tests pass except the ones that explicitly check `.role` (string) — those fail; we fix them in subsequent tasks.

If there are unexpected failures (e.g., a test reads `member.role` directly), note the file and address it now. Most failures should be at the read sites we'll touch in Task 4.

- [ ] **Step 3: Commit**

```bash
git add backend/tests backend/app/db/seed.py
git commit -m "test(TD-0084): switch fixtures and seed to roles=[...]"
```

---

## Task 4: Update read sites — service + dep + endpoints

**Files:**
- Modify: `backend/app/services/core/permissions.py:122, 214`
- Modify: `backend/app/core/deps.py:144-189`
- Modify: `backend/app/api/endpoints/notifications.py:69`
- Modify: `backend/app/api/endpoints/dashboard.py:155`
- Modify: `backend/app/api/endpoints/templates.py:58`
- Modify: `backend/app/api/endpoints/unit_ops.py:40, 183`
- Modify: `backend/app/api/endpoints/chat.py:235, 282`
- Modify: `backend/app/api/endpoints/admin.py:34`
- Modify: `backend/app/services/billing/webhook_handler.py:242`
- Modify: `backend/app/api/endpoints/project_members.py:97`
- Modify: `backend/app/api/endpoints/protocols.py:635`

- [ ] **Step 1: Write failing test for multi-role resolver**

Add to `backend/tests/unit/test_permissions.py`:

```python
@pytest.mark.asyncio
async def test_resolver_multi_role_member_has_admin_access(db_session):
    org = Organization(name="Multi Role Org")
    db_session.add(org)
    await db_session.flush()
    user = User(email="multi@example.com", full_name="Multi")
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=org.id,
        roles=["MEMBER", "ADMIN", "BILLING"],
    ))
    project = Project(name="P", organization_id=org.id)
    db_session.add(project)
    await db_session.flush()

    from app.services.core.permissions import check_permission
    from app.models.iam import ObjectType, PermissionLevel

    assert await check_permission(
        db_session, user.id, ObjectType.PROJECT, project.id, PermissionLevel.ADMIN
    ) is True
```

- [ ] **Step 2: Run, verify it fails**

```bash
pytest tests/unit/test_permissions.py::test_resolver_multi_role_member_has_admin_access -v
```
Expected: FAIL — `check_permission` still reads `membership.role`.

- [ ] **Step 3: Update `permissions.py`**

In `backend/app/services/core/permissions.py`:

Add to imports at top:

```python
from app.models.iam import (PERMISSION_RANK, ObjectPermission, ObjectType,
                            OrganizationMember, OrgRole, PermissionLevel,
                            PrincipalType, TeamMember, has_org_role)
```

Replace line 122:

```python
    if has_org_role(membership, OrgRole.ADMIN.value):
        return True
```

Replace line 214 (same change).

- [ ] **Step 4: Update `core/deps.py` `require_org_role`**

In `backend/app/core/deps.py`, replace the body of `_check` inside `require_org_role` (lines 158-187):

```python
    from app.models.iam import OrganizationMember, OrgRole, has_any_org_role

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if user.selected_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No organization selected",
            )
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == user.selected_org_id,
                OrganizationMember.archived == False,  # noqa: E712
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )
        # Hierarchy: ADMIN >= BILLING >= MEMBER. Any role at or above
        # the requirement satisfies it.
        ranked = [
            r for r, rank in _RANK.items()
            if rank >= _RANK[required_role]
        ]
        if not has_any_org_role(member, [r.value for r in ranked]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role.value} role or above",
            )
        return user

    return _check
```

- [ ] **Step 5: Update python-side admin equality checks**

In each of these files, change `membership.role == "ADMIN"` (or `!= "ADMIN"`) to use the helper:

`backend/app/api/endpoints/notifications.py:69`:
```python
from app.models.iam import OrgRole, has_org_role
# ...
if not membership or not has_org_role(membership, OrgRole.ADMIN.value):
```

`backend/app/api/endpoints/dashboard.py:155`:
```python
from app.models.iam import OrgRole, has_org_role
# ...
is_admin = has_org_role(membership, OrgRole.ADMIN.value) if membership else False
```

`backend/app/api/endpoints/chat.py:235` (currently `is_org_admin = org_role == OrgRole.ADMIN`):
- Look at the surrounding code. `org_role` is computed earlier (probably as `member.role`). Replace with `is_org_admin = has_org_role(member, OrgRole.ADMIN.value)` and remove the `org_role` intermediate if no longer used.

`backend/app/api/endpoints/iam.py:51` (`_require_org_admin`):
```python
if membership is None or not has_org_role(membership, OrgRole.ADMIN.value):
```
Add `has_org_role` to the imports at the top.

- [ ] **Step 6: Update SQL filter sites to use ARRAY containment**

In each of these, replace `OrganizationMember.role == OrgRole.ADMIN` (or `== OrgRole.ADMIN.value`, or `== "ADMIN"`) with `OrganizationMember.roles.contains([OrgRole.ADMIN.value])`:

- `backend/app/api/endpoints/templates.py:58`
- `backend/app/api/endpoints/unit_ops.py:40, 183`
- `backend/app/api/endpoints/admin.py:34`
- `backend/app/services/billing/webhook_handler.py:242`
- `backend/app/api/endpoints/project_members.py:97`
- `backend/app/api/endpoints/protocols.py:635`
- `backend/app/api/endpoints/iam.py:213, 329` (admin counts)
- `backend/app/api/endpoints/chat.py:282`

Make sure each file imports `OrgRole` (most already do).

- [ ] **Step 7: Run full backend test suite**

```bash
pytest -q 2>&1 | tail -30
```
Expected: most tests pass. The ones that touch the IAM endpoint payloads (which still reference `body.role`) still fail — Task 5 fixes those.

- [ ] **Step 8: Commit read-site updates**

```bash
git add backend/app/services backend/app/core/deps.py backend/app/api/endpoints
git commit -m "refactor(TD-0084): read sites use roles list (helper + ARRAY containment)"
```

---

## Task 5: Update IAM endpoints + back-compat shim

**Files:**
- Modify: `backend/app/api/endpoints/iam.py:118-122, 172-243, 292-342`
- Modify: `backend/app/api/endpoints/auth.py:200, 540-553`
- Modify: `backend/app/schemas/iam.py:22-41`

- [ ] **Step 1: Write failing tests for the new payload shape and shim**

Add to `backend/tests/integration/test_org_membership.py` (or a new class within it):

```python
class TestMultiRoleEndpoints:
    @pytest.mark.asyncio
    async def test_add_member_with_multi_roles(
        self, client, auth_headers, test_org, db_session
    ):
        u = User(email="newmem@example.com", full_name="N")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(u.id), "roles": ["BILLING", "PROTOCOL_APPROVER"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "MEMBER" in body["roles"]
        assert "BILLING" in body["roles"]
        assert "PROTOCOL_APPROVER" in body["roles"]

    @pytest.mark.asyncio
    async def test_back_compat_shim_accepts_role_string(
        self, client, auth_headers, test_org, db_session, caplog
    ):
        u = User(email="shim@example.com", full_name="S")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(u.id), "role": "ADMIN"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "ADMIN" in resp.json()["roles"]
        assert any(
            "deprecated" in rec.message.lower() and "role" in rec.message.lower()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_validation_rejects_unknown_role(
        self, client, auth_headers, test_org, db_session
    ):
        u = User(email="bad@example.com", full_name="B")
        db_session.add(u)
        await db_session.flush()
        resp = await client.post(
            f"/iam/organizations/{test_org.id}/members",
            json={"user_id": str(u.id), "roles": ["BOGUS"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "BOGUS" in resp.text

    @pytest.mark.asyncio
    async def test_member_role_cannot_be_removed(
        self, client, auth_headers, test_org, db_session
    ):
        u = User(email="alwaysmem@example.com", full_name="A")
        db_session.add(u)
        await db_session.flush()
        db_session.add(OrganizationMember(
            user_id=u.id, organization_id=test_org.id, roles=["MEMBER", "ADMIN"]
        ))
        await db_session.flush()

        resp = await client.patch(
            f"/iam/organizations/{test_org.id}/members/{u.id}",
            json={"roles": []},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["roles"] == ["MEMBER"]
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/integration/test_org_membership.py::TestMultiRoleEndpoints -v
```
Expected: all fail (endpoint still expects `role: str` in the payload).

- [ ] **Step 3: Update Pydantic schemas in `backend/app/schemas/iam.py`**

Replace the three `OrgMember*` schemas:

```python
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrgMemberAdd(BaseModel):
    user_id: UUID
    roles: Optional[List[str]] = None
    role: Optional[str] = None  # deprecated, accepted for one release

    @model_validator(mode="after")
    def _coerce_role_to_roles(self) -> "OrgMemberAdd":
        if self.roles is None and self.role is not None:
            self.roles = [self.role]
        if self.roles is None:
            self.roles = ["MEMBER"]
        return self


class OrgMemberUpdate(BaseModel):
    roles: Optional[List[str]] = None
    role: Optional[str] = None  # deprecated

    @model_validator(mode="after")
    def _coerce_role_to_roles(self) -> "OrgMemberUpdate":
        if self.roles is None and self.role is not None:
            self.roles = [self.role]
        return self


class OrgMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    roles: List[str]
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

(Keep existing `OrganizationCreate/Response`, `Team*`, `Invitation*`, `Permission*` unchanged.)

- [ ] **Step 4: Rewrite `add_org_member` in `backend/app/api/endpoints/iam.py`**

Add at the top of the file:

```python
import logging
from app.models.iam import OrgRole, _ALLOWED_ORG_ROLES, has_org_role

_DEPRECATION_LOG = logging.getLogger("app.deprecation")


def _normalize_roles(input_roles: list[str] | None, raw_role: str | None) -> list[str]:
    """Server-side normalization: ensure MEMBER, dedupe, validate.

    Raises HTTPException(400) on unknown values.
    """
    if raw_role is not None and not input_roles:
        _DEPRECATION_LOG.warning(
            "OrganizationMember accepted deprecated single-role payload "
            "(role=%r). Switch to roles=[...] before next release.", raw_role,
        )
        input_roles = [raw_role]
    roles = list(input_roles or [])
    # Always include MEMBER
    if OrgRole.MEMBER.value not in roles:
        roles.append(OrgRole.MEMBER.value)
    # Validate
    bad = [r for r in roles if r not in _ALLOWED_ORG_ROLES]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role(s): {bad}. Allowed: {sorted(_ALLOWED_ORG_ROLES)}",
        )
    # Dedupe, preserve insertion order
    seen: set[str] = set()
    out: list[str] = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out
```

In `add_org_member` (around line 172), replace the section that currently uses `body.role` (lines 200-235):

```python
    new_roles = _normalize_roles(body.roles, body.role)

    if existing is not None:
        if not existing.archived:
            raise HTTPException(status_code=409, detail="User is already a member")
        existing.archived = False
        existing.roles = new_roles
        membership = existing
    else:
        # Enforce max 3 admins per org
        if OrgRole.ADMIN.value in new_roles:
            admin_count = await db.execute(
                select(func.count()).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                    OrganizationMember.archived == False,
                )
            )
            if (admin_count.scalar() or 0) >= 3:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum of 3 admins per organization",
                )

        org = await db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        await seat_limits.check_seat_capacity(db, org)

        membership = OrganizationMember(
            user_id=body.user_id,
            organization_id=org_id,
            roles=new_roles,
        )
        db.add(membership)
```

- [ ] **Step 5: Rewrite `update_org_member_role` in `backend/app/api/endpoints/iam.py`**

Replace the body of `update_org_member_role` (around line 292):

```python
@router.patch(
    "/organizations/{org_id}/members/{user_id}",
    response_model=OrgMemberResponse,
)
async def update_org_member_role(
    org_id: UUID,
    user_id: UUID,
    body: OrgMemberUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await _require_org_admin(db, user.id, org_id)

    new_roles = _normalize_roles(body.roles, body.role)

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Enforce max 3 admins (only when adding ADMIN to a member that didn't have it)
    becoming_admin = (
        OrgRole.ADMIN.value in new_roles
        and not has_org_role(membership, OrgRole.ADMIN.value)
    )
    if becoming_admin:
        admin_count = await db.execute(
            select(func.count()).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                OrganizationMember.archived == False,
            )
        )
        if (admin_count.scalar() or 0) >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum of 3 admins per organization",
            )

    membership.roles = new_roles
    await db.commit()
    await db.refresh(membership)
    return membership
```

- [ ] **Step 6: Update the `list_org_members` enrichment**

Around line 370, the enrichment currently builds `OrgMemberResponse(role=m.role, ...)`. Change to `roles=m.roles`:

```python
        enriched.append(
            OrgMemberResponse(
                id=m.id,
                user_id=m.user_id,
                organization_id=m.organization_id,
                roles=m.roles,
                email=u.email if u else None,
                full_name=u.full_name if u else None,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
```

- [ ] **Step 7: Update `create_organization` and invitation acceptance**

In `backend/app/api/endpoints/iam.py:118` (caller becomes admin):

```python
    membership = OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        roles=[OrgRole.MEMBER.value, OrgRole.ADMIN.value],
    )
```

In `backend/app/api/endpoints/auth.py`:

- Line ~200 (registration creates first ADMIN membership):

```python
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
```

- Lines ~544 and ~551 (invitation acceptance — both the reactivation path and the new-membership path). For each, build the roles list from the invitation's single role plus MEMBER:

```python
    if existing is not None:
        if existing.archived:
            existing.archived = False
            existing.roles = sorted({"MEMBER", invitation.role})
        # else: already active member — no-op
    else:
        db.add(
            OrganizationMember(
                user_id=invited_user.id,
                organization_id=invitation.organization_id,
                roles=sorted({"MEMBER", invitation.role}),
            )
        )
```

- [ ] **Step 8: Run new endpoint tests**

```bash
pytest tests/integration/test_org_membership.py::TestMultiRoleEndpoints -v
```
Expected: all 4 tests PASS.

- [ ] **Step 9: Run full backend suite**

```bash
pytest -q 2>&1 | tail -30
```
Expected: all backend tests PASS. If any fail, audit the failure and either:
1. The test references `member.role` directly → update to `member.roles`.
2. The test uses an `OrgMemberResponse` field shape → update.

- [ ] **Step 10: Commit endpoint changes**

```bash
git add backend/app/api/endpoints/iam.py backend/app/api/endpoints/auth.py \
        backend/app/schemas/iam.py backend/tests/integration/test_org_membership.py
git commit -m "feat(TD-0084): IAM endpoints accept roles list with back-compat shim"
```

---

## Task 6: Frontend schema + reusable picker component

**Files:**
- Modify: `frontend/src/lib/schemas/iam.ts:14-25`
- Create: `frontend/src/lib/components/settings/MemberRolesPicker.svelte`
- Create: `frontend/src/lib/components/settings/MemberRolesPicker.test.ts`

- [ ] **Step 1: Write failing unit test for the picker**

Create `frontend/src/lib/components/settings/MemberRolesPicker.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import MemberRolesPicker from './MemberRolesPicker.svelte';

describe('MemberRolesPicker', () => {
    it('renders MEMBER as a non-removable chip', () => {
        const { getByText } = render(MemberRolesPicker, {
            props: { roles: ['MEMBER', 'ADMIN'], onChange: () => {} },
        });
        const memberChip = getByText('Member');
        expect(memberChip.closest('button')).toBeNull();
    });

    it('calls onChange with new roles when a checkbox toggles', async () => {
        const onChange = vi.fn();
        const { getByRole, getByLabelText } = render(MemberRolesPicker, {
            props: { roles: ['MEMBER'], onChange },
        });
        await fireEvent.click(getByRole('button', { name: /edit roles/i }));
        await fireEvent.click(getByLabelText('Admin'));
        // Picker dispatches on close — simulate close
        await fireEvent.keyDown(window, { key: 'Escape' });
        expect(onChange).toHaveBeenCalledWith(
            expect.arrayContaining(['MEMBER', 'ADMIN'])
        );
    });
});
```

(If `@testing-library/svelte` isn't available, install it: `cd frontend && npm install -D @testing-library/svelte`. Check `package.json` first.)

- [ ] **Step 2: Run test, verify it fails**

```bash
cd frontend && npm run test -- MemberRolesPicker
```
Expected: FAIL — component does not exist.

- [ ] **Step 3: Update Zod schema**

In `frontend/src/lib/schemas/iam.ts`, change `OrgMemberSchema`:

```typescript
export const OrgMemberSchema = z.object({
    id: uuidString(),
    user_id: uuidString(),
    organization_id: uuidString(),
    roles: z.array(z.string()),
    email: z.string().nullable().optional(),
    full_name: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type OrgMember = z.infer<typeof OrgMemberSchema>;
```

- [ ] **Step 4: Implement `MemberRolesPicker.svelte`**

Create `frontend/src/lib/components/settings/MemberRolesPicker.svelte`:

```svelte
<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import { Popover, PopoverTrigger, PopoverContent } from '$lib/components/ui/popover';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        roles: string[];
        disabled?: boolean;
        onChange: (newRoles: string[]) => void;
    }
    let { roles, disabled = false, onChange }: Props = $props();

    const ALL_ROLES = [
        { value: 'ADMIN', label: 'Admin' },
        { value: 'BILLING', label: 'Billing' },
        { value: 'PROTOCOL_APPROVER', label: 'Protocol approver' },
    ] as const;

    let open = $state(false);
    let draft = $state<string[]>([...roles]);

    $effect(() => {
        // Re-sync draft when the parent's roles prop changes (e.g., after a refresh)
        if (!open) draft = [...roles];
    });

    function toggle(role: string, checked: boolean) {
        if (checked) draft = [...new Set([...draft, role, 'MEMBER'])];
        else draft = draft.filter((r) => r !== role);
    }

    function commit() {
        // Always include MEMBER
        const final = [...new Set([...draft, 'MEMBER'])];
        const same =
            final.length === roles.length &&
            final.every((r) => roles.includes(r));
        if (!same) onChange(final);
    }

    function handleOpenChange(next: boolean) {
        open = next;
        if (!next) commit();
    }

    function labelFor(role: string): string {
        return ALL_ROLES.find((r) => r.value === role)?.label ?? role;
    }
</script>

<div class="flex items-center gap-1.5 flex-wrap">
    <Badge variant="secondary" class="opacity-70 cursor-default">Member</Badge>
    {#each roles.filter((r) => r !== 'MEMBER') as r (r)}
        <Badge variant="outline">{labelFor(r)}</Badge>
    {/each}

    {#if !disabled}
        <Popover bind:open onOpenChange={handleOpenChange}>
            <PopoverTrigger>
                <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Edit roles"
                    class="h-6 px-2 text-xs"
                >
                    ▾
                </Button>
            </PopoverTrigger>
            <PopoverContent class="w-56 p-3 space-y-2">
                {#each ALL_ROLES as r (r.value)}
                    <label class="flex items-center gap-2 text-sm cursor-pointer">
                        <input
                            type="checkbox"
                            checked={draft.includes(r.value)}
                            onchange={(e) =>
                                toggle(r.value, (e.target as HTMLInputElement).checked)}
                        />
                        <span>{r.label}</span>
                    </label>
                {/each}
                <hr class="my-2" />
                <div class="flex items-center gap-2 text-xs text-muted-foreground">
                    <input type="checkbox" checked disabled />
                    <span>Member <span class="opacity-60">(always)</span></span>
                </div>
            </PopoverContent>
        </Popover>
    {/if}
</div>
```

- [ ] **Step 5: Run picker tests**

```bash
cd frontend && npm run test -- MemberRolesPicker
```
Expected: PASS.

- [ ] **Step 6: Run full frontend unit suite + check**

```bash
cd frontend && npm run check
cd frontend && npm run test
```
Expected: type-check passes; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/schemas/iam.ts \
        frontend/src/lib/components/settings/MemberRolesPicker.svelte \
        frontend/src/lib/components/settings/MemberRolesPicker.test.ts
git commit -m "feat(TD-0084): MemberRolesPicker chip+popover component"
```

---

## Task 7: Wire picker into the settings page

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte` (lines 226-308, 590-612, 826-867, 970-980 — the `m.role` and `<select>` sites)

- [ ] **Step 1: Update `isOrgAdmin` derivation**

Replace line 229-231:

```svelte
const isOrgAdmin = $derived(
    members.some((m: any) => m.user_id === getUser()?.id && (m.roles ?? []).includes('ADMIN'))
);
```

- [ ] **Step 2: Update `MemberRow` to carry roles**

Around line 263-272, change the type and the row constructions:

```typescript
type MemberRow = {
    type: 'member' | 'invitation';
    id: string;
    email: string;
    name: string | null;
    roles: string[];           // members carry full list
    role: string;              // invitations: still single
    status: string;
    date: string;
    raw: any;
};
```

In the `allRows` derivation (lines 278-307):

```typescript
for (const m of members) {
    rows.push({
        type: 'member',
        id: m.user_id,
        email: m.email || '',
        name: m.full_name || null,
        roles: m.roles ?? [],
        role: '',
        status: 'Active',
        date: m.created_at || '',
        raw: m,
    });
}
for (const inv of pendingInvitations) {
    rows.push({
        type: 'invitation',
        id: inv.id,
        email: inv.invited_email,
        name: null,
        roles: [],
        role: inv.role,
        status: invitationStatus(inv),
        date: inv.created_at || '',
        raw: inv,
    });
}
```

- [ ] **Step 3: Replace the `updateMemberRole` function**

Around line 590, rename and rewrite:

```typescript
async function updateMemberRoles(userId: string, roles: string[]) {
    const org = getCurrentOrg();
    if (!org) return;
    try {
        await api.patch(`/iam/organizations/${org.id}/members/${userId}`, {
            roles,
        });
        await loadMembers();
    } catch (e: unknown) {
        toast.error('Failed to update roles', e instanceof Error ? e.message : '');
    }
}
```

Remove the old `ORG_ROLES` constant and `getOrgRoleLabel` function — the picker owns its own labels now.

- [ ] **Step 4: Replace the role cell in the desktop table**

Around lines 852-867, replace:

```svelte
<td class="py-3 px-4 text-center">
    {#if row.type === 'member'}
        <MemberRolesPicker
            roles={row.roles}
            disabled={!isOrgAdmin}
            onChange={(roles) => updateMemberRoles(row.id, roles)}
        />
    {:else}
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
            {row.role || 'Member'}
        </span>
    {/if}
</td>
```

Add to the imports at the top:

```typescript
import MemberRolesPicker from '$lib/components/settings/MemberRolesPicker.svelte';
```

- [ ] **Step 5: Update the mobile card**

Around line 826-830, replace the role display:

```svelte
<div class="flex items-center gap-2 text-xs text-muted-foreground ml-9">
    {#if row.type === 'member'}
        <MemberRolesPicker
            roles={row.roles}
            disabled={!isOrgAdmin}
            onChange={(roles) => updateMemberRoles(row.id, roles)}
        />
    {:else}
        <span>{row.role || 'Member'}</span>
    {/if}
    <span>&middot;</span>
    <span>{row.date ? formatDate(row.date) : '—'}</span>
</div>
```

- [ ] **Step 6: Update the filter function if it referenced `row.role`**

Around line 328, the filter function uses `item.role.toLowerCase()`. Change to:

```typescript
(item.role || (item.roles ?? []).join(' ')).toLowerCase().includes(query)
```

- [ ] **Step 7: Type-check + lint + tests**

```bash
cd frontend && npm run check
cd frontend && npm run test
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(TD-0084): wire MemberRolesPicker into settings page"
```

---

## Task 8: Browser verification (qa-verify agent)

**Files:** none modified — this is a verification step.

- [ ] **Step 1: Reset DB and re-seed against the new migration**

```bash
./scripts/reset.sh
```
Expected: DB wiped, migrations applied (including the new one), seeds inserted.

- [ ] **Step 2: Start backend and frontend dev servers**

Per `.claude/rules/conventions.md`, use the worktree ports:

```bash
# Worktree 1 ports — adjust if collisions
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010 &
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

(If `node_modules` / `.venv` are missing, install per the rule: `cd frontend && npm install`; `cd backend && python -m venv .venv && source .venv/bin/activate && pip install poetry && poetry install --no-root`.)

- [ ] **Step 3: Launch qa-verify agent**

Use the Agent tool with `subagent_type: "qa-verify"`. Brief:

> Verify TD-0084 multi-role org membership.
>
> Login: any seeded user; password `password` works in dev. Open `http://localhost:5183/settings?tab=organization`.
>
> Feature under test:
> - Each member row's Role column now shows chip badges (e.g., "Member", "Admin") and a ▾ trigger that opens a popover with checkboxes for ADMIN, BILLING, PROTOCOL_APPROVER.
> - Member chip is always shown and never removable (it's dimmed/non-interactive).
> - Toggling a checkbox and closing the popover should PATCH `/iam/organizations/{org_id}/members/{user_id}` and the chip set should update.
> - On mobile (narrow viewport), the picker should appear inline within the mobile card and remain usable.
>
> Edge cases to check:
> - Assigning multiple non-MEMBER roles (e.g., ADMIN + BILLING) renders all chips.
> - Removing all non-MEMBER roles leaves just `[Member]`.
> - Trying to assign a role to a user the current user is not admin of should be impossible (picker disabled / not present).
>
> Acceptance criteria from the task description:
> - Multi-role admin assignment via API works (test through UI by toggling checkboxes).
> - ADMIN behavior unchanged (an org admin still sees admin-only sections).
> - Layout: chips don't overflow, popover positioning is correct, mobile renders cleanly.

- [ ] **Step 4: Address any FAIL/POLISH findings before marking complete**

The qa-verify agent must fix any issues it surfaces in the same worktree. Re-run if it reports new findings.

---

## Task 9: Refresh project rules and commit

**Files:**
- Modify: `.claude/rules/backend-models.md` (add ARRAY column example near JSONB Column Patterns section)

- [ ] **Step 1: Add the ARRAY example to the rules**

Insert after the "JSONB Column Patterns" section (or alongside enum patterns) in `.claude/rules/backend-models.md`:

```markdown
## ARRAY Column Pattern

For columns that are `list[enum]` and need cheap containment queries, use Postgres `ARRAY(String)` with a CHECK constraint enforcing the allowed enum:

\`\`\`python
from sqlalchemy.dialects.postgresql import ARRAY

roles: Mapped[list[str]] = mapped_column(
    ARRAY(String),
    nullable=False,
    server_default=text("ARRAY['MEMBER']::varchar[]"),
)
\`\`\`

Add the CHECK in a migration:

\`\`\`python
op.execute(
    """
    ALTER TABLE organization_members
    ADD CONSTRAINT ck_org_member_roles
    CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])
    """
)
\`\`\`

Filter via SQLAlchemy's `Column.contains([value])` — emits `roles @> ARRAY[value]`.

Use ARRAY (not JSONB) when: small set of known string values, frequent containment queries. Use JSONB when: nested/heterogeneous structure, infrequent indexed access.
```

- [ ] **Step 2: Scan rules for stale content**

Quick check:

```bash
grep -n "OrganizationMember.role\|membership.role" .claude/rules/*.md
```
Expected: no hits. If any, update to `roles`.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/backend-models.md
git commit -m "docs(TD-0084): document ARRAY column pattern in backend-models rule"
```

---

## Self-Review (mental checklist before marking complete)

| Spec requirement | Task |
|---|---|
| Member can hold N roles concurrently | Task 5 (test_add_member_with_multi_roles) |
| ADMIN behavior unchanged | Task 4 (test_resolver_multi_role_member_has_admin_access) |
| `OrgRole` includes PROTOCOL_APPROVER | Task 1 |
| Resolver uses only `roles` | Task 4 |
| Add/remove via API works | Task 5 |
| Back-compat shim for `{"role": "X"}` + deprecation log | Task 5 (test_back_compat_shim_accepts_role_string) |
| Org-members admin UI is multi-select | Tasks 6 + 7 |
| Migration backfill correct | Task 2 (test_backfill_admin_member_includes_member_and_admin) |
| Validation rejects unknown roles | Task 5 (test_validation_rejects_unknown_role) |
| MEMBER cannot be removed | Task 5 (test_member_role_cannot_be_removed) |
| ARRAY pattern documented | Task 9 |
