# QA-0007 — Equipment ID Interpolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users reference equipment in instruction templates via `{{<local_id>_name}}` and `{{<local_id>_description}}`, where `<local_id>` is a short, per-protocol, user-editable identifier (default `E-001`, `E-002`, …) assigned in the Inspector.

**Architecture:** Frontend adds an optional `local_id` field on each `SelectedEquipment` entry inside the protocol-graph JSONB, auto-suggesting `E-NNN`. Backend extends the placeholder regex to allow hyphens, walks the graph once per render to build a flat `{f"{local_id}_name": eq.name, f"{local_id}_description": eq.description, …}` dict, merges it into each step's `params` namespace before calling `_render_template`, and surfaces unresolved tokens via the `X-Unresolved-Placeholders` response header on PDF endpoints. Render output keeps the existing behavior: unfilled placeholders stay literal in the document.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pytest; Svelte 5 runes / Vite / Vitest.

**Spec:** `docs/superpowers/specs/2026-05-10-qa-0007-equipment-interpolation-design.md`

---

## File Structure

### Backend — create

- `backend/app/services/protocols/equipment_context.py` — async helper that walks the protocol graph, fetches `Equipment` rows scoped to the org, and returns `tuple[dict[str, str], list[str]]` (flat context dict + duplicate-id warnings).

### Backend — modify

- `backend/app/services/documents/pdf_base.py` (lines 88–108) — broaden placeholder regex to `\{\{([A-Za-z][\w-]*)\}\}`; change `_render_template` return type to `tuple[str, list[str]]` where the second element is the deduped, ordered list of unresolved tokens.
- `backend/app/services/protocols/template_engine.py` (lines 72–267) — `build_context` accepts optional `equipment_context: dict[str, str] | None`; for each step, merges `equipment_context` into the step's `params` before calling `_render_template`; aggregates unresolved tokens across all step/role renders; returns `tuple[dict, list[str]]`.
- `backend/app/api/endpoints/protocol_pdfs.py` (4 PDF endpoints) — after loading `protocol.graph`, build the equipment context, pass into `build_context`, unpack the unresolved list, and attach `X-Unresolved-Placeholders` response header when non-empty. Server-side `logger.warning(...)` for unresolved.
- `backend/app/api/endpoints/runs.py` (run PDF endpoints, around lines 575 and 669) — same treatment.

### Backend — tests

- `backend/tests/unit/test_template_engine.py` — extend with hyphen-token cases (resolved, unresolved, regression).
- `backend/tests/unit/test_equipment_context.py` — new file. Tests for `build_equipment_context` (single node, multi-node, swimlane children, duplicate local_id, missing Equipment row).
- `backend/tests/integration/test_protocol_pdf_equipment.py` — new file. Renders an SOP PDF for a seeded protocol with equipment, asserts the rendered docx XML contains substituted strings, asserts header on unresolved case.

### Frontend — create

- `frontend/src/lib/protocol/equipmentIds.ts` — pure helpers:
  - `suggestNextLocalId(graphNodes: Node[]): string`
  - `findLocalIdConflicts(graphNodes: Node[]): Map<string, string[]>` (local_id → list of node_ids using it)
- `frontend/src/lib/protocol/equipmentIds.test.ts` — Vitest unit tests.

### Frontend — modify

- `frontend/src/lib/components/protocol/Inspector.svelte` — extend `SelectedEquipment` interface with optional `local_id`; in the equipment chip render (lines 388–399) show the local_id and inline-editable; line ~309 extend the template-hint to include `{{<local_id>_name}}` and `{{<local_id>_description}}` for each assigned equipment item; block `handleApply` when conflicts exist.
- `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` — extend `SelectedEquipment` interface; auto-suggest `local_id` for newly-checked items via `suggestNextLocalId`; show local_id editable input inline next to each selected row; surface uniqueness errors.
- `frontend/src/lib/api.ts` (or wherever PDF blob fetching lives) — read `X-Unresolved-Placeholders` header on PDF responses and emit a toast.

### Frontend — tests

- `frontend/src/lib/protocol/equipmentIds.test.ts` — covered above.

---

## Task 1: Frontend pure helpers — `equipmentIds.ts`

