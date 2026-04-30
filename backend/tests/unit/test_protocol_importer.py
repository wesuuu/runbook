"""Unit tests for protocol_importer service.

Tests proposal building, param_schema generation, swim lane creation,
and graph metadata — without any LLM calls.
"""

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.protocols.protocol_importer import (
    ImportedParam, ImportedStep, ParsedProtocol, ProtocolImportProposal,
    StepProposal, build_import_graph, build_param_schema_from_params,
    build_proposal)


def _make_unit_op(
    name: str,
    category: str = "General",
    param_schema: dict | None = None,
) -> MagicMock:
    """Create a mock UnitOpDefinition."""
    op = MagicMock()
    op.id = uuid.uuid4()
    op.name = name
    op.category = category
    op.description = f"Description for {name}"
    op.param_schema = param_schema or {}
    return op


# ── build_param_schema_from_params ──────────────────────────────────


class TestBuildParamSchema:
    def test_empty_params(self):
        schema = build_param_schema_from_params([])
        assert schema == {"type": "object", "properties": {}}

    def test_single_number_param(self):
        params = [
            ImportedParam(name="temperature", type="number", unit="C", default=37.0)
        ]
        schema = build_param_schema_from_params(params)
        assert "temperature" in schema["properties"]
        prop = schema["properties"]["temperature"]
        assert prop["type"] == "number"
        assert prop["unit"] == "C"
        assert prop["default"] == 37.0

    def test_multiple_params(self):
        params = [
            ImportedParam(name="volume", type="number", unit="mL"),
            ImportedParam(name="buffer_name", type="string"),
            ImportedParam(name="sterile", type="boolean", default=True),
        ]
        schema = build_param_schema_from_params(params)
        assert len(schema["properties"]) == 3
        assert schema["properties"]["volume"]["type"] == "number"
        assert schema["properties"]["buffer_name"]["type"] == "string"
        assert schema["properties"]["sterile"]["default"] is True

    def test_param_without_unit(self):
        params = [ImportedParam(name="count", type="number")]
        schema = build_param_schema_from_params(params)
        assert "unit" not in schema["properties"]["count"]


# ── build_proposal ──────────────────────────────────────────────────


class TestBuildProposal:
    def test_matched_step(self):
        ops = [
            _make_unit_op(
                "Buffer Mix",
                "Media Prep",
                {"properties": {"volume_ml": {"type": "number", "default": 100}}},
            )
        ]
        parsed = ParsedProtocol(
            protocol_name="Test",
            steps=[
                ImportedStep(
                    name="Buffer Mix",
                    category="Media Prep",
                    matched_unit_op_name="Buffer Mix",
                )
            ],
        )
        proposal = build_proposal(parsed, ops, "test.pdf")
        assert proposal.matched_count == 1
        assert proposal.unmatched_count == 0
        step = proposal.steps[0]
        assert step.matched_unit_op_id == str(ops[0].id)
        assert step.matched_unit_op_name == "Buffer Mix"
        assert step.is_new is False

    def test_unmatched_step(self):
        parsed = ParsedProtocol(
            protocol_name="Test",
            steps=[
                ImportedStep(
                    name="Custom Procedure",
                    category="General",
                    params=[
                        ImportedParam(
                            name="temp", type="number", unit="C", default=25.0
                        )
                    ],
                )
            ],
        )
        proposal = build_proposal(parsed, [], "test.pdf")
        assert proposal.matched_count == 0
        assert proposal.unmatched_count == 1
        step = proposal.steps[0]
        assert step.is_new is True
        assert step.matched_unit_op_id is None
        # Should have auto-generated param_schema
        assert "temp" in step.param_schema.get("properties", {})

    def test_mixed_matched_and_unmatched(self):
        ops = [_make_unit_op("Centrifugation", "Separation")]
        parsed = ParsedProtocol(
            protocol_name="Mixed Protocol",
            steps=[
                ImportedStep(
                    name="Centrifugation", matched_unit_op_name="Centrifugation"
                ),
                ImportedStep(name="Novel Step", category="Custom"),
                ImportedStep(
                    name="Centrifugation Again", matched_unit_op_name="Centrifugation"
                ),
            ],
        )
        proposal = build_proposal(parsed, ops, "test.pdf")
        assert proposal.matched_count == 2
        assert proposal.unmatched_count == 1
        assert proposal.steps[0].is_new is False
        assert proposal.steps[1].is_new is True
        assert proposal.steps[2].is_new is False

    def test_case_insensitive_match(self):
        ops = [_make_unit_op("Buffer Mix")]
        parsed = ParsedProtocol(
            protocol_name="Test",
            steps=[ImportedStep(name="buffer mix", matched_unit_op_name="buffer mix")],
        )
        proposal = build_proposal(parsed, ops, "test.pdf")
        assert proposal.steps[0].is_new is False
        assert proposal.steps[0].matched_unit_op_id == str(ops[0].id)

    def test_source_filename_and_preview(self):
        parsed = ParsedProtocol(
            protocol_name="Test",
            protocol_description="A test protocol",
            steps=[],
        )
        proposal = build_proposal(
            parsed, [], "my_sop.pdf", source_text="Hello world " * 100
        )
        assert proposal.source_filename == "my_sop.pdf"
        assert len(proposal.source_text_preview) <= 500
        assert proposal.protocol_name == "Test"

    def test_empty_steps(self):
        parsed = ParsedProtocol(protocol_name="Empty", steps=[])
        proposal = build_proposal(parsed, [], "empty.pdf")
        assert len(proposal.steps) == 0
        assert proposal.matched_count == 0
        assert proposal.unmatched_count == 0

    def test_step_roles_preserved(self):
        parsed = ParsedProtocol(
            protocol_name="Roles Test",
            steps=[
                ImportedStep(name="Step 1", role="Operator"),
                ImportedStep(name="Step 2", role="QC Lead"),
                ImportedStep(name="Step 3"),  # no role
            ],
        )
        proposal = build_proposal(parsed, [], "test.pdf")
        assert proposal.steps[0].role == "Operator"
        assert proposal.steps[1].role == "QC Lead"
        assert proposal.steps[2].role is None


