# F-0082 Protocol Builder Subagent — Update Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the `protocol_builder` chat subagent so it can update existing DRAFT protocols, manage protocol roles, and modify/elevate custom unit ops — without duplicating logic that already exists inline in endpoints.

**Architecture:** New service modules under `services/protocols/` hold all logic. Existing endpoints with inline logic are refactored to call the new services. Chat tools call the same services. Mutating tools refuse on non-DRAFT protocols. No frontend changes.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, pydantic-ai 1.75+, pytest-asyncio. Chat tools follow the thin-wrapper pattern in `.claude/rules/backend-ai.md`.

**Commands** (run from `backend/` with venv active: `source .venv/bin/activate`):
- Run a single test: `pytest tests/unit/test_X.py::test_Y -v`
- Run a file: `pytest tests/unit/test_X.py -v`
- Run all backend unit tests: `pytest tests/unit/ -v`
- Lint: `black app tests && isort app tests`

---

## Task 1: Extract protocol lookup service

**Files:**
- Create: `backend/app/services/protocols/lookup.py`
- Create: `backend/tests/unit/test_protocols_lookup.py`
- Modify: `backend/app/api/endpoints/protocols.py:335-381` (`get_protocol`, `list_project_protocols`)

- [ ] **Step 1: Write failing test for `list_protocols`**

Add to `backend/tests/unit/test_protocols_lookup.py`:

```python
"""Tests for services/protocols/lookup.py."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            PermissionLevel, PrincipalType, User)
from app.models.science import Project, Protocol, ProtocolRole, ProtocolVersion
from app.services.protocols.lookup import get_protocol_full, list_protocols


@pytest_asyncio.fixture
async def project_with_perm(
    db_session: AsyncSession, test_org: Organization, test_user: User
) -> Project:
    p = Project(name="proj1", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(p)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=p.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_list_protocols_returns_user_visible_protocols(
    db_session: AsyncSession, test_user: User, project_with_perm: Project
):
    p1 = Protocol(name="A", project_id=project_with_perm.id, status="DRAFT", graph={})
    p2 = Protocol(name="B", project_id=project_with_perm.id, status="APPROVED",
                  version_number=2, graph={})
    db_session.add_all([p1, p2])
    await db_session.flush()

    items = await list_protocols(db_session, user_id=test_user.id)
    names = {it.name for it in items}
    assert names == {"A", "B"}
    by_name = {it.name: it for it in items}
    assert by_name["A"].status == "DRAFT"
    assert by_name["B"].status == "APPROVED"
    assert by_name["B"].version_number == 2
    assert by_name["A"].project_name == "proj1"
    assert by_name["A"].has_draft is False


@pytest.mark.asyncio
async def test_list_protocols_marks_has_draft(
    db_session: AsyncSession, test_user: User, project_with_perm: Project
):
    p = Protocol(name="P", project_id=project_with_perm.id,
                 status="APPROVED", version_number=1, graph={})
    db_session.add(p)
    await db_session.flush()
    db_session.add(
        ProtocolVersion(
            protocol_id=p.id, version_number=2, graph={}, name="P", is_draft=True
        )
    )
    await db_session.flush()
    items = await list_protocols(db_session, user_id=test_user.id)
    assert items[0].has_draft is True


@pytest.mark.asyncio
async def test_list_protocols_excludes_unauthorized(
    db_session: AsyncSession, test_user: User
):
    other_org = Organization(name="other", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    other_proj = Project(name="other-proj", organization_id=other_org.id,
                         owner_id=uuid.uuid4())
    db_session.add(other_proj)
    await db_session.flush()
    db_session.add(Protocol(name="Hidden", project_id=other_proj.id,
                            status="DRAFT", graph={}))
    await db_session.flush()
    items = await list_protocols(db_session, user_id=test_user.id)
    assert all(it.name != "Hidden" for it in items)


@pytest.mark.asyncio
async def test_list_protocols_filters_by_project_id(
    db_session: AsyncSession, test_user: User, project_with_perm: Project
):
    other = Project(name="proj2", organization_id=project_with_perm.organization_id,
                    owner_id=test_user.id)
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=other.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    db_session.add_all([
        Protocol(name="A", project_id=project_with_perm.id, status="DRAFT", graph={}),
        Protocol(name="B", project_id=other.id, status="DRAFT", graph={}),
    ])
    await db_session.flush()
    items = await list_protocols(
        db_session, user_id=test_user.id, project_id=project_with_perm.id
    )
    assert {it.name for it in items} == {"A"}


@pytest.mark.asyncio
async def test_get_protocol_full_returns_metadata_graph_roles(
    db_session: AsyncSession, test_user: User, project_with_perm: Project
):
    p = Protocol(name="P", project_id=project_with_perm.id, status="DRAFT",
                 graph={"nodes": [], "edges": []})
    db_session.add(p)
    await db_session.flush()
    db_session.add(ProtocolRole(protocol_id=p.id, name="Operator", sort_order=0))
    await db_session.flush()

    full = await get_protocol_full(db_session, user_id=test_user.id, protocol_id=p.id)
    assert full.name == "P"
    assert full.status == "DRAFT"
    assert full.graph == {"nodes": [], "edges": []}
    assert len(full.roles) == 1
    assert full.roles[0].name == "Operator"


@pytest.mark.asyncio
async def test_get_protocol_full_raises_without_view_perm(
    db_session: AsyncSession, test_user: User
):
    other_org = Organization(name="x", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="x-proj", organization_id=other_org.id, owner_id=uuid.uuid4())
    db_session.add(proj)
    await db_session.flush()
    p = Protocol(name="P", project_id=proj.id, status="DRAFT", graph={})
    db_session.add(p)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await get_protocol_full(db_session, user_id=test_user.id, protocol_id=p.id)


@pytest.mark.asyncio
async def test_get_protocol_full_raises_when_missing(
    db_session: AsyncSession, test_user: User
):
    with pytest.raises(ValueError, match="not found"):
        await get_protocol_full(
            db_session, user_id=test_user.id, protocol_id=uuid.uuid4()
        )
```

- [ ] **Step 2: Run tests to verify they fail with import error**

Run: `pytest tests/unit/test_protocols_lookup.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'app.services.protocols.lookup'`

- [ ] **Step 3: Implement `lookup.py`**

Create `backend/app/services/protocols/lookup.py`:

