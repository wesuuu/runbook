# Batch Record Import Benchmark — Implementation Plan (revised)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two gaps: (1) extend the batch-record import pipeline to preserve timestamps, signatures, and deviations in `Run.execution_data`; (2) add a Run-output benchmark with 8 scoring dimensions that runs under `-m benchmark` against hand-authored `expected_run.json` fixtures.

**Architecture:** Shared benchmark utilities (`matching.py`, generalized `discover_fixtures`) already in place (Tasks 1-4 on the current branch). New work: small backend schema + execution_data changes → frontend pass-through → single `score_run` scorer on top of the existing shared helpers → runner that executes the full pipeline.

**Tech Stack:** pytest + pytest-asyncio, `difflib.SequenceMatcher` via `matching.fuzzy_ratio`, `dataclasses`, existing `pydantic_ai` extraction/mapping pipeline, Svelte 5 frontend.

**Spec:** [docs/superpowers/specs/2026-04-17-batch-record-import-benchmark-design.md](../specs/2026-04-17-batch-record-import-benchmark-design.md)

**Branch baseline:** `feat/f-0057-benchmark` at `7b71672` (shared utilities landed; prior two-stage scoring work was reverted).

---

## File Structure

**Create:**
- `backend/tests/benchmarks/batch_record_scoring.py` — dataclasses, `_numeric_equal`, `_unit_equal`, `_fuzzy_match` alias, `score_run`, `print_run_report`, `print_run_summary`, `_build_auto_finalized`
- `backend/tests/unit/test_batch_record_scoring.py` — unit tests for the scorer (no LLM)
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/protocol.json`
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/expected_run.json`
- `backend/tests/benchmarks/document-to-run/05-messy-scan/document.pdf` (generated)

**Modify:**
- `backend/app/schemas/batch_record_import.py` — extend `FinalizedStepMapping`
- `backend/app/services/batch_record_extractor.py` — extend `map_values_to_execution_data`
- `backend/tests/integration/test_batch_record_import_api.py` — integration test for the new fields
- `backend/tests/benchmarks/conftest.py` — add `pro_org` module fixture, run score accumulator, extend summary hook
- `backend/tests/benchmarks/test_llm_eval.py` — add `TestBatchRecordAccuracy` class
- `frontend/src/lib/schemas/batchRecordImport.ts` — extend Zod schema
- `frontend/src/lib/components/BatchRecordImportModal.svelte` (or wherever finalize mutation is built) — pass through timestamps/signatures/deviations

**Delete:**
- `backend/tests/integration/test_batch_record_import_llm.py`
- `backend/tests/fixtures/sample_batch_record.pdf`
- `backend/tests/fixtures/sample_batch_record_extraction.json`
- `backend/tests/benchmarks/document-to-run/0{1..4}-<name>/expected_extraction.json` (replaced by expected_run.json)

---

## Phase 1 — Backend product change (TDD)

### Task 1: Extend `FinalizedStepMapping` schema + `map_values_to_execution_data`

**Files:**
- Modify: `backend/app/schemas/batch_record_import.py`
- Modify: `backend/app/services/batch_record_extractor.py`
- Modify: `backend/tests/integration/test_batch_record_import_api.py` (new test)

- [ ] **Step 1: Write the failing integration test**

Read `backend/tests/integration/test_batch_record_import_api.py` for fixture/helper conventions. Append a test that:
1. Seeds a project, protocol, and a batch record import in REVIEW status
2. POSTs to `/science/batch-record-imports/{id}/finalize` with a `step_mappings` payload that includes `timestamps`, `signatures`, `deviations` on at least one step
3. Fetches the created Run and asserts `run.execution_data[step_id]["timestamps"]`, `["signatures"]`, `["deviations"]` are present and equal what was sent

Example test skeleton (adapt to match existing conventions in the same file):

```python
async def test_finalize_preserves_timestamps_signatures_deviations(
    client: AsyncClient, auth_headers: dict, test_org, db_session,
):
    # ... create project, protocol (with at least one step "node-a"), batch record import in REVIEW status ...

    finalize_payload = {
        "protocol_id": str(protocol.id),
        "run_name": "TEST-RUN-001",
        "step_mappings": [{
            "protocol_step_id": "node-a",
            "values": [{"schema_field_key": "ph", "value": 7.2, "accepted": True}],
            "notes": "ok",
            "na": False,
            "na_reason": "",
            "timestamps": [{"label": "Start Time", "value": "08:30", "confidence": 0.9}],
            "signatures": [{"initials_or_name": "JKL", "role": "Operator", "confidence": 0.88}],
            "deviations": [{"description": "Minor delay", "severity": "minor", "step_reference": "", "confidence": 0.7}],
        }],
    }
    resp = await client.post(
        f"/science/batch-record-imports/{import_row.id}/finalize",
        json=finalize_payload,
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    run_id = resp.json()["run_id"]
    run_resp = await client.get(f"/science/runs/{run_id}", headers=auth_headers)
    assert run_resp.status_code == 200
    step_data = run_resp.json()["execution_data"]["node-a"]
    assert step_data["timestamps"] == [{"label": "Start Time", "value": "08:30", "confidence": 0.9}]
    assert step_data["signatures"] == [{"initials_or_name": "JKL", "role": "Operator", "confidence": 0.88}]
    assert len(step_data["deviations"]) == 1
    assert step_data["deviations"][0]["description"] == "Minor delay"
```

- [ ] **Step 2: Run and verify it fails**

```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate && pytest tests/integration/test_batch_record_import_api.py::test_finalize_preserves_timestamps_signatures_deviations -v
```

Expected: FAIL — either Pydantic rejects unknown fields (`timestamps`, `signatures`, `deviations`) or accepts them silently and `execution_data[step_id]` lacks them.

- [ ] **Step 3: Extend the schema**

In `backend/app/schemas/batch_record_import.py`, find `class FinalizedStepMapping` (around line 116). Add three fields at the end:

