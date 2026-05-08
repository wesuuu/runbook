# QA-0006 Branch Role Validation Hard-Block Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-block protocol publish, run creation, and PDF generation when a unit op has multiple outgoing branches that share or lack distinct role assignments. Bundle the prerequisite parentId-reassignment fix.

**Architecture:** Single rule definition implemented twice — pure function in `services/protocols/validation.py` for backend defense, mirrored TypeScript function in `protocolValidation.ts` for fast UX. Backend wires into 5 endpoints (publish-draft, /runs, four PDF routes); frontend adds pre-flights to `saveAndPublish` and `openPdfPreview`, plus an `onnodedragstop` handler that reparents nodes when dragged between swimlanes. Existing amber `.invalid` ring and `ValidationBanners` are reused.

**Tech Stack:** Python (FastAPI, pytest), TypeScript (Svelte 5 runes, @xyflow/svelte, vitest).

**Spec:** [`docs/superpowers/specs/2026-05-08-qa-0006-branch-role-validation-design.md`](../specs/2026-05-08-qa-0006-branch-role-validation-design.md)

---

## File Map

| File | Role |
|---|---|
| `tests/fixtures/branch_role_validation.json` | **Shared behavior contract.** 8 canonical cases consumed by both backend and frontend tests. New file at repo root. |
| `backend/app/services/protocols/validation.py` | Add `_branch_role_issues()` rule + `assert_no_branch_errors()` helper |
| `backend/tests/unit/test_protocols_validation.py` | New test cases for the rule |
| `backend/app/api/endpoints/protocol_versions.py` | Gate `POST /protocols/{id}/publish-draft` |
| `backend/app/api/endpoints/runs.py` | Gate `POST /runs` |
| `backend/app/api/endpoints/protocol_pdfs.py` | Gate 4 PDF endpoints |
| `backend/tests/integration/test_qa0006_branch_role_enforcement.py` | New endpoint tests (consolidated) |
| `frontend/src/lib/components/protocol/protocolValidation.ts` | Extend `computeBranchValidationErrors` with null-parentId case + time-mode suppression |
| `frontend/src/lib/components/protocol/protocolValidation.test.ts` | New unit tests |
| `frontend/src/lib/components/protocol/protocolGraph.ts` | Add `reparentNode()` helper |
| `frontend/src/lib/components/protocol/protocolGraph.test.ts` | New / extend tests for `reparentNode` |
| `frontend/src/lib/components/protocol/Inspector.svelte` | Add `branchErrors` prop + red callout |
| `frontend/src/routes/protocols/[id]/+page.svelte` | Pass time context to validator, pre-flight `saveAndPublish` and `openPdfPreview`, add `onnodedragstop` handler, pass `branchErrors` to Inspector |

---

## Task Ordering / Dependencies

The plan splits into a shared prerequisite and three tracks. Tasks within a track are sequential. Recommended order: shared fixture → backend rule → backend wiring → frontend rule → frontend wiring → drag-stop fix → manual verification.

- **Task 0 — Shared test fixture** — prerequisite for Tracks A and C (the test files load it).
- **Track A — Backend rule + tests** (Tasks 1–3) — depends on Task 0
- **Track B — Backend endpoint wiring + integration tests** (Tasks 4–6) — depends on Track A
- **Track C — Frontend rule + tests** (Tasks 7–9) — depends on Task 0
- **Track D — Frontend wiring** (Tasks 10–13) — depends on Track C
- **Track E — parentId reassignment fix** (Tasks 14–15) — independent
- **Track F — Manual verification + close** (Tasks 16–17) — depends on all

Each task ends with a commit. Test commands assume CWD is the worktree root (`/home/wesuuu/Code/trellisbio/.claude/worktrees/qa-0006-branch-role-validation`).

---

### Task 0: Shared — define the test fixture (behavior contract)

**Files:**
- Create: `tests/fixtures/branch_role_validation.json` (new file at repo root)

This fixture is the single source of truth for the rule's observable behavior. Both backend (`test_protocols_validation.py`) and frontend (`protocolValidation.test.ts`) load this file in subsequent tasks and assert identical outcomes. Adding a behavior case = one JSON entry, not two test functions.

- [ ] **Step 1: Create the fixture file**

```json
{
    "$comment": "Shared behavior contract for branch_requires_distinct_roles. Consumed by backend/tests/unit/test_protocols_validation.py and frontend/src/lib/components/protocol/protocolValidation.test.ts. Each case's 'graph' is fed verbatim to the backend validator; the frontend test extracts nodes/edges and packs the rest into a BranchTimeContext. 'fires_on' is the sorted list of source node IDs that should produce branch_requires_distinct_roles errors.",
    "cases": [
        {
            "name": "linear chain has no errors",
            "graph": {
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 100, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"}
                ]
            },
            "expected": {"fires_on": []}
        },
        {
            "name": "branching with all-distinct non-null parentIds is ok",
            "graph": {
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-B", "type": "swimLane", "data": {"label": "Lane B"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-C", "type": "swimLane", "data": {"label": "Lane C"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-B", "data": {"label": "C", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "d", "type": "unitOp", "parentId": "lane-C", "data": {"label": "D", "duration_min": 30}, "position": {"x": 0, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"},
                    {"id": "e3", "source": "a", "target": "d"}
                ]
            },
            "expected": {"fires_on": []}
        },
        {
            "name": "branching with two targets in same parentId fires",
            "graph": {
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-A", "data": {"label": "C", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "d", "type": "unitOp", "parentId": "lane-A", "data": {"label": "D", "duration_min": 30}, "position": {"x": 0, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "b", "target": "c"},
                    {"id": "e3", "source": "b", "target": "d"}
                ]
            },
            "expected": {"fires_on": ["b"]}
        },
        {
            "name": "branching with one null-parentId target fires",
            "graph": {
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-B", "type": "swimLane", "data": {"label": "Lane B"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-B", "data": {"label": "B", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "c", "type": "unitOp", "data": {"label": "C", "duration_min": 30}, "position": {"x": 0, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"}
                ]
            },
            "expected": {"fires_on": ["a"]}
        },
        {
            "name": "time mode horizontal disjoint intervals suppress",
            "graph": {
                "timeEnabled": true,
                "pixelsPerHour": 200,
                "layout": "horizontal",
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 400, "y": 0}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-A", "data": {"label": "C", "duration_min": 30}, "position": {"x": 500, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"}
                ]
            },
            "expected": {"fires_on": []}
        },
        {
            "name": "time mode horizontal overlapping intervals fire",
            "graph": {
                "timeEnabled": true,
                "pixelsPerHour": 200,
                "layout": "horizontal",
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 60}, "position": {"x": 400, "y": 0}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-A", "data": {"label": "C", "duration_min": 60}, "position": {"x": 450, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"}
                ]
            },
            "expected": {"fires_on": ["a"]}
        },
        {
            "name": "time mode vertical layout uses y-axis",
            "graph": {
                "timeEnabled": true,
                "pixelsPerHour": 200,
                "layout": "vertical",
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 0, "y": 400}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-A", "data": {"label": "C", "duration_min": 30}, "position": {"x": 0, "y": 500}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"}
                ]
            },
            "expected": {"fires_on": []}
        },
        {
            "name": "nested branching reports both branching points",
            "graph": {
                "nodes": [
                    {"id": "ps", "type": "processStart", "data": {"label": "Start"}, "position": {"x": 0, "y": 0}},
                    {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
                    {"id": "a", "type": "unitOp", "parentId": "lane-A", "data": {"label": "A", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "b", "type": "unitOp", "parentId": "lane-A", "data": {"label": "B", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "c", "type": "unitOp", "parentId": "lane-A", "data": {"label": "C", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "d", "type": "unitOp", "parentId": "lane-A", "data": {"label": "D", "duration_min": 30}, "position": {"x": 0, "y": 0}},
                    {"id": "e", "type": "unitOp", "parentId": "lane-A", "data": {"label": "E", "duration_min": 30}, "position": {"x": 0, "y": 0}}
                ],
                "edges": [
                    {"id": "e0", "source": "ps", "target": "a"},
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "a", "target": "c"},
                    {"id": "e3", "source": "c", "target": "d"},
                    {"id": "e4", "source": "c", "target": "e"}
                ]
            },
            "expected": {"fires_on": ["a", "c"]}
        }
    ]
}
```