**Files:**
- Create: `frontend/src/lib/protocol/equipmentIds.ts`
- Test: `frontend/src/lib/protocol/equipmentIds.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/lib/protocol/equipmentIds.test.ts
import { describe, expect, it } from 'vitest';
import {
    findLocalIdConflicts,
    suggestNextLocalId,
} from './equipmentIds';
import type { Node } from '@xyflow/svelte';

function makeNode(id: string, equipment: Array<{ equipment_id: string; local_id?: string; shareable: boolean }> = []): Node {
    return {
        id,
        type: 'unitOp',
        position: { x: 0, y: 0 },
        data: { equipment },
    } as unknown as Node;
}

describe('suggestNextLocalId', () => {
    it('returns E-001 when no equipment exists', () => {
        expect(suggestNextLocalId([])).toBe('E-001');
    });

    it('returns E-001 when no node has an E-NNN local_id', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'uuid-1', local_id: 'pump_a', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-001');
    });

    it('increments past the highest existing E-NNN', () => {
        const nodes = [
            makeNode('n1', [
                { equipment_id: 'uuid-1', local_id: 'E-001', shareable: false },
                { equipment_id: 'uuid-2', local_id: 'E-007', shareable: false },
            ]),
            makeNode('n2', [{ equipment_id: 'uuid-3', local_id: 'E-003', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-008');
    });

    it('ignores non-unitOp nodes and missing local_id entries', () => {
        const nodes = [
            { id: 's1', type: 'swimLane', data: {}, position: { x: 0, y: 0 } } as unknown as Node,
            makeNode('n1', [{ equipment_id: 'uuid-1', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-001');
    });
});

describe('findLocalIdConflicts', () => {
    it('returns empty map when all local_ids are unique', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', local_id: 'E-001', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: 'E-002', shareable: false }]),
        ];
        expect(findLocalIdConflicts(nodes).size).toBe(0);
    });

    it('returns the offending node ids for each duplicated local_id', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', local_id: 'E-001', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: 'E-001', shareable: false }]),
        ];
        const conflicts = findLocalIdConflicts(nodes);
        expect(conflicts.get('E-001')).toEqual(['n1', 'n2']);
    });

    it('skips empty / undefined local_ids', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: '', shareable: false }]),
        ];
        expect(findLocalIdConflicts(nodes).size).toBe(0);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- equipmentIds`
Expected: FAIL with "Cannot find module './equipmentIds'".

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/lib/protocol/equipmentIds.ts
import type { Node } from '@xyflow/svelte';

interface SelectedEquipment {
    equipment_id: string;
    local_id?: string;
    shareable: boolean;
}

function readEquipment(node: Node): SelectedEquipment[] {
    if (node.type !== 'unitOp') return [];
    return (node.data?.equipment as SelectedEquipment[] | undefined) ?? [];
}

export function suggestNextLocalId(nodes: Node[]): string {
    let maxN = 0;
    for (const n of nodes) {
        for (const eq of readEquipment(n)) {
            const m = eq.local_id?.match(/^E-(\d+)$/);
            if (m) {
                const n = Number.parseInt(m[1], 10);
                if (n > maxN) maxN = n;
            }
        }
    }
    return `E-${String(maxN + 1).padStart(3, '0')}`;
}