```python
class FinalizedStepMapping(BaseModel):
    protocol_step_id: str
    values: List[FinalizedValue] = []
    notes: str = ""
    na: bool = False
    na_reason: str = ""
    timestamps: List[ExtractedTimestampResponse] = []
    signatures: List[ExtractedSignatureResponse] = []
    deviations: List[ExtractedDeviationResponse] = []
```

Verify `ExtractedTimestampResponse`, `ExtractedSignatureResponse`, `ExtractedDeviationResponse` are already imported/defined in this file (they should be — they're used by `ExtractedStepResponse`). If not, import them.

- [ ] **Step 4: Extend `map_values_to_execution_data`**

In `backend/app/services/batch_record_extractor.py`, find `def map_values_to_execution_data` (around line 734). The completed-step branch builds this dict:

```python
execution_data[step_id] = {
    "status": "completed",
    "results": results,
    "notes": notes,
    "completed_by_user_id": str(user_id),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
```

Add three new keys BEFORE the `completed_by_user_id` key:

```python
execution_data[step_id] = {
    "status": "completed",
    "results": results,
    "notes": notes,
    "timestamps": mapping.get("timestamps", []),
    "signatures": mapping.get("signatures", []),
    "deviations": mapping.get("deviations", []),
    "completed_by_user_id": str(user_id),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
```

N/A branch unchanged — N/A steps don't carry these.

- [ ] **Step 5: Re-run integration test**

```bash
cd /home/wesuuu/Code/trellisbio/backend && pytest tests/integration/test_batch_record_import_api.py -q
```

Expected: all integration tests pass (including the new one + the existing suite, which should still pass since the new fields are all optional with default empty lists).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/batch_record_import.py backend/app/services/batch_record_extractor.py backend/tests/integration/test_batch_record_import_api.py
git commit -m "feat(batch-import): preserve timestamps, signatures, deviations in Run [F-0057]"
```

---

## Phase 2 — Frontend pass-through

### Task 2: Frontend finalize payload + Zod schema

**Files:**
- Modify: `frontend/src/lib/schemas/batchRecordImport.ts` (or equivalent — locate via grep)
- Modify: `frontend/src/lib/components/BatchRecordImportModal.svelte` (or wherever finalize is built)

- [ ] **Step 1: Locate the finalize payload shape**

```bash
cd /home/wesuuu/Code/trellisbio
grep -rn "step_mappings" frontend/src/lib/schemas/ frontend/src/lib/components/ | head -20
grep -rn "finalize" frontend/src/lib/components/ frontend/src/routes/ | head -20
```

Find the Zod schema for `FinalizedStepMapping` (search terms: `protocol_step_id`, `finalize`, `BatchRecord`).

- [ ] **Step 2: Extend the Zod schema**

Add three optional list fields mirroring the backend shape. Typical pattern — add alongside existing fields:

```typescript
export const FinalizedStepMappingSchema = z.object({
  protocol_step_id: z.string(),
  values: z.array(FinalizedValueSchema).default([]),
  notes: z.string().default(''),
  na: z.boolean().default(false),
  na_reason: z.string().default(''),
  timestamps: z.array(ExtractedTimestampSchema).default([]),
  signatures: z.array(ExtractedSignatureSchema).default([]),
  deviations: z.array(ExtractedDeviationSchema).default([]),
});
```

Reuse existing `ExtractedTimestamp/Signature/Deviation` Zod schemas if present; otherwise define them to match the backend response shapes.

- [ ] **Step 3: Include the fields when building the finalize payload**

In the finalize-mutation call site (the modal or a hook), where `step_mappings` are assembled from the review UI state, include the three fields from each mapped step's extraction:

```typescript
step_mappings: mappings.map(m => ({
  protocol_step_id: m.protocol_step_id,
  values: m.values,
  notes: m.notes,
  na: m.na,
  na_reason: m.na_reason,
  timestamps: m.extracted_step?.timestamps ?? [],
  signatures: m.extracted_step?.signatures ?? [],
  deviations: m.extracted_step?.deviations ?? [],
}))
```

(Exact shape depends on how the modal tracks per-step extraction state. Check the existing payload assembly and add the three fields alongside.)

- [ ] **Step 4: Run frontend checks**

```bash
cd /home/wesuuu/Code/trellisbio/frontend && npm run check
```

Expected: passes. If the Zod inference flags type mismatches at the modal's payload site, fix them.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schemas/batchRecordImport.ts frontend/src/lib/components/BatchRecordImportModal.svelte
git commit -m "feat(batch-import): pass timestamps/signatures/deviations through finalize [F-0057]"
```

---

## Phase 3 — Scorer (TDD)

### Task 3: `batch_record_scoring.py` — dataclasses + numeric/unit helpers + fuzzy alias

**Files:**
- Create: `backend/tests/benchmarks/batch_record_scoring.py`
- Create: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_batch_record_scoring.py`:

```python
"""Unit tests for batch_record_scoring (no LLM)."""

from tests.benchmarks.batch_record_scoring import (
    RunScoreDetails,
    RunScores,
    _fuzzy_match,
    _numeric_equal,
    _unit_equal,
)


def test_run_scores_defaults():
    s = RunScores(fixture_name="t")
    assert s.overall == 0.0
    assert not s.passed


def test_run_scores_perfect():
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
        timestamps=1.0,
        signatures=1.0,
        deviations=1.0,
        na_correctness=1.0,
        notes_preservation=1.0,
        run_metadata=1.0,
    )
    assert s.overall == 1.0
    assert s.passed


def test_run_scores_weighted_sum():
    # step_completeness 20% + param_accuracy 25% = 45%
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
    )
    assert abs(s.overall - 0.45) < 1e-6


def test_fuzzy_match_aliased():
    assert _fuzzy_match("Buffer Prep", "buffer prep") == 1.0


def test_numeric_equal():
    assert _numeric_equal(100.0, 104.9)
    assert not _numeric_equal(100.0, 110.0)
    assert _numeric_equal(7.00, 7.01)
    assert not _numeric_equal(7.00, 7.05)


