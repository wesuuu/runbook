"""Tests for services/protocols/lane_layout.py."""

from app.services.protocols.lane_layout import (
    CHILD_X_STEP,
    CHILD_Y_STEP,
    LANE_DEFAULT_HORIZONTAL,
    grow_lane_to_fit,
    lane_relative_position,
    relayout_top_level_chain,
)


def _lane(lane_id: str = "lane-1", orientation: str = "horizontal") -> dict:
    """Build a swimLane node carrying the legacy ``style`` string. Most
    existing protocols persist dimensions this way, so the helpers must
    keep working without numeric ``width`` / ``height`` props set."""
    width, height = (220, 500) if orientation == "vertical" else LANE_DEFAULT_HORIZONTAL
    return {
        "id": lane_id,
        "type": "swimLane",
        "position": {"x": 0, "y": 0},
        "data": {"orientation": orientation, "label": "L"},
        "style": f"width: {width}px; height: {height}px;",
    }


def _child(node_id: str, parent_id: str) -> dict:
    return {
        "id": node_id,
        "type": "unitOp",
        "parentId": parent_id,
        "position": {"x": 0, "y": 0},
        "data": {},
    }


def test_lane_relative_position_first_child_horizontal():
    nodes = [_lane("lane-1")]
    pos = lane_relative_position(nodes, "lane-1", graph_layout="horizontal")
    assert pos == {"x": 20, "y": 60}


def test_lane_relative_position_stacks_horizontal_children():
    nodes = [_lane("lane-1"), _child("a", "lane-1"), _child("b", "lane-1")]
    pos = lane_relative_position(nodes, "lane-1", graph_layout="horizontal")
    assert pos == {"x": 20 + 2 * 240, "y": 60}


def test_lane_relative_position_stacks_vertical_children():
    nodes = [
        _lane("lane-v", "vertical"),
        _child("a", "lane-v"),
    ]
    pos = lane_relative_position(nodes, "lane-v", graph_layout="vertical")
    assert pos == {"x": 30, "y": 60 + 1 * 120}


def test_lane_relative_position_excludes_named_node():
    nodes = [_lane("lane-1"), _child("a", "lane-1"), _child("b", "lane-1")]
    pos = lane_relative_position(
        nodes, "lane-1", graph_layout="horizontal", exclude_node_id="b"
    )
    assert pos == {"x": 20 + 1 * 240, "y": 60}


def test_lane_orientation_overrides_graph_layout():
    nodes = [_lane("lane-v", "vertical")]
    pos = lane_relative_position(nodes, "lane-v", graph_layout="horizontal")
    assert pos == {"x": 30, "y": 60}


def test_grow_lane_to_fit_keeps_default_for_few_children():
    nodes = [_lane("lane-1"), _child("a", "lane-1")]
    out = grow_lane_to_fit(nodes, "lane-1", graph_layout="horizontal")
    lane = next(n for n in out if n["id"] == "lane-1")
    assert lane["width"] == 800
    assert lane["height"] == 200


def test_grow_lane_to_fit_widens_horizontal_when_needed():
    children = [_child(f"c{i}", "lane-1") for i in range(5)]
    nodes = [_lane("lane-1"), *children]
    out = grow_lane_to_fit(nodes, "lane-1", graph_layout="horizontal")
    lane = next(n for n in out if n["id"] == "lane-1")
    # 20 (inset) + 5 * 240 + 40 = 1260
    assert lane["width"] == 1260
    assert lane["height"] == 200


def test_grow_lane_to_fit_grows_vertical_when_needed():
    children = [_child(f"c{i}", "lane-v") for i in range(5)]
    nodes = [_lane("lane-v", "vertical"), *children]
    out = grow_lane_to_fit(nodes, "lane-v", graph_layout="vertical")
    lane = next(n for n in out if n["id"] == "lane-v")
    # 60 (inset) + 5 * 120 + 40 = 700
    assert lane["width"] == 220
    assert lane["height"] == 700


def test_grow_lane_to_fit_preserves_user_resized_height_horizontal():
    """User dragged the bottom handle from 200 → 400; growing the lane
    must not snap that height back to the default."""
    lane = _lane("lane-1")
    lane["height"] = 400
    nodes = [lane, _child("a", "lane-1")]
    out = grow_lane_to_fit(nodes, "lane-1", graph_layout="horizontal")
    grown = next(n for n in out if n["id"] == "lane-1")
    assert grown["height"] == 400


def test_grow_lane_to_fit_preserves_user_resized_width_vertical():
    """Cross-axis resize on a vertical lane must survive a grow pass."""
    lane = _lane("lane-v", "vertical")
    lane["width"] = 380
    nodes = [lane, _child("a", "lane-v")]
    out = grow_lane_to_fit(nodes, "lane-v", graph_layout="vertical")
    grown = next(n for n in out if n["id"] == "lane-v")
    assert grown["width"] == 380


