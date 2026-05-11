# F-0081 Phase 2 — Backend Override API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `POST /science/runs` to accept per-unit-op overrides (param values, equipment, schema, instructions) and `PUT /science/runs/{id}` to allow editing them while `PLANNED`. Each override is applied to a deep-copied graph snapshot, the protocol defaults are mirrored into `protocol_*` fields on each unit-op node, and every changed field emits one `OVERRIDE_SET` (create) or `OVERRIDE_EDIT` (update) audit entry — keeping payloads identical to the existing `STEP_EDIT` shape.

**Architecture:** All changes live at the API + service layer — overrides are stored entirely inside `Run.graph` (JSONB), so this phase needs no DB migration. A new pure-function module `app/services/runs/overrides.py` contains all merge / mirror / diff logic so create + update share it and unit tests can exercise the merge rules without HTTP.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 (async) / Pydantic v2 / pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-04-29-f-0081-run-parameter-overrides-design.md`](../specs/2026-04-29-f-0081-run-parameter-overrides-design.md) — Phase 2 section.

**Phase 1 plan (already shipped):** [`docs/superpowers/plans/2026-04-29-f-0081-phase-1-protocol-version-description.md`](2026-04-29-f-0081-phase-1-protocol-version-description.md).

---

## File map

**Modify:**
- `backend/app/schemas/science.py:281-292` — extend `RunCreate` with `protocol_version_number` + `overrides`.
- `backend/app/schemas/science.py` (after `RunResponse`) — add `NodeOverrides` and `RunOverrides` schemas.
- `backend/app/api/endpoints/runs.py:225` — replace inline `unit_op_ids = [...]` filter with `iter_unit_op_nodes(graph)`.
- `backend/app/api/endpoints/runs.py:244-264` — replace inline `_node_map` build + inline `field_label` derivation in execution_data audit path with `iter_unit_op_nodes` + `derive_field_label`.
- `backend/app/api/endpoints/runs.py:355-361` — replace inline `_name_map` build with `iter_unit_op_nodes`.
- `backend/app/api/endpoints/runs.py:50-110` — `create_run` deep-copies the graph, fetches the right `ProtocolVersion` if requested, snapshots the protocol mirror fields onto each unit-op node, applies overrides, emits audit entries.
- `backend/app/api/endpoints/runs.py:150-410` — `update_run` rejects graph edits when `status != PLANNED`, computes a diff of the new graph against the old one, emits one `OVERRIDE_EDIT` audit entry per changed field.

**Create:**
- `backend/app/services/runs/__init__.py` — empty package marker.
- `backend/app/services/runs/graph.py` — `iter_unit_op_nodes(graph)` generator and `derive_field_label(schema_props, key)`. Replaces inline duplications in `runs.py` and is shared with `overrides.py`. **No DB / no HTTP / no I/O.**
- `backend/app/services/runs/overrides.py` — pure helper functions for run overrides: `snapshot_unit_op_node`, `apply_node_overrides`, `diff_unit_op_node`. Imports `derive_field_label` from `graph.py`. **No DB / no HTTP / no I/O.**
- `backend/tests/unit/test_run_graph_helpers.py` — unit tests for `graph.py`.
- `backend/tests/unit/test_run_overrides_helpers.py` — unit tests for `overrides.py`.
- `backend/tests/integration/test_run_overrides.py` — integration tests for the create + update endpoints.

---

## Decisions locked at planning time

A few things the spec leaves underspecified — pinning them here so every task uses the same shape:

- **`NodeOverrides.equipment` type:** `List[Dict[str, Any]]`. The codebase has no `SelectedEquipment` Pydantic schema today (frontend stores equipment as a list of dicts in the graph). Introducing one is out of scope; we accept whatever shape the frontend sends. (Spec referenced `List[SelectedEquipment]` aspirationally — not present in code.)
- **Audit entry shape:** identical to the existing `STEP_EDIT` shape used at `runs.py:281-303`: `{step_id, step_name, field, field_label, old_value, new_value}`. New `OVERRIDE_SET` / `OVERRIDE_EDIT` actions reuse it verbatim.
- **`field` values:** literal param keys for params (e.g. `"target_pH"`), `"equipment"` for equipment, `"paramSchema"` (whole-schema replacement) for schema changes, `"description"` for instructions. We do not break paramSchema down per-property — the wizard treats schema add/remove as one unit, and the frontend can render the diff itself.
- **Idempotency:** `snapshot_unit_op_node` is idempotent — re-running on a node that already has `protocol_*` mirrors is a no-op. This matters because `update_run` may run on graphs that have already been snapshotted.
- **Test layout:** integration tests go in `backend/tests/integration/test_run_overrides.py` (flat, matching the project's existing layout — tests are flat, not nested under `api/`). Unit tests for helpers go in `backend/tests/unit/test_run_overrides_helpers.py`.

---

## Reuse considerations

The spec's Reuse Audit (design doc lines 56-86) is overwhelmingly frontend (`renderTemplate`, `EquipmentPickerModal`, `VersionHistoryDrawer`, `<ParamInput>`, `<SchemaEditor>`, `<EquipmentChipList>`). None of those apply to Phase 2 — they all land in Phase 3.

**What we're explicitly reusing on the backend:**

| Existing | Where today | How Phase 2 reuses it |
|---|---|---|
| `log_audit(db, user_id, action, entity_type, entity_id, changes)` | `app/services/core/audit.py:15` | Direct calls — no new audit machinery. |
| `STEP_EDIT` audit payload shape: `{step_id, step_name, field, field_label, old_value, new_value}` | `runs.py:281-303` (execution_data edits) | **Identical** shape used for new `OVERRIDE_SET` / `OVERRIDE_EDIT` actions. The frontend's `RunHistory.svelte` audit renderer (Phase 3) only needs to add labels for the two new action verbs to its existing label map — no new entry shape. |
| `check_permission`, `get_or_404`, `require_active_subscription`, `Depends(get_current_user)`, `Depends(get_db)` | `app/core/deps.py` | Standard endpoint dependencies — unchanged from existing `create_run`/`update_run`. |
| `flag_modified(run_obj, "graph")` | already imported in `runs.py:13` | Used after in-place JSONB mutation, matching the existing convention. |
| `RunCreate` / `RunUpdate` Pydantic schemas | `schemas/science.py:281,288` | Extended in place rather than replaced — backwards-compatible (every new field is `Optional` with a default). |
| `Run.graph` JSONB column | `models/science.py:158` | All overrides + mirror fields live inside this existing column — no migration. |

**Cleaned up in this phase (existing inline duplicates migrated to the new helpers):**

| Pattern | Where today | Resolution |
|---|---|---|
| `field_label = prop.get("title") or key.replace("_", " ").title()` | inline at `runs.py:286-291` (execution_data `STEP_EDIT` audit path) | Extracted to `derive_field_label(schema_props, key)` in `app/services/runs/graph.py`. Existing `runs.py` callsite migrated in Task 3. New override helpers import the same function. **One source of truth.** |
| `for n in graph["nodes"]: if n.get("type") == "unitOp"` | inline at `runs.py:225` (step-completion check), `runs.py:247-250` (execution_data audit `_node_map`), `runs.py:357-361` (`_name_map`) | Extracted to `iter_unit_op_nodes(graph)` generator in `app/services/runs/graph.py`. All three existing callsites migrated in Task 3. New code in Tasks 4 + 6 uses the same iterator. |

**Sharing inside Phase 2 itself:**

The whole point of `app/services/runs/overrides.py` is to give `create_run` and `update_run` a single source of truth for snapshot/merge/diff. `apply_node_overrides` is called by `create_run` (Task 4); `diff_unit_op_node` is called by `update_run` (Task 6); `snapshot_unit_op_node` is called by `create_run` and is idempotent so a future PUT path that needs to re-snapshot (e.g., during a future schema migration) can call it safely. Both modules import their shared utilities from `app/services/runs/graph.py`.

---

## Task 1 — Override Pydantic schemas

Add `NodeOverrides`, `RunOverrides`, and extend `RunCreate`. No endpoint behavior changes yet — wired up in Tasks 3 and 4.

**Files:**
- Modify: `backend/app/schemas/science.py` (extend `RunCreate` at line 281; add new schemas after `RunResponse`)

- [ ] **Step 1: Add `NodeOverrides` and `RunOverrides`**

Append after `RunResponse` (around line 309):

```python
# --- Run Overrides (F-0081) ---


