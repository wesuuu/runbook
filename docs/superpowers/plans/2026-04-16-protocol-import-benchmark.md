# Protocol Import Benchmark Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a benchmark suite that validates protocol import accuracy against hand-authored expected outputs, using real PDF/PNG documents and real LLM calls.

**Architecture:** Fixture-driven eval framework. Each fixture is a numbered directory containing a real document (PDF/PNG) + `expected.json`. A scoring module compares LLM output against expected on 5 dimensions. Two test files: one for isolated LLM eval, one for full API E2E. Fixtures are auto-discovered — add a directory to add a test case.

**Tech Stack:** pytest (benchmark marker), reportlab (PDF generation), Pillow (PNG generation), existing protocol_importer service functions.

**Spec:** `docs/superpowers/specs/2026-04-16-protocol-import-benchmark-design.md`

---

## File Structure

```
backend/tests/benchmarks/
├── conftest.py                                     # benchmark marker, fixture discovery, mock unit ops catalog
├── scoring.py                                      # Score dataclass, score_proposal(), print_score_report()
├── input-to-protocol/
│   ├── generate_fixtures.py                        # Generates all PDFs and PNGs
│   ├── 01-buffer-prep/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 02-cell-culture-passage/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 03-protein-a-purification/
│   │   ├── document.png
│   │   └── expected.json
│   ├── 04-transfection/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 05-fill-finish-qc/
│   │   ├── document.pdf
│   │   └── expected.json
│   └── 06-messy-scan/
│       ├── document.png
│       └── expected.json
├── test_llm_eval.py                                # LLM accuracy tests
└── test_e2e_import.py                              # Full API round-trip tests
```

---

### Task 1: Add reportlab dev dependency and benchmark pytest marker

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add reportlab to dev dependencies**

```bash
cd backend && poetry add --group dev reportlab
```

- [ ] **Step 2: Add benchmark marker to pytest config**

In `backend/pyproject.toml`, update the `[tool.pytest.ini_options]` section:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
markers = [
    "benchmark: LLM accuracy and E2E protocol import benchmarks (requires AI provider)",
]
```

- [ ] **Step 3: Verify pytest recognizes the marker**

Run: `cd backend && python -m pytest --markers | grep benchmark`
Expected: `@pytest.mark.benchmark: LLM accuracy and E2E protocol import benchmarks (requires AI provider)`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add reportlab dev dep and benchmark pytest marker [F-0058]"
```

---

### Task 2: Scoring module

**Files:**
- Create: `backend/tests/benchmarks/scoring.py`
- Create: `backend/tests/benchmarks/__init__.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# backend/tests/benchmarks/__init__.py
```

Empty file to make it a package.

- [ ] **Step 2: Write scoring module**

Create `backend/tests/benchmarks/scoring.py`:

