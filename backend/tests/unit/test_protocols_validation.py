"""Tests for services/protocols/validation.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.services.protocols.validation import (assert_no_branch_errors,
                                               validate_protocol_graph)


def _unit_op(name: str = "Buffer Mix") -> object:
    op = MagicMock()
    op.id = uuid.uuid4()
    op.name = name
    return op


def _ps(node_id: str = "ps-1") -> dict:
    return {
        "id": node_id,
        "type": "processStart",
        "data": {"label": "Start"},
    }


def _step(
    node_id: str,
    *,
    unit_op_id=None,
    schema=None,
    description="Mix it",
    category="Media Prep",
    label="Step",
) -> dict:
    return {
        "id": node_id,
        "type": "unitOp",
        "data": {
            "label": label,
            "unitOpId": str(unit_op_id) if unit_op_id else None,
            "category": category,
            "description": description,
            "paramSchema": schema
            or {"type": "object", "properties": {"x": {"type": "number"}}},
        },
    }


def test_valid_graph_has_no_issues():
    op = _unit_op()
    graph = {
        "nodes": [
            _ps("ps"),
            _step("s1", unit_op_id=op.id),
        ],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op])
    assert result.ok is True
    assert result.issues == []


def test_missing_process_start_is_error():
    graph = {
        "nodes": [_step("s1", unit_op_id=uuid.uuid4())],
        "edges": [],
    }
    result = validate_protocol_graph(graph, [])
    codes = [i.code for i in result.issues]
    assert "missing_process_start" in codes
    assert result.ok is False


def test_multiple_process_starts_in_one_component_is_error():
    graph = {
        "nodes": [_ps("ps1"), _ps("ps2"), _step("s1")],
        "edges": [
            {"id": "e1", "source": "ps1", "target": "s1"},
            {"id": "e2", "source": "ps2", "target": "s1"},
        ],
    }
    result = validate_protocol_graph(graph, [])
    codes = [i.code for i in result.issues]
    assert "multiple_process_starts" in codes
    assert result.ok is False


def test_empty_param_schema_is_warning():
    graph = {
        "nodes": [
            _ps(),
            _step("s1", schema={"type": "object", "properties": {}}),
        ],
        "edges": [{"id": "e1", "source": "ps-1", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [])
    codes = {i.code for i in result.issues}
    assert "empty_param_schema" in codes
    # Warning-only — graph still ok
    assert result.ok is True


def test_missing_description_is_warning():
    graph = {
        "nodes": [
            _ps(),
            _step("s1", description=""),
        ],
        "edges": [{"id": "e1", "source": "ps-1", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [])
    codes = {i.code for i in result.issues}
    assert "missing_description" in codes


def test_general_category_with_no_unit_op_id_is_warning():
    graph = {
        "nodes": [
            _ps(),
            _step("s1", category="General"),
        ],
        "edges": [{"id": "e1", "source": "ps-1", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [])
    codes = {i.code for i in result.issues}
    assert "placeholder_category" in codes


def test_unknown_unit_op_id_is_error():
    bogus_id = uuid.uuid4()
    graph = {
        "nodes": [
            _ps(),
            _step("s1", unit_op_id=bogus_id),
        ],
        "edges": [{"id": "e1", "source": "ps-1", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [])
    codes = [i.code for i in result.issues]
    assert "unknown_unit_op_id" in codes
    assert result.ok is False


def test_disconnected_step_is_warning():
    op = _unit_op()
    graph = {
        "nodes": [_ps(), _step("s1", unit_op_id=op.id)],
        "edges": [],  # no edge from ps to s1
    }
    result = validate_protocol_graph(graph, [op])
    codes = [i.code for i in result.issues]
    assert "disconnected_step" in codes


# ---------------------------------------------------------------------------
# Branch role validation — shared fixture contract (QA-0006)
# ---------------------------------------------------------------------------

import json
from pathlib import Path

import pytest

# Repo root: backend/tests/unit/test_protocols_validation.py → parents[3] = repo root
_FIXTURE_PATH = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "branch_role_validation.json"
)
_FIXTURE_CASES = json.loads(_FIXTURE_PATH.read_text())["cases"]


@pytest.mark.parametrize(
    "case",
    _FIXTURE_CASES,
    ids=[c["name"] for c in _FIXTURE_CASES],
)
def test_branch_role_fixture(case):
    """Shared behavior contract for branch_requires_distinct_roles.

    Cases live in tests/fixtures/branch_role_validation.json — the single
    source of truth shared with the frontend test suite. Adding/changing
    a case forces both implementations to update together.
    """
    result = validate_protocol_graph(case["graph"], [])
    actual_sources = sorted(
        i.node_id for i in result.issues if i.code == "branch_requires_distinct_roles"
    )
    expected = sorted(case["expected"]["fires_on"])
    assert (
        actual_sources == expected
    ), f"case '{case['name']}': expected fires_on={expected}, got {actual_sources}"


def test_branch_role_issue_python_shape():
    """Backend-specific assertions on ValidationIssue (severity, message)."""
    case = next(
        c
        for c in _FIXTURE_CASES
        if c["name"] == "branching with two targets in same parentId fires"
    )
    result = validate_protocol_graph(case["graph"], [])
    issue = next(i for i in result.issues if i.code == "branch_requires_distinct_roles")
    assert issue.severity == "error"
    assert issue.node_id == "b"
    assert "branches to" in issue.message
    assert result.ok is False


def test_assert_no_branch_errors_raises_400_on_violation():
    case = next(c for c in _FIXTURE_CASES if c["expected"]["fires_on"])
    with pytest.raises(HTTPException) as exc_info:
        assert_no_branch_errors(case["graph"], [])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "branch_requires_distinct_roles"
    assert len(exc_info.value.detail["issues"]) >= 1


def test_assert_no_branch_errors_passes_on_valid_graph():
    case = next(c for c in _FIXTURE_CASES if not c["expected"]["fires_on"])
    # Should not raise.
    assert_no_branch_errors(case["graph"], [])


def _role(name: str = "Operator") -> object:
    r = MagicMock()
    r.id = uuid.uuid4()
    r.name = name
    return r


def _lane(role) -> dict:
    return {
        "id": f"lane-{role.id}",
        "type": "swimLane",
        "data": {"label": role.name, "roleId": str(role.id)},
    }


def test_role_with_lane_passes():
    op = _unit_op()
    role = _role()
    step = _step("s1", unit_op_id=op.id)
    step["parentId"] = f"lane-{role.id}"
    graph = {
        "nodes": [_ps("ps"), _lane(role), step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    assert result.ok is True
    assert [i.code for i in result.issues] == []


def test_role_with_lane_but_no_steps_flags_empty_lane():
    op = _unit_op()
    role = _role("Reviewer")
    graph = {
        "nodes": [_ps("ps"), _lane(role), _step("s1", unit_op_id=op.id)],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "empty_lane" in codes
    empty = next(i for i in result.issues if i.code == "empty_lane")
    assert empty.severity == "warning"
    assert empty.node_id == f"lane-{role.id}"


def test_empty_lane_not_flagged_when_role_missing_lane_node():
    op = _unit_op()
    role = _role("Reviewer")
    graph = {
        "nodes": [_ps("ps"), _step("s1", unit_op_id=op.id)],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "missing_lane_node" in codes
    assert "empty_lane" not in codes


def test_role_without_lane_flags_missing_lane_node():
    op = _unit_op()
    role = _role("Operator")
    graph = {
        "nodes": [_ps("ps"), _step("s1", unit_op_id=op.id)],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "missing_lane_node" in codes


def test_lane_without_role_flags_orphaned_lane_node():
    op = _unit_op()
    fake_role = _role()  # not in roles list
    graph = {
        "nodes": [_ps("ps"), _lane(fake_role), _step("s1", unit_op_id=op.id)],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[])
    codes = [i.code for i in result.issues]
    assert "orphaned_lane_node" in codes


def test_step_with_dangling_parent_id_flags_orphaned_parent_id():
    op = _unit_op()
    role = _role()
    step = _step("s1", unit_op_id=op.id)
    step["parentId"] = f"lane-{role.id}"  # but no lane node in graph
    graph = {
        "nodes": [_ps("ps"), step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "orphaned_parent_id" in codes
    assert "missing_lane_node" in codes


def _horizontal_lane(role, *, width: int = 800, height: int = 200) -> dict:
    return {
        "id": f"lane-{role.id}",
        "type": "swimLane",
        "position": {"x": 0, "y": 400},
        "width": width,
        "height": height,
        "data": {
            "label": role.name,
            "roleId": str(role.id),
            "orientation": "horizontal",
        },
    }


def _child_step(node_id: str, parent_id: str, x: int, y: int) -> dict:
    op = _unit_op()
    step = _step(node_id, unit_op_id=op.id, label=node_id)
    step["parentId"] = parent_id
    step["position"] = {"x": x, "y": y}
    return step


def test_child_inside_lane_passes():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    step = _child_step("s1", lane["id"], x=20, y=60)
    step["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "child_outside_lane" not in codes


def test_child_overflowing_lane_horizontally_is_warning():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role, width=400, height=200)
    # Child at x=300 with default width 220 overruns lane width 400.
    step = _child_step("s1", lane["id"], x=300, y=60)
    step["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    issue = next((i for i in result.issues if i.code == "child_outside_lane"), None)
    assert issue is not None
    assert issue.severity == "warning"
    assert issue.node_id == "s1"
    # Layout-quality rules are warnings only — graph remains valid.
    assert result.ok is True


def test_child_with_negative_position_is_warning():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    step = _child_step("s1", lane["id"], x=-50, y=60)
    step["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "child_outside_lane" in codes


def test_dangling_parent_id_does_not_double_flag_layout():
    """If the lane node is missing entirely, orphaned_parent_id already fires —
    we shouldn't also surface child_outside_lane against the same step."""
    op = _unit_op()
    role = _role()
    step = _child_step("s1", f"lane-{role.id}", x=20, y=60)
    step["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "orphaned_parent_id" in codes
    assert "child_outside_lane" not in codes


def test_overlapping_siblings_in_same_lane_is_warning():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    a = _child_step("a", lane["id"], x=20, y=60)
    b = _child_step("b", lane["id"], x=100, y=60)  # 220-wide → overlaps a
    a["data"]["unitOpId"] = str(op.id)
    b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    overlaps = [i for i in result.issues if i.code == "overlapping_nodes"]
    assert len(overlaps) == 1
    assert overlaps[0].severity == "warning"


def test_neatly_spaced_siblings_in_same_lane_pass():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role, width=2000)
    a = _child_step("a", lane["id"], x=20, y=60)
    b = _child_step("b", lane["id"], x=260, y=60)  # exactly one CHILD_X_STEP over
    a["data"]["unitOpId"] = str(op.id)
    b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "overlapping_nodes" not in codes


