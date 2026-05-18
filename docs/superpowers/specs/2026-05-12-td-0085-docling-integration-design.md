# TD-0085 (follow-up): Docling integration + refinement editor

> Follow-up to [2026-05-12-td-0085-docling-extraction-design.md](2026-05-12-td-0085-docling-extraction-design.md). The eval spike landed an **Adopt** verdict in [eval_report.md](../../../scripts/mocks/eval_report.md). This spec covers integration. ClickUp ID is pending — the task is tracked locally as the follow-up to TD-0085 until the ClickUp MCP reconnects.

## Context

The eval spike confirmed docling produces chunk-ready markdown, structurally accurate HTML (figures with captions, real tables, single-stream body text), and works fully-local with a one-time ~1 GB model download. On a 16-core CPU it runs ~2.4 s/page; book-scale inputs are a 30-minute background job, SOP-scale inputs are 1–2 minutes.

Two exploration findings reshape the integration design and are baked into this spec rather than discovered during implementation:

- **URLs are out.** Docling's HTML backend filters form-nested content; pages like vendor recipe tools (Novoprolabs sodium-phosphate calculator) lose the recipe table entirely. The page-to-PNG-to-docling fallback works for cropped content-only screenshots but degrades sharply on cluttered pages with sidebars/footers — the OCR latches onto chrome instead of content. Web ingestion is a different problem (probably a browser-driven scraper) and will not be solved by docling.
- **OCR engine matters more than the eval suggested.** Docling's default OCR (RapidOCR's mobile English-Chinese model) drops inter-word spaces on English content — text comes out as `Prepare0.8Lofdistilledwater…`. EasyOCR with `lang=["en"]` preserves spacing but is ~3.7× slower and introduces its own artifacts (occasional missed cells, formula garbling like `NaHzPO4119.98`). Both engines need a human-in-the-loop pass. Since Batchrite's content is English-only and refinement is unavoidable either way, we hardcode EasyOCR.

These two findings drive the scope: **PDF / docx / image only**, **EasyOCR pinned**, and **a refinement phase is part of the happy path**, not an exception flow. A document is not considered usable until a human (with optional AI assist) has reviewed it.

## Goal

Replace the existing vision-LLM extraction pipeline (`document_structure.py` + `document_processor.process_document` + the `doc_structure` AI capability) with docling, and add a refinement editor that lets a PD scientist correct OCR/extraction artifacts before the document is indexed for search.

Concretely:

1. Backend extraction: upload → docling → externalized images on disk → markdown stored on the `Document` row.
2. Read API: serve refined markdown + image assets; the frontend renders markdown → HTML at view time.
3. Refinement editor: a WYSIWYG (Tiptap/edra) view of the rendered document with markdown round-tripped under the hood, a low-confidence flag queue, and a scoped AI-fix panel. Designed in [scripts/mocks/editor-mockups.html](../../../scripts/mocks/editor-mockups.html); Concept II is the chosen direction.
4. Indexing happens **only after** refinement is marked complete. A document with refinement pending never enters the vector index.

## Non-goals

