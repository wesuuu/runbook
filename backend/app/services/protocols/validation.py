"""Validate a Protocol graph against structural and quality rules.

Pure function — no DB, no LLM. Callers fetch the graph + unit-op catalog
and pass them in. Used by the chat agent's `validate_protocol` tool to
self-check work after `create_protocol`, and reusable from any future
REST endpoint or background job.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.science import ProtocolRole, UnitOpDefinition

# Visual-bbox defaults used by layout-quality rules. These mirror the
# frontend node defaults (see protocolNodes.ts) and the lane-layout
# constants (services/protocols/lane_layout.py).
_DEFAULT_NODE_W = 220
_DEFAULT_NODE_H = 100
_LANE_DEFAULT_HORIZONTAL = (800, 200)
_LANE_DEFAULT_VERTICAL = (220, 500)
# Minimum visual gap between sibling unit-ops. The canonical sibling step
# (lane_layout.CHILD_X_STEP / CHILD_Y_STEP) leaves ~20px; anything tighter
# than this threshold reads as crowded.
_MIN_SIBLING_GAP = 10.0
# Chain peers (consecutive unit ops in the same parent frame) should sit
# in roughly a single row (horizontal) or column (vertical). Cross-axis
# drift beyond this threshold makes the chain hard to read.
_CHAIN_BAND_TOLERANCE = 30.0

_STYLE_DIM_RE = re.compile(r"\s*(width|height)\s*:\s*([0-9]+)\s*px\s*;?", re.IGNORECASE)

Severity = str  # "error" | "warning"


class ValidationIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    node_id: str | None = None


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue]


_PLACEHOLDER_DESCRIPTIONS = {"", "todo", "tbd", "n/a", "placeholder"}


def validate_protocol_graph(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
    roles: list[ProtocolRole] | None = None,
) -> ValidationResult:
    """Check a graph for structural and quality problems.

    Args:
        graph: The Protocol.graph JSONB.
        unit_ops: Org-visible UnitOpDefinitions for resolving `unitOpId`.
        roles: ProtocolRole rows for cross-checking that swimLane nodes
            and unit-op `parentId`s line up. When omitted, role/lane
            consistency checks are skipped.

    Returns:
        ValidationResult — `ok=False` if any issue has severity="error".
    """
    issues: list[ValidationIssue] = []
    nodes: list[dict[str, Any]] = list(graph.get("nodes", []))
    edges: list[dict[str, Any]] = list(graph.get("edges", []))

    process_starts = [n for n in nodes if n.get("type") == "processStart"]
    unit_op_nodes = [n for n in nodes if n.get("type") == "unitOp"]

    if not process_starts:
        issues.append(
            ValidationIssue(
                severity="error",
                code="missing_process_start",
                message=(
                    "Protocol has no Process Start node. Every protocol must "
                    "begin with one."
                ),
            )
        )

    component_starts = _process_starts_per_component(nodes, edges, process_starts)
    for component_idx, count in enumerate(component_starts):
        if count > 1:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="multiple_process_starts",
                    message=(
                        f"Connected component {component_idx} has {count} "
                        "Process Start nodes; expected exactly 1."
                    ),
                )
            )

    unit_op_ids = {str(op.id) for op in unit_ops}
    incoming_targets = {e.get("target") for e in edges}

    for n in unit_op_nodes:
        node_id = n.get("id") or "<unknown>"
        data = n.get("data") or {}
        label = data.get("label") or "<unnamed>"

        unit_op_id = data.get("unitOpId")
        if unit_op_id and str(unit_op_id) not in unit_op_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_unit_op_id",
                    message=(
                        f"Step '{label}' references unitOpId={unit_op_id} which "
                        "does not exist in the unit-op catalog."
                    ),
                    node_id=node_id,
                )
            )

        param_schema = data.get("paramSchema") or {}
        if not param_schema.get("properties"):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="empty_param_schema",
                    message=(
                        f"Step '{label}' has no parameter schema. Scientists "
                        "won't be able to set per-run values."
                    ),
                    node_id=node_id,
                )
            )

        description = (data.get("description") or "").strip().lower()
        if description in _PLACEHOLDER_DESCRIPTIONS:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_description",
                    message=(
                        f"Step '{label}' has no description. Add instructions "
                        "the technician should follow."
                    ),
                    node_id=node_id,
                )
            )

        if not unit_op_id and (data.get("category") or "").lower() in {"", "general"}:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="placeholder_category",
                    message=(
                        f"Step '{label}' has no unitOpId and category "
                        f"'{data.get('category', '')}'. Either match an existing "
                        "unit op or set a specific category (e.g. 'Media Prep')."
                    ),
                    node_id=node_id,
                )
            )

        parent_id = n.get("parentId")
        if parent_id and isinstance(parent_id, str) and parent_id.startswith("lane-"):
            lane_node_ids = {
                ln.get("id") for ln in nodes if ln.get("type") == "swimLane"
            }
            if parent_id not in lane_node_ids:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="orphaned_parent_id",
                        message=(
                            f"Step '{label}' has parentId={parent_id} but no "
                            "matching swimLane node exists. The step will not "
                            "render inside any role lane."
                        ),
                        node_id=node_id,
                    )
                )

        if node_id not in incoming_targets:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="disconnected_step",
                    message=(
                        f"Step '{label}' has no incoming edge. It is not "
                        "reachable from any Process Start."
                    ),
                    node_id=node_id,
                )
            )

    issues.extend(_branch_role_issues(nodes, edges, graph))
    issues.extend(_layout_quality_issues(nodes, graph))

    if roles is not None:
        lane_nodes = [n for n in nodes if n.get("type") == "swimLane"]
        lane_ids_by_role = {f"lane-{r.id}": r for r in roles}
        present_lane_ids = {ln.get("id") for ln in lane_nodes}
        children_by_lane: dict[str, int] = {}
        for n in unit_op_nodes:
            pid = n.get("parentId")
            if isinstance(pid, str) and pid.startswith("lane-"):
                children_by_lane[pid] = children_by_lane.get(pid, 0) + 1
        for lane_id, role in lane_ids_by_role.items():
            if lane_id not in present_lane_ids:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_lane_node",
                        message=(
                            f"Role '{role.name}' has no swimLane node in the "
                            "graph. Steps assigned to this role will not appear "
                            "inside its lane."
                        ),
                    )
                )
                continue
            if children_by_lane.get(lane_id, 0) == 0:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="empty_lane",
                        message=(
                            f"Role '{role.name}' has no steps in its lane. "
                            "Assign at least one step to this role or remove "
                            "the role."
                        ),
                        node_id=lane_id,
                    )
                )
        for ln in lane_nodes:
            ln_id = ln.get("id")
            if ln_id and ln_id not in lane_ids_by_role:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="orphaned_lane_node",
                        message=(
                            f"SwimLane node {ln_id} does not match any "
                            "ProtocolRole. Either remove the lane or recreate "
                            "the role."
                        ),
                        node_id=ln_id,
                    )
                )

    ok = not any(i.severity == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)


def _process_starts_per_component(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    process_starts: list[dict[str, Any]],
) -> list[int]:
    """Count Process Start nodes within each connected component.

    Returns a list of counts (one per component). Components with zero
    Process Starts are excluded — that case is handled by the
    'missing_process_start' rule when the count is zero overall.
    """
    if not nodes:
        return []
    adjacency: dict[str, set[str]] = {n["id"]: set() for n in nodes if "id" in n}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adjacency and t in adjacency:
            adjacency[s].add(t)
            adjacency[t].add(s)

    process_start_ids = {ps["id"] for ps in process_starts if "id" in ps}
    visited: set[str] = set()
    counts: list[int] = []
    for node_id in adjacency:
        if node_id in visited:
            continue
        stack = [node_id]
        component: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in component:
                continue
            component.add(cur)
            stack.extend(adjacency[cur])
        visited |= component
        ps_in_component = len(component & process_start_ids)
        if ps_in_component:
            counts.append(ps_in_component)
    return counts


def _read_dims_from_style(style: Any) -> tuple[float | None, float | None]:
    """Parse ``"width: …px; height: …px;"`` strings written by legacy graphs."""
    if not isinstance(style, str):
        return (None, None)
    width: float | None = None
    height: float | None = None
    for key, val in _STYLE_DIM_RE.findall(style):
        if key.lower() == "width" and width is None:
            width = float(val)
        elif key.lower() == "height" and height is None:
            height = float(val)
    return width, height


def _node_dims(node: dict[str, Any]) -> tuple[float, float]:
    """Return (width, height) for a unit-op node, with sensible defaults.

    Reads numeric ``width``/``height`` props first, falling back to the
    legacy ``style`` string, then to ``_DEFAULT_NODE_W`` / ``_DEFAULT_NODE_H``.
    """
    w_prop = node.get("width")
    h_prop = node.get("height")
    width = float(w_prop) if isinstance(w_prop, (int, float)) else None
    height = float(h_prop) if isinstance(h_prop, (int, float)) else None
    if width is None or height is None:
        style_w, style_h = _read_dims_from_style(node.get("style"))
        if width is None:
            width = style_w
        if height is None:
            height = style_h
    return (
        width if width is not None else float(_DEFAULT_NODE_W),
        height if height is not None else float(_DEFAULT_NODE_H),
    )


def _lane_dims(lane_node: dict[str, Any], graph_layout: str) -> tuple[float, float]:
    """Return (width, height) for a swimLane node, with orientation defaults."""
    w_prop = lane_node.get("width")
    h_prop = lane_node.get("height")
    width = float(w_prop) if isinstance(w_prop, (int, float)) else None
    height = float(h_prop) if isinstance(h_prop, (int, float)) else None
    if width is None or height is None:
        style_w, style_h = _read_dims_from_style(lane_node.get("style"))
        if width is None:
            width = style_w
        if height is None:
            height = style_h
    orientation = (lane_node.get("data") or {}).get("orientation")
    if orientation not in ("horizontal", "vertical"):
        orientation = graph_layout
    if orientation == "vertical":
        default_w, default_h = _LANE_DEFAULT_VERTICAL
    else:
        default_w, default_h = _LANE_DEFAULT_HORIZONTAL
    return (
        width if width is not None else float(default_w),
        height if height is not None else float(default_h),
    )


def _layout_quality_issues(
    nodes: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[ValidationIssue]:
    """Surface bad-layout output from agent edits: a child whose lane-relative
    bbox would render outside its parent lane, an unparented step whose world
    bbox intersects a lane it should belong to, two siblings whose bboxes
    overlap, or siblings packed too tightly. These are warnings — they don't
    block usability, but the chat agent's `validate_protocol` should see them
    and re-place nodes neatly."""
    issues: list[ValidationIssue] = []
    graph_layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    unit_op_nodes = [n for n in nodes if n.get("type") == "unitOp"]
    lane_nodes = [n for n in nodes if n.get("type") == "swimLane"]

    # Rule 1: child_outside_lane — parented unit-op extends past lane bounds.
    for n in unit_op_nodes:
        parent_id = n.get("parentId")
        if not isinstance(parent_id, str) or not parent_id.startswith("lane-"):
            continue
        lane = nodes_by_id.get(parent_id)
        if lane is None or lane.get("type") != "swimLane":
            # `orphaned_parent_id` already covers this case.
            continue
        pos = n.get("position") or {}
        x = float(pos.get("x", 0))
        y = float(pos.get("y", 0))
        w, h = _node_dims(n)
        lane_w, lane_h = _lane_dims(lane, graph_layout)
        if x < 0 or y < 0 or x + w > lane_w or y + h > lane_h:
            label = (n.get("data") or {}).get("label") or "<unnamed>"
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="child_outside_lane",
                    node_id=n.get("id"),
                    message=(
                        f"Step '{label}' is positioned outside its swimlane — "
                        "the agent likely placed it on the edge instead of "
                        "inside. Re-place it using lane-relative coordinates "
                        "and grow the lane to fit."
                    ),
                )
            )

    # Rule 2: step_overlaps_lane — top-level unit-op (no parentId) whose
    # world bbox intersects a swimLane. The agent placed it on the lane edge
    # instead of parenting it; visually it appears half-inside, half-outside.
    # Children of a lane live in that lane's coordinate frame, so they can't
    # visually intersect a different lane — only top-level steps need checking.
    for n in unit_op_nodes:
        parent_id = n.get("parentId")
        if isinstance(parent_id, str) and parent_id.startswith("lane-"):
            continue
        pos = n.get("position") or {}
        nx = float(pos.get("x", 0))
        ny = float(pos.get("y", 0))
        nw, nh = _node_dims(n)
        for lane in lane_nodes:
            lane_pos = lane.get("position") or {}
            lx = float(lane_pos.get("x", 0))
            ly = float(lane_pos.get("y", 0))
            lw, lh = _lane_dims(lane, graph_layout)
            if nx < lx + lw and lx < nx + nw and ny < ly + lh and ly < ny + nh:
                label = (n.get("data") or {}).get("label") or "<unnamed>"
                lane_label = (lane.get("data") or {}).get("label") or "<lane>"
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="step_overlaps_lane",
                        node_id=n.get("id"),
                        message=(
                            f"Step '{label}' visually overlaps the '{lane_label}' "
                            "swimlane but is not a child of it. Set its parentId "
                            "to the lane and use lane-relative coordinates, or "
                            "move it clear of the lane bounds."
                        ),
                    )
                )
                break

    # Rule 3: overlapping_nodes — two unit-ops in the same parent frame whose
    # bboxes intersect. Children of different lanes are rendered in separate
    # coordinate frames and can't visually overlap, so group by parentId first.
    # Rule 4: insufficient_node_spacing — sibling unit-ops that don't overlap
    # but sit within _MIN_SIBLING_GAP of each other on both axes.
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for n in unit_op_nodes:
        parent_id = n.get("parentId") if isinstance(n.get("parentId"), str) else None
        by_parent.setdefault(parent_id, []).append(n)

    reported_overlap: set[frozenset[str]] = set()
    reported_spacing: set[frozenset[str]] = set()
    for siblings in by_parent.values():
        for i in range(len(siblings)):
            a = siblings[i]
            ax = float((a.get("position") or {}).get("x", 0))
            ay = float((a.get("position") or {}).get("y", 0))
            aw, ah = _node_dims(a)
            a_id = a.get("id")
            a_label = (a.get("data") or {}).get("label") or "<unnamed>"
            for j in range(i + 1, len(siblings)):
                b = siblings[j]
                bx = float((b.get("position") or {}).get("x", 0))
                by_ = float((b.get("position") or {}).get("y", 0))
                bw, bh = _node_dims(b)
                b_id = b.get("id")
                b_label = (b.get("data") or {}).get("label") or "<unnamed>"
                overlap = (
                    ax < bx + bw and bx < ax + aw and ay < by_ + bh and by_ < ay + ah
                )
                if overlap:
                    if a_id and b_id:
                        key = frozenset({a_id, b_id})
                        if key in reported_overlap:
                            continue
                        reported_overlap.add(key)
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="overlapping_nodes",
                            node_id=a_id,
                            message=(
                                f"Steps '{a_label}' and '{b_label}' overlap "
                                "visually. Space them out so a scientist can "
                                "read the protocol at a glance."
                            ),
                        )
                    )
                    continue
                # Non-overlapping: check separation. Gap on an axis is the
                # signed distance between the nearer edges; <= 0 means the
                # projections overlap on that axis. The pair is too tight
                # only if BOTH axis projections are within _MIN_SIBLING_GAP
                # (otherwise they're far apart on at least one axis).
                gap_x = max(bx - (ax + aw), ax - (bx + bw))
                gap_y = max(by_ - (ay + ah), ay - (by_ + bh))
                if gap_x < _MIN_SIBLING_GAP and gap_y < _MIN_SIBLING_GAP:
                    if a_id and b_id:
                        key = frozenset({a_id, b_id})
                        if key in reported_spacing:
                            continue
                        reported_spacing.add(key)
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="insufficient_node_spacing",
                            node_id=a_id,
                            message=(
                                f"Steps '{a_label}' and '{b_label}' are crowded "
                                f"— leave at least {int(_MIN_SIBLING_GAP)}px "
                                "between sibling unit ops so the protocol stays "
                                "readable."
                            ),
                        )
                    )

    issues.extend(_chain_layout_issues(nodes, graph))
    return issues


def _chain_layout_issues(
    nodes: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[ValidationIssue]:
    """Rules that look at chain *edges* rather than node bboxes alone:
    the chain advances along the layout axis, sibling chain steps share a
    row/column, and the chain doesn't visually thread through unrelated
    swimlanes. All warnings — they don't block usability but the chat
    agent should re-place nodes (typically via ``set_node_position``) to
    clear them."""
    issues: list[ValidationIssue] = []
    edges = list(graph.get("edges", []))
    graph_layout = "vertical" if graph.get("layout") == "vertical" else "horizontal"
    nodes_by_id = {n.get("id"): n for n in nodes if n.get("id")}
    unit_op_nodes = [n for n in nodes if n.get("type") == "unitOp"]
    unit_op_ids = {n.get("id") for n in unit_op_nodes if n.get("id")}
    lane_nodes = [n for n in nodes if n.get("type") == "swimLane"]

    def _frame_axis(node: dict[str, Any]) -> str:
        """Layout axis for a node's parent frame (lane orientation if parented)."""
        parent_id = node.get("parentId")
        if isinstance(parent_id, str) and parent_id.startswith("lane-"):
            lane = nodes_by_id.get(parent_id)
            if lane is not None:
                orientation = (lane.get("data") or {}).get("orientation")
                if orientation in ("horizontal", "vertical"):
                    return orientation
        return graph_layout

    def _label(n: dict[str, Any]) -> str:
        return (n.get("data") or {}).get("label") or "<unnamed>"

    reported_direction: set[tuple[str, str]] = set()
    reported_band: set[tuple[str, str]] = set()
    for e in edges:
        src_id = e.get("source")
        tgt_id = e.get("target")
        if src_id not in unit_op_ids or tgt_id not in unit_op_ids:
            continue
        src = nodes_by_id.get(src_id)
        tgt = nodes_by_id.get(tgt_id)
        if src is None or tgt is None:
            continue
        if src.get("parentId") != tgt.get("parentId"):
            # Cross-frame edges (e.g. a top-level step into a lane child)
            # don't share a coordinate space — comparing positions would be
            # noise.
            continue
        axis = _frame_axis(tgt)
        src_pos = src.get("position") or {}
        tgt_pos = tgt.get("position") or {}
        sx = float(src_pos.get("x", 0))
        sy = float(src_pos.get("y", 0))
        tx = float(tgt_pos.get("x", 0))
        ty = float(tgt_pos.get("y", 0))
        if axis == "vertical":
            forward = ty > sy
            cross_drift = abs(tx - sx)
        else:
            forward = tx > sx
            cross_drift = abs(ty - sy)
        pair_key = (str(src_id), str(tgt_id))
        if not forward and pair_key not in reported_direction:
            reported_direction.add(pair_key)
            arrow = "downwards" if axis == "vertical" else "rightwards"
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="chain_direction_violation",
                    node_id=str(tgt_id),
                    message=(
                        f"Step '{_label(tgt)}' sits before its predecessor "
                        f"'{_label(src)}' on the {axis} layout axis — the "
                        f"chain should read {arrow}. Move '{_label(tgt)}' "
                        "past its predecessor (use set_node_position)."
                    ),
                )
            )
        if cross_drift > _CHAIN_BAND_TOLERANCE and pair_key not in reported_band:
            reported_band.add(pair_key)
            cross_label = "x" if axis == "vertical" else "y"
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="step_outside_chain_band",
                    node_id=str(tgt_id),
                    message=(
                        f"Step '{_label(tgt)}' is offset {int(cross_drift)}px "
                        f"on the {cross_label}-axis from its chain predecessor "
                        f"'{_label(src)}'. Chain peers should sit in a single "
                        f"row/column (within {int(_CHAIN_BAND_TOLERANCE)}px) so "
                        "the protocol reads cleanly."
                    ),
                )
            )

    # lane_order_violation: a chain edge crossing from lane-A to lane-B
    # where lane-B is positioned BEFORE lane-A along the layout's
    # cross-axis (above for horizontal, left for vertical) — the chain
    # forces the reader to backtrack against natural reading order.
    cross_axis = "y" if graph_layout == "horizontal" else "x"
    reported_lane_order: set[tuple[str, str]] = set()
    for e in edges:
        src_id = e.get("source")
        tgt_id = e.get("target")
        if src_id not in unit_op_ids or tgt_id not in unit_op_ids:
            continue
        src = nodes_by_id.get(src_id)
        tgt = nodes_by_id.get(tgt_id)
        if src is None or tgt is None:
            continue
        src_parent = src.get("parentId")
        tgt_parent = tgt.get("parentId")
        if not (
            isinstance(src_parent, str)
            and src_parent.startswith("lane-")
            and isinstance(tgt_parent, str)
            and tgt_parent.startswith("lane-")
            and src_parent != tgt_parent
        ):
            continue
        src_lane = nodes_by_id.get(src_parent)
        tgt_lane = nodes_by_id.get(tgt_parent)
        if src_lane is None or tgt_lane is None:
            continue
        src_axis = float((src_lane.get("position") or {}).get(cross_axis, 0))
        tgt_axis = float((tgt_lane.get("position") or {}).get(cross_axis, 0))
        if tgt_axis >= src_axis:
            continue
        pair_key = (str(src_parent), str(tgt_parent))
        if pair_key in reported_lane_order:
            continue
        reported_lane_order.add(pair_key)
        src_label = (src_lane.get("data") or {}).get("label") or "<lane>"
        tgt_label = (tgt_lane.get("data") or {}).get("label") or "<lane>"
        direction = "above" if graph_layout == "horizontal" else "to the left of"
        reorder_hint = "below" if graph_layout == "horizontal" else "to the right of"
        issues.append(
            ValidationIssue(
                severity="warning",
                code="lane_order_violation",
                node_id=str(tgt_parent),
                message=(
                    f"Lane '{tgt_label}' sits {direction} '{src_label}' but "
                    f"the chain flows from '{src_label}' into '{tgt_label}' — "
                    "the reader has to backtrack. Move the downstream lane "
                    f"'{tgt_label}' {reorder_hint} the source lane "
                    f"'{src_label}' (use set_node_position on the lane node) "
                    "so lanes are ordered by chain flow."
                ),
            )
        )

    # chain_crosses_lane: top-level chain edges (both endpoints unparented)
    # whose midpoint lands inside an unrelated lane bbox. Visually the edge
    # threads through the lane — confusing. Children of any lane already
    # produce step_overlaps_lane / child_outside_lane signals if they stray.
    for e in edges:
        src_id = e.get("source")
        tgt_id = e.get("target")
        if src_id not in unit_op_ids or tgt_id not in unit_op_ids:
            continue
        src = nodes_by_id.get(src_id)
        tgt = nodes_by_id.get(tgt_id)
        if src is None or tgt is None:
            continue
        if src.get("parentId") or tgt.get("parentId"):
            continue
        sw, sh = _node_dims(src)
        tw, th = _node_dims(tgt)
        s_pos = src.get("position") or {}
        t_pos = tgt.get("position") or {}
        s_cx = float(s_pos.get("x", 0)) + sw / 2
        s_cy = float(s_pos.get("y", 0)) + sh / 2
        t_cx = float(t_pos.get("x", 0)) + tw / 2
        t_cy = float(t_pos.get("y", 0)) + th / 2
        mid_x = (s_cx + t_cx) / 2
        mid_y = (s_cy + t_cy) / 2
        for lane in lane_nodes:
            lane_pos = lane.get("position") or {}
            lx = float(lane_pos.get("x", 0))
            ly = float(lane_pos.get("y", 0))
            lw, lh = _lane_dims(lane, graph_layout)
            if lx <= mid_x <= lx + lw and ly <= mid_y <= ly + lh:
                lane_label = (lane.get("data") or {}).get("label") or "<lane>"
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="chain_crosses_lane",
                        node_id=str(tgt_id),
                        message=(
                            f"The edge from '{_label(src)}' to '{_label(tgt)}' "
                            f"passes through the '{lane_label}' swimlane but "
                            "neither step belongs to it. Either route the chain "
                            "around the lane (use set_node_position to nudge a "
                            "step) or assign one of the steps to that role so "
                            "the edge no longer crosses unrelated territory."
                        ),
                    )
                )
                break

    return issues


