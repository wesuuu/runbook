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
from app.services.protocols.lane_layout import (LANE_DEFAULT_HORIZONTAL,
                                                LANE_DEFAULT_VERTICAL,
                                                TOP_LEVEL_DEFAULT_X,
                                                TOP_LEVEL_DEFAULT_Y,
                                                grow_lane_to_fit,
                                                lane_relative_position,
                                                relayout_top_level_chain)


async def _load_and_guard(
    db: AsyncSession, user_id: UUID, protocol_id: UUID
) -> "WorkingDraft":
    from app.services.protocols.draft import (WorkingDraft,
                                              resolve_working_draft)

    proto = (
        await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    ).scalar_one_or_none()
    if proto is None:
        raise ValueError(f"Protocol {protocol_id} not found")
    if proto.project_id is not None:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            proto.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")
    return await resolve_working_draft(db, proto)


def _split_nodes(graph: dict) -> tuple[list[dict], list[int], list[int]]:
    """Return (nodes, ps_indices, unit_op_indices)."""
    nodes = list(graph.get("nodes", []))
    ps_idx = [i for i, n in enumerate(nodes) if n.get("type") == "processStart"]
    uo_idx = [i for i, n in enumerate(nodes) if n.get("type") == "unitOp"]
    return nodes, ps_idx, uo_idx