def test_overlapping_top_level_nodes_is_warning():
    op = _unit_op()
    a = _step("a", unit_op_id=op.id, label="a")
    a["position"] = {"x": 100, "y": 200}
    b = _step("b", unit_op_id=op.id, label="b")
    b["position"] = {"x": 150, "y": 220}
    graph = {
        "nodes": [_ps("ps"), a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op])
    codes = [i.code for i in result.issues]
    assert "overlapping_nodes" in codes


def test_overlap_across_different_lanes_is_not_flagged():
    """Children of different lanes are rendered in separate coordinate frames
    — they can't visually overlap, even at identical lane-relative coords."""
    op = _unit_op()
    role_a = _role("A")
    role_b = _role("B")
    lane_a = _horizontal_lane(role_a)
    lane_b = _horizontal_lane(role_b)
    step_a = _child_step("a", lane_a["id"], x=20, y=60)
    step_b = _child_step("b", lane_b["id"], x=20, y=60)
    step_a["data"]["unitOpId"] = str(op.id)
    step_b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane_a, lane_b, step_a, step_b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role_a, role_b])
    codes = [i.code for i in result.issues]
    assert "overlapping_nodes" not in codes


def test_roles_arg_omitted_skips_role_lane_checks():
    op = _unit_op()
    fake_role = _role()
    graph = {
        "nodes": [_ps("ps"), _lane(fake_role), _step("s1", unit_op_id=op.id)],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op])
    codes = [i.code for i in result.issues]
    assert "orphaned_lane_node" not in codes
    assert "missing_lane_node" not in codes