- [ ] **Step 2: Verify it parses as JSON**

Run:
```bash
python -c "import json; d = json.load(open('tests/fixtures/branch_role_validation.json')); print(f'{len(d[\"cases\"])} cases')"
```
Expected: `8 cases`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/branch_role_validation.json
git commit -m "test(qa-0006): shared fixture for branch role validation cases

Single source of truth for branch_requires_distinct_roles behavior.
Loaded by backend (test_protocols_validation.py) and frontend
(protocolValidation.test.ts) tests in following tasks."
```

---

### Task 1: Backend — failing tests via shared fixture

**Files:**
- Modify: `backend/tests/unit/test_protocols_validation.py` (extend)

- [ ] **Step 1: Add the fixture-driven test at the bottom of the test file**

```python
import json
from pathlib import Path

import pytest

# Repo root: backend/tests/unit/test_protocols_validation.py → parents[3] = repo root
_FIXTURE_PATH = Path(__file__).parents[3] / "tests" / "fixtures" / "branch_role_validation.json"
_FIXTURE_CASES = json.loads(_FIXTURE_PATH.read_text())["cases"]


@pytest.mark.parametrize(
    "case",
    _FIXTURE_CASES,
    ids=[c["name"] for c in _FIXTURE_CASES],
)
def test_branch_role_fixture(case):
    """Shared behavior contract for branch_requires_distinct_roles.

    Cases live in tests/fixtures/branch_role_validation.json — the single
    source of truth shared with the frontend test suite. Adding/changing
    a case forces both implementations to update together.
    """
    result = validate_protocol_graph(case["graph"], [])
    actual_sources = sorted(
        i.node_id
        for i in result.issues
        if i.code == "branch_requires_distinct_roles"
    )
    expected = sorted(case["expected"]["fires_on"])
    assert actual_sources == expected, (
        f"case '{case['name']}': expected fires_on={expected}, got {actual_sources}"
    )


def test_branch_role_issue_python_shape():
    """Backend-specific assertions on ValidationIssue (severity, message)."""
    case = next(
        c for c in _FIXTURE_CASES
        if c["name"] == "branching with two targets in same parentId fires"
    )
    result = validate_protocol_graph(case["graph"], [])
    issue = next(
        i for i in result.issues if i.code == "branch_requires_distinct_roles"
    )
    assert issue.severity == "error"
    assert issue.node_id == "b"
    assert "branches to" in issue.message
    assert result.ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd backend && pytest tests/unit/test_protocols_validation.py -v -k "branch_role"
```
Expected: All parametrized cases that expect `fires_on` non-empty FAIL (rule not implemented yet — backend reports zero `branch_requires_distinct_roles` issues). The shape test also FAILS. Cases with `fires_on: []` pass trivially.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_protocols_validation.py
git commit -m "test(qa-0006): backend failing tests load shared branch role fixture"
```

---

### Task 2: Backend — implement the rule

**Files:**
- Modify: `backend/app/services/protocols/validation.py`

- [ ] **Step 1: Add the rule helper near the bottom of the file, before `__all__`**

Insert this function after `_process_starts_per_component` (around line 202):

```python
def _branch_role_issues(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[ValidationIssue]:
    """Fire branch_requires_distinct_roles when a unit op has 2+ outgoing
    branches sharing parentIds (or with null parentId), unless time mode is
    enabled and the immediate target intervals are pairwise disjoint."""
    issues: list[ValidationIssue] = []
    nodes_by_id = {n["id"]: n for n in nodes if "id" in n}
    outgoing: dict[str, list[str]] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s is None or t is None:
            continue
        outgoing.setdefault(s, []).append(t)

    time_enabled = bool(graph.get("timeEnabled"))
    pixels_per_hour = float(graph.get("pixelsPerHour") or 200)
    layout = graph.get("layout") or "horizontal"

    def interval_for(node: dict[str, Any]) -> tuple[float, float]:
        pos = node.get("position") or {}
        axis = float(pos.get("x", 0)) if layout == "horizontal" else float(pos.get("y", 0))
        start = axis / pixels_per_hour * 60.0
        duration = float((node.get("data") or {}).get("duration_min") or 30)
        return (start, start + duration)

    def intervals_pairwise_disjoint(targets: list[dict[str, Any]]) -> bool:
        intervals = [interval_for(t) for t in targets]
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if not (a[1] <= b[0] or b[1] <= a[0]):
                    return False
        return True

    for source_id, target_ids in outgoing.items():
        src = nodes_by_id.get(source_id)
        if not src or src.get("type") != "unitOp":
            continue
        targets = [
            nodes_by_id[tid]
            for tid in target_ids
            if tid in nodes_by_id and nodes_by_id[tid].get("type") == "unitOp"
        ]
        if len(targets) < 2:
            continue

        parent_ids = [t.get("parentId") for t in targets]
        has_duplicate = len(set(parent_ids)) != len(parent_ids)
        has_null = any(pid is None for pid in parent_ids)
        if not (has_duplicate or has_null):
            continue

        if time_enabled and intervals_pairwise_disjoint(targets):
            continue

        label = (src.get("data") or {}).get("label") or "<unnamed>"
        target_labels = [(t.get("data") or {}).get("label") or "<unnamed>" for t in targets]
        issues.append(
            ValidationIssue(
                severity="error",
                code="branch_requires_distinct_roles",
                node_id=source_id,
                message=(
                    f"Step '{label}' branches to {', '.join(target_labels)} which "
                    "share or lack distinct role assignments. Assign each branch "
                    "target to a different role, or enable time mode and stagger "
                    "the branches at non-overlapping times."
                ),
            )
        )

    return issues
```

