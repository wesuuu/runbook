"""Unit tests for app.services.runs.overrides — pure functions, no DB."""


def test_snapshot_populates_mirror_fields():
    from app.services.runs.overrides import snapshot_unit_op_node

    node = {
        "id": "n1",
        "type": "unitOp",
        "data": {
            "label": "Buffer Mix",
            "params": {"pH": 7.4, "temp_c": 25},
            "equipment": [{"id": "eq1", "name": "Bioreactor A"}],
            "paramSchema": {"properties": {"pH": {"type": "number"}}},
            "description": "Mix until pH={{pH}}",
        },
    }
    snapshot_unit_op_node(node)
    d = node["data"]
    assert d["protocol_params"] == {"pH": 7.4, "temp_c": 25}
    assert d["protocol_equipment"] == [{"id": "eq1", "name": "Bioreactor A"}]
    assert d["protocol_paramSchema"] == {"properties": {"pH": {"type": "number"}}}
    assert d["protocol_description"] == "Mix until pH={{pH}}"


def test_snapshot_is_idempotent():
    from app.services.runs.overrides import snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "params": {"x": 1},
            "protocol_params": {"x": 999},  # already snapshotted with a different value
        },
    }
    snapshot_unit_op_node(node)
    # Should NOT overwrite the existing mirror.
    assert node["data"]["protocol_params"] == {"x": 999}


def test_apply_value_overrides_merges_sparsely():
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "label": "Buffer Mix",
            "params": {"pH": 7.4, "temp_c": 25},
            "paramSchema": {
                "properties": {
                    "pH": {"type": "number", "title": "Target pH"},
                    "temp_c": {"type": "number", "title": "Temperature"},
                }
            },
        },
    }
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(node, NodeOverrides(params={"pH": 6.8}))

    assert node["data"]["params"] == {"pH": 6.8, "temp_c": 25}
    assert node["data"]["protocol_params"] == {"pH": 7.4, "temp_c": 25}
    assert len(diffs) == 1
    assert diffs[0]["step_id"] == "n1"
    assert diffs[0]["step_name"] == "Buffer Mix"
    assert diffs[0]["field"] == "pH"
    assert diffs[0]["field_label"] == "Target pH"
    assert diffs[0]["old_value"] == 7.4
    assert diffs[0]["new_value"] == 6.8


def test_apply_equipment_swap_emits_one_diff():
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "label": "Centrifugation",
            "equipment": [{"id": "eq-A", "name": "Centrifuge A"}],
        },
    }
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(
        node,
        NodeOverrides(equipment=[{"id": "eq-B", "name": "Centrifuge B"}]),
    )
    assert node["data"]["equipment"] == [{"id": "eq-B", "name": "Centrifuge B"}]
    assert node["data"]["protocol_equipment"] == [
        {"id": "eq-A", "name": "Centrifuge A"}
    ]
    assert len(diffs) == 1
    assert diffs[0]["field"] == "equipment"
    assert diffs[0]["field_label"] == "Equipment"


def test_apply_paramSchema_replacement_emits_one_diff():
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "label": "Buffer Mix",
            "paramSchema": {"properties": {"pH": {"type": "number"}}},
        },
    }
    snapshot_unit_op_node(node)
    new_schema = {
        "properties": {
            "pH": {"type": "number"},
            "buffer_lot": {"type": "string", "title": "Buffer lot"},
        }
    }
    diffs = apply_node_overrides(node, NodeOverrides(paramSchema=new_schema))
    assert node["data"]["paramSchema"] == new_schema
    assert len(diffs) == 1
    assert diffs[0]["field"] == "paramSchema"


def test_apply_description_override_emits_one_diff():
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "label": "Buffer Mix",
            "description": "Mix until pH={{pH}}",
        },
    }
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(
        node,
        NodeOverrides(description="Adjust to {{pH}} using 1M HCl"),
    )
    assert node["data"]["description"] == "Adjust to {{pH}} using 1M HCl"
    assert node["data"]["protocol_description"] == "Mix until pH={{pH}}"
    assert len(diffs) == 1
    assert diffs[0]["field"] == "description"


def test_apply_no_override_returns_no_diffs():
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {"id": "n1", "data": {"label": "X", "params": {"a": 1}}}
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(node, NodeOverrides())  # all fields None
    assert diffs == []
    assert node["data"]["params"] == {"a": 1}


def test_apply_same_value_emits_no_diff():
    """If override equals current value, no audit entry should be produced."""
    from app.schemas.science import NodeOverrides
    from app.services.runs.overrides import apply_node_overrides, snapshot_unit_op_node

    node = {
        "id": "n1",
        "data": {
            "label": "X",
            "params": {"pH": 7.4},
            "paramSchema": {"properties": {"pH": {}}},
        },
    }
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(node, NodeOverrides(params={"pH": 7.4}))
    assert diffs == []


def test_diff_unit_op_node_detects_param_change():
    from app.services.runs.overrides import diff_unit_op_node

    old = {"id": "n1", "data": {"label": "X", "params": {"pH": 7.4}}}
    new = {"id": "n1", "data": {"label": "X", "params": {"pH": 6.8}}}
    diffs = diff_unit_op_node(old, new)
    assert len(diffs) == 1
    assert diffs[0]["field"] == "pH"
    assert diffs[0]["old_value"] == 7.4
    assert diffs[0]["new_value"] == 6.8


def test_diff_unit_op_node_detects_added_param():
    from app.services.runs.overrides import diff_unit_op_node

    old = {"id": "n1", "data": {"label": "X", "params": {"pH": 7.4}}}
    new = {"id": "n1", "data": {"label": "X", "params": {"pH": 7.4, "lot": "L42"}}}
    diffs = diff_unit_op_node(old, new)
    assert len(diffs) == 1
    assert diffs[0]["field"] == "lot"
    assert diffs[0]["old_value"] is None
    assert diffs[0]["new_value"] == "L42"


def test_diff_unit_op_node_detects_equipment_swap():
    from app.services.runs.overrides import diff_unit_op_node

    old = {"id": "n1", "data": {"label": "X", "equipment": [{"id": "eq-A"}]}}
    new = {"id": "n1", "data": {"label": "X", "equipment": [{"id": "eq-B"}]}}
    diffs = diff_unit_op_node(old, new)
    assert len(diffs) == 1
    assert diffs[0]["field"] == "equipment"


def test_diff_unit_op_node_no_diff_when_unchanged():
    from app.services.runs.overrides import diff_unit_op_node

    node_a = {"id": "n1", "data": {"label": "X", "params": {"pH": 7.4}}}
    node_b = {"id": "n1", "data": {"label": "X", "params": {"pH": 7.4}}}
    diffs = diff_unit_op_node(node_a, node_b)
    assert diffs == []