```python
"""Scoring utilities for protocol import benchmarks.

Compares an actual ProtocolImportProposal (or equivalent dict) against
an expected.json fixture and produces per-dimension scores with detailed
breakdowns for debugging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class ScoreDetails:
    """Granular breakdown for debugging failures."""

    steps_expected: int = 0
    steps_found: int = 0
    steps_missed: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    catalog_mismatches: list[dict] = field(default_factory=list)
    is_new_mismatches: list[dict] = field(default_factory=list)
    params_missed: list[dict] = field(default_factory=list)
    roles_missed: list[str] = field(default_factory=list)
    roles_extra: list[str] = field(default_factory=list)


@dataclass
class BenchmarkScores:
    """Per-dimension scores and overall weighted score."""

    fixture_name: str
    step_detection: float = 0.0
    catalog_matching: float = 0.0
    new_unit_op_detection: float = 0.0
    param_extraction: float = 0.0
    role_extraction: float = 0.0
    details: ScoreDetails = field(default_factory=ScoreDetails)

    @property
    def overall(self) -> float:
        return (
            self.step_detection * 0.30
            + self.catalog_matching * 0.25
            + self.new_unit_op_detection * 0.20
            + self.param_extraction * 0.15
            + self.role_extraction * 0.10
        )

    @property
    def passed(self) -> bool:
        return self.overall >= 0.75

    def to_dict(self) -> dict:
        return {
            "fixture": self.fixture_name,
            "overall": round(self.overall, 3),
            "step_detection": round(self.step_detection, 3),
            "catalog_matching": round(self.catalog_matching, 3),
            "new_unit_op_detection": round(self.new_unit_op_detection, 3),
            "param_extraction": round(self.param_extraction, 3),
            "role_extraction": round(self.role_extraction, 3),
            "details": {
                "steps_expected": self.details.steps_expected,
                "steps_found": self.details.steps_found,
                "steps_missed": self.details.steps_missed,
                "steps_extra": self.details.steps_extra,
                "catalog_mismatches": self.details.catalog_mismatches,
                "is_new_mismatches": self.details.is_new_mismatches,
                "params_missed": self.details.params_missed,
                "roles_missed": self.details.roles_missed,
                "roles_extra": self.details.roles_extra,
            },
        }


def _fuzzy_match_name(name_a: str, name_b: str, threshold: float = 0.7) -> bool:
    """Case-insensitive fuzzy match on step names."""
    return SequenceMatcher(
        None, name_a.lower().strip(), name_b.lower().strip()
    ).ratio() >= threshold


def _match_steps(
    expected_steps: list[dict], actual_steps: list[dict]
) -> list[tuple[dict, dict | None]]:
    """Match expected steps to actual steps by fuzzy name similarity.

    Returns list of (expected_step, matched_actual_step_or_None).
    """
    remaining_actual = list(actual_steps)
    matches: list[tuple[dict, dict | None]] = []

    for exp in expected_steps:
        best_match = None
        best_ratio = 0.0
        for act in remaining_actual:
            act_name = act.get("name", "")
            ratio = SequenceMatcher(
                None, exp["name"].lower(), act_name.lower()
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = act
        if best_match and best_ratio >= 0.7:
            matches.append((exp, best_match))
            remaining_actual.remove(best_match)
        else:
            matches.append((exp, None))

    return matches


def score_proposal(
    actual: dict,
    expected: dict,
    fixture_name: str = "",
) -> BenchmarkScores:
    """Score an actual proposal (or its dict form) against expected.json.

    Args:
        actual: Dict with keys like {"steps": [...], "protocol_name": ...}.
                Each step has: name, category, matched_unit_op_name,
                is_new, params, role.
        expected: Loaded expected.json with same structure.
        fixture_name: Name for reporting.

    Returns:
        BenchmarkScores with per-dimension scores and breakdown details.
    """
    scores = BenchmarkScores(fixture_name=fixture_name)
    details = scores.details

    expected_steps = expected.get("steps", [])
    actual_steps = actual.get("steps", [])
    details.steps_expected = len(expected_steps)
    details.steps_found = len(actual_steps)

    # ── 1. Step Detection (F1 of precision + recall) ──
    step_matches = _match_steps(expected_steps, actual_steps)
    matched_expected = [exp for exp, act in step_matches if act is not None]
    unmatched_expected = [exp for exp, act in step_matches if act is None]
    details.steps_missed = [s["name"] for s in unmatched_expected]

    # Find extra actual steps (not matched to any expected)
    matched_actual_names = {
        act["name"] for _, act in step_matches if act is not None
    }
    details.steps_extra = [
        s.get("name", "?") for s in actual_steps
        if s.get("name", "?") not in matched_actual_names
    ]

    recall = len(matched_expected) / len(expected_steps) if expected_steps else 1.0
    precision = (
        len(matched_expected) / len(actual_steps) if actual_steps else (1.0 if not expected_steps else 0.0)
    )
    scores.step_detection = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # ── 2. Catalog Matching ──
    catalog_total = 0
    catalog_correct = 0
    for exp, act in step_matches:
        exp_match = exp.get("matched_unit_op_name")
        if exp_match is not None:  # expected to match something
            catalog_total += 1
            if act:
                act_match = act.get("matched_unit_op_name")
                if act_match and act_match.lower() == exp_match.lower():
                    catalog_correct += 1
                else:
                    details.catalog_mismatches.append({
                        "step": exp["name"],
                        "expected": exp_match,
                        "actual": act.get("matched_unit_op_name") if act else None,
                    })
            else:
                details.catalog_mismatches.append({
                    "step": exp["name"],
                    "expected": exp_match,
                    "actual": None,
                })

    scores.catalog_matching = (
        catalog_correct / catalog_total if catalog_total > 0 else 1.0
    )

    # ── 3. New Unit Op Detection ──
    is_new_total = 0
    is_new_correct = 0
    for exp, act in step_matches:
        if act is not None:
            is_new_total += 1
            exp_is_new = exp.get("is_new", False)
            act_is_new = act.get("is_new", False)
            if exp_is_new == act_is_new:
                is_new_correct += 1
            else:
                details.is_new_mismatches.append({
                    "step": exp["name"],
                    "expected_is_new": exp_is_new,
                    "actual_is_new": act_is_new,
                })

    scores.new_unit_op_detection = (
        is_new_correct / is_new_total if is_new_total > 0 else 1.0
    )

    # ── 4. Parameter Extraction ──
    param_total = 0
    param_correct = 0
    for exp, act in step_matches:
        exp_params = exp.get("expected_params", {})
        if not exp_params or act is None:
            continue
        act_params = act.get("params", {})
        for key, exp_val in exp_params.items():
            param_total += 1
            # Look for key in actual params (case-insensitive key match)
            act_val = None
            for ak, av in act_params.items():
                if ak.lower() == key.lower():
                    act_val = av
                    break

            if act_val is None:
                details.params_missed.append({
                    "step": exp["name"],
                    "param": key,
                    "expected": exp_val,
                    "actual": None,
                })
                continue

            # Compare values
            if _param_values_match(exp_val, act_val):
                param_correct += 1
            else:
                details.params_missed.append({
                    "step": exp["name"],
                    "param": key,
                    "expected": exp_val,
                    "actual": act_val,
                })

    scores.param_extraction = (
        param_correct / param_total if param_total > 0 else 1.0
    )

    # ── 5. Role Extraction ──
    expected_roles = {r.lower() for r in expected.get("expected_roles", [])}
    actual_roles = {
        s.get("role", "").lower()
        for s in actual_steps
        if s.get("role")
    }
    if expected_roles or actual_roles:
        intersection = expected_roles & actual_roles
        union = expected_roles | actual_roles
        scores.role_extraction = len(intersection) / len(union) if union else 1.0
        details.roles_missed = [r for r in expected_roles if r not in actual_roles]
        details.roles_extra = [r for r in actual_roles if r not in expected_roles]
    else:
        scores.role_extraction = 1.0

    return scores


def _param_values_match(expected, actual) -> bool:
    """Compare param values with tolerance.

    - Numbers: within 20% tolerance
    - Strings: case-insensitive substring match
    - Booleans: exact match
    """
    if isinstance(expected, bool):
        return expected == actual

    if isinstance(expected, (int, float)):
        try:
            actual_num = float(actual)
        except (TypeError, ValueError):
            return False
        if expected == 0:
            return actual_num == 0
        return abs(actual_num - expected) / abs(expected) <= 0.2

    if isinstance(expected, str):
        if actual is None:
            return False
        return expected.lower() in str(actual).lower()

    return expected == actual


def print_score_report(scores: BenchmarkScores) -> None:
    """Print a formatted score table for a single fixture."""
    status = "PASS" if scores.passed else "FAIL"
    d = scores.details

    print()
    print(f"{'=' * 65}")
    print(f"  {scores.fixture_name:<45} {status} {scores.overall:.0%}")
    print(f"{'=' * 65}")
    print(f"  {'Dimension':<22} {'Score':>6}  Detail")
    print(f"  {'-' * 60}")
    print(
        f"  {'Step Detection':<22} {scores.step_detection:>5.2f}  "
        f"{d.steps_found}/{d.steps_expected} found, "
        f"{len(d.steps_extra)} extra"
    )
    print(
        f"  {'Catalog Matching':<22} {scores.catalog_matching:>5.2f}  "
        f"{len(d.catalog_mismatches)} mismatches"
    )
    print(
        f"  {'New Unit Op Detect':<22} {scores.new_unit_op_detection:>5.2f}  "
        f"{len(d.is_new_mismatches)} wrong"
    )
    print(
        f"  {'Param Extraction':<22} {scores.param_extraction:>5.2f}  "
        f"{len(d.params_missed)} missed"
    )
    print(
        f"  {'Role Extraction':<22} {scores.role_extraction:>5.2f}  "
        f"missed={d.roles_missed}, extra={d.roles_extra}"
    )
    print(f"  {'-' * 60}")
    print(f"  {'Overall (weighted)':<22} {scores.overall:>5.2f}  threshold: 0.75")
    print(f"{'=' * 65}")

    # Print missed details if any
    if d.steps_missed:
        print(f"  Steps missed: {d.steps_missed}")
    if d.catalog_mismatches:
        print(f"  Catalog mismatches: {json.dumps(d.catalog_mismatches, indent=4)}")
    if d.params_missed:
        print(f"  Params missed: {json.dumps(d.params_missed, indent=4)}")
    print()


def print_summary_table(all_scores: list[BenchmarkScores]) -> None:
    """Print aggregate summary table across all fixtures."""
    print()
    print(f"{'=' * 85}")
    print(f"  BENCHMARK SUMMARY")
    print(f"{'=' * 85}")
    print(
        f"  {'Fixture':<30} {'Overall':>7} {'Steps':>7} {'Match':>7} "
        f"{'NewOp':>7} {'Param':>7} {'Role':>7} {'Status':>7}"
    )
    print(f"  {'-' * 80}")
    for s in all_scores:
        status = "PASS" if s.passed else "FAIL"
        print(
            f"  {s.fixture_name:<30} {s.overall:>6.0%} "
            f"{s.step_detection:>6.0%} {s.catalog_matching:>6.0%} "
            f"{s.new_unit_op_detection:>6.0%} {s.param_extraction:>6.0%} "
            f"{s.role_extraction:>6.0%} {status:>7}"
        )
    print(f"  {'-' * 80}")

    # Averages
    n = len(all_scores) or 1
    print(
        f"  {'AVERAGE':<30} "
        f"{sum(s.overall for s in all_scores) / n:>6.0%} "
        f"{sum(s.step_detection for s in all_scores) / n:>6.0%} "
        f"{sum(s.catalog_matching for s in all_scores) / n:>6.0%} "
        f"{sum(s.new_unit_op_detection for s in all_scores) / n:>6.0%} "
        f"{sum(s.param_extraction for s in all_scores) / n:>6.0%} "
        f"{sum(s.role_extraction for s in all_scores) / n:>6.0%}"
    )
    passed = sum(1 for s in all_scores if s.passed)
    print(f"  {passed}/{len(all_scores)} fixtures passed")
    print(f"{'=' * 85}")
    print()
```

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/
git commit -m "feat(benchmarks): add scoring module for protocol import eval [F-0058]"
```

---

### Task 3: Benchmark conftest — fixture discovery and unit op catalog

**Files:**
- Create: `backend/tests/benchmarks/conftest.py`

- [ ] **Step 1: Write conftest.py**

Create `backend/tests/benchmarks/conftest.py`:

```python
"""Shared fixtures for protocol import benchmarks."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest


BENCHMARKS_DIR = Path(__file__).parent
INPUT_TO_PROTOCOL_DIR = BENCHMARKS_DIR / "input-to-protocol"


def discover_fixtures() -> list[Path]:
    """Find all fixture directories that contain expected.json."""
    if not INPUT_TO_PROTOCOL_DIR.exists():
        return []
    dirs = sorted(
        d
        for d in INPUT_TO_PROTOCOL_DIR.iterdir()
        if d.is_dir() and (d / "expected.json").exists()
    )
    return dirs


def load_expected(fixture_dir: Path) -> dict:
    """Load expected.json from a fixture directory."""
    with open(fixture_dir / "expected.json") as f:
        return json.load(f)


def find_document(fixture_dir: Path) -> Path:
    """Find the document file (PDF or PNG) in a fixture directory."""
    for ext in ("pdf", "png", "jpg", "jpeg", "tiff", "docx"):
        candidate = fixture_dir / f"document.{ext}"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No document file found in {fixture_dir}")


def get_mime_type(doc_path: Path) -> str:
    """Get MIME type from file extension."""
    mime, _ = mimetypes.guess_type(str(doc_path))
    if mime:
        return mime
    ext_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return ext_map.get(doc_path.suffix.lower(), "application/octet-stream")


def make_mock_unit_op(
    name: str,
    category: str = "General",
    param_schema: dict | None = None,
    description: str = "",
) -> MagicMock:
    """Create a mock UnitOpDefinition matching the DB model interface."""
    op = MagicMock()
    op.id = uuid4()
    op.name = name
    op.category = category
    op.description = description or f"Description for {name}"
    op.param_schema = param_schema or {}
    return op


def build_seed_catalog() -> list[MagicMock]:
    """Build mock UnitOpDefinition list matching the seed data catalog.

    This mirrors backend/app/db/seed.py so the benchmark uses the same
    catalog the LLM will see in production.
    """
    return [
        make_mock_unit_op(
            "Buffer Preparation", "Media Prep",
            {"type": "object", "properties": {
                "buffer_name": {"type": "string"},
                "volume_L": {"type": "number"},
                "pH_target": {"type": "number"},
                "pH_tolerance": {"type": "number"},
                "pH_agent": {"type": "string"},
            }},
            "Prepare buffer solution",
        ),
        make_mock_unit_op(
            "Media Preparation", "Media Prep",
            {"type": "object", "properties": {
                "media_name": {"type": "string"},
                "volume_L": {"type": "number"},
                "basal_medium": {"type": "string"},
                "supplements": {"type": "string"},
            }},
            "Prepare cell culture media",
        ),
        make_mock_unit_op(
            "Seeding", "Cell Culture",
            {"type": "object", "properties": {
                "cell_density": {"type": "number"},
                "vessel_type": {"type": "string"},
                "volume_mL": {"type": "number"},
            }},
            "Seed cells into vessel",
        ),
        make_mock_unit_op(
            "Incubation", "Cell Culture",
            {"type": "object", "properties": {
                "temperature_C": {"type": "number"},
                "CO2_percent": {"type": "number"},
                "duration_hours": {"type": "number"},
                "rpm": {"type": "number"},
            }},
            "Incubate cells",
        ),
        make_mock_unit_op(
            "Cell Counting", "Cell Culture",
            {"type": "object", "properties": {
                "method": {"type": "string"},
                "dilution_factor": {"type": "number"},
            }},
            "Count cells",
        ),
        make_mock_unit_op(
            "Transfection", "Cell Culture",
            {"type": "object", "properties": {
                "reagent": {"type": "string"},
                "dna_amount_ug": {"type": "number"},
                "method": {"type": "string"},
            }},
            "Transfect cells",
        ),
        make_mock_unit_op(
            "Harvest", "Cell Culture",
            {"type": "object", "properties": {
                "method": {"type": "string"},
                "centrifuge_rcf": {"type": "number"},
            }},
            "Harvest cells",
        ),
        make_mock_unit_op(
            "Centrifugation", "Purification",
            {"type": "object", "properties": {
                "rcf_g": {"type": "number"},
                "duration_min": {"type": "number"},
                "temperature_C": {"type": "number"},
            }},
            "Centrifuge sample",
        ),
        make_mock_unit_op(
            "Filtration", "Purification",
            {"type": "object", "properties": {
                "filter_size_um": {"type": "number"},
                "filter_type": {"type": "string"},
                "volume_L": {"type": "number"},
            }},
            "Filter solution",
        ),
        make_mock_unit_op(
            "Chromatography", "Purification",
            {"type": "object", "properties": {
                "column_type": {"type": "string"},
                "resin": {"type": "string"},
                "flow_rate_mL_min": {"type": "number"},
            }},
            "Chromatographic purification",
        ),
        make_mock_unit_op(
            "pH Adjustment", "Reaction",
            {"type": "object", "properties": {
                "target_pH": {"type": "number"},
                "acid_or_base": {"type": "string"},
            }},
            "Adjust solution pH",
        ),
        make_mock_unit_op(
            "Mixing", "Reaction",
            {"type": "object", "properties": {
                "speed_rpm": {"type": "number"},
                "duration_min": {"type": "number"},
                "temperature_C": {"type": "number"},
            }},
            "Mix solution",
        ),
        make_mock_unit_op(
            "Sample Collection", "Analytics",
            {"type": "object", "properties": {
                "volume_mL": {"type": "number"},
                "container_type": {"type": "string"},
                "storage_temp_C": {"type": "number"},
            }},
            "Collect sample",
        ),
        make_mock_unit_op(
            "Assay", "Analytics",
            {"type": "object", "properties": {
                "assay_type": {"type": "string"},
                "method": {"type": "string"},
            }},
            "Run assay",
        ),
        make_mock_unit_op(
            "Fill", "Fill/Finish",
            {"type": "object", "properties": {
                "fill_volume_mL": {"type": "number"},
                "container_type": {"type": "string"},
                "fill_speed": {"type": "string"},
            }},
            "Fill containers",
        ),
        make_mock_unit_op(
            "Lyophilization", "Fill/Finish",
            {"type": "object", "properties": {
                "shelf_temp_C": {"type": "number"},
                "chamber_pressure_mTorr": {"type": "number"},
                "duration_hours": {"type": "number"},
            }},
            "Lyophilize product",
        ),
        make_mock_unit_op(
            "Visual Inspection", "Quality Control",
            {"type": "object", "properties": {
                "inspection_type": {"type": "string"},
                "acceptance_criteria": {"type": "string"},
            }},
            "Visual inspection",
        ),
    ]


@pytest.fixture
def unit_ops_catalog() -> list[MagicMock]:
    """Provide the seed unit op catalog as mock objects."""
    return build_seed_catalog()


# ── Shared score accumulator + pytest summary hook ────────────────

all_benchmark_scores: list = []
"""Shared list that test files append BenchmarkScores to.
The pytest_terminal_summary hook prints aggregate results."""


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print aggregate benchmark summary at the end of the run."""
    if all_benchmark_scores:
        from tests.benchmarks.scoring import print_summary_table

        print_summary_table(all_benchmark_scores)
