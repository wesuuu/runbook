# TD-0085: Docling extraction — evaluation spike

## Context

The library pipeline today extracts PDFs with `pymupdf` + `pymupdf4llm`, then runs an LLM ("doc_structure" capability, default Ollama `llama3.2-vision:11b`) to recover the document outline, classify page roles, and produce a TOC. The output drives a structure-aware chunker (`rechunk_with_structure`) before embedding. The pipeline is large, slow, and brittle: `document_structure.py` is 853 lines of prompts + retry logic, `document_processor.py` carries three overlapping job entrypoints (`process_document`, `enrich_document`, `build_book`), and quality depends on a vision model the org may not have configured.

`docling` (IBM, MIT) is a candidate replacement: a layout-aware extractor that produces markdown, HTML, and structured JSON in one synchronous, fully-local call. Before we commit to ripping out the existing pipeline, we need real numbers on a representative document — quality, latency, and output fidelity — to validate the choice. **This spec covers only that evaluation.** Integration into the application is deferred to a follow-up ClickUp task.

## What we know from docling's docs

- Default pipeline is **fully local**: RT-DETR/DocLayNet layout, IBM TableFormer for tables, EasyOCR for OCR (only when `do_ocr=True`). No API keys, no phone-home.
- GPU is not required. `AcceleratorOptions(device=AUTO|CPU|CUDA|MPS|XPU, num_threads=N)` controls placement; AUTO probes CUDA→MPS→XPU→CPU.
- Models cached lazily to `~/.cache/docling/models/` on first call. `docling-tools models download` pre-fetches for container images.
- Per-page latency from arXiv 2408.09869: ~0.8s median on 8-core x86 CPU, ~0.1s on L4 GPU. Figure-heavy pages can hit 16s on CPU (p95).
- `DocumentConverter.convert()` is synchronous/blocking and CPU-bound — must run via the existing `task_runner.run_sync` thread offload if we adopt it.
- Outputs: `export_to_markdown()`, `export_to_html(image_mode=ImageRefMode.EMBEDDED)`, `export_to_dict()`, `iterate_items()`.

## Goal

Produce a one-page eval report with concrete numbers and a recommendation: **adopt docling for the library pipeline, or look elsewhere.** The report and its artifacts must be reproducible by anyone with the worktree and the textbook PDF.

## Non-goals

- Any change to `backend/app/` code.
- Any change to the frontend.
- DB migrations.
- Removing or modifying the existing extraction pipeline.
- Integration design — that lives in the follow-up task once the spike passes.

## Scope

Three artifacts get added to the worktree:

1. **`backend/pyproject.toml`** — add `docling` as a dev/optional dependency so the eval script can import it. (Note: not a runtime dep yet; if Phase A fails we remove it.)
2. **`scripts/eval_docling.py`** — CLI that runs docling on one or more input files across multiple configuration variants and writes outputs + a summary line per run.
3. **`scripts/mocks/eval_report.md`** — committed report with the numbers, side-by-side observations, and a recommendation.

Plus housekeeping:

- **`.gitignore`** — add `scripts/mocks/` except `eval_report.md` and `eval_docling.py` (binary inputs and large generated outputs stay out of git).
- **Symlink** — `scripts/mocks/animal-culture-textbook.pdf` → main repo copy so the worktree can read it.

## Plan

### Step 1 — Install

```bash
cd backend
poetry add docling --optional
poetry install
```

If the install is huge or pulls heavy ML deps we don't otherwise need, document this in the report and consider isolating docling into its own venv before integration.

### Step 2 — Make the textbook visible

```bash
mkdir -p scripts/mocks
ln -s /home/wesuuu/Code/trellisbio/scripts/mocks/animal-culture-textbook.pdf scripts/mocks/animal-culture-textbook.pdf
```

### Step 3 — Write the eval CLI

`scripts/eval_docling.py`:

- Args: `--input <path>` (repeatable), `--variant {default,no-ocr,cpu}` (repeatable; default = run all three), `--out-dir scripts/mocks/out`.
- For each (input, variant) pair:
  - Configure `DocumentConverter` per variant (see below).
  - Time the `.convert()` call.
  - Capture `accelerator_options.device` actually chosen.
  - Write `<basename>.<variant>.md`, `<basename>.<variant>.html` (with `ImageRefMode.EMBEDDED`), `<basename>.<variant>.json`.
- Print a one-line summary per run: `{input, variant, pages, seconds, sec/page, md_chars, html_chars, device}`.
- On first run only, measure model download size by snapshotting `~/.cache/docling/models/` before and after.

Variants:

| Variant | Accelerator | OCR | Why |
| --- | --- | --- | --- |
| `default` | `AUTO` | on | baseline — what users would get without tuning |
| `no-ocr` | `AUTO` | off | textbooks are text-native; tests if disabling OCR is the right default for a library of PDFs |
| `cpu` | `CPU` | on | worst case for a no-GPU container in production |

### Step 4 — Run on the textbook

```bash
python scripts/eval_docling.py --input scripts/mocks/animal-culture-textbook.pdf
```

Capture: stdout summary, total wall time, peak memory if easy (e.g. `/usr/bin/time -v`).

### Step 5 — Inspect outputs

