"""Tests for services/protocols/graph.py — protocol graph mutations."""

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
from app.models.protocols import Protocol, ProtocolRole, UnitOpDefinition
from app.services.protocols.graph import (
    add_step,
    remove_step,
    reorder_steps,
    replace_step_unit_op,
)


def _seed_graph_with_n_steps(n: int) -> dict:
    """Build a graph dict with a Process Start + n unit-op nodes chained."""
    nodes = [
        {
            "id": "node-ps",
            "type": "processStart",
            "position": {"x": 0, "y": 0},
            "data": {},
        }
    ]
    edges = []
    prev = "node-ps"
    for i in range(n):
        nid = f"node-{i}"
        nodes.append(
            {
                "id": nid,
                "type": "unitOp",
                "position": {"x": 100 * (i + 1), "y": 0},
                "data": {
                    "label": f"Step {i}",
                    "category": "C",
                    "duration_min": 10,
                    "params": {},
                    "paramSchema": {},
                },
            }
        )
        edges.append({"id": f"edge-{i}", "source": prev, "target": nid})
        prev = nid
    return {"nodes": nodes, "edges": edges, "layout": "horizontal"}


@pytest_asyncio.fixture
async def draft_proto(
    db_session: AsyncSession, test_org: Organization, test_user: User
) -> Protocol:
    proj = Project(name="g1", organization_id=test_org.id, owner_id=test_user.id, slug="g1")
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
        name="P",
        project_id=proj.id,
        status="DRAFT",
        graph=_seed_graph_with_n_steps(2),
        slug="p-draft",
        owner_org_id=test_org.id,
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest.mark.asyncio
async def test_add_step_appends_when_no_position(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    updated = await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="New Step",
        unit_op_name="Custom",
        duration_min=15,
        description="do it",
        category="Cell Culture",
    )
    nodes = updated.graph["nodes"]
    edges = updated.graph["edges"]
    unit_ops = [n for n in nodes if n["type"] == "unitOp"]
    assert len(unit_ops) == 3
    assert unit_ops[-1]["data"]["label"] == "New Step"
    assert len(edges) == 3
    assert edges[-1]["target"] == unit_ops[-1]["id"]
    assert edges[-1]["source"] == unit_ops[-2]["id"]


