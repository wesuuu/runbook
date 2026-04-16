# Protocol Import Benchmark Framework

**Date:** 2026-04-16
**Task:** F-0058 (SOP-to-Protocol Import)
**Scope:** Backend — LLM eval tests + live E2E tests

## Goal

Create a benchmark suite that validates the protocol import pipeline produces correct protocols and unit operations from uploaded SOP documents. Two modes:

1. **LLM eval** — Feed real documents through `parse_protocol_text()` and `build_proposal()`, score output against hand-authored expected results.
2. **Live E2E** — Upload documents through the full API (`/protocols/import` → `/protocols/finalize-import`), verify DB state.

## Directory Structure

```
backend/tests/benchmarks/
├── conftest.py                  # Shared fixtures, scoring utilities, DB setup
├── fixtures/
│   ├── generate_fixtures.py     # Script to (re)generate PDFs and PNGs
│   ├── 01_buffer_prep/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 02_cell_culture_passage/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 03_protein_a_purification/
│   │   ├── document.png
│   │   └── expected.json
│   ├── 04_transfection/
│   │   ├── document.pdf
│   │   └── expected.json
│   ├── 05_fill_finish_qc/
│   │   ├── document.pdf
│   │   └── expected.json
│   └── 06_messy_scan/
│       ├── document.png
│       └── expected.json
├── test_llm_eval.py             # LLM accuracy tests (pytest, requires AI provider)
└── test_e2e_import.py           # Full API E2E tests (pytest, requires DB + AI)
```

## Fixture Format

Each fixture directory contains:
- `document.pdf` or `document.png` — the SOP file
- `expected.json` — hand-authored expected output

### expected.json Schema

```json
{
  "protocol_name": "Buffer Preparation SOP",
  "step_count": 4,
  "steps": [
    {
      "name": "Prepare Tris Buffer",
      "category": "Media Prep",
      "matched_unit_op_name": "Buffer Preparation",
      "is_new": false,
      "role": "Operator",
      "duration_min": 30,
      "expected_params": {
        "buffer_name": "Tris-HCl",
        "pH_target": 7.4,
        "volume_L": 10
      }
    },
    {
      "name": "Sterility Test",
      "category": "Quality Control",
      "matched_unit_op_name": null,
      "is_new": true,
      "role": "QC Lead",
      "duration_min": 15,
      "expected_params": {
        "method": "membrane filtration"
      }
    }
  ],
  "expected_roles": ["Operator", "QC Lead"],
  "expected_new_unit_op_count": 1,
  "notes": "Optional notes about what makes this fixture interesting"
}
```

Fields in `expected.json` use **relaxed matching** — the eval doesn't require exact string equality on everything. See Scoring below.

## Scoring

Each fixture is scored across five dimensions. Per-dimension scores are 0.0–1.0.

### 1. Step Detection (precision + recall)

Compare expected steps vs. actual steps by name similarity (fuzzy, >0.7 threshold).

- **Recall**: fraction of expected steps found in output
- **Precision**: fraction of output steps that match an expected step
- **Score**: F1 of precision and recall

### 2. Catalog Matching

For each expected step where `matched_unit_op_name` is specified:

- Did the LLM return the same `matched_unit_op_name`?
- Case-insensitive comparison.
- **Score**: correct matches / total expected matches

### 3. New Unit Op Detection

- Did the pipeline correctly identify `is_new` steps?
- Compare expected `is_new` flags vs. actual.
- **Score**: correct `is_new` flags / total steps

### 4. Parameter Extraction

For each expected step with `expected_params`:

- For each expected param key: is it present in actual params?
- For numeric values: within 20% tolerance
- For string values: case-insensitive substring match
- **Score**: correct param extractions / total expected params

### 5. Role Extraction

- Compare expected roles vs. actual roles extracted.
- Order-independent, case-insensitive.
- **Score**: Jaccard similarity (intersection / union)

### Overall Score

Weighted average:
- Step Detection: 30%
- Catalog Matching: 25%
- New Unit Op Detection: 20%
- Parameter Extraction: 15%
- Role Extraction: 10%

**Pass threshold**: 75% overall per fixture. Printed as a report table.

## Mock Documents

### 01: Buffer Preparation SOP (PDF, 4 steps, all catalog matches)