def test_unit_equal():
    assert _unit_equal("°C", "C")
    assert _unit_equal("μm", "um")
    assert not _unit_equal("g", "mg")
    assert _unit_equal(None, None)
    assert not _unit_equal("mL", None)
```

- [ ] **Step 2: Run and verify fails**

```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create the module**

Create `backend/tests/benchmarks/batch_record_scoring.py`:

```python
"""Scoring for batch record import Run-output benchmark.

Compares the `execution_data + run_metadata` produced by the pipeline
against `expected_run.json` fixtures. One public entry point `score_run`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.benchmarks.matching import fuzzy_ratio


_fuzzy_match = fuzzy_ratio


_UNIT_SYNONYMS: dict[str, str] = {
    "°c": "c", "c": "c", "celsius": "c",
    "μm": "um", "um": "um", "micron": "um", "microns": "um",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "l", "liter": "l", "liters": "l",
    "g": "g", "grams": "g",
    "mg": "mg", "milligrams": "mg",
    "psi": "psi", "bar": "bar", "rpm": "rpm",
    "min": "min", "minute": "min", "minutes": "min",
    "hr": "hr", "hour": "hr", "hours": "hr", "h": "hr",
}


def _numeric_equal(a, b) -> bool:
    try:
        af, bf = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if af == bf:
        return True
    abs_diff = abs(af - bf)
    if abs_diff <= 0.01:
        return True
    denom = max(abs(af), abs(bf))
    if denom == 0:
        return False
    return abs_diff / denom <= 0.05


def _normalize_unit(u: str | None) -> str:
    if u is None:
        return ""
    return _UNIT_SYNONYMS.get(u.lower().strip(), u.lower().strip())


def _unit_equal(a: str | None, b: str | None) -> bool:
    return _normalize_unit(a) == _normalize_unit(b)


@dataclass
class RunScoreDetails:
    steps_expected: int = 0
    steps_found: int = 0
    steps_missed: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    param_value_mismatches: list[dict] = field(default_factory=list)
    param_unit_mismatches: list[dict] = field(default_factory=list)
    timestamps_missed: list[dict] = field(default_factory=list)
    signatures_missed: list[dict] = field(default_factory=list)
    deviations_missed: list[dict] = field(default_factory=list)
    na_mismatches: list[dict] = field(default_factory=list)
    notes_mismatches: list[dict] = field(default_factory=list)
    run_metadata_mismatches: list[dict] = field(default_factory=list)


@dataclass
class RunScores:
    fixture_name: str
    step_completeness: float = 0.0     # 20%
    param_accuracy: float = 0.0        # 25%
    timestamps: float = 0.0            # 15%
    signatures: float = 0.0            # 10%
    deviations: float = 0.0            # 10%
    na_correctness: float = 0.0        # 10%
    notes_preservation: float = 0.0    # 5%
    run_metadata: float = 0.0          # 5%
    details: RunScoreDetails = field(default_factory=RunScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_completeness * 0.20
            + self.param_accuracy * 0.25
            + self.timestamps * 0.15
            + self.signatures * 0.10
            + self.deviations * 0.10
            + self.na_correctness * 0.10
            + self.notes_preservation * 0.05
            + self.run_metadata * 0.05
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_completeness": round(self.step_completeness, 3),
            "param_accuracy": round(self.param_accuracy, 3),
            "timestamps": round(self.timestamps, 3),
            "signatures": round(self.signatures, 3),
            "deviations": round(self.deviations, 3),
            "na_correctness": round(self.na_correctness, 3),
            "notes_preservation": round(self.notes_preservation, 3),
            "run_metadata": round(self.run_metadata, 3),
            "details": {
                "steps_expected": self.details.steps_expected,
                "steps_found": self.details.steps_found,
                "steps_missed": self.details.steps_missed,
                "steps_extra": self.details.steps_extra,
                "param_value_mismatches": self.details.param_value_mismatches,
                "param_unit_mismatches": self.details.param_unit_mismatches,
                "timestamps_missed": self.details.timestamps_missed,
                "signatures_missed": self.details.signatures_missed,
                "deviations_missed": self.details.deviations_missed,
                "na_mismatches": self.details.na_mismatches,
                "notes_mismatches": self.details.notes_mismatches,
                "run_metadata_mismatches": self.details.run_metadata_mismatches,
            },
        }
```

- [ ] **Step 4: Run tests**

```bash
cd /home/wesuuu/Code/trellisbio/backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): add RunScores dataclass and helpers [F-0057]"
```

---

### Task 4: `score_run` — step_completeness + param_accuracy + na_correctness (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Append failing tests**

```python
from tests.benchmarks.batch_record_scoring import score_run


def _mk_expected(execution_data: dict, run_name: str = "t") -> dict:
    return {"run_name": run_name, "execution_data": execution_data}


def _mk_protocol_graph(step_ids: list[str]) -> dict:
    return {
        "nodes": [
            {"id": sid, "type": "unitOp", "position": {"x": 0, "y": 0},
             "data": {"label": sid, "paramSchema": {"type": "object", "properties": {}}}}
            for sid in step_ids
        ],
        "edges": [],
    }


def test_score_run_step_completeness_perfect():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": [], "deviations": []}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": [], "deviations": []}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.step_completeness == 1.0
    assert scores.details.steps_expected == 1
    assert scores.details.steps_found == 1


def test_score_run_step_completeness_missing():
    # Expected covers 2 steps, actual covers 1
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": ""}}
    expected = _mk_expected({
        "node-a": {"status": "completed", "results": {}, "notes": ""},
        "node-b": {"status": "completed", "results": {}, "notes": ""},
    })
    protocol = _mk_protocol_graph(["node-a", "node-b"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    # F1 with recall 0.5, precision 1.0 -> 0.667
    assert 0.65 < scores.step_completeness < 0.7
    assert "node-b" in scores.details.steps_missed


def test_score_run_param_accuracy_perfect():
    actual_ed = {"node-a": {"status": "completed", "results": {"ph": 7.2, "vol_ml": 500}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {"ph": 7.2, "vol_ml": 500}, "notes": ""}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.param_accuracy == 1.0


def test_score_run_param_accuracy_wrong_value():
    actual_ed = {"node-a": {"status": "completed", "results": {"ph": 9.0}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {"ph": 7.2}, "notes": ""}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.param_accuracy == 0.0
    assert scores.details.param_value_mismatches


def test_score_run_na_correctness_perfect():
    actual_ed = {"node-a": {"status": "na", "na_reason": "not done"}}
    expected = _mk_expected({"node-a": {"status": "na", "na_reason": "not done"}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.na_correctness == 1.0


def test_score_run_na_correctness_wrong():
    # Expected N/A, actual completed -> miss
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "na", "na_reason": "not done"}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.na_correctness == 0.0
    assert scores.details.na_mismatches
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_batch_record_scoring.py -v -k score_run
```