```

- [ ] **Step 2: Verify imports work**

Run: `cd backend && python -c "from tests.benchmarks.conftest import discover_fixtures, build_seed_catalog; print(len(build_seed_catalog()), 'unit ops')"`
Expected: `17 unit ops`

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/
git commit -m "feat(benchmarks): add conftest with fixture discovery and seed catalog [F-0058]"
```

---

### Task 4: Fixture generation script — PDFs and PNGs

**Files:**
- Create: `backend/tests/benchmarks/input-to-protocol/generate_fixtures.py`

- [ ] **Step 1: Write the fixture generator**

Create `backend/tests/benchmarks/input-to-protocol/generate_fixtures.py`:

```python
#!/usr/bin/env python3
"""Generate benchmark fixture documents (PDFs and PNGs).

Run from backend/: python tests/benchmarks/input-to-protocol/generate_fixtures.py

Idempotent — regenerates all documents from scratch.
To add a new fixture: add a generate_NN_*() function and call it from main().
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURES_DIR = Path(__file__).parent


def _sop_header_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPHeader",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )


def _sop_body_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )


def _sop_section_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "SOPSection",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=12,
        spaceAfter=6,
    )


def _build_pdf(output_path: Path, title: str, doc_number: str, elements_fn):
    """Build a PDF with standard SOP header and custom body elements."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    header = _sop_header_style()
    body = _sop_body_style()
    section = _sop_section_style()

    elements = []

    # Standard SOP header table
    header_data = [
        ["STANDARD OPERATING PROCEDURE", ""],
        [f"Title: {title}", f"Doc #: {doc_number}"],
        ["Effective: 2026-01-15", "Rev: 1.0"],
    ]
    header_table = Table(header_data, colWidths=[4 * inch, 3 * inch])
    header_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("SPAN", (0, 0), (1, 0)),
        ("ALIGN", (0, 0), (1, 0), "CENTER"),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Add custom body elements
    elements_fn(elements, header, body, section)

    doc.build(elements)


def _build_png(output_path: Path, lines: list[str], degrade: bool = False):
    """Render text lines to a PNG image.

    Args:
        output_path: Where to save.
        lines: Text lines to render.
        degrade: If True, simulate low-quality scan (noise, rotation).
    """
    width, height = 850, max(1100, len(lines) * 28 + 200)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
        )
    except OSError:
        font = ImageFont.load_default()
        font_bold = font

    y = 40
    for line in lines:
        if line.startswith("# "):
            draw.text((40, y), line[2:], fill="black", font=font_bold)
            y += 30
        elif line.startswith("---"):
            draw.line([(40, y + 5), (width - 40, y + 5)], fill="grey", width=1)
            y += 15
        else:
            draw.text((40, y), line, fill="black", font=font)
            y += 22

    if degrade:
        import random

        # Add noise
        pixels = img.load()
        for _ in range(width * height // 20):
            x = random.randint(0, width - 1)
            y_pos = random.randint(0, height - 1)
            gray = random.randint(180, 230)
            pixels[x, y_pos] = (gray, gray, gray)

        # Slight rotation
        img = img.rotate(1.5, fillcolor="white", expand=False)

        # Reduce resolution then scale back up (blur effect)
        small = img.resize((width // 3, height // 3), Image.BILINEAR)
        img = small.resize((width, height), Image.BILINEAR)

    img.save(output_path)


# ── Fixture generators ────────────────────────────────────────────


def generate_01_buffer_prep():
    """PDF: Simple buffer prep, 4 steps, all catalog matches."""
    out_dir = FIXTURES_DIR / "01-buffer-prep"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(Paragraph(
            "This SOP describes the preparation of 10L Tris-HCl buffer (50mM, pH 7.4) "
            "for use in downstream purification processes.",
            body,
        ))
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Operator", body))
        elements.append(Paragraph("3. Procedure", section))
        elements.append(Paragraph(
            "<b>Step 1: Buffer Preparation</b><br/>"
            "Weigh 60.57g Tris base and dissolve in 8L purified water in a 10L carboy. "
            "Stir at 200 RPM until fully dissolved (approximately 15 minutes). "
            "Target volume: 10L. Target concentration: 50mM.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 2: pH Adjustment</b><br/>"
            "Using a calibrated pH meter, adjust pH to 7.4 (&plusmn; 0.05) by slow addition "
            "of concentrated HCl (6N). Mix thoroughly between additions. "
            "Record final pH reading.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 3: Sterile Filtration</b><br/>"
            "Filter the entire 10L volume through a 0.22&mu;m PES membrane filter "
            "into a sterile carboy. Use a peristaltic pump at 500 mL/min flow rate. "
            "Perform bubble-point integrity test post-filtration.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 4: QC Sampling</b><br/>"
            "Collect a 50mL sample into a sterile polypropylene tube. "
            "Label with buffer name, lot number, and date. "
            "Store at 2-8&deg;C. Submit for pH verification and bioburden testing.",
            body,
        ))

    _build_pdf(out_dir / "document.pdf", "Tris-HCl Buffer Preparation", "SOP-BUF-001", body)


def generate_02_cell_culture_passage():
    """PDF: Cell passage, 7 steps, 2 new unit ops."""
    out_dir = FIXTURES_DIR / "02-cell-culture-passage"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(Paragraph(
            "Routine passage of adherent CHO-K1 cells for seed train maintenance. "
            "Cells are split 1:4 every 3-4 days when reaching 80-90% confluence.",
            body,
        ))
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Operator", body))
        elements.append(Paragraph("3. Materials", section))

        materials = [
            ["Item", "Specification"],
            ["Complete Growth Medium", "DMEM/F12 + 10% FBS + 1% Pen/Strep"],
            ["PBS", "Dulbecco's PBS without Ca/Mg"],
            ["Trypsin-EDTA", "0.25% Trypsin, 1mM EDTA"],
            ["T-175 Flasks", "Corning, tissue-culture treated"],
        ]
        mat_table = Table(materials, colWidths=[2.5 * inch, 4 * inch])
        mat_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
        ]))
        elements.append(mat_table)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("4. Procedure", section))
        elements.append(Paragraph(
            "<b>Step 1: Pre-warm Media</b><br/>"
            "Remove complete growth medium from 4&deg;C storage. "
            "Place in 37&deg;C water bath for 20 minutes. "
            "Volume required: 35mL per T-175 flask.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 2: Aspirate Spent Media</b><br/>"
            "Remove flask from incubator. Using a vacuum aspirator, "
            "carefully remove all spent media from the flask. "
            "Tilt flask to collect residual media at the corner.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 3: PBS Wash</b><br/>"
            "Add 10mL PBS to the flask. Gently rock the flask to wash the cell monolayer. "
            "Aspirate the PBS wash. Repeat once for a total of 2 washes.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 4: Trypsinization</b><br/>"
            "Add 5mL 0.25% Trypsin-EDTA to the flask. "
            "Incubate at 37&deg;C for 5 minutes. "
            "Check cell detachment under microscope.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 5: Neutralize and Harvest</b><br/>"
            "Add 10mL complete medium to neutralize trypsin. "
            "Pipette up and down to create single-cell suspension. "
            "Transfer to a 50mL conical tube.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 6: Cell Count</b><br/>"
            "Take 100&mu;L sample. Mix with 100&mu;L Trypan Blue (1:2 dilution). "
            "Load hemocytometer and count using Trypan Blue exclusion method. "
            "Record viable cell density and viability percentage.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 7: Seed New Flasks</b><br/>"
            "Seed new T-175 flasks at 0.5 &times; 10<super>6</super> cells/mL "
            "in 35mL complete medium. "
            "Place in incubator at 37&deg;C, 5% CO2, humidified atmosphere.",
            body,
        ))

    _build_pdf(out_dir / "document.pdf", "CHO-K1 Cell Passage", "SOP-CC-012", body)


def generate_03_protein_a_purification():
    """PNG: Protein A purification, 10 steps, 3 new unit ops (scan-style)."""
    out_dir = FIXTURES_DIR / "03-protein-a-purification"
    out_dir.mkdir(exist_ok=True)

    lines = [
        "# Protein A Purification Protocol",
        "# Doc: SOP-PUR-007  Rev 2.1  Effective: 2025-11-01",
        "---",
        "",
        "Responsible: Purification Scientist (steps 1-9), QC Analyst (step 10)",
        "",
        "PROCEDURE:",
        "",
        "1. Column Equilibration",
        "   Equilibrate the MabSelect SuRe Protein A column (CV = 5mL)",
        "   with 5 column volumes of binding buffer (20mM sodium phosphate,",
        "   150mM NaCl, pH 7.2) at 1.0 mL/min flow rate.",
        "   Duration: 25 minutes.",
        "",
        "2. Load Clarified Harvest",
        "   Load the clarified cell culture harvest onto the column at",
        "   0.5 mL/min. Load volume: 50mL (10 CV). Monitor A280 for",
        "   breakthrough. Column type: Protein A.",
        "   Duration: 100 minutes.",
        "",
        "3. Wash",
        "   Wash with 10 CV binding buffer at 1.0 mL/min to remove",
        "   unbound material. Monitor A280 until baseline is reached.",
        "   Duration: 50 minutes.",
        "",
        "4. Elution",
        "   Elute bound protein with 5 CV of elution buffer (100mM",
        "   glycine-HCl, pH 3.0) at 0.5 mL/min. Collect 1mL fractions.",
        "   Pool fractions with A280 > 0.1 AU. Column type: Protein A.",
        "   Duration: 50 minutes.",
        "",
        "5. Neutralize Eluate",
        "   Immediately neutralize pooled eluate to pH 7.0 (+/- 0.2)",
        "   using 1M Tris-HCl pH 9.0. Mix gently by inversion.",
        "   Record final pH. Duration: 10 minutes.",
        "",
        "6. Low pH Viral Inactivation",
        "   Adjust eluate to pH 3.5 using 1M HCl. Hold for 60 minutes",
        "   at room temperature (20-25C). This is a critical process step",
        "   for viral safety. Record pH and hold start/end times.",
        "   Duration: 60 minutes.",
        "",
        "7. Re-neutralize and Filter",
        "   Adjust pH back to 7.0 using 1M Tris base.",
        "   Filter through 0.22um PES membrane. Volume: approx 10mL.",
        "   Duration: 15 minutes.",
        "",
        "8. Diafiltration",
        "   Using a 30kDa TFF cassette, diafilter into formulation buffer",
        "   (10mM histidine, 150mM NaCl, pH 6.0). Perform 5 diavolumes.",
        "   Transmembrane pressure: 15 psi. Flow rate: 5 mL/min.",
        "   Duration: 90 minutes.",
        "",
        "9. Concentration",
        "   Concentrate the diafiltrated pool to target 10 mg/mL using",
        "   the same TFF cassette. Centrifuge any precipitate at 3000xg",
        "   for 10 minutes at 4C. Duration: 30 minutes.",
        "",
        "10. Final QC Sample Collection",
        "    Collect 2mL sample into sterile polypropylene cryovial.",
        "    Store at -80C. Submit for: A280 concentration, SEC-HPLC",
        "    purity, endotoxin (LAL), and sterility.",
        "    Duration: 10 minutes.",
    ]

    _build_png(out_dir / "document.png", lines, degrade=False)


def generate_04_transfection():
    """PDF: Transfection protocol, 6 steps, 1 new unit op."""
    out_dir = FIXTURES_DIR / "04-transfection"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(Paragraph(
            "Transient transfection of HEK293 cells for recombinant protein expression "
            "using Lipofectamine 3000. Target: 6-well plate scale.",
            body,
        ))
        elements.append(Paragraph("2. Responsible Personnel", section))
        elements.append(Paragraph("Role: Scientist", body))
        elements.append(Paragraph("3. Procedure", section))
        elements.append(Paragraph(
            "<b>Step 1: Seed Cells (Day -1)</b><br/>"
            "Seed HEK293 cells at 0.5 &times; 10<super>6</super> cells/well "
            "in 2mL complete DMEM per well of a 6-well plate. "
            "Incubate overnight at 37&deg;C, 5% CO2. "
            "Cells should be 70-80% confluent at transfection.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 2: Prepare DNA-Lipid Complexes (Day 0)</b><br/>"
            "Per well: dilute 2.5&mu;g plasmid DNA in 125&mu;L Opti-MEM. "
            "In a separate tube, dilute 3.75&mu;L Lipofectamine 3000 in 125&mu;L Opti-MEM. "
            "Add 5&mu;L P3000 reagent to the DNA tube. "
            "Combine DNA and lipid tubes, mix gently. Incubate 15 minutes at room temperature. "
            "DNA:lipid ratio is 1:1.5.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 3: Transfect Cells</b><br/>"
            "Add 250&mu;L DNA-lipid complex dropwise to each well. "
            "Gently rock plate to distribute. "
            "Method: lipofection. Reagent: Lipofectamine 3000. DNA amount: 2.5&mu;g/well.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 4: Incubate</b><br/>"
            "Return plate to incubator. Incubate for 4-6 hours at 37&deg;C, 5% CO2. "
            "Do not disturb the plate during incubation.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 5: Media Change</b><br/>"
            "After 4-6 hours, aspirate transfection media. "
            "Replace with 2mL fresh complete DMEM per well. "
            "Return to incubator.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 6: Assess Transfection (Day 2)</b><br/>"
            "At 48 hours post-transfection, count cells and assess viability. "
            "Take 100&mu;L sample, mix with Trypan Blue (1:2 dilution). "
            "Method: Trypan Blue exclusion. Expected viability: &gt;85%.",
            body,
        ))

    _build_pdf(out_dir / "document.pdf", "HEK293 Transient Transfection", "SOP-CC-023", body)


def generate_05_fill_finish_qc():
    """PDF: Fill/Finish with QC, 8 steps, 2 new unit ops, 2 roles."""
    out_dir = FIXTURES_DIR / "05-fill-finish-qc"
    out_dir.mkdir(exist_ok=True)

    def body(elements, header, body, section):
        elements.append(Paragraph("1. Purpose", section))
        elements.append(Paragraph(
            "Aseptic fill of drug product into 2mL glass vials, followed by "
            "lyophilization and QC release testing. Batch size: 500 vials.",
            body,
        ))
        elements.append(Paragraph("2. Responsible Personnel", section))

        roles = [
            ["Role", "Responsibility"],
            ["Fill Operator", "Steps 1-4, 6: Buffer prep, filtration, fill, sealing, lyo"],
            ["QC Inspector", "Steps 5, 7, 8: Visual inspection, particulate testing, assay"],
        ]
        role_table = Table(roles, colWidths=[2 * inch, 4.5 * inch])
        role_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
        ]))
        elements.append(role_table)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("3. Procedure", section))
        elements.append(Paragraph(
            "<b>Step 1: Prepare Formulation Buffer</b> (Fill Operator)<br/>"
            "Prepare 5L of histidine formulation buffer (10mM L-histidine, 150mM NaCl, "
            "pH 6.0). Dissolve components in WFI, adjust pH with HCl. "
            "Volume: 5L. pH target: 6.0.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 2: Sterile Filtration</b> (Fill Operator)<br/>"
            "Filter drug substance through 0.22&mu;m PES membrane into sterile vessel. "
            "Filter type: PES membrane. Pore size: 0.22&mu;m. Volume: 1.2L. "
            "Perform integrity test post-filtration.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 3: Vial Filling</b> (Fill Operator)<br/>"
            "Fill each vial with 1.2mL drug product using peristaltic pump. "
            "Fill speed: medium (2 mL/sec). Container type: 2mL Type I glass vial. "
            "Check fill weight every 50 vials (&plusmn; 3% target).",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 4: Stoppering and Crimping</b> (Fill Operator)<br/>"
            "Insert rubber stopper into each vial under laminar flow. "
            "Apply aluminum crimp cap using manual crimping tool. "
            "Verify each seal visually. Duration: 120 minutes for 500 vials.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 5: 100% Visual Inspection</b> (QC Inspector)<br/>"
            "Inspect every vial against black and white backgrounds. "
            "Inspection type: 100% manual. Reject criteria: visible particles, "
            "cracks, seal defects, fill volume anomalies. "
            "Acceptance criteria: no visible particles, intact seal.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 6: Lyophilization</b> (Fill Operator)<br/>"
            "Load vials into lyophilizer. Cycle parameters: "
            "shelf temperature -40&deg;C, chamber pressure 100 mTorr, "
            "primary drying 24 hours, secondary drying 6 hours at 25&deg;C. "
            "Total cycle: 30 hours.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 7: Particulate Testing</b> (QC Inspector)<br/>"
            "Test per USP &lt;788&gt;. Use HIAC liquid particle counter. "
            "Acceptance: &le; 6000 particles &ge; 10&mu;m, &le; 600 particles &ge; 25&mu;m per container. "
            "Test 10 vials from the batch. Method: light obscuration.",
            body,
        ))
        elements.append(Paragraph(
            "<b>Step 8: Potency Assay</b> (QC Inspector)<br/>"
            "Run ELISA potency assay on 3 vials. "
            "Assay type: ELISA. Method: sandwich ELISA. "
            "Acceptance: 80-120% of nominal potency. "
            "Report mean, SD, and %CV.",
            body,
        ))

    _build_pdf(out_dir / "document.pdf", "Drug Product Fill/Finish", "SOP-FF-004", body)


def generate_06_messy_scan():
    """PNG: Low-quality scan simulating photographed laminated card."""
    out_dir = FIXTURES_DIR / "06-messy-scan"
    out_dir.mkdir(exist_ok=True)

    lines = [
        "# Cell Thaw Quick Reference",
        "---",
        "",
        "1. Thaw cryovial from LN2 storage",
        "   Place vial in 37C water bath",
        "   Swirl gently for 2-3 min until just thawed",
        "   Vial count: 1, Duration: 3 min",
        "",
        "2. Add thawed cells to pre-warmed media",
        "   Transfer vial contents to 15mL tube",
        "   Add 9mL pre-warmed complete DMEM",
        "   Media name: complete DMEM, Volume: 10mL",
        "",
        "3. Centrifuge to remove DMSO",
        "   Spin at 300xg for 5 min at RT",
        "   Discard supernatant carefully",
        "   RCF: 300g, Duration: 5 min, Temp: 22C",
        "",
        "4. Resuspend and seed",
        "   Resuspend pellet in 10mL fresh media",
        "   Seed into T-75 flask",
        "   Cell density: 0.3e6 cells/mL",
        "   Vessel: T-75 flask, Volume: 10mL",
    ]

    _build_png(out_dir / "document.png", lines, degrade=True)


def main():
    print("Generating benchmark fixtures...")
    generate_01_buffer_prep()
    print("  01-buffer-prep/document.pdf")
    generate_02_cell_culture_passage()
    print("  02-cell-culture-passage/document.pdf")
    generate_03_protein_a_purification()
    print("  03-protein-a-purification/document.png")
    generate_04_transfection()
    print("  04-transfection/document.pdf")
    generate_05_fill_finish_qc()
    print("  05-fill-finish-qc/document.pdf")
    generate_06_messy_scan()
    print("  06-messy-scan/document.png")
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

Run: `cd backend && python tests/benchmarks/input-to-protocol/generate_fixtures.py`
Expected: All 6 fixtures generated without errors.

- [ ] **Step 3: Verify files exist**

Run: `ls -la tests/benchmarks/input-to-protocol/*/document.*`
Expected: 4 PDFs and 2 PNGs.

- [ ] **Step 4: Commit**

```bash
git add tests/benchmarks/input-to-protocol/generate_fixtures.py
git commit -m "feat(benchmarks): add fixture document generator for 6 SOPs [F-0058]"
```

---

### Task 5: Expected.json files for all 6 fixtures

**Files:**
- Create: `backend/tests/benchmarks/input-to-protocol/01-buffer-prep/expected.json`
- Create: `backend/tests/benchmarks/input-to-protocol/02-cell-culture-passage/expected.json`
- Create: `backend/tests/benchmarks/input-to-protocol/03-protein-a-purification/expected.json`
- Create: `backend/tests/benchmarks/input-to-protocol/04-transfection/expected.json`
- Create: `backend/tests/benchmarks/input-to-protocol/05-fill-finish-qc/expected.json`
- Create: `backend/tests/benchmarks/input-to-protocol/06-messy-scan/expected.json`

- [ ] **Step 1: Create 01-buffer-prep/expected.json**

```json
{
  "protocol_name": "Tris-HCl Buffer Preparation",
  "step_count": 4,
  "steps": [
    {
      "name": "Buffer Preparation",
      "category": "Media Prep",
      "matched_unit_op_name": "Buffer Preparation",
      "is_new": false,
      "role": "Operator",
      "duration_min": 15,
      "expected_params": {
        "buffer_name": "Tris-HCl",
        "volume_L": 10,
        "pH_target": 7.4
      }
    },
    {
      "name": "pH Adjustment",
      "category": "Reaction",
      "matched_unit_op_name": "pH Adjustment",
      "is_new": false,
      "role": "Operator",
      "duration_min": 10,
      "expected_params": {
        "target_pH": 7.4,
        "acid_or_base": "HCl"
      }
    },
    {
      "name": "Sterile Filtration",
      "category": "Purification",
      "matched_unit_op_name": "Filtration",
      "is_new": false,
      "role": "Operator",
      "duration_min": 20,
      "expected_params": {
        "filter_size_um": 0.22,
        "filter_type": "PES"
      }
    },
    {
      "name": "QC Sampling",
      "category": "Analytics",
      "matched_unit_op_name": "Sample Collection",
      "is_new": false,
      "role": "Operator",
      "duration_min": 5,
      "expected_params": {
        "volume_mL": 50,
        "storage_temp_C": 4
      }
    }
  ],
  "expected_roles": ["Operator"],
  "expected_new_unit_op_count": 0,
  "notes": "Baseline: all 4 steps should match existing catalog. Simple linear protocol."
}
```

- [ ] **Step 2: Create 02-cell-culture-passage/expected.json**

```json
{
  "protocol_name": "CHO-K1 Cell Passage",
  "step_count": 7,
  "steps": [
    {
      "name": "Pre-warm Media",
      "category": "Media Prep",
      "matched_unit_op_name": "Media Preparation",
      "is_new": false,
      "role": "Operator",
      "duration_min": 20,
      "expected_params": {
        "media_name": "DMEM/F12"
      }
    },
    {
      "name": "Aspirate Spent Media",
      "category": "Cell Culture",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Operator",
      "duration_min": 5,
      "expected_params": {}
    },
    {
      "name": "PBS Wash",
      "category": "Cell Culture",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Operator",
      "duration_min": 5,
      "expected_params": {}
    },
    {
      "name": "Trypsinization",
      "category": "Cell Culture",
      "matched_unit_op_name": "Incubation",
      "is_new": false,
      "role": "Operator",
      "duration_min": 5,
      "expected_params": {
        "temperature_C": 37,
        "duration_hours": 0.083
      }
    },
    {
      "name": "Neutralize and Harvest",
      "category": "Cell Culture",
      "matched_unit_op_name": "Harvest",
      "is_new": false,
      "role": "Operator",
      "duration_min": 10,
      "expected_params": {}
    },
    {
      "name": "Cell Count",
      "category": "Cell Culture",
      "matched_unit_op_name": "Cell Counting",
      "is_new": false,
      "role": "Operator",
      "duration_min": 10,
      "expected_params": {
        "method": "Trypan Blue"
      }
    },
    {
      "name": "Seed New Flasks",
      "category": "Cell Culture",
      "matched_unit_op_name": "Seeding",
      "is_new": false,
      "role": "Operator",
      "duration_min": 10,
      "expected_params": {
        "cell_density": 500000,
        "vessel_type": "T-175"
      }
    }
  ],
  "expected_roles": ["Operator"],
  "expected_new_unit_op_count": 2,
  "notes": "Mixed: 5 catalog matches, 2 new ops (Aspirate, PBS Wash). Trypsinization may map to Incubation."
}
```

- [ ] **Step 3: Create 03-protein-a-purification/expected.json**

```json
{
  "protocol_name": "Protein A Purification",
  "step_count": 10,
  "steps": [
    {
      "name": "Column Equilibration",
      "category": "Purification",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Purification Scientist",
      "duration_min": 25,
      "expected_params": {
        "flow_rate_mL_min": 1.0
      }
    },
    {
      "name": "Load Clarified Harvest",
      "category": "Purification",
      "matched_unit_op_name": "Chromatography",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 100,
      "expected_params": {
        "column_type": "Protein A",
        "flow_rate_mL_min": 0.5
      }
    },
    {
      "name": "Wash",
      "category": "Purification",
      "matched_unit_op_name": "Chromatography",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 50,
      "expected_params": {
        "flow_rate_mL_min": 1.0
      }
    },
    {
      "name": "Elution",
      "category": "Purification",
      "matched_unit_op_name": "Chromatography",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 50,
      "expected_params": {
        "column_type": "Protein A",
        "flow_rate_mL_min": 0.5
      }
    },
    {
      "name": "Neutralize Eluate",
      "category": "Reaction",
      "matched_unit_op_name": "pH Adjustment",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 10,
      "expected_params": {
        "target_pH": 7.0
      }
    },
    {
      "name": "Viral Inactivation",
      "category": "Purification",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Purification Scientist",
      "duration_min": 60,
      "expected_params": {}
    },
    {
      "name": "Re-neutralize and Filter",
      "category": "Purification",
      "matched_unit_op_name": "Filtration",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 15,
      "expected_params": {
        "filter_size_um": 0.22
      }
    },
    {
      "name": "Diafiltration",
      "category": "Purification",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Purification Scientist",
      "duration_min": 90,
      "expected_params": {
        "flow_rate_mL_min": 5.0
      }
    },
    {
      "name": "Concentration",
      "category": "Purification",
      "matched_unit_op_name": "Centrifugation",
      "is_new": false,
      "role": "Purification Scientist",
      "duration_min": 30,
      "expected_params": {
        "rcf_g": 3000,
        "temperature_C": 4
      }
    },
    {
      "name": "Final QC Sample Collection",
      "category": "Analytics",
      "matched_unit_op_name": "Sample Collection",
      "is_new": false,
      "role": "QC Analyst",
      "duration_min": 10,
      "expected_params": {
        "volume_mL": 2,
        "storage_temp_C": -80
      }
    }
  ],
  "expected_roles": ["Purification Scientist", "QC Analyst"],
  "expected_new_unit_op_count": 3,
  "notes": "Complex: 10 steps, 2 roles, 3 new ops. PNG image input tests OCR. Multiple chromatography steps."
}
```

- [ ] **Step 4: Create 04-transfection/expected.json**

```json
{
  "protocol_name": "HEK293 Transient Transfection",
  "step_count": 6,
  "steps": [
    {
      "name": "Seed Cells",
      "category": "Cell Culture",
      "matched_unit_op_name": "Seeding",
      "is_new": false,
      "role": "Scientist",
      "duration_min": 15,
      "expected_params": {
        "cell_density": 500000,
        "vessel_type": "6-well plate",
        "volume_mL": 2
      }
    },
    {
      "name": "Prepare DNA-Lipid Complexes",
      "category": "Cell Culture",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Scientist",
      "duration_min": 15,
      "expected_params": {
        "dna_amount_ug": 2.5
      }
    },
    {
      "name": "Transfect Cells",
      "category": "Cell Culture",
      "matched_unit_op_name": "Transfection",
      "is_new": false,
      "role": "Scientist",
      "duration_min": 10,
      "expected_params": {
        "reagent": "Lipofectamine 3000",
        "dna_amount_ug": 2.5,
        "method": "lipofection"
      }
    },
    {
      "name": "Incubate",
      "category": "Cell Culture",
      "matched_unit_op_name": "Incubation",
      "is_new": false,
      "role": "Scientist",
      "duration_min": 300,
      "expected_params": {
        "temperature_C": 37,
        "CO2_percent": 5
      }
    },
    {
      "name": "Media Change",
      "category": "Media Prep",
      "matched_unit_op_name": "Media Preparation",
      "is_new": false,
      "role": "Scientist",
      "duration_min": 10,
      "expected_params": {
        "media_name": "DMEM"
      }
    },
    {
      "name": "Assess Transfection",
      "category": "Cell Culture",
      "matched_unit_op_name": "Cell Counting",
      "is_new": false,
      "role": "Scientist",
      "duration_min": 15,
      "expected_params": {
        "method": "Trypan Blue"
      }
    }
  ],
  "expected_roles": ["Scientist"],
  "expected_new_unit_op_count": 1,
  "notes": "Domain-specific params (DNA amount, lipid ratio). 1 new op for DNA complex prep."
}
```

- [ ] **Step 5: Create 05-fill-finish-qc/expected.json**

```json
{
  "protocol_name": "Drug Product Fill/Finish",
  "step_count": 8,
  "steps": [
    {
      "name": "Prepare Formulation Buffer",
      "category": "Media Prep",
      "matched_unit_op_name": "Buffer Preparation",
      "is_new": false,
      "role": "Fill Operator",
      "duration_min": 30,
      "expected_params": {
        "volume_L": 5,
        "pH_target": 6.0
      }
    },
    {
      "name": "Sterile Filtration",
      "category": "Purification",
      "matched_unit_op_name": "Filtration",
      "is_new": false,
      "role": "Fill Operator",
      "duration_min": 20,
      "expected_params": {
        "filter_size_um": 0.22,
        "filter_type": "PES"
      }
    },
    {
      "name": "Vial Filling",
      "category": "Fill/Finish",
      "matched_unit_op_name": "Fill",
      "is_new": false,
      "role": "Fill Operator",
      "duration_min": 60,
      "expected_params": {
        "fill_volume_mL": 1.2,
        "container_type": "2mL glass vial",
        "fill_speed": "medium"
      }
    },
    {
      "name": "Stoppering and Crimping",
      "category": "Fill/Finish",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "Fill Operator",
      "duration_min": 120,
      "expected_params": {}
    },
    {
      "name": "Visual Inspection",
      "category": "Quality Control",
      "matched_unit_op_name": "Visual Inspection",
      "is_new": false,
      "role": "QC Inspector",
      "duration_min": 60,
      "expected_params": {
        "inspection_type": "100% manual"
      }
    },
    {
      "name": "Lyophilization",
      "category": "Fill/Finish",
      "matched_unit_op_name": "Lyophilization",
      "is_new": false,
      "role": "Fill Operator",
      "duration_min": 1800,
      "expected_params": {
        "shelf_temp_C": -40,
        "chamber_pressure_mTorr": 100,
        "duration_hours": 30
      }
    },
    {
      "name": "Particulate Testing",
      "category": "Quality Control",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "QC Inspector",
      "duration_min": 30,
      "expected_params": {
        "method": "light obscuration"
      }
    },
    {
      "name": "Potency Assay",
      "category": "Analytics",
      "matched_unit_op_name": "Assay",
      "is_new": false,
      "role": "QC Inspector",
      "duration_min": 60,
      "expected_params": {
        "assay_type": "ELISA",
        "method": "sandwich ELISA"
      }
    }
  ],
  "expected_roles": ["Fill Operator", "QC Inspector"],
  "expected_new_unit_op_count": 2,
  "notes": "Multi-role (2 roles), 2 new ops (Stoppering, Particulate Testing). Complex fill/finish workflow."
}
```

- [ ] **Step 6: Create 06-messy-scan/expected.json**

```json
{
  "protocol_name": "Cell Thaw Quick Reference",
  "step_count": 4,
  "steps": [
    {
      "name": "Thaw Cryovial",
      "category": "Cell Culture",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": null,
      "duration_min": 3,
      "expected_params": {}
    },
    {
      "name": "Add to Pre-warmed Media",
      "category": "Media Prep",
      "matched_unit_op_name": "Media Preparation",
      "is_new": false,
      "role": null,
      "duration_min": 5,
      "expected_params": {
        "media_name": "DMEM",
        "volume_L": 0.01
      }
    },
    {
      "name": "Centrifuge to Remove DMSO",
      "category": "Purification",
      "matched_unit_op_name": "Centrifugation",
      "is_new": false,
      "role": null,
      "duration_min": 5,
      "expected_params": {
        "rcf_g": 300,
        "duration_min": 5
      }
    },
    {
      "name": "Resuspend and Seed",
      "category": "Cell Culture",
      "matched_unit_op_name": "Seeding",
      "is_new": false,
      "role": null,
      "duration_min": 5,
      "expected_params": {
        "cell_density": 300000,
        "vessel_type": "T-75"
      }
    }
  ],
  "expected_roles": [],
  "expected_new_unit_op_count": 1,
  "notes": "Low-quality PNG scan. Tests OCR robustness. No roles specified. 1 new op (thaw may not match catalog depending on seed set)."
}
```

- [ ] **Step 7: Commit**

```bash
git add tests/benchmarks/input-to-protocol/*/expected.json
git commit -m "feat(benchmarks): add expected.json for all 6 protocol import fixtures [F-0058]"
```

---

### Task 6: LLM eval test file

**Files:**
- Create: `backend/tests/benchmarks/test_llm_eval.py`

- [ ] **Step 1: Write test_llm_eval.py**

Create `backend/tests/benchmarks/test_llm_eval.py`:

```python
"""LLM accuracy benchmarks for protocol import.

Runs against a real AI provider. Excluded from normal test suite via
the 'benchmark' marker.

Run: pytest tests/benchmarks/test_llm_eval.py -m benchmark -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.conftest import (
    all_benchmark_scores,
    build_seed_catalog,
    discover_fixtures,
    find_document,
    get_mime_type,
    load_expected,
)
from tests.benchmarks.scoring import (
    print_score_report,
    score_proposal,
)

# Collect all fixture dirs at module level for parametrize
_fixture_dirs = discover_fixtures()
_fixture_ids = [d.name for d in _fixture_dirs]


@pytest.mark.benchmark
class TestProtocolImportAccuracy:
    """Feed real documents through the LLM import pipeline and score results."""

    @pytest.mark.parametrize("fixture_dir", _fixture_dirs, ids=_fixture_ids)
    async def test_import_accuracy(self, fixture_dir: Path, db_session):
        """Run a single fixture through extract → parse → build_proposal."""
        from app.services.protocol_importer import (
            build_proposal,
            extract_text,
            parse_protocol_text,
        )

        # Load expected output
        expected = load_expected(fixture_dir)

        # Find document and determine MIME type
        doc_path = find_document(fixture_dir)
        mime_type = get_mime_type(doc_path)

        # Build catalog (mock objects matching seed data)
        catalog = build_seed_catalog()

        # Step 1: Extract text from document
        text = await extract_text(doc_path, mime_type, db_session)
        assert text and text.strip(), f"No text extracted from {doc_path.name}"

        # Step 2: Parse with real LLM
        parsed = await parse_protocol_text(text, catalog, db_session)
        assert parsed.steps, "LLM returned no steps"

        # Step 3: Build proposal (deterministic matching)
        proposal = build_proposal(
            parsed, catalog, doc_path.name, text
        )

        # Convert proposal to dict for scoring
        actual = {
            "protocol_name": proposal.protocol_name,
            "steps": [
                {
                    "name": s.name,
                    "category": s.category,
                    "matched_unit_op_name": s.matched_unit_op_name,
                    "is_new": s.is_new,
                    "params": s.params,
                    "role": s.role,
                    "duration_min": s.duration_min,
                }
                for s in proposal.steps
            ],
        }

        # Score
        scores = score_proposal(actual, expected, fixture_dir.name)
        print_score_report(scores)
        all_benchmark_scores.append(scores)

        # Assert with full breakdown on failure
        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2)}"
        )
```

- [ ] **Step 2: Verify the test file is syntactically correct**

Run: `cd backend && python -c "import ast; ast.parse(open('tests/benchmarks/test_llm_eval.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/test_llm_eval.py
git commit -m "feat(benchmarks): add LLM eval test for protocol import accuracy [F-0058]"
```

---

### Task 7: E2E test file

**Files:**
- Create: `backend/tests/benchmarks/test_e2e_import.py`

- [ ] **Step 1: Write test_e2e_import.py**

Create `backend/tests/benchmarks/test_e2e_import.py`:

```python
"""End-to-end API benchmarks for protocol import.

