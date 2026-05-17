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


async def _persist_success(
    session: AsyncSession, doc: Document, job: BackgroundJob,
) -> None:
    """Mark doc READY, complete the BackgroundJob, clear heartbeat_token.

    Flushes the indexer's in-memory writes first, then re-reads ``status``
    only (full-instance refresh would overwrite the READY write from
    ``index_refined_document``). If the watchdog won the race and marked
    us FAILED, drop our claim and exit without overwriting.
    """
    await session.flush()
    fresh_status = await session.scalar(
        select(Document.status).where(Document.id == doc.id)
    )
    if fresh_status == DocumentStatus.FAILED.value:
        # Watchdog or admin won the race; drop our claim and exit.
        return
    doc.status = DocumentStatus.READY.value
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
    claimed / row missing) — see ``_load_and_claim_document`` for the
    full predicate.
    """
    import app.db.base  # noqa: F401

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
                # update_progress commits; refresh the doc heartbeat too.
                doc.last_heartbeat_at = datetime.now(timezone.utc)
                await session.commit()

            try:
                await index_refined_document(session, doc, on_progress)
                await _persist_success(session, doc, job)
            except IndexingError as exc:
                await _persist_failure(session, document_id, job, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "document_index crashed on %s", document_id
                )
                await _persist_failure(
                    session, document_id, job,
                    f"unexpected error: {exc}",
                )
    finally:
        await engine.dispose()