Expected: `ImportError` for `score_run`.

- [ ] **Step 3: Implement `score_run` with three dimensions**

Append to `batch_record_scoring.py`:

```python
from tests.benchmarks.matching import f1


def score_run(
    actual_execution_data: dict,
    actual_run_metadata: dict,
    expected_run: dict,
    protocol_graph: dict,
    fixture_name: str = "",
) -> RunScores:
    """Score the pipeline's Run output against expected_run.json."""
    scores = RunScores(fixture_name=fixture_name)
    d = scores.details

    expected_ed = expected_run.get("execution_data", {})
    actual_ed = actual_execution_data

    d.steps_expected = len(expected_ed)
    d.steps_found = len(actual_ed)

    # ── 1. step_completeness (F1 over protocol_step_ids keyed in execution_data) ──
    expected_keys = set(expected_ed.keys())
    actual_keys = set(actual_ed.keys())
    matched_keys = expected_keys & actual_keys
    d.steps_missed = sorted(expected_keys - actual_keys)
    d.steps_extra = sorted(actual_keys - expected_keys)
    scores.step_completeness = f1(
        n_matched=len(matched_keys),
        n_expected=len(expected_keys),
        n_actual=len(actual_keys),
    )

    # ── 2. param_accuracy (3 points per expected param: key present + value + unit) ──
    # For now units on results aren't stored explicitly in execution_data — unit-equality folds
    # into value-equality via numeric tolerance (exact fallback for non-numeric).
    param_total = 0
    param_correct = 0
    for step_id in matched_keys:
        exp_step = expected_ed[step_id]
        act_step = actual_ed[step_id]
        if exp_step.get("status") != "completed":
            continue
        exp_results = exp_step.get("results", {}) or {}
        act_results = act_step.get("results", {}) or {}
        for key, exp_val in exp_results.items():
            param_total += 1
            if key not in act_results:
                d.param_value_mismatches.append({
                    "step": step_id, "key": key,
                    "expected": exp_val, "actual": None,
                })
                continue
            act_val = act_results[key]
            if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                if _numeric_equal(exp_val, act_val):
                    param_correct += 1
                else:
                    d.param_value_mismatches.append({
                        "step": step_id, "key": key,
                        "expected": exp_val, "actual": act_val,
                    })
            else:
                if str(exp_val).lower().strip() == str(act_val).lower().strip():
                    param_correct += 1
                else:
                    d.param_value_mismatches.append({
                        "step": step_id, "key": key,
                        "expected": exp_val, "actual": act_val,
                    })
    scores.param_accuracy = (
        param_correct / param_total if param_total > 0 else 1.0
    )

    # ── 6. na_correctness (per matched step, expected status == actual status) ──
    na_total = 0
    na_correct = 0
    for step_id in matched_keys:
        exp_status = expected_ed[step_id].get("status")
        act_status = actual_ed[step_id].get("status")
        if exp_status in ("completed", "na"):
            na_total += 1
            if exp_status == act_status:
                na_correct += 1
            else:
                d.na_mismatches.append({
                    "step": step_id,
                    "expected": exp_status,
                    "actual": act_status,
                })
    scores.na_correctness = (
        na_correct / na_total if na_total > 0 else 1.0
    )

    return scores
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_batch_record_scoring.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score_run step_completeness/param_accuracy/na_correctness [F-0057]"
```

---

### Task 5: `score_run` — timestamps + signatures + deviations + notes + run_metadata (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Append failing tests**

```python
def test_score_run_timestamps_match():
    ts = [{"label": "Start Time", "value": "08:30"}]
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": ts, "signatures": [], "deviations": []}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": ts, "signatures": [], "deviations": []}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.timestamps == 1.0


def test_score_run_timestamps_missing():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": [], "deviations": []}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [{"label": "Start Time", "value": "08:30"}], "signatures": [], "deviations": []}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.timestamps == 0.0
    assert scores.details.timestamps_missed


def test_score_run_signatures_and_deviations():
    sigs = [{"initials_or_name": "JKL", "role": "Operator"}]
    devs = [{"description": "Minor delay"}]
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": sigs, "deviations": devs}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "", "timestamps": [], "signatures": sigs, "deviations": devs}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    assert scores.signatures == 1.0
    assert scores.deviations == 1.0


def test_score_run_notes_preservation():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": "Solution clear.", "timestamps": [], "signatures": [], "deviations": []}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": "Solution was clear.", "timestamps": [], "signatures": [], "deviations": []}})
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "t"}, expected, protocol, "t")
    # Fuzzy ratio of the two strings is high -> preserved
    assert scores.notes_preservation >= 0.9


def test_score_run_run_metadata_match():
    actual_ed = {"node-a": {"status": "completed", "results": {}, "notes": ""}}
    expected = _mk_expected({"node-a": {"status": "completed", "results": {}, "notes": ""}}, run_name="LOT-2026-100")
    protocol = _mk_protocol_graph(["node-a"])
    scores = score_run(actual_ed, {"run_name": "LOT-2026-100"}, expected, protocol, "t")
    assert scores.run_metadata == 1.0
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/unit/test_batch_record_scoring.py -v -k "timestamps or signatures or deviations or notes_preservation or run_metadata"
```