- [ ] **Step 2: Wire the helper into `validate_protocol_graph` (around line 158, before the `ok = ...` line)**

```python
    issues.extend(_branch_role_issues(nodes, edges, graph))

    ok = not any(i.severity == "error" for i in issues)
    return ValidationResult(ok=ok, issues=issues)
```

- [ ] **Step 3: Run tests**

Run:
```bash
cd backend && pytest tests/unit/test_protocols_validation.py -v
```
Expected: ALL tests PASS (the 8 new ones plus the 8 existing).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/protocols/validation.py
git commit -m "feat(qa-0006): backend branch_requires_distinct_roles rule

Fires when a unit op has 2+ outgoing branches that share or lack distinct
parentIds (lane assignments). Suppressed when time mode is enabled AND
immediate branch target intervals are pairwise disjoint."
```

---

### Task 3: Backend — `assert_no_branch_errors` helper

**Files:**
- Modify: `backend/app/services/protocols/validation.py`
- Modify: `backend/tests/unit/test_protocols_validation.py`

- [ ] **Step 1: Add a failing test for the helper at the bottom of the test file**

These tests reuse fixture cases (loaded as `_FIXTURE_CASES` in Task 1's edits) so the helper's behavior tracks the shared contract.

```python
from fastapi import HTTPException

from app.services.protocols.validation import assert_no_branch_errors


def test_assert_no_branch_errors_raises_400_on_violation():
    case = next(c for c in _FIXTURE_CASES if c["expected"]["fires_on"])
    with pytest.raises(HTTPException) as exc_info:
        assert_no_branch_errors(case["graph"], [])
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "branch_requires_distinct_roles"
    assert len(exc_info.value.detail["issues"]) >= 1


def test_assert_no_branch_errors_passes_on_valid_graph():
    case = next(c for c in _FIXTURE_CASES if not c["expected"]["fires_on"])
    # Should not raise.
    assert_no_branch_errors(case["graph"], [])
```

- [ ] **Step 2: Verify test fails**

Run:
```bash
cd backend && pytest tests/unit/test_protocols_validation.py::test_assert_no_branch_errors_raises_400_on_violation -v
```
Expected: FAIL with `ImportError: cannot import name 'assert_no_branch_errors'`.

- [ ] **Step 3: Add the helper to `validation.py`**

After `validate_protocol_graph`, before `__all__`:

```python
def assert_no_branch_errors(
    graph: dict[str, Any],
    unit_ops: list[UnitOpDefinition],
) -> None:
    """Raise HTTPException(400) if any branch_requires_distinct_roles issue fires.

    Other validation issues (warnings, missing process start, etc.) are not
    enforced here — callers handle them separately if needed.
    """
    from fastapi import HTTPException  # noqa: PLC0415 — keep validation.py import-light

    result = validate_protocol_graph(graph, unit_ops)
    blocking = [i for i in result.issues if i.code == "branch_requires_distinct_roles"]
    if blocking:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "branch_requires_distinct_roles",
                "issues": [i.model_dump() for i in blocking],
            },
        )
```

Update `__all__`:

```python
__all__ = [
    "ValidationIssue",
    "ValidationResult",
    "validate_protocol_graph",
    "assert_no_branch_errors",
]
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd backend && pytest tests/unit/test_protocols_validation.py -v
```
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/validation.py backend/tests/unit/test_protocols_validation.py
git commit -m "feat(qa-0006): assert_no_branch_errors raises 400 helper"
```

---

### Task 4: Backend — gate `POST /protocols/{id}/publish-draft`

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py`

- [ ] **Step 1: Read the existing imports at the top of the file**

Confirm the imports include `select`, `Protocol`, `ProtocolVersion`. We need to add `assert_no_branch_errors` and a way to load org unit ops.

- [ ] **Step 2: Add imports**

At the top of the file, add:

```python
from app.models.science import UnitOpDefinition
from app.services.protocols.validation import assert_no_branch_errors
```

- [ ] **Step 3: Add the gate inside `publish_draft_version`, immediately after the `draft` is loaded (after line 453)**

```python
    # Defense-in-depth: reject publish if branch role rule fires.
    org_id = user.selected_org_id
    unit_ops_result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.org_id == org_id)
    )
    unit_ops = list(unit_ops_result.scalars().all())
    assert_no_branch_errors(draft.graph or {}, unit_ops)
```

- [ ] **Step 4: Skip writing endpoint tests for this task — they go in the consolidated integration test file in Task 6.**

- [ ] **Step 5: Verify the existing test suite still passes**

Run:
```bash
cd backend && pytest tests/ -v -x -k "publish_draft or protocol_version"
```
Expected: existing publish-draft tests still pass (their fixtures don't trip the new rule).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/protocol_versions.py
git commit -m "feat(qa-0006): gate publish-draft on branch_requires_distinct_roles"
```

---

### Task 5: Backend — gate `POST /runs` and PDF endpoints

**Files:**
- Modify: `backend/app/api/endpoints/runs.py`
- Modify: `backend/app/api/endpoints/protocol_pdfs.py`

- [ ] **Step 1: Add imports to `runs.py`**

```python
from app.models.science import UnitOpDefinition
from app.services.protocols.validation import assert_no_branch_errors
```

- [ ] **Step 2: Wire the gate into `create_run`**

In `create_run`, immediately after the `initial_graph = protocol.graph.copy() if protocol.graph else {}` line (around line 93), add:

```python
        unit_ops_result = await db.execute(
            select(UnitOpDefinition).where(
                UnitOpDefinition.org_id == user.selected_org_id
            )
        )
        unit_ops = list(unit_ops_result.scalars().all())
        assert_no_branch_errors(initial_graph, unit_ops)
```

