# F-0066 — Protocol Approval & Digital Signatures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the complete protocol approval & digital signature system end-to-end: schema + IAM + endpoints + run-gate + override-block + edit-lock + SOP/batch templates + frontend UI.

**Architecture:** Two parallel approver tracks (project Protocol Approver via PermissionLevel.APPROVE; org Protocol Approver via OrgRole.PROTOCOL_APPROVER) feed a single approve/reject path. Approval state is persisted via two new tables (`protocol_approval_events`, `protocol_approval_requests`) and surfaced in the protocol sidebar, the run editor (strict-mode gating), generated SOP/batch DOCX (embedded signature), and a dashboard "Pending approvals" card.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic, Svelte 5 (runes) + Vite + TailwindCSS 4 + bits-ui/shadcn-svelte, python-docx for templates.

**Spec:** `docs/superpowers/specs/2026-05-10-f-0066-protocol-approval-design.md` — read first.

**Working dir:** `/home/wesuuu/Code/trellisbio/.claude/worktrees/f-0066-protocol-approval`. All commands assume this CWD; backend commands assume `cd backend && source .venv/bin/activate`.

---

## Phase 0 — Worktree environment setup

The worktree has no `node_modules` or `.venv` yet (per `.claude/rules/conventions.md`).

### Task 0: Bootstrap dependencies

- [ ] **Step 1: Backend venv + install**

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -U pip poetry && poetry install --no-root
```

Expected: poetry resolves and installs all dependencies; no errors.

- [ ] **Step 2: Frontend install**

```bash
cd frontend && npm install
```

Expected: clean install.

- [ ] **Step 3: Apply existing migrations to local DB**

```bash
cd backend && source .venv/bin/activate && alembic upgrade head && alembic heads
```

Expected: ends at a single head; record the revision ID for use as `down_revision` in Task 1.

- [ ] **Step 4: Confirm baseline tests pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/ -x -q 2>&1 | tail -20
```

Expected: green or pre-existing skips only. No regressions baseline established.

---

## Phase 1 — Schema, models, migration

### Task 1: Add columns to Protocol & Run, create event/request tables

**Files:**
- Modify: `backend/app/models/science.py:83-141` (Protocol), `backend/app/models/science.py:143-201` (Run)
- Create: `backend/app/models/science.py` end of file — `ProtocolApprovalEvent`, `ProtocolApprovalRequest`
- Create: `backend/alembic/versions/f0039_protocol_approval.py`
- Test: `backend/tests/unit/test_models_protocol_approval.py`

- [ ] **Step 1: Write failing model-shape test**

```python
# backend/tests/unit/test_models_protocol_approval.py
import uuid
import pytest
from datetime import datetime
from app.models.science import (
    Protocol, Run,
    ProtocolApprovalEvent, ProtocolApprovalRequest,
)


def test_protocol_has_approval_columns():
    p = Protocol(name="x", organization_id=uuid.uuid4())
    # These attribute accesses must not raise
    assert p.requires_approval is False or p.requires_approval is None
    assert hasattr(p, "created_by_id")
    assert hasattr(p, "approved_by_id")
    assert hasattr(p, "approved_at")


def test_run_has_is_strict_column():
    r = Run(name="x", project_id=uuid.uuid4())
    assert r.is_strict is False or r.is_strict is None


def test_event_action_constants():
    e = ProtocolApprovalEvent(
        protocol_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        action="SUBMITTED",
    )
    assert e.action == "SUBMITTED"


def test_request_status_default():
    r = ProtocolApprovalRequest(
        protocol_id=uuid.uuid4(),
        requested_user_id=uuid.uuid4(),
        requested_by_id=uuid.uuid4(),
    )
    # default is OPEN once flushed; before flush, may be None — accept both
    assert r.status in (None, "OPEN")
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_models_protocol_approval.py -x -v
```

Expected: ImportError on `ProtocolApprovalEvent`/`ProtocolApprovalRequest`, then attribute errors after we partly implement.

- [ ] **Step 3: Modify Protocol model — add columns**

In `backend/app/models/science.py`, inside `class Protocol(...)` after `is_tour_sample`:

```python
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

And add corresponding relationships at the bottom of the class:

```python
    created_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[created_by_id]
    )
    approved_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[approved_by_id]
    )
    approval_events: Mapped[List["ProtocolApprovalEvent"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="ProtocolApprovalEvent.created_at.desc()",
    )
    approval_requests: Mapped[List["ProtocolApprovalRequest"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
    )
```

Confirm `from datetime import datetime` and `from sqlalchemy import DateTime` already present (they are; Run model uses TimestampMixin).

- [ ] **Step 4: Modify Run model — add `is_strict`**

Inside `class Run(...)`, after `is_tour_sample`:

```python
    is_strict: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
```

- [ ] **Step 5: Add new model classes at end of `science.py`**

```python
class ProtocolApprovalEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocol_approval_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('SUBMITTED','APPROVED','REJECTED','REVERTED')",
            name="ck_proto_appr_event_action",
        ),
        Index("ix_proto_appr_event_protocol_created", "protocol_id", "created_at"),
    )

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    protocol_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocol_versions.id", ondelete="SET NULL"), nullable=True
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    signature_statement: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    protocol: Mapped["Protocol"] = relationship(back_populates="approval_events")
    actor: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[actor_id]
    )
    protocol_version: Mapped[Optional["ProtocolVersion"]] = relationship()


class ProtocolApprovalRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocol_approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','APPROVED','REJECTED','WITHDRAWN')",
            name="ck_proto_appr_req_status",
        ),
        Index(
            "ix_proto_appr_req_open_unique",
            "protocol_id", "requested_user_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    requested_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="OPEN", server_default="OPEN", nullable=False
    )
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="approval_requests")
    requested_user: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_user_id]
    )
    requested_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_by_id]
    )
```

Add `from sqlalchemy import text` to imports if not present.

- [ ] **Step 6: Generate Alembic migration**

```bash
cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "f-0066 protocol approval"
```

Rename the generated file to `f0039_protocol_approval.py`. Review the autogen output for the columns, tables, indexes, and the partial-unique index. Verify `down_revision` matches the head from Task 0 Step 3.

- [ ] **Step 7: Add v1-creator backfill to migration `upgrade()`**

After the autogenerated table/column ops in `upgrade()`, append:

```python
    # Backfill protocols.created_by_id from v1 ProtocolVersion creator.
    op.execute("""
        UPDATE protocols p
        SET created_by_id = pv.created_by_id
        FROM protocol_versions pv
        WHERE pv.protocol_id = p.id
          AND pv.version_number = (
              SELECT MIN(version_number) FROM protocol_versions WHERE protocol_id = p.id
          )
          AND pv.created_by_id IS NOT NULL
    """)
```

- [ ] **Step 8: Run migration up, verify**

```bash
cd backend && source .venv/bin/activate && alembic upgrade head && python -c "
from sqlalchemy import inspect, create_engine
e = create_engine('postgresql+psycopg2://postgres:postgres@localhost:5432/batchrite')
i = inspect(e)
print('protocols cols:', sorted(c['name'] for c in i.get_columns('protocols') if c['name'] in ('requires_approval','created_by_id','approved_by_id','approved_at')))
print('runs cols:', sorted(c['name'] for c in i.get_columns('runs') if c['name'] == 'is_strict'))
print('event tables:', 'protocol_approval_events' in i.get_table_names(), 'protocol_approval_requests' in i.get_table_names())
"
```

Expected: 4 protocol columns, `is_strict` on runs, both new tables present.

- [ ] **Step 9: Run model test, expect pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_models_protocol_approval.py -x -v
```

Expected: PASS.

- [ ] **Step 10: Test downgrade then re-upgrade**

```bash
cd backend && source .venv/bin/activate && alembic downgrade -1 && alembic upgrade head
```

Expected: clean down + up. No errors.

- [ ] **Step 11: Lint + commit**

```bash
cd backend && black app tests && isort app tests && cd .. && git add backend/app/models/science.py backend/alembic/versions/f0039_protocol_approval.py backend/tests/unit/test_models_protocol_approval.py && git -c commit.gpgsign=false commit -m "feat(f-0066): protocol approval models, columns, and migration"
```

---

## Phase 2 — IAM and project-approver admin lock

### Task 2: Org PROTOCOL_APPROVER permission grant

**Files:**
- Modify: `backend/app/services/core/permissions.py` — `check_permission` (around line 122, after ADMIN bypass)
- Test: `backend/tests/unit/test_permissions_protocol_approver.py`

- [ ] **Step 1: Read the existing check_permission to find insertion point**

```bash
cd backend && grep -n "OrgRole.ADMIN\|has_org_role\|ObjectType.PROTOCOL" app/services/core/permissions.py | head -20
```

Note the line numbers; the patch goes immediately after the ADMIN bypass and before the permissions_enabled implicit-EDIT block.

- [ ] **Step 2: Write failing permission test**

