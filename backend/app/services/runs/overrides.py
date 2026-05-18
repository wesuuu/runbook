"""Pure helper functions for applying and diffing run-graph overrides.

These functions are intentionally I/O-free (no DB, no HTTP, no logging) so
they can be unit-tested directly. Callers are responsible for emitting the
returned diffs as audit entries.
"""

import copy
from typing import Any, List, TypedDict

from app.schemas.science import NodeOverrides
from app.services.runs.graph import derive_field_label


class FieldDiff(TypedDict):
    """One field-level change. Shape matches existing STEP_EDIT audit payload."""

    step_id: str
    step_name: str
    field: str
    field_label: str
    old_value: Any
    new_value: Any


def snapshot_unit_op_node(node: dict) -> None:
    """Populate `protocol_*` mirror fields on a unit-op node so the originals
    are preserved across overrides. Idempotent — re-running on a node that
    already has mirrors leaves them untouched.

    Mutates `node["data"]` in place.
    """
    data = node.setdefault("data", {})
    if "protocol_params" not in data:
        data["protocol_params"] = copy.deepcopy(data.get("params", {}))
    if "protocol_equipment" not in data:
        data["protocol_equipment"] = copy.deepcopy(data.get("equipment", []))
    if "protocol_paramSchema" not in data:
        data["protocol_paramSchema"] = copy.deepcopy(data.get("paramSchema", {}))
    if "protocol_description" not in data:
        data["protocol_description"] = data.get("description", "")


def apply_node_overrides(node: dict, ov: NodeOverrides) -> List[FieldDiff]:
    """Apply NodeOverrides to a unit-op node and return the field diffs.

    Mutates `node["data"]` in place. Assumes `snapshot_unit_op_node` has
    already been called (so mirror fields exist). Returns one FieldDiff per
    field that actually changed; same value -> no diff.
    """
    data = node["data"]
    step_id = node["id"]
    step_name = data.get("label", step_id)
    schema_props = (data.get("paramSchema") or {}).get("properties", {})
    diffs: List[FieldDiff] = []

    if ov.params is not None:
        current = data.get("params") or {}
        for key, new_val in ov.params.items():
            old_val = current.get(key)
            if old_val == new_val:
                continue
            diffs.append(
                {
                    "step_id": step_id,
                    "step_name": step_name,
                    "field": key,
                    "field_label": derive_field_label(schema_props, key),
                    "old_value": old_val,
                    "new_value": new_val,
                }
            )
        data["params"] = {**current, **ov.params}

    if ov.equipment is not None:
        old_eq = data.get("equipment") or []
        new_eq = ov.equipment
        if old_eq != new_eq:
            diffs.append(
                {
                    "step_id": step_id,
                    "step_name": step_name,
                    "field": "equipment",
                    "field_label": "Equipment",
                    "old_value": old_eq,
                    "new_value": new_eq,
                }
            )
            data["equipment"] = new_eq

    if ov.paramSchema is not None:
        old_schema = data.get("paramSchema") or {}
        if old_schema != ov.paramSchema:
            diffs.append(
                {
                    "step_id": step_id,
                    "step_name": step_name,
                    "field": "paramSchema",
                    "field_label": "Parameter schema",
                    "old_value": old_schema,
                    "new_value": ov.paramSchema,
                }
            )
            data["paramSchema"] = ov.paramSchema

    if ov.description is not None:
        old_desc = data.get("description", "")
        if old_desc != ov.description:
            diffs.append(
                {
                    "step_id": step_id,
                    "step_name": step_name,
                    "field": "description",
                    "field_label": "Instructions",
                    "old_value": old_desc,
                    "new_value": ov.description,
                }
            )
            data["description"] = ov.description

    return diffs


def diff_unit_op_node(old_node: dict, new_node: dict) -> List[FieldDiff]:
    """Compute field-level diffs between two unit-op nodes.

    Used by the PUT path to compare the in-DB graph against the incoming
    graph and emit OVERRIDE_EDIT audit entries.
    """
    old_data = old_node.get("data") or {}
    new_data = new_node.get("data") or {}
    step_id = new_node.get("id") or old_node.get("id")
    step_name = new_data.get("label") or old_data.get("label") or step_id
    schema_props = (new_data.get("paramSchema") or {}).get("properties", {})
    diffs: List[FieldDiff] = []

    old_params = old_data.get("params") or {}
    new_params = new_data.get("params") or {}
    for key in set(old_params) | set(new_params):
        if old_params.get(key) != new_params.get(key):
            diffs.append(
                {
                    "step_id": step_id,
                    "step_name": step_name,
                    "field": key,
                    "field_label": derive_field_label(schema_props, key),
                    "old_value": old_params.get(key),
                    "new_value": new_params.get(key),
                }
            )

    if (old_data.get("equipment") or []) != (new_data.get("equipment") or []):
        diffs.append(
            {
                "step_id": step_id,
                "step_name": step_name,
                "field": "equipment",
                "field_label": "Equipment",
                "old_value": old_data.get("equipment") or [],
                "new_value": new_data.get("equipment") or [],
            }
        )

    if (old_data.get("paramSchema") or {}) != (new_data.get("paramSchema") or {}):
        diffs.append(
            {
                "step_id": step_id,
                "step_name": step_name,
                "field": "paramSchema",
                "field_label": "Parameter schema",
                "old_value": old_data.get("paramSchema") or {},
                "new_value": new_data.get("paramSchema") or {},
            }
        )

    if (old_data.get("description") or "") != (new_data.get("description") or ""):
        diffs.append(
            {
                "step_id": step_id,
                "step_name": step_name,
                "field": "description",
                "field_label": "Instructions",
                "old_value": old_data.get("description") or "",
                "new_value": new_data.get("description") or "",
            }
        )

    return diffs