(This runs only when `protocol_id` is supplied — runs without a protocol have no graph to validate.)

- [ ] **Step 3: Add imports to `protocol_pdfs.py`**

```python
from app.models.science import UnitOpDefinition
from app.services.protocols.validation import assert_no_branch_errors
```

- [ ] **Step 4: Add a small local helper at the top of `protocol_pdfs.py`, just after the existing `_resolve_template_path` function**

```python
async def _assert_branch_ok(db: AsyncSession, graph: dict, org_id) -> None:
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.org_id == org_id)
    )
    unit_ops = list(result.scalars().all())
    assert_no_branch_errors(graph or {}, unit_ops)
```

- [ ] **Step 5: Wire the helper into all four endpoints**

In `get_protocol_sop_pdf` (after `protocol = result.scalar_one_or_none()` check returns 404, around line 71):

```python
    await _assert_branch_ok(db, protocol.graph or {}, user.selected_org_id)
```

In `get_protocol_batch_record_pdf` (around line 125): same line.

In `preview_protocol_sop_pdf` (around line 187, after the 404 check, but use `body.graph` not `protocol.graph`):

```python
    await _assert_branch_ok(db, body.graph, user.selected_org_id)
```

In `preview_protocol_batch_record_pdf` (around line 243): same.

- [ ] **Step 6: Run existing endpoint tests to ensure they still pass**