class NodeOverrides(BaseModel):
    """Sparse overrides for a single unit-op node in a run snapshot.

    All fields optional. `params` is a sparse dict (only the keys being
    overridden); `equipment`, `paramSchema`, and `description` are full
    replacements. None means "inherit from protocol default".
    """
    params: Optional[Dict[str, Any]] = None
    equipment: Optional[List[Dict[str, Any]]] = None
    paramSchema: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class RunOverrides(BaseModel):
    """Per-run edits to a protocol snapshot, keyed by unit-op node id."""
    nodes: Dict[str, NodeOverrides] = Field(default_factory=dict)
```

- [ ] **Step 2: Extend `RunCreate`**

Replace the existing `RunCreate` (lines 281-285) with:

```python
class RunCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None
    protocol_version_number: Optional[int] = None
    experiment_id: Optional[UUID] = None
    overrides: Optional["RunOverrides"] = None
```

The forward-reference `"RunOverrides"` is needed because `RunOverrides` is defined below `RunCreate` in the file. Pydantic v2 resolves these automatically when `model_rebuild()` is called (or on first use).

- [ ] **Step 3: Resolve forward references**

After the `RunOverrides` class definition, add a `model_rebuild()` call so the `"RunOverrides"` forward-ref in `RunCreate` is resolved:

```python
RunCreate.model_rebuild()
```

- [ ] **Step 4: Spot-check that imports parse**

```bash
cd backend && source /home/wesuuu/Code/trellisbio/backend/.venv/bin/activate
python -c "from app.schemas.science import RunCreate, RunOverrides, NodeOverrides; \
            r = RunCreate(name='t', project_id='00000000-0000-0000-0000-000000000001', \
                          overrides=RunOverrides(nodes={'n1': NodeOverrides(params={'x': 1})})); \
            print(r.model_dump())"
```

Expected: a dict containing `'overrides': {'nodes': {'n1': {'params': {'x': 1}, 'equipment': None, 'paramSchema': None, 'description': None}}}` (or similar — Pydantic may include defaults).

- [ ] **Step 5: Commit (combined with Task 2 — don't commit alone)**

Defer commit. Task 2 introduces the helpers that consume these schemas; the two commits are tightly coupled.

---

## Task 2 — Pure helper modules + unit tests

Two new modules under `app/services/runs/`. `graph.py` holds the small graph-navigation + label-derivation utilities that both the new override code AND the existing `runs.py` execution_data audit code will share. `overrides.py` holds the override-specific snapshot/merge/diff helpers and imports from `graph.py`.

**Files:**
- Create: `backend/app/services/runs/__init__.py`
- Create: `backend/app/services/runs/graph.py`
- Create: `backend/app/services/runs/overrides.py`
- Create: `backend/tests/unit/test_run_graph_helpers.py`
- Create: `backend/tests/unit/test_run_overrides_helpers.py`

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p backend/app/services/runs
touch backend/app/services/runs/__init__.py
```

- [ ] **Step 2: Write failing unit tests for `graph.py`**

Create `backend/tests/unit/test_run_graph_helpers.py`:

```python
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
```

- [ ] **Step 3: Run the tests — expect failure (module does not exist)**

```bash
cd backend && source /home/wesuuu/Code/trellisbio/backend/.venv/bin/activate
pytest tests/unit/test_run_graph_helpers.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.runs.graph'`.