Expected: fails (dims default 0.0).

- [ ] **Step 3: Implement the five dimensions**

In `score_run`, before `return scores`, add:

```python
    # ── 3. timestamps F1 over (step, label, value) ──
    exp_ts: list[tuple] = []
    for step_id, s in expected_ed.items():
        for t in s.get("timestamps", []) or []:
            exp_ts.append((step_id, t.get("label", ""), t.get("value", "")))
    act_ts: list[tuple] = []
    for step_id, s in actual_ed.items():
        for t in s.get("timestamps", []) or []:
            act_ts.append((step_id, t.get("label", ""), t.get("value", "")))
    if not exp_ts and not act_ts:
        scores.timestamps = 1.0
    elif not exp_ts:
        scores.timestamps = 0.0
    else:
        matched = 0
        remaining = list(act_ts)
        for exp in exp_ts:
            best = None
            best_r = 0.0
            for act in remaining:
                r = (
                    _fuzzy_match(exp[0], act[0]) * 0.5
                    + _fuzzy_match(exp[1], act[1]) * 0.25
                    + _fuzzy_match(exp[2], act[2]) * 0.25
                )
                if r > best_r:
                    best_r = r
                    best = act
            if best is not None and best_r >= 0.7:
                matched += 1
                remaining.remove(best)
            else:
                d.timestamps_missed.append({
                    "step": exp[0], "label": exp[1], "value": exp[2],
                })
        scores.timestamps = f1(
            n_matched=matched, n_expected=len(exp_ts), n_actual=len(act_ts),
        )

    # ── 4. signatures F1 over (step, initials, role) ──
    def _f1_tuples(exp_list, act_list, threshold=0.7):
        if not exp_list and not act_list:
            return 1.0, []
        if not exp_list:
            return 0.0, []
        matched, missed = 0, []
        remaining = list(act_list)
        for exp in exp_list:
            best, best_r = None, 0.0
            for act in remaining:
                r = sum(_fuzzy_match(e, a) for e, a in zip(exp, act)) / len(exp)
                if r > best_r:
                    best_r = r
                    best = act
            if best is not None and best_r >= threshold:
                matched += 1
                remaining.remove(best)
            else:
                missed.append(exp)
        return (
            f1(n_matched=matched, n_expected=len(exp_list), n_actual=len(act_list)),
            missed,
        )

    exp_sigs, act_sigs = [], []
    for step_id, s in expected_ed.items():
        for sig in s.get("signatures", []) or []:
            exp_sigs.append((step_id, sig.get("initials_or_name", ""), sig.get("role") or ""))
    for step_id, s in actual_ed.items():
        for sig in s.get("signatures", []) or []:
            act_sigs.append((step_id, sig.get("initials_or_name", ""), sig.get("role") or ""))
    scores.signatures, sig_missed = _f1_tuples(exp_sigs, act_sigs)
    d.signatures_missed.extend(
        {"step": m[0], "initials_or_name": m[1], "role": m[2]} for m in sig_missed
    )

    # ── 5. deviations F1 over (step, description) ──
    exp_devs, act_devs = [], []
    for step_id, s in expected_ed.items():
        for dv in s.get("deviations", []) or []:
            exp_devs.append((step_id, dv.get("description", "")))
    for step_id, s in actual_ed.items():
        for dv in s.get("deviations", []) or []:
            act_devs.append((step_id, dv.get("description", "")))
    scores.deviations, dev_missed = _f1_tuples(exp_devs, act_devs, threshold=0.6)
    d.deviations_missed.extend(
        {"step": m[0], "description": m[1]} for m in dev_missed
    )

    # ── 7. notes_preservation (avg fuzzy ratio per matched completed step) ──
    notes_scores: list[float] = []
    for step_id in matched_keys:
        exp_step = expected_ed[step_id]
        if exp_step.get("status") != "completed":
            continue
        exp_notes = exp_step.get("notes", "") or ""
        act_notes = actual_ed[step_id].get("notes", "") or ""
        if not exp_notes and not act_notes:
            continue  # skip steps with no expected notes
        ratio = _fuzzy_match(exp_notes, act_notes)
        notes_scores.append(ratio)
        if ratio < 0.7:
            d.notes_mismatches.append({
                "step": step_id, "expected": exp_notes, "actual": act_notes,
            })
    scores.notes_preservation = (
        sum(notes_scores) / len(notes_scores) if notes_scores else 1.0
    )

    # ── 8. run_metadata (run_name fuzzy match) ──
    exp_name = expected_run.get("run_name", "") or ""
    act_name = actual_run_metadata.get("run_name", "") or ""
    if not exp_name and not act_name:
        scores.run_metadata = 1.0
    elif _fuzzy_match(exp_name, act_name) >= 0.8:
        scores.run_metadata = 1.0
    else:
        scores.run_metadata = 0.0
        d.run_metadata_mismatches.append({
            "field": "run_name", "expected": exp_name, "actual": act_name,
        })
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_batch_record_scoring.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score_run timestamps/signatures/deviations/notes/metadata [F-0057]"
```

---

### Task 6: Print helpers + `_build_auto_finalized` utility

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`

- [ ] **Step 1: Append the three print helpers and auto-finalize utility**

```python
import json


