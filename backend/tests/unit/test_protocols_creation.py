"""Tests for services/protocols/creation.py — thin protocol creation service."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.projects import Project
from app.models.protocols import Protocol, ProtocolRole
from app.services.protocols.creation import (
    ProtocolSpec,
    ProtocolStep,
    create_protocol_from_spec,
    update_protocol_metadata,
    update_protocol_step,
)


@pytest_asyncio.fixture
async def project(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
) -> Project:
    p = Project(name="test-proj", organization_id=test_org.id, owner_id=test_user.id, slug="test-proj")
    db_session.add(p)
    await db_session.flush()
    perm = ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=test_user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=p.id,
        permission_level=PermissionLevel.EDIT.value,
    )
    db_session.add(perm)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_creates_protocol_from_spec(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    spec = ProtocolSpec(
        name="My Protocol",
        description="Bench-scale mAb",
        steps=[
            ProtocolStep(
                name="Buffer Mix", unit_op_name="Buffer Preparation", duration_min=15
            ),
            ProtocolStep(
                name="Inoculate", unit_op_name="Cell Seeding", duration_min=30
            ),
        ],
    )
    proto = await create_protocol_from_spec(
        db_session,
        user_id=test_user.id,
        project_name=project.name,
        spec=spec,
    )
    assert proto.name == "My Protocol"
    assert proto.project_id == project.id
    assert proto.status == "DRAFT"
    # 1 processStart + 2 step nodes; 2 edges chaining them
    assert len(proto.graph["nodes"]) == 3
    assert len(proto.graph["edges"]) == 2
    assert proto.graph["nodes"][0]["type"] == "processStart"


@pytest.mark.asyncio
async def test_raises_when_project_not_found(
    db_session: AsyncSession,
    test_user: User,
):
    spec = ProtocolSpec(
        name="X",
        description="",
        steps=[
            ProtocolStep(name="s", unit_op_name="s", duration_min=10),
        ],
    )
    with pytest.raises(ValueError, match="not found"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name="nonexistent",
            spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_without_edit_permission(
    db_session: AsyncSession,
    test_user: User,
):
    # Create a separate org/project that test_user is not a member of.
    other_org = Organization(name="other-org", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()

    p = Project(
        name="restricted-proj",
        organization_id=other_org.id,
        owner_id=uuid.uuid4(),
        slug="restricted-proj",
    )
    db_session.add(p)
    await db_session.flush()
    spec = ProtocolSpec(
        name="X",
        description="",
        steps=[
            ProtocolStep(name="s", unit_op_name="s", duration_min=10),
        ],
    )
    with pytest.raises(ValueError, match="permission"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name="restricted-proj",
            spec=spec,
        )


@pytest.mark.asyncio
async def test_raises_when_spec_has_no_steps(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    spec = ProtocolSpec(name="X", description="", steps=[])
    with pytest.raises(ValueError, match="step"):
        await create_protocol_from_spec(
            db_session,
            user_id=test_user.id,
            project_name=project.name,
            spec=spec,
        )


@pytest.mark.asyncio
async def test_update_protocol_metadata_patches_name_and_description(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    proto = Protocol(
        name="Old", description="o", project_id=project.id, status="DRAFT", graph={}, slug="old", owner_org_id=test_org.id
    )
    db_session.add(proto)
    await db_session.flush()
    updated = await update_protocol_metadata(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
        name="New",
        description="n",
    )
    assert updated.name == "New"
    assert updated.description == "n"


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_on_published(
    db_session: AsyncSession,
    test_user: User,
    project: Project,
):
    proto = Protocol(
        name="P", project_id=project.id, status="APPROVED", version_number=1, graph={}, slug="p-approved", owner_org_id=test_org.id
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_protocol_metadata(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="X",
        )


@pytest.mark.asyncio
async def test_update_protocol_metadata_refuses_without_perm(
    db_session: AsyncSession,
    test_user: User,
):
    other_org = Organization(name="o2", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="op", organization_id=other_org.id, owner_id=uuid.uuid4(), slug="op")
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(name="X", project_id=proj.id, status="DRAFT", graph={}, slug="x-op", owner_org_id=other_org.id)
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await update_protocol_metadata(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="Y",
        )


@pytest.mark.asyncio
async def test_update_protocol_step_refuses_on_published(
    db_session: AsyncSession, test_user: User, project: Project
):
    proto = Protocol(
        name="Pub",
        project_id=project.id,
        status="APPROVED",
        version_number=1,
        graph={
            "nodes": [
                {"id": "ps", "type": "processStart", "data": {}},
                {"id": "u0", "type": "unitOp", "data": {"label": "A"}},
            ],
            "edges": [{"id": "e", "source": "ps", "target": "u0"}],
        },
        slug="pub-step",
        owner_org_id=project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await update_protocol_step(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            step_index=0,
            description="x",
        )


@pytest.mark.asyncio
async def test_update_protocol_step_sets_parent_for_role(
    db_session: AsyncSession, test_user: User, project: Project
):
    proto = Protocol(
        name="P",
        project_id=project.id,
        status="DRAFT",
        graph={
            "nodes": [
                {"id": "ps", "type": "processStart", "data": {}},
                {"id": "u0", "type": "unitOp", "data": {"label": "A"}},
            ],
            "edges": [{"id": "e", "source": "ps", "target": "u0"}],
        },
        slug="p-role",
        owner_org_id=project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    role = ProtocolRole(protocol_id=proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()

    updated = await update_protocol_step(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
        step_index=0,
        role_id=role.id,
    )
    node = next(n for n in updated.graph["nodes"] if n["type"] == "unitOp")
    assert node.get("parentId") == f"lane-{role.id}"


@pytest.mark.asyncio
async def test_update_protocol_step_repositions_into_lane(
    db_session: AsyncSession, test_user: User, project: Project
):
    role_id = uuid.uuid4()
    lane_id = f"lane-{role_id}"
    proto = Protocol(
        name="P",
        project_id=project.id,
        status="DRAFT",
        graph={
            "layout": "horizontal",
            "nodes": [
                {"id": "ps", "type": "processStart", "data": {}},
                {
                    "id": "u0",
                    "type": "unitOp",
                    "position": {"x": 9999, "y": 9999},
                    "data": {"label": "A"},
                },
                {
                    "id": lane_id,
                    "type": "swimLane",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "label": "Op",
                        "roleId": str(role_id),
                        "orientation": "horizontal",
                    },
                    "style": "width: 800px; height: 200px;",
                },
            ],
            "edges": [{"id": "e", "source": "ps", "target": "u0"}],
        },
        slug="p-reposition",
        owner_org_id=project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    role = ProtocolRole(id=role_id, protocol_id=proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()

    updated = await update_protocol_step(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
        step_index=0,
        role_id=role.id,
    )
    node = next(n for n in updated.graph["nodes"] if n["id"] == "u0")
    assert node["parentId"] == lane_id
    # Stale absolute (9999, 9999) replaced with first-slot lane-relative.
    assert node["position"] == {"x": 20, "y": 60}


@pytest.mark.asyncio
async def test_update_protocol_step_grows_lane_for_many_children(
    db_session: AsyncSession, test_user: User, project: Project
):
    role_id = uuid.uuid4()
    lane_id = f"lane-{role_id}"
    nodes = [
        {"id": "ps", "type": "processStart", "data": {}},
        {
            "id": lane_id,
            "type": "swimLane",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "Op",
                "roleId": str(role_id),
                "orientation": "horizontal",
            },
            "style": "width: 800px; height: 200px;",
        },
    ]
    edges = []
    prev = "ps"
    for i in range(5):
        nid = f"u{i}"
        nodes.append(
            {
                "id": nid,
                "type": "unitOp",
                "position": {"x": 100, "y": 100},
                "data": {"label": f"S{i}"},
            }
        )
        edges.append({"id": f"e{i}", "source": prev, "target": nid})
        prev = nid

    # Pre-assign first 4 to the lane so the 5th update triggers growth.
    for i in range(4):
        nodes[i + 2]["parentId"] = lane_id

    proto = Protocol(
        name="P",
        project_id=project.id,
        status="DRAFT",
        graph={"layout": "horizontal", "nodes": nodes, "edges": edges},
        slug="p-grow",
        owner_org_id=project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    role = ProtocolRole(id=role_id, protocol_id=proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()

    updated = await update_protocol_step(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
        step_index=4,  # u4
        role_id=role.id,
    )
    lane = next(n for n in updated.graph["nodes"] if n["id"] == lane_id)
    # 20 + 5 * 240 + 40 = 1260
    assert lane["width"] == 1260
    assert lane["height"] == 200
