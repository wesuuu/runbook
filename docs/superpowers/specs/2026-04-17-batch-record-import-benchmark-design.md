# Batch Record Import Benchmark — Design

**Task:** F-0057 follow-up — add a Run-output benchmark for the paper batch-record import pipeline, paralleling the existing F-0058 protocol-import benchmark. Also: extend the pipeline to preserve timestamps, signatures, and deviations in the final Run so the benchmark measures output that actually reaches production.

**Date:** 2026-04-17 (revised)

## Problem

F-0057 (paper batch-record → Run) shipped with four scenario fixture PDFs + expected JSONs, but nothing scores against them. The existing smoke test at `backend/tests/integration/test_batch_record_import_llm.py` runs a single sample PDF through the pipeline and only asserts `len(steps) > 0` and `overall_confidence > 0.0`. The expected-JSON fixtures are orphaned.

F-0058 (document → protocol) has the desired pattern: `backend/tests/benchmarks/input-to-protocol/<scenario>/` directories, a `scoring.py` module, a parametrized runner marked `-m benchmark`, and a pass threshold of ≥0.75 per fixture. `optimize-benchmarks` iterates against that marker.

A second gap: the current `map_values_to_execution_data` ([batch_record_extractor.py:734-776](backend/app/services/batch_record_extractor.py#L734-L776)) builds `Run.execution_data` with only `{status, results, notes, completed_by_user_id, timestamp}`. Extracted timestamps, signatures, and deviations from the source document are dropped. Time-sensitive historical runs need these preserved.

Goal: close both gaps — preserve the missing fields in the Run, and add a `-m benchmark`-compatible suite that scores the end-to-end Run output against hand-authored ground truth.

## Scope

1. **Product changes (backend + frontend):** extend `FinalizedStepMapping` schema, extend `map_values_to_execution_data`, pass timestamps/signatures/deviations through the frontend finalize payload. No UI editing in v1 — auto-pass-through from extraction.
2. **Benchmark:** single Run-output scorer. Reads a fixture's `document.pdf` + `protocol.json`, runs the full extract → map → build-execution-data pipeline, compares the resulting `execution_data + run metadata` to `expected_run.json`. Scores across 8 dimensions. Pass threshold per fixture ≥0.75.

Out of scope:
- Frontend editing UI for timestamps/signatures/deviations (follow-up task).
- Benchmarking the `finalize` endpoint HTTP contract (no LLM, covered by existing integration tests).
- Benchmarking PDF rendering.
- Cross-language batch records.
- Automated benchmark runs in CI — remains manual (cost + LLM provider dependency).

## Architecture

### Fixture layout

```
backend/tests/benchmarks/
  scoring.py                    # existing — F-0058 only
  matching.py                   # existing — shared helpers
  batch_record_scoring.py       # NEW — Run scorer
  test_llm_eval.py              # extend: adds TestBatchRecordAccuracy
  conftest.py                   # extend: pro_org module fixture, summary hook
  input-to-protocol/            # existing (F-0058)
  document-to-run/              # populated in Task 1 (fixture migration)
    01-perfect-match/
      document.pdf              # already migrated
      protocol.json             # NEW — target protocol graph
      expected_run.json         # NEW — ground-truth Run output
    02-wrong-protocol/          # same shape
    03-half-complete/           # same shape
    04-extra-steps/             # same shape
    05-messy-scan/              # same shape — handwritten / OCR-degraded
```

The existing `expected_extraction.json` files (one per scenario) are **deleted** — they describe the old two-stage approach. The new `expected_run.json` is the single ground-truth artifact per fixture.

Same `-m benchmark` marker, same `pro_org` fixture (promoted to conftest module scope), same `>=0.75` threshold, consistent `print_..._report` style with F-0058.

## Product changes

### Backend

**1. Schema extension** — `backend/app/schemas/batch_record_import.py`:

```python
class FinalizedStepMapping(BaseModel):
    protocol_step_id: str
    values: List[FinalizedValue] = []
    notes: str = ""
    na: bool = False
    na_reason: str = ""
    # NEW:
    timestamps: List[ExtractedTimestampResponse] = []
    signatures: List[ExtractedSignatureResponse] = []
    deviations: List[ExtractedDeviationResponse] = []
```

**2. `map_values_to_execution_data`** — `backend/app/services/batch_record_extractor.py:734-776`:

```python
execution_data[step_id] = {
    "status": "completed",
    "results": results,
    "notes": notes,
    # NEW fields (empty lists if not provided — backward compatible):
    "timestamps": mapping.get("timestamps", []),
    "signatures": mapping.get("signatures", []),
    "deviations": mapping.get("deviations", []),
    "completed_by_user_id": str(user_id),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
```

Execution_data is JSONB — no DB migration. Existing Runs are unaffected (new keys simply absent for old runs).

**3. Integration tests** — `backend/tests/integration/test_batch_record_import_api.py` (existing file). Add one test that finalizes a batch record import with timestamps/signatures/deviations on at least one step, and asserts the resulting `Run.execution_data[step_id]` contains those three keys with the expected values.

### Frontend

**4. Finalize payload pass-through** — `frontend/src/lib/components/BatchRecordImportModal.svelte` (or wherever the finalize mutation is assembled). When building `step_mappings` for the POST body, include `timestamps`, `signatures`, `deviations` from the per-step extraction result. No user edit UI in v1 — these fields are auto-populated from what the extractor produced.

**5. Zod schema update** — `frontend/src/lib/schemas/batchRecordImport.ts` (or wherever the `FinalizedStepMapping` shape is defined). Add the three optional list fields to mirror the backend schema.

### Display (deferred)

The run detail view already renders `execution_data[step_id].results` and `notes`. Rendering `timestamps / signatures / deviations` is a follow-up task — the benchmark doesn't require it.

## Benchmark components

### `batch_record_scoring.py`

Single public entry point:

```python
def score_run(
    actual_execution_data: dict,
    actual_run_metadata: dict,
    expected_run: dict,
    protocol_graph: dict,
    fixture_name: str,
) -> RunScores: ...
```

Returns a dataclass with per-dimension floats, a weighted `overall` property, `passed` flag (≥0.75), and a `details` sub-dataclass. Same structural shape as F-0058's `BenchmarkScores`.

**Dimensions (8, weights sum to 100%):**

| Dimension | Weight | Measures |
|---|---|---|
| `step_completeness` | 20% | Set equality of protocol_step_ids that have populated execution data between actual and expected |
| `param_accuracy` | 25% | Per completed step: right schema_field keys populated with right values (numeric tolerance + unit normalization) |
| `timestamps` | 15% | Per-step `(label, value)` tuples captured; F1 over tuples |
| `signatures` | 10% | Per-step `(initials_or_name, role)` captured; F1 |
| `deviations` | 10% | Per-step `description` captured; F1 (threshold 0.6 on description fuzzy match) |
| `na_correctness` | 10% | Steps correctly marked `status: "na"` vs. `"completed"` |
| `notes_preservation` | 5% | Step `notes` string preserved (fuzzy match ≥0.7) |
| `run_metadata` | 5% | `run_name` matches expected (fuzzy ≥0.8) |

**Pass threshold:** overall ≥ 0.75 per fixture.

Reports: `print_run_report(scores)` per fixture and `print_run_summary(all_scores)` as the aggregated terminal summary table.

### Scoring helpers

Reuse what already exists:
- `matching.fuzzy_ratio`, `matching.align_by_name`, `matching.f1` (shared module from Task 2)
- Numeric tolerance (±5% relative OR ±0.01 absolute)
- Unit normalization (°C↔C, μm↔um, mL↔ml, etc.)

The numeric/unit helpers need to be re-introduced in `batch_record_scoring.py` since they were removed by the reset. Keep them here (not in `matching.py`) because they're lab-domain-specific.

### `expected_run.json` shape

```json
{
  "run_name": "LOT-2026-100",
  "execution_data": {
    "node-buffer-prep": {
      "status": "completed",
      "results": {"ph_value": 7.2, "temperature_c": 25.0, "volume_ml": 500},
      "notes": "Solution was clear.",
      "timestamps": [{"label": "Start Time", "value": "08:30"}],
      "signatures": [{"initials_or_name": "JKL", "role": "Operator"}],
      "deviations": []
    },
    "node-qc": {
      "status": "na",
      "na_reason": "Not performed in this run"
    }
  }
}
```

Unmapped extracted steps (e.g., extra handwritten steps not in the protocol) and unmapped protocol steps (e.g., protocol steps not present in the document) are reflected implicitly:
- Protocol steps missing from `execution_data` → unmapped/not-covered (scored by `step_completeness` recall).
- Extracted steps that don't correspond to any protocol step → simply absent from `execution_data` since there's no `protocol_step_id` to key on. In practice `step_completeness` precision catches hallucinated entries if the pipeline ever writes an `execution_data` key that doesn't exist in the protocol graph.

### Runner

```python
@pytest.mark.benchmark
class TestBatchRecordAccuracy:
    @pytest.mark.parametrize("fixture_dir", _br_fixture_dirs, ids=_br_fixture_ids)
    async def test_batch_record_to_run(
        self, fixture_dir: Path, db_session, pro_org,
    ):
        # 1. Extract
        doc = find_document(fixture_dir)
        text, page_images = await extract_batch_record_pages(doc, ..., db_session, org_id=pro_org.id)
        extraction = await extract_batch_record_data(text, page_images, db_session, org_id=pro_org.id)

        # 2. Load protocol and map
        protocol = load_json(fixture_dir, "protocol.json")
        mappings = await map_steps_to_protocol(extraction, protocol, db_session, org_id=pro_org.id)

        # 3. Build execution_data as the finalize endpoint would (auto-accept all extracted values).
        #    This simulates the user reviewing without edits.
        finalized = _build_auto_finalized(extraction, mappings)
        execution_data = map_values_to_execution_data(finalized, protocol, user_id=pro_org.id)

        # 4. Score against expected_run.json
        expected = load_json(fixture_dir, "expected_run.json")
        run_metadata = {"run_name": extraction.batch_id or extraction.document_title or ""}
        scores = score_run(execution_data, run_metadata, expected, protocol, fixture_dir.name)
        print_run_report(scores)
        all_batch_record_run_scores.append(scores)
        assert scores.overall >= 0.75, f"{fixture_dir.name}: {scores.overall:.0%} < 75%\n{json.dumps(scores.to_dict(), indent=2)}"
```

The `_build_auto_finalized` helper lives in the test file (or `batch_record_scoring.py`) and builds the same dict shape the real frontend would POST — accepting all extracted values, carrying through timestamps/signatures/deviations/notes. It exercises the same code path as the real finalize flow.

## Fixture authoring

Each scenario needs a `protocol.json` (target protocol graph) and `expected_run.json` (ground truth Run output). Hand-authored per scenario — pause for user sign-off before committing.

- **01-perfect-match:** 3-node protocol matching the document's 3 steps. All steps expected `completed`, all params/timestamps/signatures/notes populated.
- **02-wrong-protocol:** Protocol structurally unrelated to the document's run (e.g., purification protocol vs. cell-culture document). Expected Run: every protocol step has no execution data (they'd be unmapped); run_name might still populate from batch_id.
- **03-half-complete:** Protocol has more steps than the document covers. Some protocol steps marked `na`, the rest `completed` with extracted data.
- **04-extra-steps:** Document has additional steps not in the protocol. Expected Run covers only the mappable protocol steps; the extras are ignored (not in execution_data).
- **05-messy-scan:** Handwritten/OCR-degraded scan. Expected Run tolerates some extraction noise in values/labels; the benchmark's fuzzy tolerance should absorb minor OCR wobble.

## Error handling & edge cases

- **LLM unavailable:** tests are `-m benchmark`, excluded from default `pytest`. CI doesn't run them. Missing provider credentials raise at `get_model`.
- **Numeric tolerance:** `_numeric_equal(a, b)`: |a - b| / max(|a|, |b|, 1e-9) ≤ 0.05, OR |a - b| ≤ 0.01.
- **Unit normalization:** small synonym map covering °C↔C↔celsius, μm↔um↔micron, mL↔ml, etc.
- **Dimension zero-weight redistribution:** if a fixture legitimately has no timestamps or no deviations expected AND the pipeline produced none, that dimension scores 1.0 (N/A case) and its weight contributes fully — preserves total 100%. If expected has none but pipeline produced some, score 0.0 (hallucination).
- **Step alignment:** execution_data dicts are keyed by `protocol_step_id` directly — no fuzzy alignment needed for step matching. Fuzzy match still used for param labels/values where text comparison matters.

## Migration (from current branch state)

Branch `feat/f-0057-benchmark` is at `7b71672` after reset. Already in place:
- `document-to-run/` fixture tree (01-04 have `document.pdf` + `expected_extraction.json`)
- `matching.py` + tests
- Generalized `discover_fixtures(subdir, marker_file)` + `load_json` in conftest
- F-0058 `scoring.py` consumes `matching.py`

To do:
- Delete `expected_extraction.json` from each of 01-04 (replaced by `expected_run.json` later)
- Author `protocol.json` + `expected_run.json` for each of 01-05
- Delete orphaned smoke test `backend/tests/integration/test_batch_record_import_llm.py` and `sample_batch_record*` fixtures

## Testing the benchmark itself

Unit tests for `batch_record_scoring.py` (NOT LLM-dependent — run in normal suite). `backend/tests/unit/test_batch_record_scoring.py`:
- Perfect match on all dims → overall 1.0
- Missing expected step → `step_completeness` drops; details populated
- Wrong param value → `param_accuracy` drops; specific mismatch captured
- Synonym unit (°C vs. C) → matches
- Out-of-tolerance numeric (pH 7.2 vs. 7.3) → fails; (7.00 vs 7.01) → passes
- N/A handling: expected "na", actual "completed" → `na_correctness` < 1.0
- Timestamp F1 with missed ts → drops
- Signature F1 with hallucinated sig → precision drops

Integration test for the product changes:
- `test_batch_record_import_api.py` — finalize with timestamps/signatures/deviations → `Run.execution_data[step].timestamps|signatures|deviations` all present and correct.

## Invocation

```bash
# batch-record benchmark only
pytest backend/tests/benchmarks/test_llm_eval.py::TestBatchRecordAccuracy -m benchmark -v -s

# all benchmarks (F-0058 + F-0057)
pytest -m benchmark -v -s

# scorer unit tests (fast, no LLM)
pytest backend/tests/unit/test_batch_record_scoring.py -v

# integration test for product changes (no LLM)
pytest backend/tests/integration/test_batch_record_import_api.py -v
```

## Open questions / known limitations

- **`run_metadata` dimension is thin (5%)** — currently only scores `run_name`. Could later include `date`, `product_name`, `batch_id` if those make it to the Run structure (they don't currently). Weight reflects that narrowness.
- **Messy-scan fixture generation** — exact approach (synthetic handwritten vs. real scanned photo) decided during implementation. Preference: use an existing filled-template DOCX, print → scan, or simulate scan artifacts (blur/noise/rotation) via Pillow.
- **Scoring tolerance evolves with fixtures** — calibration may need tuning once real LLM output is in hand. Keep `batch_record_scoring.py` small and readable to make that easy.

## Out of scope

- Frontend review UI for editing timestamps/signatures/deviations.
- Benchmarking the PDF generation of batch records (F-0065).
- Cross-language batch records (English only for now).
- CI-automated benchmark runs.