@pytest.mark.asyncio
async def test_add_step_inserts_after_index(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    updated = await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="Middle",
        unit_op_name="X",
        after_step_index=0,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    assert [n["data"]["label"] for n in unit_ops] == ["Step 0", "Middle", "Step 1"]
    edges = updated.graph["edges"]
    assert len(edges) == 3
    chain_targets = {e["source"]: e["target"] for e in edges}
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
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="Roled",
        unit_op_name="X",
        role_id=role.id,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    new_node = next(n for n in unit_ops if n["data"]["label"] == "Roled")
    assert new_node.get("parentId") == f"lane-{role.id}"
    # First child of the lane lands at the standard inset slot.
    assert new_node["position"] == {"x": 20, "y": 60}


@pytest.mark.asyncio
async def test_add_step_stacks_children_inside_lane(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    role_id = uuid.uuid4()
    role = ProtocolRole(id=role_id, protocol_id=draft_proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    # Inject a swimLane node so grow_lane_to_fit has something to size.
    g = dict(draft_proto.graph)
    g["nodes"] = list(g["nodes"]) + [
        {
            "id": f"lane-{role_id}",
            "type": "swimLane",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": "Op",
                "roleId": str(role_id),
                "orientation": "horizontal",
            },
            "style": "width: 800px; height: 200px;",
        }
    ]
    draft_proto.graph = g
    await db_session.flush()

    for i in range(5):
        await add_step(
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            name=f"R{i}",
            unit_op_name="X",
            role_id=role.id,
        )
    await db_session.refresh(draft_proto)
    children = [
        n for n in draft_proto.graph["nodes"] if n.get("parentId") == f"lane-{role_id}"
    ]
    xs = sorted(c["position"]["x"] for c in children)
    assert xs == [20, 260, 500, 740, 980]
    # Lane should have grown to fit 5 children: 20 + 5*240 + 40 = 1260.
    lane = next(n for n in draft_proto.graph["nodes"] if n["id"] == f"lane-{role_id}")
    assert lane["width"] == 1260
    assert lane["height"] == 200


@pytest.mark.asyncio
async def test_add_step_refuses_on_published(
    db_session: AsyncSession, test_org: Organization, test_user: User
):
    proj = Project(name="g2", organization_id=test_org.id, owner_id=test_user.id, slug="g2")
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
        name="Pub",
        project_id=proj.id,
        status="APPROVED",
        version_number=1,
        graph=_seed_graph_with_n_steps(1),
        slug="pub",
        owner_org_id=test_org.id,
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="published"):
        await add_step(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="X",
            unit_op_name="X",
        )


@pytest.mark.asyncio
async def test_add_step_refuses_without_edit_perm(
    db_session: AsyncSession, test_user: User
):
    other_org = Organization(name="oo", subscription_tier="ESSENTIALS")
    db_session.add(other_org)
    await db_session.flush()
    proj = Project(name="hidden", organization_id=other_org.id, owner_id=uuid.uuid4(), slug="hidden")
    db_session.add(proj)
    await db_session.flush()
    proto = Protocol(
        name="H",
        project_id=proj.id,
        status="DRAFT",
        graph=_seed_graph_with_n_steps(1),
        slug="h",
        owner_org_id=other_org.id,
    )
    db_session.add(proto)
    await db_session.flush()
    with pytest.raises(ValueError, match="permission"):
        await add_step(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            name="X",
            unit_op_name="X",
        )


@pytest.mark.asyncio
async def test_add_step_index_out_of_range(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="out of range"):
        await add_step(
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            name="X",
            unit_op_name="X",
            after_step_index=99,
        )


@pytest.mark.asyncio
async def test_remove_step_drops_node_and_rewires(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    updated = await remove_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
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
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            step_index=5,
        )


@pytest.mark.asyncio
async def test_reorder_steps_reverses_chain(
    db_session: AsyncSession, test_user: User, test_org: Organization
):
    proj = Project(name="ro", organization_id=test_org.id, owner_id=test_user.id, slug="ro")
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
        name="R",
        project_id=proj.id,
        status="DRAFT",
        graph=_seed_graph_with_n_steps(3),
        slug="r",
        owner_org_id=test_org.id,
    )
    db_session.add(proto)
    await db_session.flush()

    updated = await reorder_steps(
        db_session,
        user_id=test_user.id,
        protocol_id=proto.id,
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
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            ordered_step_indices=[0, 0],
        )
    with pytest.raises(ValueError, match="permutation"):
        await reorder_steps(
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            ordered_step_indices=[0],
        )