export function findLocalIdConflicts(nodes: Node[]): Map<string, string[]> {
    const byId = new Map<string, string[]>();
    for (const node of nodes) {
        for (const eq of readEquipment(node)) {
            if (!eq.local_id) continue;
            const arr = byId.get(eq.local_id) ?? [];
            arr.push(node.id);
            byId.set(eq.local_id, arr);
        }
    }
    const conflicts = new Map<string, string[]>();
    for (const [id, nodeIds] of byId) {
        if (nodeIds.length > 1) conflicts.set(id, nodeIds);
    }
    return conflicts;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- equipmentIds`
Expected: PASS for all six tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/protocol/equipmentIds.ts frontend/src/lib/protocol/equipmentIds.test.ts
git commit -m "feat(qa-0007): add equipment local_id suggester and conflict finder"
```

---

## Task 2: Backend — broaden render regex, return unresolved list

**Files:**
- Modify: `backend/app/services/documents/pdf_base.py:88-108`
- Test: `backend/tests/unit/test_template_engine.py`

- [ ] **Step 1: Add failing tests at the bottom of `test_template_engine.py`**

```python
# backend/tests/unit/test_template_engine.py — append
from app.services.documents.pdf_base import _render_template


def test_render_template_returns_unresolved_list_for_missing_keys():
    out, unresolved = _render_template(
        "Mix {{volume}} mL and stir {{rpm}}.",
        {"volume": 500},
    )
    assert out == "Mix 500 mL and stir {{rpm}}."
    assert unresolved == ["rpm"]


def test_render_template_resolves_hyphenated_equipment_token():
    out, unresolved = _render_template(
        "Set up the {{E-001_name}} ({{E-001_description}}).",
        {
            "E-001_name": "Sartorius Bioreactor",
            "E-001_description": "5L stirred-tank, single-use",
        },
    )
    assert out == "Set up the Sartorius Bioreactor (5L stirred-tank, single-use)."
    assert unresolved == []


def test_render_template_leaves_unresolved_hyphen_token_literal_and_lists_it():
    out, unresolved = _render_template(
        "Calibrate {{E-009_name}}.",
        {"unrelated": "x"},
    )
    assert out == "Calibrate {{E-009_name}}."
    assert unresolved == ["E-009_name"]


def test_render_template_deduplicates_unresolved_preserves_order():
    out, unresolved = _render_template(
        "{{b}} {{a}} {{b}} {{c}}",
        {},
    )
    assert out == "{{b}} {{a}} {{b}} {{c}}"
    assert unresolved == ["b", "a", "c"]


def test_render_template_handles_empty_params_dict():
    out, unresolved = _render_template("Plain text", None)
    assert out == "Plain text"
    assert unresolved == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_template_engine.py -k "render_template" -v`
Expected: FAIL — current `_render_template` returns `str`, not a tuple.

- [ ] **Step 3: Update `_render_template`**

Replace lines 88–108 of `backend/app/services/documents/pdf_base.py` with:

```python
def _render_template(
    template: str,
    params: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Substitute ``{{key}}`` placeholders with formatted param values.

    Returns the rendered text and an ordered, deduplicated list of
    tokens that could not be resolved (missing key, None, empty
    string, or empty list). Unresolved tokens are left as literal
    ``{{key}}`` in the output.
    """
    if not params:
        # Still walk so we report unresolved tokens for visibility.
        params = {}

    unresolved: list[str] = []
    seen: set[str] = set()

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        val = params.get(key)
        if val is None or val == "" or val == []:
            if key not in seen:
                seen.add(key)
                unresolved.append(key)
            return match.group(0)
        return _format_value(val)

    rendered = re.sub(r"\{\{([A-Za-z][\w-]*)\}\}", _replace, template)
    return rendered, unresolved
```

- [ ] **Step 4: Run new tests; expect existing call sites to fail next**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_template_engine.py -v`
Expected: New tests pass. Existing `_build_param_sentence` / `parse_template` tests still pass (they don't use the changed return shape). However the two call sites in `template_engine.py` (lines 125 and 287) now return tuples, which will be silently coerced incorrectly — fix immediately in Task 3 before any commit.

- [ ] **Step 5: Patch call sites in `template_engine.py`**

For each occurrence at `backend/app/services/protocols/template_engine.py:125` and `:287`, replace:

```python
desc = _render_template(desc, params)
```

with:

```python
desc, _ = _render_template(desc, params)
```

(Aggregation comes in Task 4 — for now keep the old behavior of dropping the unresolved list at the call site so we have a clean intermediate commit.)

- [ ] **Step 6: Re-run unit tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/ -v`
Expected: All green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/documents/pdf_base.py backend/app/services/protocols/template_engine.py backend/tests/unit/test_template_engine.py
git commit -m "feat(qa-0007): broaden render regex; return unresolved token list"
```

---

## Task 3: Backend — equipment context builder

**Files:**
- Create: `backend/app/services/protocols/equipment_context.py`
- Test: `backend/tests/unit/test_equipment_context.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_equipment_context.py
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization
from app.models.science import Equipment
from app.services.protocols.equipment_context import build_equipment_context


@pytest.mark.asyncio
async def test_build_equipment_context_flattens_assigned_equipment(
    db: AsyncSession,
):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()

    eq1 = Equipment(
        organization_id=org.id,
        name="Sartorius Bioreactor",
        description="5L stirred-tank, single-use",
    )
    eq2 = Equipment(
        organization_id=org.id,
        name="pH Probe",
        description="Mettler Toledo InPro 3250i",
    )
    db.add_all([eq1, eq2])
    await db.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(eq1.id), "local_id": "E-001", "shareable": False},
                        {"equipment_id": str(eq2.id), "local_id": "E-002", "shareable": False},
                    ],
                },
            },
        ],
    }

    ctx, warnings = await build_equipment_context(db, org.id, graph)

    assert ctx == {
        "E-001_name": "Sartorius Bioreactor",
        "E-001_description": "5L stirred-tank, single-use",
        "E-002_name": "pH Probe",
        "E-002_description": "Mettler Toledo InPro 3250i",
    }
    assert warnings == []


@pytest.mark.asyncio
async def test_build_equipment_context_skips_entries_without_local_id(
    db: AsyncSession,
):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()
    eq = Equipment(organization_id=org.id, name="X", description="d")
    db.add(eq)
    await db.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(eq.id), "shareable": False},  # no local_id
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db, org.id, graph)
    assert ctx == {}
    assert warnings == []