Standard buffer prep procedure:
1. Weigh and dissolve Tris base (→ Buffer Preparation)
2. Adjust pH to 7.4 with HCl (→ pH Adjustment)
3. Sterile filter through 0.22µm (→ Filtration)
4. Collect QC sample (→ Sample Collection)

Roles: Operator only. No new unit ops.

### 02: Cell Culture Passage (PDF, 7 steps, 2 new unit ops)

Standard mammalian cell passage:
1. Pre-warm media to 37°C (→ Media Preparation)
2. Aspirate old media — **new: "Media Aspiration"**
3. Wash with PBS — **new: "PBS Wash"**
4. Add trypsin and incubate 5 min (→ Incubation)
5. Neutralize and collect cells (→ Harvest)
6. Count cells (→ Cell Counting)
7. Seed new flask at 0.5×10⁶ cells/mL (→ Seeding)

Roles: Operator. Two new unit ops: Media Aspiration, PBS Wash.

### 03: Protein A Purification (PNG scan, 10 steps, 3 new unit ops)

Downstream purification protocol:
1. Equilibrate column with binding buffer — **new: "Column Equilibration"**
2. Load clarified harvest (→ Chromatography)
3. Wash with binding buffer (→ Chromatography or new)
4. Elute with low pH buffer (→ Chromatography)
5. Neutralize eluate (→ pH Adjustment)
6. Viral inactivation at low pH hold — **new: "Viral Inactivation"**
7. Filter through 0.2µm (→ Filtration)
8. Diafiltration into formulation buffer — **new: "Diafiltration"**
9. Concentrate to target (→ Centrifugation)
10. Collect final sample (→ Sample Collection)

Roles: Purification Scientist, QC Analyst. Three new unit ops.

### 04: Transfection Protocol (PDF, 6 steps, 1 new unit op)

Transient transfection for recombinant protein production:
1. Seed cells day before (→ Seeding)
2. Prepare DNA-lipid complexes — **new: "DNA Complex Preparation"**
3. Add complexes to cells (→ Transfection)
4. Incubate 4-6 hours (→ Incubation)
5. Replace media (→ Media Preparation)
6. Count and check viability at 48h (→ Cell Counting)

Roles: Scientist. One new unit op. Domain-specific params: DNA amount (µg), lipid:DNA ratio, MOI.

### 05: Fill/Finish with QC (PDF, 8 steps, 2 new unit ops)

Drug product fill and finish:
1. Prepare formulation buffer (→ Buffer Preparation)
2. Sterile filter drug substance (→ Filtration)
3. Fill vials at 1.2 mL each (→ Fill)
4. Stopper and crimp — **new: "Vial Sealing"**
5. Visual inspection of 100% (→ Visual Inspection)
6. Lyophilize at -40°C shelf (→ Lyophilization)
7. Check for particulates — **new: "Particulate Testing"**
8. Run potency assay (→ Assay)

Roles: Fill Operator, QC Inspector. Two new unit ops.

### 06: Messy Handwritten Scan (PNG, 4 steps, 1 new unit op)

Low-quality image simulating a photographed laminated SOP card:
1. Thaw vial from LN2 (→ Thaw or similar)
2. Add to pre-warmed media (→ Media Preparation)
3. Spin down at 300g — **new: "Centrifuge Wash"** (or → Centrifugation)
4. Resuspend and seed (→ Seeding)

Roles: none specified. Tests OCR robustness with imperfect text.

## Document Generation

`generate_fixtures.py` creates all PDFs and PNGs programmatically:

- **PDFs** (`reportlab`): Formatted like real SOPs — title, document number, revision, effective date, purpose section, numbered procedure steps, parameters in tables, role assignments in headers. Professional but not over-designed.
- **PNGs** (`Pillow`): Rendered text images. Document #3 looks like a scanned printed page (slight rotation, gray background). Document #6 simulates low quality (reduced resolution, noise, handwriting-style font if available, otherwise degraded print font).

The script is idempotent — run it to regenerate all fixtures. New fixtures are added by:
1. Creating a new numbered directory
2. Adding the expected.json
3. Adding a generation function in generate_fixtures.py
4. Running the script

## Test Harness: LLM Eval (`test_llm_eval.py`)