def _branch_role_issues(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[ValidationIssue]:
    """Fire branch_requires_distinct_roles when a unit op has 2+ outgoing
    branches sharing parentIds (or with null parentId), unless time mode is
    enabled and the immediate target intervals are pairwise disjoint."""
    issues: list[ValidationIssue] = []
    nodes_by_id = {n["id"]: n for n in nodes if "id" in n}
    outgoing: dict[str, list[str]] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s is None or t is None:
            continue
        outgoing.setdefault(s, []).append(t)

    time_enabled = bool(graph.get("timeEnabled"))
    pixels_per_hour = float(graph.get("pixelsPerHour") or 200)
    layout = graph.get("layout") or "horizontal"

    def interval_for(node: dict[str, Any]) -> tuple[float, float]:
        pos = node.get("position") or {}
        axis = (
            float(pos.get("x", 0)) if layout == "horizontal" else float(pos.get("y", 0))
        )
        start = axis / pixels_per_hour * 60.0
        duration = float((node.get("data") or {}).get("duration_min") or 30)
        return (start, start + duration)

    def intervals_pairwise_disjoint(targets: list[dict[str, Any]]) -> bool:
        intervals = [interval_for(t) for t in targets]
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if not (a[1] <= b[0] or b[1] <= a[0]):
                    return False
        return True

    for source_id, target_ids in outgoing.items():
        src = nodes_by_id.get(source_id)
        if not src or src.get("type") != "unitOp":
            continue
        targets = [
            nodes_by_id[tid]
            for tid in target_ids
            if tid in nodes_by_id and nodes_by_id[tid].get("type") == "unitOp"
        ]
        if len(targets) < 2:
            continue

        parent_ids = [t.get("parentId") for t in targets]
        has_duplicate = len(set(parent_ids)) != len(parent_ids)
        has_null = any(pid is None for pid in parent_ids)
        if not (has_duplicate or has_null):
            continue

        if time_enabled and intervals_pairwise_disjoint(targets):
            continue

        label = (src.get("data") or {}).get("label") or "<unnamed>"
        target_labels = [
            (t.get("data") or {}).get("label") or "<unnamed>" for t in targets
        ]
        issues.append(
            ValidationIssue(
                severity="error",
                code="branch_requires_distinct_roles",
                node_id=source_id,
                message=(
                    f"Step '{label}' branches to {', '.join(target_labels)} which "
                    "share or lack distinct role assignments. Assign each branch "
                    "target to a different role, or enable time mode and stagger "
                    "the branches at non-overlapping times."
                ),
            )
        )

    return issues


def assert_no_branch_errors(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
) -> None:
    """Raise HTTPException(400) if any branch_requires_distinct_roles issue fires.

    Other validation issues (warnings, missing process start, etc.) are not
    enforced here — callers handle them separately if needed.
    """
    from fastapi import HTTPException  # noqa: PLC0415 — keep validation.py import-light

    result = validate_protocol_graph(graph, unit_ops)
    blocking = [i for i in result.issues if i.code == "branch_requires_distinct_roles"]
    if blocking:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "branch_requires_distinct_roles",
                "issues": [i.model_dump() for i in blocking],
            },
        )


__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_protocol_graph",
    "assert_no_branch_errors",
]
