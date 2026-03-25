# Document Processing Pipeline

The document processing pipeline handles PDF uploads through a two-pass architecture: an immediate extraction pass that makes the document readable, followed by an async LLM-based enrichment pass that classifies document structure for improved rendering.

## Pipeline Overview

```
Upload PDF
    |
    v
Pass 1: Extraction & Chunking (no LLM)
    - Per-page text extraction via pymupdf4llm
    - Page-level chunking (no overlap)
    - Embedding generation (best-effort)
    - Document status: INDEXED
    - Document is readable immediately
    |
    v
Pass 2: LLM Structure Enrichment (async, non-blocking)
    - Renders pages as PNG images
    - Sends page images to multimodal LLM in batches of 30
    - Classifies each page: role, headers, footers, sections
    - Re-chunks with structure awareness
    - Document status: ENRICHED
    - Frontend upgrades to section nav + role-based rendering
```

## Architecture

### Key Files

| File | Purpose |
|------|---------|
| `backend/app/services/document_processor.py` | Main pipeline: `process_document()` and `enrich_document()` |
| `backend/app/services/markdown_chunker.py` | Chunking: `chunk_by_pages()` and `rechunk_with_structure()` |
| `backend/app/services/document_structure.py` | LLM classification service |
| `backend/app/services/text_chunker.py` | `PageData` and `TextChunk` dataclasses |
| `backend/app/models/jobs.py` | `BackgroundJob` model for job tracking |
| `backend/app/models/library.py` | `Document` and `DocumentChunk` models |
| `backend/app/services/ai_config.py` | AI provider resolution (Ollama, Anthropic, OpenAI, Google) |
| `frontend/src/routes/library/[id]/+page.svelte` | Document viewer with structure-aware rendering |

### Document Statuses

| Status | Meaning |
|--------|---------|
| `UPLOADED` | File stored, processing not yet started |
| `PROCESSING` | Pass 1 in progress (extraction + chunking) |
| `INDEXED` | Pass 1 complete, document is readable. Pass 2 may be in progress. |
| `ENRICHED` | Pass 2 complete, structure metadata available |
| `FAILED` | Processing failed (check `error_message`) |

### Non-blocking Guarantees

All processing runs outside the request lifecycle. The upload endpoint returns immediately.

| Operation | Execution Method | Why Non-blocking |
|-----------|-----------------|-----------------|
| PDF text extraction | Thread pool (`run_sync`) | CPU-bound |
| Page image rendering | Thread pool (`run_sync`) | CPU-bound |
| LLM classification | `httpx.AsyncClient` | Async I/O |
| Embedding generation | `httpx.AsyncClient` | Async I/O |
| DB operations | `asyncpg` | Async I/O |

## Pass 1: Extraction & Chunking

### Per-Page Extraction

The function `extract_pdf_pages()` (and its batched variant `_extract_pdf_page_range()`) processes each PDF page individually using `pymupdf4llm.to_markdown(doc, pages=[i])`. This is a deliberate design choice over extracting the entire document at once, because:

- Multi-column layouts are handled correctly when scope is one page
- No column text interleaving
- Exact page boundaries (no proportional scaling approximation)
- Each page also gets a rendered PNG image for the LLM pass

### Page-Level Chunking

`chunk_by_pages()` converts pages to chunks with these rules:

- Each page normally becomes one chunk
- Short pages (< 100 tokens) are merged with neighbors
- Long pages (> 2000 tokens) are split at heading boundaries
- **No overlap** between chunks (overlap is only useful for RAG search, not sequential reading)

### Progress Reporting

During extraction, progress is flushed to the `BackgroundJob.output_data` every 10 pages:

```json
{
  "stage": "extracting",
  "stage_label": "Extracting text",
  "current": 340,
  "total": 676,
  "percent": 50
}
```

The frontend polls the document detail endpoint every 3 seconds and renders a progress bar from this data.

Stages reported: `extracting` -> `chunking` -> `embedding`

## Pass 2: LLM Structure Enrichment

### Triggering

After Pass 1 sets the document to `INDEXED`, it checks if the `doc_structure` AI capability is configured. If so, it submits `enrich_document()` as a fire-and-forget async task.

Enrichment can also be triggered manually via `POST /library/documents/{id}/enrich`.

### Classification

The `document_structure.py` service:

1. Renders all pages as PNG images at 150 DPI
2. Batches page images into groups of 30
3. Sends each batch to the multimodal LLM with a classification prompt
4. The LLM returns JSON classifying each page:

```json
{
  "pages": [
    {
      "page": 1,
      "role": "front_matter",
      "running_header": null,
      "running_footer": null,
      "section_heading": null,
      "has_figures": false,
      "is_scanned": false
    }
  ]
}
```

Page roles: `front_matter`, `toc`, `body`, `appendix`, `index`, `bibliography`, `blank`

### Structure-Aware Re-Chunking

`rechunk_with_structure()` uses the classification to:

- Strip running headers/footers from page text
- Merge all front matter pages into a single chunk
- Merge all TOC pages into a single chunk
- Merge consecutive body pages that share the same `section_heading`
- Split oversized sections (> 3000 tokens) at paragraph boundaries
- Tag each chunk's `chunk_metadata` with `role` and `section_heading`

### Graceful Degradation

- If the LLM is unavailable, the document stays `INDEXED` (still fully readable)
- If a batch fails, those pages default to `role="body"`
- If enrichment crashes entirely, the `BackgroundJob` is marked `FAILED` and can be retried

## Job Tracking

All async work is tracked via the `background_jobs` table.

### BackgroundJob Fields

| Field | Purpose |
|-------|---------|
| `job_type` | `document_process` or `document_enrich` |
| `status` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED` |
| `entity_type` / `entity_id` | Links to the document being processed |
| `input_data` | JSONB with job parameters |
| `output_data` | JSONB with progress updates and final results |
| `error_message` | Failure details |
| `started_at` / `completed_at` | Timing |
| `worker_id` | Hostname of the pod/worker that claimed the job |
| `attempts` / `max_attempts` | Retry tracking |

### Future Extensibility

The job table supports the `SELECT ... FOR UPDATE SKIP LOCKED` pattern for external workers:

1. External worker polls: `SELECT ... WHERE status='PENDING' FOR UPDATE SKIP LOCKED`
2. Claims job: sets `status='RUNNING'`, `worker_id`
3. Executes using `input_data`
4. Reports back: sets `output_data`, `status='COMPLETED'` or `FAILED`

This means the current in-process `ThreadTaskRunner` can be swapped to Kubernetes Jobs or Celery without changing the pipeline logic.

## AI Provider Configuration

The `doc_structure` capability uses the same provider abstraction as all other AI features.

### Resolution Order

1. In-memory cache (30-second TTL)
2. Database (`ai_provider_configs` table, capability = `doc_structure`)
3. Environment variables (`RUNBOOK_AI_DOC_STRUCTURE_PROVIDER`, `RUNBOOK_AI_DOC_STRUCTURE_MODEL`, etc.)
4. Hardcoded default: `ollama` / `llama3.2-vision`

### Environment Variables

```bash
RUNBOOK_AI_DOC_STRUCTURE_PROVIDER=ollama          # or anthropic, openai, google
RUNBOOK_AI_DOC_STRUCTURE_MODEL=llama3.2-vision    # model name
RUNBOOK_AI_DOC_STRUCTURE_API_KEY=                  # for cloud providers
RUNBOOK_AI_DOC_STRUCTURE_BASE_URL=                 # custom endpoint
```

### Provider Support

- **Ollama**: Uses native `/api/chat` endpoint with base64 images and `format: json`
- **Cloud providers** (Anthropic, OpenAI, Google): Uses pydantic-ai Agent with `BinaryContent` for images and structured output

### Local Development

The default model `llama3.2-vision:11b` runs on Ollama and fits in ~8GB VRAM (suitable for RTX 9070 XT with 16GB).

```bash
ollama pull llama3.2-vision
```

## Frontend Rendering

The document viewer (`/library/[id]`) adapts based on document status:

### INDEXED (no structure metadata)

- Renders chunks as continuous content
- Page break dividers between pages
- Search within document

### ENRICHED (structure metadata available)

- **Section navigation sidebar**: sticky sidebar with section headings, click to scroll
- **Collapsible front matter**: collapsed by default, expandable toggle
- **Collapsible TOC**: collapsed by default, expandable toggle
- **Body content**: continuous prose rendering with no chunk boundaries
- **Progress bar**: shown during processing/enrichment with stage label and percentage

## Monitoring

### Job Monitor CLI

```bash
cd backend

# Live watch active jobs (refreshes every 2s)
python scripts/job_monitor.py

# Show all jobs including completed/failed
python scripts/job_monitor.py --all

# Watch jobs for a specific document
python scripts/job_monitor.py --doc <document-uuid>

# Print once and exit
python scripts/job_monitor.py --all --once

# Reset a stuck job (marks job FAILED, resets document to UPLOADED)
python scripts/job_monitor.py --reset <job-uuid>
```

The monitor shows: job status with color coding, document title, duration with stale warnings (yellow > 5min, red > 10min), live progress bar, error messages, and worker ID.

### Stale Job Detection

Jobs running longer than `STALE_PROCESSING_SECONDS` (300s / 5 minutes) are considered potentially stuck. The startup recovery hook in `app/main.py` automatically resets stale `PROCESSING` documents on server restart.

### Database Queries

Check a specific document's processing state:

```sql
-- Document status
SELECT status, page_count, structure_metadata IS NOT NULL as enriched
FROM documents WHERE id = '<uuid>';

-- Job history
SELECT job_type, status, output_data, error_message,
       started_at, completed_at
FROM background_jobs
WHERE entity_id = '<uuid>'
ORDER BY created_at DESC;

-- Active jobs across all documents
SELECT j.job_type, j.status, j.output_data, d.title
FROM background_jobs j
JOIN documents d ON d.id = j.entity_id
WHERE j.status IN ('PENDING', 'RUNNING')
ORDER BY j.created_at DESC;
```