def test_top_level_step_intersecting_lane_flags_step_overlaps_lane():
    """A top-level unit op (no parentId) whose world bbox intersects a
    swimlane should fire step_overlaps_lane — the agent placed it on the
    lane boundary instead of parenting it (see Storage and Labeling case)."""
    op = _unit_op()
    role = _role("QA Analyst")
    lane = _horizontal_lane(role)
    # Lane at world (0, 400), size 800x200 → bbox (0-800, 400-600).
    # Place a top-level step at (60, 550) — bbox (60-280, 550-650) — its
    # bottom half hangs below the lane, top half overlaps the lane.
    step = _step("s1", unit_op_id=op.id, label="Storage and Labeling")
    step["position"] = {"x": 60, "y": 550}
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    issue = next((i for i in result.issues if i.code == "step_overlaps_lane"), None)
    assert issue is not None
    assert issue.severity == "warning"
    assert issue.node_id == "s1"
    assert "QA Analyst" in issue.message
    # Warning-only — graph remains valid.
    assert result.ok is True


def test_top_level_step_clear_of_lane_does_not_fire_step_overlaps_lane():
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    step = _step("s1", unit_op_id=op.id)
    step["position"] = {"x": 60, "y": 100}  # well above lane at y=400
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "step_overlaps_lane" not in codes


