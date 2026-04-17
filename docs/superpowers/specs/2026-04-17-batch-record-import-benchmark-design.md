# Batch Record Import Benchmark — Design

**Task:** F-0057 follow-up — add a proper LLM accuracy benchmark for the paper batch-record import pipeline, paralleling the existing F-0058 protocol-import benchmark.

**Date:** 2026-04-17

## Problem

F-0057 (paper batch-record → run) shipped with four scenario fixture PDFs + expected JSONs, but nothing scores against them. The sole "LLM eval" at `backend/tests/integration/test_batch_record_import_llm.py` runs a single smoke PDF through the pipeline and asserts only that `len(steps) > 0` and `overall_confidence > 0.0`. The expected-JSON fixtures are orphaned.

F-0058 (document → protocol) has the desired pattern: `backend/tests/benchmarks/input-to-protocol/<scenario>/` directories, a `scoring.py` module that weights five accuracy dimensions, a parametrized runner marked `-m benchmark`, and a pass threshold of ≥0.75 per fixture. `optimize-benchmarks` iterates against that marker.

Goal: close the gap — migrate the orphaned fixtures into the benchmark structure, add stage-separated scoring (extraction + mapping), and make the suite `-m benchmark`-compatible so `optimize-benchmarks` can drive prompt improvements.

## Scope

Covers both LLM stages of the batch-record pipeline, scored separately:

1. **Extraction** — `extract_batch_record_data(text, page_images, db_session) -> BatchRecordExtraction`. Measures "what's in this document?" accuracy.
2. **Protocol mapping** — `map_steps_to_protocol(extraction, protocol_graph, db_session) -> list[StepMapping]`. Measures "how does the extraction align to this target protocol?" accuracy.

Not covered: the `finalize` endpoint that creates a Run from the reviewed mapping (pure data construction, no LLM).

## Architecture

Mirror F-0058's structure:

```
backend/tests/benchmarks/
  scoring.py                    # existing — F-0058 only
  batch_record_scoring.py       # NEW — stage 1 + stage 2 scorers
  test_llm_eval.py              # existing — adds TestBatchRecordAccuracy class
  conftest.py                   # extend: batch-record fixture discovery; promote pro_org to module scope for reuse
  input-to-protocol/            # existing
  document-to-run/              # NEW
    01-perfect-match/
      document.pdf
      protocol.json
      expected_extraction.json
      expected_mapping.json
    02-wrong-protocol/          # same shape
    03-half-complete/           # same shape
    04-extra-steps/             # same shape
    05-messy-scan/              # same shape — handwritten / OCR-degraded
```

Same `-m benchmark` marker, same `pro_org` fixture, same `>=0.75` threshold, same `print_score_report` style.

## Components

### 1. `batch_record_scoring.py`

Two public entry points mirroring F-0058's `score_proposal`:

```python
def score_extraction(
    actual: BatchRecordExtraction,
    expected: dict,
    fixture_name: str,
) -> ExtractionScores: ...

def score_mapping(
    actual: list[StepMapping],
    expected: dict,
    fixture_name: str,
) -> MappingScores: ...
```

#### Dataclasses

```python
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
    # overall + passed analogous to above
```

#### Internal helpers

- `_fuzzy_match(a: str, b: str) -> float` — `difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()`. Threshold 0.85 for a "match" on step names and field labels.
- `_align_steps(expected, actual) -> list[tuple[dict|None, dict|None]]` — greedy best-match on step_name, returns aligned pairs (with `None` on either side for misses/extras).
- `_numeric_equal(a, b) -> bool` — ±5% relative tolerance, or ±0.01 absolute for |a| < 0.2 (covers pH).
- `_unit_equal(a, b) -> bool` — normalize case, strip whitespace, map synonyms: `°C`↔`C`↔`c`, `μm`↔`um`↔`micron`, `mL`↔`ml`, `g`↔`G` (only when context is centrifugal; treat as case-insensitive equality otherwise).
- `_confidence_correlation(extraction, expected) -> float` — bucket each param into high-conf (>=0.9), mid (0.6–0.9), low (<0.6); check the proportion of high-conf that's actually correct (by value match). Returns a scalar in [0,1].

### 2. Fixture discovery

Extend `backend/tests/benchmarks/conftest.py`:

```python
DOCUMENT_TO_RUN_DIR = BENCHMARKS_DIR / "document-to-run"

def discover_batch_record_fixtures() -> list[Path]:
    if not DOCUMENT_TO_RUN_DIR.exists():
        return []
    return sorted(
        d for d in DOCUMENT_TO_RUN_DIR.iterdir()
        if d.is_dir() and (d / "expected_extraction.json").exists()
    )

def load_expected_extraction(fixture_dir: Path) -> dict: ...
def load_protocol(fixture_dir: Path) -> dict | None: ...
def load_expected_mapping(fixture_dir: Path) -> dict | None: ...
```

Reuse existing `find_document`, `get_mime_type`.

### 3. Runner

Add to `backend/tests/benchmarks/test_llm_eval.py`:

