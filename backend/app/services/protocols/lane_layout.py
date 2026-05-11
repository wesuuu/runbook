"""Shared lane-layout helpers for graph mutations.

Children of a swimLane node use coordinates RELATIVE to the lane (this is
how @xyflow renders nested nodes). When a tool moves a step into a lane —
either by creating it with `parentId` set or by patching `parentId` later
— it must place the node inside the lane's visible area, otherwise it
ends up overlapping a sibling or outside the dashed border.

The functions here mirror the visual conventions used by the frontend
editor (see `frontend/src/lib/components/protocol/protocolNodes.ts` and
`SwimLaneNode.svelte`):

  * Horizontal lane: 800x200. Children flow left-to-right at y≈60, every
    240px on x.
  * Vertical lane: 220x500. Children flow top-to-bottom at x≈30, every
    120px on y.

Lane dimensions live on the node as numeric `width` / `height` props so
that `<NodeResizer>` updates flow back without a string-vs-numeric race.
Legacy graphs may still carry `style: "width: …; height: …;"`; we parse
those values once and strip them.
"""

import re
from typing import Any

CHILD_X_STEP = 240
CHILD_Y_STEP = 120
CHILD_INSET_X = 20
CHILD_INSET_Y = 60

LANE_DEFAULT_HORIZONTAL = (800, 200)
LANE_DEFAULT_VERTICAL = (220, 500)


def _graph_layout(graph: dict[str, Any]) -> str:
    return "vertical" if graph.get("layout") == "vertical" else "horizontal"


def _lane_orientation(lane_node: dict[str, Any], graph_layout: str) -> str:
    """Lane's own orientation overrides graph layout if set."""
    orientation = (lane_node.get("data") or {}).get("orientation")
    if orientation in ("horizontal", "vertical"):
        return orientation
    return graph_layout


def lane_relative_position(
    nodes: list[dict[str, Any]],
    lane_id: str,
    *,
    graph_layout: str,
    exclude_node_id: str | None = None,
) -> dict[str, int]:
    """Compute lane-relative position for the next child of ``lane_id``.

    Counts existing children with ``parentId == lane_id`` (excluding the
    optional ``exclude_node_id`` — useful when relocating an existing node
    from another lane). Returns ``{"x": ..., "y": ...}``.
    """
    lane = next((n for n in nodes if n.get("id") == lane_id), None)
    orientation = (
        _lane_orientation(lane, graph_layout) if lane is not None else graph_layout
    )
    siblings = [
        n
        for n in nodes
        if n.get("parentId") == lane_id and n.get("id") != exclude_node_id
    ]
    index = len(siblings)
    if orientation == "vertical":
        return {"x": 30, "y": CHILD_INSET_Y + index * CHILD_Y_STEP}
    return {"x": CHILD_INSET_X + index * CHILD_X_STEP, "y": CHILD_INSET_Y}


_STYLE_DIMENSION_RE = re.compile(
    r"\s*(width|height)\s*:\s*([0-9]+)\s*px\s*;?", re.IGNORECASE
)


def _current_dimensions(node: dict[str, Any]) -> tuple[int | None, int | None]:
    """Read width/height from numeric props, falling back to legacy style.

    Returns ``(width, height)`` where each value is ``None`` if missing.
    """
    w = node.get("width")
    h = node.get("height")
    width: int | None = int(w) if isinstance(w, (int, float)) else None
    height: int | None = int(h) if isinstance(h, (int, float)) else None
    if width is None or height is None:
        style = node.get("style")
        if isinstance(style, str):
            for key, val in _STYLE_DIMENSION_RE.findall(style):
                if key.lower() == "width" and width is None:
                    width = int(val)
                elif key.lower() == "height" and height is None:
                    height = int(val)
    return width, height


