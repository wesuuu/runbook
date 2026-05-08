"""Tests for services/protocols/lane_layout.py."""

from app.services.protocols.lane_layout import (
    LANE_DEFAULT_HORIZONTAL,
    grow_lane_to_fit,
    lane_relative_position,
)


def _lane(lane_id: str = "lane-1", orientation: str = "horizontal") -> dict:
    """Build a swimLane node carrying the legacy ``style`` string. Most
    existing protocols persist dimensions this way, so the helpers must
    keep working without numeric ``width`` / ``height`` props set."""
    width, height = (
        (220, 500) if orientation == "vertical" else LANE_DEFAULT_HORIZONTAL
    )
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