def test_parented_child_does_not_fire_step_overlaps_lane():
    """Parented steps live in the lane's coordinate frame; child_outside_lane
    handles their overflow. step_overlaps_lane is only for top-level steps."""
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    step = _child_step("s1", lane["id"], x=20, y=60)
    step["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, step],
        "edges": [{"id": "e1", "source": "ps", "target": "s1"}],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "step_overlaps_lane" not in codes


def test_crowded_siblings_flag_insufficient_node_spacing():
    """Two siblings that don't overlap but sit within 10px of each other
    should be flagged as crowded."""
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role, width=2000)
    a = _child_step("a", lane["id"], x=20, y=60)
    # b sits 5px to the right of a (gap_x = 5 < 10). Same y → gap_y = -100.
    b = _child_step("b", lane["id"], x=245, y=60)
    a["data"]["unitOpId"] = str(op.id)
    b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    tight = [i for i in result.issues if i.code == "insufficient_node_spacing"]
    assert len(tight) == 1
    assert tight[0].severity == "warning"


def test_canonical_spacing_does_not_fire_insufficient_node_spacing():
    """The canonical CHILD_X_STEP (240) leaves a 20px gap — well above
    the 10px threshold."""
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role, width=2000)
    a = _child_step("a", lane["id"], x=20, y=60)
    b = _child_step("b", lane["id"], x=260, y=60)
    a["data"]["unitOpId"] = str(op.id)
    b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "insufficient_node_spacing" not in codes


def test_overlap_takes_precedence_over_spacing():
    """A pair that overlaps should fire overlapping_nodes but NOT also
    insufficient_node_spacing."""
    op = _unit_op()
    role = _role()
    lane = _horizontal_lane(role)
    a = _child_step("a", lane["id"], x=20, y=60)
    b = _child_step("b", lane["id"], x=100, y=60)  # overlaps a
    a["data"]["unitOpId"] = str(op.id)
    b["data"]["unitOpId"] = str(op.id)
    graph = {
        "nodes": [_ps("ps"), lane, a, b],
        "edges": [
            {"id": "e1", "source": "ps", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
        ],
    }
    result = validate_protocol_graph(graph, [op], roles=[role])
    codes = [i.code for i in result.issues]
    assert "overlapping_nodes" in codes
    assert "insufficient_node_spacing" not in codes