# ── build_import_graph ──────────────────────────────────────────────


class TestBuildImportGraph:
    def _make_step_proposal(
        self,
        name: str = "Step",
        category: str = "General",
        duration_min: int = 30,
        role: str | None = None,
        unit_op_id: str | None = None,
    ) -> StepProposal:
        return StepProposal(
            name=name,
            description=f"Desc for {name}",
            category=category,
            duration_min=duration_min,
            params={},
            param_schema={},
            role=role,
            matched_unit_op_id=unit_op_id,
            matched_unit_op_name=name if unit_op_id else None,
            is_new=unit_op_id is None,
        )

    def test_basic_graph_structure(self):
        steps = [
            self._make_step_proposal("Step A", duration_min=10),
            self._make_step_proposal("Step B", duration_min=20),
        ]
        user_id = uuid.uuid4()
        graph = build_import_graph(steps, user_id, "test.pdf")

        assert graph["layout"] == "horizontal"
        assert graph["handleOrientation"] == "horizontal"
        assert graph["timeEnabled"] is False
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]
        op_nodes = [n for n in graph["nodes"] if n["type"] == "unitOp"]
        assert len(ps_nodes) == 1  # one processStart for ungrouped chain
        assert len(op_nodes) == 2
        # 2 edges: processStart->A, A->B
        assert len(graph["edges"]) == 2

    def test_metadata_source(self):
        steps = [self._make_step_proposal()]
        graph = build_import_graph(steps, uuid.uuid4(), "my_protocol.pdf")
        meta = graph["_metadata"]
        assert meta["source"] == "protocol_import"
        assert meta["source_filename"] == "my_protocol.pdf"
        assert "generated_by" in meta
        assert "generated_at" in meta

    def test_sequential_edges(self):
        steps = [
            self._make_step_proposal("A"),
            self._make_step_proposal("B"),
            self._make_step_proposal("C"),
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        op_nodes = [n for n in graph["nodes"] if n["type"] == "unitOp"]
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]
        # 3 edges: processStart->A, A->B, B->C
        assert len(graph["edges"]) == 3
        assert graph["edges"][0]["source"] == ps_nodes[0]["id"]
        assert graph["edges"][0]["target"] == op_nodes[0]["id"]

    def test_single_step_has_process_start_edge(self):
        steps = [self._make_step_proposal()]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]
        op_nodes = [n for n in graph["nodes"] if n["type"] == "unitOp"]
        assert len(ps_nodes) == 1
        # 1 edge: processStart -> step
        assert len(graph["edges"]) == 1
        assert graph["edges"][0]["source"] == ps_nodes[0]["id"]
        assert graph["edges"][0]["target"] == op_nodes[0]["id"]

    def test_swim_lanes_created_for_roles(self):
        steps = [
            self._make_step_proposal("Step 1", role="Operator"),
            self._make_step_proposal("Step 2", role="QC Lead"),
            self._make_step_proposal("Step 3", role="Operator"),
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")

        lane_nodes = [n for n in graph["nodes"] if n["type"] == "swimLane"]
        op_nodes = [n for n in graph["nodes"] if n["type"] == "unitOp"]
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]

        # 2 unique roles → 2 swim lanes + 2 processStart nodes
        assert len(lane_nodes) == 2
        assert len(op_nodes) == 3
        assert len(ps_nodes) == 2

        # Swim lanes have correct data
        lane_names = {n["data"]["label"] for n in lane_nodes}
        assert lane_names == {"Operator", "QC Lead"}

        # Swim lanes have zIndex -1
        for lane in lane_nodes:
            assert lane.get("zIndex") == -1

        # Op nodes with roles have parentId pointing to their lane
        operator_lane = next(n for n in lane_nodes if n["data"]["label"] == "Operator")
        qc_lane = next(n for n in lane_nodes if n["data"]["label"] == "QC Lead")

        assert op_nodes[0]["parentId"] == operator_lane["id"]
        assert op_nodes[1]["parentId"] == qc_lane["id"]
        assert op_nodes[2]["parentId"] == operator_lane["id"]

    def test_no_lanes_when_no_roles(self):
        steps = [
            self._make_step_proposal("Step 1"),
            self._make_step_proposal("Step 2"),
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        lane_nodes = [n for n in graph["nodes"] if n["type"] == "swimLane"]
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]
        assert len(lane_nodes) == 0
        assert len(ps_nodes) == 1  # one processStart for ungrouped chain

    def test_mixed_roles_and_no_roles(self):
        steps = [
            self._make_step_proposal("Step 1", role="Operator"),
            self._make_step_proposal("Step 2"),  # no role
            self._make_step_proposal("Step 3", role="Operator"),
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        lane_nodes = [n for n in graph["nodes"] if n["type"] == "swimLane"]
        op_nodes = [n for n in graph["nodes"] if n["type"] == "unitOp"]
        ps_nodes = [n for n in graph["nodes"] if n["type"] == "processStart"]

        assert len(lane_nodes) == 1  # only Operator
        assert len(ps_nodes) == 2  # one for Operator lane, one for ungrouped
        assert op_nodes[0].get("parentId") is not None  # Operator
        assert op_nodes[1].get("parentId") is None  # no role
        assert op_nodes[2].get("parentId") is not None  # Operator

    def test_swim_lane_positioning(self):
        steps = [
            self._make_step_proposal("S1", role="Role A"),
            self._make_step_proposal("S2", role="Role B"),
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        lanes = sorted(
            [n for n in graph["nodes"] if n["type"] == "swimLane"],
            key=lambda n: n["position"]["y"],
        )
        # Lanes should be stacked vertically at 220px intervals
        assert lanes[0]["position"]["y"] == 0
        assert lanes[1]["position"]["y"] == 220

    def test_node_data_fields(self):
        steps = [
            self._make_step_proposal(
                "Centrifuge",
                category="Separation",
                duration_min=45,
                unit_op_id=str(uuid.uuid4()),
            )
        ]
        graph = build_import_graph(steps, uuid.uuid4(), "test.pdf")
        node = [n for n in graph["nodes"] if n["type"] == "unitOp"][0]
        assert node["data"]["label"] == "Centrifuge"
        assert node["data"]["category"] == "Separation"
        assert node["data"]["duration_min"] == 45
        assert node["data"]["unitOpId"] == steps[0].matched_unit_op_id
