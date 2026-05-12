# TD-0085: Docling document extraction

## Context

The library pipeline today extracts PDFs with `pymupdf` + `pymupdf4llm`, then runs an LLM ("doc_structure" capability, default Ollama `llama3.2-vision:11b`) to recover the document outline, classify page roles, and produce a TOC. The output drives a structure-aware chunker (`rechunk_with_structure`) before embedding. The pipeline is large, slow, and brittle: `document_structure.py` is 853 lines of prompts + retry logic, `document_processor.py` carries three overlapping job entrypoints (`process_document`, `enrich_document`, `build_book`), and quality depends on a vision model the org may not have configured.

`docling` (IBM, MIT) is a layout-aware extractor that produces markdown, HTML, and structured JSON in one synchronous call. Adopting it removes the LLM detour for layout, removes the `doc_structure` capability, and gives us a rendered HTML view we can show users directly — a capability the frontend currently lacks for DOCX/MD/HTML documents (today it only renders chunk lists).

The change is scoped to the **library** pipeline. `protocol_importer` and `batch_record_extractor` keep using `pymupdf` because they need raw page text + page PNGs for vision LLMs — docling does not serve those needs.

The intended outcome: one extractor, one entry point, smaller surface area, an HTML viewer for non-PDF documents, and a paper trail (eval report) justifying the choice over datalab/marker and unstructured.io.

## Goals

- Library document extraction goes through docling end-to-end.
- `Document.rendered_html` is populated for every successfully processed document; the frontend renders it inside a sandboxed iframe.
- Net code deletion in `backend/app/services/documents/`.
- The `doc_structure` AI capability and its env/DB config are gone.
- `protocol_importer` and `batch_record_extractor` continue to work unchanged.
- An eval report (markdown + sample HTML outputs) lives under `scripts/mocks/` for future re-runs.

## Non-goals

- Replacing extraction inside `protocol_importer` or `batch_record_extractor`.
- Improving chunking strategy beyond consuming docling markdown via the existing `chunk_markdown`.
- Sanitization or rewriting of docling HTML on the server — the sandboxed iframe is the trust boundary.
- Image-only HTML asset extraction (defer; HTML stays self-contained with embedded base64).

## Architecture

```
frontend/library/[id]/+page.svelte
  ├─ PDF                       → existing iframe of /documents/{id}/download
  ├─ DOCX/MD/TXT/HTML w/ html  → DocumentHtmlViewer (lazy fetch /documents/{id}/html)
  └─ no rendered_html          → existing chunk-list fallback

backend/app/api/endpoints/library.py
  └─ GET /documents/{id}/html  → text/html; charset=utf-8

backend/app/services/documents/document_processor.py
  └─ build_book(document_id, db_url)
       │
       ├─ resolve file by mime
       ├─ workflows.document_extraction.extract_pdf | extract_docx
       │     → StructuredDoc(markdown, html, page_spans, page_count, toc)
       ├─ persist Document.rendered_html
       ├─ persist Document.structure_metadata["toc"]
       ├─ chunk_markdown(markdown, page_boundaries=page_spans-derived)
       ├─ embed chunks
       └─ status = INDEXED

backend/app/services/ai/workflows/document_extraction/
  ├─ types.py       (StructuredDoc, PageSpan, TocEntry dataclasses)
  ├─ extractor.py   (extract_pdf, extract_docx — blocking, called via task_runner.run_sync)
  └─ html_renderer.py  (DoclingDocument → HTML string with ImageRefMode.EMBEDDED)
```

`StructuredDoc.page_spans` carries `(page_number, char_start, char_end)` so the chunker can attach a page number to each chunk without re-parsing.

## Data model

One column on `documents`:

```python
rendered_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Alembic migration adds the column nullable; backfill is not required (docs without HTML stay null until next retry).

`Document.structure_metadata` JSONB keeps its shape, but only `{"toc": [...]}` is populated post-cutover. Existing rows that contain `{outline, pages, toc}` are left in place; the keys are simply not read anymore.

## API surface

| Endpoint | Method | Change | Returns |
| --- | --- | --- | --- |
| `/library/documents/{id}/html` | GET | **new** | `text/html; charset=utf-8` body = `rendered_html`, 404 if null |
| `/library/documents/{id}/enrich` | POST | **removed** | — |
| `/library/documents/*` (upload, list, detail, chunks, download, retry, search, from-url) | — | unchanged | — |

Detail response (`GET /documents/{id}`) does **not** inline `rendered_html` — it's fetched separately to keep the detail payload small.

## Frontend

New component:

```
frontend/src/lib/components/library/DocumentHtmlViewer.svelte
```

- On mount, fetches `/library/documents/{id}/html` via the existing `api` client.
- Renders inside `<iframe sandbox="allow-same-origin" srcdoc={html}>` for defense in depth, even though docling output is server-generated.
- Loading and empty states inline.

Wired into `library/[id]/+page.svelte` via mime/`rendered_html` switch (see Architecture diagram). PDF path unchanged. Chunk-list remains the fallback for any doc without `rendered_html`.

## Deletions (Phase C only)

- `backend/app/services/documents/document_structure.py` (entire file, 853 lines)
- `backend/app/services/documents/document_processor.py`:
  - `process_document`
  - `enrich_document`
  - `_get_pdf_page_count`
  - `_extract_pdf_toc`
  - `_build_toc_from_structure`
  - `_assign_toc_chunk_indices`
- `backend/app/services/documents/markdown_chunker.py`:
  - `chunk_by_pages`
  - `rechunk_with_structure`
  - `toc_lines_to_markdown`
  - All helpers only used by the above
- `backend/app/api/endpoints/library.py::enrich_document_endpoint`
- `backend/app/models/ai.py`: remove `"doc_structure"` from `SUPPORTED_CAPABILITIES` and `DEFAULT_CONFIGS`
- `backend/app/core/config.py`: remove `ai_doc_structure_provider`, `ai_doc_structure_model`

Kept:
- `extract_pdf_pages`, `extract_docx`, `extract_text_file`, `_extract_pdf_page_range`, `_extract_page_text`, `_pad_embedding` (used by `protocol_importer`, `batch_record_extractor`, or `build_book`)
- `chunk_markdown` and its block-segmentation helpers
- `chunk_text` (used for `text/plain` mime in `build_book`)

## Phases

### Phase A — eval spike

Goal: prove docling is good enough on a real-world textbook before any production code lands.

1. Add `docling` to `backend/pyproject.toml` and `poetry install` in the worktree venv.
2. Add `scripts/mocks/` to `.gitignore` (convention dir for big binary eval inputs).
3. Make the textbook visible inside the worktree (symlink from `/home/wesuuu/Code/trellisbio/scripts/mocks/animal-culture-textbook.pdf`).
4. Build `scripts/eval_docling.py`:
   - CLI takes one or more file paths.
   - For each input: time `DocumentConverter().convert(...)`; emit `<basename>.md`, `<basename>.html` (`ImageRefMode.EMBEDDED`), `<basename>.json` into `scripts/mocks/out/`.
   - Log per-doc: file size, page count, conversion latency, markdown char count, HTML char count. Record model download size on first run.
5. Run on the textbook. Open the HTML in a browser. Read the markdown.
6. **Pass criteria (manual sign-off):**
   - HTML renders the textbook readably (figures, tables, headings present).
   - Markdown is chunk-ready (no obvious garbage, sections preserved).
   - Latency on the 27MB textbook is acceptable for a background job (≲ ~2 min on dev machine).
7. If pass: run a second pass on an image-heavy / scanned PDF (sourced ad-hoc) to confirm OCR fallback.
8. Commit `scripts/mocks/eval_report.md` with the numbers + verdict + warmup recommendation (lazy on first upload vs. startup warm).

Exit gate: explicit user approval of the report before Phase B begins. If textbook fails, plan stops and we re-evaluate (tune `PdfPipelineOptions`, or fall back to comparing datalab/marker).

### Phase B — extraction module

Build `backend/app/services/ai/workflows/document_extraction/` (types, extractor, html_renderer) plus `backend/tests/unit/test_document_extraction.py`. No wiring into `build_book` yet — module is self-contained, testable in isolation.

Tests cover: PDF roundtrip on a small fixture, DOCX roundtrip, HTML contains expected tags, page spans align with page count.

### Phase C — pipeline rewrite

- Alembic migration: add `rendered_html` column.
- Rewrite `build_book` to call the new extractor, persist HTML, chunk via `chunk_markdown` with page boundaries, embed.
- Add `GET /documents/{id}/html` endpoint.
- Slim `markdown_chunker.py` (delete dead chunkers).
- Delete `document_structure.py`, `process_document`, `enrich_document`, `enrich_document_endpoint`, doc_structure capability + config fields.
- Rewire `main.py::_recover_stalled_jobs` and `_recover_stalled_documents` to re-fire `build_book` for all three legacy job types.
- Update integration test fixtures: `autouse` patch switches from `process_document` to `build_book`.
- Update unit test file: `backend/tests/unit/test_markdown_chunker.py` — remove tests for deleted functions, keep tests for `chunk_markdown`.

### Phase D — frontend HTML viewer

- New `DocumentHtmlViewer.svelte` under `frontend/src/lib/components/library/`.
- Wire into `library/[id]/+page.svelte` viewer-selection switch.
- Vitest unit test for the viewer (mocks `api.get`, asserts iframe srcdoc).

### Phase E — verify, qa, refresh rules

- `pytest` green (backend), `npm run test` green (frontend), `npm run check` clean.
- `qa-verify` agent walks: upload the textbook PDF → wait for INDEXED → open detail page → confirm HTML viewer renders → run a `/library/search` query and confirm hits → upload a DOCX → confirm HTML viewer fallback path. Also confirms PDF viewer path still works.
- Refresh `.claude/rules/backend-ai.md` to document `workflows.document_extraction/`.
- Refresh `CLAUDE.md`: docling under deps; note removal of `doc_structure` env vars.
- Post ClickUp tradeoff doc + summary to TD-0085 once the ClickUp MCP reconnects (currently down — track as a TODO in the session, not in code).

## Critical files

| Path | Change |
| --- | --- |
| `backend/pyproject.toml` | Add `docling` dep |
| `scripts/eval_docling.py` | New — eval CLI |
| `scripts/mocks/eval_report.md` | New — committed report from Phase A |
| `.gitignore` | Add `scripts/mocks/` (except `eval_report.md`) |
| `backend/app/services/ai/workflows/document_extraction/types.py` | New |
| `backend/app/services/ai/workflows/document_extraction/extractor.py` | New |
| `backend/app/services/ai/workflows/document_extraction/html_renderer.py` | New |
| `backend/tests/unit/test_document_extraction.py` | New |
| `backend/alembic/versions/<rev>_add_rendered_html_to_documents.py` | New migration |
| `backend/app/models/library.py` | Add `rendered_html` column |
| `backend/app/services/documents/document_processor.py` | Rewrite `build_book`; delete `process_document`, `enrich_document`, helpers |
| `backend/app/services/documents/document_structure.py` | **Delete** |
| `backend/app/services/documents/markdown_chunker.py` | Delete `chunk_by_pages`, `rechunk_with_structure`, `toc_lines_to_markdown` + dead helpers |
| `backend/app/api/endpoints/library.py` | Add `GET /documents/{id}/html`; delete enrich endpoint |
| `backend/app/main.py` | Recovery: re-fire `build_book` for legacy job types |
| `backend/app/models/ai.py` | Remove `doc_structure` capability + default |
| `backend/app/core/config.py` | Remove `ai_doc_structure_*` settings |
| `backend/tests/integration/test_library_api.py` | Patch `build_book` |
| `backend/tests/integration/test_library_search.py` | Patch `build_book` |
| `backend/tests/unit/test_markdown_chunker.py` | Drop tests for deleted chunkers |
| `frontend/src/lib/components/library/DocumentHtmlViewer.svelte` | New |
| `frontend/src/routes/library/[id]/+page.svelte` | Viewer-selection switch |
| `.claude/rules/backend-ai.md` | Document `workflows/document_extraction/` |
| `CLAUDE.md` | Doc dep + flag removal note |

## Reused utilities

- `app.services.core.task_runner.get_task_runner()` — `run_sync` for the blocking docling call, `submit` for the build_book coroutine.
- `app.services.documents.markdown_chunker.chunk_markdown` — unchanged signature; new pipeline passes `page_boundaries` from `StructuredDoc.page_spans`.
- `app.services.data.text_chunker.chunk_text` — used in `build_book` for `text/plain` mime.
- `app.services.core.file_storage.FileStorageService` — resolves the original file path passed to docling.
- `app.services.ai.embedding.embed_texts` + `_pad_embedding` — unchanged.

## Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| HTML payload 5–50 MB | Lazy endpoint isolates from detail page. If a doc's HTML exceeds the threshold set after eval (likely 25 MB), skip persistence and log; chunk-list fallback handles render. |
| Docling model cache lost on container restart | Eval spike measures download size and time. Decision (bake into image vs. lazy-warm vs. startup-warm) flows from the report. |
| Quality parity is subjective | Eval criteria are explicit (HTML readable + markdown chunk-ready + ≲2 min). User signs off on the report before Phase B starts. |
| Deleting `process_document` is irreversible | All three legacy job types route to `build_book` in recovery. Existing `structure_metadata` rows stay queryable; nothing is destroyed, just orphaned. |
| `{@html ...}` is XSS-prone | Render inside `<iframe sandbox="allow-same-origin">` regardless. |
| Worktree can't see `scripts/mocks/` PDF | Symlink from main repo. `scripts/mocks/` is gitignored, so re-create per worktree. |

## Verification

1. **Eval spike (manual):** open `scripts/mocks/out/animal-culture-textbook.html` in a browser; confirm legibility. Inspect `scripts/mocks/out/animal-culture-textbook.md` for missing sections vs. the PDF.
2. **Unit tests:** `cd backend && source .venv/bin/activate && pytest tests/unit/test_document_extraction.py tests/unit/test_markdown_chunker.py -v`
3. **Integration tests:** `pytest tests/integration/test_library_api.py tests/integration/test_library_search.py -v`
4. **Full suite:** `pytest` — no regressions outside known pre-existing failures.
5. **Browser smoke (qa-verify):**
   - Login → upload `animal-culture-textbook.pdf` → wait for INDEXED status → open detail page → HTML viewer renders inside iframe → run a search for a known phrase in the textbook → confirm a hit.
   - Upload a DOCX from `backend/tests/artifacts/templates/sop_simple.docx` → INDEXED → HTML viewer renders → search works.
   - Confirm PDF viewer fallback unchanged for the original PDF.
6. **Cleanup verification:** `grep -r doc_structure backend/app/` returns nothing; `grep -r process_document backend/app/` returns nothing; `grep -r enrich_document backend/app/` returns nothing.