def grow_lane_to_fit(
    nodes: list[dict[str, Any]],
    lane_id: str,
    *,
    graph_layout: str,
) -> list[dict[str, Any]]:
    """Return ``nodes`` with the lane sized to fit its children.

    Writes lane dimensions to the node's numeric ``width`` / ``height``
    props. xyflow renders these *after* the ``style`` string, so the
    numeric values override any stale ``"width: …; height: …;"`` left
    over from earlier writes — and `<NodeResizer>` updates the same
    numeric props, so user resizes flow back here as the new baseline.

    Only grows along the layout axis (children don't overflow); the
    cross-axis is preserved if the user previously resized the lane.
    Idempotent — never shrinks below the user's manual size. Does not
    touch the ``style`` string.
    """
    out = list(nodes)
    for i, n in enumerate(out):
        if n.get("id") != lane_id or n.get("type") != "swimLane":
            continue
        orientation = _lane_orientation(n, graph_layout)
        children = [c for c in out if c.get("parentId") == lane_id]
        count = len(children)
        current_w, current_h = _current_dimensions(n)
        if orientation == "vertical":
            default_w, default_h = LANE_DEFAULT_VERTICAL
            needed_h = CHILD_INSET_Y + count * CHILD_Y_STEP + 40
            new_w = current_w if current_w is not None else default_w
            new_h = max(current_h or default_h, needed_h)
        else:
            default_w, default_h = LANE_DEFAULT_HORIZONTAL
            needed_w = CHILD_INSET_X + count * CHILD_X_STEP + 40
            new_w = max(current_w or default_w, needed_w)
            new_h = current_h if current_h is not None else default_h
        updated = dict(n)
        updated["width"] = new_w
        updated["height"] = new_h
        out[i] = updated
        break
    return out


TOP_LEVEL_DEFAULT_X = 100
TOP_LEVEL_DEFAULT_Y = 200


def relayout_top_level_chain(
    nodes: list[dict[str, Any]],
    *,
    graph_layout: str,
) -> list[dict[str, Any]]:
    """Re-flow top-level unit-op nodes along the chain axis with uniform spacing.

    Top-level here means ``type == "unitOp"`` with no ``parentId``. Children
    of swimlanes live in lane-relative coordinates and are owned by
    ``lane_relative_position``/``grow_lane_to_fit``; this helper leaves them
    alone.

    Order follows the node list (the chain edges are rebuilt in list order,
    so list order == visual chain order). Spacing is ``CHILD_X_STEP`` on x
    for horizontal layout, ``CHILD_Y_STEP`` on y for vertical. The anchor is
    the existing position of the first top-level unit-op so the row stays
    where the user last saw it; subsequent nodes are placed at uniform
    offsets from that anchor along the layout axis (cross-axis stays equal
    to the anchor's value).
    """
    top_level_indices = [
        i
        for i, n in enumerate(nodes)
        if n.get("type") == "unitOp" and not n.get("parentId")
    ]
    if not top_level_indices:
        return nodes
    first = nodes[top_level_indices[0]]
    first_pos = first.get("position") or {}
    anchor_x = float(first_pos.get("x", TOP_LEVEL_DEFAULT_X))
    anchor_y = float(first_pos.get("y", TOP_LEVEL_DEFAULT_Y))
    out = list(nodes)
    for k, i in enumerate(top_level_indices):
        if graph_layout == "vertical":
            new_pos = {"x": anchor_x, "y": anchor_y + k * CHILD_Y_STEP}
        else:
            new_pos = {"x": anchor_x + k * CHILD_X_STEP, "y": anchor_y}
        out[i] = {**out[i], "position": new_pos}
    return out


__all__ = [
    "CHILD_INSET_X",
    "CHILD_INSET_Y",
    "CHILD_X_STEP",
    "CHILD_Y_STEP",
    "LANE_DEFAULT_HORIZONTAL",
    "LANE_DEFAULT_VERTICAL",
    "TOP_LEVEL_DEFAULT_X",
    "TOP_LEVEL_DEFAULT_Y",
    "grow_lane_to_fit",
    "lane_relative_position",
    "relayout_top_level_chain",
]