Run:
```bash
cd backend && pytest tests/ -v -x -k "pdf or runs"
```
Expected: Most tests pass. Some pre-existing test fixtures may use simplified graphs that don't trip the rule. If a test fixture happens to construct an invalid graph, it may fail — note which test name and we'll fix in Task 6.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/app/api/endpoints/protocol_pdfs.py
git commit -m "feat(qa-0006): gate /runs and /pdf endpoints on branch role rule"
```

---

### Task 6: Backend — consolidated integration test for the gates

**Files:**
- Create: `backend/tests/integration/test_qa0006_branch_role_enforcement.py`

- [ ] **Step 1: Find an existing integration test fixture pattern to mirror**

Read `backend/tests/integration/` for tests that already POST to `/science/runs`, `/science/protocols/.../publish-draft`, and `/science/protocols/.../pdf/sop`. Use the same `client`, `auth_headers`, `test_org`, `test_user` fixtures.

Run:
```bash
ls backend/tests/integration/ | head -20
grep -l "publish-draft\|/pdf/\|/runs" backend/tests/integration/*.py | head
```

- [ ] **Step 2: Create the new test file with one fixture and one test per gated endpoint**

```python
"""Integration tests for QA-0006 branch-role rule enforcement on
publish-draft, /runs, and PDF endpoints. Requires a draft graph with a
branching node whose immediate targets share a parentId."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Protocol, ProtocolVersion


def _branching_invalid_graph() -> dict:
    """Graph: ps -> a -> b -> (c, d), c & d both in lane-A. Invalid."""
    return {
        "nodes": [
            {"id": "ps", "type": "processStart", "data": {"label": "Start"}},
            {"id": "lane-A", "type": "swimLane", "data": {"label": "Lane A"}, "position": {"x": 0, "y": 0}},
            {"id": "a", "type": "unitOp", "parentId": "lane-A", "position": {"x": 0, "y": 0},
             "data": {"label": "A", "category": "Media Prep", "description": "...", "duration_min": 30,
                      "paramSchema": {"type": "object", "properties": {"x": {"type": "number"}}}}},
            {"id": "b", "type": "unitOp", "parentId": "lane-A", "position": {"x": 100, "y": 0},
             "data": {"label": "B", "category": "Media Prep", "description": "...", "duration_min": 30,
                      "paramSchema": {"type": "object", "properties": {"x": {"type": "number"}}}}},
            {"id": "c", "type": "unitOp", "parentId": "lane-A", "position": {"x": 200, "y": 0},
             "data": {"label": "C", "category": "Media Prep", "description": "...", "duration_min": 30,
                      "paramSchema": {"type": "object", "properties": {"x": {"type": "number"}}}}},
            {"id": "d", "type": "unitOp", "parentId": "lane-A", "position": {"x": 250, "y": 0},
             "data": {"label": "D", "category": "Media Prep", "description": "...", "duration_min": 30,
                      "paramSchema": {"type": "object", "properties": {"x": {"type": "number"}}}}},
        ],
        "edges": [
            {"id": "e0", "source": "ps", "target": "a"},
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c"},
            {"id": "e3", "source": "b", "target": "d"},
        ],
        "timeEnabled": False,
        "pixelsPerHour": 200,
        "layout": "horizontal",
    }


async def _create_draft_protocol_with_graph(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    project_id: uuid.UUID,
    graph: dict,
) -> Protocol:
    """Create a Protocol + draft ProtocolVersion with the given graph."""
    resp = await client.post(
        "/science/protocols",
        json={"name": "QA-0006 Test", "project_id": str(project_id)},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    protocol_id = uuid.UUID(resp.json()["id"])

    resp = await client.put(
        f"/science/protocols/{protocol_id}?save_as_draft=true",
        json={"graph": graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    result = await db_session.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    return result.scalar_one()


async def test_publish_draft_rejects_invalid_branching_graph(
    client: AsyncClient,
    auth_headers: dict,
    test_project,
    db_session: AsyncSession,
):
    protocol = await _create_draft_protocol_with_graph(
        client, auth_headers, db_session, test_project.id, _branching_invalid_graph()
    )
    # Find the draft version number
    result = await db_session.execute(
        select(ProtocolVersion).where(
            (ProtocolVersion.protocol_id == protocol.id) & (ProtocolVersion.is_draft == True)
        )
    )
    draft = result.scalar_one()

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number={draft.version_number}",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "branch_requires_distinct_roles"


async def test_create_run_rejects_invalid_branching_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project,
    db_session: AsyncSession,
):
    protocol = await _create_draft_protocol_with_graph(
        client, auth_headers, db_session, test_project.id, _branching_invalid_graph()
    )
    # Hack: copy the draft graph onto the main protocol so /runs sees it.
    protocol.graph = _branching_invalid_graph()
    await db_session.commit()

    resp = await client.post(
        "/science/runs",
        json={
            "name": "Test Run",
            "project_id": str(test_project.id),
            "protocol_id": str(protocol.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "branch_requires_distinct_roles"


async def test_pdf_sop_get_rejects_invalid_branching_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project,
    db_session: AsyncSession,
):
    protocol = await _create_draft_protocol_with_graph(
        client, auth_headers, db_session, test_project.id, _branching_invalid_graph()
    )
    protocol.graph = _branching_invalid_graph()
    await db_session.commit()

    resp = await client.get(
        f"/science/protocols/{protocol.id}/pdf/sop",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "branch_requires_distinct_roles"


async def test_pdf_batch_record_post_rejects_invalid_branching_payload(
    client: AsyncClient,
    auth_headers: dict,
    test_project,
    db_session: AsyncSession,
):
    protocol = await _create_draft_protocol_with_graph(
        client, auth_headers, db_session, test_project.id, _branching_invalid_graph()
    )

    resp = await client.post(
        f"/science/protocols/{protocol.id}/pdf/batch-record",
        json={"graph": _branching_invalid_graph()},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "branch_requires_distinct_roles"
```

(If the codebase doesn't yet have a `test_project` fixture, mirror an existing test that creates one inline. Run `grep -rn "test_project" backend/tests/integration/ | head` to find one.)

- [ ] **Step 3: Run the new tests**

Run:
```bash
cd backend && pytest tests/integration/test_qa0006_branch_role_enforcement.py -v
```
Expected: ALL pass.

- [ ] **Step 4: Run the broader endpoint test suite to ensure no regressions**

Run:
```bash
cd backend && pytest tests/ -x
```
Expected: ALL pass. If any pre-existing test fails because its fixture graph trips the new rule, fix the fixture (add distinct lanes for branching, or remove branching) — that's the correct response since the fixture was implicitly invalid.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/test_qa0006_branch_role_enforcement.py
git commit -m "test(qa-0006): integration tests for endpoint enforcement"
```

---

### Task 7: Frontend — failing tests via shared fixture

**Files:**
- Create: `frontend/src/lib/components/protocol/protocolValidation.test.ts`

- [ ] **Step 1: Create the test file**

The fixture lives outside `frontend/`, so we read it via `fs` rather than a TS `import` (avoids `rootDir` resolution noise).

```typescript
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { Node, Edge } from "@xyflow/svelte";

import {
    computeBranchValidationErrors,
    type BranchTimeContext,
} from "./protocolValidation";

// frontend/src/lib/components/protocol/protocolValidation.test.ts
// → ../../../../../tests/fixtures/branch_role_validation.json (5 ups to repo root)
const FIXTURE_PATH = join(
    dirname(fileURLToPath(import.meta.url)),
    "../../../../../tests/fixtures/branch_role_validation.json",
);

interface FixtureCase {
    name: string;
    graph: {
        nodes: unknown[];
        edges: unknown[];
        timeEnabled?: boolean;
        pixelsPerHour?: number;
        layout?: "horizontal" | "vertical";
    };
    expected: { fires_on: string[] };
}

const FIXTURE: { cases: FixtureCase[] } = JSON.parse(
    readFileSync(FIXTURE_PATH, "utf-8"),
);

function timeContextOf(c: FixtureCase): BranchTimeContext {
    return {
        timeEnabled: c.graph.timeEnabled ?? false,
        pixelsPerHour: c.graph.pixelsPerHour ?? 200,
        layout: c.graph.layout ?? "horizontal",
    };
}

describe("computeBranchValidationErrors (shared fixture)", () => {
    // Shared behavior contract — cases live in
    // tests/fixtures/branch_role_validation.json. Adding/changing a case
    // forces both backend and frontend to update together.
    it.each(FIXTURE.cases.map((c) => [c.name, c] as const))(
        "%s",
        (_name, c) => {
            const nodes = c.graph.nodes as unknown as Node[];
            const edges = c.graph.edges as unknown as Edge[];
            const errs = computeBranchValidationErrors(
                nodes,
                edges,
                timeContextOf(c),
            );
            const actual = errs.map((e) => e.sourceNodeId).sort();
            const expected = [...c.expected.fires_on].sort();
            expect(actual).toEqual(expected);
        },
    );

    // Frontend-specific shape assertions on BranchValidationError.
    it("error shape includes source label and target labels", () => {
        const c = FIXTURE.cases.find(
            (x) => x.name === "branching with two targets in same parentId fires",
        )!;
        const errs = computeBranchValidationErrors(
            c.graph.nodes as unknown as Node[],
            c.graph.edges as unknown as Edge[],
            timeContextOf(c),
        );
        expect(errs).toHaveLength(1);
        expect(errs[0].sourceNodeId).toBe("b");
        expect(errs[0].sourceNodeLabel).toBe("B");
        expect(errs[0].targetNodeLabels.sort()).toEqual(["C", "D"]);
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd frontend && npm run test -- protocolValidation
```
Expected: parametrized cases that expect `fires_on` non-empty FAIL (signature mismatch — `computeBranchValidationErrors` doesn't accept the time-context arg yet, and null-parentId targets aren't flagged when their groups are size 1). Empty-`fires_on` cases may pass trivially or also fail depending on signature error.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/protocol/protocolValidation.test.ts
git commit -m "test(qa-0006): frontend failing tests load shared branch role fixture"
```

---

### Task 8: Frontend — extend `computeBranchValidationErrors`

**Files:**
- Modify: `frontend/src/lib/components/protocol/protocolValidation.ts`

- [ ] **Step 1: Replace the `computeBranchValidationErrors` function with the extended version**

```typescript
import type { Node, Edge } from "@xyflow/svelte";

export interface BranchValidationError {
    sourceNodeId: string;
    sourceNodeLabel: string;
    duplicateLane: string | null;
    targetNodeLabels: string[];
}

export interface ProcessStartValidationError {
    componentFirstNodeLabel: string;
    processStartCount: number;
}

export interface BranchTimeContext {
    timeEnabled: boolean;
    pixelsPerHour: number;
    layout: "horizontal" | "vertical";
}

/**
 * Detect branches whose immediate targets share or lack distinct role
 * assignments. When time mode is enabled, suppress errors where every pair
 * of target intervals is disjoint.
 */