- Web/URL ingestion.
- Multi-language OCR (Batchrite users are English-only for now; the OCR setting stays as a constant, not a per-document or per-org config).
- Re-extracting the entire document from a single AI prompt. AI assistance is **selection-scoped** — fix this cell, fill this gap, fix this paragraph. No "rewrite the whole document" actions.
- Live collaboration (multiple users editing the same document simultaneously). The editor takes a soft lock on save; concurrent edits surface a stale-version conflict at save time, same model as Protocol editing.
- Replacing `pymupdf` outright — it stays for non-extraction uses (page rendering for the source-thumbnail preview in the refinement editor's left rail).

## Scope — two phases

This work ships in two phases so the spec stays a single source of truth across them.

**Phase 1 — Backend extraction + storage** (this spec covers in detail).
**Phase 2 — Refinement editor frontend** (this spec covers the design; implementation in a follow-up planning doc).

A separate, smaller phase implements `CloudGpuExtractionLauncher` whenever the first book-scale workload (or a pod-restart-loss incident) makes it worth the infra cost. That's not in either of the two phases below.

### Phase 1 — Backend

- **Add `docling` to runtime deps.** Resolve the torch constraint conflict (see Risks; current decision: bump `torch` and isolate to a separate Poetry group `[tool.poetry.group.docling]` so it doesn't bloat the base image of services that don't need it).
- **Bake models at image build.** Dockerfile step: `docling-tools models download` + EasyOCR warmup. Cold-container first-extraction otherwise stalls minutes downloading ~1 GB.
- **New service:** `backend/app/services/documents/extraction/docling_extractor.py` — wraps `DocumentConverter` with a fixed configuration (see "Pipeline configuration" below). Exposes one function `extract_document(file_path: Path, document_id: UUID, images_dir: Path) -> ExtractionResult`.
- **Externalize images.** During extraction, write picture regions to `{org_storage}/documents/{document_id}/images/{n}.png` and rewrite the markdown's `<!-- image -->` placeholders to `![<caption>](images/{n}.png)`. The relative path stays in the stored markdown; the API rewrites it to an absolute URL at read time.
- **New job + launcher:** `backend/app/services/documents/extraction/launcher.py` introduces `ExtractionLauncher` (see "Job infrastructure" below). Phase 1 ships `LocalExtractionLauncher` only — it submits the extraction coroutine to the existing in-process `TaskRunner`. `CloudGpuExtractionLauncher` is a stub for now.
- **`Document` model additions** (see "Schema changes").
- **AI capability registration:** new `document_refinement` capability resolved via `get_model('document_refinement', db, org_id)` — never hardcoded. Defaults to claude-sonnet-4-6 for cost; users can override per-org.
- **Indexing trigger:** moves from "after extraction completes" to "after refinement marked complete". Chunking input is the **stored, refined markdown**, not docling's raw output.
- **Refinement endpoints** (see "API surface") — the backend API surface ships with Phase 1 so Phase 2 has something to hit; PUT/AI endpoints can be smoke-tested with curl before the editor lands.

### Phase 2 — Frontend

- **New route:** `/library/documents/[id]/refine` — refinement editor for a single document.
- **Components** (under `lib/components/document-refinement/` — new domain bucket per `.claude/rules/conventions.md`):
  - `RefinementEditor.svelte` — center canvas; thin wrapper around the existing edra Tiptap setup with markdown serialization and image src rewriting.
  - `RefinementSidebar.svelte` — left rail: source-page thumbnail (rendered via existing pymupdf endpoint), extraction status pipeline.
  - `RefinementQueue.svelte` — right rail: low-confidence flags from `Document.refinement_flags` JSONB, click-to-scroll-to-block behavior.
  - `RefinementAiPanel.svelte` — right rail: prompt area, scope chip (selection / block / whole document), AI suggestions list, apply/cancel.
- **Markdown rendering for non-refinement views** — a shared `MarkdownDocument.svelte` in `lib/components/shared/` that converts markdown → HTML and rewrites image refs to API URLs. Used by the read-only viewer too.
- **API client + Zod schemas** in `frontend/src/lib/api/documents.ts` and `frontend/src/lib/schemas/documents.ts` for the new endpoints.

### Removed / replaced

- `backend/app/services/documents/document_structure.py` — deleted.
- `backend/app/services/documents/document_processor.py` — `process_document`, `enrich_document` removed; `build_book` removed (chunker now consumes refined markdown directly, no rebuild step).
- `enrich_document_endpoint` in `library.py` — deleted.
- `doc_structure` AI capability — removed from `DEFAULT_CONFIGS` and the platform-env-var allowlist in `ai_config.py`.
- Ollama vision-model dependency — dropped (no other capability uses it today).

## Schema changes

### `Document` model

```python
# new columns
source_format: Mapped[DocumentSourceFormat]  # PDF | DOCX | IMAGE — derived from mime, persisted
stored_markdown: Mapped[Optional[str]]       # nullable until extraction completes; TEXT column
images_dir: Mapped[Optional[str]]            # storage-relative path; null until extraction
refinement_status: Mapped[RefinementStatus]  # PENDING | IN_PROGRESS | COMPLETE | NOT_REQUIRED
refinement_flags: Mapped[list[dict]]         # JSONB; docling-emitted low-confidence regions
ocr_engine: Mapped[Optional[str]]            # "easyocr" or null (no OCR needed for text-native)
refined_by_id: Mapped[Optional[UUID]]        # FK to users; set when refinement marked complete
refined_at: Mapped[Optional[datetime]]
```

New enums:

```python
class DocumentSourceFormat(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    IMAGE = "IMAGE"

class RefinementStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"   # docling reported no flags — auto-mark as complete
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
```

`DocumentStatus` extension (preserving existing values for backwards compatibility):

```python
class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"           # new — replaces "PROCESSING" semantics for docling
    AWAITING_REFINEMENT = "AWAITING_REFINEMENT"   # new
    INDEXING = "INDEXING"               # new — chunking + embedding post-refinement
    READY = "READY"
    FAILED = "FAILED"
    # legacy values preserved (treated as READY by viewers):
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    ENRICHED = "ENRICHED"
```

The legacy statuses keep existing documents readable without a backfill. New uploads flow through the new statuses only.

### Migration

- One alembic revision: add the new columns (all nullable), add the new enum values to `DocumentStatus`, default `refinement_status='NOT_REQUIRED'` for existing rows (they're already indexed under the old pipeline, no refinement needed retroactively).
- No data migration needed for stored content; existing documents continue to render from the legacy pipeline's outputs.

### `refinement_flags` JSONB shape

```json
[
  {
    "id": "flag-001",
    "kind": "low_confidence_ocr",
    "confidence": 0.31,
    "block_anchor": "table-1.row-1.col-2",
    "source_text": "NaHzPO4119.98",
    "page": 1,
    "bbox": [0.42, 0.31, 0.58, 0.34]
  }
]
```

The frontend uses `block_anchor` to scroll to and highlight the flagged region. `bbox` (normalized page coords) is preserved so the AI panel can crop the source page for vision-LLM-assisted fixes.

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/documents` | Upload; accepts pdf/docx/image. Enqueues extraction. Returns `{id, status: 'QUEUED'}`. |
| `GET` | `/documents/{id}` | Metadata + status + flag count. |
| `GET` | `/documents/{id}/markdown` | Raw stored markdown. 404 until `stored_markdown is not null`. |
| `PUT` | `/documents/{id}/markdown` | Save refined markdown. Sets `refinement_status='IN_PROGRESS'` if first edit. |
| `GET` | `/documents/{id}/images/{n}.png` | Image asset (extracted figure). Permission-gated like the parent document. |
| `GET` | `/documents/{id}/source-page/{n}.png` | Source-page render (pymupdf), used by the editor's left rail. |
| `POST` | `/documents/{id}/refine/ai` | Apply AI to a region. Body: `{scope, selection_markdown, instruction, page?, bbox?}`. Returns `{suggested_markdown, model_used}`. |
| `POST` | `/documents/{id}/refine/complete` | Mark refinement complete. Triggers indexing job. |

Mime allowlist enforced server-side:

```
application/pdf
application/vnd.openxmlformats-officedocument.wordprocessingml.document
image/png  image/jpeg  image/tiff  image/webp
```

URL uploads (`source_url` column) become explicitly unsupported for new uploads — the column stays for legacy rows but the upload endpoint rejects any payload with a `source_url`.

## Pipeline configuration

Hardcoded inside `docling_extractor.py`. Not user-configurable.

```python
pdf_options = PdfPipelineOptions()
pdf_options.do_ocr = True   # always on; for text-native PDFs docling auto-skips OCR per page
pdf_options.generate_picture_images = True
pdf_options.ocr_options = EasyOcrOptions(lang=["en"], force_full_page_ocr=False)
pdf_options.accelerator_options = AcceleratorOptions(
    num_threads=settings.docling_num_threads,
    device=AcceleratorDevice.AUTO,
)
```

The only setting exposed in `Settings` is `docling_num_threads` (default 4, override per host). Device is `AUTO` — picks GPU when available.

## Job infrastructure: extraction launcher

Docling extraction is a long-running, CPU/GPU-bound, single-document job. SOP-scale runs in 1–2 min; book-scale runs in ~30 min on CPU. The existing in-process `TaskRunner` is the right home for the small case but a poor fit for the large one (pod-restart loses ~30 min of work; the ~1 GB docling/torch dependency would bloat every API pod's image just because any pod might be the one to run extraction).

We introduce a dedicated **`ExtractionLauncher`** abstraction — parallel to `TaskRunner` but scoped specifically to document extraction — so the runtime/where-it-runs decision is decoupled from the extractor logic. Other background work (audits, notifications, lifecycle) keeps using `TaskRunner` and stays in-process.

```python
# backend/app/services/documents/extraction/launcher.py

class ExtractionLauncher(ABC):
    @abstractmethod
    async def launch(self, document_id: UUID) -> None:
        """Dispatch extraction for one document. Fire-and-forget.

        Implementations must:
          - Update Document.status -> EXTRACTING before returning.
          - Write a BackgroundJob row and heartbeat from the running worker.
          - Set Document.status -> AWAITING_REFINEMENT (or FAILED) on completion.
        """
        ...


class LocalExtractionLauncher(ExtractionLauncher):
    """Runs docling in the API pod's thread pool via the existing TaskRunner.

    Used in dev and the first prod ramp. Accepts the pod-restart-loses-work
    risk because we don't expect book-scale uploads early on.
    """

    async def launch(self, document_id: UUID) -> None:
        runner = get_task_runner()
        runner.submit(_run_extraction(document_id, settings.database_url))


class CloudGpuExtractionLauncher(ExtractionLauncher):
    """Dispatches extraction to a dedicated worker (Cloud Run GPU service,
    Kubernetes Job, or equivalent). Stub for Phase 2 production; not built
    in Phase B.
    """

    async def launch(self, document_id: UUID) -> None:
        raise NotImplementedError("cloud-gpu launcher not implemented yet")


def get_extraction_launcher() -> ExtractionLauncher:
    backend = settings.extraction_launcher  # "local" | "cloud-gpu"
    if backend == "local":
        return LocalExtractionLauncher()
    if backend == "cloud-gpu":
        return CloudGpuExtractionLauncher()
    raise ValueError(f"unknown extraction_launcher: {backend!r}")
```

New settings on `Settings`:

| Setting | Default | Notes |
| --- | --- | --- |
| `extraction_launcher` | `"local"` | `local` for dev. `cloud-gpu` reserved for staging/prod once that backend lands. |
| `docling_num_threads` | `4` | Forwarded to `AcceleratorOptions`. |
| `docling_models_path` | `~/.cache/huggingface/hub` | Where models live. Image build copies them here. |

Phase B ships **only** `LocalExtractionLauncher`. `CloudGpuExtractionLauncher` exists as a stub (raises `NotImplementedError`) so the factory is in place and the runtime switch is one config change away — but actually building it is staged for whenever the first book-scale workload or pod-restart-loss incident makes it worth the infra cost. The follow-up implementation choice (Cloud Run GPU vs. Kubernetes Job vs. RQ/arq worker pool) gets made then, not now.

The base API container image **does not include docling**. `LocalExtractionLauncher` runs the extractor in-process, so the API pod still needs the dep. To square this:

- Phase B: a single combined image (`batchrite-api`) ships with the docling Poetry group installed. Acceptable while we have one pod role.
- Phase C (paired with `CloudGpuExtractionLauncher`): split into `batchrite-api` (no docling) and `batchrite-extractor` (docling-only). The launcher routes RPCs to the extractor service; the API pod loses ~1 GB of dead weight.

## Refinement editor (frontend)

Design reference: [scripts/mocks/editor-mockups.html](../../../scripts/mocks/editor-mockups.html) — Concept II, themed against `lab-glass`. Three-column workspace; Tiptap canvas in the middle; existing edra `BubbleMenu` and `DragHandle` reused.

Key behaviors:

- **Round-trip**: editor loads markdown → Tiptap doc → user edits → serialize to markdown on save. The stored format is always markdown. HTML is render-only. Image refs in markdown stay relative (`images/3.png`); the API client rewrites to `/documents/{id}/images/3.png` for the live view.
- **Flag → block mapping**: `RefinementQueue.svelte` reads `Document.refinement_flags` and renders one item per flag. Clicking a flag scrolls the editor to the block via the `block_anchor` and highlights the flagged span with the `.flag` styling from the mockup.
- **AI panel**: the panel is selection-aware. When the user selects text, the scope chip auto-switches from "block" to "selection". When they invoke an AI action from a flag, the scope auto-targets that flag's anchor. Submitting calls `POST /documents/{id}/refine/ai`; the response renders as a side-by-side diff (original / suggested) with **Accept** / **Reject** buttons. Accept replaces the markdown in-place and re-runs Tiptap.
- **Save semantics**: explicit save button + autosave every 8 s of idle, matching Protocol editor. Saves are debounced; the "saved 12 sec ago" indicator in the toolbar reflects last successful PUT.
- **Refinement complete**: green primary button in toolbar. Confirms with a dialog noting that indexing will begin and the document becomes searchable. After completion, the editor route 404s (or redirects to `/library/documents/{id}`) — refinement is one-time.
- **Re-open refinement**: librarians (existing `LIBRARY_ADMIN` role) can re-open by hitting `POST /documents/{id}/refine/complete` with `{reopen: true}`. Not exposed in the editor UI itself; lives on the document detail page.

## AI capability: `document_refinement`

- Registered in `ai_config.py`'s `DEFAULT_CONFIGS` with default model `claude-sonnet-4-6` and a system prompt that pins the task: "You are correcting OCR / layout-extraction artifacts in scientific documents. Return only the corrected markdown for the selection — no preamble, no explanation."
- Resolution: `get_model('document_refinement', db, org_id)` — org config wins, then platform env vars (`BATCHRITE_AI_DOCUMENT_REFINEMENT_*`), then default.
- Input contract: `{instruction, selection_markdown, surrounding_context_markdown?, source_page_image_b64?}`. Surrounding context is the 200 chars before and after the selection; the page image (cropped to `bbox`) is included for vision-capable models to ground the correction in pixels.
- Cost discipline: selection-scoped only. No "rewrite the document" action. The refinement queue's "Fix all flags" toolbar button runs the AI sequentially per flag, not as one large call.

## Pass criteria

- Upload of a PDF / docx / image creates a document and runs extraction end-to-end on the dev stack.
- The refinement editor loads the stored markdown, renders it as HTML, surfaces every entry from `refinement_flags`, and saves edits back to markdown round-trip without losing structure (tables stay tables, images stay images).
- AI-fix on a flagged cell returns a suggested replacement and applying it updates the markdown.
- "Mark refinement complete" transitions the document to `INDEXING` and the existing chunker successfully chunks the refined markdown (chunk count ≥ legacy pipeline on the same input).
- A scanned image input round-trips through EasyOCR with `force_full_page_ocr` auto-enabled when no text layer is detected (the extractor service decides this from the input type).
- `document_structure.py`, `process_document`, `enrich_document`, `enrich_document_endpoint`, `build_book`, and the `doc_structure` AI capability are deleted. `grep -r 'doc_structure\|document_structure' backend/app` returns no hits outside of migration files.
- `pyproject.toml` declares docling in the `[tool.poetry.group.docling]` group; the base API image builds in CI without it; the extractor-job image builds with it.

## Critical files

| Path | Change |
| --- | --- |
| `backend/pyproject.toml` | Add docling group; bump torch constraint |
| `backend/app/core/config.py` | Add `docling_num_threads` setting; remove `doc_structure` defaults |
| `backend/app/models/library.py` | Document field additions, new enums |
| `backend/alembic/versions/<new>.py` | New migration: columns + enum values |
| `backend/app/services/documents/extraction/docling_extractor.py` | **New** — wraps docling |
| `backend/app/services/documents/extraction/image_externalizer.py` | **New** — writes picture regions to disk |
| `backend/app/services/jobs/extract_document.py` | **New** — extraction job |
| `backend/app/services/ai/ai_config.py` | Register `document_refinement` capability; remove `doc_structure` |
| `backend/app/services/documents/markdown_chunker.py` | Trim structure-aware logic; consume refined markdown directly |
| `backend/app/api/endpoints/library.py` | New endpoints (markdown/images/refine); remove enrich_document_endpoint |
| `backend/app/schemas/library.py` | New schemas: `DocumentRefinementPayload`, `RefineAiRequest/Response`, etc. |
| `backend/app/services/documents/document_structure.py` | **Delete** |
| `backend/app/services/documents/document_processor.py` | Remove `process_document`, `enrich_document`, `build_book` |
| `frontend/src/routes/library/documents/[id]/refine/+page.svelte` | **New** — refinement route |
| `frontend/src/lib/components/document-refinement/RefinementEditor.svelte` | **New** |
| `frontend/src/lib/components/document-refinement/RefinementSidebar.svelte` | **New** |
| `frontend/src/lib/components/document-refinement/RefinementQueue.svelte` | **New** |
| `frontend/src/lib/components/document-refinement/RefinementAiPanel.svelte` | **New** |
| `frontend/src/lib/components/shared/MarkdownDocument.svelte` | **New** — read-only renderer |
| `frontend/src/lib/api/documents.ts` | New API client methods |
| `frontend/src/lib/schemas/documents.ts` | Zod schemas for refinement payloads |
| `.claude/rules/conventions.md` | Add `document-refinement/` to the component-placement bucket list |
| `CLAUDE.md` | Update Architecture section if any new top-level conventions land |

## Risks

| Risk | Mitigation |
| --- | --- |
| Torch constraint conflict with rest of Poetry deps (`OverrideNeededError` confirmed in eval) | Isolate docling into `[tool.poetry.group.docling]`; only the extractor-worker image installs it. Base API image stays slim. If group isolation doesn't fully resolve it, fallback is a sidecar service exposing `POST /extract` over HTTP. |
| Cold-start model download (~1 GB) stalls first request by minutes | `docling-tools models download` runs at image build; EasyOCR warmup runs at container start (an empty `.convert()` call against a 1×1 PNG). |
| Markdown round-trip in Tiptap loses structure (tables, lists, image refs) | Existing edra setup already round-trips markdown for the protocol editor's rich-text notes; reuse those serializer extensions. Add an explicit round-trip test fixture: `assert markdown == tiptap_to_md(md_to_tiptap(markdown))` for the eval-spike outputs. |
| Users skip refinement and index garbage | Refinement is gated: `INDEXING` only triggers from `POST /refine/complete`. The library list view shows a clear "Needs refinement" badge for `AWAITING_REFINEMENT` documents and hides them from search results until complete. |
| Per-page latency on no-GPU production hosts | Inherits from the eval: SOP-scale (5–50 pages) ≈ 12 s – 2 min, acceptable as a background job. Book-scale = 30 min, documented as a known constraint. Plan for a GPU node if book-scale ingestion becomes a regular pattern. |
| AI refinement cost runs away on large queue | Per-flag selection-scoped calls; surrounding context capped at 200 chars + optional page-crop image. "Fix all flags" iterates sequentially and shows a stop button. |
| EasyOCR introduces its own artifacts (the eval flagged missing cells, garbled formulas) | These are exactly what the refinement queue surfaces — `refinement_flags` is populated from docling's per-region confidence scores. The whole point of the refinement phase is that OCR is imperfect. |
| Existing documents (pre-migration) still depend on the deleted pipeline for re-processing | They don't — once indexed, documents don't re-process. The deletion is safe. If a legacy document genuinely needs to be re-extracted, it gets re-uploaded under the new pipeline. |

## Verification

1. Upload a representative SOP (5–10 pages, mixed text + one table + one figure) via the new endpoint. Watch the status transitions: `QUEUED → EXTRACTING → AWAITING_REFINEMENT` within ~30 s.
2. Open `/library/documents/{id}/refine`. Editor loads. Refinement queue shows ≥0 flags. Source thumbnail renders. AI panel is interactive.
3. Click a flag → editor scrolls and highlights. Click "Ask AI to fix" → suggested replacement appears in the diff view. Accept → markdown updates and queue item disappears.
4. Save → markdown PUT succeeds. Reload page → edits persist.
5. Click "Mark refinement complete" → status transitions to `INDEXING` then `READY`. Document appears in library search results.
6. Verify a re-upload of the same file through the new pipeline produces byte-comparable markdown to the eval's `no-ocr` output.
7. `grep -r 'doc_structure\|document_structure' backend/app/services backend/app/api` returns 0 hits.
8. Existing legacy-status documents (`INDEXED`, `ENRICHED`) still load in the library list and the read-only viewer.

## Out of scope (deferred to future tasks)

- Web/URL ingestion (separate spike if/when needed; not docling's problem).
- Multi-language OCR.
- Collaborative real-time editing on the refinement editor.
- AI-driven structural transforms ("turn this prose into a step list") — the current AI scope is artifact-fix only.
- GPU node provisioning for production extraction (a separate infra task once book-scale ingestion is in demand).
- Replacing pymupdf for source-page rendering in the editor's left rail.
- Bulk re-extraction of legacy documents to the new format (one-off script, separate task if needed).
