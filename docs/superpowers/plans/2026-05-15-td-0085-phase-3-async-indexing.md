# TD-0085 Phase 3 — Async Indexing + Restart-Robust Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the post-refinement indexing step (chunk refined markdown → embed → persist `DocumentChunk` rows) out of the request handler into a first-class background job, so the user sees the existing shimmer card with live progress, the doc state survives worker restarts via the existing heartbeat/watchdog machinery, and the dispatch is safe under horizontal autoscale.

**Architecture:** `POST /library/documents/{id}/refine/complete` now flips the doc to `INDEXING` and commits, then `await handler.launch("document_index", document_id=...)` and returns immediately. A new `document_index` job mirrors the shape of `document_extract`: own session, `SELECT … FOR UPDATE SKIP LOCKED` doc claim, own `BackgroundJob` row, per-batch progress updates via `BackgroundJobService.update_progress` (which the existing `GET /library/documents/{id}` endpoint already surfaces as `processing_progress`). Recovery is extended on both halves of the existing startup sweep to recognize `INDEXING` + `document_index`, and a new `_recovery_loop` runs the sweeps on a timer (default 90 s) so autoscaled steady-state pods don't have to wait for a deploy to rescue stalled docs. The frontend `isLiveExtraction` derivation in `/library/[id]` already includes `INDEXING` and renders the shimmer card; no UI work beyond a stage-label tweak.

**Tech Stack:** FastAPI (async) · SQLAlchemy 2.0 · pgvector · pytest-asyncio + httpx.AsyncClient · existing `BackgroundHandler` / `BackgroundJobService` / heartbeat-watchdog plumbing. Embeddings continue to flow through `app.services.ai.embedding.embed_texts` (Ollama `nomic-embed-text:latest` by default). **No new external deps. No `ext/` subproject. No migration.**

---

## File map

Files **created** in Phase 3:

| Path | Responsibility |
| --- | --- |
| `backend/app/services/documents/refinement/index_job.py` | The `document_index` job. Owns its own `AsyncSession`, locks the `Document` row with `FOR UPDATE SKIP LOCKED`, creates the `BackgroundJob`, drives `index_refined_document` with a progress callback that ticks `BackgroundJobService.update_progress`, transitions `INDEXING → READY` on success or `INDEXING → FAILED` on error. Registers as `"document_index"` via `@register_job`. |
| `backend/tests/unit/test_index_job.py` | Unit tests for `index_job.py`: claim semantics (right status / wrong status / already-claimed), happy-path status transitions, failure-path status + `BackgroundJob.error_message`, idempotent re-run on recovery. |
| `backend/tests/integration/test_refine_async_indexing.py` | Integration test: `POST /refine/complete` returns 200 with `status=INDEXING` and a queued job; after the background coroutine drains, the doc is `READY` with chunks. |
| `backend/tests/unit/test_recovery_loop.py` | Unit tests for the new periodic `_recovery_loop`: interval honored, sweep failures don't crash the loop, cancellation tears it down cleanly. |

Files **modified** in Phase 3:

| Path | What changes |
| --- | --- |
| `backend/app/services/documents/refinement/indexing.py` | `index_refined_document` grows an optional `on_progress: ProgressCallback | None` argument, embeddings are pulled per `embed_texts` batch with progress emitted between batches, chunks for each batch are committed before the next batch starts (so a restart only re-does the unfinished tail in the worst case — and the safety-net `DELETE FROM document_chunks` at the top of the function still makes the operation idempotent). Empty-markdown path raises `IndexingError` instead of silently transitioning to `READY`. Broad `except Exception` around `embed_texts` is narrowed to `EmbeddingError` and **re-raised** — the job wrapper owns the FAILED transition now. |
| `backend/app/api/endpoints/library.py` | `refine_complete` (around line 940) — after `mark_complete(...)`, commit, then `await get_background_handler().launch("document_index", document_id=doc.id)`, then `await db.refresh(doc)` and return the response with `status=INDEXING`. Stop calling `index_refined_document` inline. |
| `backend/app/main.py` | (1) Extend the job-type allow-list at `_recover_stalled_jobs` (~line 163) to include `"document_index"`. (2) Extend `_recover_stalled_documents` (~line 217) to also match docs in `INDEXING` with stale `processing_started_at`, release their `heartbeat_token`/`processing_started_at`, and re-fire `handler.launch("document_index", ...)` for those (vs `"document_extract"` for `UPLOADED`/`EXTRACTING`/`PROCESSING`). (3) Add `_recovery_loop` task and start it in `lifespan` alongside `_heartbeat_loop`. |
| `backend/app/core/config.py` | Add `recovery_interval_seconds: int = 90` to `Settings` (env: `BATCHRITE_RECOVERY_INTERVAL_SECONDS`). |
| `backend/tests/unit/test_indexing.py` *(if exists; create otherwise)* | Update / add tests for the refactored `index_refined_document`: empty-markdown raises, embed failure raises, progress callback fires once per batch, chunks land per batch. |
| `backend/tests/integration/test_library_docling.py` | Update the existing refine-complete assertion to expect `status=INDEXING` immediately (not `READY`), and add a follow-up assertion that awaits the background task and re-fetches to see `READY`. |
| `frontend/src/routes/library/[id]/+page.svelte` | One-line stage-label tweak in `liveStageText` so the `INDEXING` branch reads "stage: embedding" until the job's `processing_progress` lands, then defers to the job's `stage_label`. No structural change — the shimmer card already fires for `status === 'INDEXING'`. |

