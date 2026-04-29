"""Unit tests for protocol_generator service.

Tests graph building, unit op matching, and param extraction
without any LLM calls.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.ai.workflows.protocol_generator import (GeneratedProtocol,
                                                          GeneratedStep,
                                                          build_graph,
                                                          extract_params,
                                                          match_unit_op)


def _make_unit_op(
    name: str, category: str = "General", param_schema: dict | None = None
):
    """Create a mock UnitOpDefinition."""
    op = MagicMock()
    op.id = uuid.uuid4()
    op.name = name
    op.category = category
    op.description = f"Description for {name}"
    op.param_schema = param_schema or {}
    return op


class TestBuildGraph:
    def test_single_step(self):
        step = GeneratedStep(
            name="Buffer Mix",
            unit_op_name="Buffer Mix",
            category="Media Prep",
            duration_min=30,
        )
        generated = GeneratedProtocol(
            name="Test Protocol",
            description="A test",
            steps=[step],
        )
        unit_ops = [_make_unit_op("Buffer Mix", "Media Prep")]
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()

        graph = build_graph(generated, unit_ops, session_id, user_id)

        assert len(graph["nodes"]) == 1
        assert len(graph["edges"]) == 0
        node = graph["nodes"][0]
        assert node["type"] == "unitOp"
        assert node["data"]["label"] == "Buffer Mix"
        assert node["data"]["category"] == "Media Prep"
        assert node["data"]["duration_min"] == 30

    def test_multiple_steps_create_sequential_edges(self):
        steps = [
            GeneratedStep(name="Step A", unit_op_name="Step A", duration_min=10),
            GeneratedStep(name="Step B", unit_op_name="Step B", duration_min=20),
            GeneratedStep(name="Step C", unit_op_name="Step C", duration_min=30),
        ]
        generated = GeneratedProtocol(
            name="Multi-Step",
            description="",
            steps=steps,
        )

        graph = build_graph(generated, [], uuid.uuid4(), uuid.uuid4())

        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2
        # Edge 0: A -> B
        assert graph["edges"][0]["source"] == graph["nodes"][0]["id"]
        assert graph["edges"][0]["target"] == graph["nodes"][1]["id"]
        # Edge 1: B -> C
        assert graph["edges"][1]["source"] == graph["nodes"][1]["id"]
        assert graph["edges"][1]["target"] == graph["nodes"][2]["id"]

    def test_horizontal_positions_increment(self):
        steps = [
            GeneratedStep(name="S1", unit_op_name="S1", duration_min=10),
            GeneratedStep(name="S2", unit_op_name="S2", duration_min=10),
        ]
        generated = GeneratedProtocol(name="P", description="", steps=steps)

        graph = build_graph(generated, [], uuid.uuid4(), uuid.uuid4())

        x0 = graph["nodes"][0]["position"]["x"]
        x1 = graph["nodes"][1]["position"]["x"]
        assert x1 > x0
        assert x1 - x0 == 300

    def test_metadata_present(self):
        steps = [GeneratedStep(name="S", unit_op_name="S", duration_min=10)]
        generated = GeneratedProtocol(name="P", description="", steps=steps)
        session_id = uuid.uuid4()
        user_id = uuid.uuid4()

        graph = build_graph(generated, [], session_id, user_id)

        meta = graph["_metadata"]
        assert meta["source"] == "ai_generated"
        assert meta["chat_session_id"] == str(session_id)
        assert meta["generated_by"] == str(user_id)
        assert "generated_at" in meta

    def test_standard_layout_fields(self):
        steps = [GeneratedStep(name="S", unit_op_name="S", duration_min=10)]
        generated = GeneratedProtocol(name="P", description="", steps=steps)

        graph = build_graph(generated, [], uuid.uuid4(), uuid.uuid4())

        assert graph["layout"] == "horizontal"
        assert graph["handleOrientation"] == "horizontal"
        assert graph["timeEnabled"] is False
        assert graph["startTime"] == "08:00"
        assert graph["pixelsPerHour"] == 150

    def test_matched_unit_op_uses_catalog_data(self):
        schema = {
            "properties": {
                "temperature": {"type": "number", "default": 37.0},
                "volume_ml": {"type": "number", "default": 100},
            }
        }
        op = _make_unit_op("Incubation", "Cell Culture", schema)

        step = GeneratedStep(
            name="Incubation",
            unit_op_name="Incubation",
            category="General",
            duration_min=60,
            params={"temperature": 42.0},
        )
        generated = GeneratedProtocol(name="P", description="", steps=[step])

        graph = build_graph(generated, [op], uuid.uuid4(), uuid.uuid4())

        node = graph["nodes"][0]
        assert node["data"]["category"] == "Cell Culture"
        assert node["data"]["unitOpId"] == str(op.id)
        assert node["data"]["paramSchema"] == schema
        # Merged params: override + default
        assert node["data"]["params"]["temperature"] == 42.0
        assert node["data"]["params"]["volume_ml"] == 100


class TestMatchUnitOp:
    def test_exact_match(self):
        ops = [_make_unit_op("Buffer Mix"), _make_unit_op("Seeding")]
        result = match_unit_op("Buffer Mix", ops)
        assert result is not None
        assert result.name == "Buffer Mix"

    def test_case_insensitive_match(self):
        ops = [_make_unit_op("Buffer Mix")]
        result = match_unit_op("buffer mix", ops)
        assert result is not None
        assert result.name == "Buffer Mix"

    def test_no_match_returns_none(self):
        ops = [_make_unit_op("Buffer Mix")]
        result = match_unit_op("Centrifugation", ops)
        assert result is None

    def test_empty_catalog(self):
        result = match_unit_op("Anything", [])
        assert result is None


class TestExtractParams:
    def test_merges_with_schema_defaults(self):
        schema = {
            "properties": {
                "temperature": {"type": "number", "default": 37.0},
                "ph": {"type": "number", "default": 7.4},
                "volume_ml": {"type": "number", "default": 100},
            }
        }
        step_params = {"temperature": 42.0}

        result = extract_params(step_params, schema)

        assert result["temperature"] == 42.0  # overridden
        assert result["ph"] == 7.4  # default
        assert result["volume_ml"] == 100  # default

    def test_handles_missing_params(self):
        schema = {
            "properties": {
                "name": {"type": "string"},  # no default
                "count": {"type": "integer", "default": 1},
            }
        }
        step_params = {}

        result = extract_params(step_params, schema)

        assert "name" not in result  # no default, no value
        assert result["count"] == 1

    def test_empty_schema(self):
        result = extract_params({"a": 1, "b": 2}, {})
        assert result == {"a": 1, "b": 2}

    def test_extra_params_preserved(self):
        schema = {
            "properties": {
                "x": {"type": "number", "default": 0},
            }
        }
        result = extract_params({"x": 5, "extra": "value"}, schema)
        assert result["x"] == 5
        assert result["extra"] == "value"
