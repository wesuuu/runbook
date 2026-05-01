"""Unit tests for app.services.runs.graph — pure functions, no DB."""


def test_iter_unit_op_nodes_yields_only_unit_ops():
    from app.services.runs.graph import iter_unit_op_nodes
    graph = {
        "nodes": [
            {"id": "n1", "type": "unitOp", "data": {"label": "Mix"}},
            {"id": "lane-a", "type": "swimLane", "data": {"label": "QC"}},
            {"id": "n2", "type": "unitOp", "data": {"label": "Spin"}},
            {"id": "start", "type": "processStart"},
        ],
        "edges": [],
    }
    ids = [n["id"] for n in iter_unit_op_nodes(graph)]
    assert ids == ["n1", "n2"]


def test_iter_unit_op_nodes_handles_missing_nodes_key():
    from app.services.runs.graph import iter_unit_op_nodes
    assert list(iter_unit_op_nodes({})) == []
    assert list(iter_unit_op_nodes({"nodes": None})) == []


def test_iter_unit_op_nodes_skips_nodes_without_type():
    """Defensive: a node without a 'type' field should not be treated as unit-op."""
    from app.services.runs.graph import iter_unit_op_nodes
    graph = {"nodes": [{"id": "x", "data": {}}, {"id": "y", "type": "unitOp"}]}
    assert [n["id"] for n in iter_unit_op_nodes(graph)] == ["y"]


def test_derive_field_label_uses_title_when_present():
    from app.services.runs.graph import derive_field_label
    schema_props = {"target_pH": {"type": "number", "title": "Target pH"}}
    assert derive_field_label(schema_props, "target_pH") == "Target pH"


def test_derive_field_label_falls_back_to_humanized_key():
    from app.services.runs.graph import derive_field_label
    schema_props = {"target_pH": {"type": "number"}}  # no title
    assert derive_field_label(schema_props, "target_pH") == "Target Ph"


def test_derive_field_label_falls_back_for_unknown_key():
    from app.services.runs.graph import derive_field_label
    assert derive_field_label({}, "agitation_rpm") == "Agitation Rpm"


def test_derive_field_label_handles_none_schema_props():
    from app.services.runs.graph import derive_field_label
    assert derive_field_label(None, "lot_id") == "Lot Id"