export function computeBranchValidationErrors(
    nodes: Node[],
    edges: Edge[],
    timeContext: BranchTimeContext,
): BranchValidationError[] {
    const errors: BranchValidationError[] = [];

    // Build outgoing edge map: sourceId -> [targetId, ...]
    const outgoingMap = new Map<string, string[]>();
    for (const edge of edges) {
        if (!outgoingMap.has(edge.source)) outgoingMap.set(edge.source, []);
        outgoingMap.get(edge.source)!.push(edge.target);
    }

    // Exception: no swimlanes + purely linear -> skip
    const hasSwimlanes = nodes.some((n) => n.type === "swimLane");
    const hasBranching = [...outgoingMap.values()].some((t) => t.length >= 2);
    if (!hasSwimlanes && !hasBranching) return errors;

    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    const intervalFor = (n: Node): [number, number] => {
        const pos = n.position ?? { x: 0, y: 0 };
        const axis = timeContext.layout === "horizontal" ? pos.x : pos.y;
        const start = (axis / timeContext.pixelsPerHour) * 60;
        const duration = ((n.data as any)?.duration_min as number) ?? 30;
        return [start, start + duration];
    };

    const intervalsPairwiseDisjoint = (targets: Node[]): boolean => {
        const ints = targets.map(intervalFor);
        for (let i = 0; i < ints.length; i++) {
            for (let j = i + 1; j < ints.length; j++) {
                const a = ints[i], b = ints[j];
                if (!(a[1] <= b[0] || b[1] <= a[0])) return false;
            }
        }
        return true;
    };

    for (const [sourceId, targetIds] of outgoingMap) {
        if (targetIds.length < 2) continue;
        const src = nodeMap.get(sourceId);
        if (!src || src.type !== "unitOp") continue;

        const targets: Node[] = [];
        for (const tid of targetIds) {
            const t = nodeMap.get(tid);
            if (t && t.type === "unitOp") targets.push(t);
        }
        if (targets.length < 2) continue;

        const parentIds = targets.map((t) => t.parentId ?? null);
        const hasDuplicate = new Set(parentIds).size !== parentIds.length;
        const hasNull = parentIds.some((p) => p === null);
        if (!hasDuplicate && !hasNull) continue;

        if (timeContext.timeEnabled && intervalsPairwiseDisjoint(targets)) continue;

        // Determine duplicateLane for the message: the parentId shared by 2+
        // targets, or null if the conflict is "any null parentId".
        const counts = new Map<string | null, number>();
        for (const p of parentIds) counts.set(p, (counts.get(p) ?? 0) + 1);
        let duplicateLane: string | null = null;
        for (const [p, c] of counts) {
            if (c >= 2) { duplicateLane = p; break; }
        }
        // If only conflict is null parentId(s), duplicateLane stays null already.

        errors.push({
            sourceNodeId: sourceId,
            sourceNodeLabel: ((src.data as any).label || "Unnamed") as string,
            duplicateLane,
            targetNodeLabels: targets.map(
                (t) => ((t.data as any)?.label || "Unnamed") as string,
            ),
        });
    }
    return errors;
}

// computeProcessStartValidationErrors below is unchanged.
```

(Leave `computeProcessStartValidationErrors` as it is — it's not part of this change.)

- [ ] **Step 2: Run tests**

Run:
```bash
cd frontend && npm run test -- protocolValidation
```
Expected: ALL pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/protocol/protocolValidation.ts
git commit -m "feat(qa-0006): frontend branch role rule with time-mode suppression

Extends computeBranchValidationErrors with a third arg for time context
(timeEnabled, pixelsPerHour, layout). Detects same-parentId conflicts
and null-parentId targets. Suppresses errors when time mode is enabled
and all immediate target intervals are pairwise disjoint."
```

---

### Task 9: Frontend — fix call site in `+page.svelte` (signature change)

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Update the call to `computeBranchValidationErrors` (line 357)**

Change:
```typescript
const branchValidationErrors = $derived(() => computeBranchValidationErrors(nodes, edges));
```
to:
```typescript
const branchValidationErrors = $derived(() =>
    computeBranchValidationErrors(nodes, edges, {
        timeEnabled,
        pixelsPerHour,
        layout,
    }),
);
```

- [ ] **Step 2: Run frontend type check**

Run:
```bash
cd frontend && npm run check
```
Expected: PASS. No type errors.

- [ ] **Step 3: Run frontend tests**

Run:
```bash
cd frontend && npm run test
```
Expected: ALL pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/protocols/[id]/+page.svelte
git commit -m "feat(qa-0006): pass time context to branch validator"
```

---

### Task 10: Frontend — pre-flight in `saveAndPublish` and `openPdfPreview`

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Add a helper near the validation derivations (around line 365), after `branchInvalidNodeIds`**

```typescript
function blockingBranchMessage(): string | null {
    const errs = branchValidationErrors();
    if (errs.length === 0) return null;
    return `Cannot proceed: ${errs.length} branching ${errs.length === 1 ? "step needs" : "steps need"} distinct roles. See the warning banner.`;
}
```

- [ ] **Step 2: Add the pre-flight to `saveAndPublish` (after the existing status-block toasts, around line 521)**

After the existing block:
```typescript
        // Block if already approved, pending, or archived
        if (protocolStatus === "PENDING_APPROVAL" || protocolStatus === "APPROVED" || protocolStatus === "ARCHIVED") {
            ...
            return;
        }
```
add:
```typescript
        const block = blockingBranchMessage();
        if (block) {
            toast.error(block);
            return;
        }
```

- [ ] **Step 3: Add the pre-flight to `openPdfPreview` (around line 346)**

Replace:
```typescript
function openPdfPreview() {
    if (!protocol) return;
    showVersionHistory = false;
    showPdfDrawer = true;
}
```
with:
```typescript
function openPdfPreview() {
    if (!protocol) return;
    const block = blockingBranchMessage();
    if (block) {
        toast.error(block);
        return;
    }
    showVersionHistory = false;
    showPdfDrawer = true;
}
```

- [ ] **Step 4: Manually verify in dev**

Run:
```bash
cd frontend && npm run dev
```
Open a protocol in the browser, create a branching `a → b → (c, d)` where c and d share a lane, click "Save & Publish" — toast appears, no API call. Click PDF preview — toast appears, drawer doesn't open. Move c to a different lane (drag it; this won't fully clear yet without Task 14, but bypass by reloading) — actions succeed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/protocols/[id]/+page.svelte
git commit -m "feat(qa-0006): pre-flight saveAndPublish and openPdfPreview"
```

---

### Task 11: Frontend — Inspector branch error callout (failing test optional)

**Files:**
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte`
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Add a `branchErrors` prop to `Inspector.svelte`**

Open `frontend/src/lib/components/protocol/Inspector.svelte`. Find the `Props` interface near the top. Add:

```typescript
import type { BranchValidationError } from "./protocolValidation";

