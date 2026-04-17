# Batch Record Import Benchmark — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM accuracy benchmark for the F-0057 paper batch-record import pipeline — migrate the four orphaned fixtures into `backend/tests/benchmarks/document-to-run/`, add stage-separated scoring (extraction + mapping), wire a parametrized runner under the existing `-m benchmark` marker.

**Architecture:** New `batch_record_scoring.py` with two scorers (`score_extraction`, `score_mapping`) and helper alignment/tolerance utilities. New `TestBatchRecordAccuracy` class in the existing `test_llm_eval.py`. Conftest extended with fixture discovery, shared `pro_org` fixture, and an updated `pytest_terminal_summary` that prints three tables (protocol-import, batch-record-extraction, batch-record-mapping).

**Tech Stack:** pytest + pytest-asyncio, `difflib.SequenceMatcher` for fuzzy string match, `dataclasses` for score containers, `pydantic_ai` pipeline (already in place).

**Spec:** [docs/superpowers/specs/2026-04-17-batch-record-import-benchmark-design.md](../specs/2026-04-17-batch-record-import-benchmark-design.md)

---

## File Structure

**Create:**
- `backend/tests/benchmarks/batch_record_scoring.py` — dataclasses, helpers, `score_extraction`, `score_mapping`, `print_extraction_report`, `print_mapping_report`
- `backend/tests/unit/test_batch_record_scoring.py` — unit tests for the scorer (no LLM required)
- `backend/tests/benchmarks/document-to-run/` — new fixture tree
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/document.pdf` — migrated + new scenario docs
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/expected_extraction.json`
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/protocol.json`
- `backend/tests/benchmarks/document-to-run/0{1..5}-<name>/expected_mapping.json`

**Modify:**
- `backend/tests/benchmarks/conftest.py` — add batch-record fixture discovery, promote `pro_org` to module scope, extend `pytest_terminal_summary`
- `backend/tests/benchmarks/test_llm_eval.py` — add `TestBatchRecordAccuracy` class
- `backend/tests/benchmarks/scoring.py` — no change (keeps F-0058 signature untouched)

**Delete:**
- `backend/tests/integration/test_batch_record_import_llm.py` (superseded smoke test)
- `backend/tests/fixtures/sample_batch_record.pdf`
- `backend/tests/fixtures/sample_batch_record_extraction.json`
- `backend/tests/fixtures/batch_record_{perfect_match,wrong_protocol,half_complete,extra_steps}.pdf` and `_expected.json` (moved, not copied)

---

## Phase 0 — Fixture Migration

### Task 1: Create `document-to-run/` tree and migrate PDFs

**Files:**
- Create directory: `backend/tests/benchmarks/document-to-run/`
- Move: `backend/tests/fixtures/batch_record_*.pdf` → `document-to-run/0X-<name>/document.pdf`
- Move: `backend/tests/fixtures/batch_record_*_expected.json` → `document-to-run/0X-<name>/expected_extraction.json`

- [ ] **Step 1: Create directories**

```bash
mkdir -p backend/tests/benchmarks/document-to-run/01-perfect-match
mkdir -p backend/tests/benchmarks/document-to-run/02-wrong-protocol
mkdir -p backend/tests/benchmarks/document-to-run/03-half-complete
mkdir -p backend/tests/benchmarks/document-to-run/04-extra-steps
mkdir -p backend/tests/benchmarks/document-to-run/05-messy-scan
```

- [ ] **Step 2: Move PDFs and expected JSONs**

```bash
git mv backend/tests/fixtures/batch_record_perfect_match.pdf backend/tests/benchmarks/document-to-run/01-perfect-match/document.pdf
git mv backend/tests/fixtures/batch_record_perfect_match_expected.json backend/tests/benchmarks/document-to-run/01-perfect-match/expected_extraction.json

git mv backend/tests/fixtures/batch_record_wrong_protocol.pdf backend/tests/benchmarks/document-to-run/02-wrong-protocol/document.pdf
git mv backend/tests/fixtures/batch_record_wrong_protocol_expected.json backend/tests/benchmarks/document-to-run/02-wrong-protocol/expected_extraction.json

git mv backend/tests/fixtures/batch_record_half_complete.pdf backend/tests/benchmarks/document-to-run/03-half-complete/document.pdf
git mv backend/tests/fixtures/batch_record_half_complete_expected.json backend/tests/benchmarks/document-to-run/03-half-complete/expected_extraction.json