def print_run_report(scores: RunScores) -> None:
    status = "PASS" if scores.passed else "FAIL"
    d = scores.details
    print()
    print(f"{'=' * 65}")
    print(f"  [RUN] {scores.fixture_name:<42} {status} {scores.overall:.0%}")
    print(f"{'=' * 65}")
    print(f"  {'Dimension':<24} {'Score':>6}  Detail")
    print(f"  {'-' * 60}")
    print(f"  {'Step Completeness':<24} {scores.step_completeness:>5.2f}  "
          f"{d.steps_found}/{d.steps_expected} found, {len(d.steps_extra)} extra")
    print(f"  {'Param Accuracy':<24} {scores.param_accuracy:>5.2f}  "
          f"{len(d.param_value_mismatches)} mismatches")
    print(f"  {'Timestamps':<24} {scores.timestamps:>5.2f}  "
          f"{len(d.timestamps_missed)} missed")
    print(f"  {'Signatures':<24} {scores.signatures:>5.2f}  "
          f"{len(d.signatures_missed)} missed")
    print(f"  {'Deviations':<24} {scores.deviations:>5.2f}  "
          f"{len(d.deviations_missed)} missed")
    print(f"  {'N/A Correctness':<24} {scores.na_correctness:>5.2f}  "
          f"{len(d.na_mismatches)} mismatches")
    print(f"  {'Notes Preservation':<24} {scores.notes_preservation:>5.2f}")
    print(f"  {'Run Metadata':<24} {scores.run_metadata:>5.2f}")
    print(f"  {'-' * 60}")
    print(f"  {'Overall (weighted)':<24} {scores.overall:>5.2f}  threshold: 0.75")
    print(f"{'=' * 65}")
    if d.steps_missed:
        print(f"  Steps missed: {d.steps_missed}")
    if d.param_value_mismatches:
        print(f"  Param mismatches (first 5):")
        print(f"    {json.dumps(d.param_value_mismatches[:5], indent=4, default=str)}")
    print()


def print_run_summary(scores_list: list[RunScores]) -> None:
    if not scores_list:
        return
    print()
    print(f"{'=' * 95}")
    print(f"  BATCH RECORD RUN-OUTPUT SUMMARY")
    print(f"{'=' * 95}")
    print(
        f"  {'Fixture':<25} {'Overall':>7} {'Step':>6} {'Param':>6} "
        f"{'Time':>6} {'Sig':>6} {'Dev':>6} {'N/A':>6} {'Note':>6} {'Meta':>6} {'Status':>7}"
    )
    print(f"  {'-' * 90}")
    for s in scores_list:
        st = "PASS" if s.passed else "FAIL"
        print(
            f"  {s.fixture_name:<25} {s.overall:>6.0%} "
            f"{s.step_completeness:>5.0%} {s.param_accuracy:>5.0%} "
            f"{s.timestamps:>5.0%} {s.signatures:>5.0%} {s.deviations:>5.0%} "
            f"{s.na_correctness:>5.0%} {s.notes_preservation:>5.0%} "
            f"{s.run_metadata:>5.0%} {st:>7}"
        )
    passed = sum(1 for s in scores_list if s.passed)
    print(f"  {'-' * 90}")
    print(f"  {passed}/{len(scores_list)} run fixtures passed")
    print(f"{'=' * 95}\n")


def build_auto_finalized_mappings(
    extraction, mappings,
) -> list[dict]:
    """Simulate the user auto-accepting all extracted values in the review UI.

    Produces the `step_mappings` payload shape that `map_values_to_execution_data`
    consumes (see `FinalizedStepMapping` schema).
    """
    finalized: list[dict] = []
    for sm in mappings:
        step = extraction.steps[sm.extracted_step_index]
        finalized.append({
            "protocol_step_id": sm.protocol_step_id,
            "values": [
                {
                    "schema_field_key": pm.schema_field_key,
                    "value": pm.extracted_value,
                    "accepted": True,
                    "edited": False,
                    "original_value": pm.extracted_value,
                    "original_confidence": pm.confidence,
                }
                for pm in sm.param_mappings
            ],
            "notes": step.notes or "",
            "na": False,
            "na_reason": "",
            "timestamps": [t.model_dump() for t in step.timestamps],
            "signatures": [s.model_dump() for s in step.signatures],
            "deviations": [dv.model_dump() for dv in step.deviations],
        })
    return finalized
```

- [ ] **Step 2: Verify imports work**

```bash
python -c "from tests.benchmarks.batch_record_scoring import print_run_report, print_run_summary, build_auto_finalized_mappings, score_run; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py
git commit -m "test(benchmark): add run-output print helpers and auto-finalize util [F-0057]"
```

---

## Phase 4 — Conftest + Runner

### Task 7: Extend conftest (pro_org + accumulator + summary hook)

**Files:**
- Modify: `backend/tests/benchmarks/conftest.py`

- [ ] **Step 1: Read current conftest**

```bash
cat backend/tests/benchmarks/conftest.py | head -50
```

- [ ] **Step 2: Add imports and fixture**

Near the top of conftest.py (near existing `import pytest`), add:

```python
import pytest_asyncio
from app.models.iam import Organization, SubscriptionTier
```

Near the bottom (before `all_benchmark_scores`), add the module-scope fixture:

```python
@pytest_asyncio.fixture
async def pro_org(db_session) -> Organization:
    """Pro-tier org for benchmarks so AI provider defaults resolve."""
    org = Organization(
        name="Benchmark Org",
        subscription_tier=SubscriptionTier.PRO.value,
    )
    db_session.add(org)
    await db_session.flush()
    return org