```python
"""Service: list and read protocols the user can see.

Single canonical implementation called by:
  - api/endpoints/protocols.py::list_project_protocols, get_protocol
  - subagents/protocol_builder/tools.py::list_protocols, get_protocol
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.iam import (ObjectPermission, ObjectType, PermissionLevel,
                            PrincipalType)
from app.models.science import (Project, Protocol, ProtocolRole,
                                ProtocolVersion)
from app.services.core.permissions import check_permission


@dataclass
class ProtocolListItem:
    id: UUID
    name: str
    description: str | None
    project_id: UUID | None
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool


@dataclass
class ProtocolFull:
    id: UUID
    name: str
    description: str | None
    project_id: UUID | None
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool
    graph: dict[str, Any]
    roles: list[ProtocolRole]


async def list_protocols(
    db,
    *,
    user_id: UUID,
    project_id: UUID | None = None,
) -> list[ProtocolListItem]:
    """Return protocols the user can VIEW. Optionally filter to one project."""
    # Subquery: project_ids the user has any permission on (USER principal).
    # Org-admin / role-based access is honored by check_permission below; this
    # subquery is a fast pre-filter to avoid scanning every protocol.
    perm_proj_q = select(ObjectPermission.object_id).where(
        ObjectPermission.principal_type == PrincipalType.USER,
        ObjectPermission.principal_id == user_id,
        ObjectPermission.object_type == ObjectType.PROJECT.value,
    )
    perm_proj_ids = {row[0] for row in (await db.execute(perm_proj_q)).all()}

    has_draft_subq = (
        select(ProtocolVersion.protocol_id)
        .where(ProtocolVersion.is_draft.is_(True))
        .subquery()
    )

    stmt = (
        select(Protocol, Project.name, has_draft_subq.c.protocol_id)
        .join(Project, Protocol.project_id == Project.id)
        .outerjoin(has_draft_subq, has_draft_subq.c.protocol_id == Protocol.id)
        .where(Protocol.project_id.in_(perm_proj_ids) if perm_proj_ids
               else Protocol.id.is_(None))
        .order_by(Protocol.name)
    )
    if project_id is not None:
        stmt = stmt.where(Protocol.project_id == project_id)

    rows = (await db.execute(stmt)).all()
    return [
        ProtocolListItem(
            id=p.id,
            name=p.name,
            description=p.description,
            project_id=p.project_id,
            project_name=proj_name,
            status=p.status,
            version_number=p.version_number,
            has_draft=draft_id is not None,
        )
        for p, proj_name, draft_id in rows
    ]


async def get_protocol_full(
    db, *, user_id: UUID, protocol_id: UUID
) -> ProtocolFull:
    """Return one protocol's full state (metadata, graph, roles).

    Raises ValueError on missing protocol or missing VIEW permission.
    """
    stmt = (
        select(Protocol, Project.name)
        .outerjoin(Project, Protocol.project_id == Project.id)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    protocol, project_name = row

    if protocol.project_id is not None:
        allowed = await check_permission(
            db, user_id, ObjectType.PROJECT, protocol.project_id,
            PermissionLevel.VIEW,
        )
        if not allowed:
            raise ValueError("You don't have permission to view this protocol")

    draft_q = select(func.count()).where(
        ProtocolVersion.protocol_id == protocol.id,
        ProtocolVersion.is_draft.is_(True),
    )
    has_draft = (await db.execute(draft_q)).scalar_one() > 0

    return ProtocolFull(
        id=protocol.id,
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        project_name=project_name,
        status=protocol.status,
        version_number=protocol.version_number,
        has_draft=has_draft,
        graph=protocol.graph or {},
        roles=list(protocol.roles),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_protocols_lookup.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Refactor endpoints to use lookup service**

In `backend/app/api/endpoints/protocols.py`, replace the body of `get_protocol` (around line 335) and `list_project_protocols` (around line 367) to call the new service. Keep the response shape identical.

`get_protocol`:

```python
@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.protocols.lookup import get_protocol_full
    try:
        full = await get_protocol_full(db, user_id=user.id, protocol_id=protocol_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    # Re-load the ORM object so the existing ProtocolResponse serializer works
    # unchanged (it expects ORM attrs, not the dataclass).
    protocol = await get_or_404(db, Protocol, protocol_id)
    return protocol
```

`list_project_protocols`:

```python
@router.get(
    "/projects/{project_id}/protocols",
    response_model=List[ProtocolResponse],
)
async def list_project_protocols(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.protocols.lookup import list_protocols
    items = await list_protocols(db, user_id=user.id, project_id=project_id)
    ids = [it.id for it in items]
    if not ids:
        return []
    result = await db.execute(select(Protocol).where(Protocol.id.in_(ids)))
    return list(result.scalars().all())
```

- [ ] **Step 6: Run integration tests for protocols endpoints**

Run: `pytest tests/integration/test_protocols.py -v` (or whichever file exists; if missing, run `pytest tests/ -k protocol -v`)
Expected: PASS — endpoint behavior unchanged.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/protocols/lookup.py \
        backend/tests/unit/test_protocols_lookup.py \
        backend/app/api/endpoints/protocols.py
git commit -m "feat(F-0082): extract protocol lookup service from inline endpoints"
```

---

## Task 2: Extract protocol-roles service

**Files:**
- Create: `backend/app/services/protocols/roles.py`
- Create: `backend/tests/unit/test_protocols_roles.py`
- Modify: `backend/app/api/endpoints/protocols.py:684-825` (4 role endpoints)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_protocols_roles.py`:

```python
"""Tests for services/protocols/roles.py."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            PermissionLevel, PrincipalType, User)
from app.models.science import Project, Protocol, ProtocolRole
from app.services.protocols.roles import (add_role, list_roles, remove_role,
                                          update_role)


@pytest_asyncio.fixture
async def draft_protocol(
    db_session: AsyncSession, test_org: Organization, test_user: User
) -> Protocol:
    proj = Project(name="p", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=proj.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    proto = Protocol(name="P", project_id=proj.id, status="DRAFT", graph={})
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def published_protocol(
    db_session: AsyncSession, test_org: Organization, test_user: User
) -> Protocol:
    proj = Project(name="p2", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=proj.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    proto = Protocol(name="P2", project_id=proj.id, status="APPROVED",
                     version_number=1, graph={})
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest.mark.asyncio
async def test_add_role_assigns_next_sort_order(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    r1 = await add_role(db_session, user_id=test_user.id,
                        protocol_id=draft_protocol.id, name="Operator")
    r2 = await add_role(db_session, user_id=test_user.id,
                        protocol_id=draft_protocol.id, name="Reviewer")
    assert r1.sort_order == 0
    assert r2.sort_order == 1


@pytest.mark.asyncio
async def test_add_role_refuses_on_published(
    db_session: AsyncSession, test_user: User, published_protocol: Protocol
):
    with pytest.raises(ValueError, match="published"):
        await add_role(db_session, user_id=test_user.id,
                       protocol_id=published_protocol.id, name="X")


@pytest.mark.asyncio
async def test_list_roles_returns_sorted(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    db_session.add_all([
        ProtocolRole(protocol_id=draft_protocol.id, name="B", sort_order=2),
        ProtocolRole(protocol_id=draft_protocol.id, name="A", sort_order=0),
        ProtocolRole(protocol_id=draft_protocol.id, name="C", sort_order=1),
    ])
    await db_session.flush()
    roles = await list_roles(db_session, user_id=test_user.id,
                             protocol_id=draft_protocol.id)
    assert [r.name for r in roles] == ["A", "C", "B"]


@pytest.mark.asyncio
async def test_update_role_patches_fields(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    role = ProtocolRole(protocol_id=draft_protocol.id, name="Old", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    updated = await update_role(db_session, user_id=test_user.id,
                                role_id=role.id, name="New", color="#ff0000")
    assert updated.name == "New"
    assert updated.color == "#ff0000"
    assert updated.sort_order == 0


@pytest.mark.asyncio
async def test_update_role_refuses_on_published(
    db_session: AsyncSession, test_user: User, published_protocol: Protocol
):
    role = ProtocolRole(protocol_id=published_protocol.id, name="X", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_role(db_session, user_id=test_user.id,
                          role_id=role.id, name="Y")


@pytest.mark.asyncio
async def test_remove_role_deletes(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    role = ProtocolRole(protocol_id=draft_protocol.id, name="X", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    await remove_role(db_session, user_id=test_user.id, role_id=role.id)
    remaining = await list_roles(db_session, user_id=test_user.id,
                                 protocol_id=draft_protocol.id)
    assert remaining == []


@pytest.mark.asyncio
async def test_remove_role_refuses_on_published(
    db_session: AsyncSession, test_user: User, published_protocol: Protocol
):
    role = ProtocolRole(protocol_id=published_protocol.id, name="X", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await remove_role(db_session, user_id=test_user.id, role_id=role.id)


@pytest.mark.asyncio
async def test_role_ops_require_view_or_edit(
    db_session: AsyncSession, test_user: User
):
    other_org = Organization(name="o", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="op", organization_id=other_org.id, owner_id=uuid.uuid4())
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(name="X", project_id=proj.id, status="DRAFT", graph={})
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await add_role(db_session, user_id=test_user.id,
                       protocol_id=proto.id, name="X")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_roles.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.protocols.roles'`

- [ ] **Step 3: Implement `roles.py`**

Create `backend/app/services/protocols/roles.py`:

```python
"""Service: CRUD on ProtocolRole rows.

Mutations require DRAFT status on the parent protocol + project EDIT perm.
Reads require VIEW. Single canonical impl shared by:
  - api/endpoints/protocols.py role endpoints
  - subagents/protocol_builder/tools.py role tools
"""

from uuid import UUID

from sqlalchemy import func, select

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Protocol, ProtocolRole
from app.services.core.permissions import check_permission


async def _load_protocol_or_raise(db, protocol_id: UUID) -> Protocol:
    p = (await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )).scalar_one_or_none()
    if p is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    return p


async def _require_view(db, user_id: UUID, protocol: Protocol) -> None:
    if protocol.project_id is None:
        return
    allowed = await check_permission(
        db, user_id, ObjectType.PROJECT, protocol.project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise ValueError("You don't have permission to view this protocol")


async def _require_draft_and_edit(db, user_id: UUID, protocol: Protocol) -> None:
    if protocol.project_id is None:
        return
    allowed = await check_permission(
        db, user_id, ObjectType.PROJECT, protocol.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise ValueError("You don't have edit permission on this protocol")
    if protocol.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )


async def list_roles(
    db, *, user_id: UUID, protocol_id: UUID
) -> list[ProtocolRole]:
    proto = await _load_protocol_or_raise(db, protocol_id)
    await _require_view(db, user_id, proto)
    rows = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return list(rows.scalars().all())


async def add_role(
    db, *, user_id: UUID, protocol_id: UUID,
    name: str, color: str = "#94a3b8", sort_order: int | None = None,
) -> ProtocolRole:
    proto = await _load_protocol_or_raise(db, protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    if sort_order is None:
        max_so = (await db.execute(
            select(func.coalesce(func.max(ProtocolRole.sort_order), -1))
            .where(ProtocolRole.protocol_id == protocol_id)
        )).scalar_one()
        sort_order = max_so + 1
    role = ProtocolRole(
        protocol_id=protocol_id, name=name, color=color, sort_order=sort_order,
    )
    db.add(role)
    await db.flush()
    return role


async def update_role(
    db, *, user_id: UUID, role_id: UUID,
    name: str | None = None, color: str | None = None,
    sort_order: int | None = None,
) -> ProtocolRole:
    role = (await db.execute(
        select(ProtocolRole).where(ProtocolRole.id == role_id)
    )).scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    proto = await _load_protocol_or_raise(db, role.protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    if name is not None:
        role.name = name
    if color is not None:
        role.color = color
    if sort_order is not None:
        role.sort_order = sort_order
    await db.flush()
    return role


async def remove_role(db, *, user_id: UUID, role_id: UUID) -> None:
    role = (await db.execute(
        select(ProtocolRole).where(ProtocolRole.id == role_id)
    )).scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role {role_id} not found")
    proto = await _load_protocol_or_raise(db, role.protocol_id)
    await _require_draft_and_edit(db, user_id, proto)
    await db.delete(role)
    await db.flush()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_roles.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Refactor role endpoints**

In `backend/app/api/endpoints/protocols.py`, replace the bodies of `list_protocol_roles`, `create_protocol_role`, `update_protocol_role`, `delete_protocol_role` to delegate. Keep the existing decorators, response models, and dependency signatures unchanged.

```python
@router.get(
    "/protocols/{protocol_id}/roles",
    response_model=List[ProtocolRoleResponse],
)
async def list_protocol_roles(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.protocols.roles import list_roles
    try:
        return await list_roles(db, user_id=user.id, protocol_id=protocol_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=403, detail=msg)


@router.post(
    "/protocols/{protocol_id}/roles",
    response_model=ProtocolRoleResponse,
    status_code=201,
)
async def create_protocol_role(
    protocol_id: UUID,
    role: ProtocolRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    from app.services.protocols.roles import add_role
    try:
        new_role = await add_role(
            db, user_id=user.id, protocol_id=protocol_id,
            name=role.name, color=role.color, sort_order=role.sort_order,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    await db.refresh(new_role)
    return new_role


@router.put(
    "/protocols/{protocol_id}/roles/{role_id}",
    response_model=ProtocolRoleResponse,
)
async def update_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    update_data: ProtocolRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    from app.services.protocols.roles import update_role
    changes = update_data.model_dump(exclude_unset=True)
    try:
        updated = await update_role(
            db, user_id=user.id, role_id=role_id, **changes,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    await db.refresh(updated)
    return updated


@router.delete("/protocols/{protocol_id}/roles/{role_id}")
async def delete_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    from app.services.protocols.roles import remove_role
    try:
        await remove_role(db, user_id=user.id, role_id=role_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    return {"deleted": True}
```

- [ ] **Step 6: Run integration tests**

Run: `pytest tests/ -k role -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/protocols/roles.py \
        backend/tests/unit/test_protocols_roles.py \
        backend/app/api/endpoints/protocols.py
git commit -m "feat(F-0082): extract protocol roles service from inline endpoints"
```

---

## Task 3: Add `update_unit_op_definition` and `elevate_unit_op_scope`

**Files:**
- Modify: `backend/app/services/protocols/unit_ops.py`
- Modify: `backend/tests/unit/test_protocols_unit_ops.py`
- Modify: `backend/app/api/endpoints/unit_ops.py:220` (`update_unit_op`)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_unit_ops.py`:

```python
from app.models.science import Project, UnitOpDefinition
from app.services.protocols.unit_ops import (elevate_unit_op_scope,
                                             update_unit_op_definition)


@pytest.mark.asyncio
async def test_update_unit_op_patches_fields(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    op = await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=True, scope="org", name="Mix", category="Buffer Prep",
        description="old", param_schema={"properties": {}},
    )
    updated = await update_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=True, unit_op_id=op.id,
        description="new", category="Cell Culture",
    )
    assert updated.description == "new"
    assert updated.category == "Cell Culture"
    assert updated.name == "Mix"  # unchanged


@pytest.mark.asyncio
async def test_update_org_scoped_op_requires_admin(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    op = await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=True, scope="org", name="OrgOp", category="C",
        description="d", param_schema={},
    )
    with pytest.raises(ValueError, match="admin"):
        await update_unit_op_definition(
            db_session, user_id=test_user.id, org_id=test_org.id,
            is_org_admin=False, unit_op_id=op.id, description="x",
        )


@pytest.mark.asyncio
async def test_update_refuses_library_override(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    op = UnitOpDefinition(
        name="Lib", category="C", description="d", param_schema={},
        organization_id=test_org.id, project_id=None,
        source_library_slug="lib", source_op_slug="op",
    )
    db_session.add(op)
    await db_session.flush()
    with pytest.raises(ValueError, match="library"):
        await update_unit_op_definition(
            db_session, user_id=test_user.id, org_id=test_org.id,
            is_org_admin=True, unit_op_id=op.id, description="x",
        )


@pytest.mark.asyncio
async def test_elevate_promotes_project_to_org(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    proj = Project(name="p", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=False, scope="project", project_id=proj.id,
        name="ProjOp", category="C", description="d", param_schema={},
    )
    elevated = await elevate_unit_op_scope(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=True, unit_op_id=op.id,
    )
    assert elevated.project_id is None
    assert elevated.organization_id == test_org.id


@pytest.mark.asyncio
async def test_elevate_requires_admin(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    proj = Project(name="p2", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=False, scope="project", project_id=proj.id,
        name="ProjOp2", category="C", description="d", param_schema={},
    )
    with pytest.raises(ValueError, match="admin"):
        await elevate_unit_op_scope(
            db_session, user_id=test_user.id, org_id=test_org.id,
            is_org_admin=False, unit_op_id=op.id,
        )


@pytest.mark.asyncio
async def test_elevate_refuses_already_org(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    op = await create_unit_op_definition(
        db_session, user_id=test_user.id, org_id=test_org.id,
        is_org_admin=True, scope="org", name="X", category="C",
        description="d", param_schema={},
    )
    with pytest.raises(ValueError, match="already"):
        await elevate_unit_op_scope(
            db_session, user_id=test_user.id, org_id=test_org.id,
            is_org_admin=True, unit_op_id=op.id,
        )


@pytest.mark.asyncio
async def test_elevate_refuses_library_override(
    db_session: AsyncSession, test_org: Organization, test_user: User,
):
    proj = Project(name="p3", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    op = UnitOpDefinition(
        name="LibProj", category="C", description="d", param_schema={},
        organization_id=test_org.id, project_id=proj.id,
        source_library_slug="lib", source_op_slug="op",
    )
    db_session.add(op)
    await db_session.flush()
    with pytest.raises(ValueError, match="library"):
        await elevate_unit_op_scope(
            db_session, user_id=test_user.id, org_id=test_org.id,
            is_org_admin=True, unit_op_id=op.id,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_unit_ops.py -v`
Expected: New tests FAIL with `ImportError`.

- [ ] **Step 3: Implement update + elevate**

Append to `backend/app/services/protocols/unit_ops.py`:

```python
async def _load_op_or_raise(
    db: AsyncSession, unit_op_id: UUID, org_id: UUID
) -> UnitOpDefinition:
    op = (await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )).scalar_one_or_none()
    if op is None:
        raise ValueError(f"Unit op {unit_op_id} not found")
    if op.organization_id is not None and op.organization_id != org_id:
        raise ValueError("Unit op belongs to another organization")
    return op


def _require_not_library(op: UnitOpDefinition) -> None:
    if op.source_library_slug is not None:
        raise ValueError(
            "Cannot modify a library-override unit op — "
            "manage it via the library subscription."
        )


async def update_unit_op_definition(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    unit_op_id: UUID,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    param_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpDefinition:
    """Patch an existing UnitOpDefinition.

    Permission rules:
      - org-scoped op (project_id=NULL, organization_id=org_id) → admin only
      - project-scoped op (both set) → caller has already validated project
        EDIT perm at the endpoint/tool layer (this service only checks the
        admin gate for org-scoped rows; project EDIT is checked by callers
        before invoking)
      - library-override rows are refused outright
    """
    op = await _load_op_or_raise(db, unit_op_id, org_id)
    _require_not_library(op)
    if op.project_id is None and not is_org_admin:
        raise ValueError(
            "Only organization admins can update org-wide unit operations."
        )
    if name is not None:
        op.name = name
    if category is not None:
        op.category = category
    if description is not None:
        op.description = description
    if param_schema is not None:
        op.param_schema = param_schema
    if result_schema is not None:
        op.result_schema = result_schema
    await db.flush()
    return op


async def elevate_unit_op_scope(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    is_org_admin: bool,
    unit_op_id: UUID,
) -> UnitOpDefinition:
    """Promote a project-scoped unit op to org-scoped.

    Project → org only. Org-admin required. Refuses if op is already org or
    global, if it's a library override, or if an org-scoped op with the same
    name already exists.
    """
    op = await _load_op_or_raise(db, unit_op_id, org_id)
    _require_not_library(op)
    if op.project_id is None:
        raise ValueError("Unit op is already at org or global scope.")
    if not is_org_admin:
        raise ValueError(
            "Only organization admins can elevate unit ops to org scope."
        )
    collision = (await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.organization_id == org_id,
            UnitOpDefinition.project_id.is_(None),
            UnitOpDefinition.name == op.name,
            UnitOpDefinition.id != op.id,
        )
    )).scalars().first()
    if collision is not None:
        raise ValueError(
            f"An org-wide unit op named '{op.name}' already exists."
        )
    op.project_id = None
    await db.flush()
    return op
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_unit_ops.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Refactor `endpoints/unit_ops.py:update_unit_op` to delegate**

Open `backend/app/api/endpoints/unit_ops.py`, find `update_unit_op` (around line 220). Replace its body to call `update_unit_op_definition`. Keep the route signature, response model, and `_require_org_admin` dep as the existing scope check (the endpoint historically only allowed org-scoped updates; project-scoped editing is done via a separate path). Use the existing dep to provide `is_org_admin=True`; pass through the request fields:

```python
@router.put(
    "/unit-ops/{unit_op_id}",
    response_model=UnitOpDefinitionResponse,
)
async def update_unit_op(
    unit_op_id: UUID,
    update_data: UnitOpDefinitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_org_admin),
):
    from app.services.protocols.unit_ops import update_unit_op_definition
    org_id = user.selected_org_id
    changes = update_data.model_dump(exclude_unset=True)
    try:
        op = await update_unit_op_definition(
            db, user_id=user.id, org_id=org_id, is_org_admin=True,
            unit_op_id=unit_op_id, **changes,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "library" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    await db.refresh(op)
    return _row_to_response_dict(op)
```

If the existing endpoint signature differs (different field names on `UnitOpDefinitionUpdate`), keep the field names matching the existing schema and only re-route the body construction.

- [ ] **Step 6: Run integration tests**

Run: `pytest tests/ -k unit_op -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/protocols/unit_ops.py \
        backend/tests/unit/test_protocols_unit_ops.py \
        backend/app/api/endpoints/unit_ops.py
git commit -m "feat(F-0082): add update_unit_op_definition and elevate_unit_op_scope services"
```

---

## Task 4: Add `update_protocol_metadata` to creation service

**Files:**
- Modify: `backend/app/services/protocols/creation.py`
- Modify: `backend/tests/unit/test_protocols_creation.py`
- Modify: `backend/app/api/endpoints/protocols.py:534-680` (only the metadata-only branch)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_creation.py`:

```python
from app.models.science import Protocol
from app.services.protocols.creation import update_protocol_metadata


@pytest.mark.asyncio
async def test_update_protocol_metadata_patches_name_and_description(
    db_session: AsyncSession, test_user: User, project: Project,
):
    proto = Protocol(name="Old", description="o", project_id=project.id,
                     status="DRAFT", graph={})
    db_session.add(proto)
    await db_session.flush()
    updated = await update_protocol_metadata(
        db_session, user_id=test_user.id, protocol_id=proto.id,
        name="New", description="n",
    )
    assert updated.name == "New"
    assert updated.description == "n"


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_on_published(
    db_session: AsyncSession, test_user: User, project: Project,
):
    proto = Protocol(name="P", project_id=project.id,
                     status="APPROVED", version_number=1, graph={})
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_protocol_metadata(
            db_session, user_id=test_user.id, protocol_id=proto.id, name="X",
        )


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_without_perm(
    db_session: AsyncSession, test_user: User,
):
    other_org = Organization(name="o2", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="op", organization_id=other_org.id, owner_id=uuid.uuid4())
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(name="X", project_id=proj.id, status="DRAFT", graph={})
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await update_protocol_metadata(
            db_session, user_id=test_user.id, protocol_id=proto.id, name="Y",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_creation.py -v`
Expected: New tests FAIL with ImportError.

- [ ] **Step 3: Implement `update_protocol_metadata`**

Append to `backend/app/services/protocols/creation.py`:

```python
async def update_protocol_metadata(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    name: str | None = None,
    description: str | None = None,
) -> Protocol:
    """Patch an existing DRAFT Protocol's name and/or description.

    Refuses on APPROVED/PENDING_APPROVAL — those require a draft via the
    existing endpoint flow.
    """
    proto = (await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )).scalar_one_or_none()
    if proto is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    if proto.project_id is not None:
        allowed = await check_permission(
            db, user_id, ObjectType.PROJECT, proto.project_id, PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    if proto.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )
    if name is not None:
        proto.name = name
    if description is not None:
        proto.description = description
    await db.flush()
    return proto
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_creation.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Refactor metadata-only branch in `update_protocol` endpoint**

In `backend/app/api/endpoints/protocols.py:update_protocol` (around line 534), at the top of the function (after the permission check and `protocol = await get_or_404(...)` load), add a fast-path delegation for the "metadata only, no graph" case. Insert just before `# If graph is being updated and save_as_draft is True`:

```python
    # Metadata-only patch fast path (no graph change, no draft request) —
    # delegate to the canonical service so chat tools and HTTP share logic.
    if "graph" not in changes and not save_as_draft and any(
        k in changes for k in ("name", "description")
    ):
        from app.services.protocols.creation import update_protocol_metadata
        try:
            await update_protocol_metadata(
                db, user_id=user.id, protocol_id=protocol_id,
                name=changes.get("name"),
                description=changes.get("description"),
            )
        except ValueError as e:
            msg = str(e)
            if "published" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=403, detail=msg)
        # Apply any non-name/description changes inline (e.g. flags) so the
        # rest of the handler still runs for unrelated fields.
        for k in ("name", "description"):
            changes.pop(k, None)
```

This preserves all existing endpoint behavior; only the name/description patching is delegated.

- [ ] **Step 6: Run integration tests**

Run: `pytest tests/ -k protocol -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/protocols/creation.py \
        backend/tests/unit/test_protocols_creation.py \
        backend/app/api/endpoints/protocols.py
git commit -m "feat(F-0082): add update_protocol_metadata service; delegate from endpoint"
```

---

## Task 5: Graph mutation service — `add_step` + draft guard

**Files:**
- Create: `backend/app/services/protocols/graph.py`
- Create: `backend/tests/unit/test_protocols_graph.py`

- [ ] **Step 1: Write failing tests for `add_step` and the draft guard**

Create `backend/tests/unit/test_protocols_graph.py`:

```python
"""Tests for services/protocols/graph.py — protocol graph mutations."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            PermissionLevel, PrincipalType, User)
from app.models.science import Project, Protocol, ProtocolRole
from app.services.protocols.graph import add_step


def _seed_graph_with_n_steps(n: int) -> dict:
    """Build a graph dict with a Process Start + n unit-op nodes chained."""
    nodes = [{"id": "node-ps", "type": "processStart",
              "position": {"x": 0, "y": 0}, "data": {}}]
    edges = []
    prev = "node-ps"
    for i in range(n):
        nid = f"node-{i}"
        nodes.append({
            "id": nid, "type": "unitOp",
            "position": {"x": 100 * (i + 1), "y": 0},
            "data": {"label": f"Step {i}", "category": "C",
                     "duration_min": 10, "params": {}, "paramSchema": {}},
        })
        edges.append({"id": f"edge-{i}", "source": prev, "target": nid})
        prev = nid
    return {"nodes": nodes, "edges": edges, "layout": "horizontal"}


@pytest_asyncio.fixture
async def draft_proto(
    db_session: AsyncSession, test_org: Organization, test_user: User
) -> Protocol:
    proj = Project(name="g1", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=proj.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    proto = Protocol(name="P", project_id=proj.id, status="DRAFT",
                     graph=_seed_graph_with_n_steps(2))
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest.mark.asyncio
async def test_add_step_appends_when_no_position(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    updated = await add_step(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id,
        name="New Step", unit_op_name="Custom", duration_min=15,
        description="do it", category="Cell Culture",
    )
    nodes = updated.graph["nodes"]
    edges = updated.graph["edges"]
    # Was 1 ps + 2 unitOps + 2 edges -> 1 ps + 3 unitOps + 3 edges
    unit_ops = [n for n in nodes if n["type"] == "unitOp"]
    assert len(unit_ops) == 3
    assert unit_ops[-1]["data"]["label"] == "New Step"
    assert len(edges) == 3
    # Last edge connects previous tail to the new node
    assert edges[-1]["target"] == unit_ops[-1]["id"]
    assert edges[-1]["source"] == unit_ops[-2]["id"]


@pytest.mark.asyncio
async def test_add_step_inserts_after_index(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    updated = await add_step(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id,
        name="Middle", unit_op_name="X", after_step_index=0,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    assert [n["data"]["label"] for n in unit_ops] == ["Step 0", "Middle", "Step 1"]
    # Edges form a single chain ps -> 0 -> Middle -> 1
    edges = updated.graph["edges"]
    assert len(edges) == 3
    chain_targets = {e["source"]: e["target"] for e in edges}
    # ps -> step 0 -> middle -> step 1
    ids = [n["id"] for n in unit_ops]
    assert chain_targets["node-ps"] == ids[0]
    assert chain_targets[ids[0]] == ids[1]
    assert chain_targets[ids[1]] == ids[2]


@pytest.mark.asyncio
async def test_add_step_with_role_id_sets_parent(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    role = ProtocolRole(protocol_id=draft_proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    updated = await add_step(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id,
        name="Roled", unit_op_name="X", role_id=role.id,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    new_node = next(n for n in unit_ops if n["data"]["label"] == "Roled")
    assert new_node.get("parentId") == f"lane-{role.id}"


@pytest.mark.asyncio
async def test_add_step_refuses_on_published(
    db_session: AsyncSession, test_org: Organization, test_user: User
):
    proj = Project(name="g2", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=proj.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    proto = Protocol(name="Pub", project_id=proj.id,
                     status="APPROVED", version_number=1,
                     graph=_seed_graph_with_n_steps(1))
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await add_step(
            db_session, user_id=test_user.id, protocol_id=proto.id,
            name="X", unit_op_name="X",
        )


@pytest.mark.asyncio
async def test_add_step_refuses_without_edit_perm(
    db_session: AsyncSession, test_user: User
):
    other_org = Organization(name="oo", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="hidden", organization_id=other_org.id,
                   owner_id=uuid.uuid4())
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(name="H", project_id=proj.id, status="DRAFT",
                     graph=_seed_graph_with_n_steps(1))
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await add_step(
            db_session, user_id=test_user.id, protocol_id=proto.id,
            name="X", unit_op_name="X",
        )


@pytest.mark.asyncio
async def test_add_step_index_out_of_range(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="out of range"):
        await add_step(
            db_session, user_id=test_user.id, protocol_id=draft_proto.id,
            name="X", unit_op_name="X", after_step_index=99,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_graph.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `graph.py` with helpers + `add_step`**

Create `backend/app/services/protocols/graph.py`:

```python
"""Service: deterministic mutations on Protocol.graph (DRAFT only).

All functions:
  - load the protocol, check VIEW/EDIT and DRAFT status
  - mutate ``protocol.graph`` (a JSONB dict) in-place
  - flush and return the protocol

Step indices reference unit-op nodes only (Process Start excluded), 0-based.
The single-chain edge invariant is maintained: ps -> step[0] -> step[1] -> ...
Arbitrary DAG topologies are not reshaped.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Protocol
from app.services.core.permissions import check_permission


async def _load_and_guard(
    db: AsyncSession, user_id: UUID, protocol_id: UUID
) -> Protocol:
    proto = (await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )).scalar_one_or_none()
    if proto is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    if proto.project_id is not None:
        allowed = await check_permission(
            db, user_id, ObjectType.PROJECT, proto.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    if proto.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )
    return proto


def _split_nodes(graph: dict) -> tuple[list[dict], list[int], list[int]]:
    """Return (nodes, ps_indices, unit_op_indices)."""
    nodes = list(graph.get("nodes", []))
    ps_idx = [i for i, n in enumerate(nodes) if n.get("type") == "processStart"]
    uo_idx = [i for i, n in enumerate(nodes) if n.get("type") == "unitOp"]
    return nodes, ps_idx, uo_idx


def _rebuild_chain_edges(
    existing_edges: list[dict], ps_id: str, ordered_unit_op_ids: list[str]
) -> list[dict]:
    """Replace the linear chain edges with ps -> uo[0] -> uo[1] -> ...

    Non-chain edges (e.g. user-drawn cross-links) are preserved as-is. We
    detect chain edges as: source==ps_id, OR (source in unit_op_ids AND
    target in unit_op_ids AND no parallel structural meaning).
    """
    uo_set = set(ordered_unit_op_ids)
    preserved = [
        e for e in existing_edges
        if e.get("source") != ps_id
        and not (e.get("source") in uo_set and e.get("target") in uo_set)
    ]
    chain: list[dict] = []
    prev = ps_id
    for nid in ordered_unit_op_ids:
        chain.append({"id": f"edge-{uuid4()}", "source": prev, "target": nid})
        prev = nid
    return preserved + chain


async def add_step(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    name: str,
    unit_op_name: str,
    duration_min: int = 30,
    description: str = "",
    category: str = "General",
    params: dict[str, Any] | None = None,
    after_step_index: int | None = None,
    role_id: UUID | None = None,
) -> Protocol:
    """Insert a new unit-op node into the graph.

    ``after_step_index=None`` appends after the last unit op. Otherwise
    inserts immediately after that 0-based unit-op step index.
    """
    proto = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(proto.graph or {})
    nodes, ps_idx, uo_idx = _split_nodes(graph)
    if not ps_idx:
        raise ValueError("Protocol graph has no Process Start node")
    ps_id = nodes[ps_idx[0]]["id"]

    if after_step_index is not None:
        if after_step_index < 0 or after_step_index >= len(uo_idx):
            raise ValueError(
                f"after_step_index {after_step_index} out of range "
                f"(protocol has {len(uo_idx)} unit op steps)"
            )
        insert_pos = uo_idx[after_step_index] + 1
    else:
        insert_pos = (uo_idx[-1] + 1) if uo_idx else (ps_idx[0] + 1)

    new_node: dict[str, Any] = {
        "id": f"node-{uuid4()}",
        "type": "unitOp",
        "position": {"x": 100, "y": 200},
        "data": {
            "label": name,
            "unitOpId": None,
            "category": category,
            "description": description,
            "duration_min": duration_min,
            "params": params or {},
            "paramSchema": {},
        },
    }
    if role_id is not None:
        new_node["parentId"] = f"lane-{role_id}"
    nodes.insert(insert_pos, new_node)

    # Recompute the linear unit-op chain in node order.
    new_uo_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
    edges = _rebuild_chain_edges(graph.get("edges", []), ps_id, new_uo_ids)

    graph["nodes"] = nodes
    graph["edges"] = edges
    proto.graph = graph
    await db.flush()
    return proto
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_graph.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/graph.py backend/tests/unit/test_protocols_graph.py
git commit -m "feat(F-0082): protocol graph mutation service with add_step + draft guard"
```

---

## Task 6: Graph mutation — `remove_step`

**Files:**
- Modify: `backend/app/services/protocols/graph.py`
- Modify: `backend/tests/unit/test_protocols_graph.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_graph.py`:

```python
from app.services.protocols.graph import remove_step


@pytest.mark.asyncio
async def test_remove_step_drops_node_and_rewires(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    # draft_proto has 2 unit-op steps. Remove step 0.
    updated = await remove_step(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id,
        step_index=0,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    assert len(unit_ops) == 1
    assert unit_ops[0]["data"]["label"] == "Step 1"
    edges = updated.graph["edges"]
    assert len(edges) == 1
    assert edges[0]["target"] == unit_ops[0]["id"]


@pytest.mark.asyncio
async def test_remove_step_index_out_of_range(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="out of range"):
        await remove_step(
            db_session, user_id=test_user.id, protocol_id=draft_proto.id,
            step_index=5,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_graph.py -v -k remove`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `remove_step`**

Append to `backend/app/services/protocols/graph.py`:

```python
async def remove_step(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    step_index: int,
) -> Protocol:
    """Delete the unit-op node at the given 0-based step index."""
    proto = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(proto.graph or {})
    nodes, ps_idx, uo_idx = _split_nodes(graph)
    if not ps_idx:
        raise ValueError("Protocol graph has no Process Start node")
    if step_index < 0 or step_index >= len(uo_idx):
        raise ValueError(
            f"step_index {step_index} out of range "
            f"(protocol has {len(uo_idx)} unit op steps)"
        )
    drop_pos = uo_idx[step_index]
    nodes.pop(drop_pos)
    ps_id = next(n["id"] for n in nodes if n.get("type") == "processStart")
    new_uo_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
    graph["nodes"] = nodes
    graph["edges"] = _rebuild_chain_edges(
        graph.get("edges", []), ps_id, new_uo_ids
    )
    proto.graph = graph
    await db.flush()
    return proto
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_graph.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/graph.py backend/tests/unit/test_protocols_graph.py
git commit -m "feat(F-0082): graph.remove_step"
```

---

## Task 7: Graph mutation — `reorder_steps`

**Files:**
- Modify: `backend/app/services/protocols/graph.py`
- Modify: `backend/tests/unit/test_protocols_graph.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_graph.py`:

```python
from app.services.protocols.graph import reorder_steps


@pytest.mark.asyncio
async def test_reorder_steps_reverses_chain(
    db_session: AsyncSession, test_user: User, test_org: Organization
):
    proj = Project(name="ro", organization_id=test_org.id, owner_id=test_user.id)
    db_session.add(proj)
    await db_session.flush()
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER, principal_id=test_user.id,
            object_type=ObjectType.PROJECT.value, object_id=proj.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    proto = Protocol(name="R", project_id=proj.id, status="DRAFT",
                     graph=_seed_graph_with_n_steps(3))
    db_session.add(proto)
    await db_session.flush()

    updated = await reorder_steps(
        db_session, user_id=test_user.id, protocol_id=proto.id,
        ordered_step_indices=[2, 1, 0],
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    assert [n["data"]["label"] for n in unit_ops] == ["Step 2", "Step 1", "Step 0"]
    edges = updated.graph["edges"]
    assert len(edges) == 3
    ids = [n["id"] for n in unit_ops]
    chain = {e["source"]: e["target"] for e in edges}
    assert chain[ids[0]] == ids[1]
    assert chain[ids[1]] == ids[2]


@pytest.mark.asyncio
async def test_reorder_rejects_bad_permutation(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="permutation"):
        await reorder_steps(
            db_session, user_id=test_user.id, protocol_id=draft_proto.id,
            ordered_step_indices=[0, 0],
        )
    with pytest.raises(ValueError, match="permutation"):
        await reorder_steps(
            db_session, user_id=test_user.id, protocol_id=draft_proto.id,
            ordered_step_indices=[0],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_graph.py -v -k reorder`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `reorder_steps`**

Append to `backend/app/services/protocols/graph.py`:

```python
async def reorder_steps(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    ordered_step_indices: list[int],
) -> Protocol:
    """Reorder unit-op steps. ``ordered_step_indices`` is a permutation of
    range(n_unit_ops) — the new visual order."""
    proto = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(proto.graph or {})
    nodes, ps_idx, uo_idx = _split_nodes(graph)
    if not ps_idx:
        raise ValueError("Protocol graph has no Process Start node")
    n = len(uo_idx)
    if sorted(ordered_step_indices) != list(range(n)):
        raise ValueError(
            f"ordered_step_indices must be a permutation of 0..{n-1}"
        )
    # Build a new node list: keep non-unit-op nodes in place, then the
    # unit-op nodes in the requested order at their current positions.
    unit_ops = [nodes[i] for i in uo_idx]
    new_unit_ops = [unit_ops[i] for i in ordered_step_indices]
    new_nodes = list(nodes)
    for slot, new_uo in zip(uo_idx, new_unit_ops):
        new_nodes[slot] = new_uo
    ps_id = next(n["id"] for n in new_nodes if n.get("type") == "processStart")
    new_uo_ids = [n["id"] for n in new_nodes if n.get("type") == "unitOp"]
    graph["nodes"] = new_nodes
    graph["edges"] = _rebuild_chain_edges(
        graph.get("edges", []), ps_id, new_uo_ids
    )
    proto.graph = graph
    await db.flush()
    return proto
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_graph.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/graph.py backend/tests/unit/test_protocols_graph.py
git commit -m "feat(F-0082): graph.reorder_steps"
```

---

## Task 8: Graph mutation — `replace_step_unit_op`

**Files:**
- Modify: `backend/app/services/protocols/graph.py`
- Modify: `backend/tests/unit/test_protocols_graph.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_graph.py`:

```python
from app.models.science import UnitOpDefinition
from app.services.protocols.graph import replace_step_unit_op


@pytest.mark.asyncio
async def test_replace_step_unit_op_uses_catalog(
    db_session: AsyncSession, test_org: Organization, test_user: User,
    draft_proto: Protocol,
):
    op = UnitOpDefinition(
        name="Cell Seeding", category="Cell Culture",
        description="seed cells", param_schema={"properties": {"vol": {"type": "number"}}},
        organization_id=test_org.id, project_id=None,
    )
    db_session.add(op)
    await db_session.flush()
    updated = await replace_step_unit_op(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id,
        step_index=0, new_unit_op_name="Cell Seeding",
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    target = unit_ops[0]
    assert target["data"]["unitOpId"] == str(op.id)
    assert target["data"]["category"] == "Cell Culture"
    # Label preserved
    assert target["data"]["label"] == "Step 0"
    # paramSchema swapped to catalog's
    assert "vol" in target["data"]["paramSchema"]["properties"]


@pytest.mark.asyncio
async def test_replace_step_unit_op_unknown_op_raises(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="not found"):
        await replace_step_unit_op(
            db_session, user_id=test_user.id, protocol_id=draft_proto.id,
            step_index=0, new_unit_op_name="Nope",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_graph.py -v -k replace`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `replace_step_unit_op`**

Append to `backend/app/services/protocols/graph.py`:

```python
async def replace_step_unit_op(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    step_index: int,
    new_unit_op_name: str,
) -> Protocol:
    """Swap the underlying unit op of an existing step.

    Step's display label is preserved. category, paramSchema, and unitOpId
    are taken from the matched catalog row. Existing params are kept
    (caller can clear via update_protocol_step if needed).
    """
    from app.models.science import UnitOpDefinition

    proto = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(proto.graph or {})
    nodes, _, uo_idx = _split_nodes(graph)
    if step_index < 0 or step_index >= len(uo_idx):
        raise ValueError(
            f"step_index {step_index} out of range "
            f"(protocol has {len(uo_idx)} unit op steps)"
        )
    op = (await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.name == new_unit_op_name)
    )).scalars().first()
    if op is None:
        raise ValueError(f"Unit op '{new_unit_op_name}' not found in catalog")
    node_pos = uo_idx[step_index]
    node = dict(nodes[node_pos])
    data = dict(node.get("data") or {})
    data["unitOpId"] = str(op.id)
    data["category"] = op.category
    data["paramSchema"] = op.param_schema or {}
    node["data"] = data
    nodes[node_pos] = node
    graph["nodes"] = nodes
    proto.graph = graph
    await db.flush()
    return proto
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_graph.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/graph.py backend/tests/unit/test_protocols_graph.py
git commit -m "feat(F-0082): graph.replace_step_unit_op"
```

---

## Task 9: Add DRAFT guard + `role_id` to existing `update_protocol_step`

**Files:**
- Modify: `backend/app/services/protocols/creation.py:111-175` (`update_protocol_step`)
- Modify: `backend/tests/unit/test_protocols_creation.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_protocols_creation.py`:

```python
from app.services.protocols.creation import update_protocol_step


@pytest.mark.asyncio
async def test_update_protocol_step_refuses_on_published(
    db_session: AsyncSession, test_user: User, project: Project
):
    proto = Protocol(
        name="Pub", project_id=project.id, status="APPROVED",
        version_number=1,
        graph={
            "nodes": [
                {"id": "ps", "type": "processStart", "data": {}},
                {"id": "u0", "type": "unitOp", "data": {"label": "A"}},
            ],
            "edges": [{"id": "e", "source": "ps", "target": "u0"}],
        },
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_protocol_step(
            db_session, user_id=test_user.id, protocol_id=proto.id,
            step_index=0, description="x",
        )


@pytest.mark.asyncio
async def test_update_protocol_step_sets_parent_for_role(
    db_session: AsyncSession, test_user: User, project: Project
):
    proto = Protocol(
        name="P", project_id=project.id, status="DRAFT",
        graph={
            "nodes": [
                {"id": "ps", "type": "processStart", "data": {}},
                {"id": "u0", "type": "unitOp", "data": {"label": "A"}},
            ],
            "edges": [{"id": "e", "source": "ps", "target": "u0"}],
        },
    )
    db_session.add(proto)
    await db_session.flush()
    role = ProtocolRole(protocol_id=proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()

    updated = await update_protocol_step(
        db_session, user_id=test_user.id, protocol_id=proto.id,
        step_index=0, role_id=role.id,
    )
    node = next(n for n in updated.graph["nodes"] if n["type"] == "unitOp")
    assert node.get("parentId") == f"lane-{role.id}"
```

Add `from app.models.science import ProtocolRole` near the existing imports if not present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_protocols_creation.py -v -k "published or parent_for_role"`
Expected: FAIL — `update_protocol_step` doesn't reject published yet and doesn't accept `role_id`.

- [ ] **Step 3: Modify `update_protocol_step`**

In `backend/app/services/protocols/creation.py`, change the function signature to add `role_id`, and add the DRAFT guard.

Replace the function body (currently around lines 111-175):

```python
async def update_protocol_step(
    db: AsyncSession,
    user_id: UUID,
    protocol_id: UUID,
    step_index: int,
    *,
    description: str | None = None,
    category: str | None = None,
    param_schema: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    role_id: UUID | None = None,
) -> Protocol:
    """Patch a single unit-op step inside an existing DRAFT Protocol's graph.

    Only the kwargs supplied are written. ``role_id`` sets the node's
    ``parentId`` to ``lane-<role_id>`` (frontend lane convention).
    Refuses on APPROVED/PENDING_APPROVAL — published protocols require a
    new draft (out of scope for this service).
    """
    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if protocol is None:
        raise ValueError(f"Protocol {protocol_id} not found")

    if protocol.project_id is not None:
        allowed = await check_permission(
            db, user_id, ObjectType.PROJECT, protocol.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")

    if protocol.status != "DRAFT":
        raise ValueError(
            "Protocol is published — create a draft in the protocol editor first."
        )

    graph = dict(protocol.graph or {})
    nodes = list(graph.get("nodes", []))
    unit_op_indices = [i for i, n in enumerate(nodes) if n.get("type") == "unitOp"]
    if step_index < 0 or step_index >= len(unit_op_indices):
        raise ValueError(
            f"step_index {step_index} out of range "
            f"(protocol has {len(unit_op_indices)} unit op steps)"
        )

    node_idx = unit_op_indices[step_index]
    node = dict(nodes[node_idx])
    data = dict(node.get("data") or {})

    if description is not None:
        data["description"] = description
    if category is not None:
        data["category"] = category
    if param_schema is not None:
        data["paramSchema"] = param_schema
    if params is not None:
        data["params"] = params

    node["data"] = data
    if role_id is not None:
        node["parentId"] = f"lane-{role_id}"

    nodes[node_idx] = node
    graph["nodes"] = nodes
    protocol.graph = graph
    await db.flush()
    return protocol
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_protocols_creation.py tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS (existing chat-tool tests should still work — the new `role_id` defaults to None).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/creation.py backend/tests/unit/test_protocols_creation.py
git commit -m "feat(F-0082): update_protocol_step gains DRAFT guard + role_id"
```

---

## Task 10: Read tools — `list_protocols` and `get_protocol`

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py`
- Modify: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_subagents_protocol_builder.py`:

```python
import uuid as _uuid

from app.services.ai.subagents.protocol_builder.tools import (get_protocol,
                                                              list_protocols)


@pytest.mark.asyncio
async def test_list_protocols_tool_delegates(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(*args, **kwargs):
        captured.update(kwargs)
        from app.services.protocols.lookup import ProtocolListItem
        return [
            ProtocolListItem(
                id=_uuid.uuid4(), name="A", description=None,
                project_id=_uuid.uuid4(), project_name="proj", status="DRAFT",
                version_number=0, has_draft=False,
            ),
        ]

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.list_protocols_service",
        fake,
    )
    result = await list_protocols(ctx)
    assert result.total == 1
    assert result.protocols[0].name == "A"
    assert ctx.deps.tool_calls[-1]["tool"] == "list_protocols"


@pytest.mark.asyncio
async def test_get_protocol_tool_delegates(monkeypatch):
    ctx = make_ctx()
    pid = _uuid.uuid4()

    async def fake(*args, **kwargs):
        from app.services.protocols.lookup import ProtocolFull
        return ProtocolFull(
            id=pid, name="P", description="d",
            project_id=_uuid.uuid4(), project_name="proj",
            status="DRAFT", version_number=0, has_draft=False,
            graph={"nodes": [], "edges": []}, roles=[],
        )

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.get_protocol_full_service",
        fake,
    )
    result = await get_protocol(ctx, protocol_id=str(pid))
    assert result.protocol_id == str(pid)
    assert result.summary.startswith("Protocol 'P'")
    assert ctx.deps.tool_calls[-1]["tool"] == "get_protocol"


@pytest.mark.asyncio
async def test_get_protocol_tool_returns_error_on_value_error(monkeypatch):
    ctx = make_ctx()

    async def fake(*args, **kwargs):
        raise ValueError("Protocol not found")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.get_protocol_full_service",
        fake,
    )
    result = await get_protocol(ctx, protocol_id=str(_uuid.uuid4()))
    assert result.ok is False
    assert "not found" in result.summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v -k "list_protocols_tool or get_protocol_tool"`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the tools**

Append to `backend/app/services/ai/subagents/protocol_builder/tools.py`. Add new imports near the top of the file:

```python
from app.services.protocols.lookup import (ProtocolFull, ProtocolListItem,
                                           get_protocol_full as
                                           get_protocol_full_service,
                                           list_protocols as
                                           list_protocols_service)
```

Then append the tool definitions and result dataclasses:

```python
# ─── list_protocols / get_protocol ─────────────────────────────────────────────


@dataclass
class ProtocolSummary:
    id: str
    name: str
    project_name: str | None
    status: str
    version_number: int
    has_draft: bool


@dataclass
class ListProtocolsResult:
    ok: bool
    total: int
    protocols: list[ProtocolSummary]
    summary: str


@dataclass
class RoleSummary:
    id: str
    name: str
    sort_order: int


@dataclass
class GetProtocolResult:
    ok: bool
    protocol_id: str
    name: str
    description: str | None
    status: str
    version_number: int
    has_draft: bool
    step_count: int
    roles: list[RoleSummary]
    graph: dict[str, Any]
    summary: str


def _summary_from_full(p: ProtocolFull) -> str:
    state = p.status
    if p.has_draft:
        state += " (draft pending)"
    return (
        f"Protocol '{p.name}' in project '{p.project_name}' — {state}, "
        f"v{p.version_number}, {len([n for n in p.graph.get('nodes', []) if n.get('type') == 'unitOp'])} steps"
    )


async def list_protocols(
    ctx: RunContext[ChatDeps],
    project_id: str | None = None,
) -> ListProtocolsResult:
    """List protocols the user can see. Optionally scope to one project.

    Args:
        ctx: Run context with shared deps.
        project_id: Optional project UUID string to filter to one project.
    """
    proj_uuid = UUID(project_id) if project_id else None
    items = await list_protocols_service(
        ctx.deps.db, user_id=ctx.deps.user_id, project_id=proj_uuid,
    )
    ctx.deps.tool_calls.append({
        "tool": "list_protocols", "subagent": "protocol_builder",
        "results": len(items),
    })
    return ListProtocolsResult(
        ok=True,
        total=len(items),
        protocols=[
            ProtocolSummary(
                id=str(it.id), name=it.name, project_name=it.project_name,
                status=it.status, version_number=it.version_number,
                has_draft=it.has_draft,
            )
            for it in items
        ],
        summary=f"Found {len(items)} protocol(s).",
    )


async def get_protocol(
    ctx: RunContext[ChatDeps], protocol_id: str
) -> GetProtocolResult:
    """Return full state of one protocol (metadata, graph, roles).

    Args:
        ctx: Run context with shared deps.
        protocol_id: UUID string of the protocol to fetch.
    """
    try:
        full = await get_protocol_full_service(
            ctx.deps.db, user_id=ctx.deps.user_id,
            protocol_id=UUID(protocol_id),
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "get_protocol", "subagent": "protocol_builder",
            "error": str(e),
        })
        return GetProtocolResult(
            ok=False, protocol_id=protocol_id, name="", description=None,
            status="", version_number=0, has_draft=False, step_count=0,
            roles=[], graph={}, summary=str(e),
        )
    ctx.deps.tool_calls.append({
        "tool": "get_protocol", "subagent": "protocol_builder",
        "protocol_id": protocol_id,
    })
    step_count = len(
        [n for n in full.graph.get("nodes", []) if n.get("type") == "unitOp"]
    )
    return GetProtocolResult(
        ok=True,
        protocol_id=str(full.id),
        name=full.name,
        description=full.description,
        status=full.status,
        version_number=full.version_number,
        has_draft=full.has_draft,
        step_count=step_count,
        roles=[
            RoleSummary(id=str(r.id), name=r.name, sort_order=r.sort_order)
            for r in full.roles
        ],
        graph=full.graph,
        summary=_summary_from_full(full),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/tools.py \
        backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(F-0082): chat tools list_protocols and get_protocol"
```

---

## Task 11: Mutation tools — metadata + graph

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py`
- Modify: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_subagents_protocol_builder.py`:

```python
from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_step, remove_protocol_step, reorder_protocol_steps,
    replace_step_unit_op, update_protocol_metadata)


@pytest.mark.asyncio
async def test_update_protocol_metadata_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.name = kwargs.get("name") or "old"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_protocol_metadata_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await update_protocol_metadata(
        ctx, protocol_id=str(pid), name="New Name",
    )
    assert captured["protocol_id"] == pid
    assert captured["name"] == "New Name"
    assert result.ok is True
    assert ctx.deps.tool_calls[-1]["tool"] == "update_protocol_metadata"


@pytest.mark.asyncio
async def test_update_protocol_metadata_published_returns_error(monkeypatch):
    ctx = make_ctx()

    async def fake(db, **kwargs):
        raise ValueError("Protocol is published — create a draft first.")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_protocol_metadata_service",
        fake,
    )
    result = await update_protocol_metadata(
        ctx, protocol_id=str(_uuid.uuid4()), name="X",
    )
    assert result.ok is False
    assert "published" in result.summary


@pytest.mark.asyncio
async def test_add_protocol_step_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.add_step_service",
        fake,
    )
    pid = _uuid.uuid4()
    rid = _uuid.uuid4()
    result = await add_protocol_step(
        ctx, protocol_id=str(pid), name="Mix", unit_op_name="Mix Op",
        duration_min=20, role_id=str(rid),
    )
    assert captured["protocol_id"] == pid
    assert captured["role_id"] == rid
    assert result.ok is True


@pytest.mark.asyncio
async def test_remove_protocol_step_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.remove_step_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await remove_protocol_step(
        ctx, protocol_id=str(pid), step_index=2,
    )
    assert captured["step_index"] == 2
    assert result.ok is True


@pytest.mark.asyncio
async def test_reorder_protocol_steps_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.reorder_steps_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await reorder_protocol_steps(
        ctx, protocol_id=str(pid), ordered_step_indices=[2, 0, 1],
    )
    assert captured["ordered_step_indices"] == [2, 0, 1]
    assert result.ok is True


@pytest.mark.asyncio
async def test_replace_step_unit_op_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.replace_step_unit_op_service",
        fake,
    )
    pid = _uuid.uuid4()
    result = await replace_step_unit_op(
        ctx, protocol_id=str(pid), step_index=1, new_unit_op_name="Cell Seeding",
    )
    assert captured["new_unit_op_name"] == "Cell Seeding"
    assert result.ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v -k "metadata_tool or step_tool or reorder or replace_step"`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the mutation tools**

In `backend/app/services/ai/subagents/protocol_builder/tools.py`, add new imports near the top:

```python
from app.services.protocols.creation import (
    update_protocol_metadata as update_protocol_metadata_service,
)
from app.services.protocols.graph import (
    add_step as add_step_service,
    remove_step as remove_step_service,
    reorder_steps as reorder_steps_service,
    replace_step_unit_op as replace_step_unit_op_service,
)
```

Append the tool definitions:

```python
# ─── Mutation tools (DRAFT-only) ───────────────────────────────────────────────


@dataclass
class ProtocolMutationResult:
    ok: bool
    protocol_id: str
    summary: str


def _mutation_error(protocol_id: str, exc: ValueError) -> ProtocolMutationResult:
    return ProtocolMutationResult(
        ok=False, protocol_id=protocol_id, summary=str(exc)
    )


async def update_protocol_metadata(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str | None = None,
    description: str | None = None,
) -> ProtocolMutationResult:
    """Patch a DRAFT protocol's name and/or description."""
    pid = UUID(protocol_id)
    try:
        await update_protocol_metadata_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            name=name, description=description,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "update_protocol_metadata",
            "subagent": "protocol_builder", "error": str(e),
        })
        return _mutation_error(protocol_id, e)
    fields = [k for k, v in (("name", name), ("description", description))
              if v is not None]
    ctx.deps.tool_calls.append({
        "tool": "update_protocol_metadata", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "fields_updated": fields,
    })
    return ProtocolMutationResult(
        ok=True, protocol_id=protocol_id,
        summary=f"Updated {', '.join(fields)} on protocol.",
    )


async def add_protocol_step(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str,
    unit_op_name: str,
    duration_min: int = 30,
    description: str = "",
    category: str = "General",
    params: dict[str, Any] | None = None,
    after_step_index: int | None = None,
    role_id: str | None = None,
) -> ProtocolMutationResult:
    """Append or insert a unit-op step into a DRAFT protocol's graph."""
    pid = UUID(protocol_id)
    rid = UUID(role_id) if role_id else None
    try:
        await add_step_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            name=name, unit_op_name=unit_op_name,
            duration_min=duration_min, description=description,
            category=category, params=params,
            after_step_index=after_step_index, role_id=rid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "add_protocol_step", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _mutation_error(protocol_id, e)
    where = (f"after step {after_step_index}"
             if after_step_index is not None else "appended")
    ctx.deps.tool_calls.append({
        "tool": "add_protocol_step", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "name": name,
    })
    return ProtocolMutationResult(
        ok=True, protocol_id=protocol_id,
        summary=f"Added step '{name}' ({where}).",
    )


async def remove_protocol_step(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    step_index: int,
) -> ProtocolMutationResult:
    """Delete the unit-op step at the given 0-based index."""
    pid = UUID(protocol_id)
    try:
        await remove_step_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            step_index=step_index,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "remove_protocol_step", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append({
        "tool": "remove_protocol_step", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "step_index": step_index,
    })
    return ProtocolMutationResult(
        ok=True, protocol_id=protocol_id,
        summary=f"Removed step {step_index}.",
    )


async def reorder_protocol_steps(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    ordered_step_indices: list[int],
) -> ProtocolMutationResult:
    """Reorder unit-op steps. Pass a permutation of 0..N-1."""
    pid = UUID(protocol_id)
    try:
        await reorder_steps_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            ordered_step_indices=ordered_step_indices,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "reorder_protocol_steps", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append({
        "tool": "reorder_protocol_steps", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "order": ordered_step_indices,
    })
    return ProtocolMutationResult(
        ok=True, protocol_id=protocol_id,
        summary=f"Reordered steps to {ordered_step_indices}.",
    )


async def replace_step_unit_op(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    step_index: int,
    new_unit_op_name: str,
) -> ProtocolMutationResult:
    """Swap the underlying unit op for an existing step. Label is preserved."""
    pid = UUID(protocol_id)
    try:
        await replace_step_unit_op_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            step_index=step_index, new_unit_op_name=new_unit_op_name,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "replace_step_unit_op", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _mutation_error(protocol_id, e)
    ctx.deps.tool_calls.append({
        "tool": "replace_step_unit_op", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "step_index": step_index,
        "new_unit_op_name": new_unit_op_name,
    })
    return ProtocolMutationResult(
        ok=True, protocol_id=protocol_id,
        summary=f"Replaced step {step_index} unit op with '{new_unit_op_name}'.",
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/tools.py \
        backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(F-0082): chat tools for protocol metadata + graph mutations"
```

---

## Task 12: Role tools

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py`
- Modify: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_subagents_protocol_builder.py`:

```python
from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_role, list_protocol_roles, remove_protocol_role,
    update_protocol_role)


@pytest.mark.asyncio
async def test_list_protocol_roles_tool(monkeypatch):
    ctx = make_ctx()

    async def fake(db, **kwargs):
        from app.models.science import ProtocolRole
        r1 = ProtocolRole(name="Op", color="#fff", sort_order=0)
        r1.id = _uuid.uuid4()
        return [r1]

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.list_roles_service",
        fake,
    )
    result = await list_protocol_roles(ctx, protocol_id=str(_uuid.uuid4()))
    assert result.ok is True
    assert result.roles[0].name == "Op"


@pytest.mark.asyncio
async def test_add_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        from app.models.science import ProtocolRole
        r = ProtocolRole(name=kwargs["name"], color="#fff", sort_order=0)
        r.id = _uuid.uuid4()
        return r

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.add_role_service",
        fake,
    )
    result = await add_protocol_role(
        ctx, protocol_id=str(_uuid.uuid4()), name="Operator",
    )
    assert captured["name"] == "Operator"
    assert result.ok is True


@pytest.mark.asyncio
async def test_update_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        from app.models.science import ProtocolRole
        r = ProtocolRole(name=kwargs.get("name") or "X", color="#fff",
                         sort_order=0)
        r.id = kwargs["role_id"]
        return r

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_role_service",
        fake,
    )
    rid = _uuid.uuid4()
    result = await update_protocol_role(ctx, role_id=str(rid), name="New")
    assert captured["role_id"] == rid
    assert captured["name"] == "New"
    assert result.ok is True


@pytest.mark.asyncio
async def test_remove_protocol_role_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.remove_role_service",
        fake,
    )
    rid = _uuid.uuid4()
    result = await remove_protocol_role(ctx, role_id=str(rid))
    assert captured["role_id"] == rid
    assert result.ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v -k "_role"`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the role tools**

In `backend/app/services/ai/subagents/protocol_builder/tools.py`, add imports:

```python
from app.services.protocols.roles import (
    add_role as add_role_service, list_roles as list_roles_service,
    remove_role as remove_role_service, update_role as update_role_service,
)
```

Append:

```python
# ─── Role tools ────────────────────────────────────────────────────────────────