git mv backend/tests/fixtures/batch_record_extra_steps.pdf backend/tests/benchmarks/document-to-run/04-extra-steps/document.pdf
git mv backend/tests/fixtures/batch_record_extra_steps_expected.json backend/tests/benchmarks/document-to-run/04-extra-steps/expected_extraction.json
```

- [ ] **Step 3: Verify moves**

Run: `ls backend/tests/benchmarks/document-to-run/*/`
Expected: each of 01–04 shows `document.pdf` and `expected_extraction.json`. `05-messy-scan` is empty (populated in Task 18).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/
git commit -m "test(benchmark): migrate batch record fixtures to document-to-run/ [F-0057]"
```

---

## Phase 1 — Scoring Module Core (TDD)

### Task 2: Create scoring module skeleton with dataclasses

**Files:**
- Create: `backend/tests/benchmarks/batch_record_scoring.py`
- Create: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write the failing test for dataclass construction**

Create `backend/tests/unit/test_batch_record_scoring.py`:

```python
"""Unit tests for batch_record_scoring (no LLM required)."""

from tests.benchmarks.batch_record_scoring import (
    ExtractionScoreDetails,
    ExtractionScores,
    MappingScoreDetails,
    MappingScores,
)


def test_extraction_scores_defaults():
    s = ExtractionScores(fixture_name="01-perfect-match")
    assert s.overall == 0.0
    assert not s.passed


def test_extraction_scores_perfect():
    s = ExtractionScores(
        fixture_name="01-perfect-match",
        step_detection=1.0,
        param_extraction=1.0,
        timestamps=1.0,
        metadata=1.0,
        signatures_deviations=1.0,
        confidence_calibration=1.0,
    )
    assert s.overall == 1.0
    assert s.passed


def test_extraction_scores_weighted_sum():
    s = ExtractionScores(
        fixture_name="t",
        step_detection=1.0,
        param_extraction=1.0,
        timestamps=0.0,
        metadata=0.0,
        signatures_deviations=0.0,
        confidence_calibration=0.0,
    )
    # 0.25 + 0.25 = 0.5
    assert abs(s.overall - 0.5) < 1e-6
    assert not s.passed


def test_mapping_scores_weighted_sum():
    s = MappingScores(
        fixture_name="t",
        step_matching=1.0,
        param_field_matching=1.0,
        na_detection=0.0,
        extra_step_handling=0.0,
        mapping_confidence=0.0,
    )
    # 0.35 + 0.30 = 0.65
    assert abs(s.overall - 0.65) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.benchmarks.batch_record_scoring'`.

- [ ] **Step 3: Write minimal scoring module**

Create `backend/tests/benchmarks/batch_record_scoring.py`:

```python
"""Scoring utilities for batch record import benchmarks.

Compares an actual BatchRecordExtraction and StepMapping list against
expected fixture JSONs; produces per-dimension scores with detailed
breakdowns for debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractionScoreDetails:
    steps_expected: int = 0
    steps_found: int = 0
    steps_missed: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    param_value_mismatches: list[dict] = field(default_factory=list)
    param_unit_mismatches: list[dict] = field(default_factory=list)
    metadata_mismatches: list[dict] = field(default_factory=list)
    timestamps_missed: list[dict] = field(default_factory=list)
    signatures_missed: list[dict] = field(default_factory=list)
    deviations_missed: list[dict] = field(default_factory=list)
    confidence_correlation: float = 0.0


@dataclass
class ExtractionScores:
    fixture_name: str
    step_detection: float = 0.0          # 25%
    param_extraction: float = 0.0        # 25%
    timestamps: float = 0.0              # 15%
    metadata: float = 0.0                # 10%
    signatures_deviations: float = 0.0   # 15%
    confidence_calibration: float = 0.0  # 10%
    details: ExtractionScoreDetails = field(default_factory=ExtractionScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_detection * 0.25
            + self.param_extraction * 0.25
            + self.timestamps * 0.15
            + self.metadata * 0.10
            + self.signatures_deviations * 0.15
            + self.confidence_calibration * 0.10
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_detection": round(self.step_detection, 3),
            "param_extraction": round(self.param_extraction, 3),
            "timestamps": round(self.timestamps, 3),
            "metadata": round(self.metadata, 3),
            "signatures_deviations": round(self.signatures_deviations, 3),
            "confidence_calibration": round(self.confidence_calibration, 3),
            "details": {
                "steps_expected": self.details.steps_expected,
                "steps_found": self.details.steps_found,
                "steps_missed": self.details.steps_missed,
                "steps_extra": self.details.steps_extra,
                "param_value_mismatches": self.details.param_value_mismatches,
                "param_unit_mismatches": self.details.param_unit_mismatches,
                "metadata_mismatches": self.details.metadata_mismatches,
                "timestamps_missed": self.details.timestamps_missed,
                "signatures_missed": self.details.signatures_missed,
                "deviations_missed": self.details.deviations_missed,
                "confidence_correlation": round(
                    self.details.confidence_correlation, 3
                ),
            },
        }


@dataclass
class MappingScoreDetails:
    step_matching_misses: list[dict] = field(default_factory=list)
    param_field_matching_misses: list[dict] = field(default_factory=list)
    na_detection_misses: list[dict] = field(default_factory=list)
    extra_step_handling_misses: list[dict] = field(default_factory=list)


@dataclass
class MappingScores:
    fixture_name: str
    step_matching: float = 0.0           # 35%
    param_field_matching: float = 0.0    # 30%
    na_detection: float = 0.0            # 15%
    extra_step_handling: float = 0.0     # 10%
    mapping_confidence: float = 0.0      # 10%
    details: MappingScoreDetails = field(default_factory=MappingScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_matching * 0.35
            + self.param_field_matching * 0.30
            + self.na_detection * 0.15
            + self.extra_step_handling * 0.10
            + self.mapping_confidence * 0.10
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_matching": round(self.step_matching, 3),
            "param_field_matching": round(self.param_field_matching, 3),
            "na_detection": round(self.na_detection, 3),
            "extra_step_handling": round(self.extra_step_handling, 3),
            "mapping_confidence": round(self.mapping_confidence, 3),
            "details": {
                "step_matching_misses": self.details.step_matching_misses,
                "param_field_matching_misses": self.details.param_field_matching_misses,
                "na_detection_misses": self.details.na_detection_misses,
                "extra_step_handling_misses": self.details.extra_step_handling_misses,
            },
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): add batch record scoring dataclasses [F-0057]"
```

---

### Task 3: Implement fuzzy/numeric/unit helpers (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py` (add helpers)
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests for helpers**

Append to `backend/tests/unit/test_batch_record_scoring.py`:

```python
from tests.benchmarks.batch_record_scoring import (
    _fuzzy_match,
    _numeric_equal,
    _unit_equal,
)


def test_fuzzy_match_identical():
    assert _fuzzy_match("Buffer Preparation", "Buffer Preparation") == 1.0


def test_fuzzy_match_case_insensitive():
    assert _fuzzy_match("Buffer Prep", "buffer prep") == 1.0


def test_fuzzy_match_similar():
    # "Buffer Prep" vs "Buffer Preparation" should be a strong match
    assert _fuzzy_match("Buffer Prep", "Buffer Preparation") >= 0.7


def test_fuzzy_match_different():
    assert _fuzzy_match("Buffer Prep", "Centrifugation") < 0.5


def test_numeric_equal_exact():
    assert _numeric_equal(100.0, 100.0)


def test_numeric_equal_within_relative_tolerance():
    # 5% tolerance
    assert _numeric_equal(100.0, 104.9)
    assert _numeric_equal(100.0, 95.1)


def test_numeric_equal_outside_relative_tolerance():
    assert not _numeric_equal(100.0, 110.0)


def test_numeric_equal_small_values_absolute_tolerance():
    # pH 7.0 vs 7.01 should match (abs within 0.01)
    assert _numeric_equal(7.00, 7.01)
    # pH 7.0 vs 7.05 should NOT match (outside both tolerances)
    assert not _numeric_equal(7.00, 7.05)


def test_numeric_equal_zero():
    assert _numeric_equal(0.0, 0.0)
    assert not _numeric_equal(0.0, 0.5)


def test_unit_equal_synonyms():
    assert _unit_equal("°C", "C")
    assert _unit_equal("μm", "um")
    assert _unit_equal("mL", "ml")
    assert _unit_equal("micron", "um")


def test_unit_equal_mismatch():
    assert not _unit_equal("g", "mg")
    assert not _unit_equal("mL", "L")


def test_unit_equal_missing():
    # Both None/empty: equal
    assert _unit_equal(None, None)
    assert _unit_equal("", "")
    assert _unit_equal(None, "")
    # One side has a unit, the other doesn't: not equal
    assert not _unit_equal("mL", None)
    assert not _unit_equal(None, "mL")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: FAIL with import error for `_fuzzy_match`, `_numeric_equal`, `_unit_equal`.

- [ ] **Step 3: Implement the helpers**

Append to `backend/tests/benchmarks/batch_record_scoring.py`:

```python
from difflib import SequenceMatcher


_UNIT_SYNONYMS: dict[str, str] = {
    "°c": "c",
    "c": "c",
    "celsius": "c",
    "μm": "um",
    "um": "um",
    "micron": "um",
    "microns": "um",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "g": "g",
    "grams": "g",
    "mg": "mg",
    "milligrams": "mg",
    "psi": "psi",
    "bar": "bar",
    "rpm": "rpm",
    "min": "min",
    "minute": "min",
    "minutes": "min",
    "hr": "hr",
    "hour": "hr",
    "hours": "hr",
    "h": "hr",
}


def _fuzzy_match(a: str, b: str) -> float:
    """Case-insensitive fuzzy ratio in [0.0, 1.0]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _numeric_equal(a: float | int, b: float | int) -> bool:
    """±5% relative tolerance OR ±0.01 absolute tolerance."""
    try:
        af = float(a)
        bf = float(b)
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
    key = u.lower().strip()
    return _UNIT_SYNONYMS.get(key, key)


def _unit_equal(a: str | None, b: str | None) -> bool:
    na = _normalize_unit(a)
    nb = _normalize_unit(b)
    return na == nb
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all tests PASS (including 4 from Task 2 + new helper tests).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): add batch record scoring helpers [F-0057]"
```

---

### Task 4: Implement step alignment (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py` (add `_align_steps`)
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
from tests.benchmarks.batch_record_scoring import _align_steps


def test_align_steps_perfect_match():
    expected = [{"step_name": "A"}, {"step_name": "B"}]
    actual = [{"step_name": "A"}, {"step_name": "B"}]
    aligned = _align_steps(expected, actual)
    assert len(aligned) == 2
    assert aligned[0][0]["step_name"] == "A" and aligned[0][1]["step_name"] == "A"
    assert aligned[1][0]["step_name"] == "B" and aligned[1][1]["step_name"] == "B"


def test_align_steps_missing_expected():
    expected = [{"step_name": "A"}, {"step_name": "B"}]
    actual = [{"step_name": "A"}]
    aligned = _align_steps(expected, actual)
    assert len(aligned) == 2
    assert aligned[1][1] is None  # B has no actual match


def test_align_steps_fuzzy_match():
    expected = [{"step_name": "Buffer Preparation"}]
    actual = [{"step_name": "Buffer Prep"}]
    aligned = _align_steps(expected, actual)
    assert aligned[0][1] is not None


def test_align_steps_no_match_below_threshold():
    expected = [{"step_name": "Filtration"}]
    actual = [{"step_name": "Incubation"}]
    aligned = _align_steps(expected, actual)
    assert aligned[0][1] is None


def test_align_steps_greedy_ambiguous():
    # Two expected fuzzy-matching one actual — first expected wins
    expected = [{"step_name": "Buffer Prep"}, {"step_name": "Buffer Preparation"}]
    actual = [{"step_name": "Buffer Prep"}]
    aligned = _align_steps(expected, actual)
    assert aligned[0][1] is not None  # first wins
    assert aligned[1][1] is None      # second is missed
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: FAIL with import error for `_align_steps`.

- [ ] **Step 3: Implement `_align_steps`**

Append to `batch_record_scoring.py`:

```python
_STEP_MATCH_THRESHOLD = 0.7


def _align_steps(
    expected: list[dict],
    actual: list[dict],
) -> list[tuple[dict, dict | None]]:
    """Greedy best-match by fuzzy step_name similarity.

    Returns (expected_step, matched_actual_or_None) pairs in expected order.
    """
    remaining = list(actual)
    out: list[tuple[dict, dict | None]] = []
    for exp in expected:
        exp_name = exp.get("step_name", "")
        best = None
        best_ratio = 0.0
        for act in remaining:
            ratio = _fuzzy_match(exp_name, act.get("step_name", ""))
            if ratio > best_ratio:
                best_ratio = ratio
                best = act
        if best is not None and best_ratio >= _STEP_MATCH_THRESHOLD:
            out.append((exp, best))
            remaining.remove(best)
        else:
            out.append((exp, None))
    return out
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): add step alignment for batch record scoring [F-0057]"
```

---

## Phase 2 — Extraction Scoring (TDD per dimension)

### Task 5: `score_extraction` — step_detection dimension (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
from app.services.batch_record_extractor import (
    BatchRecordExtraction,
    ExtractedStep,
)
from tests.benchmarks.batch_record_scoring import score_extraction


def _make_extraction(steps: list[dict]) -> BatchRecordExtraction:
    return BatchRecordExtraction(
        steps=[
            ExtractedStep(step_name=s["step_name"], confidence=s.get("confidence", 0.9))
            for s in steps
        ],
        overall_confidence=0.9,
    )


def test_score_extraction_step_detection_perfect():
    actual = _make_extraction([{"step_name": "A"}, {"step_name": "B"}])
    expected = {"steps": [{"step_name": "A"}, {"step_name": "B"}]}
    scores = score_extraction(actual, expected, "t")
    assert scores.step_detection == 1.0
    assert scores.details.steps_expected == 2
    assert scores.details.steps_found == 2
    assert scores.details.steps_missed == []


def test_score_extraction_step_detection_missed():
    actual = _make_extraction([{"step_name": "A"}])
    expected = {"steps": [{"step_name": "A"}, {"step_name": "B"}]}
    scores = score_extraction(actual, expected, "t")
    # recall 0.5, precision 1.0 -> F1 = 2*1*0.5/(1+0.5) = 0.667
    assert 0.65 < scores.step_detection < 0.7
    assert scores.details.steps_missed == ["B"]


def test_score_extraction_step_detection_extra():
    actual = _make_extraction([{"step_name": "A"}, {"step_name": "C"}])
    expected = {"steps": [{"step_name": "A"}]}
    scores = score_extraction(actual, expected, "t")
    # recall 1.0, precision 0.5 -> F1 = 0.667
    assert 0.65 < scores.step_detection < 0.7
    assert "C" in scores.details.steps_extra
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: FAIL with import error for `score_extraction`.

- [ ] **Step 3: Implement `score_extraction` skeleton with step_detection only**

Append to `batch_record_scoring.py`:

```python
from app.services.batch_record_extractor import BatchRecordExtraction


def score_extraction(
    actual: BatchRecordExtraction,
    expected: dict,
    fixture_name: str = "",
) -> ExtractionScores:
    """Score a BatchRecordExtraction against expected_extraction.json."""
    scores = ExtractionScores(fixture_name=fixture_name)
    d = scores.details

    expected_steps = expected.get("steps", [])
    actual_steps_raw = [s.model_dump() for s in actual.steps]

    d.steps_expected = len(expected_steps)
    d.steps_found = len(actual_steps_raw)

    # ── 1. step_detection (F1 on step_name fuzzy match) ──
    aligned = _align_steps(expected_steps, actual_steps_raw)
    matched_expected = [e for e, a in aligned if a is not None]
    d.steps_missed = [
        e.get("step_name", "?") for e, a in aligned if a is None
    ]
    matched_actual_names = {
        a.get("step_name", "") for _, a in aligned if a is not None
    }
    d.steps_extra = [
        s.get("step_name", "?") for s in actual_steps_raw
        if s.get("step_name", "") not in matched_actual_names
    ]

    recall = (
        len(matched_expected) / len(expected_steps)
        if expected_steps else 1.0
    )
    precision = (
        len(matched_expected) / len(actual_steps_raw)
        if actual_steps_raw else (1.0 if not expected_steps else 0.0)
    )
    scores.step_detection = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0 else 0.0
    )

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass (step_detection tests + prior dataclass/helper tests).

- [ ] **Step 5: Commit**

```bash
git add -p backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score step_detection dimension [F-0057]"
```

---

### Task 6: `score_extraction` — param_extraction (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
from app.services.batch_record_extractor import ExtractedParameterValue


def _make_extraction_with_params(steps_data: list[dict]) -> BatchRecordExtraction:
    steps = []
    for s in steps_data:
        params = [
            ExtractedParameterValue(
                field_label=p["field_label"],
                value=p["value"],
                unit=p.get("unit"),
                confidence=p.get("confidence", 0.9),
            )
            for p in s.get("parameters", [])
        ]
        steps.append(ExtractedStep(
            step_name=s["step_name"],
            parameters=params,
            confidence=s.get("confidence", 0.9),
        ))
    return BatchRecordExtraction(steps=steps, overall_confidence=0.9)


def test_score_extraction_params_perfect():
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [
            {"field_label": "pH", "value": 7.2, "unit": None},
            {"field_label": "Volume", "value": 500, "unit": "mL"},
        ],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [
            {"field_label": "pH", "value": 7.2, "unit": None},
            {"field_label": "Volume", "value": 500, "unit": "mL"},
        ],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.param_extraction == 1.0


def test_score_extraction_params_wrong_value():
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "pH", "value": 8.0, "unit": None}],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "pH", "value": 7.2, "unit": None}],
    }]}
    scores = score_extraction(actual, expected, "t")
    # label matches (1/3), value wrong (0/3), unit matches (1/3) -> 2/3
    assert abs(scores.param_extraction - 2/3) < 1e-6
    assert scores.details.param_value_mismatches


def test_score_extraction_params_wrong_unit():
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "Volume", "value": 500, "unit": "L"}],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "Volume", "value": 500, "unit": "mL"}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert abs(scores.param_extraction - 2/3) < 1e-6
    assert scores.details.param_unit_mismatches


def test_score_extraction_params_synonym_unit():
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "Temp", "value": 25, "unit": "C"}],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "Temp", "value": 25, "unit": "°C"}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.param_extraction == 1.0
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v -k params
```

Expected: param tests FAIL (param_extraction stays 0.0).

- [ ] **Step 3: Implement param_extraction**

Replace the `return scores` line at the bottom of `score_extraction` with:

```python
    # ── 2. param_extraction (per step: label match + value match + unit match) ──
    param_total_points = 0.0
    param_max_points = 0.0
    for exp, act in aligned:
        if act is None:
            # Count expected params as missed
            for exp_p in exp.get("parameters", []):
                param_max_points += 3
                d.param_value_mismatches.append({
                    "step": exp.get("step_name", "?"),
                    "param": exp_p.get("field_label", "?"),
                    "expected": exp_p.get("value"),
                    "actual": None,
                })
            continue
        exp_params = exp.get("parameters", [])
        act_params = list(act.get("parameters", []))
        for exp_p in exp_params:
            param_max_points += 3
            # Find best fuzzy-match on field_label
            best_act = None
            best_ratio = 0.0
            for ap in act_params:
                ratio = _fuzzy_match(
                    exp_p.get("field_label", ""),
                    ap.get("field_label", ""),
                )
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_act = ap
            if best_act is None or best_ratio < 0.7:
                d.param_value_mismatches.append({
                    "step": exp.get("step_name", "?"),
                    "param": exp_p.get("field_label", "?"),
                    "expected": exp_p.get("value"),
                    "actual": None,
                })
                continue
            # Label matched (1 point)
            param_total_points += 1
            act_params.remove(best_act)
            # Value check (1 point)
            if _numeric_equal(exp_p.get("value"), best_act.get("value")):
                param_total_points += 1
            else:
                d.param_value_mismatches.append({
                    "step": exp.get("step_name", "?"),
                    "param": exp_p.get("field_label", "?"),
                    "expected": exp_p.get("value"),
                    "actual": best_act.get("value"),
                })
            # Unit check (1 point)
            if _unit_equal(exp_p.get("unit"), best_act.get("unit")):
                param_total_points += 1
            else:
                d.param_unit_mismatches.append({
                    "step": exp.get("step_name", "?"),
                    "param": exp_p.get("field_label", "?"),
                    "expected_unit": exp_p.get("unit"),
                    "actual_unit": best_act.get("unit"),
                })

    scores.param_extraction = (
        param_total_points / param_max_points
        if param_max_points > 0 else 1.0
    )

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -p backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score param_extraction dimension [F-0057]"
```

---

### Task 7: `score_extraction` — metadata + timestamps (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.batch_record_extractor import ExtractedTimestamp


def test_score_extraction_metadata_perfect():
    actual = BatchRecordExtraction(
        document_title="Batch Record LOT-2026-100",
        batch_id="LOT-2026-100",
        product_name="mAb-X",
        date="2026-03-10",
        steps=[],
        overall_confidence=0.9,
    )
    expected = {
        "document_title": "Batch Record LOT-2026-100",
        "batch_id": "LOT-2026-100",
        "product_name": "mAb-X",
        "date": "2026-03-10",
        "steps": [],
    }
    scores = score_extraction(actual, expected, "t")
    assert scores.metadata == 1.0


def test_score_extraction_metadata_partial():
    actual = BatchRecordExtraction(
        document_title="",
        batch_id="LOT-2026-100",
        product_name="mAb-X",
        date="",
        steps=[],
        overall_confidence=0.9,
    )
    expected = {
        "document_title": "Batch Record LOT-2026-100",
        "batch_id": "LOT-2026-100",
        "product_name": "mAb-X",
        "date": "2026-03-10",
        "steps": [],
    }
    scores = score_extraction(actual, expected, "t")
    # 2 of 4 metadata fields matched
    assert scores.metadata == 0.5


def test_score_extraction_timestamps_match():
    actual = BatchRecordExtraction(
        steps=[ExtractedStep(
            step_name="Buffer Prep",
            timestamps=[ExtractedTimestamp(
                value="08:30", label="Start Time", confidence=0.9,
            )],
            confidence=0.9,
        )],
        overall_confidence=0.9,
    )
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "timestamps": [{"value": "08:30", "label": "Start Time"}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.timestamps == 1.0


def test_score_extraction_timestamps_missing():
    actual = BatchRecordExtraction(
        steps=[ExtractedStep(
            step_name="Buffer Prep", timestamps=[], confidence=0.9,
        )],
        overall_confidence=0.9,
    )
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "timestamps": [{"value": "08:30", "label": "Start Time"}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.timestamps == 0.0
    assert scores.details.timestamps_missed


def test_score_extraction_timestamps_absent_expected_scores_full():
    # No timestamps expected anywhere: dimension is N/A, score 1.0
    actual = BatchRecordExtraction(
        steps=[ExtractedStep(
            step_name="Buffer Prep", timestamps=[], confidence=0.9,
        )],
        overall_confidence=0.9,
    )
    expected = {"steps": [{"step_name": "Buffer Prep"}]}
    scores = score_extraction(actual, expected, "t")
    assert scores.timestamps == 1.0
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v -k "metadata or timestamps"
```

Expected: FAIL (metadata/timestamps stay 0.0 or 1.0 by default).

- [ ] **Step 3: Implement metadata + timestamps scoring**

In `score_extraction` before `return scores`, insert:

```python
    # ── 3. metadata (4 fields, each 0.25) ──
    meta_fields = ("document_title", "batch_id", "product_name", "date")
    meta_total = 0
    meta_matched = 0
    for f in meta_fields:
        exp_val = expected.get(f)
        act_val = getattr(actual, f, None)
        if exp_val is None or exp_val == "":
            continue
        meta_total += 1
        if act_val and _fuzzy_match(str(exp_val), str(act_val)) >= 0.8:
            meta_matched += 1
        else:
            d.metadata_mismatches.append({
                "field": f, "expected": exp_val, "actual": act_val,
            })
    scores.metadata = meta_matched / meta_total if meta_total > 0 else 1.0

    # ── 4. timestamps (F1 on (step, label, value) tuples) ──
    expected_ts: list[tuple[str, str, str]] = []
    for e in expected_steps:
        for t in e.get("timestamps", []) or []:
            expected_ts.append((
                e.get("step_name", ""),
                t.get("label", ""),
                t.get("value", ""),
            ))
    actual_ts: list[tuple[str, str, str]] = []
    for s in actual.steps:
        for t in s.timestamps:
            actual_ts.append((s.step_name, t.label, t.value))

    if not expected_ts and not actual_ts:
        scores.timestamps = 1.0
    elif not expected_ts:
        scores.timestamps = 0.0  # unexpected timestamps hallucinated
    else:
        matched = 0
        remaining_actual = list(actual_ts)
        for step, label, val in expected_ts:
            best = None
            best_ratio = 0.0
            for act in remaining_actual:
                r = (
                    _fuzzy_match(step, act[0]) * 0.5
                    + _fuzzy_match(label, act[1]) * 0.25
                    + _fuzzy_match(val, act[2]) * 0.25
                )
                if r > best_ratio:
                    best_ratio = r
                    best = act
            if best is not None and best_ratio >= 0.7:
                matched += 1
                remaining_actual.remove(best)
            else:
                d.timestamps_missed.append({
                    "step": step, "label": label, "value": val,
                })
        recall = matched / len(expected_ts)
        precision = (
            matched / len(actual_ts) if actual_ts
            else (1.0 if not expected_ts else 0.0)
        )
        scores.timestamps = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0.0
        )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -p backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score metadata and timestamps dimensions [F-0057]"
```

---

### Task 8: `score_extraction` — signatures_deviations + confidence_calibration (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.batch_record_extractor import (
    ExtractedDeviation,
    ExtractedSignature,
)


def test_score_extraction_signatures_match():
    actual = BatchRecordExtraction(
        steps=[ExtractedStep(
            step_name="Buffer Prep",
            signatures=[ExtractedSignature(
                initials_or_name="JKL", role="Operator", confidence=0.9,
            )],
            confidence=0.9,
        )],
        overall_confidence=0.9,
    )
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "signatures": [{"initials_or_name": "JKL", "role": "Operator"}],
        "deviations": [],
    }]}
    scores = score_extraction(actual, expected, "t")
    # No deviations expected; dimension = signatures F1 only
    assert scores.signatures_deviations == 1.0


def test_score_extraction_deviations_missed():
    actual = BatchRecordExtraction(
        steps=[ExtractedStep(
            step_name="Buffer Prep", deviations=[], confidence=0.9,
        )],
        overall_confidence=0.9,
    )
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "signatures": [],
        "deviations": [{"description": "Temperature spike during mix"}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.signatures_deviations == 0.0


def test_score_extraction_confidence_calibration_well_calibrated():
    # High confidence + correct value = good calibration
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [
            {"field_label": "pH", "value": 7.2, "unit": None, "confidence": 0.95},
        ],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "pH", "value": 7.2, "unit": None}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.confidence_calibration >= 0.9


def test_score_extraction_confidence_calibration_overconfident():
    # High confidence + wrong value = poor calibration
    actual = _make_extraction_with_params([{
        "step_name": "Buffer Prep",
        "parameters": [
            {"field_label": "pH", "value": 9.0, "unit": None, "confidence": 0.95},
        ],
    }])
    expected = {"steps": [{
        "step_name": "Buffer Prep",
        "parameters": [{"field_label": "pH", "value": 7.2, "unit": None}],
    }]}
    scores = score_extraction(actual, expected, "t")
    assert scores.confidence_calibration < 0.5
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v -k "signatures or deviations or calibration"
```

Expected: FAIL.

- [ ] **Step 3: Implement signatures_deviations + confidence_calibration**

In `score_extraction` before `return scores`, insert:

```python
    # ── 5. signatures_deviations (average of two F1 sub-scores, N/A if absent) ──
    def _f1_tuples(
        expected_list: list[tuple], actual_list: list[tuple],
        threshold: float = 0.7,
    ) -> tuple[float, list]:
        """F1 over tuple-of-strings matched fuzzily. Returns (f1, missed_list)."""
        if not expected_list and not actual_list:
            return 1.0, []
        if not expected_list:
            return 0.0, []
        remaining = list(actual_list)
        matched = 0
        missed: list = []
        for exp in expected_list:
            best = None
            best_ratio = 0.0
            for act in remaining:
                r = sum(_fuzzy_match(e, a) for e, a in zip(exp, act)) / len(exp)
                if r > best_ratio:
                    best_ratio = r
                    best = act
            if best is not None and best_ratio >= threshold:
                matched += 1
                remaining.remove(best)
            else:
                missed.append(exp)
        recall = matched / len(expected_list)
        precision = (
            matched / len(actual_list) if actual_list
            else (1.0 if not expected_list else 0.0)
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0.0
        )
        return f1, missed

    exp_sigs: list[tuple[str, str]] = []
    exp_devs: list[tuple[str]] = []
    for e in expected_steps:
        for s in e.get("signatures", []) or []:
            exp_sigs.append((
                s.get("initials_or_name", ""),
                s.get("role", "") or "",
            ))
        for dv in e.get("deviations", []) or []:
            exp_devs.append((dv.get("description", ""),))

    act_sigs: list[tuple[str, str]] = []
    act_devs: list[tuple[str]] = []
    for s in actual.steps:
        for sig in s.signatures:
            act_sigs.append((sig.initials_or_name, sig.role or ""))
        for dv in s.deviations:
            act_devs.append((dv.description,))

    sub_scores: list[float] = []
    if exp_sigs or act_sigs:
        f1, missed = _f1_tuples(exp_sigs, act_sigs)
        sub_scores.append(f1)
        d.signatures_missed.extend([
            {"initials_or_name": m[0], "role": m[1]} for m in missed
        ])
    if exp_devs or act_devs:
        f1, missed = _f1_tuples(exp_devs, act_devs, threshold=0.6)
        sub_scores.append(f1)
        d.deviations_missed.extend([{"description": m[0]} for m in missed])

    scores.signatures_deviations = (
        sum(sub_scores) / len(sub_scores) if sub_scores else 1.0
    )

    # ── 6. confidence_calibration (bucket correctness rate) ──
    # Collect all expected/actual param pairs we've already aligned
    buckets: dict[str, list[bool]] = {"high": [], "mid": [], "low": []}
    for exp, act in aligned:
        if act is None:
            continue
        exp_params = exp.get("parameters", []) or []
        act_params = list(act.get("parameters", []) or [])
        for exp_p in exp_params:
            best = None
            best_ratio = 0.0
            for ap in act_params:
                r = _fuzzy_match(
                    exp_p.get("field_label", ""),
                    ap.get("field_label", ""),
                )
                if r > best_ratio:
                    best_ratio = r
                    best = ap
            if best is None or best_ratio < 0.7:
                continue
            conf = best.get("confidence", 0.0)
            correct = _numeric_equal(
                exp_p.get("value"), best.get("value")
            ) and _unit_equal(exp_p.get("unit"), best.get("unit"))
            if conf >= 0.9:
                buckets["high"].append(correct)
            elif conf >= 0.6:
                buckets["mid"].append(correct)
            else:
                buckets["low"].append(correct)

    # Expectations: high bucket ≥0.9 correct, mid ≥0.6, low unconstrained
    bucket_results: list[float] = []
    if buckets["high"]:
        rate = sum(buckets["high"]) / len(buckets["high"])
        bucket_results.append(min(1.0, rate / 0.9))
    if buckets["mid"]:
        rate = sum(buckets["mid"]) / len(buckets["mid"])
        bucket_results.append(min(1.0, rate / 0.6))
    if buckets["low"]:
        rate = sum(buckets["low"]) / len(buckets["low"])
        # Should NOT exceed 0.8 correct — overconfident-calling-wrong-cases-as-low
        bucket_results.append(1.0 if rate <= 0.8 else 0.8 / rate)

    scores.confidence_calibration = (
        sum(bucket_results) / len(bucket_results)
        if bucket_results else 1.0
    )
    d.confidence_correlation = scores.confidence_calibration

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass. If `test_score_extraction_confidence_calibration_overconfident` fails (overconfident case scoring too high), check that the high-bucket rate (0/1 = 0) divided by 0.9 gives 0 — should drag the score below 0.5.

- [ ] **Step 5: Commit**

```bash
git add -p backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score signatures_deviations and confidence dimensions [F-0057]"
```

---

## Phase 3 — Mapping Scoring (TDD)

### Task 9: `score_mapping` — step_matching + param_field_matching (TDD)

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.batch_record_extractor import ParamMapping, StepMapping
from tests.benchmarks.batch_record_scoring import score_mapping


def _mk_mapping(
    extracted_idx: int, extracted_name: str,
    protocol_id: str, protocol_name: str,
    score: float = 0.95,
    param_pairs: list[tuple[str, str]] | None = None,
) -> StepMapping:
    param_mappings = []
    for i, (label, key) in enumerate(param_pairs or []):
        param_mappings.append(ParamMapping(
            extracted_param_index=i,
            extracted_label=label,
            extracted_value=None,
            schema_field_key=key,
            schema_field_label=key,
            confidence=0.9,
        ))
    return StepMapping(
        extracted_step_index=extracted_idx,
        extracted_step_name=extracted_name,
        protocol_step_id=protocol_id,
        protocol_step_name=protocol_name,
        score=score,
        param_mappings=param_mappings,
    )


def test_score_mapping_perfect_step_match():
    actual = [_mk_mapping(0, "Buffer Prep", "node-buf", "Buffer Prep")]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.step_matching == 1.0


def test_score_mapping_wrong_step_match():
    actual = [_mk_mapping(0, "Buffer Prep", "node-cent", "Centrifugation")]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.step_matching == 0.0
    assert scores.details.step_matching_misses


def test_score_mapping_perfect_param_fields():
    actual = [_mk_mapping(
        0, "Buffer Prep", "node-buf", "Buffer Prep",
        param_pairs=[("pH", "ph_value"), ("Volume", "volume_ml")],
    )]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [
                {"extracted_label": "pH", "schema_field_key": "ph_value"},
                {"extracted_label": "Volume", "schema_field_key": "volume_ml"},
            ],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.param_field_matching == 1.0


def test_score_mapping_one_wrong_param_field():
    actual = [_mk_mapping(
        0, "Buffer Prep", "node-buf", "Buffer Prep",
        param_pairs=[("pH", "WRONG_KEY"), ("Volume", "volume_ml")],
    )]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [
                {"extracted_label": "pH", "schema_field_key": "ph_value"},
                {"extracted_label": "Volume", "schema_field_key": "volume_ml"},
            ],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.param_field_matching == 0.5
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v -k "score_mapping"
```

Expected: FAIL with import error for `score_mapping`.

- [ ] **Step 3: Implement `score_mapping`**

Append to `batch_record_scoring.py`:

```python
from app.services.batch_record_extractor import StepMapping


def score_mapping(
    actual: list[StepMapping],
    expected: dict,
    fixture_name: str = "",
) -> MappingScores:
    """Score list[StepMapping] against expected_mapping.json."""
    scores = MappingScores(fixture_name=fixture_name)
    d = scores.details

    expected_mappings: list[dict] = expected.get("step_mappings", [])
    expected_unmapped_proto: list[str] = expected.get(
        "unmapped_protocol_steps", []
    )
    expected_unmapped_ext: list[str] = expected.get(
        "unmapped_extracted_steps", []
    )

    actual_by_name = {m.extracted_step_name: m for m in actual}

    # ── 1. step_matching (of expected mapped, fraction correct) ──
    step_correct = 0
    step_total = 0
    for exp_m in expected_mappings:
        if not exp_m.get("mapped", True):
            continue
        step_total += 1
        ext_name = exp_m["extracted_step_name"]
        # Find actual mapping by fuzzy match on extracted_step_name
        best = None
        best_r = 0.0
        for a in actual:
            r = _fuzzy_match(ext_name, a.extracted_step_name)
            if r > best_r:
                best_r = r
                best = a
        if best is None or best_r < 0.7:
            d.step_matching_misses.append({
                "extracted_step_name": ext_name,
                "expected_protocol_step": exp_m["protocol_step_name"],
                "actual_protocol_step": None,
            })
            continue
        if _fuzzy_match(
            best.protocol_step_name, exp_m["protocol_step_name"]
        ) >= 0.85:
            step_correct += 1
        else:
            d.step_matching_misses.append({
                "extracted_step_name": ext_name,
                "expected_protocol_step": exp_m["protocol_step_name"],
                "actual_protocol_step": best.protocol_step_name,
            })
    scores.step_matching = (
        step_correct / step_total if step_total > 0 else 1.0
    )

    # ── 2. param_field_matching (over correctly-mapped steps) ──
    pf_correct = 0
    pf_total = 0
    for exp_m in expected_mappings:
        if not exp_m.get("mapped", True):
            continue
        ext_name = exp_m["extracted_step_name"]
        act = None
        for a in actual:
            if _fuzzy_match(ext_name, a.extracted_step_name) >= 0.7:
                act = a
                break
        if act is None:
            continue
        # Only score param fields if the step was correctly matched
        if _fuzzy_match(
            act.protocol_step_name, exp_m["protocol_step_name"]
        ) < 0.85:
            continue
        for exp_p in exp_m.get("param_mappings", []):
            pf_total += 1
            ext_label = exp_p["extracted_label"]
            expected_key = exp_p["schema_field_key"]
            best_pm = None
            best_r = 0.0
            for pm in act.param_mappings:
                r = _fuzzy_match(ext_label, pm.extracted_label)
                if r > best_r:
                    best_r = r
                    best_pm = pm
            if (
                best_pm is not None and best_r >= 0.7
                and best_pm.schema_field_key == expected_key
            ):
                pf_correct += 1
            else:
                d.param_field_matching_misses.append({
                    "step": exp_m["protocol_step_name"],
                    "extracted_label": ext_label,
                    "expected_key": expected_key,
                    "actual_key": (
                        best_pm.schema_field_key if best_pm else None
                    ),
                })
    scores.param_field_matching = (
        pf_correct / pf_total if pf_total > 0 else 1.0
    )

    # ── 3. na_detection (expected unmapped protocol steps left unmapped) ──
    mapped_protocol_names = {a.protocol_step_name for a in actual}
    if expected_unmapped_proto:
        correct_na = 0
        for name in expected_unmapped_proto:
            if not any(
                _fuzzy_match(name, mp) >= 0.85
                for mp in mapped_protocol_names
            ):
                correct_na += 1
            else:
                d.na_detection_misses.append({
                    "protocol_step": name,
                    "should_be": "unmapped",
                    "actual": "mapped",
                })
        scores.na_detection = correct_na / len(expected_unmapped_proto)
    else:
        scores.na_detection = 1.0

    # ── 4. extra_step_handling (expected unmapped extracted steps absent) ──
    actual_mapped_extracted = {a.extracted_step_name for a in actual}
    if expected_unmapped_ext:
        correct_extra = 0
        for name in expected_unmapped_ext:
            if not any(
                _fuzzy_match(name, e) >= 0.85
                for e in actual_mapped_extracted
            ):
                correct_extra += 1
            else:
                d.extra_step_handling_misses.append({
                    "extracted_step": name,
                    "should_be": "unmapped",
                    "actual": "mapped",
                })
        scores.extra_step_handling = (
            correct_extra / len(expected_unmapped_ext)
        )
    else:
        scores.extra_step_handling = 1.0

    # ── 5. mapping_confidence (score correlation with correctness) ──
    # For each actual StepMapping, correct if protocol_step_name fuzzy-matches
    # the expected mapping for that extracted step.
    expected_by_ext = {
        m["extracted_step_name"]: m for m in expected_mappings
    }
    conf_items: list[tuple[float, bool]] = []
    for a in actual:
        exp_m = expected_by_ext.get(a.extracted_step_name)
        # Also try fuzzy if exact name match fails
        if exp_m is None:
            for k, v in expected_by_ext.items():
                if _fuzzy_match(a.extracted_step_name, k) >= 0.85:
                    exp_m = v
                    break
        if exp_m is None:
            # Actual step not in expected mappings — if it's in the
            # unmapped-extracted list, the mapping is wrong regardless of score
            correct = False
        else:
            correct = (
                _fuzzy_match(
                    a.protocol_step_name, exp_m["protocol_step_name"]
                ) >= 0.85
            )
        conf_items.append((a.score, correct))

    if conf_items:
        correlation_points = 0
        for score_val, correct in conf_items:
            if correct and score_val >= 0.8:
                correlation_points += 1
            elif not correct and score_val <= 0.5:
                correlation_points += 1
            elif correct and score_val >= 0.5:
                correlation_points += 0.5  # partial credit
        scores.mapping_confidence = correlation_points / len(conf_items)
    else:
        scores.mapping_confidence = 1.0

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -p backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): score mapping dimensions [F-0057]"
```

---

### Task 10: `score_mapping` — na_detection + extra_step_handling edge cases (TDD)

**Files:**
- Modify: `backend/tests/unit/test_batch_record_scoring.py`

(Implementation already in place from Task 9; this task just adds the tests.)

- [ ] **Step 1: Write edge case tests**

Append:

```python
def test_score_mapping_na_detection_correct():
    # No extracted step maps to "Final QC" — correctly left N/A
    actual = [_mk_mapping(0, "Buffer Prep", "node-buf", "Buffer Prep")]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": ["Final QC"],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.na_detection == 1.0


def test_score_mapping_na_detection_wrong():
    # Actual mapping incorrectly includes Final QC
    actual = [
        _mk_mapping(0, "Buffer Prep", "node-buf", "Buffer Prep"),
        _mk_mapping(1, "Something", "node-qc", "Final QC"),
    ]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": ["Final QC"],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.na_detection == 0.0
    assert scores.details.na_detection_misses


def test_score_mapping_extra_step_handling_correct():
    # Extra step in document is correctly NOT mapped
    actual = [_mk_mapping(0, "Buffer Prep", "node-buf", "Buffer Prep")]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": ["Handwritten Extra Note"],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.extra_step_handling == 1.0


def test_score_mapping_mapping_confidence_high_and_correct():
    actual = [_mk_mapping(
        0, "Buffer Prep", "node-buf", "Buffer Prep", score=0.95,
    )]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    assert scores.mapping_confidence == 1.0


def test_score_mapping_mapping_confidence_high_but_wrong():
    actual = [_mk_mapping(
        0, "Buffer Prep", "node-cent", "Centrifugation", score=0.95,
    )]
    expected = {
        "step_mappings": [{
            "extracted_step_name": "Buffer Prep",
            "protocol_step_name": "Buffer Prep",
            "mapped": True,
            "param_mappings": [],
        }],
        "unmapped_protocol_steps": [],
        "unmapped_extracted_steps": [],
    }
    scores = score_mapping(actual, expected, "t")
    # High-confidence wrong mapping → 0 correlation points
    assert scores.mapping_confidence == 0.0
```

- [ ] **Step 2: Run tests**

```bash
cd backend && pytest tests/unit/test_batch_record_scoring.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add -p backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): add edge-case tests for mapping dimensions [F-0057]"
```

---

### Task 11: Print helpers for benchmark reports

**Files:**
- Modify: `backend/tests/benchmarks/batch_record_scoring.py`

- [ ] **Step 1: Append print helpers**

```python
import json


def print_extraction_report(scores: ExtractionScores) -> None:
    status = "PASS" if scores.passed else "FAIL"
    d = scores.details
    print()
    print(f"{'=' * 65}")
    print(f"  [EXTRACTION] {scores.fixture_name:<35} {status} {scores.overall:.0%}")
    print(f"{'=' * 65}")
    print(f"  {'Dimension':<26} {'Score':>6}  Detail")
    print(f"  {'-' * 60}")
    print(
        f"  {'Step Detection':<26} {scores.step_detection:>5.2f}  "
        f"{d.steps_found}/{d.steps_expected} found, "
        f"{len(d.steps_extra)} extra"
    )
    print(
        f"  {'Param Extraction':<26} {scores.param_extraction:>5.2f}  "
        f"{len(d.param_value_mismatches)} val miss, "
        f"{len(d.param_unit_mismatches)} unit miss"
    )
    print(
        f"  {'Timestamps':<26} {scores.timestamps:>5.2f}  "
        f"{len(d.timestamps_missed)} missed"
    )
    print(
        f"  {'Metadata':<26} {scores.metadata:>5.2f}  "
        f"{len(d.metadata_mismatches)} mismatches"
    )
    print(
        f"  {'Signatures/Deviations':<26} {scores.signatures_deviations:>5.2f}  "
        f"sig_miss={len(d.signatures_missed)}, dev_miss={len(d.deviations_missed)}"
    )
    print(
        f"  {'Confidence Calibration':<26} {scores.confidence_calibration:>5.2f}"
    )
    print(f"  {'-' * 60}")
    print(f"  {'Overall (weighted)':<26} {scores.overall:>5.2f}  threshold: 0.75")
    print(f"{'=' * 65}")
    if d.steps_missed:
        print(f"  Steps missed: {d.steps_missed}")
    if d.param_value_mismatches:
        print(f"  Param value mismatches:")
        print(f"    {json.dumps(d.param_value_mismatches[:5], indent=4)}")
    print()


def print_mapping_report(scores: MappingScores) -> None:
    status = "PASS" if scores.passed else "FAIL"
    d = scores.details
    print()
    print(f"{'=' * 65}")
    print(f"  [MAPPING] {scores.fixture_name:<38} {status} {scores.overall:.0%}")
    print(f"{'=' * 65}")
    print(f"  {'Dimension':<26} {'Score':>6}  Detail")
    print(f"  {'-' * 60}")
    print(
        f"  {'Step Matching':<26} {scores.step_matching:>5.2f}  "
        f"{len(d.step_matching_misses)} misses"
    )
    print(
        f"  {'Param Field Matching':<26} {scores.param_field_matching:>5.2f}  "
        f"{len(d.param_field_matching_misses)} misses"
    )
    print(
        f"  {'N/A Detection':<26} {scores.na_detection:>5.2f}  "
        f"{len(d.na_detection_misses)} misses"
    )
    print(
        f"  {'Extra Step Handling':<26} {scores.extra_step_handling:>5.2f}  "
        f"{len(d.extra_step_handling_misses)} misses"
    )
    print(f"  {'Mapping Confidence':<26} {scores.mapping_confidence:>5.2f}")
    print(f"  {'-' * 60}")
    print(f"  {'Overall (weighted)':<26} {scores.overall:>5.2f}  threshold: 0.75")
    print(f"{'=' * 65}")
    print()


def print_batch_record_summary(
    extraction_scores: list[ExtractionScores],
    mapping_scores: list[MappingScores],
) -> None:
    """Print aggregate summary for batch record benchmark."""
    if extraction_scores:
        print()
        print(f"{'=' * 85}")
        print(f"  BATCH RECORD EXTRACTION SUMMARY")
        print(f"{'=' * 85}")
        print(
            f"  {'Fixture':<30} {'Overall':>7} {'Steps':>7} {'Param':>7} "
            f"{'Times':>7} {'Meta':>7} {'Sig/Dev':>8} {'Conf':>7} {'Status':>7}"
        )
        print(f"  {'-' * 80}")
        for s in extraction_scores:
            st = "PASS" if s.passed else "FAIL"
            print(
                f"  {s.fixture_name:<30} {s.overall:>6.0%} "
                f"{s.step_detection:>6.0%} {s.param_extraction:>6.0%} "
                f"{s.timestamps:>6.0%} {s.metadata:>6.0%} "
                f"{s.signatures_deviations:>7.0%} "
                f"{s.confidence_calibration:>6.0%} {st:>7}"
            )
        passed = sum(1 for s in extraction_scores if s.passed)
        print(f"  {'-' * 80}")
        print(f"  {passed}/{len(extraction_scores)} extraction fixtures passed")
        print(f"{'=' * 85}\n")

    if mapping_scores:
        print(f"{'=' * 85}")
        print(f"  BATCH RECORD MAPPING SUMMARY")
        print(f"{'=' * 85}")
        print(
            f"  {'Fixture':<30} {'Overall':>7} {'Step':>7} {'Param':>7} "
            f"{'N/A':>7} {'Extra':>7} {'Conf':>7} {'Status':>7}"
        )
        print(f"  {'-' * 80}")
        for s in mapping_scores:
            st = "PASS" if s.passed else "FAIL"
            print(
                f"  {s.fixture_name:<30} {s.overall:>6.0%} "
                f"{s.step_matching:>6.0%} {s.param_field_matching:>6.0%} "
                f"{s.na_detection:>6.0%} {s.extra_step_handling:>6.0%} "
                f"{s.mapping_confidence:>6.0%} {st:>7}"
            )
        passed = sum(1 for s in mapping_scores if s.passed)
        print(f"  {'-' * 80}")
        print(f"  {passed}/{len(mapping_scores)} mapping fixtures passed")
        print(f"{'=' * 85}\n")
```

- [ ] **Step 2: Commit**

```bash
git add backend/tests/benchmarks/batch_record_scoring.py
git commit -m "test(benchmark): add batch record report printers [F-0057]"
```

---

## Phase 4 — Conftest & Runner

### Task 12: Extend `conftest.py` with fixture discovery + pro_org promotion + summary

**Files:**
- Modify: `backend/tests/benchmarks/conftest.py`

- [ ] **Step 1: Read current state**

```bash
cat backend/tests/benchmarks/conftest.py | head -30
```

- [ ] **Step 2: Apply edits**

Add to the top imports section of `conftest.py`:

```python
import pytest_asyncio
from app.models.iam import Organization, SubscriptionTier
```

Add after `INPUT_TO_PROTOCOL_DIR = BENCHMARKS_DIR / "input-to-protocol"`:

```python
DOCUMENT_TO_RUN_DIR = BENCHMARKS_DIR / "document-to-run"


def discover_batch_record_fixtures() -> list[Path]:
    """Find all document-to-run fixture directories with expected_extraction.json."""
    if not DOCUMENT_TO_RUN_DIR.exists():
        return []
    return sorted(
        d for d in DOCUMENT_TO_RUN_DIR.iterdir()
        if d.is_dir() and (d / "expected_extraction.json").exists()
    )


def load_expected_extraction(fixture_dir: Path) -> dict:
    with open(fixture_dir / "expected_extraction.json") as f:
        return json.load(f)


def load_protocol(fixture_dir: Path) -> dict | None:
    p = fixture_dir / "protocol.json"
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def load_expected_mapping(fixture_dir: Path) -> dict | None:
    p = fixture_dir / "expected_mapping.json"
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)
```

Promote `pro_org` to conftest module scope. Add near the bottom (before `all_benchmark_scores`):

```python
@pytest_asyncio.fixture
async def pro_org(db_session) -> Organization:
    """Pro-tier org used by benchmark tests so AI provider defaults resolve."""
    org = Organization(
        name="Benchmark Org",
        subscription_tier=SubscriptionTier.PRO.value,
    )
    db_session.add(org)
    await db_session.flush()
    return org
```

Add two more accumulators alongside `all_benchmark_scores`:

```python
all_batch_record_extraction_scores: list = []
all_batch_record_mapping_scores: list = []
```

Update `pytest_terminal_summary`:

```python
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print aggregate benchmark summary at the end of the run."""
    from tests.benchmarks.scoring import print_summary_table
    from tests.benchmarks.batch_record_scoring import print_batch_record_summary

    if all_benchmark_scores:
        print_summary_table(all_benchmark_scores)
    if all_batch_record_extraction_scores or all_batch_record_mapping_scores:
        print_batch_record_summary(
            all_batch_record_extraction_scores,
            all_batch_record_mapping_scores,
        )
```

- [ ] **Step 3: Remove the duplicated `pro_org` fixture from `TestProtocolImportAccuracy`**

Open `backend/tests/benchmarks/test_llm_eval.py`. Delete the `@pytest_asyncio.fixture async def pro_org(...)` method inside `TestProtocolImportAccuracy` (lines ~40-50). Test still uses `pro_org` arg — it now resolves via conftest.

- [ ] **Step 4: Verify F-0058 benchmark still collects cleanly**

```bash
cd backend && pytest tests/benchmarks/test_llm_eval.py -m benchmark --collect-only
```

Expected: collection succeeds, all `TestProtocolImportAccuracy::test_import_accuracy[*]` items listed. Do NOT run them (requires LLM).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/conftest.py backend/tests/benchmarks/test_llm_eval.py
git commit -m "test(benchmark): add batch record fixture discovery and shared pro_org [F-0057]"
```

---

### Task 13: Add `TestBatchRecordAccuracy` runner

**Files:**
- Modify: `backend/tests/benchmarks/test_llm_eval.py`

- [ ] **Step 1: Add imports at top of file**

```python
from app.services.batch_record_extractor import (
    extract_batch_record_data,
    extract_batch_record_pages,
    map_steps_to_protocol,
)
from tests.benchmarks.batch_record_scoring import (
    print_extraction_report,
    print_mapping_report,
    score_extraction,
    score_mapping,
)
from tests.benchmarks.conftest import (
    all_batch_record_extraction_scores,
    all_batch_record_mapping_scores,
    discover_batch_record_fixtures,
    load_expected_extraction,
    load_expected_mapping,
    load_protocol,
)
```

- [ ] **Step 2: Add fixture collection at module level**

Near the top of the file, after `_fixture_dirs` / `_fixture_ids` lines:

```python
_br_fixture_dirs = discover_batch_record_fixtures()
_br_fixture_ids = [d.name for d in _br_fixture_dirs]
```

- [ ] **Step 3: Add the new test class at the bottom of `test_llm_eval.py`**

```python
@pytest.mark.benchmark
class TestBatchRecordAccuracy:
    """Feed real batch record documents through extraction + mapping and score."""

    @pytest.mark.parametrize(
        "fixture_dir", _br_fixture_dirs, ids=_br_fixture_ids,
    )
    async def test_batch_record_accuracy(
        self, fixture_dir: Path, db_session, pro_org,
    ):
        # Stage 1: extraction
        doc = find_document(fixture_dir)
        mime = get_mime_type(doc)
        text, page_images = await extract_batch_record_pages(
            doc, mime, db_session, org_id=pro_org.id,
        )
        extraction = await extract_batch_record_data(
            text, page_images, db_session, org_id=pro_org.id,
        )

        expected_extraction = load_expected_extraction(fixture_dir)
        ext_scores = score_extraction(
            extraction, expected_extraction, fixture_dir.name,
        )
        print_extraction_report(ext_scores)
        all_batch_record_extraction_scores.append(ext_scores)

        assert ext_scores.overall >= 0.75, (
            f"{fixture_dir.name} extraction: {ext_scores.overall:.0%} < 75%\n"
            f"{json.dumps(ext_scores.to_dict(), indent=2)}"
        )

        # Stage 2: mapping (only if protocol.json exists)
        protocol = load_protocol(fixture_dir)
        if protocol is None:
            return

        expected_mapping = load_expected_mapping(fixture_dir)
        if expected_mapping is None:
            pytest.fail(
                f"{fixture_dir.name}: protocol.json present but "
                "expected_mapping.json missing"
            )

        mappings = await map_steps_to_protocol(
            extraction, protocol, db_session, org_id=pro_org.id,
        )
        map_scores = score_mapping(
            mappings, expected_mapping, fixture_dir.name,
        )
        print_mapping_report(map_scores)
        all_batch_record_mapping_scores.append(map_scores)

        assert map_scores.overall >= 0.75, (
            f"{fixture_dir.name} mapping: {map_scores.overall:.0%} < 75%\n"
            f"{json.dumps(map_scores.to_dict(), indent=2)}"
        )
```

- [ ] **Step 4: Verify collection**

```bash
cd backend && pytest tests/benchmarks/test_llm_eval.py -m benchmark --collect-only -q
```

Expected: shows 4 `TestBatchRecordAccuracy::test_batch_record_accuracy[0X-<name>]` items (one per migrated fixture; `05-messy-scan` only appears after Task 18).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/test_llm_eval.py
git commit -m "test(benchmark): add TestBatchRecordAccuracy parametrized runner [F-0057]"
```

---

## Phase 5 — Author Ground-Truth Mapping Fixtures

Each scenario needs `protocol.json` + `expected_mapping.json`. These are hand-authored ground truth — **pause between tasks and show the user for sign-off**.

### Task 14: Author `01-perfect-match/protocol.json` and `expected_mapping.json`

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/01-perfect-match/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/01-perfect-match/expected_mapping.json`

- [ ] **Step 1: Read the expected_extraction.json for this fixture**

```bash
cat backend/tests/benchmarks/document-to-run/01-perfect-match/expected_extraction.json
```

Extraction has 3 steps: Buffer Preparation, Centrifugation, Filtration.

- [ ] **Step 2: Author `protocol.json`**

Create the file with a 3-node protocol graph matching the 3 extraction steps exactly. Use parameter schema fields that align to the extracted labels.

```json
{
  "nodes": [
    {
      "id": "node-buffer-prep",
      "type": "unitOp",
      "position": {"x": 0, "y": 0},
      "data": {
        "label": "Buffer Preparation",
        "paramSchema": {
          "type": "object",
          "properties": {
            "ph_value": {"type": "number", "title": "pH Value"},
            "temperature_c": {"type": "number", "title": "Temperature (°C)"},
            "volume_ml": {"type": "number", "title": "Volume (mL)"}
          }
        }
      }
    },
    {
      "id": "node-centrifugation",
      "type": "unitOp",
      "position": {"x": 200, "y": 0},
      "data": {
        "label": "Centrifugation",
        "paramSchema": {
          "type": "object",
          "properties": {
            "speed_g": {"type": "number", "title": "Speed (g)"},
            "duration_min": {"type": "number", "title": "Duration (min)"},
            "temperature_c": {"type": "number", "title": "Temperature (°C)"}
          }
        }
      }
    },
    {
      "id": "node-filtration",
      "type": "unitOp",
      "position": {"x": 400, "y": 0},
      "data": {
        "label": "Filtration",
        "paramSchema": {
          "type": "object",
          "properties": {
            "filter_size_um": {"type": "number", "title": "Filter Size (μm)"},
            "pressure_psi": {"type": "number", "title": "Pressure (PSI)"}
          }
        }
      }
    }
  ],
  "edges": [
    {"id": "e1", "source": "node-buffer-prep", "target": "node-centrifugation"},
    {"id": "e2", "source": "node-centrifugation", "target": "node-filtration"}
  ]
}
```

- [ ] **Step 3: Author `expected_mapping.json`**

```json
{
  "step_mappings": [
    {
      "extracted_step_name": "Buffer Preparation",
      "protocol_step_name": "Buffer Preparation",
      "mapped": true,
      "param_mappings": [
        {"extracted_label": "pH", "schema_field_key": "ph_value"},
        {"extracted_label": "Temperature", "schema_field_key": "temperature_c"},
        {"extracted_label": "Volume", "schema_field_key": "volume_ml"}
      ]
    },
    {
      "extracted_step_name": "Centrifugation",
      "protocol_step_name": "Centrifugation",
      "mapped": true,
      "param_mappings": [
        {"extracted_label": "Speed", "schema_field_key": "speed_g"},
        {"extracted_label": "Duration", "schema_field_key": "duration_min"},
        {"extracted_label": "Temperature", "schema_field_key": "temperature_c"}
      ]
    },
    {
      "extracted_step_name": "Filtration",
      "protocol_step_name": "Filtration",
      "mapped": true,
      "param_mappings": [
        {"extracted_label": "Filter Size", "schema_field_key": "filter_size_um"},
        {"extracted_label": "Pressure", "schema_field_key": "pressure_psi"}
      ]
    }
  ],
  "unmapped_protocol_steps": [],
  "unmapped_extracted_steps": []
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/01-perfect-match/
git commit -m "test(benchmark): author 01-perfect-match protocol + mapping [F-0057]"
```

---

### Task 15: Author `02-wrong-protocol/protocol.json` and `expected_mapping.json`

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/02-wrong-protocol/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/02-wrong-protocol/expected_mapping.json`

- [ ] **Step 1: Read the expected_extraction.json to identify the document's actual steps**

```bash
cat backend/tests/benchmarks/document-to-run/02-wrong-protocol/expected_extraction.json
```

Identify the step_names. For this scenario the *protocol* should be unrelated (e.g., a cell-culture protocol while the document describes purification), so nothing maps.

- [ ] **Step 2: Author a mismatched `protocol.json`**

Pick a 3-step protocol (e.g., Seeding / Incubation / Harvest) completely unrelated to the document's steps. Full file with nodes + edges similar to Task 14's shape.

- [ ] **Step 3: Author `expected_mapping.json` capturing "nothing maps"**

```json
{
  "step_mappings": [],
  "unmapped_protocol_steps": ["Seeding", "Incubation", "Harvest"],
  "unmapped_extracted_steps": [
    "<first extracted step_name from expected_extraction.json>",
    "<second>",
    "<third>"
  ]
}
```

Fill `unmapped_extracted_steps` with the actual step_names from `expected_extraction.json`.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/02-wrong-protocol/
git commit -m "test(benchmark): author 02-wrong-protocol protocol + mapping [F-0057]"
```

---

### Task 16: Author `03-half-complete/protocol.json` and `expected_mapping.json`

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/03-half-complete/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/03-half-complete/expected_mapping.json`

- [ ] **Step 1: Read the extraction**

```bash
cat backend/tests/benchmarks/document-to-run/03-half-complete/expected_extraction.json
```

- [ ] **Step 2: Author a 5-step protocol where the document only covers ~2-3 steps**

Include the 2-3 step_names from the extraction + 2-3 additional protocol steps that should be marked N/A (`unmapped_protocol_steps`).

- [ ] **Step 3: Author `expected_mapping.json`** — `step_mappings` covers only the steps that appeared in the document; `unmapped_protocol_steps` lists the missing ones.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/03-half-complete/
git commit -m "test(benchmark): author 03-half-complete protocol + mapping [F-0057]"
```

---

### Task 17: Author `04-extra-steps/protocol.json` and `expected_mapping.json`

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/04-extra-steps/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/04-extra-steps/expected_mapping.json`

- [ ] **Step 1: Read the extraction**

```bash
cat backend/tests/benchmarks/document-to-run/04-extra-steps/expected_extraction.json
```

- [ ] **Step 2: Author a protocol with fewer steps than the document**

Protocol has, say, 2 steps. Document has 4 extracted steps — 2 of them should map, 2 should be `unmapped_extracted_steps`.

- [ ] **Step 3: Author `expected_mapping.json`** — `step_mappings` covers only the 2 that map; `unmapped_extracted_steps` lists the 2 extras.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/04-extra-steps/
git commit -m "test(benchmark): author 04-extra-steps protocol + mapping [F-0057]"
```

---

## Phase 6 — Messy-Scan Fixture

### Task 18: Create `05-messy-scan/` fixture

**Files:**
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/document.pdf`
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/expected_extraction.json`
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/protocol.json`
- Create: `backend/tests/benchmarks/document-to-run/05-messy-scan/expected_mapping.json`

- [ ] **Step 1: Look at how existing F-0058 `06-messy-scan` was generated**

```bash
ls backend/tests/benchmarks/input-to-protocol/06-messy-scan/
cat backend/tests/benchmarks/input-to-protocol/06-messy-scan/expected.json | head -40
```

- [ ] **Step 2: Generate a handwritten-style batch record PDF**

Options (pick one; document the choice in a commit message):

**Option A — Use an existing filled template from `tests/artifacts/templates/`:**

```bash
cp backend/tests/artifacts/templates/batch_record_filled_simple.pdf backend/tests/benchmarks/document-to-run/05-messy-scan/document.pdf
```

Then simulate scan degradation with Pillow (blur + noise + slight rotation):

```python
# Save as scratch script, run once
from pathlib import Path
from pdf2image import convert_from_path
from PIL import Image, ImageFilter
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

src = Path("backend/tests/benchmarks/document-to-run/05-messy-scan/document.pdf")
pages = convert_from_path(str(src), dpi=150)
degraded_pages = []
for p in pages:
    img = p.rotate(-2, fillcolor="white", expand=False)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    # Add a bit of noise
    degraded_pages.append(img)

# Save as PDF
degraded_pages[0].save(
    src,
    save_all=True,
    append_images=degraded_pages[1:],
    resolution=150.0,
)
```

**Option B — Hand-craft a fully handwritten scenario:** use the `batch_record_blank_roles.docx` template, fill it by hand via a rendering script, then convert to PDF. Heavier but more realistic.

For this task: **default to Option A.** If Option A isn't visually different enough from a clean scan, switch to B and note why in the commit message.

- [ ] **Step 3: Author `expected_extraction.json`**

Based on what the degraded document actually shows, write the ground-truth extraction JSON following the shape of `01-perfect-match/expected_extraction.json`. Tolerance for extraction is built into scoring, so minor value wobble is fine.

- [ ] **Step 4: Author `protocol.json` + `expected_mapping.json`**

Pick a protocol that matches the document's step set. Likely similar shape to Task 14's perfect-match fixture.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/benchmarks/document-to-run/05-messy-scan/
git commit -m "test(benchmark): add 05-messy-scan fixture for OCR robustness [F-0057]"
```

---

## Phase 7 — Cleanup & Dry Run

### Task 19: Delete the old smoke test and orphaned fixtures

**Files:**
- Delete: `backend/tests/integration/test_batch_record_import_llm.py`
- Delete: `backend/tests/fixtures/sample_batch_record.pdf`
- Delete: `backend/tests/fixtures/sample_batch_record_extraction.json`

- [ ] **Step 1: Check nothing else references these files**

```bash
grep -r "sample_batch_record" backend/
grep -r "test_batch_record_import_llm" backend/
```

Expected: only the files themselves match. If the integration test is imported elsewhere, pause and reconsider.

- [ ] **Step 2: Delete**

```bash
git rm backend/tests/integration/test_batch_record_import_llm.py
git rm backend/tests/fixtures/sample_batch_record.pdf
git rm backend/tests/fixtures/sample_batch_record_extraction.json
```

- [ ] **Step 3: Run the full unit test suite to confirm nothing broke**

```bash
cd backend && pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "test(benchmark): remove F-0057 smoke test and orphaned fixtures [F-0057]"
```

---

### Task 20: End-to-end dry run with real LLM + calibrate

**Files:** none modified in this task — it's an execution + calibration step.

- [ ] **Step 1: Confirm an LLM provider is configured**

```bash
echo $BATCHRITE_AI_VISION_PROVIDER $BATCHRITE_AI_VISION_MODEL
```

Either Anthropic/OpenAI creds via env or an Ollama instance at `localhost:11434` with `llama3.2-vision:11b` pulled. If neither, STOP — benchmark can't run.

- [ ] **Step 2: Run batch-record benchmark only**

```bash
cd backend && pytest tests/benchmarks/test_llm_eval.py::TestBatchRecordAccuracy -m benchmark -v -s
```

Expected: 4–5 fixtures run. Each prints an extraction report (and a mapping report for 01–04 + 05 since all five have `protocol.json`).

- [ ] **Step 3: Review outcomes**

- If all fixtures PASS: great, benchmark baseline is established.
- If some FAIL with overall between 0.6 and 0.75: likely LLM quality issue — not a scoring bug. Note fixture names and move on.
- If some FAIL with overall near 0: likely a scoring bug or fixture misauthoring. Pause and investigate before committing.

- [ ] **Step 4: If calibration adjustments are needed**

Scoring tolerances (numeric 5%, fuzzy thresholds 0.7 / 0.85) are the likely knobs. Only adjust if a clearly-correct extraction is scoring poorly — do NOT adjust to mask real LLM quality issues. If you adjust, update `tests/unit/test_batch_record_scoring.py` correspondingly.

- [ ] **Step 5: If all four migrated fixtures PASS, commit nothing**

This task either passes clean (no commit) or produces a calibration commit:

```bash
# only if calibration changes were made
git add backend/tests/benchmarks/batch_record_scoring.py backend/tests/unit/test_batch_record_scoring.py
git commit -m "test(benchmark): calibrate batch record scoring tolerances [F-0057]"
```

- [ ] **Step 6: Run the F-0058 benchmark too, to confirm nothing upstream broke**

```bash
cd backend && pytest tests/benchmarks/test_llm_eval.py::TestProtocolImportAccuracy -m benchmark --collect-only
```

Expected: collects without errors (do not actually run unless verifying end-to-end — LLM cost).

- [ ] **Step 7: Optional end-of-phase push**

```bash
git push origin $(git branch --show-current)
```

(Only if user has approved pushing this branch.)

---

## Self-Review Checklist

**1. Spec coverage:** all sections in the spec are mapped to tasks:
- Architecture → Task 2, 12, 13
- `batch_record_scoring.py` dataclasses/helpers/scorers → Tasks 2-11
- Fixture discovery + conftest promotion → Task 12
- Runner → Task 13
- Expected-mapping fixture format → Tasks 14-17 (and validated by consumers in Task 20)
- Error handling (missing protocol / missing mapping) → encoded in Task 13 runner
- Migration → Task 1
- Messy-scan fixture → Task 18
- Deletion of smoke test / orphans → Task 19
- Unit tests for scorer → Tasks 2-10
- Invocation commands → Task 20

**2. Placeholder scan:** two tasks intentionally require per-fixture inspection (Tasks 15-17 ask the engineer to read the expected_extraction.json before authoring protocol.json + expected_mapping.json). That's correct — the ground truth depends on document content. Every scoring step includes full code. No TBD/TODO.

**3. Type consistency:** `ExtractionScores`, `MappingScores`, `score_extraction`, `score_mapping`, `BatchRecordExtraction`, `StepMapping`, `ParamMapping` — names consistent across all tasks and match the extractor module.