For each variant, open `scripts/mocks/out/animal-culture-textbook.<variant>.html` in a browser side by side. Read the corresponding `.md` end to end (or sample 5–10 pages spread across the textbook).

Things to evaluate:

- **HTML readability**: headings rendered, figures present (and visible, not broken refs), tables structured (not flattened to plain text), columns handled, no overlapping content.
- **Markdown quality**: section headings preserved with correct levels, table rows intact, no obvious garbage, code/equation handling.
- **Latency**: per-page mean and total wall time per variant; difference between `default` and `no-ocr`.
- **Output size**: HTML size with embedded base64 images — does it stay under, say, 25MB for the textbook, or blow past?
- **Differences between variants**: does `no-ocr` lose anything for a text-native textbook? Does forcing CPU make a 27MB textbook unworkable as a background job?

### Step 6 — Optional second pass

Only if the textbook passes: source an image-heavy / scanned PDF (e.g. a scanned SOP, or one of the existing fixtures in `backend/tests/artifacts/templates/`), drop it into `scripts/mocks/`, run the eval on it with `default` and `no-ocr` variants. The point is to confirm OCR actually fires when needed and produces usable text.

### Step 7 — Write the report

`scripts/mocks/eval_report.md` covers:

1. **Inputs** — list of PDFs evaluated, page count, file size.
2. **Results table** — one row per (input, variant): pages, seconds, sec/page, md_chars, html_chars, device. Model download size (one-time).
3. **HTML observations** — bullet list per variant noting visible issues (tables flattened? figures broken? layout breaks?). Embed 2–3 screenshots of the rendered HTML for the record.
4. **Markdown observations** — same shape; list any missing or garbled sections.
5. **Recommendation** — one of:
   - **Adopt** — docling passes; integration task can proceed. Note recommended default variant, warmup strategy (lazy vs. `docling-tools models download` at build time), and which `PdfPipelineOptions` should be exposed as settings.
   - **Tune** — promising but needs different pipeline options; iterate before deciding.
   - **Reject** — quality or latency disqualifies it; evaluate alternatives (datalab/marker GPLv3, unstructured.io Apache-2.0, mistral-ocr).

## Pass criteria

The user signs off on the report after manual review. Conditions for "Adopt":

- HTML for the textbook renders readably (figures present, headings preserved, tables structured).
- Markdown is chunk-ready (no obvious garbage, sections preserved).
- At least one variant completes the 27MB textbook within ≲ 5 min on the dev machine — a workable background-job window.
- Output sizes don't break realistic storage assumptions (HTML ≲ ~50MB even for the textbook).

If any condition fails, the report recommends Tune or Reject and the integration task does not get created.

## Critical files

| Path | Change |
| --- | --- |
| `backend/pyproject.toml` | Add `docling` as optional dep |
| `scripts/eval_docling.py` | New — eval CLI |
| `scripts/mocks/eval_report.md` | New — committed report |
| `.gitignore` | Ignore `scripts/mocks/*` except `eval_report.md` and `eval_docling.py` |
| `scripts/mocks/animal-culture-textbook.pdf` | Symlink to main repo copy (untracked) |
| `scripts/mocks/out/` | Generated outputs (untracked) |

## Risks

| Risk | Mitigation |
| --- | --- |
| Model download is huge / slow | First-run measurement is part of the eval; if pathological, report flags it and integration plan must bake models into the image. |
| CPU latency on textbook is unworkable | `cpu` variant measures it directly; if bad, recommendation either ties adoption to GPU infra (ADR) or rejects docling. |
| HTML with embedded base64 blows past sane sizes | Eval records HTML byte size; if too large, integration plan must externalize images (out of scope for this spike, but flagged). |
| `poetry add docling` pulls 1GB+ of ML deps | If unacceptable, report recommends isolating docling into its own venv/service and integration plan handles the wiring. |
| Spike succeeds but integration discovers a blocker we missed | Acceptable — that's exactly what the follow-up task is for. The spike's job is to clear the obvious blockers, not all blockers. |

## Verification

1. `python scripts/eval_docling.py --input scripts/mocks/animal-culture-textbook.pdf` runs to completion across all three variants.
2. `scripts/mocks/out/animal-culture-textbook.default.html` opens in a browser and renders.
3. `scripts/mocks/eval_report.md` exists, is committed, and contains all six required sections (Inputs, Results table, HTML obs, Markdown obs, Recommendation, and any caveats).
4. User reviews the report and signs off on the recommendation.
5. If recommendation is "Adopt": create the follow-up ClickUp task ("Integrate docling into library pipeline + HTML viewer"), referencing TD-0085 and this report. Tracked locally as task #25 until the ClickUp MCP reconnects.

## Out of scope (deferred to follow-up)

The following were in earlier drafts of this spec and are explicitly **not** part of TD-0085. They move to the follow-up integration task created post-adoption:

- New `backend/app/services/ai/workflows/document_extraction/` module.
- Rewriting `build_book` to call docling.
- `Document.rendered_html` column + alembic migration.
- `GET /documents/{id}/html` endpoint.
- Deleting `document_structure.py`, `process_document`, `enrich_document`, `enrich_document_endpoint`.
- Slimming `markdown_chunker.py`.
- Removing the `doc_structure` AI capability.
- Frontend HTML viewer.
- `.claude/rules/*` + `CLAUDE.md` updates.
