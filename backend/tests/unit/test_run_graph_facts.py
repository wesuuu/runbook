"""Unit tests for services/runs/graph_facts.py."""

from __future__ import annotations

from uuid import uuid4

from app.services.runs.graph_facts import RunGraphFacts, extract_graph_facts


def test_extract_graph_facts_collects_all_three_categories():
    eq_id = uuid4()
    graph = {
        "nodes": [
            {"id": "lane-1", "type": "swimLane"},
            {"id": "lane-2", "type": "swimLane"},
            {
                "id": "op-1",
                "type": "unitOp",
                "data": {"equipment": [{"equipment_id": str(eq_id)}]},
            },
            {"id": "op-2", "type": "unitOp"},
            {"id": "start-1", "type": "processStart"},
        ]
    }
    facts = extract_graph_facts(graph)
    assert facts.swimlane_node_ids == ["lane-1", "lane-2"]
    assert facts.unit_op_node_ids == ["op-1", "op-2"]
    assert facts.equipment_ids == [eq_id]


def test_extract_graph_facts_deduplicates_equipment_ids():
    eq_id = uuid4()
    graph = {
        "nodes": [
            {"id": "op-1", "type": "unitOp",
             "data": {"equipment": [{"equipment_id": str(eq_id)}]}},
            {"id": "op-2", "type": "unitOp",
             "data": {"equipment": [{"equipment_id": str(eq_id)}]}},
        ]
    }
    assert extract_graph_facts(graph).equipment_ids == [eq_id]


def test_extract_graph_facts_skips_malformed_equipment_id():
    graph = {
        "nodes": [
            {"id": "op-1", "type": "unitOp",
             "data": {"equipment": [{"equipment_id": "not-a-uuid"}, {}]}},
        ]
    }
    assert extract_graph_facts(graph).equipment_ids == []


def test_extract_graph_facts_tolerates_empty_and_missing():
    assert extract_graph_facts({}) == RunGraphFacts()
    assert extract_graph_facts({"nodes": None}) == RunGraphFacts()
    assert extract_graph_facts({"nodes": ["junk", 3]}) == RunGraphFacts()