```python
_br_fixture_dirs = discover_batch_record_fixtures()
_br_ids = [d.name for d in _br_fixture_dirs]

@pytest.mark.benchmark
class TestBatchRecordAccuracy:
    # pro_org fixture promoted to conftest module scope so both
    # TestProtocolImportAccuracy and TestBatchRecordAccuracy share it.

    @pytest.mark.parametrize("fixture_dir", _br_fixture_dirs, ids=_br_ids)
    async def test_batch_record_accuracy(self, fixture_dir, db_session, pro_org):
        # Stage 1: extraction
        doc = find_document(fixture_dir)
        text, page_images = await extract_batch_record_pages(
            doc, get_mime_type(doc), db_session,
        )
        extraction = await extract_batch_record_data(
            text, page_images, db_session,
        )
        expected_extraction = load_expected_extraction(fixture_dir)
        ext_scores = score_extraction(
            extraction, expected_extraction, fixture_dir.name,
        )
        print_extraction_report(ext_scores)
        all_benchmark_scores.append(ext_scores)
        assert ext_scores.overall >= 0.75, (
            f"{fixture_dir.name} extraction: {ext_scores.overall:.0%}\n"
            f"{json.dumps(ext_scores.to_dict(), indent=2)}"
        )

        # Stage 2: mapping (only if protocol.json exists)
        protocol = load_protocol(fixture_dir)
        if protocol is None:
            return
        expected_mapping = load_expected_mapping(fixture_dir)
        if expected_mapping is None:
            pytest.fail(
                f"{fixture_dir.name}: protocol.json exists but "
                f"expected_mapping.json is missing"
            )
        mappings = await map_steps_to_protocol(
            extraction, protocol, db_session,
        )
        map_scores = score_mapping(
            mappings, expected_mapping, fixture_dir.name,
        )
        print_mapping_report(map_scores)
        all_benchmark_scores.append(map_scores)
        assert map_scores.overall >= 0.75, (
            f"{fixture_dir.name} mapping: {map_scores.overall:.0%}\n"
            f"{json.dumps(map_scores.to_dict(), indent=2)}"
        )
```

### 4. Expected-mapping fixture format

```json
{
  "step_mappings": [
    {
      "extracted_step_name": "Buffer Preparation",
      "protocol_step_name": "Buffer Prep",
      "mapped": true,
      "param_mappings": [
        { "extracted_label": "pH", "schema_field_key": "ph_value" },
        { "extracted_label": "Temperature", "schema_field_key": "temperature_c" }
      ]
    }
  ],
  "unmapped_protocol_steps": ["Post-Clarification QC"],
  "unmapped_extracted_steps": ["Extra Handwritten Step"]
}
```

- `unmapped_protocol_steps`: protocol steps that SHOULD be N/A for this document (feeds `na_detection` scoring).
- `unmapped_extracted_steps`: extracted steps that SHOULDN'T map to any protocol step (feeds `extra_step_handling` scoring).

### 5. Scoring dimension details

#### Stage 1 — extraction