- [ ] **Step 4: Implement `graph.py`**

Create `backend/app/services/runs/graph.py`:

```python
"""Pure graph-navigation + audit-label helpers for runs.

Used by both `app.services.runs.overrides` and by the existing audit /
validation code in `app.api.endpoints.runs`. Single source of truth for:
  - filtering a graph's nodes to just unit-op nodes
  - deriving a human-readable field label from a paramSchema property
"""
from typing import Any, Iterator, Optional


def iter_unit_op_nodes(graph: Optional[dict]) -> Iterator[dict]:
    """Yield every node in `graph["nodes"]` whose `type == "unitOp"`.

    Tolerant of `graph` being None, missing the `nodes` key, or having
    `nodes` set to None — returns an empty iterator in all those cases.
    """
    if not graph:
        return
    nodes = graph.get("nodes") or []
    for node in nodes:
        if isinstance(node, dict) and node.get("type") == "unitOp":
            yield node


def derive_field_label(schema_props: Optional[dict], key: str) -> str:
    """Return a human-readable label for a paramSchema property key.

    Prefers the `title` from the schema; falls back to a humanized version
    of the key (snake_case → Title Case). Tolerant of `schema_props` being
    None or the key being absent.
    """
    if isinstance(schema_props, dict):
        prop = schema_props.get(key, {}) or {}
        title = prop.get("title") if isinstance(prop, dict) else None
        if title:
            return title
    return key.replace("_", " ").title()
```

- [ ] **Step 5: Run the tests — expect pass**

```bash
pytest tests/unit/test_run_graph_helpers.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Write failing unit tests for `overrides.py`**

Create `backend/tests/unit/test_run_overrides_helpers.py`:

```python
"""Unit tests for app.services.runs.overrides — pure functions, no DB."""
import pytest


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
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
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
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
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
    assert node["data"]["protocol_equipment"] == [{"id": "eq-A", "name": "Centrifuge A"}]
    assert len(diffs) == 1
    assert diffs[0]["field"] == "equipment"
    assert diffs[0]["field_label"] == "Equipment"


def test_apply_paramSchema_replacement_emits_one_diff():
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
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
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
    node = {
        "id": "n1",
        "data": {
            "label": "Buffer Mix",
            "description": "Mix until pH={{pH}}",
        },
    }
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(
        node, NodeOverrides(description="Adjust to {{pH}} using 1M HCl"),
    )
    assert node["data"]["description"] == "Adjust to {{pH}} using 1M HCl"
    assert node["data"]["protocol_description"] == "Mix until pH={{pH}}"
    assert len(diffs) == 1
    assert diffs[0]["field"] == "description"


def test_apply_no_override_returns_no_diffs():
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
    node = {"id": "n1", "data": {"label": "X", "params": {"a": 1}}}
    snapshot_unit_op_node(node)
    diffs = apply_node_overrides(node, NodeOverrides())  # all fields None
    assert diffs == []
    assert node["data"]["params"] == {"a": 1}