@pytest.mark.asyncio
async def test_replace_step_unit_op_uses_catalog(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
    draft_proto: Protocol,
):
    op = UnitOpDefinition(
        name="Cell Seeding",
        category="Cell Culture",
        description="seed cells",
        param_schema={"properties": {"vol": {"type": "number"}}},
        organization_id=test_org.id,
        project_id=None,
    )
    db_session.add(op)
    await db_session.flush()
    updated = await replace_step_unit_op(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        step_index=0,
        new_unit_op_name="Cell Seeding",
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    target = unit_ops[0]
    assert target["data"]["unitOpId"] == str(op.id)
    assert target["data"]["category"] == "Cell Culture"
    assert target["data"]["label"] == "Step 0"
    assert "vol" in target["data"]["paramSchema"]["properties"]


@pytest.mark.asyncio
async def test_replace_step_unit_op_unknown_op_raises(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    with pytest.raises(ValueError, match="not found"):
        await replace_step_unit_op(
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            step_index=0,
            new_unit_op_name="Nope",
        )


@pytest.mark.asyncio
async def test_add_step_top_level_packs_chain_no_overlap(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """Adding a top-level (no-role) step must position the new node such
    that no two top-level chain steps overlap. The seed has two unit ops
    at (100, 0) and (200, 0) which would otherwise overlap each other
    after the agent inserts a third at the hardcoded (100, 200)."""
    from app.services.protocols.graph import add_step
    from app.services.protocols.lane_layout import CHILD_X_STEP

    updated = await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="New",
        unit_op_name="X",
    )
    top_level = [
        n
        for n in updated.graph["nodes"]
        if n.get("type") == "unitOp" and not n.get("parentId")
    ]
    xs = [n["position"]["x"] for n in top_level]
    # Anchor = first existing step's position (100, 0). Uniform spacing.
    assert xs == [100, 100 + CHILD_X_STEP, 100 + 2 * CHILD_X_STEP]
    # No two steps share the same x → no visual stack.
    assert len(set(xs)) == len(xs)


@pytest.mark.asyncio
async def test_add_step_top_level_middle_insert_no_overlap(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """Inserting a step in the middle of the chain re-flows so the new
    node and its predecessors/successors don't collide."""
    from app.services.protocols.graph import add_step
    from app.services.protocols.lane_layout import CHILD_X_STEP

    updated = await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="Middle",
        unit_op_name="X",
        after_step_index=0,
    )
    unit_ops = [n for n in updated.graph["nodes"] if n["type"] == "unitOp"]
    xs = [n["position"]["x"] for n in unit_ops]
    assert xs == [100, 100 + CHILD_X_STEP, 100 + 2 * CHILD_X_STEP]
    labels = [n["data"]["label"] for n in unit_ops]
    assert labels == ["Step 0", "Middle", "Step 1"]


@pytest.mark.asyncio
async def test_relayout_chain_fixes_legacy_overlap(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """A graph whose top-level steps were placed at the same legacy
    (100, 200) slot — the symptom we're trying to fix — gets spaced out."""
    from app.services.protocols.graph import relayout_chain
    from app.services.protocols.lane_layout import CHILD_X_STEP

    # Force the seed's two unit ops to the legacy overlapping slot.
    g = dict(draft_proto.graph)
    nodes = [dict(n) for n in g["nodes"]]
    for n in nodes:
        if n.get("type") == "unitOp":
            n["position"] = {"x": 100, "y": 200}
    g["nodes"] = nodes
    draft_proto.graph = g
    await db_session.flush()

    updated = await relayout_chain(
        db_session, user_id=test_user.id, protocol_id=draft_proto.id
    )
    top_level = [
        n
        for n in updated.graph["nodes"]
        if n.get("type") == "unitOp" and not n.get("parentId")
    ]
    xs = [n["position"]["x"] for n in top_level]
    assert xs == [100, 100 + CHILD_X_STEP]


# ─── set_node_position ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_node_position_top_level_writes_absolute(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """Top-level (no parentId) node: write absolute x/y as given."""
    from app.services.protocols.graph import set_node_position

    target_id = next(
        n["id"] for n in draft_proto.graph["nodes"] if n.get("type") == "unitOp"
    )
    updated = await set_node_position(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        node_id=target_id,
        x=425,
        y=275,
    )
    moved = next(n for n in updated.graph["nodes"] if n["id"] == target_id)
    assert moved["position"] == {"x": 425, "y": 275}
    # Untouched nodes stay where they were.
    other_unit_ops = [
        n
        for n in updated.graph["nodes"]
        if n.get("type") == "unitOp" and n["id"] != target_id
    ]
    for n in other_unit_ops:
        assert n["position"]["x"] != 425 or n["position"]["y"] != 275


@pytest.mark.asyncio
async def test_set_node_position_lane_child_writes_lane_relative(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """A child of a swimlane already carries lane-relative coords. The
    position the agent passes is interpreted in that same lane-relative
    frame — the service writes it through verbatim."""
    from app.services.protocols.graph import set_node_position

    role_id = uuid.uuid4()
    role = ProtocolRole(id=role_id, protocol_id=draft_proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    g = dict(draft_proto.graph)
    g["nodes"] = list(g["nodes"]) + [
        {
            "id": f"lane-{role_id}",
            "type": "swimLane",
            "position": {"x": 0, "y": 400},
            "width": 800,
            "height": 200,
            "data": {
                "label": "Op",
                "roleId": str(role_id),
                "orientation": "horizontal",
            },
        }
    ]
    draft_proto.graph = g
    await db_session.flush()

    from app.services.protocols.graph import add_step

    await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="Lane child",
        unit_op_name="X",
        role_id=role_id,
    )
    await db_session.refresh(draft_proto)
    child = next(
        n
        for n in draft_proto.graph["nodes"]
        if n.get("data", {}).get("label") == "Lane child"
    )
    updated = await set_node_position(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        node_id=child["id"],
        x=260,
        y=60,
    )
    moved = next(n for n in updated.graph["nodes"] if n["id"] == child["id"])
    assert moved["position"] == {"x": 260, "y": 60}
    assert moved.get("parentId") == f"lane-{role_id}"


@pytest.mark.asyncio
async def test_set_node_position_grows_lane_when_child_extends_past(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    """If the requested lane-relative position would push the child past
    the lane's current bounds, the lane grows along the layout axis to fit."""
    from app.services.protocols.graph import add_step, set_node_position

    role_id = uuid.uuid4()
    role = ProtocolRole(id=role_id, protocol_id=draft_proto.id, name="Op", sort_order=0)
    db_session.add(role)
    await db_session.flush()
    g = dict(draft_proto.graph)
    g["nodes"] = list(g["nodes"]) + [
        {
            "id": f"lane-{role_id}",
            "type": "swimLane",
            "position": {"x": 0, "y": 400},
            "width": 800,
            "height": 200,
            "data": {
                "label": "Op",
                "roleId": str(role_id),
                "orientation": "horizontal",
            },
        }
    ]
    draft_proto.graph = g
    await db_session.flush()
    await add_step(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        name="Lane child",
        unit_op_name="X",
        role_id=role_id,
    )
    await db_session.refresh(draft_proto)
    child = next(
        n
        for n in draft_proto.graph["nodes"]
        if n.get("data", {}).get("label") == "Lane child"
    )
    # x=900 + default node width 220 → 1120, beyond initial lane width 800.
    updated = await set_node_position(
        db_session,
        user_id=test_user.id,
        protocol_id=draft_proto.id,
        node_id=child["id"],
        x=900,
        y=60,
    )
    lane = next(n for n in updated.graph["nodes"] if n["id"] == f"lane-{role_id}")
    assert lane["width"] >= 1120


@pytest.mark.asyncio
async def test_set_node_position_unknown_node_raises(
    db_session: AsyncSession, test_user: User, draft_proto: Protocol
):
    from app.services.protocols.graph import set_node_position

    with pytest.raises(ValueError, match="not found"):
        await set_node_position(
            db_session,
            user_id=test_user.id,
            protocol_id=draft_proto.id,
            node_id="node-does-not-exist",
            x=0,
            y=0,
        )


@pytest.mark.asyncio
async def test_set_node_position_refuses_on_published(
    db_session: AsyncSession, test_org: Organization, test_user: User
):
    from app.services.protocols.graph import set_node_position

    proj = Project(name="g3", organization_id=test_org.id, owner_id=test_user.id, slug="g3")
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
        name="Pub",
        project_id=proj.id,
        status="APPROVED",
        version_number=1,
        graph=_seed_graph_with_n_steps(1),
        slug="pub-g3",
        owner_org_id=test_org.id,
    )
    db_session.add(proto)
    await db_session.flush()
    target = next(n["id"] for n in proto.graph["nodes"] if n.get("type") == "unitOp")
    with pytest.raises(ValueError, match="published"):
        await set_node_position(
            db_session,
            user_id=test_user.id,
            protocol_id=proto.id,
            node_id=target,
            x=10,
            y=10,
        )
