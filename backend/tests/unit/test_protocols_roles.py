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
    proto = Protocol(
        name="P2", project_id=proj.id, status="APPROVED", version_number=1, graph={}
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest.mark.asyncio
async def test_add_role_assigns_next_sort_order(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    r1 = await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="Operator"
    )
    r2 = await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="Reviewer"
    )
    assert r1.sort_order == 0
    assert r2.sort_order == 1


@pytest.mark.asyncio
async def test_add_role_refuses_on_published(
    db_session: AsyncSession, test_user: User, published_protocol: Protocol
):
    with pytest.raises(ValueError, match="published"):
        await add_role(
            db_session,
            user_id=test_user.id,
            protocol_id=published_protocol.id,
            name="X",
        )


@pytest.mark.asyncio
async def test_list_roles_returns_sorted(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    db_session.add_all(
        [
            ProtocolRole(protocol_id=draft_protocol.id, name="B", sort_order=2),
            ProtocolRole(protocol_id=draft_protocol.id, name="A", sort_order=0),
            ProtocolRole(protocol_id=draft_protocol.id, name="C", sort_order=1),
        ]
    )
    await db_session.flush()
    roles = await list_roles(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id
    )
    assert [r.name for r in roles] == ["A", "C", "B"]


@pytest.mark.asyncio
async def test_update_role_patches_fields(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    role = ProtocolRole(protocol_id=draft_protocol.id, name="Old", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    updated = await update_role(
        db_session, user_id=test_user.id, role_id=role.id, name="New", color="#ff0000"
    )
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
        await update_role(db_session, user_id=test_user.id, role_id=role.id, name="Y")


@pytest.mark.asyncio
async def test_remove_role_deletes(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    role = ProtocolRole(protocol_id=draft_protocol.id, name="X", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    await remove_role(db_session, user_id=test_user.id, role_id=role.id)
    remaining = await list_roles(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id
    )
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
async def test_add_role_appends_swimlane_node(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    draft_protocol.graph = {"nodes": [], "edges": [], "layout": "horizontal"}
    await db_session.flush()
    role = await add_role(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_protocol.id,
        name="Operator",
        color="#abcdef",
    )
    await db_session.refresh(draft_protocol)
    lane_nodes = [n for n in draft_protocol.graph["nodes"] if n["type"] == "swimLane"]
    assert len(lane_nodes) == 1
    lane = lane_nodes[0]
    assert lane["id"] == f"lane-{role.id}"
    assert lane["data"]["label"] == "Operator"
    assert lane["data"]["color"] == "#abcdef"
    assert lane["data"]["roleId"] == str(role.id)
    assert lane["data"]["orientation"] == "horizontal"
    assert lane["position"] == {"x": 0, "y": 0}


@pytest.mark.asyncio
async def test_add_role_offsets_subsequent_lanes_vertical(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    draft_protocol.graph = {"nodes": [], "edges": [], "layout": "vertical"}
    await db_session.flush()
    await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="A"
    )
    await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="B"
    )
    await db_session.refresh(draft_protocol)
    lanes = [n for n in draft_protocol.graph["nodes"] if n["type"] == "swimLane"]
    assert lanes[0]["position"] == {"x": 0, "y": 0}
    assert lanes[1]["position"] == {"x": 220, "y": 0}
    assert all(n["data"]["orientation"] == "vertical" for n in lanes)


@pytest.mark.asyncio
async def test_update_role_patches_swimlane_label_and_color(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    draft_protocol.graph = {"nodes": [], "edges": [], "layout": "horizontal"}
    await db_session.flush()
    role = await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="Old"
    )
    await update_role(
        db_session,
        user_id=test_user.id,
        role_id=role.id,
        name="New",
        color="#112233",
    )
    await db_session.refresh(draft_protocol)
    lane = next(
        n for n in draft_protocol.graph["nodes"] if n["id"] == f"lane-{role.id}"
    )
    assert lane["data"]["label"] == "New"
    assert lane["data"]["color"] == "#112233"


@pytest.mark.asyncio
async def test_remove_role_drops_lane_and_clears_parent(
    db_session: AsyncSession, test_user: User, draft_protocol: Protocol
):
    draft_protocol.graph = {"nodes": [], "edges": [], "layout": "horizontal"}
    await db_session.flush()
    role = await add_role(
        db_session, user_id=test_user.id, protocol_id=draft_protocol.id, name="R"
    )
    lane_id = f"lane-{role.id}"
    nested = {
        "id": "uo-1",
        "type": "unitOp",
        "parentId": lane_id,
        "extent": "parent",
        "position": {"x": 10, "y": 10},
        "data": {"label": "step"},
    }
    graph = dict(draft_protocol.graph)
    graph["nodes"] = list(graph["nodes"]) + [nested]
    draft_protocol.graph = graph
    await db_session.flush()

    await remove_role(db_session, user_id=test_user.id, role_id=role.id)
    await db_session.refresh(draft_protocol)
    nodes = draft_protocol.graph["nodes"]
    assert all(n["id"] != lane_id for n in nodes)
    step = next(n for n in nodes if n["id"] == "uo-1")
    assert "parentId" not in step
    assert "extent" not in step


@pytest.mark.asyncio
async def test_role_ops_require_view_or_edit(db_session: AsyncSession, test_user: User):
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
        await add_role(db_session, user_id=test_user.id, protocol_id=proto.id, name="X")