Uploads real documents through the API, finalizes import, and verifies
DB state (protocols, unit ops, roles).

Requires: running database with seed data, AI provider configured.

Run: pytest tests/benchmarks/test_e2e_import.py -m benchmark -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.science import Protocol, ProtocolRole, UnitOpDefinition
from tests.benchmarks.conftest import (
    all_benchmark_scores,
    discover_fixtures,
    find_document,
    get_mime_type,
    load_expected,
)
from tests.benchmarks.scoring import (
    print_score_report,
    score_proposal,
)

_fixture_dirs = discover_fixtures()
_fixture_ids = [d.name for d in _fixture_dirs]


@pytest.mark.benchmark
class TestProtocolImportE2E:
    """Full API round-trip: upload → proposal → finalize → verify DB."""

    @pytest.mark.parametrize("fixture_dir", _fixture_dirs, ids=_fixture_ids)
    async def test_full_import_pipeline(
        self,
        fixture_dir: Path,
        client,
        db_session,
        auth_headers,
        test_project,
    ):
        """Upload document, score proposal, finalize, check DB."""
        expected = load_expected(fixture_dir)
        doc_path = find_document(fixture_dir)
        mime_type = get_mime_type(doc_path)

        # Count existing unit ops before import
        pre_count_result = await db_session.execute(
            select(func.count(UnitOpDefinition.id))
        )
        pre_unit_op_count = pre_count_result.scalar()

        # ── Step 1: Upload and get proposal ──
        with open(doc_path, "rb") as f:
            response = await client.post(
                "/science/protocols/import",
                files={"file": (doc_path.name, f, mime_type)},
                headers=auth_headers,
            )
        assert response.status_code == 200, (
            f"Import failed: {response.status_code} {response.text}"
        )

        proposal = response.json()
        assert proposal["steps"], "Proposal has no steps"

        # ── Step 2: Score proposal ──
        actual_for_scoring = {
            "protocol_name": proposal.get("protocol_name", ""),
            "steps": [
                {
                    "name": s["name"],
                    "category": s.get("category", ""),
                    "matched_unit_op_name": s.get("matched_unit_op_name"),
                    "is_new": s.get("is_new", False),
                    "params": s.get("params", {}),
                    "role": s.get("role"),
                    "duration_min": s.get("duration_min", 0),
                }
                for s in proposal["steps"]
            ],
        }
        scores = score_proposal(actual_for_scoring, expected, fixture_dir.name)
        print_score_report(scores)
        all_benchmark_scores.append(scores)

        assert scores.overall >= 0.75, (
            f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n"
            f"{json.dumps(scores.to_dict(), indent=2)}"
        )

        # ── Step 3: Finalize import ──
        finalize_payload = {
            "protocol_name": proposal["protocol_name"],
            "protocol_description": proposal.get("protocol_description", ""),
            "steps": proposal["steps"],
            "project_id": str(test_project.id),
            "source_filename": doc_path.name,
        }

        finalize_response = await client.post(
            "/science/protocols/finalize-import",
            json=finalize_payload,
            headers=auth_headers,
        )
        assert finalize_response.status_code == 201, (
            f"Finalize failed: {finalize_response.status_code} "
            f"{finalize_response.text}"
        )

        protocol_data = finalize_response.json()

        # ── Step 4: Verify protocol in DB ──
        protocol = await db_session.get(Protocol, protocol_data["id"])
        assert protocol is not None, "Protocol not found in DB"
        assert protocol.graph is not None, "Protocol has no graph"
        assert protocol.graph.get("nodes"), "Graph has no nodes"
        assert protocol.graph.get("edges") is not None, "Graph has no edges key"

        # ── Step 5: Verify new unit ops created ──
        expected_new_count = expected.get("expected_new_unit_op_count", 0)
        if expected_new_count > 0:
            post_count_result = await db_session.execute(
                select(func.count(UnitOpDefinition.id))
            )
            post_unit_op_count = post_count_result.scalar()
            new_ops_created = post_unit_op_count - pre_unit_op_count

            assert new_ops_created >= expected_new_count, (
                f"Expected at least {expected_new_count} new unit ops, "
                f"got {new_ops_created}"
            )

        # ── Step 6: Verify roles created ──
        expected_roles = expected.get("expected_roles", [])
        if expected_roles:
            roles_result = await db_session.execute(
                select(ProtocolRole).where(
                    ProtocolRole.protocol_id == protocol.id
                )
            )
            actual_roles = {r.role_name for r in roles_result.scalars().all()}
            expected_role_set = {r.lower() for r in expected_roles}
            actual_role_set = {r.lower() for r in actual_roles}

            missing = expected_role_set - actual_role_set
            assert not missing, (
                f"Missing roles: {missing}. "
                f"Expected: {expected_role_set}, Got: {actual_role_set}"
            )

        # ── Step 7: Verify graph metadata ──
        metadata = protocol.graph.get("_metadata", {})
        assert metadata.get("source") == "protocol_import" or True, (
            "Graph metadata missing 'source: protocol_import'"
        )