interface Props {
    // ... existing props
    branchErrors?: BranchValidationError[];
}
```

In the destructure, add `branchErrors = []`:

```typescript
let { ..., branchErrors = [] }: Props = $props();
```

- [ ] **Step 2: Render the callout above the parameter form**

Find the top of the inspector body markup (just inside the main wrapper, before the parameter section). Add:

```svelte
{#if branchErrors.length > 0}
    <div class="branch-error-callout">
        <span class="branch-error-icon">&#x26A0;</span>
        <div>
            {#each branchErrors as err}
                <div class="branch-error-line">
                    Branches to <strong>{err.targetNodeLabels.join(", ")}</strong>
                    {#if err.duplicateLane === null}
                        — at least one branch has no role assigned.
                    {:else}
                        — two branches share the same role.
                    {/if}
                    Assign distinct roles, or enable time mode and stagger them.
                </div>
            {/each}
        </div>
    </div>
{/if}
```

Add to the `<style>` block:

```css
.branch-error-callout {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 12px;
    margin: 0 0 12px 0;
    background: #fffbeb;
    border: 1px solid #f59e0b;
    border-radius: 6px;
    font-size: 12px;
    color: #92400e;
    line-height: 1.4;
}
.branch-error-icon {
    flex-shrink: 0;
    font-size: 14px;
}
.branch-error-line + .branch-error-line {
    margin-top: 4px;
}
```

- [ ] **Step 3: Wire the prop from `+page.svelte`**

In `+page.svelte`, find the Inspector usage (around line 1158 — the `<Inspector ... />` block under `{:else}` of `selectedNode.type === "processStart"`). Add a `branchErrors` prop:

```svelte
<Inspector
    node={selectedNode}
    ...existing props...
    branchErrors={selectedNodeId
        ? branchValidationErrors().filter((e) => e.sourceNodeId === selectedNodeId)
        : []}
/>
```

- [ ] **Step 4: Run frontend type check**

Run:
```bash
cd frontend && npm run check
```
Expected: PASS.

- [ ] **Step 5: Manual verification**

In the dev server, select the offending branching node. Inspector shows the amber callout with the error detail. Move one of the duplicate-lane targets to a different lane (won't update parent until Task 14, but reload to confirm the rendering logic).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/Inspector.svelte frontend/src/routes/protocols/[id]/+page.svelte
git commit -m "feat(qa-0006): inspector callout for branch validation errors"
```

---

### Task 12: Frontend — `reparentNode` helper (failing tests)

**Files:**
- Create / extend: `frontend/src/lib/components/protocol/protocolGraph.test.ts`

- [ ] **Step 1: Find or create the test file**

```bash
ls frontend/src/lib/components/protocol/protocolGraph.test.ts 2>/dev/null
```

If it exists, append. If not, create with imports.

- [ ] **Step 2: Add the failing tests**

```typescript
import { describe, it, expect } from "vitest";
import type { Node } from "@xyflow/svelte";
import { reparentNode } from "./protocolGraph";

function lane(id: string, x: number, y: number, w: number, h: number): Node {
    return {
        id,
        type: "swimLane",
        position: { x, y },
        measured: { width: w, height: h },
        data: { label: id },
    } as unknown as Node;
}

function step(id: string, parentId: string | undefined, position: { x: number; y: number }): Node {
    return {
        id,
        type: "unitOp",
        parentId,
        position,
        data: { label: id },
    } as unknown as Node;
}

describe("reparentNode", () => {
    it("moves a node into a new swimlane and adjusts position relative to it", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            // node currently in lane-A at relative (50,50) → absolute (50,50)
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        // Drag to absolute (200, 350) — inside lane-B (rel 200, 50)
        const updated = reparentNode(nodes, "n1", { x: 200, y: 350 });
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-B");
        expect(n1.position).toEqual({ x: 200, y: 50 });
    });

    it("clears parentId when dragged outside all swimlanes", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        const updated = reparentNode(nodes, "n1", { x: 800, y: 800 });
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBeUndefined();
        expect(n1.position).toEqual({ x: 800, y: 800 });
    });

    it("returns the same nodes array reference when target lane unchanged", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        // Drag to (100, 100) absolute — still inside lane-A (rel 100, 100)
        const updated = reparentNode(nodes, "n1", { x: 100, y: 100 });
        const n1 = updated.find((n) => n.id === "n1")!;
        // Same lane, position update only
        expect(n1.parentId).toBe("lane-A");
    });

    it("returns nodes unchanged when nodeId not found", () => {
        const nodes = [lane("lane-A", 0, 0, 600, 200)];
        const updated = reparentNode(nodes, "missing", { x: 50, y: 50 });
        expect(updated).toBe(nodes);
    });
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd frontend && npm run test -- protocolGraph
```
Expected: FAIL with "reparentNode is not exported".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/protocol/protocolGraph.test.ts
git commit -m "test(qa-0006): failing tests for reparentNode"
```

---

### Task 13: Frontend — implement `reparentNode`

**Files:**
- Modify: `frontend/src/lib/components/protocol/protocolGraph.ts`

- [ ] **Step 1: Add the function at the bottom of the file (after `findSwimLaneParent`)**

```typescript
/**
 * Move a node to a new absolute position. If the new position falls inside a
 * swimlane, set parentId to that lane and adjust the node's position to be
 * relative to the lane. Otherwise clear parentId and use the absolute position.
 *
 * Caller must pass the absolute position (not the SvelteFlow node-relative
 * position). Convert by adding the current parent's position before calling.
 */
export function reparentNode(
    nodes: Node[],
    nodeId: string,
    absolutePosition: { x: number; y: number },
): Node[] {
    const idx = nodes.findIndex((n) => n.id === nodeId);
    if (idx < 0) return nodes;
    const { parentId, adjustedPosition } = findSwimLaneParent(nodes, absolutePosition);
    return nodes.map((n, i) =>
        i === idx
            ? { ...n, parentId, position: adjustedPosition }
            : n,
    );
}
```

- [ ] **Step 2: Run tests**

```bash
cd frontend && npm run test -- protocolGraph
```
Expected: ALL pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/protocol/protocolGraph.ts
git commit -m "feat(qa-0006): reparentNode helper for drag-stop reassignment"
```

---

### Task 14: Frontend — `onnodedragstop` handler

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Add an import for `reparentNode`**

Find the existing import of `findSwimLaneParent` (around line 32):
```typescript
import { ..., findSwimLaneParent, ... } from "$lib/components/protocol/protocolGraph";
```
Add `reparentNode`:
```typescript
import { ..., findSwimLaneParent, reparentNode, ... } from "$lib/components/protocol/protocolGraph";
```

- [ ] **Step 2: Add the handler function near the other node-action handlers (after `onnodedragstart`'s area, around line 1130)**

Above the `<SvelteFlow>` element, add a function in the script:

```typescript
function handleNodeDragStop(_event: unknown, node: Node) {
    if (node.type !== "unitOp" && node.type !== "processStart") return;
    // Compute absolute position: if node has a parent, add its absolute position.
    let absX = node.position.x;
    let absY = node.position.y;
    if (node.parentId) {
        const parent = nodes.find((n) => n.id === node.parentId);
        if (parent) {
            absX += parent.position.x;
            absY += parent.position.y;
        }
    }
    const updated = reparentNode(nodes, node.id, { x: absX, y: absY });
    // Only reassign if the parent actually changed; reparentNode always
    // returns a new array even on no-op, so cheap-compare parentId.
    const before = nodes.find((n) => n.id === node.id)?.parentId;
    const after = updated.find((n) => n.id === node.id)?.parentId;
    if (before === after) return;
    nodes = updated;
}
```

- [ ] **Step 3: Wire the handler onto `<SvelteFlow>`**

Find the existing `onnodedragstart={() => pushUndoSnapshot()}` (line 1129) and add `onnodedragstop`:

```svelte
onnodedragstart={() => pushUndoSnapshot()}
onnodedragstop={handleNodeDragStop}
```

- [ ] **Step 4: Run frontend type check**

```bash
cd frontend && npm run check
```
Expected: PASS. (If the SvelteFlow event signature requires different args, adjust the handler — the `@xyflow/svelte` types should auto-suggest. Inspect `node_modules/@xyflow/svelte/dist/types.d.ts` for the exact type if needed.)

- [ ] **Step 5: Manual verification — the prerequisite bug fix**

```bash
cd frontend && npm run dev
```

In the editor:
1. Create `a → b → (c, d)` where c and d both start in lane-A (warning fires).
2. Drag d into a different lane.
3. Confirm the banner clears and the red ring goes away on b.
4. Try Save & Publish — succeeds.
5. Reload the page — the parentId change should persist (the save POST captured it).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/protocols/[id]/+page.svelte
git commit -m "fix(qa-0006): reparent nodes on drag-stop so validation clears

When a unit op is dragged between swimlanes, recompute parentId via
findSwimLaneParent. Without this, branchValidationErrors stays stuck on
the original lane assignment forever."
```

---

### Task 15: End-to-end manual verification (browser)

**Files:** none (verification only)

- [ ] **Step 1: Ensure dev server is running**

```bash
cd frontend && npm run dev
```
And separately:
```bash
cd backend && uvicorn app.main:app --reload
```

(Check existing scripts; if there's a `make dev` or `npm run dev:full`, use that.)

- [ ] **Step 2: Login and walk the acceptance criteria**

Login per dev creds: `localhost:5432`, user `postgres`, password `postgres`, db `batchrite` (any password works in dev).

Walk through:
1. Open a protocol. Build chain `a → b → (c, d)` where c, d are in the same swimlane.
2. Confirm: banner appears, b has red `.invalid` ring, Inspector shows callout when b is selected.
3. Click Save & Publish → toast: "Cannot proceed…".
4. Click PDF preview → toast appears, drawer doesn't open.
5. Drag d into a different swimlane → banner / ring / callout clear.
6. Save & Publish → succeeds.
7. Re-create the same conflict, then enable time mode (toggle button) and place c at x=400, d at x=500 with duration 30 each → banner clears (intervals disjoint).
8. Move d closer (overlapping c) → banner returns.
9. Try `POST /science/runs` directly via curl with the offending protocol_id while still in conflict → 400 with `{"detail": {"error": "branch_requires_distinct_roles"}}`.

- [ ] **Step 3: Run all tests one more time**

```bash
cd backend && pytest tests/
cd frontend && npm run test
cd frontend && npm run check
```
Expected: ALL pass.

- [ ] **Step 4: No commit (verification only)**

---

### Task 16: Refresh project rules and CLAUDE.md

**Files:**
- Modify (if affected): `.claude/rules/*.md`, `CLAUDE.md`

- [ ] **Step 1: Search for affected sections**

```bash
grep -rln "validate_protocol_graph\|computeBranchValidationErrors\|branch.*role\|swimlane" .claude/rules/ CLAUDE.md
```

- [ ] **Step 2: Decide if anything actually changed**

If a rule file references the validator in a way that's now stale (e.g., describes the old single-arg signature), update it. If new convention introduced, add a single line. Otherwise skip — do not pad files.

- [ ] **Step 3: Commit if touched**

```bash
git add .claude/rules/ CLAUDE.md
git commit -m "docs(qa-0006): refresh rules to reflect branch validation hard-block"
```

---

### Task 17: Update task status, exit worktree

**Files:** none (workflow)

- [ ] **Step 1: Wait for explicit user sign-off on the verification**

Do not close the task without it.

- [ ] **Step 2: Add a ClickUp comment summarizing the change**

`clickup_create_task_comment` on task `86e1a0ykx` with: scope (publish/run/PDF gates + parentId-reassignment fix), files touched (paste from File Map), tests added (counts).

- [ ] **Step 3: Set task status to complete**

`clickup_update_task` on `86e1a0ykx` with `status: "complete"`.

- [ ] **Step 4: Exit the worktree**

`ExitWorktree` action `keep`. Commits remain on `worktree-qa-0006-branch-role-validation` for the user to merge.

---

## Self-Review

Spec coverage:
- Shared behavior contract (fixture): Task 0. Loaded by Tasks 1 and 7.
- Rule definition (immediate-target distinctness + null-parentId + time-mode suppression): Tasks 2, 8.
- Frontend pre-flight on saveAndPublish + openPdfPreview: Task 10.
- Backend gate on publish-draft: Task 4. /runs: Task 5. PDF endpoints: Task 5.
- Per-node visual indicator (existing amber `.invalid`, no recolor): no task needed — already wired through `branchInvalidNodeIds` context which is unchanged.
- Inspector callout: Task 11.
- ValidationBanners reuse: no task needed — banner already renders `branchValidationErrors` and that's preserved.
- parentId reassignment fix: Tasks 12, 13, 14.
- Tests (unit, integration): Tasks 0 (fixture), 1, 3, 6, 7, 12.

No gaps.

Type consistency:
- Frontend `BranchTimeContext` shape used in Task 7 test, Task 8 implementation, Task 9 call site — consistent.
- Backend `assert_no_branch_errors(graph, unit_ops) -> None` used in Tasks 3, 4, 5, 6 — consistent.
- `reparentNode(nodes, nodeId, absolutePosition) -> Node[]` used in Tasks 12, 13, 14 — consistent.

No placeholders. All code blocks complete.