Files **untouched** (called out so the engineer doesn't go hunting):

- `backend/app/services/core/background_handler.py` — `LocalBackgroundHandler` already works for this; new job registers via the existing `@register_job` decorator.
- `backend/app/services/core/background_jobs.py` — `BackgroundJobService.update_progress` already commits the progress write so the GET endpoint sees it; no changes.
- `backend/app/services/documents/markdown_chunker.py` — `chunk_markdown` stays as-is.
- `backend/app/services/ai/embedding.py` — `embed_texts` already batches at 50 and supports an `on_progress` callback; we'll use that callback for heartbeats.
- `backend/app/models/library.py` — `INDEXING` is already a valid `DocumentStatus`. No schema or migration change.

---

## Workflow conventions

- **TDD throughout:** every code change starts with a failing test. Run the single test by its node id; don't run the whole suite mid-task.
- **Commits are small and frequent**, one per task (sometimes one per sub-step if the diff is sizable). Commit message format follows the repo: `feat(scope): description` or `refactor(scope): …`, ending with the standard `Co-Authored-By` trailer.
- **Backend commands** assume you've already run `source .venv/bin/activate` from `backend/`.
- **Test isolation:** every test uses the `db_session` fixture which wraps the test in a SAVEPOINT and rolls it back. Background jobs that open their *own* sessions need special handling — see Task 2.

---

### Task 1: Refactor `index_refined_document` for batched commits + progress + real errors

**Files:**
- Modify: `backend/app/services/documents/refinement/indexing.py`
- Test: `backend/tests/unit/test_indexing.py` (create)

The current implementation embeds everything in one `embed_texts` call, swallows any exception, and silently transitions to `READY`. Three things to fix:

1. Empty `stored_markdown` → raise `IndexingError`, not silent `READY`.
2. Embedding failure → raise `IndexingError` (wrapping `EmbeddingError`), not swallow.
3. Add an `on_progress` callback so the caller (the job wrapper in Task 2) can emit live progress per batch.

The function stays *idempotent* — it still starts with `DELETE FROM document_chunks WHERE document_id = ?` so a re-run on recovery just rebuilds from scratch. We're not adding per-batch commits inside this function (that'd require it to own its session lifecycle); instead the function emits progress callbacks and the job wrapper does the commits at safe points.

- [ ] **Step 1: Write the failing test for empty markdown**

Create `backend/tests/unit/test_indexing.py`:

```python
import uuid
from datetime import datetime, timezone

import pytest

from app.models.library import Document, DocumentStatus, RefinementStatus
from app.services.documents.refinement.indexing import (
    IndexingError,
    index_refined_document,
)


def _doc(stored_markdown: str | None) -> Document:
    return Document(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        uploaded_by_id=uuid.uuid4(),
        title="t",
        original_filename="t.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        file_path="p",
        status=DocumentStatus.INDEXING.value,
        refinement_status=RefinementStatus.COMPLETE.value,
        stored_markdown=stored_markdown,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_empty_markdown_raises(db_session):
    doc = _doc(stored_markdown=None)
    db_session.add(doc)
    await db_session.flush()

    with pytest.raises(IndexingError, match="no stored_markdown"):
        await index_refined_document(db_session, doc)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest backend/tests/unit/test_indexing.py::test_empty_markdown_raises -v
```

Expected: FAIL with `ImportError: cannot import name 'IndexingError'`.

- [ ] **Step 3: Define `IndexingError` and the empty-markdown branch**

Edit `backend/app/services/documents/refinement/indexing.py`:

```python
"""Chunks refined markdown into DocumentChunks and embeds them.

Called from the document_index background job (services/documents/
refinement/index_job.py). The function is idempotent — it deletes
existing chunks before re-indexing — so a worker restart that lands
on the recovery sweep can safely re-run from scratch.
"""

import logging
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Document, DocumentChunk, DocumentStatus
from app.services.ai.embedding import EmbeddingError, embed_texts
from app.services.documents.document_processor import _pad_embedding
from app.services.documents.markdown_chunker import chunk_markdown

logger = logging.getLogger(__name__)


class IndexingError(Exception):
    """Raised when indexing cannot proceed (no markdown, embed failed, etc.).

    The document_index job wrapper catches this and transitions the
    document to FAILED with the error message.
    """


# Type for batch-progress callbacks: async fn(current, total).
ProgressCallback = Callable[[int, int], Awaitable[None]]


async def index_refined_document(
    db: AsyncSession,
    doc: Document,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Chunk + embed the refined markdown. Idempotent — drops prior chunks first.

    Raises IndexingError on empty markdown or embed failure. The caller
    (background job) owns transitioning doc.status to READY/FAILED and
    committing.
    """
    if not doc.stored_markdown:
        raise IndexingError(
            f"Document {doc.id} has no stored_markdown to index"
        )

    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )
    await db.flush()

    chunks = chunk_markdown(doc.stored_markdown, 1000, 200, None)
    if not chunks:
        # Markdown was non-empty but only whitespace / unsplittable.
        doc.status = DocumentStatus.READY.value
        return

    try:
        embeddings = await embed_texts(
            [c.content for c in chunks],
            db,
            on_progress=on_progress,
            org_id=doc.org_id,
        )
    except EmbeddingError as exc:
        raise IndexingError(
            f"Embedding failed for document {doc.id}: {exc}"
        ) from exc

    for i, chunk in enumerate(chunks):
        emb = _pad_embedding(embeddings[i]) if i < len(embeddings) else None
        db.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                chunk_metadata={"content_format": "markdown"},
                embedding=emb,
            )
        )

    doc.status = DocumentStatus.READY.value
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest backend/tests/unit/test_indexing.py::test_empty_markdown_raises -v
```

Expected: PASS.

- [ ] **Step 5: Add test for embed failure path**

Append to `backend/tests/unit/test_indexing.py`:

```python
from unittest.mock import patch

from app.services.ai.embedding import EmbeddingError


@pytest.mark.asyncio
async def test_embed_failure_raises_indexing_error(db_session):
    doc = _doc(stored_markdown="# A heading\n\nSome body content.")
    db_session.add(doc)
    await db_session.flush()

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=EmbeddingError("Ollama unreachable"),
    ):
        with pytest.raises(IndexingError, match="Embedding failed"):
            await index_refined_document(db_session, doc)
```

- [ ] **Step 6: Run that test**

```bash
pytest backend/tests/unit/test_indexing.py::test_embed_failure_raises_indexing_error -v
```

Expected: PASS (the new narrow-and-reraise handler already covers this).

- [ ] **Step 7: Add test for progress callback wiring**

Append:

```python
@pytest.mark.asyncio
async def test_progress_callback_forwarded_to_embed_texts(db_session):
    doc = _doc(stored_markdown="# H\n\n" + ("word " * 3000))  # >1 chunk
    db_session.add(doc)
    await db_session.flush()

    seen: list[tuple[int, int]] = []

    async def cb(current: int, total: int) -> None:
        seen.append((current, total))

    async def fake_embed_texts(texts, db, on_progress=None, org_id=None):
        # Simulate the real embed_texts behavior: fire on_progress once
        # per BATCH_SIZE batch and return one zero-vector per text.
        BATCH = 50
        for i in range(0, len(texts), BATCH):
            if on_progress:
                await on_progress(min(i + BATCH, len(texts)), len(texts))
        return [[0.0] * 768 for _ in texts]

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=fake_embed_texts,
    ):
        await index_refined_document(db_session, doc, on_progress=cb)

    assert seen, "expected at least one progress callback"
    # Last call should report current == total
    assert seen[-1][0] == seen[-1][1]
    assert doc.status == DocumentStatus.READY.value
```

