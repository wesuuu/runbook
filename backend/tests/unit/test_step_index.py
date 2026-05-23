"""Unit tests for the index_steps helper (TD-0091c Phase 1)."""

from app.services.runs.graph import index_steps


def test_index_steps_returns_node_and_name_maps_in_one_pass():
    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Mix Buffer",
                    "paramSchema": {"properties": {"k": {"title": "K"}}},
                },
            },
            {"id": "n2", "type": "unitOp", "data": {"label": "Seed Bioreactor"}},
            {"id": "lane1", "type": "swimLane", "data": {"label": "Lane"}},
        ]
    }
    index = index_steps(graph)
    assert index.nodes["n1"]["label"] == "Mix Buffer"
    assert index.names == {"n1": "Mix Buffer", "n2": "Seed Bioreactor"}
    assert "lane1" not in index.nodes
    assert index.name_for("n1") == "Mix Buffer"
    assert index.name_for("unknown") == "unknown"


def test_index_steps_tolerates_empty_graph():
    index = index_steps(None)
    assert index.nodes == {}
    assert index.names == {}
    assert index.name_for("x") == "x"


def test_index_steps_uses_id_when_label_missing():
    graph = {"nodes": [{"id": "n1", "type": "unitOp", "data": {}}]}
    index = index_steps(graph)
    assert index.names["n1"] == "n1"