def test_grow_lane_to_fit_keeps_existing_style_string_intact():
    """The frontend still ships ``style: "width: …; height: …;"`` strings
    from `createSwimLaneNode`. xyflow appends numeric width/height after
    the style string, so the numeric values win at render time — but we
    must not touch the original string (frontend treats absence as a
    different shape and would lose it on next save)."""
    lane = _lane("lane-1")
    original_style = lane["style"]
    nodes = [lane, _child("a", "lane-1")]
    out = grow_lane_to_fit(nodes, "lane-1", graph_layout="horizontal")
    grown = next(n for n in out if n["id"] == "lane-1")
    assert grown["style"] == original_style


def test_grow_lane_to_fit_reads_dimensions_from_legacy_style_only():
    """When a lane carries only a ``style`` string (no numeric props),
    the helper must still read the user's dimensions from it so a grow
    pass doesn't shrink the lane below what the user already set."""
    lane = {
        "id": "lane-1",
        "type": "swimLane",
        "position": {"x": 0, "y": 0},
        "data": {"orientation": "horizontal", "label": "L"},
        "style": "width: 950px; height: 320px;",
    }
    nodes = [lane, _child("a", "lane-1")]
    out = grow_lane_to_fit(nodes, "lane-1", graph_layout="horizontal")
    grown = next(n for n in out if n["id"] == "lane-1")
    # Few children → no growth needed, but user's wider style should be
    # promoted to numeric props.
    assert grown["width"] == 950
    assert grown["height"] == 320


def _top_level_uo(node_id: str, x: float, y: float) -> dict:
    return {
        "id": node_id,
        "type": "unitOp",
        "position": {"x": x, "y": y},
        "data": {},
    }


def test_relayout_top_level_chain_spaces_horizontal():
    """Two top-level steps stacked at the same coords get re-flowed at
    CHILD_X_STEP intervals along x, anchored on the first node's position."""
    nodes = [
        _top_level_uo("a", 100, 200),
        _top_level_uo("b", 100, 200),
        _top_level_uo("c", 100, 200),
    ]
    out = relayout_top_level_chain(nodes, graph_layout="horizontal")
    xs = [n["position"]["x"] for n in out]
    ys = [n["position"]["y"] for n in out]
    assert xs == [100, 100 + CHILD_X_STEP, 100 + 2 * CHILD_X_STEP]
    assert ys == [200, 200, 200]


def test_relayout_top_level_chain_spaces_vertical():
    nodes = [
        _top_level_uo("a", 50, 80),
        _top_level_uo("b", 999, 999),  # the anchor wins; this node moves
    ]
    out = relayout_top_level_chain(nodes, graph_layout="vertical")
    xs = [n["position"]["x"] for n in out]
    ys = [n["position"]["y"] for n in out]
    assert xs == [50, 50]
    assert ys == [80, 80 + CHILD_Y_STEP]


def test_relayout_top_level_chain_ignores_lane_children():
    """Nodes parented to a swimlane are owned by lane layout — leave them."""
    nodes = [
        _lane("lane-1"),
        _child("child-a", "lane-1"),
        _top_level_uo("t1", 100, 200),
        _top_level_uo("t2", 100, 200),
    ]
    # Mutate the lane child to a non-default position so we can detect if
    # relayout wrongly touched it.
    nodes[1]["position"] = {"x": 7, "y": 11}
    out = relayout_top_level_chain(nodes, graph_layout="horizontal")
    child_pos = next(n for n in out if n["id"] == "child-a")["position"]
    assert child_pos == {"x": 7, "y": 11}
    t2_pos = next(n for n in out if n["id"] == "t2")["position"]
    assert t2_pos == {"x": 100 + CHILD_X_STEP, "y": 200}


def test_relayout_top_level_chain_preserves_anchor_when_no_top_level():
    """A graph with only lane children is a no-op."""
    nodes = [_lane("lane-1"), _child("child-a", "lane-1")]
    out = relayout_top_level_chain(nodes, graph_layout="horizontal")
    assert out == nodes


def test_relayout_top_level_chain_does_not_mutate_input():
    nodes = [_top_level_uo("a", 100, 200), _top_level_uo("b", 100, 200)]
    out = relayout_top_level_chain(nodes, graph_layout="horizontal")
    # New list, new node dicts — input untouched.
    assert nodes[1]["position"] == {"x": 100, "y": 200}
    assert out[1]["position"] == {"x": 100 + CHILD_X_STEP, "y": 200}
