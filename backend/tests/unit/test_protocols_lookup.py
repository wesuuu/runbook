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