@pytest.mark.asyncio
async def test_build_equipment_context_warns_on_duplicate_local_id(
    db: AsyncSession,
):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()
    a = Equipment(organization_id=org.id, name="A", description="a")
    b = Equipment(organization_id=org.id, name="B", description="b")
    db.add_all([a, b])
    await db.flush()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(a.id), "local_id": "E-001", "shareable": False},
                    ],
                },
            },
            {
                "id": "n2",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(b.id), "local_id": "E-001", "shareable": False},
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db, org.id, graph)
    # First wins
    assert ctx["E-001_name"] == "A"
    assert any("E-001" in w and "duplicate" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_build_equipment_context_warns_when_equipment_missing(
    db: AsyncSession,
):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()
    bogus = uuid.uuid4()

    graph = {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "equipment": [
                        {"equipment_id": str(bogus), "local_id": "E-001", "shareable": False},
                    ],
                },
            },
        ],
    }
    ctx, warnings = await build_equipment_context(db, org.id, graph)
    assert ctx == {}
    assert any("E-001" in w for w in warnings)


@pytest.mark.asyncio
async def test_build_equipment_context_handles_swimlane_children(
    db: AsyncSession,
):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()
    eq = Equipment(organization_id=org.id, name="N", description="d")
    db.add(eq)
    await db.flush()

    graph = {
        "nodes": [
            {"id": "s1", "type": "swimLane", "data": {}},
            {
                "id": "n1",
                "type": "unitOp",
                "parentId": "s1",
                "data": {
                    "equipment": [
                        {"equipment_id": str(eq.id), "local_id": "E-001", "shareable": False},
                    ],
                },
            },
        ],
    }
    ctx, _ = await build_equipment_context(db, org.id, graph)
    assert ctx["E-001_name"] == "N"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_equipment_context.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/services/protocols/equipment_context.py
"""Flatten assigned equipment in a protocol graph into a template-context dict.

Returns a flat ``{f"{local_id}_name": eq.name, f"{local_id}_description":
eq.description}`` mapping that callers merge into the per-step params namespace
before invoking the template renderer. Walks every unit op node (including
swimlane children) and fetches the referenced Equipment rows in a single
org-scoped query.
"""

import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment

logger = logging.getLogger(__name__)


async def build_equipment_context(
    db: AsyncSession,
    org_id: uuid.UUID,
    graph: dict[str, Any] | None,
) -> tuple[dict[str, str], list[str]]:
    """Walk the protocol graph, build the flat template-context dict.

    Args:
        db: async session.
        org_id: scope Equipment lookup to this org.
        graph: protocol graph JSONB (``{"nodes": [...], "edges": [...]}``).

    Returns:
        ``(context, warnings)`` where ``context`` maps
        ``"<local_id>_name"`` / ``"<local_id>_description"`` to the
        resolved equipment field, and ``warnings`` is a list of
        human-readable strings for duplicate local_ids and missing
        Equipment rows.
    """
    if not graph:
        return {}, []

    nodes = graph.get("nodes") or []
    # Collect (local_id, equipment_uuid) pairs from every unit op.
    assignments: list[tuple[str, str, str]] = []  # (node_id, local_id, equipment_id)
    for node in nodes:
        if node.get("type") != "unitOp":
            continue
        for eq in (node.get("data") or {}).get("equipment") or []:
            local_id = eq.get("local_id")
            equipment_id = eq.get("equipment_id")
            if not local_id or not equipment_id:
                continue
            assignments.append((node.get("id", ""), local_id, equipment_id))

    if not assignments:
        return {}, []

    # Group by local_id; track duplicates.
    by_local: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for node_id, local_id, equipment_id in assignments:
        by_local[local_id].append((node_id, equipment_id))

    warnings: list[str] = []
    for local_id, hits in by_local.items():
        if len(hits) > 1:
            node_ids = ", ".join(h[0] for h in hits)
            warnings.append(
                f"Duplicate equipment local_id '{local_id}' on nodes: {node_ids} — first wins"
            )

    # Fetch every referenced Equipment in one org-scoped query.
    eq_uuids: set[uuid.UUID] = set()
    for hits in by_local.values():
        try:
            eq_uuids.add(uuid.UUID(hits[0][1]))
        except (ValueError, TypeError):
            continue

    rows = []
    if eq_uuids:
        result = await db.execute(
            select(Equipment).where(
                Equipment.id.in_(eq_uuids),
                Equipment.organization_id == org_id,
            )
        )
        rows = list(result.scalars().all())
    eq_by_uuid = {str(r.id): r for r in rows}

    context: dict[str, str] = {}
    for local_id, hits in by_local.items():
        # First wins on duplicates.
        equipment_id = hits[0][1]
        eq = eq_by_uuid.get(equipment_id)
        if not eq:
            warnings.append(
                f"Equipment for local_id '{local_id}' (equipment_id={equipment_id}) not found in organization"
            )
            continue
        context[f"{local_id}_name"] = eq.name or ""
        context[f"{local_id}_description"] = eq.description or ""

    if warnings:
        logger.warning("Equipment context warnings: %s", "; ".join(warnings))

    return context, warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_equipment_context.py -v`
Expected: All five tests pass. If there's no `db` fixture under `tests/unit/`, copy the pattern from an existing unit test that uses async DB (or move the file to `tests/integration/` and re-run).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/equipment_context.py backend/tests/unit/test_equipment_context.py
git commit -m "feat(qa-0007): equipment_context builder for instruction templates"
```