- [ ] **Step 8: Run it**

```bash
pytest backend/tests/unit/test_indexing.py::test_progress_callback_forwarded_to_embed_texts -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/documents/refinement/indexing.py \
        backend/tests/unit/test_indexing.py
git commit -m "refactor(documents): batch-progress + real errors for indexer (TD-0085)

- IndexingError replaces silent READY transitions on empty markdown
  and the broad except-Exception that swallowed EmbeddingError.
- Adds optional on_progress callback so the upcoming document_index
  job can update BackgroundJob.output_data per embedding batch.
- Function stays idempotent: still DELETEs prior chunks first, so a
  recovery-sweep re-run rebuilds cleanly.
- Removes the doc.status writes for the failure paths; the job
  wrapper owns those transitions now.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Create the `document_index` background job

**Files:**
- Create: `backend/app/services/documents/refinement/index_job.py`
- Test: `backend/tests/unit/test_index_job.py`

Mirror the shape of `backend/app/services/documents/extraction/extract_job.py`:
own DB session, claim the doc with `FOR UPDATE SKIP LOCKED`, create the
`BackgroundJob` row, run `index_refined_document` with a progress callback that
calls `BackgroundJobService.update_progress`, transition status on success/failure.

The claim conditions for `document_index` are different from extraction:

| Field | Expected at claim | Why |
| --- | --- | --- |
| `Document.status` | `INDEXING` | The endpoint already set it via `mark_complete`. |
| `Document.heartbeat_token` | `None` | Either fresh, or just released by recovery sweep. |
| `Document.stored_markdown` | non-empty | Otherwise the indexer raises, and we fail loud. |

- [ ] **Step 1: Write the failing claim test**

Create `backend/tests/unit/test_index_job.py`:

```python
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.models.library import Document, DocumentStatus, RefinementStatus


