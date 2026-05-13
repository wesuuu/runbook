"""Document refinement state transitions.

These are the only writes allowed against refinement_status /
refined_by_id / refined_at. Endpoints call these; they raise
ValueError on disallowed transitions and the endpoint layer converts
to HTTP 409.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import (Document, DocumentStatus, RefinementStatus)


async def mark_in_progress(db: AsyncSession, doc: Document) -> None:
    if doc.refinement_status in (
        RefinementStatus.NOT_REQUIRED.value,
        RefinementStatus.PENDING.value,
    ):
        doc.refinement_status = RefinementStatus.IN_PROGRESS.value
    # else: IN_PROGRESS stays, COMPLETE stays (caller should re-open
    # explicitly)


async def save_markdown(
    db: AsyncSession,
    doc: Document,
    markdown: str,
    user_id: UUID,
) -> None:
    doc.stored_markdown = markdown
    await mark_in_progress(db, doc)


async def mark_complete(
    db: AsyncSession, doc: Document, user_id: UUID
) -> None:
    if doc.refinement_status == RefinementStatus.COMPLETE.value:
        raise ValueError("Document refinement already complete")
    doc.refinement_status = RefinementStatus.COMPLETE.value
    doc.status = DocumentStatus.INDEXING.value
    doc.refined_by_id = user_id
    doc.refined_at = datetime.now(timezone.utc)


async def reopen(db: AsyncSession, doc: Document) -> None:
    if doc.refinement_status != RefinementStatus.COMPLETE.value:
        raise ValueError("Only completed refinements can be re-opened")
    doc.refinement_status = RefinementStatus.IN_PROGRESS.value
    doc.status = DocumentStatus.AWAITING_REFINEMENT.value
    doc.refined_by_id = None
    doc.refined_at = None