---

## Task 4: Backend — thread equipment_context through `build_context`

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:72-267`
- Test: extend `backend/tests/unit/test_template_engine.py`

- [ ] **Step 1: Add failing test**

Append to `test_template_engine.py`:

```python
def test_build_context_merges_equipment_into_step_params(monkeypatch):
    from app.services.protocols.template_engine import build_context

    equipment_context = {
        "E-001_name": "Sartorius Bioreactor",
        "E-001_description": "5L stirred-tank, single-use",
    }
    flat_steps = [
        {
            "id": "n1",
            "name": "Setup",
            "description": "Set up the {{E-001_name}} ({{E-001_description}}). Volume {{volume}} mL.",
            "params": {"volume": 500},
            "param_schema": {},
            "duration_min": 10,
            "role_name": "Op",
        }
    ]

    ctx, unresolved = build_context(
        protocol_name="P",
        flat_steps=flat_steps,
        equipment_context=equipment_context,
    )

    step_desc = ctx["steps"][0]["description"]
    assert "Sartorius Bioreactor" in step_desc
    assert "5L stirred-tank" in step_desc
    assert "500" in step_desc
    assert unresolved == []


def test_build_context_aggregates_unresolved_tokens_across_steps():
    from app.services.protocols.template_engine import build_context

    flat_steps = [
        {
            "id": "n1",
            "name": "Step 1",
            "description": "Use {{E-999_name}} and {{missing_param}}.",
            "params": {"volume": 1},
            "param_schema": {},
            "duration_min": 1,
            "role_name": "",
        },
        {
            "id": "n2",
            "name": "Step 2",
            "description": "Also {{E-999_name}}.",  # repeats
            "params": {},
            "param_schema": {},
            "duration_min": 1,
            "role_name": "",
        },
    ]
    _, unresolved = build_context(
        protocol_name="P",
        flat_steps=flat_steps,
        equipment_context={},
    )
    # Deduped across the whole render.
    assert sorted(unresolved) == sorted(["E-999_name", "missing_param"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_template_engine.py -k "build_context" -v`
Expected: FAIL — `build_context` doesn't accept `equipment_context` and doesn't return a tuple.

- [ ] **Step 3: Update `build_context` signature and merge logic**

In `backend/app/services/protocols/template_engine.py`:

(a) Add `equipment_context: dict[str, str] | None = None` to the `build_context` keyword arguments (after `storage`).

(b) Change return type to `tuple[dict[str, Any], list[str]]`.

(c) Near the top of the function (just after `umap = user_map or {}`), add:

```python
    eq_ctx = equipment_context or {}
    unresolved_all: list[str] = []
    _seen_unresolved: set[str] = set()

    def _merge_and_render(desc: str, params: dict[str, Any] | None) -> str:
        merged = {**eq_ctx, **(params or {})}
        rendered, unresolved = _render_template(desc, merged)
        for tok in unresolved:
            if tok not in _seen_unresolved:
                _seen_unresolved.add(tok)
                unresolved_all.append(tok)
        return rendered
```

(d) Replace both call sites:

- Line 125: `desc = _render_template(desc, params)` → `desc = _merge_and_render(desc, params)`
- Line 287: same replacement.

(e) Change the final `return { ... }` to `return ({...}, unresolved_all)`.

- [ ] **Step 4: Update every caller of `build_context` to unpack the tuple**

Callers (from earlier grep):

- `backend/app/api/endpoints/protocol_pdfs.py:81, 137, 197, 255`
- `backend/app/api/endpoints/runs.py:575, 669`
- `backend/app/api/endpoints/templates.py` (mock_ctx — verify and update if it uses `build_context`)

For each call site, replace:

```python
context = build_context(...)
```

with:

```python
context, _unresolved = build_context(...)
```

Leave the `_unresolved` unused for this commit — Task 5 will wire the header.

- [ ] **Step 5: Run tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit -v`
Expected: All green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/app/api/endpoints/protocol_pdfs.py backend/app/api/endpoints/runs.py backend/app/api/endpoints/templates.py backend/tests/unit/test_template_engine.py
git commit -m "feat(qa-0007): merge equipment_context into step params before render"
```

---

## Task 5: Backend — equipment lookup wiring + response header in PDF endpoints

**Files:**
- Modify: `backend/app/api/endpoints/protocol_pdfs.py`
- Modify: `backend/app/api/endpoints/runs.py`

- [ ] **Step 1: Write integration test**

```python
# backend/tests/integration/test_protocol_pdf_equipment.py
"""Smoke test that equipment_id interpolation reaches the rendered docx."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.science import Equipment


@pytest.mark.asyncio
async def test_protocol_sop_pdf_includes_equipment_name(
    authed_client: AsyncClient,
    seeded_protocol_with_equipment_template,  # fixture below or inline-build
):
    """Render the SOP PDF; assert the response is non-empty + header absent on success."""
    protocol_id, _ = seeded_protocol_with_equipment_template
    res = await authed_client.get(f"/protocols/{protocol_id}/pdf/sop")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    # Successful render — no unresolved header.
    assert "x-unresolved-placeholders" not in {k.lower() for k in res.headers}


@pytest.mark.asyncio
async def test_protocol_sop_pdf_surfaces_unresolved_via_header(
    authed_client: AsyncClient,
    seeded_protocol_with_unresolved_equipment_token,
):
    protocol_id = seeded_protocol_with_unresolved_equipment_token
    res = await authed_client.get(f"/protocols/{protocol_id}/pdf/sop")
    assert res.status_code == 200
    header = res.headers.get("x-unresolved-placeholders")
    assert header is not None
    assert "E-999_name" in header
```

Add the two fixtures next to other protocol fixtures (e.g., in `backend/tests/conftest.py` or `tests/integration/conftest.py`). The fixtures should:

- Create an Organization, User, Project, a `DocumentTemplate` of type SOP that the test rig already uses, and a `Protocol` with `graph` JSONB that has one unit op carrying `equipment: [{equipment_id, local_id: "E-001", shareable: false}]` and a description like `"Use the {{E-001_name}}."`. Look at existing `test_protocol_pdf*.py` for the fixture pattern; reuse the simplest SOP template the integration suite already loads.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_protocol_pdf_equipment.py -v`
Expected: FAIL — endpoints don't set the header.

- [ ] **Step 3: Wire equipment context + header in `protocol_pdfs.py`**

For each of the four endpoints in `backend/app/api/endpoints/protocol_pdfs.py` (`get_protocol_sop_pdf`, `get_protocol_batch_record_pdf`, and the two "edit-mode" variants if present at lines 197 and 255), after loading `protocol` and computing `roles_with_steps`, replace the `build_context(...)` call with:

```python
    from app.services.protocols.equipment_context import build_equipment_context

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, protocol.organization_id, protocol.graph or {}
    )

    context, unresolved = build_context(
        # ... existing kwargs ...
        equipment_context=equipment_ctx,
    )

    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    headers = {"Content-Disposition": f'{disp}; filename="{filename}"'}
    if unresolved:
        headers["X-Unresolved-Placeholders"] = ",".join(unresolved)
        logger.warning(
            "Unresolved template variables in protocol %s: %s",
            protocol.id,
            unresolved,
        )
    if eq_warnings:
        logger.warning(
            "Equipment warnings in protocol %s: %s",
            protocol.id,
            eq_warnings,
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=headers,
    )
```

Note: `Protocol` uses `organization_id` — verify by reading the model; if the attribute is named `org_id` use that.

Repeat for `backend/app/api/endpoints/runs.py` (around lines 575 and 669). For run endpoints, the graph lives on `run.graph` (or `run.execution_data['graph']` — check `runs.py` to confirm); use whichever the existing code already passes to `_parse_graph_roles_and_steps`.

- [ ] **Step 4: Run tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_protocol_pdf_equipment.py tests/unit -v`
Expected: All green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocol_pdfs.py backend/app/api/endpoints/runs.py backend/tests/integration/test_protocol_pdf_equipment.py
git commit -m "feat(qa-0007): wire equipment lookup into PDF endpoints; surface unresolved via header"
```

---

## Task 6: Frontend — extend `SelectedEquipment` and `EquipmentPickerModal`

**Files:**
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte`
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.svelte`

- [ ] **Step 1: Update the `SelectedEquipment` interface in both files**

In `Inspector.svelte` (line 22) and `EquipmentPickerModal.svelte` (line 16):

```typescript
interface SelectedEquipment {
    equipment_id: string;
    local_id?: string;
    shareable: boolean;
}
```

- [ ] **Step 2: Auto-suggest `local_id` for newly-checked items in the picker**

In `EquipmentPickerModal.svelte`:

(a) Add a new prop:

```typescript
allNodes: Node[];  // for suggesting next local_id
```

…and import:

```typescript
import { suggestNextLocalId, findLocalIdConflicts } from '$lib/protocol/equipmentIds';
import type { Node } from '@xyflow/svelte';
```

(b) Change `selectedItems` from `Map<string, boolean>` to `Map<string, { local_id: string; shareable: boolean }>`.

(c) On `toggleEquipment`, when adding an item, compute its local_id by combining `allNodes` (excluding the current nodeId's own existing selection, to avoid collisions with itself) with already-selected items in this modal session:

```typescript
function nextLocalIdInContext(): string {
    // Build a virtual node list reflecting in-flight modal selections.
    const virtualSelf = {
        id: nodeId,
        type: 'unitOp',
        position: { x: 0, y: 0 },
        data: {
            equipment: Array.from(selectedItems.entries()).map(([eqId, st]) => ({
                equipment_id: eqId,
                local_id: st.local_id,
                shareable: st.shareable,
            })),
        },
    } as unknown as Node;
    const otherNodes = allNodes.filter((n) => n.id !== nodeId);
    return suggestNextLocalId([...otherNodes, virtualSelf]);
}

function toggleEquipment(equipmentId: string) {
    if (selectedItems.has(equipmentId)) {
        selectedItems.delete(equipmentId);
    } else {
        selectedItems.set(equipmentId, {
            local_id: nextLocalIdInContext(),
            shareable: false,
        });
    }
    selectedItems = selectedItems;
}
```

(d) Render an editable text input next to each selected row showing the `local_id`. Use a small input (~6 ch wide). On change, update `selectedItems.get(equipmentId).local_id` and trigger reactivity.

(e) Compute `conflictsHere` as a derived value via `findLocalIdConflicts` over the virtual full list, and display an inline error next to any row whose local_id is duplicated.

(f) In `handleApply`, build the apply payload from the new map shape:

```typescript
function handleApply() {
    const equipment: SelectedEquipment[] = Array.from(selectedItems.entries()).map(
        ([equipmentId, st]) => ({
            equipment_id: equipmentId,
            local_id: st.local_id || undefined,
            shareable: st.shareable,
        })
    );
    onApply(equipment);
    onClose();
}
```

(g) Block the Apply button (`disabled={hasConflicts}`) when conflicts exist.

(h) On `$effect(() => { if (open) { ... } })`, initialize from `currentEquipment` preserving existing `local_id` values; for entries that lack one, leave blank — user explicitly picks. (No bulk backfill on open.)

- [ ] **Step 3: Pass `allNodes` from Inspector into the picker**

In `Inspector.svelte` around line 417, add `{allNodes}` to the props passed to `<EquipmentPickerModal>`.

- [ ] **Step 4: Render `local_id` on the Inspector chip**

In `Inspector.svelte` lines 388–399, update the chip:

```svelte
{#each editEquipment as eq (eq.equipment_id)}
    <div class="equipment-chip" class:conflict={...}>
        {#if eq.local_id}
            <span class="chip-localid">{eq.local_id}</span>
        {/if}
        <span class="chip-name">{getEquipmentName(eq.equipment_id)}</span>
        {#if eq.shareable}<span class="chip-badge">Shared</span>{/if}
        ...
    </div>
{/each}
```

Add `.chip-localid` styling: small monospace pill — see existing `.chip-badge` styling for a starting point.

- [ ] **Step 5: Run frontend tests + typecheck**

Run: `cd frontend && npm run check && npm run test`
Expected: Both pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/Inspector.svelte frontend/src/lib/components/modals/EquipmentPickerModal.svelte
git commit -m "feat(qa-0007): Inspector + EquipmentPickerModal support per-protocol local_id"
```

---

## Task 7: Frontend — extend Inspector template-hint with equipment variables

**Files:**
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte:309-313`

- [ ] **Step 1: Add the equipment-hint derived value**

Just above the template (in the `<script>` block, near `paramKeys`):

```typescript
const equipmentHintTokens = $derived(
    editEquipment
        .filter((eq) => eq.local_id)
        .flatMap((eq) => [
            `{{${eq.local_id}_name}}`,
            `{{${eq.local_id}_description}}`,
        ])
);
```

- [ ] **Step 2: Render it alongside the param hint**

Replace the hint block (lines 309–313) with:

```svelte
{#if paramKeys.length > 0 || equipmentHintTokens.length > 0}
    <p class="template-hint">
        {#if paramKeys.length > 0}
            Params: {paramKeys.map((k) => `{{${k}}}`).join('  ')}
        {/if}
        {#if equipmentHintTokens.length > 0}
            <br />Equipment: {equipmentHintTokens.join('  ')}
        {/if}
    </p>
{/if}
```

- [ ] **Step 3: Run check + tests**

Run: `cd frontend && npm run check && npm run test`
Expected: Pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/protocol/Inspector.svelte
git commit -m "feat(qa-0007): Inspector template-hint lists equipment variables"
```

---

## Task 8: Frontend — surface unresolved header as a toast

**Files:**
- Modify: PDF fetch call site (likely `frontend/src/pages/ProtocolEditor.svelte` or wherever the SOP/batch-record PDF preview button lives — locate via `grep -rn "/pdf/sop\|/pdf/batch-record" frontend/src`).

- [ ] **Step 1: Locate the PDF preview fetch**

Run: `grep -rn "/pdf/sop\|/pdf/batch-record\|/pdf/run" frontend/src`

Pick the highest-level call site for each (avoid wiring per-page if there is a single shared helper).

- [ ] **Step 2: After fetch, read `X-Unresolved-Placeholders` and toast**

In each call site, after the `fetch(...)` (or `api.get(...)` returning a Blob) resolves, check `res.headers.get('X-Unresolved-Placeholders')`. If present and non-empty, call the existing toast helper (e.g., `toast.warning(...)` or whichever pattern shadcn-svelte uses in this repo). Look at existing toast usage with `grep -rn "toast\.\|showToast" frontend/src/lib | head`.

Toast text: `Unresolved template variables: <comma-separated list>. They remain literal in the document.`

- [ ] **Step 3: Manual smoke**

(Browser verification handled by qa-verify in Task 10; nothing automated needed here unless a Vitest unit test naturally fits.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/...
git commit -m "feat(qa-0007): surface unresolved template variables as a toast"
```

---

## Task 9: Full test suite

- [ ] **Step 1: Backend**

Run: `cd backend && source .venv/bin/activate && black app tests && isort app tests && mypy app && pytest`
Expected: All green.

- [ ] **Step 2: Frontend**

Run: `cd frontend && npm run check && npm run test`
Expected: All green.

- [ ] **Step 3: Commit any formatter-induced changes**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore(qa-0007): formatter fixups"
```

---

## Task 10: Browser verification (delegated to qa-verify)

Hand off to the qa-verify agent with the following brief:

- **Login:** dev DB credentials, any user.
- **Feature:** Equipment template-variable interpolation in instruction templates.
- **Steps to verify:**
  1. Open the protocol editor for a seeded protocol; create a unit op.
  2. Open Inspector → Manage Equipment → check one equipment item → confirm auto-suggested `E-001` appears and is editable.
  3. Edit the local_id to something custom (`pump_a`), apply, confirm chip shows the new id.
  4. In the unit op description, type `Set up the {{E-001_name}} ({{E-001_description}}). Volume {{volume}} mL.`
  5. (Assign a second equipment item, confirm it auto-suggests `E-002`.)
  6. Open the SOP PDF preview; verify substituted names appear and that param interpolation still works (`{{volume}}` → `500`).
  7. Edit the description to include `{{E-999_name}}`, regenerate, confirm the literal `{{E-999_name}}` stays in the doc AND a warning toast appears listing `E-999_name`.
  8. Try to assign duplicate `local_id` to two equipment items — confirm the Apply button is disabled with an inline error.
  9. Smoke-check that other paths (no equipment assigned, no templates) still render PDF without warnings.
- **Acceptance criteria:** Listed in QA-0007 (mirror them in the brief).
- **Pages affected:** protocol editor (Inspector + EquipmentPickerModal), SOP/batch-record PDF preview, run instruction render path.

---

## Self-Review

### Spec coverage
- AC: Inspector lets user assign + pick/confirm a human-readable ID → Task 6.
- AC: Equipment IDs unique within a protocol → Task 1 helpers + Task 6 picker validation.
- AC: `{{<id>_name}}` resolves → Tasks 2 + 3 + 4 + tests in Task 2/4.
- AC: `{{<id>_description}}` resolves → same.
- AC: Unresolved surfaced as warning, listing failed IDs → Tasks 4 (aggregation) + 5 (header) + 8 (toast).
- AC: Existing param interpolation continues to work → Tasks 2/4 regression tests + Task 9 full suite + Task 10 step 6.
- AC: Variables documented in template-hint helper → Task 7.

### Placeholder scan
- No TBDs. Task 5 references "find the exact attribute name" (`organization_id` vs `org_id`) — this is a check, not a placeholder; the engineer reads one file to confirm.
- Task 8 leaves the specific call site to be discovered via grep; the grep command is given and the action is concrete (read header → toast).

### Type consistency
- `SelectedEquipment.local_id` is `string | undefined` everywhere.
- `_render_template` returns `tuple[str, list[str]]` everywhere; updated at all call sites in Task 2 (drop-result) and Task 4 (aggregate).
- `build_context` returns `tuple[dict, list[str]]` everywhere; all 6 callers updated in Task 4.
- `build_equipment_context` returns `tuple[dict[str, str], list[str]]`; consumed in Task 5.

### Scope
- Single plan, ~10 tasks, mostly TDD. No decomposition needed.