```python
# backend/tests/unit/test_permissions_protocol_approver.py
import uuid
import pytest
from app.models.iam import (
    Organization, OrganizationMember, OrgRole, PermissionLevel, User, ObjectType,
)
from app.models.science import Protocol, Project
from app.services.core.permissions import check_permission


@pytest.mark.asyncio
async def test_org_protocol_approver_can_view_edit_approve_protocol(db_session):
    org = Organization(name="o")
    db_session.add(org)
    await db_session.flush()
    user = User(email="a@b.c", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        organization_id=org.id, user_id=user.id,
        role=OrgRole.MEMBER.value,
        roles=[OrgRole.MEMBER.value, OrgRole.PROTOCOL_APPROVER.value],
    ))
    project = Project(name="p", organization_id=org.id)
    db_session.add(project)
    await db_session.flush()
    proto = Protocol(name="proto", project_id=project.id, requires_approval=True)
    db_session.add(proto)
    await db_session.flush()

    for level in (PermissionLevel.VIEW, PermissionLevel.EDIT, PermissionLevel.APPROVE):
        ok = await check_permission(
            db_session, user_id=user.id,
            object_type=ObjectType.PROTOCOL,
            object_id=proto.id,
            level=level,
        )
        assert ok, f"PROTOCOL_APPROVER should pass {level}"

    not_admin = await check_permission(
        db_session, user_id=user.id,
        object_type=ObjectType.PROTOCOL,
        object_id=proto.id,
        level=PermissionLevel.ADMIN,
    )
    assert not not_admin, "PROTOCOL_APPROVER must NOT grant ADMIN"


@pytest.mark.asyncio
async def test_org_protocol_approver_no_project_access(db_session):
    # Same setup as above (factor a fixture if you prefer)…
    # Then assert check_permission for ObjectType.PROJECT returns False at any level.
    ...
```

(The `db_session` fixture exists in `backend/tests/conftest.py`; mirror its usage from any other unit test that imports it.)

- [ ] **Step 3: Run, expect failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_permissions_protocol_approver.py -x -v
```

Expected: FAIL — current permissions.py does not grant on PROTOCOL_APPROVER.

- [ ] **Step 4: Patch `check_permission`**

In `backend/app/services/core/permissions.py`, immediately after the existing block that bypasses on `has_org_role(membership, OrgRole.ADMIN.value)`:

```python
        # F-0066: Org PROTOCOL_APPROVER grants VIEW/EDIT/APPROVE on protocols
        # (no project access, no ADMIN).
        if (
            obj.object_type == ObjectType.PROTOCOL
            and has_org_role(membership, OrgRole.PROTOCOL_APPROVER.value)
            and level in (PermissionLevel.VIEW, PermissionLevel.EDIT, PermissionLevel.APPROVE)
        ):
            return True
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_permissions_protocol_approver.py -x -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/core/permissions.py backend/tests/unit/test_permissions_protocol_approver.py && git -c commit.gpgsign=false commit -m "feat(f-0066): org PROTOCOL_APPROVER grants VIEW/EDIT/APPROVE on protocols"
```

### Task 3: Lock project /approvers endpoints to project ADMIN

**Files:**
- Modify: `backend/app/api/endpoints/projects.py:420-565`
- Test: `backend/tests/integration/test_project_protocol_approvers_admin_lock.py`

- [ ] **Step 1: Read the existing approvers endpoints to identify their dependency**

```bash
cd backend && sed -n '420,575p' app/api/endpoints/projects.py
```

Note the current `Depends(require_permission(...))` arg — likely `PermissionLevel.EDIT` or similar.

- [ ] **Step 2: Failing test — EDIT user gets 403, ADMIN gets 200**

```python
# backend/tests/integration/test_project_protocol_approvers_admin_lock.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_approvers_requires_admin(
    client: AsyncClient, edit_user_token, project_id
):
    r = await client.get(
        f"/api/v1/projects/{project_id}/approvers",
        headers={"Authorization": f"Bearer {edit_user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_approvers_admin_ok(
    client: AsyncClient, admin_user_token, project_id
):
    r = await client.get(
        f"/api/v1/projects/{project_id}/approvers",
        headers={"Authorization": f"Bearer {admin_user_token}"},
    )
    assert r.status_code == 200
```

(Mirror existing fixtures from `backend/tests/conftest.py` for `client`, tokens, project setup. Where similar tests already exist for other endpoints, copy their fixture wiring.)

- [ ] **Step 3: Run, expect failure (200/200 today)**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_project_protocol_approvers_admin_lock.py -x -v
```

- [ ] **Step 4: Tighten the dependency**

In each of GET/POST/DELETE `/projects/{project_id}/approvers`, change:

```python
permission: None = Depends(require_permission(ObjectType.PROJECT, "project_id", PermissionLevel.EDIT))
```

to:

```python
permission: None = Depends(require_permission(ObjectType.PROJECT, "project_id", PermissionLevel.ADMIN))
```

- [ ] **Step 5: Run test, expect pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_project_protocol_approvers_admin_lock.py -x -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/projects.py backend/tests/integration/test_project_protocol_approvers_admin_lock.py && git -c commit.gpgsign=false commit -m "feat(f-0066): lock project /approvers GET/POST/DELETE to project ADMIN"
```

---

## Phase 3 — Approval state machine endpoints

### Task 4: Approval helper service

**Files:**
- Create: `backend/app/services/approvals/__init__.py`
- Create: `backend/app/services/approvals/events.py`
- Test: covered indirectly by integration tests in later tasks; add a small unit test for the helper itself.

- [ ] **Step 1: Create the helper module**

```python
# backend/app/services/approvals/events.py
"""Helpers for writing approval events + audit log atomically."""
from __future__ import annotations
import uuid
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import (
    Protocol, ProtocolApprovalEvent, ProtocolApprovalRequest, ProtocolVersion,
)
from app.services.audit_log import log_audit  # use whatever helper exists


VALID_ACTIONS = ("SUBMITTED", "APPROVED", "REJECTED", "REVERTED")


async def write_event(
    db: AsyncSession,
    *,
    protocol: Protocol,
    actor_id: Optional[uuid.UUID],
    action: str,
    comment: Optional[str] = None,
    signature_statement: Optional[str] = None,
    protocol_version_id: Optional[uuid.UUID] = None,
) -> ProtocolApprovalEvent:
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid approval action {action!r}")
    event = ProtocolApprovalEvent(
        protocol_id=protocol.id,
        protocol_version_id=protocol_version_id,
        actor_id=actor_id,
        action=action,
        comment=comment,
        signature_statement=signature_statement,
    )
    db.add(event)
    await log_audit(
        db,
        actor_id=actor_id,
        action=f"PROTOCOL_APPROVAL_{action}",
        object_type="PROTOCOL",
        object_id=protocol.id,
        details={"comment": comment, "signature_statement": bool(signature_statement)},
    )
    return event


async def fulfill_open_requests(
    db: AsyncSession,
    *,
    protocol_id: uuid.UUID,
    final_status: str,  # "APPROVED" or "REJECTED" or "WITHDRAWN"
    actor_id: Optional[uuid.UUID],
) -> int:
    from sqlalchemy import select, update
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ProtocolApprovalRequest)
        .where(
            ProtocolApprovalRequest.protocol_id == protocol_id,
            ProtocolApprovalRequest.status == "OPEN",
        )
        .values(status=final_status, fulfilled_at=now, fulfilled_by_id=actor_id)
    )
    return result.rowcount or 0