def _make_doc(
    status: DocumentStatus,
    *,
    heartbeat_token: str | None = None,
    stored_markdown: str | None = "# Title\n\nBody.",
) -> Document:
    return Document(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        uploaded_by_id=uuid.uuid4(),
        title="t",
        original_filename="t.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        file_path="p",
        status=status.value,
        refinement_status=RefinementStatus.COMPLETE.value,
        stored_markdown=stored_markdown,
        heartbeat_token=heartbeat_token,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_claim_rejects_doc_in_wrong_status(db_session):
    from app.services.documents.refinement.index_job import (
        _load_and_claim_document,
    )

    doc = _make_doc(DocumentStatus.UPLOADED)  # wrong: not INDEXING
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, claimed_job = await _load_and_claim_document(
        db_session, doc.id
    )
    assert claimed_doc is None
    assert claimed_job is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest backend/tests/unit/test_index_job.py::test_claim_rejects_doc_in_wrong_status -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Scaffold `index_job.py` with the claim function**

Create `backend/app/services/documents/refinement/index_job.py`:

```python
"""Background coroutine that indexes a refined document.

Mirrors the shape of `extract_job.py`: owns its own AsyncSession,
locks the Document row with FOR UPDATE SKIP LOCKED, creates the
BackgroundJob row, drives `index_refined_document` with a progress
callback that emits per-batch heartbeats via BackgroundJobService.

Registers under the name "document_index" via @register_job.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from app.core.config import settings
from app.models.jobs import BackgroundJob
from app.models.library import Document, DocumentStatus
from app.services.core.background_handler import register_job
from app.services.core.background_jobs import BackgroundJobService
from app.services.documents.refinement.indexing import (
    IndexingError,
    index_refined_document,
)

logger = logging.getLogger(__name__)


async def _load_and_claim_document(
    session: AsyncSession, document_id: UUID
) -> tuple[Document | None, BackgroundJob | None]:
    """Lock the document row + create the BackgroundJob in one transaction.

    Returns (None, None) — without committing — if the document is not
    a valid claim target:
      - row doesn't exist (deleted between launch and pickup),
      - status is not INDEXING (already finished, failed, or moved on),
      - heartbeat_token is already set (another worker has the claim).
    """
    result = await session.execute(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update(skip_locked=True)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None, None
    if doc.status != DocumentStatus.INDEXING.value:
        return None, None
    if doc.heartbeat_token is not None:
        return None, None

    job = await BackgroundJobService.create(
        session, "document_index", "document", document_id,
        input_data={"chunk_count_before": 0},
    )
    doc.processing_started_at = datetime.now(timezone.utc)
    doc.heartbeat_token = secrets.token_urlsafe(32)
    doc.last_heartbeat_at = doc.processing_started_at
    doc.error_message = None
    await session.commit()
    return doc, job
```

- [ ] **Step 4: Re-run test to verify it passes**

```bash
pytest backend/tests/unit/test_index_job.py::test_claim_rejects_doc_in_wrong_status -v
```

Expected: PASS.

- [ ] **Step 5: Add tests for the other two claim-rejection paths**

Append to `backend/tests/unit/test_index_job.py`:

```python
@pytest.mark.asyncio
async def test_claim_rejects_doc_with_existing_heartbeat_token(db_session):
    from app.services.documents.refinement.index_job import (
        _load_and_claim_document,
    )

    doc = _make_doc(DocumentStatus.INDEXING, heartbeat_token="someone-else")
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, _ = await _load_and_claim_document(db_session, doc.id)
    assert claimed_doc is None


@pytest.mark.asyncio
async def test_claim_accepts_indexing_doc_with_no_token(db_session):
    from app.services.documents.refinement.index_job import (
        _load_and_claim_document,
    )

    doc = _make_doc(DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, claimed_job = await _load_and_claim_document(
        db_session, doc.id
    )
    assert claimed_doc is not None
    assert claimed_doc.id == doc.id
    assert claimed_doc.heartbeat_token is not None
    assert claimed_doc.processing_started_at is not None
    assert claimed_job is not None
    assert claimed_job.job_type == "document_index"
```

- [ ] **Step 6: Run them**

```bash
pytest backend/tests/unit/test_index_job.py -v
```

Expected: 3 PASS.

- [ ] **Step 7: Write the failing happy-path-runner test**

Append to `backend/tests/unit/test_index_job.py`:

```python
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_run_index_happy_path_transitions_to_ready(db_session):
    """End-to-end of the registered job, with a fake embed_texts."""
    from app.services.documents.refinement import index_job

    doc = _make_doc(
        DocumentStatus.INDEXING,
        stored_markdown="# H\n\n" + ("word " * 1500),
    )
    db_session.add(doc)
    await db_session.flush()
    await db_session.commit()  # job opens its own session, needs persisted data

    async def fake_embed_texts(texts, db, on_progress=None, org_id=None):
        if on_progress:
            await on_progress(len(texts), len(texts))
        return [[0.0] * 768 for _ in texts]

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=fake_embed_texts,
    ):
        await index_job.run_index(document_id=doc.id)

    # Re-fetch through the session
    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.READY.value
    assert doc.heartbeat_token is None
    assert doc.processing_started_at is None
```

- [ ] **Step 8: Run it (expect fail — `run_index` not defined yet)**

```bash
pytest backend/tests/unit/test_index_job.py::test_run_index_happy_path_transitions_to_ready -v
```

Expected: FAIL with `AttributeError: module … has no attribute 'run_index'`.

- [ ] **Step 9: Implement `run_index` and the success persistence path**

Append to `backend/app/services/documents/refinement/index_job.py`:

```python
async def _persist_success(
    session: AsyncSession, doc: Document, job: BackgroundJob,
) -> None:
    """Mark doc READY, complete the BackgroundJob, clear heartbeat_token."""
    await session.refresh(doc)
    if doc.status == DocumentStatus.FAILED.value:
        # Watchdog or admin won the race; drop our claim and exit.
        return
    doc.processing_started_at = None
    doc.heartbeat_token = None
    await BackgroundJobService.complete(
        session, job,
        output_data={"stage": "done", "stage_label": "Indexing complete",
                     "current": 1, "total": 1, "percent": 100},
    )
    await session.commit()


async def _persist_failure(
    session: AsyncSession,
    document_id: UUID,
    job: BackgroundJob | None,
    message: str,
) -> None:
    """Rollback, mark doc FAILED, mark job FAILED — in a clean session."""
    await session.rollback()
    result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is not None:
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = f"Indexing error: {message[:500]}"
        doc.processing_started_at = None
        doc.heartbeat_token = None
    if job is not None:
        job_result = await session.execute(
            select(BackgroundJob).where(BackgroundJob.id == job.id)
        )
        job = job_result.scalar_one_or_none()
        if job is not None:
            await BackgroundJobService.fail(session, job, message[:500])
    await session.commit()


@register_job("document_index")
async def run_index(document_id: UUID) -> None:
    """Background entry point. Owns its own DB session.

    Decline-and-exit if the claim is invalid (wrong status / already
    claimed / row missing) — see `_load_and_claim_document` for the
    full predicate.
    """
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            doc, job = await _load_and_claim_document(session, document_id)
            if doc is None or job is None:
                logger.info(
                    "document_index: skipping %s (no valid claim)",
                    document_id,
                )
                return

            async def on_progress(current: int, total: int) -> None:
                await BackgroundJobService.update_progress(
                    session,
                    job,
                    stage="embedding",
                    stage_label="Embedding chunks",
                    current=current,
                    total=total,
                )
                # update_progress commits; also refresh the doc heartbeat.
                doc.last_heartbeat_at = datetime.now(timezone.utc)
                await session.commit()

            try:
                await index_refined_document(session, doc, on_progress)
                await _persist_success(session, doc, job)
            except IndexingError as exc:
                await _persist_failure(session, document_id, job, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception("document_index crashed on %s", document_id)
                await _persist_failure(
                    session, document_id, job,
                    f"unexpected error: {exc}",
                )
    finally:
        await engine.dispose()
```

- [ ] **Step 10: Run the happy-path test**

```bash
pytest backend/tests/unit/test_index_job.py::test_run_index_happy_path_transitions_to_ready -v
```

Expected: PASS.

- [ ] **Step 11: Add the failure-path test**

Append:

```python
from app.services.ai.embedding import EmbeddingError


@pytest.mark.asyncio
async def test_run_index_embed_failure_transitions_to_failed(db_session):
    from app.services.documents.refinement import index_job
    from app.models.jobs import BackgroundJob, JobStatus

    doc = _make_doc(DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.commit()

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=EmbeddingError("Ollama unreachable"),
    ):
        await index_job.run_index(document_id=doc.id)

    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED.value
    assert "Indexing error" in (doc.error_message or "")

    # The BackgroundJob row should be marked FAILED with a real message
    result = await db_session.execute(
        select(BackgroundJob)
        .where(BackgroundJob.entity_id == doc.id)
        .where(BackgroundJob.job_type == "document_index")
    )
    job_row = result.scalar_one()
    assert job_row.status == JobStatus.FAILED.value
    assert "Embedding failed" in (job_row.error_message or "")
```

- [ ] **Step 12: Run it**

```bash
pytest backend/tests/unit/test_index_job.py::test_run_index_embed_failure_transitions_to_failed -v
```

Expected: PASS.

- [ ] **Step 13: Register the job in the import graph**

Verify `register_job("document_index")` actually fires at import time. Add a smoke test:

```python
def test_job_registered_under_canonical_name():
    # Side-effect import: importing the module registers the job.
    from app.services.documents.refinement import index_job  # noqa: F401
    from app.services.core.background_handler import JOB_REGISTRY

    assert "document_index" in JOB_REGISTRY
    assert JOB_REGISTRY["document_index"].__name__ == "run_index"
```

```bash
pytest backend/tests/unit/test_index_job.py::test_job_registered_under_canonical_name -v
```

Expected: PASS.

Make sure the module is imported on app startup. Find where `extract_job` is imported and add `index_job` next to it:

```bash
grep -rn "extract_job" backend/app/main.py backend/app/services/documents/__init__.py
```

If `extract_job` is imported in `backend/app/main.py` or a package `__init__`, add `from app.services.documents.refinement import index_job  # noqa: F401` next to it. If there's no such import path, add it explicitly to `backend/app/main.py` at the top of `lifespan` (before the recovery sweep runs).

- [ ] **Step 14: Commit**

```bash
git add backend/app/services/documents/refinement/index_job.py \
        backend/tests/unit/test_index_job.py \
        backend/app/main.py  # if you added an import line there
git commit -m "feat(documents): add document_index background job (TD-0085)

Mirrors the document_extract shape: own session, FOR UPDATE SKIP LOCKED
doc claim, own BackgroundJob row, per-batch progress via
BackgroundJobService.update_progress, READY on success, FAILED on
IndexingError / unexpected error.

Claim conditions: status=INDEXING, heartbeat_token=None — invalid
claims exit cleanly so two workers can never run the same job.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Update `refine_complete` to fire-and-return

**Files:**
- Modify: `backend/app/api/endpoints/library.py` (around lines 906–947)
- Test: `backend/tests/integration/test_refine_async_indexing.py` (create)
- Modify: `backend/tests/integration/test_library_docling.py` (existing refine-complete test)

The endpoint must now: flip status to `INDEXING`, commit, launch the job, and return immediately. The user's HTTP round-trip stops there; the indexer churns in the background and the frontend polls until `READY`.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_refine_async_indexing.py`:

```python
"""Integration test for the async refine→index flow (TD-0085 Phase 3)."""

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_refine_complete_returns_indexing_and_launches_job(
    client: AsyncClient,
    auth_headers: dict,
    indexed_pdf_doc,  # fixture: a Document in AWAITING_REFINEMENT
):
    """POST /refine/complete returns 200 with status=INDEXING and queues a job."""
    doc = indexed_pdf_doc
    launched: list[tuple[str, dict]] = []

    async def fake_launch(job, **kwargs):
        launched.append((job, kwargs))

    with patch(
        "app.api.endpoints.library.get_background_handler"
    ) as get_handler:
        get_handler.return_value.launch = AsyncMock(side_effect=fake_launch)
        resp = await client.post(
            f"/library/documents/{doc.id}/refine/complete",
            json={"reopen": False},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "INDEXING"
    assert launched == [("document_index", {"document_id": doc.id})]
```

You'll need a fixture `indexed_pdf_doc` (returns a Document in `AWAITING_REFINEMENT` with `stored_markdown` set). If it doesn't exist in `backend/tests/integration/conftest.py`, add it:

```python
# backend/tests/integration/conftest.py
import uuid
from datetime import datetime, timezone

import pytest

from app.models.library import (Document, DocumentStatus, RefinementStatus)


@pytest.fixture
async def indexed_pdf_doc(db_session, test_org, test_user) -> Document:
    """A document that has finished extraction and is awaiting refinement."""
    doc = Document(
        id=uuid.uuid4(),
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="Fixture SOP",
        original_filename="fixture.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        file_path="docs/fixture.pdf",
        status=DocumentStatus.AWAITING_REFINEMENT.value,
        refinement_status=RefinementStatus.PENDING.value,
        stored_markdown="# Title\n\nBody.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(doc)
    await db_session.flush()
    return doc
```

If `test_org` / `test_user` / `auth_headers` already exist (they do — see `.claude/rules/testing.md`), no extra fixture work is needed.

- [ ] **Step 2: Run it to verify failure**

```bash
pytest backend/tests/integration/test_refine_async_indexing.py -v
```

Expected: FAIL (the endpoint still indexes inline; `launched` will be empty).

- [ ] **Step 3: Modify the endpoint**

In `backend/app/api/endpoints/library.py`, replace the body of `refine_complete` (starting from the `try: await mark_complete(...)` at ~line 940) so the function reads:

```python
@router.post(
    "/documents/{document_id}/refine/complete",
    response_model=DocumentResponse,
)
async def refine_complete(
    document_id: uuid.UUID,
    payload: RefineCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.EDIT
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")

    if payload.reopen:
        try:
            await reopen(db, doc)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)

    try:
        await mark_complete(db, doc, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()

    # Indexing now runs as a background job so the user gets the live
    # shimmer card and the doc survives worker restarts via the
    # heartbeat / recovery machinery.
    handler = get_background_handler()
    await handler.launch("document_index", document_id=doc.id)

    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)
```

Remove the `from app.services.documents.refinement.indexing import index_refined_document` import at the top of the file — it's no longer called from the endpoint. (Leave the module itself in place; the job uses it.)

Add the new import near the existing service imports:

```python
from app.services.core.background_handler import get_background_handler
```

- [ ] **Step 4: Re-run the integration test**

```bash
pytest backend/tests/integration/test_refine_async_indexing.py -v
```

Expected: PASS.

- [ ] **Step 5: Update the existing refine-complete test**

In `backend/tests/integration/test_library_docling.py` find the test that asserts `status == "READY"` after `POST /refine/complete` and update it to expect `INDEXING` instead. Search:

```bash
grep -n "refine/complete\|READY" backend/tests/integration/test_library_docling.py
```

The intent of any test that previously asserted `READY` immediately is now wrong (the response returns before indexing finishes). Two options per test:

1. If the test is asserting "the endpoint works", change `"READY"` → `"INDEXING"` and patch `get_background_handler` so the job isn't actually scheduled.
2. If the test is asserting "indexing produces chunks", run the job inline by directly calling `await index_job.run_index(document_id=doc.id)` after the POST returns, then assert chunks exist.

Update accordingly. Run:

```bash
pytest backend/tests/integration/test_library_docling.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/library.py \
        backend/tests/integration/test_refine_async_indexing.py \
        backend/tests/integration/test_library_docling.py \
        backend/tests/integration/conftest.py  # if you added the fixture
git commit -m "feat(library): refine/complete fires document_index, returns INDEXING (TD-0085)

The handler no longer chunks + embeds inline. It commits the
INDEXING transition (via mark_complete), launches the background
job, and returns. The user immediately sees the shimmer card; the
job drives status to READY (or FAILED) async.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Extend startup recovery sweeps to cover indexing

**Files:**
- Modify: `backend/app/main.py` (`_recover_stalled_jobs` ~line 163, `_recover_stalled_documents` ~line 217)
- Test: extend `backend/tests/unit/test_index_job.py` with a sweep test, *or* `backend/tests/unit/test_main_recovery.py` if it exists.

Two surgical edits:

1. **Job-type allow-list** in `_recover_stalled_jobs` (around line 163): add `"document_index"` next to `"document_extract"`. The reset block needs different logic for indexing — instead of resetting to `UPLOADED`, we keep `INDEXING` and just release the claim (`processing_started_at = None`, `heartbeat_token = None`). The doc sweep will re-fire `document_index`.

2. **Doc sweep** in `_recover_stalled_documents` (around line 217): add a separate branch for stale `INDEXING` docs. For those, release the claim and re-fire `document_index`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_main_recovery.py` (or extend an existing one if you find it):

```python
"""Unit tests for the startup recovery sweep (TD-0085 Phase 3)."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.jobs import BackgroundJob, JobStatus
from app.models.library import (Document, DocumentStatus, RefinementStatus,
                                STALE_PROCESSING_SECONDS)


@pytest.mark.asyncio
async def test_recovery_refires_stalled_indexing_doc_with_document_index(
    db_session, test_org, test_user,
):
    """Stalled INDEXING doc → handler.launch('document_index', ...)."""
    from app.main import _recover_stalled_documents

    stale_when = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_PROCESSING_SECONDS + 60
    )
    doc = Document(
        id=uuid.uuid4(),
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="t",
        original_filename="t.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        file_path="p",
        status=DocumentStatus.INDEXING.value,
        refinement_status=RefinementStatus.COMPLETE.value,
        stored_markdown="# H\n\nbody",
        processing_started_at=stale_when,
        heartbeat_token="dead-worker-token",
        created_at=stale_when,
        updated_at=stale_when,
    )
    db_session.add(doc)
    await db_session.commit()

    launched: list[tuple[str, dict]] = []

    async def fake_launch(job, **kwargs):
        launched.append((job, kwargs))

    with patch(
        "app.main.get_background_handler"
    ) as get_handler:
        get_handler.return_value.launch = AsyncMock(side_effect=fake_launch)
        await _recover_stalled_documents()

    assert ("document_index", {"document_id": doc.id}) in launched

    await db_session.refresh(doc)
    # Status stays INDEXING (don't reset to UPLOADED — that'd send it
    # back through extraction). Just the claim got released.
    assert doc.status == DocumentStatus.INDEXING.value
    assert doc.heartbeat_token is None
    assert doc.processing_started_at is None
```

- [ ] **Step 2: Run it**

```bash
pytest backend/tests/unit/test_main_recovery.py -v
```

Expected: FAIL — the current sweep doesn't include `INDEXING` and only fires `document_extract`.

- [ ] **Step 3: Edit `_recover_stalled_documents` in `backend/app/main.py`**

Locate the `select(Document).where(...)` (around line 213) and change the predicate + downstream loops. Find this block:

```python
            result = await session.execute(
                select(Document)
                .where(
                    or_(
                        Document.status == DocumentStatus.UPLOADED.value,
                        (
                            Document.status.in_([
                                DocumentStatus.EXTRACTING.value,
                                DocumentStatus.PROCESSING.value,
                            ])
                            & (
                                (Document.processing_started_at == None)  # noqa: E711
                                | (Document.processing_started_at < stale_cutoff)
                            )
                        ),
                    )
                )
                .with_for_update(skip_locked=True)
            )
```

Replace with:

```python
            result = await session.execute(
                select(Document)
                .where(
                    or_(
                        Document.status == DocumentStatus.UPLOADED.value,
                        (
                            Document.status.in_([
                                DocumentStatus.EXTRACTING.value,
                                DocumentStatus.PROCESSING.value,
                            ])
                            & (
                                (Document.processing_started_at == None)  # noqa: E711
                                | (Document.processing_started_at < stale_cutoff)
                            )
                        ),
                        (
                            (Document.status == DocumentStatus.INDEXING.value)
                            & (
                                (Document.processing_started_at == None)  # noqa: E711
                                | (Document.processing_started_at < stale_cutoff)
                            )
                        ),
                    )
                )
                .with_for_update(skip_locked=True)
            )
```

Then replace the reset+fire loop (the for-doc-in-stalled_docs block) with branching:

```python
            # Reset + categorize for re-fire
            extracting_docs: list[Document] = []
            indexing_docs: list[Document] = []
            for doc in stalled_docs:
                if doc.status == DocumentStatus.INDEXING.value:
                    # Release the claim; keep status=INDEXING so the job
                    # picks up where the previous attempt left off.
                    doc.processing_started_at = None
                    doc.heartbeat_token = None
                    indexing_docs.append(doc)
                else:
                    # UPLOADED / EXTRACTING / PROCESSING all re-enter the
                    # extraction pipeline. Reset to UPLOADED for a fresh fire.
                    if doc.status in (
                        DocumentStatus.EXTRACTING.value,
                        DocumentStatus.PROCESSING.value,
                    ):
                        doc.status = DocumentStatus.UPLOADED.value
                        doc.processing_started_at = None
                        doc.heartbeat_token = None
                    extracting_docs.append(doc)
            await session.commit()

            handler = get_background_handler()
            for doc in extracting_docs:
                await handler.launch("document_extract", document_id=doc.id)
                logger.info("Re-fired extraction for document %s", doc.id)
            for doc in indexing_docs:
                await handler.launch("document_index", document_id=doc.id)
                logger.info("Re-fired indexing for document %s", doc.id)
```

- [ ] **Step 4: Run the test**

```bash
pytest backend/tests/unit/test_main_recovery.py -v
```

Expected: PASS.

- [ ] **Step 5: Extend the job-type allow-list in `_recover_stalled_jobs`**

In the same file, find (around line 163):

```python
                if job.job_type in (
                    "document_extract",
                    "document_process",
                    "document_enrich",
                ):
```

Change to:

```python
                if job.job_type in (
                    "document_extract",
                    "document_index",
                    "document_process",
                    "document_enrich",
                ):
```

The reset block already correctly leaves docs in non-resettable states (`AWAITING_REFINEMENT`, `INDEXING`, `READY`, `FAILED`) alone. With `document_index` in the allow-list, a stalled `document_index` job's row gets marked FAILED and the sister `_recover_stalled_documents` sweep handles the doc.

- [ ] **Step 6: Add a unit test for the job-row sweep**

Append to `backend/tests/unit/test_main_recovery.py`:

```python
@pytest.mark.asyncio
async def test_recovery_marks_stalled_index_job_failed_after_max_attempts(
    db_session, test_org, test_user,
):
    """A document with 3 stale FAILED document_index jobs should
    transition to status=FAILED (terminal)."""
    from app.main import _recover_stalled_jobs, MAX_RECOVERY_ATTEMPTS

    doc = Document(
        id=uuid.uuid4(),
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
        title="t",
        original_filename="t.pdf",
        mime_type="application/pdf",
        file_size_bytes=1,
        file_path="p",
        status=DocumentStatus.INDEXING.value,
        refinement_status=RefinementStatus.COMPLETE.value,
        stored_markdown="# H",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(doc)

    # Pre-seed (MAX_RECOVERY_ATTEMPTS - 1) prior FAILED job rows.
    for _ in range(MAX_RECOVERY_ATTEMPTS - 1):
        db_session.add(BackgroundJob(
            id=uuid.uuid4(),
            job_type="document_index",
            status=JobStatus.FAILED.value,
            entity_type="document",
            entity_id=doc.id,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            heartbeat_at=datetime.now(timezone.utc),
        ))

    # One RUNNING job with stale heartbeat — this is the one the sweep finds.
    db_session.add(BackgroundJob(
        id=uuid.uuid4(),
        job_type="document_index",
        status=JobStatus.RUNNING.value,
        entity_type="document",
        entity_id=doc.id,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    ))
    await db_session.commit()

    await _recover_stalled_jobs()

    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.FAILED.value
    assert "recovery attempts" in (doc.error_message or "")
```

- [ ] **Step 7: Run it**

```bash
pytest backend/tests/unit/test_main_recovery.py::test_recovery_marks_stalled_index_job_failed_after_max_attempts -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_main_recovery.py
git commit -m "feat(recovery): sweep INDEXING + document_index (TD-0085)

- _recover_stalled_documents now matches stale INDEXING docs and
  re-fires document_index (not document_extract).
- _recover_stalled_jobs allow-list includes document_index, so a
  killed indexing attempt is marked FAILED and the document sweep
  re-fires a fresh one — with the existing 3-attempt cap before
  terminal FAILED.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Periodic recovery loop for autoscaled steady-state

**Files:**
- Modify: `backend/app/main.py` (add `_recovery_loop`, start in `lifespan`)
- Modify: `backend/app/core/config.py` (add `recovery_interval_seconds: int = 90`)
- Test: `backend/tests/unit/test_recovery_loop.py` (create)

The existing recovery sweeps run only at process startup. In a stable autoscaled deployment where no new pod boots for hours, a doc that gets stranded by a scale-down event will sit forever. Fix: run the sweeps on a timer.

- [ ] **Step 1: Add the config knob**

Edit `backend/app/core/config.py` and add to `Settings`:

```python
    # Phase 3: how often the recovery loop sweeps for stalled jobs/docs.
    # The startup sweep still runs once on lifespan boot; this loop adds
    # in-process polling for autoscaled deployments where new pods don't
    # boot frequently. Set to 0 to disable the loop entirely.
    recovery_interval_seconds: int = 90
```

The `BATCHRITE_` env prefix means env var is `BATCHRITE_RECOVERY_INTERVAL_SECONDS`.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_recovery_loop.py`:

```python
"""Unit tests for the periodic recovery loop (TD-0085 Phase 3)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_recovery_loop_runs_both_sweeps_each_tick():
    """One iteration calls both sweep functions in order."""
    from app.main import _recovery_loop

    jobs = AsyncMock()
    docs = AsyncMock()
    with patch("app.main._recover_stalled_jobs", jobs), \
         patch("app.main._recover_stalled_documents", docs), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0.01

        task = asyncio.create_task(_recovery_loop())
        await asyncio.sleep(0.05)  # let it tick a few times
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert jobs.await_count >= 1
    assert docs.await_count >= 1


@pytest.mark.asyncio
async def test_recovery_loop_swallows_sweep_exceptions():
    """A sweep raising should not kill the loop."""
    from app.main import _recovery_loop

    calls = []

    async def boom():
        calls.append("boom")
        raise RuntimeError("simulated DB blip")

    async def ok():
        calls.append("ok")

    with patch("app.main._recover_stalled_jobs", boom), \
         patch("app.main._recover_stalled_documents", ok), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0.01

        task = asyncio.create_task(_recovery_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Each iteration: boom (raises), then ok still runs.
    assert calls.count("boom") >= 2
    assert calls.count("ok") >= 2


@pytest.mark.asyncio
async def test_recovery_loop_disabled_when_interval_is_zero():
    from app.main import _recovery_loop

    jobs = AsyncMock()
    docs = AsyncMock()
    with patch("app.main._recover_stalled_jobs", jobs), \
         patch("app.main._recover_stalled_documents", docs), \
         patch("app.main.settings") as fake_settings:
        fake_settings.recovery_interval_seconds = 0

        # Should return immediately.
        await asyncio.wait_for(_recovery_loop(), timeout=0.2)

    assert jobs.await_count == 0
    assert docs.await_count == 0
```

- [ ] **Step 3: Run all three to verify failure**

```bash
pytest backend/tests/unit/test_recovery_loop.py -v
```

Expected: FAIL — `_recovery_loop` doesn't exist.

- [ ] **Step 4: Add `_recovery_loop` to `backend/app/main.py`**

Find the existing `_heartbeat_loop` definition and add this function alongside it:

```python
async def _recovery_loop() -> None:
    """Periodically re-run the stalled-jobs and stalled-docs sweeps.

    The startup sweep covers cold boots; this loop covers steady-state
    autoscaled deployments where new pods don't boot for hours. Each
    sweep is independent — exceptions inside one don't kill the other,
    and don't kill the loop.

    Set BATCHRITE_RECOVERY_INTERVAL_SECONDS=0 to disable.
    """
    interval = settings.recovery_interval_seconds
    if not interval or interval <= 0:
        logger.info("Recovery loop disabled (interval <= 0)")
        return

    while True:
        try:
            await _recover_stalled_jobs()
        except Exception:
            logger.exception("Recovery loop: job sweep failed")
        try:
            await _recover_stalled_documents()
        except Exception:
            logger.exception("Recovery loop: doc sweep failed")
        await asyncio.sleep(interval)
```

In the `lifespan` function, after the heartbeat task is started, also start the recovery loop and tear it down on shutdown. Find this block (around line 311 — look for `_heartbeat_task = asyncio.create_task`):

```python
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
```

Add right after it:

```python
    _recovery_task = asyncio.create_task(_recovery_loop())
```

In the same lifespan, find the `finally:` block where `_heartbeat_task.cancel()` lives and add:

```python
        _recovery_task.cancel()
        try:
            await _recovery_task
        except asyncio.CancelledError:
            pass
```

(Mirror exactly what the existing heartbeat-task teardown does.)

- [ ] **Step 5: Run the tests**

```bash
pytest backend/tests/unit/test_recovery_loop.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py \
        backend/app/core/config.py \
        backend/tests/unit/test_recovery_loop.py
git commit -m "feat(recovery): periodic sweep loop for autoscale (TD-0085)

The startup sweep covers cold boots but leaves a gap in steady-state
autoscaled deployments where new pods don't boot for hours. The new
_recovery_loop ticks every BATCHRITE_RECOVERY_INTERVAL_SECONDS (default
90s) and re-runs both sweeps. Each sweep is independent; exceptions
don't kill the loop. Set the env var to 0 to disable.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Frontend stage-label tweak

**Files:**
- Modify: `frontend/src/routes/library/[id]/+page.svelte`

The shimmer card already fires for `status === 'INDEXING'`. The only polish needed is the stage-label fallback when `processing_progress` is null (the brief window between `mark_complete` committing and the first `update_progress` call). Right now `liveStageText` returns `'stage: indexing'` for `INDEXING` — fine, but let's make it nicer: `'stage: chunking'` until the first progress lands, then defer to `processing_progress.stage_label` ("Embedding chunks").

- [ ] **Step 1: Locate and edit `liveStageText`**

In `frontend/src/routes/library/[id]/+page.svelte`, find the `INDEXING` branch inside `liveStageText` (around line 213):

```typescript
            case 'INDEXING':
            case 'PROCESSING':
                return 'stage: indexing';
```

Replace with:

```typescript
            case 'INDEXING':
                // Pre-progress fallback. Once the document_index job
                // calls update_progress, processing_progress takes
                // precedence (handled by the earlier branch).
                return 'stage: chunking';
            case 'PROCESSING':
                return 'stage: indexing';
```

- [ ] **Step 2: Adjust `liveTitle` to read naturally**

In the same file, around line 232 find:

```typescript
            case 'INDEXING':
            case 'PROCESSING':
                return 'Indexing for search';
```

It already reads well — no change needed. Skip.

- [ ] **Step 3: Run frontend type-check**

```bash
cd frontend && npm run check 2>&1 | grep "routes/library" || echo "No new errors in library route"
```

Expected: "No new errors in library route" (or empty if grep finds nothing).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/library/\[id\]/+page.svelte
git commit -m "polish(library): better stage label for INDEXING pre-progress window (TD-0085)

The brief window between mark_complete committing INDEXING and the
job's first update_progress now reads 'stage: chunking' instead of
the generic 'stage: indexing' — once the job ticks, the real stage
label ('Embedding chunks') takes over via processing_progress.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Manual smoke test on dev stack

This is not automated. Catches integration issues that unit/integration tests can't, namely the actual Ollama path and the live UI.

- [ ] **Step 1: Confirm dev stack is up**

```bash
# Backend should be on the worktree port (see CLAUDE.md): 8000 main / 8010 wt1 / 8020 wt2
lsof -i :8000 -i :8010 -i :8020 | head
# Frontend
lsof -i :5173 -i :5183 -i :5193 | head
# Ollama with the embedding model
curl -s http://localhost:11434/api/tags | jq '.models[].name' | grep nomic
```

Expected: backend + frontend on a known port pair, and at least one `nomic-embed-text:*` model present.

- [ ] **Step 2: Upload a non-trivial PDF**

Use the Library UI to upload a PDF with ~50+ pages (a textbook, a long SOP). Confirm:
- Status walks through Uploading → Extracting (shimmer) → Awaiting Refinement.

- [ ] **Step 3: Refine and click "Mark complete"**

In the refinement editor, make a trivial edit and click "Mark complete". Confirm:
- The library detail page **immediately** flips to the shimmer card with "Indexing for search".
- Stage label initially reads "stage: chunking", then transitions to "stage: Embedding chunks · 50 / 280" (or similar) as batches complete.
- Percentage ticks up as batches complete.
- After a minute or two (depending on doc size), the card disappears and the refined reader appears.

- [ ] **Step 4: Verify chunks + embeddings landed**

```bash
# Replace <doc-id> with the document id from the URL
psql -U postgres -d batchrite -c "
  SELECT count(*) AS total, count(embedding) AS with_embeddings
  FROM document_chunks
  WHERE document_id = '<doc-id>';
"
```

Expected: `total == with_embeddings` (both non-zero). If `with_embeddings < total`, the embed path failed silently for some batches — investigate before declaring success.

- [ ] **Step 5: Test the lens toggle**

On the document detail page, flip between "Refined" and "Source PDF". Both should render. The refined reader should show chunks; the source PDF view should iframe the original.

- [ ] **Step 6: Simulate a worker restart mid-index** *(optional but recommended)*

In a second large doc, while the shimmer is still ticking, kill the backend (`Ctrl-C` the uvicorn process) and immediately restart it. Watch the logs for:

```
Found N stalled document(s) to recover: [...]
Re-fired indexing for document <uuid>
```

The shimmer should pick up where it left off (status may briefly go through the heartbeat reset). The final outcome should still be a `READY` doc with all chunks indexed.

- [ ] **Step 7: Update the smoke-test memory**

If anything in this manual flow turned out differently from the plan's expectations, note it in `.claude/agent-memory/qa-verify/project_td0085_async_indexing.md` so the next QA pass knows.

---

## Self-Review Notes

**Coverage check (against the design conversation upstream of this plan):**

- ✅ Indexing runs as a background job (Task 2).
- ✅ Refined markdown flows from `refine_complete` → `mark_complete` → job (Task 3).
- ✅ Shimmer renders during indexing (Task 6 + existing frontend wiring).
- ✅ Embeddings still go to local Ollama (Task 1 — `embed_texts` unchanged provider chain).
- ✅ Restart-robust: startup sweep extended (Task 4) + periodic loop (Task 5).
- ✅ Horizontal-autoscale safe: `FOR UPDATE SKIP LOCKED` at job claim (Task 2) and both sweeps (existing).
- ✅ Silent embed failures fail loud (Task 1).
- ✅ `MAX_RECOVERY_ATTEMPTS=3` cap preserved for `document_index` (Task 4 test).

**Placeholder scan:** none. Every code block is concrete; every test references a real fixture or model field.

**Type / name consistency:** `IndexingError`, `run_index`, `"document_index"`, `_load_and_claim_document`, `_persist_success`, `_persist_failure`, `_recovery_loop`, `recovery_interval_seconds`, `on_progress` — all consistent across tasks.

**Out of scope (intentionally not in this plan, flagged for separate tickets if anyone wants them):**

- Resume-from-checkpoint indexing (only re-embed chunks whose `embedding IS NULL`). Current plan re-runs from scratch on recovery via the idempotent `DELETE FROM document_chunks`. Adds ~complexity for marginal benefit until users actually feel the redo pain.
- Distributed queue (Celery / Modal). Not needed while `LocalBackgroundHandler` + the periodic recovery loop close the autoscale gap. `CloudGpuBackgroundHandler` is reserved for this.
- Per-chunk page-number propagation. The current `chunk_markdown(..., None)` loses page boundaries; the lens toggle (already shipped) compensates with the Source PDF view but the refined-reader TOC can't deep-link to pages. Independent fix that involves docling-side instrumentation.