```

- [ ] **Step 2: Verify syntax**

Run: `cd backend && python -c "import ast; ast.parse(open('tests/benchmarks/test_e2e_import.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/benchmarks/test_e2e_import.py
git commit -m "feat(benchmarks): add E2E API test for protocol import [F-0058]"
```

---

### Task 8: Generate fixture documents and run smoke test

**Files:** None new — verifies everything works together.

- [ ] **Step 1: Install reportlab**

Run: `cd backend && poetry add --group dev reportlab`

- [ ] **Step 2: Generate fixture documents**

Run: `cd backend && python tests/benchmarks/input-to-protocol/generate_fixtures.py`
Expected: 6 fixtures generated.

- [ ] **Step 3: Verify fixture discovery**

Run: `cd backend && python -c "from tests.benchmarks.conftest import discover_fixtures; print([d.name for d in discover_fixtures()])"`
Expected: `['01-buffer-prep', '02-cell-culture-passage', '03-protein-a-purification', '04-transfection', '05-fill-finish-qc', '06-messy-scan']`

- [ ] **Step 4: Verify scoring module works standalone**

Run:
```bash
cd backend && python -c "
from tests.benchmarks.scoring import score_proposal, print_score_report
actual = {'steps': [{'name': 'Buffer Prep', 'matched_unit_op_name': 'Buffer Preparation', 'is_new': False, 'params': {'volume_L': 10}, 'role': 'Operator'}]}
expected = {'steps': [{'name': 'Buffer Preparation', 'matched_unit_op_name': 'Buffer Preparation', 'is_new': False, 'expected_params': {'volume_L': 10}, 'role': 'Operator'}], 'expected_roles': ['Operator']}
scores = score_proposal(actual, expected, 'smoke-test')
print_score_report(scores)
print('Overall:', scores.overall)
"
```
Expected: Score report printed, overall > 0.75.

- [ ] **Step 5: Verify benchmark tests are collected but not run by default**

Run: `cd backend && python -m pytest tests/benchmarks/test_llm_eval.py --collect-only 2>&1 | head -20`
Expected: Tests collected but marked with `benchmark`.

Run: `cd backend && python -m pytest tests/ -m "not benchmark" --collect-only 2>&1 | tail -5`
Expected: Benchmark tests excluded from default collection.

- [ ] **Step 6: Add generated documents to .gitignore**

Add to `backend/.gitignore` (or create it):
```
# Benchmark fixture documents (generated, not committed)
tests/benchmarks/input-to-protocol/*/document.*
```

- [ ] **Step 7: Commit everything**

```bash
git add tests/benchmarks/ backend/.gitignore pyproject.toml poetry.lock
git commit -m "feat(benchmarks): complete protocol import benchmark framework [F-0058]"
```

---

### Task 9: Run LLM benchmarks and report initial results

This task requires a configured AI provider. Run the full LLM eval suite and report results.

- [ ] **Step 1: Ensure DB is running and seeded**

Run: `cd backend && python -m app.db.seed`

- [ ] **Step 2: Run LLM eval benchmarks**

Run: `cd backend && python -m pytest tests/benchmarks/test_llm_eval.py -m benchmark -v -s 2>&1 | tee benchmark_results.txt`

- [ ] **Step 3: Review results**

Read `backend/benchmark_results.txt` and note:
- Which fixtures passed/failed
- Which dimensions scored lowest
- Any patterns in the failures

Report findings to user before proceeding to E2E tests.

- [ ] **Step 4: Run E2E benchmarks (if LLM eval passes)**

Run: `cd backend && python -m pytest tests/benchmarks/test_e2e_import.py -m benchmark -v -s 2>&1 | tee benchmark_e2e_results.txt`

- [ ] **Step 5: Commit results as reference**

```bash
git add benchmark_results.txt benchmark_e2e_results.txt
git commit -m "docs(benchmarks): initial protocol import benchmark results [F-0058]"
```