```python
@pytest.mark.benchmark
class TestProtocolImportAccuracy:
    """Runs against real LLM. Excluded from normal test suite."""

    @pytest.fixture
    def fixtures(self):
        """Discover all fixture directories with document + expected.json."""
        ...

    @pytest.mark.parametrize("fixture_dir", discover_fixtures())
    async def test_import_accuracy(self, fixture_dir, unit_ops_catalog):
        # 1. Extract text from document (real extraction)
        text = await extract_text(fixture_path, mime_type)

        # 2. Parse with LLM (real LLM call)
        parsed = await parse_protocol_text(text, unit_ops_catalog)

        # 3. Build proposal (deterministic)
        proposal = build_proposal(parsed, unit_ops_catalog, filename, text)

        # 4. Score against expected.json
        scores = score_proposal(proposal, expected)

        # 5. Print report row
        print_score_report(fixture_dir.name, scores)

        # 6. Assert pass threshold
        assert scores.overall >= 0.75, f"{fixture_dir.name}: {scores.overall:.0%} < 75%"
```

Marked with `@pytest.mark.benchmark` so they don't run in normal `pytest`. Run with:
```bash
pytest tests/benchmarks/test_llm_eval.py -m benchmark -v
```

## Test Harness: E2E (`test_e2e_import.py`)

```python
@pytest.mark.benchmark
class TestProtocolImportE2E:
    """Full API round-trip. Requires running backend + DB + AI provider."""

    @pytest.mark.parametrize("fixture_dir", discover_fixtures())
    async def test_full_import_pipeline(self, fixture_dir, async_client, db_session):
        # 1. Upload document via POST /protocols/import
        response = await async_client.post("/science/protocols/import", files=...)

        # 2. Assert proposal response structure
        proposal = response.json()
        assert proposal["steps"]

        # 3. Score proposal against expected.json (same scoring as LLM eval)
        scores = score_proposal(proposal, expected)
        assert scores.overall >= 0.75

        # 4. Finalize import via POST /protocols/finalize-import
        finalize_response = await async_client.post(
            "/science/protocols/finalize-import",
            json={...proposal data, project_id or organization_id...}
        )
        assert finalize_response.status_code == 200

        # 5. Verify DB state
        protocol = finalize_response.json()
        assert protocol["graph"]["nodes"]
        assert protocol["graph"]["edges"]

        # 6. Verify new unit ops were created
        new_steps = [s for s in expected["steps"] if s["is_new"]]
        for step in new_steps:
            # Query DB for newly created UnitOpDefinition
            op = await db_session.execute(
                select(UnitOpDefinition).where(UnitOpDefinition.name.ilike(f"%{step['name']}%"))
            )
            assert op.scalar_one_or_none() is not None, f"Missing unit op: {step['name']}"

        # 7. Verify roles created
        if expected.get("expected_roles"):
            roles = protocol["graph"].get("metadata", {})
            # Check ProtocolRole records in DB
            ...
```

## Running the Benchmarks

```bash
# Generate/regenerate fixture documents
python backend/tests/benchmarks/fixtures/generate_fixtures.py

# LLM eval only (no DB needed, needs AI provider)
pytest backend/tests/benchmarks/test_llm_eval.py -m benchmark -v

# Full E2E (needs DB + AI provider + running backend)
pytest backend/tests/benchmarks/test_e2e_import.py -m benchmark -v

# All benchmarks
pytest backend/tests/benchmarks/ -m benchmark -v
```

## Extensibility

Adding a new fixture:

1. Create `backend/tests/benchmarks/fixtures/07_my_new_sop/expected.json`
2. Add a generation function in `generate_fixtures.py` (or place a real PDF/PNG as `document.pdf`/`document.png`)
3. Run `generate_fixtures.py` if auto-generating
4. Run `pytest backend/tests/benchmarks/ -m benchmark -v`

The test harness auto-discovers fixture directories by scanning for `expected.json` files. No code changes needed to add new test cases.

Users can also drop real SOP documents directly into a fixture directory instead of generating them — the harness only cares about having a `document.*` file and an `expected.json`.

## Dependencies

New Python packages for fixture generation:
- `reportlab` — PDF generation
- `Pillow` — PNG generation (already in requirements for image processing)

Both are dev-only dependencies, not needed at runtime.