```

Next to `all_benchmark_scores: list = []`, add:

```python
all_batch_record_run_scores: list = []
```

Extend `pytest_terminal_summary`:

```python
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print aggregate benchmark summary at end of run."""
    from tests.benchmarks.scoring import print_summary_table
    from tests.benchmarks.batch_record_scoring import print_run_summary

    if all_benchmark_scores:
        print_summary_table(all_benchmark_scores)
    if all_batch_record_run_scores:
        print_run_summary(all_batch_record_run_scores)
```

- [ ] **Step 3: Remove the class-scope `pro_org` from `TestProtocolImportAccuracy`**

In `backend/tests/benchmarks/test_llm_eval.py`, delete the `@pytest_asyncio.fixture async def pro_org(...)` method inside the `TestProtocolImportAccuracy` class (around lines 40-50). Test method's `pro_org` arg now resolves via conftest.

- [ ] **Step 4: Verify F-0058 benchmark still collects**

```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate && pytest tests/benchmarks/test_llm_eval.py -m benchmark --collect-only -q
```

Expected: 6 `TestProtocolImportAccuracy::test_import_accuracy[*]` items.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/conftest.py backend/tests/benchmarks/test_llm_eval.py
git commit -m "test(benchmark): promote pro_org + add run-score accumulator [F-0057]"
```

---

### Task 8: `TestBatchRecordAccuracy` runner class

**Files:**
- Modify: `backend/tests/benchmarks/test_llm_eval.py`

- [ ] **Step 1: Add imports**

At the top of `test_llm_eval.py`, near existing imports:

```python
from app.services.batch_record_extractor import (
    extract_batch_record_data,
    extract_batch_record_pages,
    map_steps_to_protocol,
    map_values_to_execution_data,
)
from tests.benchmarks.batch_record_scoring import (
    build_auto_finalized_mappings,
    print_run_report,
    score_run,
)
from tests.benchmarks.conftest import (
    all_batch_record_run_scores,
    discover_fixtures,
    load_json,
)
```

- [ ] **Step 2: Add module-level fixture collection**

After the existing `_fixture_dirs` lines:

```python
_br_fixture_dirs = discover_fixtures(
    subdir="document-to-run",
    marker_file="expected_run.json",
)
_br_fixture_ids = [d.name for d in _br_fixture_dirs]
```

Fixtures without `expected_run.json` (e.g., not authored yet) are skipped automatically.

- [ ] **Step 3: Append the runner class at the bottom of the file**

```python
@pytest.mark.benchmark
class TestBatchRecordAccuracy:
    """Run the full batch-record-import pipeline and score the output Run."""

    @pytest.mark.parametrize(
        "fixture_dir", _br_fixture_dirs, ids=_br_fixture_ids,
    )
    async def test_batch_record_to_run(
        self, fixture_dir: Path, db_session, pro_org,
    ):
        # 1. Extract
        doc = find_document(fixture_dir)
        mime = get_mime_type(doc)
        text, page_images = await extract_batch_record_pages(
            doc, mime, db_session, org_id=pro_org.id,
        )
        extraction = await extract_batch_record_data(
            text, page_images, db_session, org_id=pro_org.id,
        )

        # 2. Map against target protocol
        protocol = load_json(fixture_dir, "protocol.json")
        mappings = await map_steps_to_protocol(
            extraction, protocol, db_session, org_id=pro_org.id,
        )

        # 3. Simulate user-finalize: auto-accept all extracted values + pass through aux fields
        finalized = build_auto_finalized_mappings(extraction, mappings)
        execution_data = map_values_to_execution_data(
            finalized, protocol, user_id=pro_org.id,
        )

        # 4. Score against expected_run.json
        expected_run = load_json(fixture_dir, "expected_run.json")
        run_metadata = {
            "run_name": extraction.batch_id or extraction.document_title or "",
        }
        scores = score_run(
            execution_data, run_metadata, expected_run, protocol, fixture_dir.name,
        )
        print_run_report(scores)
        all_batch_record_run_scores.append(scores)

        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2, default=str)}"
        )
```

- [ ] **Step 4: Verify collection (0 items until fixtures are authored)**

```bash
pytest tests/benchmarks/test_llm_eval.py -m benchmark --collect-only -q 2>&1 | tail -10
```

Expected: 6 `TestProtocolImportAccuracy` items + 0 `TestBatchRecordAccuracy` items (no expected_run.json yet anywhere).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/test_llm_eval.py
git commit -m "test(benchmark): add TestBatchRecordAccuracy runner [F-0057]"
```

---

## Phase 5 — Author ground-truth fixtures (human review per scenario)

Each task reads the scenario's existing `expected_extraction.json` (soon to be deleted) to understand what the document contains, then authors `protocol.json` + `expected_run.json`. **Pause for user sign-off before each commit.**

### Task 9: Author 01-perfect-match fixtures

- [ ] **Step 1:** Read `backend/tests/benchmarks/document-to-run/01-perfect-match/expected_extraction.json` — gives step structure, params, timestamps, signatures, notes.

- [ ] **Step 2:** Author `protocol.json` with 3 nodes matching the 3 extraction steps. Give each a paramSchema with fields that map cleanly from the extracted labels.

- [ ] **Step 3:** Author `expected_run.json` — `run_name` = batch_id ("LOT-2026-100"). Each protocol step gets `status: "completed"`, `results` keyed by schema_field, `notes` from extraction, and `timestamps/signatures/deviations` arrays pulled directly from the extraction.

- [ ] **Step 4:** Show user the two files for sign-off. Commit only on approval:

```bash
git add backend/tests/benchmarks/document-to-run/01-perfect-match/protocol.json \
        backend/tests/benchmarks/document-to-run/01-perfect-match/expected_run.json
git commit -m "test(benchmark): author 01-perfect-match protocol + expected_run [F-0057]"
```

### Task 10: Author 02-wrong-protocol fixtures

- [ ] **Step 1:** Read the extraction (cell-culture run: Cell Seeding / Incubation / Harvest).

- [ ] **Step 2:** Author `protocol.json` with an unrelated 3-step purification protocol (e.g., Buffer Prep → Protein A Chromatography → Sterile Filtration).

- [ ] **Step 3:** Author `expected_run.json` — no step mappings possible, so `execution_data` should be empty (or mark all protocol steps as `na` with `na_reason: "Protocol does not match document"`). Pick ONE of those two conventions and document the choice in the file. Prefer **empty execution_data** — simpler and reflects the reality that the mapping stage produces no StepMappings. `run_name` = batch_id from extraction if present.

- [ ] **Step 4:** Show user, commit on approval:

```bash
git add backend/tests/benchmarks/document-to-run/02-wrong-protocol/protocol.json \
        backend/tests/benchmarks/document-to-run/02-wrong-protocol/expected_run.json
git commit -m "test(benchmark): author 02-wrong-protocol protocol + expected_run [F-0057]"
```

### Task 11: Author 03-half-complete fixtures

- [ ] **Step 1:** Read the extraction — typically fewer steps than a "full" protocol.

- [ ] **Step 2:** Author `protocol.json` with 5 steps where only 2-3 are covered by the document.

- [ ] **Step 3:** Author `expected_run.json` — covered steps `status: "completed"` with all data; uncovered steps either not present in execution_data OR `status: "na"`. Prefer **not-present** (mirrors the real pipeline which only writes execution_data for mapped steps).

- [ ] **Step 4:** Show user, commit on approval.

### Task 12: Author 04-extra-steps fixtures

- [ ] **Step 1:** Read the extraction — document has extra steps not in protocol.

- [ ] **Step 2:** Author `protocol.json` with fewer steps than the document — only the subset that should map.

- [ ] **Step 3:** Author `expected_run.json` — only the mapped steps present. Extra extracted steps don't appear in execution_data (no protocol_step_id to key on).

- [ ] **Step 4:** Show user, commit on approval.

### Task 13: Create 05-messy-scan fixture

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/document.pdf`
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/expected_run.json`

- [ ] **Step 1:** Generate a messy-scan style PDF. Simplest approach: copy `backend/tests/artifacts/templates/batch_record_filled_simple.pdf` to the fixture dir as `document.pdf`, then optionally run it through a Pillow-based degradation script (rotate 2°, Gaussian blur 0.8, noise) to simulate scan artifacts. Commit the resulting PDF.

Alternative if the degradation script is friction: use an already-degraded sample from `tests/artifacts/templates/` if one exists, or skip degradation and note this fixture tests a clean-scan scenario (move the messy-scan label elsewhere).

- [ ] **Step 2:** Author `protocol.json` + `expected_run.json` matching whatever the document actually contains. Since the document is a real filled batch record, read the content first to know what's expected.

- [ ] **Step 3:** Show user, commit on approval.

---

## Phase 6 — Cleanup + Dry Run

### Task 14: Delete the orphaned smoke test and now-unused expected_extraction.json files

- [ ] **Step 1:** Confirm nothing else references these paths:

```bash
cd /home/wesuuu/Code/trellisbio
grep -rn "sample_batch_record\|test_batch_record_import_llm\|expected_extraction" backend/ | grep -v "tests/benchmarks/document-to-run"
```

Expected: only matches inside `document-to-run/` (the files we're about to delete) or in the deleted smoke test itself.

- [ ] **Step 2:** Delete files:

```bash
git rm backend/tests/integration/test_batch_record_import_llm.py
git rm backend/tests/fixtures/sample_batch_record.pdf
git rm backend/tests/fixtures/sample_batch_record_extraction.json
git rm backend/tests/benchmarks/document-to-run/01-perfect-match/expected_extraction.json
git rm backend/tests/benchmarks/document-to-run/02-wrong-protocol/expected_extraction.json
git rm backend/tests/benchmarks/document-to-run/03-half-complete/expected_extraction.json
git rm backend/tests/benchmarks/document-to-run/04-extra-steps/expected_extraction.json
```

- [ ] **Step 3:** Run unit tests to confirm nothing broke:

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: no new failures (3 pre-existing `test_ai_config.py` failures from TD-0074 are unrelated and remain).

- [ ] **Step 4:** Commit:

```bash
git commit -m "test(benchmark): remove F-0057 smoke test and orphaned extraction fixtures [F-0057]"
```

### Task 15: End-to-end dry run with real LLM + optional calibration

- [ ] **Step 1:** Confirm an LLM provider is configured (Ollama at `localhost:11434` with `llama3.2-vision:11b`, or cloud creds via env):

```bash
echo "Vision provider: $BATCHRITE_AI_VISION_PROVIDER  Model: $BATCHRITE_AI_VISION_MODEL"
```

If neither is configured, STOP — benchmark can't run.

- [ ] **Step 2:** Run batch-record benchmark only:

```bash
cd /home/wesuuu/Code/trellisbio/backend && source .venv/bin/activate && pytest tests/benchmarks/test_llm_eval.py::TestBatchRecordAccuracy -m benchmark -v -s
```

Expected: 5 fixtures run (01-05). Each prints a report. Summary table at end shows PASS/FAIL per fixture and dimensional breakdown.

- [ ] **Step 3:** Review outcomes:

- All PASS → benchmark baseline established.
- Some FAIL at 0.60-0.75 → likely LLM quality gap, not scoring bug. Note fixture names.
- Some FAIL near 0.0 → likely scoring bug or fixture misauthoring. Pause and investigate.

- [ ] **Step 4:** Calibrate only if needed:

Scoring tolerances (numeric 5%, fuzzy 0.7/0.85) are the knobs. Only adjust if clearly-correct extractions score poorly. Do NOT relax tolerances to mask real LLM quality issues.

- [ ] **Step 5:** Confirm F-0058 still collects cleanly:

```bash
pytest tests/benchmarks/test_llm_eval.py::TestProtocolImportAccuracy -m benchmark --collect-only
```

- [ ] **Step 6:** No commit on pass; calibration commit if any:

```bash
# only if tolerances adjusted
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): calibrate run-output scoring tolerances [F-0057]"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- Product changes (backend schema + execution_data) → Task 1
- Frontend pass-through → Task 2
- Run scorer (dataclasses + helpers) → Task 3
- `score_run` first 3 dims → Task 4
- `score_run` remaining 5 dims → Task 5
- Print helpers + auto-finalize → Task 6
- Conftest promotion + accumulators + summary → Task 7
- Runner class → Task 8
- Fixture authoring (5 scenarios) → Tasks 9-13
- Cleanup → Task 14
- Dry run + calibration → Task 15

**2. Placeholder scan:** None. Every step has concrete code or commands. Fixture authoring tasks defer to per-document inspection + user sign-off (inherent to the problem).

**3. Type consistency:** `RunScores`, `RunScoreDetails`, `score_run` consistent across tasks. `build_auto_finalized_mappings` produces the shape consumed by `map_values_to_execution_data` (which accepts the post-Pydantic dicts). Frontend `FinalizedStepMapping` mirrors backend Pydantic schema exactly.