@dataclass
class RoleItem:
    id: str
    name: str
    color: str
    sort_order: int


@dataclass
class ListRolesResult:
    ok: bool
    total: int
    roles: list[RoleItem]
    summary: str


@dataclass
class RoleMutationResult:
    ok: bool
    role_id: str
    summary: str


def _role_error(role_id: str, exc: ValueError) -> RoleMutationResult:
    return RoleMutationResult(ok=False, role_id=role_id, summary=str(exc))


async def list_protocol_roles(
    ctx: RunContext[ChatDeps], protocol_id: str
) -> ListRolesResult:
    """List roles on the given protocol, sorted by sort_order."""
    pid = UUID(protocol_id)
    try:
        roles = await list_roles_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "list_protocol_roles", "subagent": "protocol_builder",
            "error": str(e),
        })
        return ListRolesResult(ok=False, total=0, roles=[], summary=str(e))
    ctx.deps.tool_calls.append({
        "tool": "list_protocol_roles", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "results": len(roles),
    })
    return ListRolesResult(
        ok=True, total=len(roles),
        roles=[
            RoleItem(id=str(r.id), name=r.name, color=r.color,
                     sort_order=r.sort_order)
            for r in roles
        ],
        summary=f"Found {len(roles)} role(s) on protocol.",
    )


