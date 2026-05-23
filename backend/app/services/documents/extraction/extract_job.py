"""Background coroutine that runs the ext/ docling extractor against one document.

The actual docling/torch/easyocr work runs in a subprocess against the
standalone ``ext/docling-extractor/`` project's venv. This module owns
the DB session lifecycle, BackgroundJob row, status transitions, and
artifact ingestion — it never imports docling itself.

Registers under the name "document_extract" via @register_job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.jobs import BackgroundJob
from app.models.library import (
    Document,
    DocumentSourceFormat,
    DocumentStatus,
    RefinementStatus,
)
from app.services.core.background_handler import register_job
from app.services.core.background_jobs import BackgroundJobService
from app.services.core.file_storage import FileStorageService
from app.services.documents.extraction.heartbeat_watchdog import HeartbeatWatchdog

logger = logging.getLogger(__name__)


# Hard cap on stderr persisted to Document.error_message. The column is
# unbounded String, but a runaway docling crash can dump megabytes of
# traceback and we don't want to bloat the documents table or hit row
# limits. 64 KB is plenty to diagnose any real failure.
_MAX_STDERR_BYTES = 64 * 1024

_MIME_TO_FORMAT = {
    "application/pdf": DocumentSourceFormat.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentSourceFormat.DOCX,
    "image/jpeg": DocumentSourceFormat.IMAGE,
    "image/png": DocumentSourceFormat.IMAGE,
    "image/tiff": DocumentSourceFormat.IMAGE,
    "image/webp": DocumentSourceFormat.IMAGE,
}


def _resolve_paths(doc: Document) -> tuple[Path, Path]:
    """Return (input_file_path, output_dir) for a document.

    The output_dir is per-document, under the storage root, so the
    refined.md / images/ / result.json artifacts land in a predictable
    place that the read endpoints (and the user-facing image URL) can
    point at.
    """
    storage = FileStorageService()
    input_path = storage.resolve_path(doc.file_path)
    output_dir = storage.storage_root / "documents" / str(doc.id)
    return input_path, output_dir


async def _load_and_claim_document(
    session: AsyncSession, document_id: UUID
) -> tuple[Document | None, BackgroundJob | None]:
    """Lock the document row + create the BackgroundJob in one transaction.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so a second worker that picks
    up the same document concurrently sees no row and exits cleanly.
    """
    result = await session.execute(
        select(Document)
        .where(Document.id == document_id)
        .with_for_update(skip_locked=True)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        return None, None

    if doc.mime_type not in _MIME_TO_FORMAT:
        raise ValueError(f"Unsupported MIME type for extraction: {doc.mime_type!r}")

    job = await BackgroundJobService.create(
        session,
        "document_extract",
        "document",
        document_id,
        input_data={"mime_type": doc.mime_type},
    )
    doc.status = DocumentStatus.EXTRACTING.value
    doc.processing_started_at = datetime.now(timezone.utc)
    doc.source_format = _MIME_TO_FORMAT[doc.mime_type].value
    doc.ocr_engine = "easyocr"
    doc.heartbeat_token = secrets.token_urlsafe(32)
    doc.last_heartbeat_at = None
    await session.commit()
    return doc, job


async def _persist_success(
    session: AsyncSession,
    doc: Document,
    job: BackgroundJob,
    output_dir: Path,
) -> None:
    """Read artifacts from output_dir and write them to the Document row.

    Transitions status to AWAITING_REFINEMENT. Sets refinement_status to
    PENDING when docling flagged content concerns, NOT_REQUIRED otherwise.

    Late-discard: if the watchdog already marked the document FAILED while
    the subprocess was finishing up, we drop the artifacts and return so we
    don't overwrite the FAILED state.
    """
    # Re-read terminal state inside our session — the watchdog may have
    # already marked us FAILED while the subprocess was finishing up.
    await session.refresh(doc)
    if doc.status == DocumentStatus.FAILED.value:
        # Watchdog won the race. Drop the artifacts and bail.
        shutil.rmtree(output_dir, ignore_errors=True)
        return

    result_payload: dict[str, Any] = json.loads(
        (output_dir / "result.json").read_text()
    )
    refined = (output_dir / "refined.md").read_text()
    storage = FileStorageService()

    doc.stored_markdown = refined
    doc.images_dir = str((output_dir / "images").relative_to(storage.storage_root))
    doc.page_count = result_payload.get("page_count")
    doc.refinement_flags = result_payload.get("flags", [])
    flags = doc.refinement_flags
    doc.refinement_status = (
        RefinementStatus.PENDING.value if flags else RefinementStatus.NOT_REQUIRED.value
    )
    doc.status = DocumentStatus.AWAITING_REFINEMENT.value
    doc.processing_started_at = None
    doc.heartbeat_token = None

    await BackgroundJobService.complete(
        session,
        job,
        output_data={
            "page_count": doc.page_count,
            "flag_count": len(flags),
            "image_count": result_payload.get("image_count", 0),
        },
    )
    await session.commit()


async def _persist_failure(
    session: AsyncSession,
    document_id: UUID,
    job: BackgroundJob | None,
    message: str,
) -> None:
    """Rollback any dirty state, re-query the document, mark it FAILED.

    The rollback-then-re-query pattern is required because _persist_success
    may have made partial writes before raising; we need a clean session
    to write the FAILED status atomically.
    """
    await session.rollback()
    result = await session.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is not None:
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = f"Extraction error: {message[:_MAX_STDERR_BYTES]}"
        doc.processing_started_at = None
        doc.heartbeat_token = None
    if job is not None:
        job_result = await session.execute(
            select(BackgroundJob).where(BackgroundJob.id == job.id)
        )
        job = job_result.scalar_one_or_none()
        if job is not None:
            # BackgroundJobService.fail() applies its own [:500] cap; the Document
            # row keeps the full stderr (up to _MAX_STDERR_BYTES) for diagnostics.
            await BackgroundJobService.fail(session, job, message)
    await session.commit()


@register_job("document_extract")
async def run_extraction(
    document_id: UUID,
    heartbeat_base_url: str | None = None,
) -> None:
    """Run the docling extraction subprocess for ``document_id``.

    ``heartbeat_base_url`` overrides ``settings.extraction_heartbeat_base_url``
    when provided. The upload endpoints pass the live ``Request.base_url`` so
    the subprocess always posts back to the port the backend actually bound,
    independent of how the operator configured the settings default. The
    settings value remains the fallback for restart-recovery paths where no
    request context is available.
    """
    import app.db.base  # noqa: F401

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        job: BackgroundJob | None = None
        try:
            doc, job = await _load_and_claim_document(session, document_id)
            if doc is None:
                logger.info("Document %s not found or locked", document_id)
                return

            input_path, output_dir = _resolve_paths(doc)
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            base_url = (
                heartbeat_base_url or settings.extraction_heartbeat_base_url
            ).rstrip("/")
            heartbeat_url = f"{base_url}/internal/extraction/{document_id}/heartbeat"

            proc = await asyncio.create_subprocess_exec(
                settings.docling_script_python,
                settings.docling_script_path,
                "--input",
                str(input_path),
                "--output-dir",
                str(output_dir),
                "--num-threads",
                str(settings.docling_num_threads),
                "--heartbeat-url",
                heartbeat_url,
                "--heartbeat-token",
                doc.heartbeat_token,
                "--heartbeat-interval-seconds",
                str(settings.extraction_heartbeat_interval_seconds),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            watchdog = HeartbeatWatchdog(
                document_id=document_id,
                proc=proc,
                interval_seconds=settings.extraction_heartbeat_interval_seconds,
                max_misses=settings.extraction_heartbeat_max_misses,
                session_factory=session_factory,
            )
            watchdog_task = asyncio.create_task(watchdog.run_until_dead_or_done())

            try:
                stdout, stderr = await proc.communicate()
            finally:
                watchdog.stop()
                await watchdog_task

            if watchdog.timed_out:
                await _persist_failure(
                    session,
                    document_id,
                    job,
                    "Extraction process became unresponsive "
                    f"(no heartbeat for "
                    f"{settings.extraction_heartbeat_interval_seconds * settings.extraction_heartbeat_max_misses}s)",
                )
                return

            if proc.returncode != 0:
                msg = stderr.decode(errors="replace") or stdout.decode(errors="replace")
                logger.error(
                    "docling subprocess failed (rc=%s) for %s: %s",
                    proc.returncode,
                    document_id,
                    msg[:500],
                )
                await _persist_failure(session, document_id, job, msg)
                return

            await _persist_success(session, doc, job, output_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Extraction failed for document %s", document_id)
            await _persist_failure(session, document_id, job, str(exc))
        finally:
            await engine.dispose()