- **`step_detection` (25%):** F1 over step names. For each expected step, mark "found" if any extracted step fuzzy-matches ≥ 0.85. Precision and recall computed, F1 returned.
- **`param_extraction` (25%):** per aligned step pair, for each expected param: 1/3 point if field_label fuzzy-matches, 1/3 if value within tolerance, 1/3 if unit matches. Summed and normalized.
- **`timestamps` (15%):** F1 over timestamp `(step_name, label, value)` tuples. Value fuzzy-match (handwritten "08:30" ↔ "8:30 AM"). Zero weight when no step has expected timestamps.
- **`metadata` (10%):** 4 fields (document_title, batch_id, product_name, date), each worth 0.25. Fuzzy match on strings.
- **`signatures_deviations` (15%):** average of two sub-scores — F1 over signatures (by initials_or_name fuzzy-match) and F1 over deviations (fuzzy-match on notes text, threshold 0.6). Missing entirely from expected → dimension skipped and weight redistributed.
- **`confidence_calibration` (10%):** correctness rate of params bucketed by reported confidence. Expected: ≥0.9 bucket has ≥90% correct, 0.6–0.9 has ≥60%, <0.6 has unconstrained (just shouldn't exceed 80% correct). Returns fraction of buckets meeting their target.

#### Stage 2 — mapping

- **`step_matching` (35%):** of extracted steps that should map to a protocol step, fraction mapped to the correct one.
- **`param_field_matching` (30%):** over correctly-mapped steps, fraction of param labels mapped to the correct `schema_field_key`.
- **`na_detection` (15%):** of protocol steps listed in `unmapped_protocol_steps`, fraction correctly left unmapped (no extracted step claims them). If the expected list is empty, dimension scored 1.0 (no misses possible).
- **`extra_step_handling` (10%):** of extracted steps listed in `unmapped_extracted_steps`, fraction correctly flagged as unmapped (no `StepMapping` produced). If expected list is empty, dimension scored 1.0.
- **`mapping_confidence` (10%):** for each `StepMapping`, its `score` field should be ≥0.8 for correct matches and ≤0.5 for wrong ones. Fraction of mappings where confidence-correctness correlation holds.

## Error handling & edge cases

- **Missing `protocol.json`:** skip stage 2 cleanly — fixture is extraction-only. Test passes if extraction passes.
- **Missing `expected_mapping.json` but `protocol.json` present:** `pytest.fail` with misconfiguration message — prevents silent skips.
- **LLM unavailable:** tests are `-m benchmark`, excluded from default `pytest` run. CI doesn't run them. Manual invocation required; missing provider credentials raise at `get_model`.
- **Numeric tolerance:** `_numeric_equal(a, b)`: |a - b| / max(|a|, |b|, 1e-9) ≤ 0.05, OR |a - b| ≤ 0.01. Second clause handles pH near 7.0.
- **Unit normalization:** build a small synonym map once, apply both sides before comparing. Treat missing unit on one side as "no-match" only when the other side has a unit.
- **Dimension zero-weight redistribution:** if a fixture legitimately has no timestamps or no deviations, that dimension is omitted and its weight is proportionally redistributed across the remaining dimensions. Prevents `03-half-complete` from being unfairly penalized.
- **Step alignment ambiguity:** greedy best-match by fuzzy ratio. If two expected steps fuzzy-match one actual step (e.g. "Buffer Prep" vs. "Buffer Preparation" vs. "Prep Buffer"), the first expected step wins and the second is marked missed. Document this — it's a known limitation, acceptable for the current fixtures.

## Migration

### Move (rename, don't duplicate)

- `backend/tests/fixtures/batch_record_perfect_match.pdf` → `backend/tests/benchmarks/document-to-run/01-perfect-match/document.pdf`
- `batch_record_perfect_match_expected.json` → `.../01-perfect-match/expected_extraction.json`
- Same rename pattern for `wrong_protocol` → `02-wrong-protocol`, `half_complete` → `03-half-complete`, `extra_steps` → `04-extra-steps`.

### Author new

For each of the 4 migrated scenarios:
- `protocol.json` — a protocol graph with `nodes[]` and `edges[]` matching the scenario's intended target. For `02-wrong-protocol`, the protocol intentionally differs from what the document describes. Format follows existing protocol graph structure (see `_parse_graph_roles_and_steps`).
- `expected_mapping.json` — ground-truth step + param mappings and unmapped lists as specified in §4.

### Create from scratch

- `05-messy-scan/document.pdf` — handwritten or low-quality scan. I'll generate a plausible messy batch record (scanned photo of printed form with handwritten fills, or fully handwritten) via the template-generation scripts or hand-crafted.
- `05-messy-scan/{protocol.json, expected_extraction.json, expected_mapping.json}`.

### Delete

- `backend/tests/integration/test_batch_record_import_llm.py` (smoke test, superseded)
- `backend/tests/fixtures/sample_batch_record.pdf`
- `backend/tests/fixtures/sample_batch_record_extraction.json`
- Any unused fixtures after migration

## Testing the benchmark itself

Unit tests for `batch_record_scoring.py` (NOT LLM-dependent — run in normal suite):

- `tests/unit/test_batch_record_scoring.py`:
  - Perfect match inputs → 1.0 across all dims
  - Missing expected step → `step_detection` drops, `details.steps_missed` populated
  - Wrong param value → `param_extraction` drops, `details.param_value_mismatches` populated
  - Wrong unit with synonym (°C vs C) → still counts as match
  - Out-of-tolerance numeric (pH 7.2 vs 7.3) → miss; in-tolerance (pH 7.00 vs 7.01) → match
  - Mapping: all correct → 1.0; one step mis-mapped → `step_matching` drops by 1/N
  - na_detection: protocol has 3 expected-N/A steps, all correctly unmapped → 1.0; one falsely mapped → 2/3

These are fast unit tests. Gives the scorer its own ground truth, independent of LLM output.

## Invocation

```bash
# run only batch-record benchmark
pytest backend/tests/benchmarks/test_llm_eval.py::TestBatchRecordAccuracy -m benchmark -v -s

# run all benchmarks (protocol import + batch record)
pytest -m benchmark -v -s

# scorer unit tests (fast, no LLM)
pytest backend/tests/unit/test_batch_record_scoring.py -v
```

## Open questions / known limitations

- **Greedy step alignment** doesn't handle ambiguous many-to-one expected/actual mappings. Acceptable for the 5 designed fixtures; revisit if future fixtures exercise it.
- **Messy-scan fixture generation** — exact approach (synthetic handwritten vs. real scanned photo) to be decided during implementation. Preference: use the existing `tests/artifacts/templates` workflow to produce a "filled" DOCX, print + scan or simulate scan artifacts (blur, noise, rotation) in Pillow.
- **Scoring evolves with fixtures** — as we add scenarios that reveal new failure modes, dimensions/weights may need tuning. Keep `batch_record_scoring.py` small and readable to make that easy.

## Out of scope

- Benchmarking the `finalize` endpoint (pure data construction, no LLM).
- Benchmarking PDF rendering of batch records (covered by docxtpl-side tests in F-0065).
- Cross-language batch records (English only for now).
- Automated benchmark runs in CI — remains manual (cost + LLM provider dependency).