async def add_protocol_role(
    ctx: RunContext[ChatDeps],
    protocol_id: str,
    name: str,
    color: str = "#94a3b8",
    sort_order: int | None = None,
) -> RoleMutationResult:
    """Add a new role to a DRAFT protocol."""
    pid = UUID(protocol_id)
    try:
        role = await add_role_service(
            ctx.deps.db, user_id=ctx.deps.user_id, protocol_id=pid,
            name=name, color=color, sort_order=sort_order,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "add_protocol_role", "subagent": "protocol_builder",
            "error": str(e),
        })
        return RoleMutationResult(ok=False, role_id="", summary=str(e))
    ctx.deps.tool_calls.append({
        "tool": "add_protocol_role", "subagent": "protocol_builder",
        "protocol_id": protocol_id, "role_id": str(role.id),
    })
    return RoleMutationResult(
        ok=True, role_id=str(role.id),
        summary=f"Added role '{name}'.",
    )


async def update_protocol_role(
    ctx: RunContext[ChatDeps],
    role_id: str,
    name: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
) -> RoleMutationResult:
    """Patch a role's name, color, or sort_order on a DRAFT protocol."""
    rid = UUID(role_id)
    try:
        await update_role_service(
            ctx.deps.db, user_id=ctx.deps.user_id, role_id=rid,
            name=name, color=color, sort_order=sort_order,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "update_protocol_role", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _role_error(role_id, e)
    fields = [k for k, v in (("name", name), ("color", color),
                              ("sort_order", sort_order)) if v is not None]
    ctx.deps.tool_calls.append({
        "tool": "update_protocol_role", "subagent": "protocol_builder",
        "role_id": role_id, "fields_updated": fields,
    })
    return RoleMutationResult(
        ok=True, role_id=role_id,
        summary=f"Updated role ({', '.join(fields)}).",
    )


async def remove_protocol_role(
    ctx: RunContext[ChatDeps], role_id: str
) -> RoleMutationResult:
    """Remove a role from a DRAFT protocol."""
    rid = UUID(role_id)
    try:
        await remove_role_service(
            ctx.deps.db, user_id=ctx.deps.user_id, role_id=rid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "remove_protocol_role", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _role_error(role_id, e)
    ctx.deps.tool_calls.append({
        "tool": "remove_protocol_role", "subagent": "protocol_builder",
        "role_id": role_id,
    })
    return RoleMutationResult(
        ok=True, role_id=role_id, summary="Removed role.",
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/tools.py \
        backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(F-0082): chat tools for protocol roles"
```

---

## Task 13: Unit op tools — `update_unit_op`, `elevate_unit_op_scope`

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py`
- Modify: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/test_subagents_protocol_builder.py`:

```python
from app.services.ai.subagents.protocol_builder.tools import (
    elevate_unit_op_scope, update_unit_op)


@pytest.mark.asyncio
async def test_update_unit_op_tool(monkeypatch):
    ctx = make_ctx()
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.id = kwargs["unit_op_id"]
        m.name = kwargs.get("name") or "Old"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.update_unit_op_definition_service",
        fake,
    )
    uoid = _uuid.uuid4()
    result = await update_unit_op(
        ctx, unit_op_id=str(uoid), description="new desc",
    )
    assert captured["unit_op_id"] == uoid
    assert captured["description"] == "new desc"
    assert captured["is_org_admin"] is False  # from ChatDeps
    assert result.ok is True


@pytest.mark.asyncio
async def test_elevate_unit_op_scope_tool(monkeypatch):
    ctx = make_ctx()
    ctx.deps.is_org_admin = True
    captured = {}

    async def fake(db, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.id = kwargs["unit_op_id"]
        m.name = "X"
        return m

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.elevate_unit_op_scope_service",
        fake,
    )
    uoid = _uuid.uuid4()
    result = await elevate_unit_op_scope(ctx, unit_op_id=str(uoid))
    assert captured["unit_op_id"] == uoid
    assert captured["is_org_admin"] is True
    assert result.ok is True


@pytest.mark.asyncio
async def test_elevate_returns_error_when_not_admin(monkeypatch):
    ctx = make_ctx()  # is_org_admin defaults False

    async def fake(db, **kwargs):
        raise ValueError("Only organization admins can elevate unit ops.")

    monkeypatch.setattr(
        "app.services.ai.subagents.protocol_builder.tools.elevate_unit_op_scope_service",
        fake,
    )
    result = await elevate_unit_op_scope(ctx, unit_op_id=str(_uuid.uuid4()))
    assert result.ok is False
    assert "admin" in result.summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v -k "update_unit_op_tool or elevate"`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the unit-op tools**

In `backend/app/services/ai/subagents/protocol_builder/tools.py`, add imports:

```python
from app.services.protocols.unit_ops import (
    elevate_unit_op_scope as elevate_unit_op_scope_service,
    update_unit_op_definition as update_unit_op_definition_service,
)
```

Append:

```python
# ─── Unit op tools (update + elevate) ──────────────────────────────────────────


@dataclass
class UnitOpMutationResult:
    ok: bool
    unit_op_id: str
    name: str
    summary: str


def _uo_error(unit_op_id: str, exc: ValueError) -> UnitOpMutationResult:
    return UnitOpMutationResult(
        ok=False, unit_op_id=unit_op_id, name="", summary=str(exc),
    )


async def update_unit_op(
    ctx: RunContext[ChatDeps],
    unit_op_id: str,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    param_schema: dict[str, Any] | None = None,
    result_schema: dict[str, Any] | None = None,
) -> UnitOpMutationResult:
    """Patch an existing unit op definition.

    Org-scoped ops require org-admin (resolved from ChatDeps.is_org_admin).
    Library-override rows are refused.
    """
    uoid = UUID(unit_op_id)
    try:
        op = await update_unit_op_definition_service(
            ctx.deps.db, user_id=ctx.deps.user_id, org_id=ctx.deps.org_id,
            is_org_admin=ctx.deps.is_org_admin, unit_op_id=uoid,
            name=name, category=category, description=description,
            param_schema=param_schema, result_schema=result_schema,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "update_unit_op", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _uo_error(unit_op_id, e)
    fields = [k for k, v in (
        ("name", name), ("category", category), ("description", description),
        ("param_schema", param_schema), ("result_schema", result_schema),
    ) if v is not None]
    ctx.deps.tool_calls.append({
        "tool": "update_unit_op", "subagent": "protocol_builder",
        "unit_op_id": unit_op_id, "fields_updated": fields,
    })
    return UnitOpMutationResult(
        ok=True, unit_op_id=str(op.id), name=op.name,
        summary=f"Updated unit op '{op.name}' ({', '.join(fields)}).",
    )


async def elevate_unit_op_scope(
    ctx: RunContext[ChatDeps], unit_op_id: str,
) -> UnitOpMutationResult:
    """Promote a project-scoped unit op to org-wide. Org-admin only."""
    uoid = UUID(unit_op_id)
    try:
        op = await elevate_unit_op_scope_service(
            ctx.deps.db, user_id=ctx.deps.user_id, org_id=ctx.deps.org_id,
            is_org_admin=ctx.deps.is_org_admin, unit_op_id=uoid,
        )
    except ValueError as e:
        ctx.deps.tool_calls.append({
            "tool": "elevate_unit_op_scope", "subagent": "protocol_builder",
            "error": str(e),
        })
        return _uo_error(unit_op_id, e)
    ctx.deps.tool_calls.append({
        "tool": "elevate_unit_op_scope", "subagent": "protocol_builder",
        "unit_op_id": unit_op_id,
    })
    return UnitOpMutationResult(
        ok=True, unit_op_id=str(op.id), name=op.name,
        summary=f"Elevated unit op '{op.name}' to org-wide scope.",
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/tools.py \
        backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(F-0082): chat tools update_unit_op and elevate_unit_op_scope"
```

---

## Task 14: Register all new tools + update prompt

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/config.py`
- Modify: `backend/app/services/ai/subagents/protocol_builder/prompt.md`
- Modify: `backend/tests/unit/test_subagents_protocol_builder.py`

- [ ] **Step 1: Extend the build-config test to assert every new tool is wired**

Replace `test_build_returns_subagent_config` in `backend/tests/unit/test_subagents_protocol_builder.py` with:

```python
def test_build_returns_subagent_config():
    from app.services.ai.subagents.protocol_builder.tools import (
        add_protocol_role, add_protocol_step, elevate_unit_op_scope,
        get_protocol, list_protocol_roles, list_protocols,
        remove_protocol_role, remove_protocol_step, replace_step_unit_op,
        reorder_protocol_steps, update_protocol_metadata,
        update_protocol_role, update_unit_op,
    )

    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_builder"
    assert cfg["model"] == "openai:gpt-4.1-mini"
    tools = cfg["agent_kwargs"]["tools"]
    expected = {
        list_projects, list_unit_ops, create_unit_op, create_protocol,
        validate_protocol, update_protocol_step,
        # F-0082 additions
        list_protocols, get_protocol, update_protocol_metadata,
        add_protocol_step, remove_protocol_step, reorder_protocol_steps,
        replace_step_unit_op,
        list_protocol_roles, add_protocol_role, update_protocol_role,
        remove_protocol_role,
        update_unit_op, elevate_unit_op_scope,
    }
    assert set(tools) >= expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_subagents_protocol_builder.py::test_build_returns_subagent_config -v`
Expected: FAIL — new tools not registered yet.

- [ ] **Step 3: Update `config.py` to register all new tools**

Replace `backend/app/services/ai/subagents/protocol_builder/config.py`:

```python
"""Config builder for the protocol_builder subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_role, add_protocol_step, create_protocol, create_unit_op,
    elevate_unit_op_scope, get_protocol, list_projects, list_protocol_roles,
    list_protocols, list_unit_ops, remove_protocol_role,
    remove_protocol_step, replace_step_unit_op, reorder_protocol_steps,
    update_protocol_metadata, update_protocol_role, update_protocol_step,
    update_unit_op, validate_protocol)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_builder subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_builder",
        description=(
            "Collaborates with the user to design, build, and edit Protocol "
            "records and their roles, plus manage custom unit-op definitions. "
            "Dispatch when the user wants to create a new protocol, edit an "
            "existing draft protocol's steps/metadata/roles, or modify or "
            "elevate the scope of a custom unit op."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "tools": [
                # Reads
                list_projects,
                list_protocols,
                get_protocol,
                list_unit_ops,
                list_protocol_roles,
                # Creation
                create_unit_op,
                create_protocol,
                # Validation
                validate_protocol,
                # Mutations (DRAFT-only)
                update_protocol_metadata,
                add_protocol_step,
                update_protocol_step,
                remove_protocol_step,
                reorder_protocol_steps,
                replace_step_unit_op,
                # Roles
                add_protocol_role,
                update_protocol_role,
                remove_protocol_role,
                # Unit op mutations
                update_unit_op,
                elevate_unit_op_scope,
            ],
        },
    )
```

- [ ] **Step 4: Update `prompt.md`**

Append to `backend/app/services/ai/subagents/protocol_builder/prompt.md`:

```markdown

---

## Editing existing protocols

You can also modify protocols the user already has. Workflow:

1. Use `list_protocols` to find candidates by name + project. Don't
   fabricate ids — show options if multiple match.
2. Use `get_protocol(protocol_id)` to read the current state before any
   mutation. The returned `step_count`, `roles`, and `graph` are your
   ground truth.
3. **Mutating tools only work on DRAFT protocols.** If a protocol's
   status is `APPROVED` or `PENDING_APPROVAL`, every mutating tool will
   return `ok=false` with `summary` saying *"Protocol is published —
   create a draft in the protocol editor first."* Relay that to the user
   verbatim and stop. Do not try to work around it. (A future flow will
   handle draft creation; for now the user must use the editor UI.)
4. Available mutations (DRAFT-only):
   - `update_protocol_metadata(protocol_id, name?, description?)`
   - `add_protocol_step(protocol_id, name, unit_op_name, ...,
     after_step_index?, role_id?)` — appends if `after_step_index` is
     omitted.
   - `update_protocol_step(protocol_id, step_index, description?,
     category?, param_schema?, params?, role_id?)`
   - `remove_protocol_step(protocol_id, step_index)`
   - `reorder_protocol_steps(protocol_id, ordered_step_indices)` —
     `ordered_step_indices` MUST be a permutation of `0..N-1`.
   - `replace_step_unit_op(protocol_id, step_index, new_unit_op_name)` —
     swaps the underlying unit op; the step's display label is preserved.

## Roles

Each protocol can have ProtocolRoles (swimlanes for different operators,
e.g. "Operator", "QA Reviewer"). Tools:
- `list_protocol_roles(protocol_id)`
- `add_protocol_role(protocol_id, name, color?, sort_order?)`
- `update_protocol_role(role_id, name?, color?, sort_order?)`
- `remove_protocol_role(role_id)`

To build out a role's chain of steps: call `add_protocol_role` first,
then `add_protocol_step(..., role_id=<new_role_id>)` per step. The new
nodes will be assigned to that role's lane via `parentId`.

## Unit op editing and scope ladder

Unit op definitions live at one of three scopes:
- **global** — built-in catalog (organization_id NULL, project_id NULL)
- **org** — org-wide custom op (organization_id set, project_id NULL)
- **project** — project-only custom op (both set)

Scope ladder for elevation: project → org. Tools:
- `update_unit_op(unit_op_id, name?, category?, description?, param_schema?,
  result_schema?)` — org-scoped updates require org-admin (the platform
  decides; you don't need to gate). Library-override rows refuse.
- `elevate_unit_op_scope(unit_op_id)` — promotes project → org. Org-admin
  only. Refuses if op is already org/global, is a library override, or if
  an org-scoped op with the same name exists.

If a tool returns `ok=false` because the user lacks admin rights, surface
that politely and suggest they ask an org admin.
```

- [ ] **Step 5: Run all subagent tests**

Run: `pytest tests/unit/test_subagents_protocol_builder.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/config.py \
        backend/app/services/ai/subagents/protocol_builder/prompt.md \
        backend/tests/unit/test_subagents_protocol_builder.py
git commit -m "feat(F-0082): register update tools + extend protocol_builder prompt"
```

---

## Task 15: Full test suite + lint

**Files:** none new — verifies the full stack.

- [ ] **Step 1: Run full backend unit suite**

Run: `pytest tests/unit/ -v`
Expected: All PASS.

- [ ] **Step 2: Run integration tests touching protocols / unit_ops / chat**

Run: `pytest tests/integration/ -k "protocol or unit_op or chat" -v`
Expected: PASS. If any fail because the endpoint refactor changed an exception path or a status code, fix the endpoint translation (don't change the service contract).

- [ ] **Step 3: Lint**

Run: `black app tests && isort app tests && mypy app`
Expected: clean (or unchanged-from-baseline mypy noise).

- [ ] **Step 4: Commit any lint fixups**

```bash
git status
# If there are formatting changes only:
git add -A
git commit -m "style(F-0082): black + isort"
```

If no changes, skip.

---

## Self-Review Notes

**Spec coverage:**
- Discovery & inspection: Tasks 1, 10
- Protocol metadata: Task 4 (service) + Task 11 (tool)
- Graph editing: Tasks 5–8 (services) + Task 11 (tools)
- Roles: Task 2 (service) + Task 12 (tool)
- Unit ops update + elevate: Task 3 (service) + Task 13 (tool)
- Cross-cutting (thin tools, dataclass results, prompt update): Tasks 10–14
- Endpoint refactor (DRY): Tasks 1, 2, 3, 4

**Out-of-scope items confirmed not in plan:** Draft-version materialization, `NeedsTargetDecision`, `update_protocol_edges`, inline-graph→UnitOp promotion, role-control gating, frontend changes.

**Type consistency:** Service functions consistently use `*, user_id, ..., protocol_id, ...` keyword-only after the db arg. Tool result dataclasses always have `ok: bool` and `summary: str`. Service errors are always `ValueError`; tools translate to `ok=False`. Step indices reference unit-op nodes only, 0-based.