```

```python
# backend/app/services/approvals/__init__.py
from .events import write_event, fulfill_open_requests, VALID_ACTIONS  # noqa: F401
```

(If `app/services/audit_log.py` is not the actual path, find the existing audit-log helper via `grep -r "def log_audit" backend/app/services/` and import from there.)

- [ ] **Step 2: Quick smoke import**

```bash
cd backend && source .venv/bin/activate && python -c "from app.services.approvals import write_event, fulfill_open_requests; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/approvals/ && git -c commit.gpgsign=false commit -m "feat(f-0066): approvals service helpers"
```

### Task 5: Designation endpoint

**Files:**
- Modify: `backend/app/api/endpoints/protocols.py`
- Modify: `backend/app/schemas/science.py` — add `DesignateApprovalRequest`
- Test: `backend/tests/integration/test_protocol_designate_approval.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_protocol_designate_approval.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_designate_requires_project_setting(client, creator_token, draft_protocol_id):
    # Project setting OFF → 400.
    r = await client.post(
        f"/api/v1/science/protocols/{draft_protocol_id}/designate-approval",
        json={"requires_approval": True},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 400
    assert "require_protocol_approval" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_designate_creator_or_admin_only(client, edit_user_token, draft_protocol_id_setting_on):
    r = await client.post(
        f"/api/v1/science/protocols/{draft_protocol_id_setting_on}/designate-approval",
        json={"requires_approval": True},
        headers={"Authorization": f"Bearer {edit_user_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_designate_creator_flips_flag(client, creator_token, draft_protocol_id_setting_on):
    r = await client.post(
        f"/api/v1/science/protocols/{draft_protocol_id_setting_on}/designate-approval",
        json={"requires_approval": True},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 200
    assert r.json()["requires_approval"] is True


@pytest.mark.asyncio
async def test_designate_blocked_when_not_draft(client, creator_token, pending_protocol_id):
    r = await client.post(
        f"/api/v1/science/protocols/{pending_protocol_id}/designate-approval",
        json={"requires_approval": False},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Add schema**

In `backend/app/schemas/science.py`:

```python
class DesignateApprovalRequest(BaseModel):
    requires_approval: bool
```

- [ ] **Step 3: Add endpoint to `protocols.py`**

```python
from app.schemas.science import DesignateApprovalRequest

@router.post("/protocols/{protocol_id}/designate-approval", response_model=ProtocolResponse)
async def designate_approval(
    protocol_id: UUID,
    body: DesignateApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proto = await get_or_404(db, Protocol, protocol_id)
    project = await get_or_404(db, Project, proto.project_id)

    is_creator = proto.created_by_id == user.id
    is_admin = await check_permission(
        db, user_id=user.id,
        object_type=ObjectType.PROJECT, object_id=project.id,
        level=PermissionLevel.ADMIN,
    )
    if not (is_creator or is_admin):
        raise HTTPException(403, "Only the protocol creator or a project admin can change requires_approval.")

    if proto.status != "DRAFT":
        raise HTTPException(400, "requires_approval can only be changed while status is DRAFT.")

    if body.requires_approval and not (project.settings or {}).get("require_protocol_approval"):
        raise HTTPException(400, "Project setting `require_protocol_approval` must be enabled first.")

    proto.requires_approval = body.requires_approval
    await db.commit()
    await db.refresh(proto)
    return proto
```

(Adjust imports + path-prefix style to match the file's convention.)

- [ ] **Step 4: Test → expect pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_protocol_designate_approval.py -x -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocols.py backend/app/schemas/science.py backend/tests/integration/test_protocol_designate_approval.py && git -c commit.gpgsign=false commit -m "feat(f-0066): designate-approval endpoint with creator/admin gate"
```

### Task 6: Submit-for-approval (rewrite to persist event + requests + eligibility)

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py:217-269`
- Modify: `backend/app/schemas/science.py` — add `SubmitForApprovalRequest`
- Test: `backend/tests/integration/test_protocol_submit_for_approval.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_protocol_submit_for_approval.py
import pytest


@pytest.mark.asyncio
async def test_submit_requires_requires_approval_flag(client, creator_token, draft_protocol_no_flag_id, project_approver_id):
    r = await client.post(
        f"/api/v1/science/protocols/{draft_protocol_no_flag_id}/submit-for-approval",
        json={"requested_user_ids": [str(project_approver_id)]},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 400
    assert "requires_approval" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_rejects_ineligible_users(client, creator_token, draft_designated_protocol_id, plain_user_id):
    r = await client.post(
        f"/api/v1/science/protocols/{draft_designated_protocol_id}/submit-for-approval",
        json={"requested_user_ids": [str(plain_user_id)]},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 400
    assert "approver" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_creates_event_and_requests(
    client, db_session, creator_token,
    draft_designated_protocol_id, project_approver_id,
):
    from app.models.science import ProtocolApprovalEvent, ProtocolApprovalRequest
    from sqlalchemy import select
    r = await client.post(
        f"/api/v1/science/protocols/{draft_designated_protocol_id}/submit-for-approval",
        json={"requested_user_ids": [str(project_approver_id)]},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PENDING_APPROVAL"

    events = (await db_session.execute(
        select(ProtocolApprovalEvent).where(
            ProtocolApprovalEvent.protocol_id == draft_designated_protocol_id
        )
    )).scalars().all()
    assert any(e.action == "SUBMITTED" for e in events)

    reqs = (await db_session.execute(
        select(ProtocolApprovalRequest).where(
            ProtocolApprovalRequest.protocol_id == draft_designated_protocol_id
        )
    )).scalars().all()
    assert len(reqs) == 1
    assert reqs[0].status == "OPEN"
    assert reqs[0].requested_user_id == project_approver_id
```

- [ ] **Step 2: Add schema**

```python
# backend/app/schemas/science.py
from typing import List
from uuid import UUID

class SubmitForApprovalRequest(BaseModel):
    requested_user_ids: List[UUID]
```

- [ ] **Step 3: Rewrite endpoint body**

In `backend/app/api/endpoints/protocol_versions.py:217-269`:

```python
from app.schemas.science import SubmitForApprovalRequest
from app.services.approvals import write_event
from app.models.science import Protocol, ProtocolApprovalRequest
from app.models.iam import OrgRole, PermissionLevel, ObjectType, OrganizationMember, ObjectPermission, User
from sqlalchemy import select

@router.post("/protocols/{protocol_id}/submit-for-approval", response_model=ProtocolResponse)
async def submit_protocol_for_approval(
    protocol_id: UUID,
    body: SubmitForApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _perm = Depends(require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.EDIT)),
):
    proto = await get_or_404(db, Protocol, protocol_id)
    if not proto.requires_approval:
        raise HTTPException(400, "Protocol must be designated requires_approval before submission.")
    if proto.status != "DRAFT":
        raise HTTPException(400, f"Protocol must be DRAFT to submit (current: {proto.status}).")
    if not body.requested_user_ids:
        raise HTTPException(400, "Pick at least one approver.")

    # Eligibility: each requested user must be a project APPROVER on this project's project,
    # OR have org PROTOCOL_APPROVER role in the same org.
    project = await get_or_404(db, Project, proto.project_id)
    eligible = set()
    # Project approvers
    rows = (await db.execute(
        select(ObjectPermission.user_id)
        .where(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project.id,
            ObjectPermission.level == PermissionLevel.APPROVE,
            ObjectPermission.user_id.is_not(None),
        )
    )).scalars().all()
    eligible.update(rows)
    # Org approvers
    org_rows = (await db.execute(
        select(OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.roles.any(OrgRole.PROTOCOL_APPROVER.value),
        )
    )).scalars().all()
    eligible.update(org_rows)

    bad = [u for u in body.requested_user_ids if u not in eligible]
    if bad:
        raise HTTPException(400, f"Some requested users are not eligible approvers: {bad}")

    proto.status = "PENDING_APPROVAL"
    for uid in body.requested_user_ids:
        db.add(ProtocolApprovalRequest(
            protocol_id=proto.id,
            requested_user_id=uid,
            requested_by_id=user.id,
            status="OPEN",
        ))
    await write_event(db, protocol=proto, actor_id=user.id, action="SUBMITTED")

    # Notify each requested user via existing notification service.
    # Use whatever helper exists; e.g.:
    # from app.services.notifications import notify
    # for uid in body.requested_user_ids:
    #     await notify(db, recipient_id=uid, type="PROTOCOL_APPROVAL_REQUESTED",
    #                  payload={"protocol_id": str(proto.id), "name": proto.name})

    await db.commit()
    await db.refresh(proto)
    return proto
```

If the notification helper has a different shape, locate it via `grep -rn "def notify\|def send_notification" backend/app/services/notifications/`.

- [ ] **Step 4: Run test, fix iteratively until pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_protocol_submit_for_approval.py -x -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocol_versions.py backend/app/schemas/science.py backend/tests/integration/test_protocol_submit_for_approval.py && git -c commit.gpgsign=false commit -m "feat(f-0066): submit-for-approval persists events + requests + eligibility"
```

### Task 7: Approve endpoint rewrite

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py:272-356`
- Modify: `backend/app/schemas/science.py` — `ApproveProtocolRequest`
- Test: `backend/tests/integration/test_protocol_approve.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_protocol_approve.py
import pytest


@pytest.mark.asyncio
async def test_approve_writes_event_and_sets_approved_fields(
    client, db_session, project_approver_token, pending_protocol_id, project_approver_user_id,
):
    from app.models.science import Protocol, ProtocolApprovalEvent, ProtocolApprovalRequest
    from sqlalchemy import select

    r = await client.post(
        f"/api/v1/science/protocols/{pending_protocol_id}/approve",
        json={"signature_statement": "I have reviewed."},
        headers={"Authorization": f"Bearer {project_approver_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by_id"] == str(project_approver_user_id)
    assert body["approved_at"] is not None

    events = (await db_session.execute(
        select(ProtocolApprovalEvent).where(
            ProtocolApprovalEvent.protocol_id == pending_protocol_id,
            ProtocolApprovalEvent.action == "APPROVED",
        )
    )).scalars().all()
    assert len(events) == 1
    assert events[0].signature_statement == "I have reviewed."

    open_reqs = (await db_session.execute(
        select(ProtocolApprovalRequest).where(
            ProtocolApprovalRequest.protocol_id == pending_protocol_id,
            ProtocolApprovalRequest.status == "OPEN",
        )
    )).scalars().all()
    assert open_reqs == []


@pytest.mark.asyncio
async def test_org_protocol_approver_can_approve(
    client, db_session, org_approver_token, pending_protocol_id,
):
    r = await client.post(
        f"/api/v1/science/protocols/{pending_protocol_id}/approve",
        json={},
        headers={"Authorization": f"Bearer {org_approver_token}"},
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Add schema**

```python
class ApproveProtocolRequest(BaseModel):
    comment: Optional[str] = None
    signature_statement: Optional[str] = None
```

- [ ] **Step 3: Rewrite endpoint**

```python
from app.services.approvals import write_event, fulfill_open_requests
from datetime import datetime, timezone
from app.schemas.science import ApproveProtocolRequest

@router.post("/protocols/{protocol_id}/approve", response_model=ProtocolResponse)
async def approve_protocol(
    protocol_id: UUID,
    body: ApproveProtocolRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _perm = Depends(require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.APPROVE)),
):
    proto = await get_or_404(db, Protocol, protocol_id)
    if proto.status != "PENDING_APPROVAL":
        raise HTTPException(400, f"Protocol must be PENDING_APPROVAL (current: {proto.status}).")
    proto.status = "APPROVED"
    proto.approved_by_id = user.id
    proto.approved_at = datetime.now(timezone.utc)
    await write_event(
        db, protocol=proto, actor_id=user.id, action="APPROVED",
        comment=body.comment, signature_statement=body.signature_statement,
    )
    await fulfill_open_requests(db, protocol_id=proto.id, final_status="APPROVED", actor_id=user.id)
    # Optionally notify the protocol creator that it was approved.
    await db.commit()
    await db.refresh(proto)
    return proto
```

- [ ] **Step 4: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocol_versions.py backend/app/schemas/science.py backend/tests/integration/test_protocol_approve.py && git -c commit.gpgsign=false commit -m "feat(f-0066): approve persists event, fulfills requests, snapshots approved_by/at"
```

### Task 8: Reject endpoint rewrite

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py:359-400`
- Modify: schema `RejectProtocolRequest`
- Test: `backend/tests/integration/test_protocol_reject.py`

- [ ] **Step 1: Failing test (comment required, status → DRAFT, REJECTED event)**

```python
# backend/tests/integration/test_protocol_reject.py
import pytest

@pytest.mark.asyncio
async def test_reject_requires_comment(client, project_approver_token, pending_protocol_id):
    r = await client.post(
        f"/api/v1/science/protocols/{pending_protocol_id}/reject",
        json={},
        headers={"Authorization": f"Bearer {project_approver_token}"},
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_reject_writes_event_and_resets_status(
    client, db_session, project_approver_token, pending_protocol_id,
):
    from app.models.science import ProtocolApprovalEvent
    from sqlalchemy import select

    r = await client.post(
        f"/api/v1/science/protocols/{pending_protocol_id}/reject",
        json={"comment": "Missing safety section."},
        headers={"Authorization": f"Bearer {project_approver_token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "DRAFT"

    events = (await db_session.execute(
        select(ProtocolApprovalEvent).where(
            ProtocolApprovalEvent.protocol_id == pending_protocol_id,
            ProtocolApprovalEvent.action == "REJECTED",
        )
    )).scalars().all()
    assert len(events) == 1
    assert events[0].comment == "Missing safety section."
```

- [ ] **Step 2: Add schema**

```python
class RejectProtocolRequest(BaseModel):
    comment: str = Field(..., min_length=1)
    signature_statement: Optional[str] = None
```

- [ ] **Step 3: Rewrite endpoint**

```python
@router.post("/protocols/{protocol_id}/reject", response_model=ProtocolResponse)
async def reject_protocol(
    protocol_id: UUID,
    body: RejectProtocolRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _perm = Depends(require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.APPROVE)),
):
    proto = await get_or_404(db, Protocol, protocol_id)
    if proto.status != "PENDING_APPROVAL":
        raise HTTPException(400, f"Protocol must be PENDING_APPROVAL (current: {proto.status}).")
    proto.status = "DRAFT"
    await write_event(
        db, protocol=proto, actor_id=user.id, action="REJECTED",
        comment=body.comment, signature_statement=body.signature_statement,
    )
    await fulfill_open_requests(db, protocol_id=proto.id, final_status="REJECTED", actor_id=user.id)
    await db.commit()
    await db.refresh(proto)
    return proto
```

- [ ] **Step 4: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocol_versions.py backend/app/schemas/science.py backend/tests/integration/test_protocol_reject.py && git -c commit.gpgsign=false commit -m "feat(f-0066): reject persists event, requires comment, fulfills requests"
```

### Task 9: Approval-history endpoint

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py` (add new route)
- Modify: schema `ProtocolApprovalEventResponse`
- Test: `backend/tests/integration/test_protocol_approval_history.py`

- [ ] **Step 1: Failing test** — fetch history after submit/approve cycle, assert ordering DESC and that `actor.name` is populated.

```python
@pytest.mark.asyncio
async def test_history_returns_events_desc(client, db_session, project_approver_token, approved_protocol_id):
    r = await client.get(
        f"/api/v1/science/protocols/{approved_protocol_id}/approval-history",
        headers={"Authorization": f"Bearer {project_approver_token}"},
    )
    assert r.status_code == 200
    events = r.json()
    assert events[0]["action"] == "APPROVED"
    assert events[-1]["action"] == "SUBMITTED"
    assert events[0]["actor"]["name"]
```

- [ ] **Step 2: Add schemas**

```python
class ApprovalActorRef(BaseModel):
    id: UUID
    name: str
    email: str

class ProtocolVersionRef(BaseModel):
    id: UUID
    version_number: int

class ProtocolApprovalEventResponse(BaseModel):
    id: UUID
    action: str
    comment: Optional[str]
    signature_statement: Optional[str]
    actor: Optional[ApprovalActorRef]
    protocol_version: Optional[ProtocolVersionRef]
    created_at: datetime
```

- [ ] **Step 3: Add endpoint**

```python
from sqlalchemy.orm import selectinload

@router.get(
    "/protocols/{protocol_id}/approval-history",
    response_model=List[ProtocolApprovalEventResponse],
)
async def get_approval_history(
    protocol_id: UUID,
    db: AsyncSession = Depends(get_db),
    _perm = Depends(require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.VIEW)),
):
    rows = (await db.execute(
        select(ProtocolApprovalEvent)
        .where(ProtocolApprovalEvent.protocol_id == protocol_id)
        .options(selectinload(ProtocolApprovalEvent.actor),
                 selectinload(ProtocolApprovalEvent.protocol_version))
        .order_by(ProtocolApprovalEvent.created_at.desc())
    )).scalars().all()
    return [
        {
            "id": e.id,
            "action": e.action,
            "comment": e.comment,
            "signature_statement": e.signature_statement,
            "actor": (
                {"id": e.actor.id, "name": e.actor.name or e.actor.email, "email": e.actor.email}
                if e.actor else None
            ),
            "protocol_version": (
                {"id": e.protocol_version.id, "version_number": e.protocol_version.version_number}
                if e.protocol_version else None
            ),
            "created_at": e.created_at,
        }
        for e in rows
    ]
```

(Use whatever the User model's name field is — likely `full_name`. Adjust accordingly.)

- [ ] **Step 4: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocol_versions.py backend/app/schemas/science.py backend/tests/integration/test_protocol_approval_history.py && git -c commit.gpgsign=false commit -m "feat(f-0066): GET /protocols/{id}/approval-history"
```

### Task 10: Awaiting-my-approval endpoint

**Files:**
- Create: `backend/app/services/approvals/awaiting.py`
- Modify: `backend/app/api/endpoints/protocol_versions.py` (or `protocols.py`) — add new route
- Test: `backend/tests/integration/test_protocol_awaiting_my_approval.py`

- [ ] **Step 1: Failing test** — both code paths populate the list, deduped.

```python
@pytest.mark.asyncio
async def test_open_request_listed_for_user(client, project_approver_token, pending_protocol_id):
    r = await client.get(
        "/api/v1/science/protocols/awaiting-my-approval",
        headers={"Authorization": f"Bearer {project_approver_token}"},
    )
    assert r.status_code == 200
    items = r.json()
    assert any(it["protocol_id"] == str(pending_protocol_id) for it in items)


@pytest.mark.asyncio
async def test_org_approver_sees_all_org_pending(client, org_approver_token, pending_protocol_id_other_project):
    r = await client.get(
        "/api/v1/science/protocols/awaiting-my-approval",
        headers={"Authorization": f"Bearer {org_approver_token}"},
    )
    items = r.json()
    assert any(it["protocol_id"] == str(pending_protocol_id_other_project) for it in items)


@pytest.mark.asyncio
async def test_dedupe(client, hybrid_approver_token, pending_protocol_id):
    """Hybrid user has BOTH a request row AND org PROTOCOL_APPROVER. Should appear once."""
    r = await client.get(
        "/api/v1/science/protocols/awaiting-my-approval",
        headers={"Authorization": f"Bearer {hybrid_approver_token}"},
    )
    items = r.json()
    matches = [it for it in items if it["protocol_id"] == str(pending_protocol_id)]
    assert len(matches) == 1
```

- [ ] **Step 2: Implement query helper**

```python
# backend/app/services/approvals/awaiting.py
from __future__ import annotations
import uuid
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.science import Protocol, Project, ProtocolApprovalRequest, ProtocolApprovalEvent
from app.models.iam import OrganizationMember, OrgRole, User


async def list_awaiting_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    # Org IDs where user is PROTOCOL_APPROVER
    approver_orgs = (await db.execute(
        select(OrganizationMember.organization_id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.roles.any(OrgRole.PROTOCOL_APPROVER.value),
        )
    )).scalars().all()

    # Protocol IDs with an OPEN request for this user
    request_proto_ids = (await db.execute(
        select(ProtocolApprovalRequest.protocol_id)
        .where(
            ProtocolApprovalRequest.requested_user_id == user_id,
            ProtocolApprovalRequest.status == "OPEN",
        )
    )).scalars().all()

    if not approver_orgs and not request_proto_ids:
        return []

    rows = (await db.execute(
        select(Protocol, Project)
        .join(Project, Project.id == Protocol.project_id)
        .where(
            Protocol.status == "PENDING_APPROVAL",
            or_(
                Protocol.id.in_(request_proto_ids) if request_proto_ids else False,
                Protocol.organization_id.in_(approver_orgs) if approver_orgs else False,
                Project.organization_id.in_(approver_orgs) if approver_orgs else False,
            ),
        )
    )).all()

    out = []
    seen = set()
    for proto, project in rows:
        if proto.id in seen:
            continue
        seen.add(proto.id)
        # Most recent SUBMITTED event for submitted_at + submitted_by
        sub = (await db.execute(
            select(ProtocolApprovalEvent)
            .where(
                ProtocolApprovalEvent.protocol_id == proto.id,
                ProtocolApprovalEvent.action == "SUBMITTED",
            )
            .order_by(ProtocolApprovalEvent.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        sub_by = None
        if sub and sub.actor_id:
            actor = await db.get(User, sub.actor_id)
            if actor:
                sub_by = {"id": str(actor.id), "name": actor.full_name or actor.email}
        out.append({
            "protocol_id": str(proto.id),
            "name": proto.name,
            "project_id": str(project.id),
            "project_name": project.name,
            "organization_id": str(project.organization_id),
            "submitted_at": sub.created_at.isoformat() if sub else None,
            "submitted_by": sub_by,
        })
    return out
```

- [ ] **Step 3: Add endpoint**

```python
@router.get("/protocols/awaiting-my-approval")
async def awaiting_my_approval(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.approvals.awaiting import list_awaiting_for_user
    return await list_awaiting_for_user(db, user.id)
```

- [ ] **Step 4: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocol_versions.py backend/app/services/approvals/awaiting.py backend/tests/integration/test_protocol_awaiting_my_approval.py && git -c commit.gpgsign=false commit -m "feat(f-0066): GET /protocols/awaiting-my-approval"
```

### Task 11: ProtocolResponse / RunResponse field additions

**Files:**
- Modify: `backend/app/schemas/science.py` — add fields to `ProtocolResponse`, `RunResponse`
- Modify: `backend/app/api/endpoints/protocol_versions.py` (or wherever ProtocolResponse is built) — derive `latest_signature_statement` and `latest_approval_comment`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_protocol_response_has_approval_fields(client, viewer_token, approved_protocol_id):
    r = await client.get(
        f"/api/v1/science/protocols/{approved_protocol_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    body = r.json()
    for key in ("requires_approval", "created_by_id", "approved_by_id", "approved_at",
                "latest_signature_statement", "latest_approval_comment"):
        assert key in body, key


@pytest.mark.asyncio
async def test_run_response_has_is_strict(client, viewer_token, run_id_strict):
    r = await client.get(
        f"/api/v1/science/runs/{run_id_strict}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    body = r.json()
    assert body["is_strict"] is True
```

- [ ] **Step 2: Add fields to ProtocolResponse / RunResponse pydantic schemas.** Both `latest_*` fields are derived in the endpoint via:

```python
latest_approved = (await db.execute(
    select(ProtocolApprovalEvent)
    .where(ProtocolApprovalEvent.protocol_id == proto.id,
           ProtocolApprovalEvent.action == "APPROVED")
    .order_by(ProtocolApprovalEvent.created_at.desc())
    .limit(1)
)).scalar_one_or_none()
latest_signature_statement = latest_approved.signature_statement if latest_approved else None
latest_approval_comment = latest_approved.comment if latest_approved else None
```

Wire that into wherever the GET protocol endpoint constructs the response. Keep it as a property method on the response model only if cheap; otherwise pass explicitly.

- [ ] **Step 3: Tests pass.** Commit.

```bash
git add backend/app/schemas/science.py backend/app/api/endpoints/ && git -c commit.gpgsign=false commit -m "feat(f-0066): expand ProtocolResponse + RunResponse with approval fields"
```

---

## Phase 4 — Run gate, override block, edit lock, revert

### Task 12: Run-creation gate + is_strict snapshot

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:75-93` (create_run)
- Test: `backend/tests/integration/test_run_approval_gate.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_run_create_blocked_when_protocol_not_approved(
    client, edit_user_token, project_id_setting_on, draft_designated_protocol_id,
):
    r = await client.post(
        "/api/v1/science/runs",
        json={"name": "x", "project_id": str(project_id_setting_on),
              "protocol_id": str(draft_designated_protocol_id)},
        headers={"Authorization": f"Bearer {edit_user_token}"},
    )
    assert r.status_code == 400
    assert "approved" in r.text.lower()


@pytest.mark.asyncio
async def test_run_create_snapshots_is_strict_from_protocol(
    client, edit_user_token, project_id_setting_on, approved_protocol_id,
):
    r = await client.post(
        "/api/v1/science/runs",
        json={"name": "x", "project_id": str(project_id_setting_on),
              "protocol_id": str(approved_protocol_id)},
        headers={"Authorization": f"Bearer {edit_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["is_strict"] is True
```

- [ ] **Step 2: Patch create_run**

Inside the function near where `protocol` is loaded:

```python
project = await get_or_404(db, Project, body.project_id)
project_settings = project.settings or {}
require_approval = project_settings.get("require_protocol_approval", False)
if (
    body.protocol_id is not None
    and require_approval
    and protocol.requires_approval
    and protocol.status != "APPROVED"
):
    raise HTTPException(
        400,
        {"code": "PROTOCOL_NOT_APPROVED",
         "message": "This protocol requires approval before runs can be created."},
    )

# Snapshot strictness independent of project setting (once a protocol opts in,
# its runs are always strict).
is_strict = bool(protocol and protocol.requires_approval)
# … later in the Run() construction:
new_run = Run(..., is_strict=is_strict)
```

- [ ] **Step 3: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_approval_gate.py && git -c commit.gpgsign=false commit -m "feat(f-0066): block run creation on un-approved required protocol; snapshot is_strict"
```

### Task 13: Override-set / Override-edit block when run.is_strict

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:162` (OVERRIDE_SET) and `:543` (OVERRIDE_EDIT)
- Test: `backend/tests/integration/test_run_override_strict_block.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_override_set_403_when_strict(client, runner_token, run_id_strict, node_id):
    r = await client.post(
        f"/api/v1/science/runs/{run_id_strict}/overrides",
        json={"node_id": node_id, "param": "x", "value": 1},
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert r.status_code == 403
    assert "RUN_IS_STRICT" in r.text


@pytest.mark.asyncio
async def test_override_set_ok_when_not_strict(client, runner_token, run_id_loose, node_id):
    r = await client.post(
        f"/api/v1/science/runs/{run_id_loose}/overrides",
        json={"node_id": node_id, "param": "x", "value": 1},
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert r.status_code in (200, 201)
```

- [ ] **Step 2: Patch both endpoints — at the top of each handler:**

```python
run = await get_or_404(db, Run, run_id)
if run.is_strict:
    raise HTTPException(
        403,
        {"code": "RUN_IS_STRICT",
         "message": "Overrides are disabled for runs of approved protocols."},
    )
```

- [ ] **Step 3: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_override_strict_block.py && git -c commit.gpgsign=false commit -m "feat(f-0066): block OVERRIDE_SET/EDIT on strict runs"
```

### Task 14: Edit-lock extension + auto-revert on edit while APPROVED

**Files:**
- Modify: `backend/app/api/endpoints/protocols.py:533-574`
- Test: `backend/tests/integration/test_protocol_edit_lock_revert.py`

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_edit_blocked_for_unauthorized_when_approved(
    client, plain_edit_token, approved_protocol_id,
):
    r = await client.put(
        f"/api/v1/science/protocols/{approved_protocol_id}",
        json={"name": "renamed"},
        headers={"Authorization": f"Bearer {plain_edit_token}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_edit_by_creator_reverts_to_draft(
    client, db_session, creator_token, approved_protocol_id,
):
    from app.models.science import Protocol, ProtocolApprovalEvent
    from sqlalchemy import select

    r = await client.put(
        f"/api/v1/science/protocols/{approved_protocol_id}",
        json={"name": "renamed"},
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert r.status_code == 200
    proto = await db_session.get(Protocol, approved_protocol_id)
    assert proto.status == "DRAFT"
    assert proto.approved_by_id is None and proto.approved_at is None
    assert proto.requires_approval is True

    events = (await db_session.execute(
        select(ProtocolApprovalEvent).where(
            ProtocolApprovalEvent.protocol_id == approved_protocol_id,
            ProtocolApprovalEvent.action == "REVERTED",
        )
    )).scalars().all()
    assert len(events) == 1
```

- [ ] **Step 2: Patch update_protocol**

In the existing handler where `protocol.status == "PENDING_APPROVAL"` is checked:

```python
APPROVED_EDIT_FIELDS = {"name", "description", "graph"}

# Detect whether any restricted field is being changed
changed_fields = set(body.model_dump(exclude_unset=True).keys()) & APPROVED_EDIT_FIELDS

if proto.status == "APPROVED" and changed_fields:
    # Authorized while APPROVED: creator + project ADMIN + project APPROVER + org PROTOCOL_APPROVER
    is_creator = proto.created_by_id == user.id
    is_admin = await check_permission(
        db, user_id=user.id,
        object_type=ObjectType.PROJECT, object_id=proto.project_id,
        level=PermissionLevel.ADMIN,
    )
    is_approver = await check_permission(
        db, user_id=user.id,
        object_type=ObjectType.PROTOCOL, object_id=proto.id,
        level=PermissionLevel.APPROVE,
    )
    if not (is_creator or is_admin or is_approver):
        raise HTTPException(403, "Only the creator, project admin, or an approver can edit an APPROVED protocol.")

    # Auto-revert
    proto.status = "DRAFT"
    proto.approved_by_id = None
    proto.approved_at = None
    await write_event(db, protocol=proto, actor_id=user.id, action="REVERTED")

if proto.status == "PENDING_APPROVAL" and changed_fields:
    raise HTTPException(400, "Cannot edit a protocol while pending approval.")
```

- [ ] **Step 3: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocols.py backend/tests/integration/test_protocol_edit_lock_revert.py && git -c commit.gpgsign=false commit -m "feat(f-0066): edit-lock extends to name/description; auto-revert on APPROVED edit"
```

---

## Phase 5 — Templates and SOP/batch context

### Task 15: Extend `_build_user_signatures` to expose full path

**Files:**
- Modify: `backend/app/api/endpoints/protocol_pdfs.py:35-60`
- Test: `backend/tests/unit/test_user_signatures_helper.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_build_user_signatures_returns_full_path(db_session, user_with_signatures):
    from app.api.endpoints.protocol_pdfs import _build_user_signatures
    sig = await _build_user_signatures(db_session, [user_with_signatures.id])
    entry = sig[user_with_signatures.id]
    assert "signature_full_path" in entry
    assert entry["signature_full_path"].endswith(user_with_signatures.signature_full_path)
```

- [ ] **Step 2: Patch helper** — the existing helper returns `signature_initials_path`; mirror the same logic for `signature_full_path`.

- [ ] **Step 3: Test → pass.** Commit.

```bash
git add backend/app/api/endpoints/protocol_pdfs.py backend/tests/unit/test_user_signatures_helper.py && git -c commit.gpgsign=false commit -m "feat(f-0066): expose signature_full_path in _build_user_signatures"
```

### Task 16: Template-engine KNOWN_VARIABLES + SOP/batch context builders

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:25-48`
- Modify: SOP/batch context builders (per spec, `runs.py:527-593` and the batch-record sibling). Locate via `grep -n "approval_history\|KNOWN_VARIABLES\|build_context\|sop_template" backend/app/api/endpoints/runs.py backend/app/api/endpoints/protocol_pdfs.py`
- Test: `backend/tests/integration/test_protocol_pdf_approval_section.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_sop_context_includes_approval(
    db_session, approved_protocol_with_signature, project_with_setting_on,
):
    from app.api.endpoints.protocol_pdfs import build_sop_context
    ctx = await build_sop_context(db_session, approved_protocol_with_signature.id)
    assert ctx["approval"]["approver_name"]
    assert ctx["approval"]["approved_at"]
    assert ctx["approval"]["signature_image_path"]
    assert ctx["approval"]["protocol_version"] >= 1
    assert ctx["unapproved_warning"] is False
    assert isinstance(ctx["approval_history"], list)


@pytest.mark.asyncio
async def test_sop_context_unapproved_warning(
    db_session, draft_designated_protocol_setting_on,
):
    from app.api.endpoints.protocol_pdfs import build_sop_context
    ctx = await build_sop_context(db_session, draft_designated_protocol_setting_on.id)
    assert ctx["approval"] is None
    assert ctx["unapproved_warning"] is True
```

(Where `build_sop_context` doesn't exist by that name, find/rename the existing context builder. Adjust signature/return as needed.)

- [ ] **Step 2: Add to KNOWN_VARIABLES**

```python
KNOWN_VARIABLES = {
    # … existing …
    "approval", "approval_history", "unapproved_warning",
}
```

- [ ] **Step 3: Patch the SOP/batch context builders**

Where the dict is being built for Jinja2 / docxtpl rendering, add:

```python
from sqlalchemy import select
from app.models.science import ProtocolApprovalEvent

approved_event = (await db.execute(
    select(ProtocolApprovalEvent)
    .where(
        ProtocolApprovalEvent.protocol_id == proto.id,
        ProtocolApprovalEvent.action == "APPROVED",
    )
    .options(selectinload(ProtocolApprovalEvent.actor))
    .order_by(ProtocolApprovalEvent.created_at.desc())
    .limit(1)
)).scalar_one_or_none()

approval = None
if approved_event and approved_event.actor:
    sigs = await _build_user_signatures(db, [approved_event.actor_id])
    sig_path = sigs.get(approved_event.actor_id, {}).get("signature_full_path")
    approval = {
        "approver_name": approved_event.actor.full_name or approved_event.actor.email,
        "approver_email": approved_event.actor.email,
        "approved_at": approved_event.created_at,
        "signature_statement": approved_event.signature_statement,
        "signature_image_path": sig_path,
        "protocol_version": proto.version_number,
    }

history_rows = (await db.execute(
    select(ProtocolApprovalEvent)
    .where(ProtocolApprovalEvent.protocol_id == proto.id)
    .options(selectinload(ProtocolApprovalEvent.actor))
    .order_by(ProtocolApprovalEvent.created_at.desc())
)).scalars().all()
approval_history = [
    {
        "action": e.action,
        "actor_name": (e.actor.full_name or e.actor.email) if e.actor else "(deleted user)",
        "comment": e.comment,
        "signature_statement": e.signature_statement,
        "created_at": e.created_at,
    }
    for e in history_rows
]

project_settings = (project.settings or {})
unapproved_warning = bool(
    project_settings.get("require_protocol_approval")
    and proto.requires_approval
    and proto.status != "APPROVED"
)

context["approval"] = approval
context["approval_history"] = approval_history
context["unapproved_warning"] = unapproved_warning
```

- [ ] **Step 4: Test → pass.** Commit.

```bash
git add backend/app/services/protocols/template_engine.py backend/app/api/endpoints/protocol_pdfs.py backend/app/api/endpoints/runs.py backend/tests/integration/test_protocol_pdf_approval_section.py && git -c commit.gpgsign=false commit -m "feat(f-0066): SOP/batch context includes approval, history, unapproved_warning"
```

### Task 17: Edit default DOCX templates

**Files:**
- Modify: `backend/app/services/documents/templates/sop_default.docx`, `batch_record_default.docx`

DOCX edits use `python-docx`. Best executed as a small script we run once and commit the binary.

- [ ] **Step 1: Write the edit script** at `scripts/inject_approval_section.py`:

```python
"""One-shot edit script: append F-0066 'Approval & Signatures' Jinja block to defaults."""
from pathlib import Path
from docx import Document

TEMPLATES = [
    Path("backend/app/services/documents/templates/sop_default.docx"),
    Path("backend/app/services/documents/templates/batch_record_default.docx"),
]

JINJA_BLOCK = """
{% if unapproved_warning %}
⚠ UNAPPROVED — DRAFT ONLY
{% else %}
{% if approval %}
Approval & Signatures
Approver: {{ approval.approver_name }}
Approved: {{ approval.approved_at }}
Protocol version: {{ approval.protocol_version }}
{% if approval.signature_statement %}Statement: "{{ approval.signature_statement }}"{% endif %}
{% if approval.signature_image_path %}{{ image(approval.signature_image_path, width=1.5*inch) }}{% else %}Signature: {{ approval.approver_name }} (no saved signature){% endif %}
{% endif %}
{% if approval_history %}
Approval History
{% for ev in approval_history %}
- {{ ev.created_at }} — {{ ev.action }} by {{ ev.actor_name }}{% if ev.comment %} — {{ ev.comment }}{% endif %}
{% endfor %}
{% endif %}
{% endif %}
"""

for path in TEMPLATES:
    doc = Document(str(path))
    doc.add_paragraph()
    doc.add_paragraph(JINJA_BLOCK)
    doc.save(str(path))
    print(f"updated {path}")
```

(Adjust the Jinja markers to match whatever helper functions the existing engine exposes — e.g., if templates use `docxtpl`'s `{{ p }}` for paragraphs or `{%p tr ... %}` for tables, mirror that. Look at the existing `roles`/`steps` rendering in the template for reference.)

- [ ] **Step 2: Run the script**

```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/f-0066-protocol-approval && cd backend && source .venv/bin/activate && python ../scripts/inject_approval_section.py
```

- [ ] **Step 3: Render-smoke test**

```python
# backend/tests/integration/test_default_template_render.py
@pytest.mark.asyncio
async def test_default_sop_renders_with_approval(approved_protocol_with_signature, sop_render_helper):
    out = await sop_render_helper(approved_protocol_with_signature.id)
    assert b"Approval" in out  # docx body extract
```

(Mirror existing template-render integration tests for the helper signature.)

- [ ] **Step 4: Test → pass.** Commit (binary diffs go in too).

```bash
git add backend/app/services/documents/templates/sop_default.docx backend/app/services/documents/templates/batch_record_default.docx scripts/inject_approval_section.py backend/tests/integration/test_default_template_render.py && git -c commit.gpgsign=false commit -m "feat(f-0066): default SOP/batch templates render approval section"
```

---

## Phase 6 — Frontend API client + Zod schemas

### Task 18: Frontend API + schemas

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify or create: `frontend/src/lib/schemas/protocol.ts` (or wherever Protocol schemas live)
- Test: `frontend/src/lib/api.test.ts` (or whatever existing test file pattern is)

- [ ] **Step 1: Add Zod schemas + API functions**

```ts
// frontend/src/lib/schemas/protocolApproval.ts
import { z } from 'zod';

export const ProtocolApprovalEventSchema = z.object({
  id: z.string().uuid(),
  action: z.enum(['SUBMITTED', 'APPROVED', 'REJECTED', 'REVERTED']),
  comment: z.string().nullable(),
  signature_statement: z.string().nullable(),
  actor: z.object({
    id: z.string().uuid(),
    name: z.string(),
    email: z.string(),
  }).nullable(),
  protocol_version: z.object({
    id: z.string().uuid(),
    version_number: z.number().int(),
  }).nullable(),
  created_at: z.string(),
});
export type ProtocolApprovalEvent = z.infer<typeof ProtocolApprovalEventSchema>;

export const AwaitingMyApprovalItemSchema = z.object({
  protocol_id: z.string().uuid(),
  name: z.string(),
  project_id: z.string().uuid(),
  project_name: z.string(),
  organization_id: z.string().uuid(),
  submitted_at: z.string().nullable(),
  submitted_by: z.object({ id: z.string(), name: z.string() }).nullable(),
});
export type AwaitingMyApprovalItem = z.infer<typeof AwaitingMyApprovalItemSchema>;
```

In `frontend/src/lib/api.ts`:

```ts
export const designateProtocolApproval = (id: string, requires_approval: boolean) =>
  request(`/api/v1/science/protocols/${id}/designate-approval`, { method: 'POST', body: { requires_approval }});

export const submitProtocolForApproval = (id: string, requested_user_ids: string[]) =>
  request(`/api/v1/science/protocols/${id}/submit-for-approval`, { method: 'POST', body: { requested_user_ids }});

export const approveProtocol = (id: string, payload: { comment?: string; signature_statement?: string }) =>
  request(`/api/v1/science/protocols/${id}/approve`, { method: 'POST', body: payload });

export const rejectProtocol = (id: string, payload: { comment: string; signature_statement?: string }) =>
  request(`/api/v1/science/protocols/${id}/reject`, { method: 'POST', body: payload });

export const getProtocolApprovalHistory = (id: string) =>
  request(`/api/v1/science/protocols/${id}/approval-history`).then(r => r.map(ProtocolApprovalEventSchema.parse));

export const getAwaitingMyApproval = () =>
  request(`/api/v1/science/protocols/awaiting-my-approval`).then(r => r.map(AwaitingMyApprovalItemSchema.parse));
```

(Match the actual `request()` helper conventions in `lib/api.ts`.)

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run check
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/schemas/protocolApproval.ts && git -c commit.gpgsign=false commit -m "feat(f-0066): API client + Zod schemas for approval endpoints"
```

---

## Phase 7 — Frontend new components

Each component below follows the same skeleton: write component → write a vitest → wire it into a parent (deferred to Phase 8). Tests use `@testing-library/svelte` (mirror existing test files in `frontend/src/`).

### Task 19: ApprovalDesignator.svelte

**Files:**
- Create: `frontend/src/lib/components/protocol/ApprovalDesignator.svelte`
- Test: `frontend/src/lib/components/protocol/ApprovalDesignator.test.ts`

- [ ] **Step 1: Component**

```svelte
<script lang="ts">
  import { Switch } from '$lib/components/ui/switch';
  import { Tooltip } from '$lib/components/ui/tooltip';
  import { designateProtocolApproval } from '$lib/api';

  interface Props {
    protocolId: string;
    requiresApproval: boolean;
    status: string;
    canManage: boolean;
    projectSettingEnabled: boolean;
    onChanged: (next: boolean) => void;
  }
  let { protocolId, requiresApproval, status, canManage, projectSettingEnabled, onChanged }: Props = $props();

  let pending = $state(false);
  const disabledReason = $derived(
    !canManage ? 'Only the protocol creator or a project admin can change this.' :
    !projectSettingEnabled ? 'Enable Project Settings → "Require protocol approval" first.' :
    status !== 'DRAFT' ? 'Can only change while status is DRAFT.' : null
  );

  async function toggle() {
    if (disabledReason) return;
    pending = true;
    try {
      const next = !requiresApproval;
      await designateProtocolApproval(protocolId, next);
      onChanged(next);
    } finally { pending = false; }
  }
</script>

<div class="flex items-center gap-2">
  <Switch checked={requiresApproval} disabled={!!disabledReason || pending} on:change={toggle} />
  <span class="text-sm">Requires approval</span>
  {#if disabledReason}
    <Tooltip>{disabledReason}</Tooltip>
  {/if}
</div>
```

- [ ] **Step 2: Test** — assert disabled when status !== DRAFT, when canManage=false, when project setting off; calls API on toggle.

- [ ] **Step 3: Commit.**

```bash
git add frontend/src/lib/components/protocol/ApprovalDesignator.svelte frontend/src/lib/components/protocol/ApprovalDesignator.test.ts && git -c commit.gpgsign=false commit -m "feat(f-0066): ApprovalDesignator component"
```

### Task 20: ApprovalHistory.svelte

**Files:**
- Create: `frontend/src/lib/components/protocol/ApprovalHistory.svelte`
- Test: `frontend/src/lib/components/protocol/ApprovalHistory.test.ts`

- [ ] **Step 1: Component** — collapsible section that lazy-fetches `/approval-history` on first expand. Renders an ordered timeline (newest first) with action badge, actor, date, comment, and statement.

```svelte
<script lang="ts">
  import { getProtocolApprovalHistory } from '$lib/api';
  import type { ProtocolApprovalEvent } from '$lib/schemas/protocolApproval';
  interface Props { protocolId: string; }
  let { protocolId }: Props = $props();
  let open = $state(false);
  let events = $state<ProtocolApprovalEvent[] | null>(null);
  let loading = $state(false);

  async function expand() {
    open = !open;
    if (open && events === null && !loading) {
      loading = true;
      try { events = await getProtocolApprovalHistory(protocolId); }
      finally { loading = false; }
    }
  }
  const colorFor = (a: string) => ({
    SUBMITTED: 'bg-blue-100 text-blue-700',
    APPROVED: 'bg-green-100 text-green-700',
    REJECTED: 'bg-red-100 text-red-700',
    REVERTED: 'bg-amber-100 text-amber-700',
  } as Record<string, string>)[a] ?? 'bg-gray-100';
</script>

<div class="border-t pt-3 mt-3">
  <button class="text-sm font-medium" on:click={expand}>{open ? '▼' : '▶'} Approval history</button>
  {#if open}
    {#if loading}<div class="text-xs">Loading…</div>
    {:else if events && events.length === 0}<div class="text-xs text-gray-500">No events yet.</div>
    {:else if events}
      <ol class="mt-2 space-y-2">
        {#each events as e}
          <li class="text-xs">
            <span class="px-1.5 py-0.5 rounded {colorFor(e.action)}">{e.action}</span>
            <span class="ml-2">{e.actor?.name ?? '—'}</span>
            <span class="ml-2 text-gray-500">{new Date(e.created_at).toLocaleString()}</span>
            {#if e.comment}<div class="mt-1 italic">"{e.comment}"</div>{/if}
            {#if e.signature_statement}<div class="mt-1 text-gray-600">Statement: {e.signature_statement}</div>{/if}
          </li>
        {/each}
      </ol>
    {/if}
  {/if}
</div>
```

- [ ] **Step 2: Test** — first expand fetches; second expand doesn't refetch; empty state and populated state render.

- [ ] **Step 3: Commit.**

### Task 21: ApprovalSignatureDialog.svelte (approve + reject modes)

**Files:**
- Create: `frontend/src/lib/components/protocol/ApprovalSignatureDialog.svelte`
- Test: same dir, `.test.ts`

- [ ] **Step 1: Component** — Dialog (bits-ui), prop `mode: 'approve' | 'reject'`. Approve shows optional `signature_statement` textarea + preview of the user's saved signature image (or cursive name fallback). Reject shows required `comment` textarea + optional statement. On confirm calls the appropriate API and emits `onSuccess`.

- [ ] **Step 2: Test** — submit disabled until comment provided in reject mode; preview src equals user.signature_full_path when present; cursive class applied when not.

- [ ] **Step 3: Commit.**

### Task 22: SubmitForApprovalDialog.svelte

**Files:**
- Create: `frontend/src/lib/components/protocol/SubmitForApprovalDialog.svelte`
- Test: `.test.ts` sibling

- [ ] **Step 1: Component** — Dialog with multi-select. On open, fetches both project approvers (existing `GET /projects/{id}/approvers`) and org PROTOCOL_APPROVER members (existing org member endpoint filtered for that role). Groups under "Project approvers" and "Org approvers" headers. Submit posts `submitProtocolForApproval`.

- [ ] **Step 2: Test** — submit disabled when zero selected; correct grouping; eligibility merge dedupes hybrid users.

- [ ] **Step 3: Commit.**

### Task 23: RevertOnEditConfirmDialog.svelte

**Files:**
- Create: `frontend/src/lib/components/protocol/RevertOnEditConfirmDialog.svelte`
- Test: sibling

- [ ] **Step 1: Component** — Simple confirmation modal. Props: `open: boolean`, `onConfirm`, `onCancel`. Body: "Editing this protocol will revert it from APPROVED to DRAFT and require re-approval before runs can be created. Continue?"

- [ ] **Step 2: Test** — fires onConfirm/onCancel; renders body text.

- [ ] **Step 3: Commit.**

### Task 24: ProjectProtocolApproversCard.svelte

**Files:**
- Create: `frontend/src/lib/components/project/ProjectProtocolApproversCard.svelte`
- Test: sibling

- [ ] **Step 1: Component** — Card titled "Protocol Approvers" inside a project's SettingsTab. Lists project members with `PermissionLevel.APPROVE` via `GET /projects/{id}/approvers`. Add/remove buttons (only visible to project ADMIN — pass `canManage` prop). Wire to existing POST/DELETE.

- [ ] **Step 2: Test** — add/remove flows; canManage=false hides controls.

- [ ] **Step 3: Commit.**

### Task 25: OrgProtocolApproversCard.svelte

**Files:**
- Create: `frontend/src/lib/components/settings/OrgProtocolApproversCard.svelte`
- Test: sibling

- [ ] **Step 1: Component** — Card on the org settings page. Lists members with `PROTOCOL_APPROVER` in their `roles`. Add/remove via existing org-member endpoints (TD-0084). canManage based on org ADMIN.

- [ ] **Step 2: Test** — add/remove flows.

- [ ] **Step 3: Commit.**

### Task 26: PendingApprovalsCard.svelte

**Files:**
- Create: `frontend/src/lib/components/shared/PendingApprovalsCard.svelte`
- Test: sibling

- [ ] **Step 1: Component** — On mount, calls `getAwaitingMyApproval()`. If empty, renders nothing. Otherwise renders a card with a list of `[Project] Protocol Name` rows linking to the protocol editor.

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { getAwaitingMyApproval } from '$lib/api';
  import type { AwaitingMyApprovalItem } from '$lib/schemas/protocolApproval';

  let items = $state<AwaitingMyApprovalItem[]>([]);
  onMount(async () => { items = await getAwaitingMyApproval(); });
</script>

{#if items.length > 0}
  <div class="rounded border bg-white p-4">
    <h3 class="font-semibold mb-2">Pending approvals</h3>
    <ul class="space-y-1">
      {#each items as it}
        <li>
          <a class="text-blue-600 hover:underline" href={`/protocols/${it.protocol_id}`}>
            {it.project_name} · {it.name}
          </a>
          {#if it.submitted_by}
            <span class="text-xs text-gray-500 ml-2">Submitted by {it.submitted_by.name}</span>
          {/if}
        </li>
      {/each}
    </ul>
  </div>
{/if}
```

- [ ] **Step 2: Test** — hides when empty; renders rows when populated.

- [ ] **Step 3: Commit.**

---

## Phase 8 — Frontend wire-up

### Task 27: ProtocolSidebar mods (designator + history + buttons)

**Files:**
- Modify: `frontend/src/lib/components/protocol/ProtocolSidebar.svelte`

- [ ] **Step 1: Mount the new components**

In ProtocolSidebar, near the existing `approvalRequired` indicator:

```svelte
<ApprovalDesignator
  protocolId={protocol.id}
  requiresApproval={protocol.requires_approval}
  status={protocolStatus}
  canManage={canDesignate}
  projectSettingEnabled={projectSettingEnabled}
  onChanged={(next) => { protocol.requires_approval = next; }}
/>

{#if protocolStatus === 'DRAFT' && protocol.requires_approval}
  <Button on:click={() => submitDialogOpen = true}>Submit for Approval</Button>
{/if}
{#if protocolStatus === 'PENDING_APPROVAL' && canApprove}
  <Button on:click={() => sigDialogOpen = 'approve'}>Approve</Button>
  <Button variant="destructive" on:click={() => sigDialogOpen = 'reject'}>Reject</Button>
{/if}

<ApprovalHistory protocolId={protocol.id} />

<SubmitForApprovalDialog
  bind:open={submitDialogOpen}
  protocolId={protocol.id} projectId={protocol.project_id}
  onSuccess={refreshProtocol}
/>
<ApprovalSignatureDialog
  bind:open={sigDialogOpen} protocolId={protocol.id}
  onSuccess={refreshProtocol}
/>
```

(Add the new props to the Props interface; surface `canDesignate`, `canApprove`, `projectSettingEnabled`, `refreshProtocol` from the parent route.)

- [ ] **Step 2: Type-check + visual smoke (deferred to qa-verify task).** Commit.

```bash
git add frontend/src/lib/components/protocol/ProtocolSidebar.svelte && git -c commit.gpgsign=false commit -m "feat(f-0066): mount approval designator, history, and action dialogs in ProtocolSidebar"
```

### Task 28: Protocol editor page — revert-on-edit confirm + capability props

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Add session-level state**

```ts
let revertConfirmedThisSession = $state(false);
let revertConfirmOpen = $state(false);
let pendingEditAction: (() => void) | null = $state(null);

function guardEdit(action: () => void) {
  if (protocol.status === 'APPROVED' && !revertConfirmedThisSession) {
    pendingEditAction = action;
    revertConfirmOpen = true;
    return;
  }
  action();
}
```

Wrap the canvas/onChange handlers and the name/description save handlers with `guardEdit(...)`. Render `<RevertOnEditConfirmDialog bind:open={revertConfirmOpen} onConfirm={() => { revertConfirmedThisSession = true; pendingEditAction?.(); pendingEditAction = null; }} onCancel={() => { pendingEditAction = null; }} />`.

Compute `canDesignate`, `canApprove`, `projectSettingEnabled` from the loaded protocol/project and pass to `ProtocolSidebar`.

- [ ] **Step 2: Type-check.** Commit.

### Task 29: Run-creator + run-editor strict-mode hide

**Files:**
- Modify: `frontend/src/lib/components/run/RunOverridesEditor.svelte`
- Modify: `frontend/src/lib/components/run/RunCreatorUnitOpCard.svelte`
- Modify: `frontend/src/routes/runs/[id]/+page.svelte` (and the run-creator page) — pass `isStrict={run.is_strict}`

- [ ] **Step 1: Add `isStrict: boolean` prop to both components.** When true, RunOverridesEditor renders a banner instead of the editor; RunCreatorUnitOpCard hides the override controls. Vitest assertions added.

- [ ] **Step 2: Pass the prop from the parent route(s).** Type-check. Commit.

### Task 30: ProtocolsTab approval badges + SettingsTab card mount + dashboard

**Files:**
- Modify: `frontend/src/lib/components/project/ProtocolsTab.svelte`
- Modify: `frontend/src/lib/components/project/SettingsTab.svelte`
- Modify: `frontend/src/routes/+page.svelte` (dashboard)

- [ ] **Step 1: ProtocolsTab** — add a "Requires approval" badge column for any protocol with `requires_approval=true`; for APPROVED protocols, show approver name + date in a tooltip on the status badge.

- [ ] **Step 2: SettingsTab** — replace the existing "Approvers" list with `<ProjectProtocolApproversCard>`. Update helper text.

- [ ] **Step 3: Dashboard** — mount `<PendingApprovalsCard />` near the top.

- [ ] **Step 4: Type-check + tests pass.** Commit:

```bash
git add frontend/src/lib/components/project/ProtocolsTab.svelte frontend/src/lib/components/project/SettingsTab.svelte frontend/src/routes/+page.svelte && git -c commit.gpgsign=false commit -m "feat(f-0066): protocols tab badges, settings card, dashboard pending list"
```

### Task 31: Org settings page — mount OrgProtocolApproversCard

**Files:**
- Modify: the org settings route (find via `grep -l "OrganizationMember\|org members" frontend/src/routes/settings/`).

- [ ] **Step 1: Mount the card.** Type-check + tests pass. Commit.

---

## Phase 9 — Final verification + close-out

### Task 32: Backend full sweep + lint

- [ ] **Step 1: Lint**

```bash
cd backend && source .venv/bin/activate && black app tests && isort app tests && mypy app
```

Fix any reported issues.

- [ ] **Step 2: Full test suite**

```bash
cd backend && source .venv/bin/activate && pytest -x -q
```

All green. If anything red is unrelated, investigate before assuming.

- [ ] **Step 3: Coverage on touched files**

```bash
cd backend && source .venv/bin/activate && pytest --cov=app/api/endpoints/protocol_versions --cov=app/api/endpoints/protocols --cov=app/api/endpoints/runs --cov=app/services/approvals --cov=app/services/core/permissions --cov-report=term-missing
```

Target ≥80% on each touched file. Fill in unit tests where coverage falls short.

- [ ] **Step 4: Commit any missing-coverage fixes.**

### Task 33: Frontend full sweep

- [ ] **Step 1: `cd frontend && npm run check`** → fix all type errors.
- [ ] **Step 2: `cd frontend && CI=true npm run test`** → green.
- [ ] **Step 3: Commit.**

### Task 34: Browser verification

- [ ] **Step 1: Reset DB + start servers**

```bash
./scripts/reset.sh
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010 &
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183 &
```

- [ ] **Step 2: Launch qa-verify subagent**

Brief it with: login as admin (`admin@trellis.bio` / any password), navigate to a project, enable `require_protocol_approval` in project settings, create a protocol, designate it requires approval, submit for approval picking the seeded approver, log in as that approver, approve, attempt to create a run (should succeed and is_strict=true), attempt an override (should be blocked), edit the protocol name (should prompt the revert confirmation), confirm the revert, verify status is DRAFT and a REVERTED event is in history, generate the SOP PDF and confirm the Approval & Signatures section renders. Also verify the dashboard "Pending approvals" card shows up for the approver and disappears after approval.

The qa-verify agent must fix any FAIL/POLISH issues it finds.

### Task 35: Refresh project rules + close out

- [ ] **Step 1: Update CLAUDE.md feature flags table** if applicable, and `.claude/rules/conventions.md` if any new convention surfaced.
- [ ] **Step 2: Prune any stale lines per implement-task §6.**
- [ ] **Step 3: Commit doc updates.**
- [ ] **Step 4: Present summary to user, await explicit sign-off, then `clickup_create_task_comment` + `clickup_update_task` to mark complete, then `ExitWorktree action: keep`.**

---

## Self-review

**Spec coverage check (each acceptance criterion → which task):**

- TD-0084 prereq: covered (assumed shipped, verified in Phase 0).
- `Protocol.requires_approval`, `created_by_id`, `approved_by_id`, `approved_at`: Task 1.
- `Run.is_strict`: Task 1.
- `protocol_approval_events` table: Task 1.
- `protocol_approval_requests` table: Task 1.
- v1-creator backfill: Task 1.
- Org PROTOCOL_APPROVER permission grant: Task 2.
- `/projects/{id}/approvers` ADMIN lock: Task 3.
- Designation endpoint with creator/admin gate: Task 5.
- Submit-for-approval (event + requests + eligibility + notify): Task 6.
- Approve (event + signature + fulfill + project|org gate): Task 7.
- Reject (required comment, event, fulfill): Task 8.
- Approval-history endpoint (eager actor, DESC): Task 9.
- Awaiting-my-approval endpoint (both paths, dedupe): Task 10.
- ProtocolResponse / RunResponse field expansion: Task 11.
- Run-creation gate + is_strict snapshot: Task 12.
- Override-set/edit 403 when strict: Task 13.
- Edit-lock extension to name/description, auto-revert + REVERTED event, authorized-editor list: Task 14.
- _build_user_signatures returns signature_full_path: Task 15.
- KNOWN_VARIABLES extended; SOP/batch context with approval, history, unapproved_warning: Task 16.
- Default DOCX templates render Approval & Signatures + cursive fallback: Task 17.
- Frontend API client + Zod: Task 18.
- New components (ApprovalDesignator, ApprovalHistory, ApprovalSignatureDialog, SubmitForApprovalDialog, RevertOnEditConfirmDialog, ProjectProtocolApproversCard, OrgProtocolApproversCard, PendingApprovalsCard): Tasks 19–26.
- ProtocolSidebar wire-up: Task 27.
- Protocol editor revert confirm: Task 28.
- RunOverridesEditor / RunCreatorUnitOpCard `isStrict` hide: Task 29.
- ProtocolsTab badges, SettingsTab card mount, dashboard pending card: Task 30.
- Org settings card mount: Task 31.
- Backend coverage ≥80% on touched files: Task 32.
- Frontend type-check + tests: Task 33.
- Browser e2e: Task 34.
- Rules refresh + close-out: Task 35.

**Placeholder scan:** code blocks present everywhere a step changes code. Tests use mirror-pattern fixtures from `tests/conftest.py` (a fixture-write task is implied inside Tasks 5–14 — the engineer should add fixtures as needed, mirroring existing ones).

**Type consistency:** `requires_approval` (snake_case) in BE; `requiresApproval` (camelCase) in Svelte props per project convention. `is_strict` BE / `isStrict` FE. Endpoint paths consistently `/api/v1/science/protocols/...`. Action enum values uppercase strings throughout.

---

## Out of scope (will not implement here)

- PKI / cert-backed signatures.
- N-of-M / sequential approvals.
- Run-step-level e-sig.
- Removing org approvers with active pending requests (returns 409 from existing org member endpoints).
- Backfilling `requires_approval` for existing protocols.
