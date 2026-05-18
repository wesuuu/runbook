"""Unit tests for the document_index background job (TD-0085 Phase 3)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.library import Document, DocumentStatus, RefinementStatus


def _make_doc(
    test_org,
    test_user,
    status: DocumentStatus,
    *,
    heartbeat_token: str | None = None,
    stored_markdown: str | None = "# Title\n\nBody.",
) -> Document:
    return Document(
        id=uuid.uuid4(),
        org_id=test_org.id,
        uploaded_by_id=test_user.id,
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
async def test_claim_rejects_doc_in_wrong_status(db_session, test_org, test_user):
    from app.services.documents.refinement.index_job import _load_and_claim_document

    doc = _make_doc(test_org, test_user, DocumentStatus.UPLOADED)
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, claimed_job = await _load_and_claim_document(db_session, doc.id)
    assert claimed_doc is None
    assert claimed_job is None


@pytest.mark.asyncio
async def test_claim_rejects_doc_with_existing_heartbeat_token(
    db_session, test_org, test_user
):
    from app.services.documents.refinement.index_job import _load_and_claim_document

    doc = _make_doc(
        test_org,
        test_user,
        DocumentStatus.INDEXING,
        heartbeat_token="someone-else",
    )
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, _ = await _load_and_claim_document(db_session, doc.id)
    assert claimed_doc is None


@pytest.mark.asyncio
async def test_claim_accepts_indexing_doc_with_no_token(
    db_session, test_org, test_user
):
    from app.services.documents.refinement.index_job import _load_and_claim_document

    doc = _make_doc(test_org, test_user, DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()

    claimed_doc, claimed_job = await _load_and_claim_document(db_session, doc.id)
    assert claimed_doc is not None
    assert claimed_doc.id == doc.id
    assert claimed_doc.heartbeat_token is not None
    assert claimed_doc.processing_started_at is not None
    assert claimed_job is not None
    assert claimed_job.job_type == "document_index"


@pytest.mark.asyncio
async def test_run_index_happy_path_transitions_to_ready(
    db_session, test_org, test_user
):
    """run_index drives the doc to READY when indexing succeeds.

    Uses the extract_job pattern: patch the session-lifecycle helpers so
    the job runs against the test's SAVEPOINT-isolated db_session
    instead of opening its own connection (which couldn't see the
    uncommitted fixture data).
    """
    from unittest.mock import AsyncMock, patch

    from app.models.jobs import BackgroundJob
    from app.services.core.background_jobs import BackgroundJobService
    from app.services.documents.refinement import index_job

    doc = _make_doc(
        test_org,
        test_user,
        DocumentStatus.INDEXING,
        stored_markdown="# H\n\n" + ("word " * 1500),
    )
    db_session.add(doc)
    await db_session.flush()
    job = await BackgroundJobService.create(
        db_session,
        "document_index",
        "document",
        doc.id,
    )
    await db_session.flush()

    async def fake_embed_texts(texts, db, on_progress=None, org_id=None):
        if on_progress:
            await on_progress(len(texts), len(texts))
        return [[0.0] * 768 for _ in texts]

    # Patch session lifecycle so the job uses db_session instead of
    # opening its own engine.
    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=fake_embed_texts,
    ), patch.object(
        index_job,
        "_load_and_claim_document",
        AsyncMock(return_value=(doc, job)),
    ), patch.object(
        index_job,
        "create_async_engine",
        MagicMock(return_value=AsyncMock()),
    ), patch.object(
        index_job,
        "async_sessionmaker",
        MagicMock(return_value=fake_factory),
    ):
        await index_job.run_index(document_id=doc.id)

    await db_session.refresh(doc)
    assert doc.status == DocumentStatus.READY.value
    assert doc.heartbeat_token is None
    assert doc.processing_started_at is None


@pytest.mark.asyncio
async def test_run_index_routes_embed_failure_to_persist_failure(
    db_session, test_org, test_user
):
    """An EmbeddingError inside the indexer triggers _persist_failure
    with the IndexingError message. The actual DB-state transition is
    covered by direct tests on _persist_failure below — this asserts
    the routing only."""
    from unittest.mock import AsyncMock, patch

    from app.models.jobs import BackgroundJob
    from app.services.ai.embedding import EmbeddingError
    from app.services.core.background_jobs import BackgroundJobService
    from app.services.documents.refinement import index_job

    doc = _make_doc(test_org, test_user, DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()
    job = await BackgroundJobService.create(
        db_session,
        "document_index",
        "document",
        doc.id,
    )
    await db_session.flush()

    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    persist_failure = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=EmbeddingError("Ollama unreachable"),
    ), patch.object(
        index_job,
        "_load_and_claim_document",
        AsyncMock(return_value=(doc, job)),
    ), patch.object(
        index_job,
        "_persist_failure",
        persist_failure,
    ), patch.object(
        index_job,
        "create_async_engine",
        MagicMock(return_value=AsyncMock()),
    ), patch.object(
        index_job,
        "async_sessionmaker",
        MagicMock(return_value=fake_factory),
    ):
        await index_job.run_index(document_id=doc.id)

    persist_failure.assert_awaited_once()
    call = persist_failure.await_args
    # call.args is (session, document_id, job, message)
    assert call.args[1] == doc.id
    assert call.args[2] is job
    assert "Embedding failed" in call.args[3]


@pytest.mark.asyncio
async def test_persist_failure_marks_doc_and_job_failed(
    db_session, test_org, test_user
):
    """Direct unit test for _persist_failure with fully-committed fixtures."""
    from app.models.jobs import BackgroundJob, JobStatus
    from app.services.core.background_jobs import BackgroundJobService
    from app.services.documents.refinement import index_job

    doc = _make_doc(test_org, test_user, DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()
    job = await BackgroundJobService.create(
        db_session,
        "document_index",
        "document",
        doc.id,
    )
    await db_session.commit()

    await index_job._persist_failure(
        db_session,
        doc.id,
        job,
        "Embedding failed: Ollama unreachable",
    )

    from sqlalchemy import select

    fresh_doc = await db_session.scalar(select(Document).where(Document.id == doc.id))
    assert fresh_doc.status == DocumentStatus.FAILED.value
    assert "Indexing error" in (fresh_doc.error_message or "")

    fresh_job = await db_session.scalar(
        select(BackgroundJob).where(BackgroundJob.id == job.id)
    )
    assert fresh_job.status == JobStatus.FAILED.value
    assert "Embedding failed" in (fresh_job.error_message or "")


def test_job_registered_under_canonical_name():
    # Side-effect import: importing the module registers the job.
    from app.services.core.background_handler import JOB_REGISTRY
    from app.services.documents.refinement import index_job  # noqa: F401

    assert "document_index" in JOB_REGISTRY
    assert JOB_REGISTRY["document_index"].__name__ == "run_index"


@pytest.mark.asyncio
async def test_persist_success_drops_claim_if_watchdog_won_race(
    db_session, test_org, test_user
):
    """If the watchdog (or another sweep) marked the doc FAILED while the
    indexer was running, _persist_success must NOT overwrite that with
    READY — it should bail without touching state."""
    from app.services.core.background_jobs import BackgroundJobService
    from app.services.documents.refinement import index_job

    doc = _make_doc(test_org, test_user, DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()
    job = await BackgroundJobService.create(
        db_session,
        "document_index",
        "document",
        doc.id,
    )
    await db_session.flush()

    # Simulate watchdog winning the race: status flipped to FAILED in DB.
    doc.status = DocumentStatus.FAILED.value
    doc.error_message = "watchdog: stale heartbeat"
    await db_session.flush()

    await index_job._persist_success(db_session, doc, job)

    from sqlalchemy import select

    fresh = await db_session.scalar(select(Document).where(Document.id == doc.id))
    assert fresh.status == DocumentStatus.FAILED.value
    assert fresh.error_message == "watchdog: stale heartbeat"


@pytest.mark.asyncio
async def test_run_index_routes_unexpected_exception_to_persist_failure(
    db_session, test_org, test_user
):
    """A non-IndexingError crash inside the indexer must still route to
    _persist_failure, with the message prefixed 'unexpected error' so
    operators can tell it apart from a real IndexingError."""
    from unittest.mock import AsyncMock, patch

    from app.services.core.background_jobs import BackgroundJobService
    from app.services.documents.refinement import index_job

    doc = _make_doc(test_org, test_user, DocumentStatus.INDEXING)
    db_session.add(doc)
    await db_session.flush()
    job = await BackgroundJobService.create(
        db_session,
        "document_index",
        "document",
        doc.id,
    )
    await db_session.flush()

    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    persist_failure = AsyncMock()

    # NOTE: patch the symbol where it's *used* (index_job module), not
    # where it's defined — index_job imports the name at module-load.
    with patch.object(
        index_job,
        "index_refined_document",
        AsyncMock(side_effect=RuntimeError("disk on fire")),
    ), patch.object(
        index_job,
        "_load_and_claim_document",
        AsyncMock(return_value=(doc, job)),
    ), patch.object(
        index_job,
        "_persist_failure",
        persist_failure,
    ), patch.object(
        index_job,
        "create_async_engine",
        MagicMock(return_value=AsyncMock()),
    ), patch.object(
        index_job,
        "async_sessionmaker",
        MagicMock(return_value=fake_factory),
    ):
        await index_job.run_index(document_id=doc.id)

    persist_failure.assert_awaited_once()
    message = persist_failure.await_args.args[3]
    assert "unexpected error" in message
    assert "disk on fire" in message
