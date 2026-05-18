"""Unit tests for the startup recovery sweeps (TD-0085 Phase 3)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.jobs import BackgroundJob, JobStatus
from app.models.library import (
    STALE_PROCESSING_SECONDS,
    Document,
    DocumentStatus,
    RefinementStatus,
)


def _stale_indexing_doc(test_org, test_user) -> Document:
    stale_when = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_PROCESSING_SECONDS + 60
    )
    return Document(
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


@pytest.mark.asyncio
async def test_recovery_refires_stalled_indexing_doc_with_document_index(
    db_session,
    test_org,
    test_user,
):
    """Stalled INDEXING doc → handler.launch('document_index', ...).

    The doc.status stays INDEXING (don't reset to UPLOADED — that'd
    send it back through extraction). Just the claim gets released.
    """
    from app import main as main_module

    doc = _stale_indexing_doc(test_org, test_user)
    db_session.add(doc)
    await db_session.commit()  # _recover_stalled_documents opens its own session

    launched: list[tuple[str, dict]] = []

    async def fake_launch(job, **kwargs):
        launched.append((job, kwargs))

    fake_handler = MagicMock()
    fake_handler.launch = AsyncMock(side_effect=fake_launch)

    # Patch the session factory inside _recover_stalled_documents so it
    # uses db_session (sees the fixture data). Also stub the handler.
    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(
        main_module,
        "get_background_handler",
        return_value=fake_handler,
    ), patch.object(
        main_module,
        "create_async_engine",
        MagicMock(return_value=AsyncMock()),
    ), patch.object(
        main_module,
        "async_sessionmaker",
        MagicMock(return_value=fake_factory),
    ):
        await main_module._recover_stalled_documents()

    assert ("document_index", {"document_id": doc.id}) in launched

    from sqlalchemy import select

    fresh = await db_session.scalar(select(Document).where(Document.id == doc.id))
    assert fresh.status == DocumentStatus.INDEXING.value
    assert fresh.heartbeat_token is None
    assert fresh.processing_started_at is None


@pytest.mark.asyncio
async def test_recovery_marks_stalled_index_job_failed_after_max_attempts(
    db_session,
    test_org,
    test_user,
):
    """A document with 3 stale FAILED document_index jobs should
    transition to status=FAILED (terminal)."""
    from app import main as main_module
    from app.main import MAX_RECOVERY_ATTEMPTS
    from app.models.library import RefinementStatus

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
        db_session.add(
            BackgroundJob(
                id=uuid.uuid4(),
                job_type="document_index",
                status=JobStatus.FAILED.value,
                entity_type="document",
                entity_id=doc.id,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                heartbeat_at=datetime.now(timezone.utc),
            )
        )

    # One RUNNING job with stale heartbeat — this is the one the sweep finds.
    db_session.add(
        BackgroundJob(
            id=uuid.uuid4(),
            job_type="document_index",
            status=JobStatus.RUNNING.value,
            entity_type="document",
            entity_id=doc.id,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    # _recover_stalled_jobs opens its own engine; patch the session
    # factory so it shares db_session (sees the SAVEPOINT-bound fixtures).
    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(
        main_module,
        "create_async_engine",
        MagicMock(return_value=AsyncMock()),
    ), patch.object(
        main_module,
        "async_sessionmaker",
        MagicMock(return_value=fake_factory),
    ):
        await main_module._recover_stalled_jobs()

    from sqlalchemy import select

    fresh = await db_session.scalar(select(Document).where(Document.id == doc.id))
    assert fresh.status == DocumentStatus.FAILED.value
    assert "recovery attempts" in (fresh.error_message or "")