def _rebuild_chain_edges(
    existing_edges: list[dict],
    ps_id: str,
    ordered_unit_op_ids: list[str],
    all_node_ids: set[str] | None = None,
) -> list[dict]:
    """Replace the linear chain edges with ps -> uo[0] -> uo[1] -> ...

    Non-chain edges (e.g. user-drawn cross-links) are preserved as-is, but
    only if both endpoints still reference live nodes. We detect chain edges
    as: source==ps_id, OR (source AND target are both unit-op nodes).
    """
    uo_set = set(ordered_unit_op_ids)
    valid = all_node_ids if all_node_ids is not None else uo_set | {ps_id}
    preserved = [
        e
        for e in existing_edges
        if e.get("source") != ps_id
        and not (e.get("source") in uo_set and e.get("target") in uo_set)
        and e.get("source") in valid
        and e.get("target") in valid
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
    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
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

    layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    if role_id is not None:
        from app.services.protocols.roles import assert_role_on_protocol

        await assert_role_on_protocol(db, protocol_id=protocol_id, role_id=role_id)
        lane_id = f"lane-{role_id}"
        position = lane_relative_position(nodes, lane_id, graph_layout=layout)
    else:
        lane_id = None
        position = {"x": TOP_LEVEL_DEFAULT_X, "y": TOP_LEVEL_DEFAULT_Y}

    new_node: dict[str, Any] = {
        "id": f"node-{uuid4()}",
        "type": "unitOp",
        "position": position,
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
    if lane_id is not None:
        new_node["parentId"] = lane_id
    nodes.insert(insert_pos, new_node)

    if lane_id is not None:
        nodes = grow_lane_to_fit(nodes, lane_id, graph_layout=layout)
    else:
        # Top-level insert: re-flow the chain row so the new node and its
        # siblings sit at uniform spacing along the layout axis. Without
        # this, a top-level add stacks every new step on the same default
        # (100, 200) slot and the agent has no way to space them out.
        nodes = relayout_top_level_chain(nodes, graph_layout=layout)

    new_uo_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
    all_ids = {n["id"] for n in nodes}
    edges = _rebuild_chain_edges(graph.get("edges", []), ps_id, new_uo_ids, all_ids)

    graph["nodes"] = nodes
    graph["edges"] = edges
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol


async def remove_step(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    step_index: int,
) -> Protocol:
    """Delete the unit-op node at the given 0-based step index."""
    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
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
    layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    nodes = relayout_top_level_chain(nodes, graph_layout=layout)
    ps_id = next(n["id"] for n in nodes if n.get("type") == "processStart")
    new_uo_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
    all_ids = {n["id"] for n in nodes}
    graph["nodes"] = nodes
    graph["edges"] = _rebuild_chain_edges(
        graph.get("edges", []), ps_id, new_uo_ids, all_ids
    )
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol


async def reorder_steps(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    ordered_step_indices: list[int],
) -> Protocol:
    """Reorder unit-op steps. ``ordered_step_indices`` is a permutation of
    range(n_unit_ops) — the new visual order."""
    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
    nodes, ps_idx, uo_idx = _split_nodes(graph)
    if not ps_idx:
        raise ValueError("Protocol graph has no Process Start node")
    n = len(uo_idx)
    if sorted(ordered_step_indices) != list(range(n)):
        raise ValueError(f"ordered_step_indices must be a permutation of 0..{n-1}")
    unit_ops = [nodes[i] for i in uo_idx]
    new_unit_ops = [unit_ops[i] for i in ordered_step_indices]
    new_nodes = list(nodes)
    for slot, new_uo in zip(uo_idx, new_unit_ops):
        new_nodes[slot] = new_uo
    layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    new_nodes = relayout_top_level_chain(new_nodes, graph_layout=layout)
    ps_id = next(n["id"] for n in new_nodes if n.get("type") == "processStart")
    new_uo_ids = [n["id"] for n in new_nodes if n.get("type") == "unitOp"]
    all_ids = {n["id"] for n in new_nodes}
    graph["nodes"] = new_nodes
    graph["edges"] = _rebuild_chain_edges(
        graph.get("edges", []), ps_id, new_uo_ids, all_ids
    )
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol


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

    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
    nodes, _, uo_idx = _split_nodes(graph)
    if step_index < 0 or step_index >= len(uo_idx):
        raise ValueError(
            f"step_index {step_index} out of range "
            f"(protocol has {len(uo_idx)} unit op steps)"
        )
    op = (
        (
            await db.execute(
                select(UnitOpDefinition).where(
                    UnitOpDefinition.name == new_unit_op_name
                )
            )
        )
        .scalars()
        .first()
    )
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
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol


_DEFAULT_CHILD_W = 220
_DEFAULT_CHILD_H = 100


def _grow_lane_for_child_bbox(
    nodes: list[dict[str, Any]],
    lane_id: str,
    *,
    graph_layout: str,
) -> list[dict[str, Any]]:
    """Grow a lane so every parented child's bbox stays inside its bounds.

    `grow_lane_to_fit` only handles the count-based floor; this complements
    it by considering actual child positions/dimensions. Idempotent — never
    shrinks the lane.
    """
    out = list(nodes)
    lane_idx = next((i for i, n in enumerate(out) if n.get("id") == lane_id), None)
    if lane_idx is None:
        return out
    lane = out[lane_idx]
    if lane.get("type") != "swimLane":
        return out
    children = [c for c in out if c.get("parentId") == lane_id]
    if not children:
        return out
    max_right = 0.0
    max_bottom = 0.0
    for c in children:
        pos = c.get("position") or {}
        cx = float(pos.get("x", 0))
        cy = float(pos.get("y", 0))
        w_prop = c.get("width")
        h_prop = c.get("height")
        cw = float(w_prop) if isinstance(w_prop, (int, float)) else _DEFAULT_CHILD_W
        ch = float(h_prop) if isinstance(h_prop, (int, float)) else _DEFAULT_CHILD_H
        max_right = max(max_right, cx + cw)
        max_bottom = max(max_bottom, cy + ch)
    orientation = (lane.get("data") or {}).get("orientation")
    if orientation not in ("horizontal", "vertical"):
        orientation = graph_layout
    current_w = lane.get("width")
    current_h = lane.get("height")
    cw = (
        float(current_w)
        if isinstance(current_w, (int, float))
        else float(
            LANE_DEFAULT_VERTICAL[0]
            if orientation == "vertical"
            else LANE_DEFAULT_HORIZONTAL[0]
        )
    )
    ch = (
        float(current_h)
        if isinstance(current_h, (int, float))
        else float(
            LANE_DEFAULT_VERTICAL[1]
            if orientation == "vertical"
            else LANE_DEFAULT_HORIZONTAL[1]
        )
    )
    new_w = max(cw, max_right + 20)
    new_h = max(ch, max_bottom + 20)
    updated = dict(lane)
    updated["width"] = int(new_w)
    updated["height"] = int(new_h)
    out[lane_idx] = updated
    return out


async def set_node_position(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
    node_id: str,
    x: float,
    y: float,
) -> Protocol:
    """Move a single node to ``(x, y)``.

    Top-level nodes (no ``parentId``) get an absolute world position.
    Children of a swimLane (``parentId="lane-…"``) get a lane-relative
    position — xyflow renders them inside the lane's coordinate frame, so
    the agent should pass coordinates in that same frame. After the move,
    if the node lives inside a lane, the lane is grown along the layout
    axis to fit (idempotent — never shrinks below the user's manual size).
    Other nodes are not touched.
    """
    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    target_index = next(
        (i for i, n in enumerate(nodes) if n.get("id") == node_id), None
    )
    if target_index is None:
        raise ValueError(f"Node {node_id!r} not found in protocol graph")
    moved = dict(nodes[target_index])
    moved["position"] = {"x": x, "y": y}
    nodes[target_index] = moved
    parent_id = moved.get("parentId")
    if isinstance(parent_id, str) and parent_id.startswith("lane-"):
        layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
        # `grow_lane_to_fit` sizes by child count, which is the right answer
        # when steps land on the canonical CHILD_*_STEP grid. A direct
        # `set_node_position` can place a child anywhere, so first ensure the
        # lane is at least big enough to enclose the actual child bbox; then
        # let `grow_lane_to_fit` apply the count-based floor.
        nodes = _grow_lane_for_child_bbox(nodes, parent_id, graph_layout=layout)
        nodes = grow_lane_to_fit(nodes, parent_id, graph_layout=layout)
    graph["nodes"] = nodes
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol


async def relayout_chain(
    db: AsyncSession,
    *,
    user_id: UUID,
    protocol_id: UUID,
) -> Protocol:
    """Re-pack top-level unit-op nodes at uniform spacing along the chain axis.

    For legacy graphs whose top-level steps were placed at the same
    hardcoded slot and now overlap visually. Children of swimlanes are
    untouched — their layout is owned by lane_relative_position. The first
    top-level node keeps its position so the chain row stays where the user
    last saw it; subsequent top-level nodes are spaced by ``CHILD_X_STEP``
    on x (horizontal layout) or ``CHILD_Y_STEP`` on y (vertical).
    """
    wg = await _load_and_guard(db, user_id, protocol_id)
    graph = dict(wg.graph)
    nodes = list(graph.get("nodes", []))
    layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    nodes = relayout_top_level_chain(nodes, graph_layout=layout)
    graph["nodes"] = nodes
    wg.set_graph(graph)
    await db.flush()
    return wg.protocol