def test_apply_same_value_emits_no_diff():
    """If override equals current value, no audit entry should be produced."""
    from app.services.runs.overrides import (apply_node_overrides,
                                             snapshot_unit_op_node)
    from app.schemas.science import NodeOverrides
    node = {
        "id": "n1",
        "data": {"label": "X", "params": {"pH": 7.4}, "paramSchema": {"properties": {"pH": {}}}},
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
```

- [ ] **Step 7: Run the tests — expect all to fail (module does not exist)**

```bash
cd backend && source /home/wesuuu/Code/trellisbio/backend/.venv/bin/activate
pytest tests/unit/test_run_overrides_helpers.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.runs.overrides'`. All tests error out at import time.

- [ ] **Step 8: Implement the helper module**

Create `backend/app/services/runs/overrides.py`:

```python
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
            diffs.append({
                "step_id": step_id,
                "step_name": step_name,
                "field": key,
                "field_label": derive_field_label(schema_props, key),
                "old_value": old_val,
                "new_value": new_val,
            })
        data["params"] = {**current, **ov.params}

    if ov.equipment is not None:
        old_eq = data.get("equipment") or []
        new_eq = ov.equipment
        if old_eq != new_eq:
            diffs.append({
                "step_id": step_id,
                "step_name": step_name,
                "field": "equipment",
                "field_label": "Equipment",
                "old_value": old_eq,
                "new_value": new_eq,
            })
            data["equipment"] = new_eq

    if ov.paramSchema is not None:
        old_schema = data.get("paramSchema") or {}
        if old_schema != ov.paramSchema:
            diffs.append({
                "step_id": step_id,
                "step_name": step_name,
                "field": "paramSchema",
                "field_label": "Parameter schema",
                "old_value": old_schema,
                "new_value": ov.paramSchema,
            })
            data["paramSchema"] = ov.paramSchema

    if ov.description is not None:
        old_desc = data.get("description", "")
        if old_desc != ov.description:
            diffs.append({
                "step_id": step_id,
                "step_name": step_name,
                "field": "description",
                "field_label": "Instructions",
                "old_value": old_desc,
                "new_value": ov.description,
            })
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
            diffs.append({
                "step_id": step_id,
                "step_name": step_name,
                "field": key,
                "field_label": derive_field_label(schema_props, key),
                "old_value": old_params.get(key),
                "new_value": new_params.get(key),
            })

    if (old_data.get("equipment") or []) != (new_data.get("equipment") or []):
        diffs.append({
            "step_id": step_id,
            "step_name": step_name,
            "field": "equipment",
            "field_label": "Equipment",
            "old_value": old_data.get("equipment") or [],
            "new_value": new_data.get("equipment") or [],
        })

    if (old_data.get("paramSchema") or {}) != (new_data.get("paramSchema") or {}):
        diffs.append({
            "step_id": step_id,
            "step_name": step_name,
            "field": "paramSchema",
            "field_label": "Parameter schema",
            "old_value": old_data.get("paramSchema") or {},
            "new_value": new_data.get("paramSchema") or {},
        })

    if (old_data.get("description") or "") != (new_data.get("description") or ""):
        diffs.append({
            "step_id": step_id,
            "step_name": step_name,
            "field": "description",
            "field_label": "Instructions",
            "old_value": old_data.get("description") or "",
            "new_value": new_data.get("description") or "",
        })

    return diffs
```

- [ ] **Step 9: Run the override tests — expect all to pass**

```bash
pytest tests/unit/test_run_overrides_helpers.py -v
```

Expected: 12 passed.

- [ ] **Step 10: Commit (Tasks 1 + 2 together)**

```bash
git add backend/app/schemas/science.py backend/app/services/runs/__init__.py \
        backend/app/services/runs/graph.py \
        backend/app/services/runs/overrides.py \
        backend/tests/unit/test_run_graph_helpers.py \
        backend/tests/unit/test_run_overrides_helpers.py
git commit -m "feat(F-0081): override schemas + pure helper modules for graph nav and snapshot/merge/diff"
```

---

## Task 3 — Migrate existing `runs.py` to use the new helpers

Three places in `runs.py` already iterate `graph["nodes"]` and filter on `type == "unitOp"`, and one place derives a `field_label` inline. Migrate them to `iter_unit_op_nodes` and `derive_field_label` so the new override code in Tasks 4–6 doesn't introduce parallel duplicates.

Existing integration tests (`test_science_api.py`, `test_run_attachments.py`, `test_run_notes.py`) act as the regression net — the refactor is a no-op behaviorally; if anything goes red, revert.

**Files:**
- Modify: `backend/app/api/endpoints/runs.py` — three callsites + one inline `field_label`

- [ ] **Step 1: Add the imports**

Edit `backend/app/api/endpoints/runs.py`. Find the existing imports for `app.services.core.audit` (around line 31) and add a new import line right below:

```python
from app.services.runs.graph import derive_field_label, iter_unit_op_nodes
```

- [ ] **Step 2: Migrate the step-completion check (around line 225)**

Find this block in `update_run` (around lines 222-225 in the COMPLETED transition):

```python
            exec_data = update_data.execution_data or run_obj.execution_data or {}
            graph = run_obj.graph or {}
            nodes = graph.get("nodes", [])
            unit_op_ids = [n["id"] for n in nodes if n.get("type") == "unitOp"]
```

Replace with:

```python
            exec_data = update_data.execution_data or run_obj.execution_data or {}
            unit_op_ids = [n["id"] for n in iter_unit_op_nodes(run_obj.graph)]
```

(The intermediate `graph` and `nodes` locals were only used for the comprehension; dropping them is part of the cleanup.)

- [ ] **Step 3: Migrate the execution_data audit `_node_map` build (around lines 246-264)**

Find this block in `update_run` (the EDITED-status execution_data audit path):

```python
            # Build step name + param schema lookup from graph
            graph = run_obj.graph or {}
            _node_map: dict[str, dict] = {}
            for n in graph.get("nodes", []):
                if n.get("type") == "unitOp":
                    _node_map[n["id"]] = n.get("data", {})
```

Replace with:

```python
            # Build step name + param schema lookup from graph
            _node_map: dict[str, dict] = {
                n["id"]: n.get("data", {})
                for n in iter_unit_op_nodes(run_obj.graph)
            }
```

- [ ] **Step 4: Migrate the inline `field_label` derivation (around lines 286-291)**

Find this block (still inside the EDITED-status loop):

```python
                        if old_val != new_val:
                            prop = param_schema_props.get(field_key, {})
                            field_label = (
                                prop.get("title")
                                or field_key.replace("_", " ").title()
                            )
                            await log_audit(
```

Replace with:

```python
                        if old_val != new_val:
                            field_label = derive_field_label(
                                param_schema_props, field_key,
                            )
                            await log_audit(
```

(The local `prop = param_schema_props.get(field_key, {})` was only used by the inline derivation, so it can go. `param_schema_props` itself is still the lookup dict that `derive_field_label` consumes — keep its existing assignment a few lines earlier in the loop.)

- [ ] **Step 5: Migrate the `_name_map` build (around lines 355-361)**

Find this block in `update_run` (the step-completion / step-uncomplete audit path):

```python
        # Build step name lookup from graph
        _graph = run_obj.graph or {}
        _name_map: dict[str, str] = {}
        for _n in _graph.get("nodes", []):
            if _n.get("type") == "unitOp":
                _name_map[_n["id"]] = _n.get("data", {}).get("label", _n["id"])
```

Replace with:

```python
        # Build step name lookup from graph
        _name_map: dict[str, str] = {
            n["id"]: n.get("data", {}).get("label", n["id"])
            for n in iter_unit_op_nodes(run_obj.graph)
        }
```

- [ ] **Step 6: Run the existing run-related integration tests as a regression check**

```bash
cd backend && source /home/wesuuu/Code/trellisbio/backend/.venv/bin/activate
pytest tests/integration/test_science_api.py tests/integration/test_run_attachments.py tests/integration/test_run_notes.py -q
```

Expected: all pass (same counts as before this task). If anything fails, the refactor introduced a regression — read the error, compare your edited `runs.py` against the original at `git show HEAD:backend/app/api/endpoints/runs.py | sed -n '220,365p'`, and fix.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/runs.py
git commit -m "refactor(F-0081): consolidate unit-op iteration + field_label derivation in runs.py"
```

---

## Task 4 — `create_run` wiring (deep copy + version fetch + apply + audit)

The biggest behavioral change. Each step writes one (or a couple closely-related) tests, then makes them pass. Six tests; six steps.

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:50-110`
- Test: `backend/tests/integration/test_run_overrides.py` (new file)

- [ ] **Step 1: Set up the test file scaffolding**

Create `backend/tests/integration/test_run_overrides.py`:

```python
"""Integration tests for run override behavior on POST/PUT /science/runs.

These exercise the full HTTP path so the service-layer helpers and the
endpoint plumbing are tested together.
"""
import copy

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AuditLog
from app.models.science import Project, Protocol, ProtocolVersion, Run


def _sample_protocol_graph() -> dict:
    """A minimal but realistic protocol graph: two unit-op nodes."""
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Buffer Mix",
                    "params": {"pH": 7.4, "temp_c": 25},
                    "equipment": [{"id": "eq-A", "name": "Bioreactor A"}],
                    "paramSchema": {
                        "properties": {
                            "pH": {"type": "number", "title": "Target pH"},
                            "temp_c": {"type": "number", "title": "Temperature"},
                        }
                    },
                    "description": "Mix until pH={{pH}}",
                },
            },
            {
                "id": "n2",
                "type": "unitOp",
                "data": {
                    "label": "Centrifugation",
                    "params": {"rpm": 4000},
                    "equipment": [{"id": "cf-A", "name": "Centrifuge A"}],
                    "paramSchema": {
                        "properties": {
                            "rpm": {"type": "number", "title": "Spin speed"}
                        }
                    },
                    "description": "Spin at {{rpm}} rpm",
                },
            },
        ],
        "edges": [],
    }


async def _seed_protocol(
    db_session: AsyncSession,
    project: Project,
    graph: dict | None = None,
) -> Protocol:
    p = Protocol(
        name="Test Protocol",
        project_id=project.id,
        status="APPROVED",
        version_number=1,
        graph=graph or _sample_protocol_graph(),
    )
    db_session.add(p)
    await db_session.flush()
    return p
```

- [ ] **Step 2: Test — no overrides → graph identical, mirrors populated, deep copy holds**

Append:

```python
@pytest.mark.asyncio
async def test_create_run_no_overrides_populates_mirror_fields(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """With no overrides, every unit-op node still gets its protocol_* mirror
    fields populated, and Run.graph is a deep copy of Protocol.graph."""
    protocol = await _seed_protocol(db_session, test_project)
    original_graph = copy.deepcopy(protocol.graph)

    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run 1",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Reload run + protocol
    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    nodes = run.graph["nodes"]
    n1 = next(n for n in nodes if n["id"] == "n1")

    # Mirror fields populated
    assert n1["data"]["protocol_params"] == {"pH": 7.4, "temp_c": 25}
    assert n1["data"]["protocol_equipment"] == [{"id": "eq-A", "name": "Bioreactor A"}]
    assert n1["data"]["protocol_description"] == "Mix until pH={{pH}}"
    # Effective values unchanged
    assert n1["data"]["params"] == {"pH": 7.4, "temp_c": 25}

    # Deep-copy regression: mutating run.graph does NOT mutate protocol.graph
    n1["data"]["params"]["pH"] = 999
    await db_session.flush()
    fresh_protocol = (
        await db_session.execute(select(Protocol).where(Protocol.id == protocol.id))
    ).scalar_one()
    assert fresh_protocol.graph == original_graph, (
        "Mutating Run.graph leaked into Protocol.graph — likely a shallow copy bug"
    )
```

Run it — expect failure:

```bash
pytest tests/integration/test_run_overrides.py::test_create_run_no_overrides_populates_mirror_fields -v
```

Expected: FAIL because `protocol_params` etc. are not in the response (current code doesn't populate them); the deep-copy assertion may also fail because the existing endpoint uses `.copy()` (shallow).

- [ ] **Step 3: Wire create_run to deep-copy + snapshot mirrors**

Edit `backend/app/api/endpoints/runs.py`. Add the import at the top of the file:

```python
import copy
```

(Likely already imported via line 1 — the existing `import copy` may or may not be present; check before adding a duplicate.) Also extend the existing schema/model imports and add the override-helper import:

```python
from app.schemas.science import (RunAttachment, RunAttachmentListResponse,
                                 RunCreate, RunNote, RunNoteCreate,
                                 RunNoteListResponse, RunOverrides,
                                 RunResponse, RunRoleAssignmentCreate,
                                 RunRoleAssignmentListResponse,
                                 RunRoleAssignmentResponse, RunUpdate)
from app.models.science import (Project, Protocol, ProtocolVersion, Run,
                                RunRoleAssignment)
from app.services.runs.overrides import (apply_node_overrides,
                                         diff_unit_op_node,
                                         snapshot_unit_op_node)
```

(`iter_unit_op_nodes` was already imported in Task 3 from `app.services.runs.graph` — don't add a duplicate.)

Replace the existing `create_run` function body (`runs.py:53-110`) with:

```python
async def create_run(
    run_in: RunCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        run_in.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == run_in.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    initial_graph: dict = {}
    if run_in.protocol_id:
        result = await db.execute(
            select(Protocol).where(Protocol.id == run_in.protocol_id)
        )
        protocol = result.scalar_one_or_none()
        if protocol is None:
            raise HTTPException(status_code=404, detail="Protocol not found")
        if protocol.status == "ARCHIVED":
            raise HTTPException(
                status_code=400,
                detail="Cannot create run from archived protocol",
            )

        # Resolve which graph to snapshot: a specific version, else current.
        if run_in.protocol_version_number is not None:
            v_result = await db.execute(
                select(ProtocolVersion).where(
                    (ProtocolVersion.protocol_id == protocol.id)
                    & (ProtocolVersion.version_number == run_in.protocol_version_number)
                    & (ProtocolVersion.is_draft == False)  # noqa: E712
                )
            )
            version = v_result.scalar_one_or_none()
            if version is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Protocol version {run_in.protocol_version_number} "
                        f"not found for this protocol"
                    ),
                )
            initial_graph = copy.deepcopy(version.graph or {})
        else:
            initial_graph = copy.deepcopy(protocol.graph or {})

        # Snapshot protocol_* mirror fields on every unit-op node.
        for node in iter_unit_op_nodes(initial_graph):
            snapshot_unit_op_node(node)

    run_obj = Run(
        name=run_in.name,
        project_id=run_in.project_id,
        protocol_id=run_in.protocol_id,
        experiment_id=run_in.experiment_id,
        graph=initial_graph,
        execution_data={},
    )
    db.add(run_obj)
    await db.flush()

    # Apply overrides if provided.
    override_diffs = []
    if run_in.overrides is not None:
        node_index = {n["id"]: n for n in iter_unit_op_nodes(run_obj.graph)}
        for node_id, ov in run_in.overrides.nodes.items():
            node = node_index.get(node_id)
            if node is None:
                # Unknown node id: ignore (sparse override addressing a missing
                # node is a frontend bug, but we don't want to 500 on it).
                continue
            override_diffs.extend(apply_node_overrides(node, ov))
        # Notify SQLAlchemy that we mutated the JSONB column in place.
        flag_modified(run_obj, "graph")

    await log_audit(
        db, user.id, "CREATE", "Run",
        run_obj.id, {"name": run_in.name},
    )
    for d in override_diffs:
        await log_audit(
            db, user.id, "OVERRIDE_SET", "Run", run_obj.id, d,
        )

    await db.commit()
    await db.refresh(run_obj)
    return run_obj
```

Notes:
- `flag_modified` is already imported at the top of `runs.py` (line 13).
- `ProtocolVersion` was previously not in the import list at line 24 — make sure you add it (the import block above does so).

Run the test:

```bash
pytest tests/integration/test_run_overrides.py::test_create_run_no_overrides_populates_mirror_fields -v
```

Expected: PASS.

- [ ] **Step 4: Test — sparse value override + audit entry per field**

Append to `test_run_overrides.py`:

```python
@pytest.mark.asyncio
async def test_create_run_sparse_value_overrides(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Sparse override merges with defaults; mirrors preserve originals; one
    OVERRIDE_SET audit entry per overridden field."""
    protocol = await _seed_protocol(db_session, test_project)

    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run pH",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {
                    "n1": {"params": {"pH": 6.8}},
                }
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert n1["data"]["params"] == {"pH": 6.8, "temp_c": 25}
    assert n1["data"]["protocol_params"] == {"pH": 7.4, "temp_c": 25}

    # Audit: one OVERRIDE_SET entry for pH
    audit_q = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "Run")
            & (AuditLog.entity_id == run.id)
            & (AuditLog.action == "OVERRIDE_SET")
        )
    )
    entries = audit_q.scalars().all()
    assert len(entries) == 1
    assert entries[0].changes["step_id"] == "n1"
    assert entries[0].changes["field"] == "pH"
    assert entries[0].changes["field_label"] == "Target pH"
    assert entries[0].changes["old_value"] == 7.4
    assert entries[0].changes["new_value"] == 6.8
```

Run:

```bash
pytest tests/integration/test_run_overrides.py::test_create_run_sparse_value_overrides -v
```

Expected: PASS (the wiring done in Step 3 already covers it). If this test fails, debug before continuing — the helper or the audit emission has a bug.

- [ ] **Step 5: Test — equipment swap, paramSchema replacement, description override**

Append three more tests:

```python
@pytest.mark.asyncio
async def test_create_run_equipment_swap(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run swap",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {
                    "n2": {"equipment": [{"id": "cf-B", "name": "Centrifuge B"}]},
                }
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (await db_session.execute(
        select(Run).where(Run.id == resp.json()["id"])
    )).scalar_one()
    n2 = next(n for n in run.graph["nodes"] if n["id"] == "n2")
    assert n2["data"]["equipment"] == [{"id": "cf-B", "name": "Centrifuge B"}]
    assert n2["data"]["protocol_equipment"] == [{"id": "cf-A", "name": "Centrifuge A"}]


@pytest.mark.asyncio
async def test_create_run_paramSchema_override(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Replacing paramSchema (e.g. wizard added a new param row) is stored as
    a full schema replacement; mirror keeps original."""
    protocol = await _seed_protocol(db_session, test_project)
    new_schema = {
        "properties": {
            "pH": {"type": "number", "title": "Target pH"},
            "temp_c": {"type": "number", "title": "Temperature"},
            "buffer_lot": {"type": "string", "title": "Buffer lot"},
        }
    }
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run schema",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {"n1": {"paramSchema": new_schema}},
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (await db_session.execute(
        select(Run).where(Run.id == resp.json()["id"])
    )).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert "buffer_lot" in n1["data"]["paramSchema"]["properties"]
    assert "buffer_lot" not in n1["data"]["protocol_paramSchema"]["properties"]


@pytest.mark.asyncio
async def test_create_run_description_override(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    new_desc = "Adjust to {{pH}} using 1M HCl, then incubate at {{temp_c}}°C"
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run desc",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {"n1": {"description": new_desc}},
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (await db_session.execute(
        select(Run).where(Run.id == resp.json()["id"])
    )).scalar_one()
    n1 = next(n for n in run.graph["nodes"] if n["id"] == "n1")
    assert n1["data"]["description"] == new_desc
    assert n1["data"]["protocol_description"] == "Mix until pH={{pH}}"
```

Run:

```bash
pytest tests/integration/test_run_overrides.py -v -k "equipment_swap or paramSchema_override or description_override"
```

Expected: 3 PASS.

- [ ] **Step 6: Test — non-current `protocol_version_number` snapshots that version**

Append:

```python
@pytest.mark.asyncio
async def test_create_run_from_specific_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """When protocol_version_number is set, the run snapshots that
    ProtocolVersion.graph, not protocol.graph."""
    protocol = await _seed_protocol(db_session, test_project)

    # Create an older published version with a different graph
    old_graph = {
        "nodes": [
            {
                "id": "old-n1",
                "type": "unitOp",
                "data": {
                    "label": "Legacy step",
                    "params": {"x": 1},
                    "paramSchema": {"properties": {"x": {"type": "integer"}}},
                },
            }
        ],
        "edges": [],
    }
    db_session.add(ProtocolVersion(
        protocol_id=protocol.id,
        version_number=1,
        name=protocol.name,
        graph=old_graph,
        is_draft=False,
    ))
    # Bump the protocol's current version to 2 so v1 is "old"
    protocol.version_number = 2
    await db_session.flush()

    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run from v1",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "protocol_version_number": 1,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    run = (await db_session.execute(
        select(Run).where(Run.id == resp.json()["id"])
    )).scalar_one()
    node_ids = {n["id"] for n in run.graph["nodes"]}
    assert node_ids == {"old-n1"}  # snapshotted v1, not the current protocol graph


@pytest.mark.asyncio
async def test_create_run_with_unknown_version_returns_404(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    resp = await client.post(
        "/science/runs",
        json={
            "name": "Run from missing version",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "protocol_version_number": 99,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404
```

Run:

```bash
pytest tests/integration/test_run_overrides.py -v -k "specific_version or unknown_version"
```

Expected: 2 PASS.

- [ ] **Step 7: Run the entire override test file**

```bash
pytest tests/integration/test_run_overrides.py -v
```

Expected: 7 passed (the six test functions above plus the audit-entry test from Step 4).

Also run the existing `test_science_api.py` to confirm we didn't break anything:

```bash
pytest tests/integration/test_science_api.py -q
```

Expected: 42 passed (same as Phase 1).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_overrides.py
git commit -m "feat(F-0081): create_run accepts overrides, deep-copies + snapshots graph, audits diffs"
```

---

## Task 5 — `update_run` PLANNED guard

Currently `update_run` accepts a graph payload regardless of status. Reject it with 422 when the run is not `PLANNED`.

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:150-410` (specifically near the start of the function body, after status validation but before the `setattr` loop)

- [ ] **Step 1: Test — graph edit on a PLANNED run is allowed**

Append to `backend/tests/integration/test_run_overrides.py`:

```python
@pytest.mark.asyncio
async def test_update_run_graph_allowed_while_planned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/science/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # PLANNED is the default — confirm the guard does NOT trigger.
    new_graph = copy.deepcopy(create_resp.json()["graph"])
    n1 = next(n for n in new_graph["nodes"] if n["id"] == "n1")
    n1["data"]["params"]["pH"] = 6.8

    resp = await client.put(
        f"/science/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["graph"]["nodes"][0]["data"]["params"]["pH"] == 6.8
```

Run:

```bash
pytest tests/integration/test_run_overrides.py::test_update_run_graph_allowed_while_planned -v
```

Expected: PASS today (no guard yet). This is a regression sentinel for the next step.

- [ ] **Step 2: Test — graph edit on an ACTIVE run is rejected**

Append:

```python
@pytest.mark.asyncio
async def test_update_run_graph_rejected_when_not_planned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user,  # to add ourselves as a role assignment so we can transition
    db_session: AsyncSession,
):
    """Once a run leaves PLANNED, graph edits return 422."""
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/science/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # Mark ACTIVE directly in the DB to skip the role-assignment guard, which
    # is unrelated to the override behavior under test.
    run = (await db_session.execute(select(Run).where(Run.id == run_id))).scalar_one()
    run.status = "ACTIVE"
    await db_session.flush()

    new_graph = copy.deepcopy(create_resp.json()["graph"])
    new_graph["nodes"][0]["data"]["params"]["pH"] = 6.8

    resp = await client.put(
        f"/science/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "PLANNED" in resp.json()["detail"]
```

Run:

```bash
pytest tests/integration/test_run_overrides.py::test_update_run_graph_rejected_when_not_planned -v
```

Expected: FAIL (currently the endpoint accepts the edit and returns 200).

- [ ] **Step 3: Add the guard**

Edit `backend/app/api/endpoints/runs.py`. Find the line `update_data: RunUpdate,` in `update_run` (near line 155). After the existing status-transition validation block (`runs.py:170-186`) and *before* the `if new_status == "ACTIVE":` block (line 188), add:

```python
    # Block graph edits when the run has left PLANNED — overrides are GMP-locked
    # at that point. (F-0081)
    if update_data.graph is not None and current_status != "PLANNED":
        raise HTTPException(
            status_code=422,
            detail="Cannot edit run graph: run must be in PLANNED status to apply overrides",
        )
```

Run:

```bash
pytest tests/integration/test_run_overrides.py -v -k "update_run_graph"
```

Expected: both tests PASS (the PLANNED-allowed test still passes; the ACTIVE-rejected test now passes).

- [ ] **Step 4: Run the full override file plus existing science tests as a regression check**

```bash
pytest tests/integration/test_run_overrides.py -v
pytest tests/integration/test_science_api.py -q
```

Expected: 10 passed in `test_run_overrides.py`; 42 passed in `test_science_api.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_overrides.py
git commit -m "feat(F-0081): reject graph edits on update_run when run is not PLANNED"
```

---

## Task 6 — `update_run` audit-diff for graph overrides

When the client PUTs a new graph (allowed because we're PLANNED), compare it against the run's current graph and emit one `OVERRIDE_EDIT` audit entry per changed unit-op field. This is the edit-time analog of Task 4's `OVERRIDE_SET`.

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:150-410` (near where `setattr(run_obj, key, value)` runs the setter — we need to compute the diff *before* mutation)

- [ ] **Step 1: Test — graph diff on PLANNED edit produces OVERRIDE_EDIT entries**

Append to `backend/tests/integration/test_run_overrides.py`:

```python
@pytest.mark.asyncio
async def test_update_run_emits_override_edit_audit(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Editing override values on a PLANNED run writes one OVERRIDE_EDIT
    entry per changed (node, field) tuple."""
    protocol = await _seed_protocol(db_session, test_project)
    create_resp = await client.post(
        "/science/runs",
        json={
            "name": "Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
            "overrides": {
                "nodes": {"n1": {"params": {"pH": 6.8}}}
            },
        },
        headers=auth_headers,
    )
    run_id = create_resp.json()["id"]

    # Flip pH to a third value and swap n2's equipment.
    new_graph = copy.deepcopy(create_resp.json()["graph"])
    n1 = next(n for n in new_graph["nodes"] if n["id"] == "n1")
    n2 = next(n for n in new_graph["nodes"] if n["id"] == "n2")
    n1["data"]["params"]["pH"] = 7.0
    n2["data"]["equipment"] = [{"id": "cf-B", "name": "Centrifuge B"}]

    resp = await client.put(
        f"/science/runs/{run_id}",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    audit_q = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "Run")
            & (AuditLog.entity_id == run_id)
            & (AuditLog.action == "OVERRIDE_EDIT")
        ).order_by(AuditLog.created_at)
    )
    entries = audit_q.scalars().all()
    fields = sorted((e.changes["step_id"], e.changes["field"]) for e in entries)
    assert fields == [("n1", "pH"), ("n2", "equipment")]

    # pH entry: old_value should be the previous override (6.8), not the
    # protocol default (7.4) — this is the edit-time semantic.
    ph_entry = next(e for e in entries if e.changes["field"] == "pH")
    assert ph_entry.changes["old_value"] == 6.8
    assert ph_entry.changes["new_value"] == 7.0
```

Run:

```bash
pytest tests/integration/test_run_overrides.py::test_update_run_emits_override_edit_audit -v
```

Expected: FAIL — the endpoint currently writes only the catch-all `UPDATE` audit at line 404, no per-field `OVERRIDE_EDIT` entries.

- [ ] **Step 2: Wire the diff in update_run**

Edit `backend/app/api/endpoints/runs.py`. Find the `update_run` function. Right after the new PLANNED guard from Task 5, and *before* the `changes = update_data.model_dump(exclude_unset=True)` line (around line 396), insert:

```python
    # Diff incoming graph against current Run.graph and emit OVERRIDE_EDIT
    # audit entries per changed unit-op field. (F-0081)
    if update_data.graph is not None:
        old_nodes = {n["id"]: n for n in iter_unit_op_nodes(run_obj.graph)}
        new_nodes = {n["id"]: n for n in iter_unit_op_nodes(update_data.graph)}
        for node_id in old_nodes.keys() & new_nodes.keys():
            for diff in diff_unit_op_node(old_nodes[node_id], new_nodes[node_id]):
                await log_audit(
                    db, user.id, "OVERRIDE_EDIT", "Run", run_obj.id, diff,
                )
```

(Note: `diff_unit_op_node` and `log_audit` are already imported via Task 4; `iter_unit_op_nodes` was imported in Task 3 for the existing callsites.)

Run:

```bash
pytest tests/integration/test_run_overrides.py::test_update_run_emits_override_edit_audit -v
```

Expected: PASS.

- [ ] **Step 3: Run the full override file**

```bash
pytest tests/integration/test_run_overrides.py -v
```

Expected: 11 passed.

- [ ] **Step 4: Run the broader regression suite to make sure nothing else breaks**

```bash
pytest tests/integration/test_science_api.py tests/integration/test_run_attachments.py tests/integration/test_run_notes.py -q
```

Expected: all green. Any failure here means the diff loop is misbehaving (most likely: it's running on graphs that include non-`unitOp` nodes that don't have a `data` key — but the loop already filters by `type == "unitOp"`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_overrides.py
git commit -m "feat(F-0081): update_run emits OVERRIDE_EDIT audit per changed unit-op field"
```

---

## Phase 2 done — completion checklist

- [ ] `NodeOverrides` and `RunOverrides` schemas defined; `RunCreate` accepts them
- [ ] `app/services/runs/graph.py` and `app/services/runs/overrides.py` exist and are imported from a single source by both new override code and existing `runs.py` execution_data audit code
- [ ] 7 unit tests in `test_run_graph_helpers.py` pass
- [ ] 12 unit tests in `test_run_overrides_helpers.py` pass
- [ ] 10 integration tests in `test_run_overrides.py` pass
- [ ] All existing tests still pass (`test_science_api.py`, `test_run_attachments.py`, `test_run_notes.py`) — Task 3 is a no-op behaviorally
- [ ] No inline duplicates of `for n in graph["nodes"] if n.get("type") == "unitOp"` or `prop.get("title") or key.replace("_", " ").title()` remain in `runs.py`
- [ ] Worktree branch has clean conventional-commit history matching this plan

When this phase is complete:
- The wizard front-end (Phase 3) can call `POST /science/runs` with the override payload and trust that mirrors + audits are recorded correctly.
- The run-detail editor (Phase 4) can call `PUT /science/runs/{id}` while PLANNED and trust that the diff is audited.

There is no qa-verify session for Phase 2 — Phase 2 has no UI surface (per the spec's verification table, Phase 3 is where the API gets exercised end-to-end through the wizard).

---

## Out of scope (do NOT do here)

- Server-side JSON-Schema validation of override values (frontend is responsible for now).
- A `RunBatch` model or `POST /science/runs/batch` endpoint (the singleton API is shaped to accept it later; the batch handler itself is a separate feature).
- Migrating existing audit-log consumers (`RunHistory.svelte`) to render `OVERRIDE_SET` / `OVERRIDE_EDIT` labels — that lives in Phase 3 with the rest of the frontend changes.
- Backfilling `protocol_*` mirror fields on runs that already exist in the DB — they keep their current shape; only new runs get mirrors. (No-overrides runs created post-Phase-2 *will* get mirrors; that's fine, and old runs without mirrors render correctly because the frontend treats missing mirrors as "same as effective".)
- Validating that `protocol_version_number` is one of the protocol's actual versions (we 404 when missing — server doesn't restrict to the protocol's published version list further).
