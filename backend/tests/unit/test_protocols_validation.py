"""Tests for services/protocols/validation.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.services.protocols.validation import validate_protocol_graph


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
