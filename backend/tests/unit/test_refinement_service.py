from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.library import DocumentStatus, RefinementStatus
from app.services.documents.refinement.refinement_service import (
    mark_complete, mark_in_progress, reopen, save_markdown)


def _doc(refinement_status=RefinementStatus.PENDING.value):
    d = MagicMock()
    d.id = uuid4()
    d.refinement_status = refinement_status
    d.status = DocumentStatus.AWAITING_REFINEMENT.value
    d.stored_markdown = "old"
    d.refined_by_id = None
    d.refined_at = None
    return d


@pytest.mark.asyncio
async def test_save_markdown_writes_and_marks_in_progress():
    db = AsyncMock()
    doc = _doc()
    await save_markdown(db, doc, "new markdown", user_id=uuid4())
    assert doc.stored_markdown == "new markdown"
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_save_markdown_skips_state_change_when_already_in_progress():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.IN_PROGRESS.value)
    await save_markdown(db, doc, "another edit", user_id=uuid4())
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_mark_in_progress_idempotent():
    db = AsyncMock()
    doc = _doc()
    await mark_in_progress(db, doc)
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value
    # second call: still IN_PROGRESS
    await mark_in_progress(db, doc)
    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_mark_complete_sets_indexing_and_stamps_user():
    db = AsyncMock()
    doc = _doc()
    uid = uuid4()
    await mark_complete(db, doc, user_id=uid)
    assert doc.refinement_status == RefinementStatus.COMPLETE.value
    assert doc.status == DocumentStatus.INDEXING.value
    assert doc.refined_by_id == uid
    assert isinstance(doc.refined_at, datetime)


@pytest.mark.asyncio
async def test_mark_complete_rejects_already_complete():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.COMPLETE.value)
    with pytest.raises(ValueError, match="already complete"):
        await mark_complete(db, doc, user_id=uuid4())


@pytest.mark.asyncio
async def test_reopen_resets_complete_doc_to_awaiting_refinement():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.COMPLETE.value)
    doc.status = DocumentStatus.READY.value
    doc.refined_by_id = uuid4()
    doc.refined_at = datetime.now(timezone.utc)

    await reopen(db, doc)

    assert doc.refinement_status == RefinementStatus.IN_PROGRESS.value
    assert doc.status == DocumentStatus.AWAITING_REFINEMENT.value
    assert doc.refined_by_id is None
    assert doc.refined_at is None


@pytest.mark.asyncio
async def test_reopen_rejects_non_complete_doc():
    db = AsyncMock()
    doc = _doc(refinement_status=RefinementStatus.IN_PROGRESS.value)
    with pytest.raises(ValueError, match="Only completed refinements"):
        await reopen(db, doc)
