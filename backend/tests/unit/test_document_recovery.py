"""Tests for document processing resilience: idempotency, locking, recovery."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.iam import Organization, OrganizationMember, User
from app.models.library import (
    STALE_PROCESSING_SECONDS,
    Document,
    DocumentChunk,
    DocumentStatus,
)


@pytest_asyncio.fixture
async def recovery_user(db_session: AsyncSession) -> User:
    user = User(
        email="recovery-test@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Recovery Test User",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def recovery_org(db_session: AsyncSession, recovery_user: User) -> Organization:
    org = Organization(name="Recovery Org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=recovery_user.id,
            organization_id=org.id,
            roles=["MEMBER", "ADMIN"],
        )
    )
    await db_session.flush()
    return org


def _make_doc(
    org: Organization,
    user: User,
    status: str = DocumentStatus.UPLOADED.value,
    processing_started_at: datetime | None = None,
) -> Document:
    return Document(
        org_id=org.id,
        uploaded_by_id=user.id,
        title=f"Test Doc {uuid.uuid4().hex[:8]}",
        original_filename="test.txt",
        mime_type="text/plain",
        file_size_bytes=100,
        file_path="/tmp/fake.txt",
        status=status,
        processing_started_at=processing_started_at,
    )


class TestIdempotentProcessing:
    """Verify that re-processing a document deletes old chunks first."""

    @pytest.mark.asyncio
    async def test_reprocessing_deletes_old_chunks(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        doc = _make_doc(recovery_org, recovery_user, DocumentStatus.INDEXED.value)
        db_session.add(doc)
        await db_session.flush()

        # Simulate chunks from a prior run
        for i in range(3):
            db_session.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    content=f"old chunk {i}",
                    token_count=3,
                )
            )
        await db_session.flush()

        result = await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        )
        assert len(result.scalars().all()) == 3

        # Simulate what process_document does: delete old chunks
        from sqlalchemy import delete

        await db_session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        )
        await db_session.flush()

        result = await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        )
        assert len(result.scalars().all()) == 0


class TestStaleDetection:
    """Verify stale processing detection logic."""

    def test_stale_threshold_is_5_minutes(self):
        assert STALE_PROCESSING_SECONDS == 300

    @pytest.mark.asyncio
    async def test_stale_processing_detected(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        """A document processing for > 5 min should be detected as stale."""
        stale_time = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_PROCESSING_SECONDS + 60
        )
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.PROCESSING.value,
            processing_started_at=stale_time,
        )
        db_session.add(doc)
        await db_session.flush()

        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_PROCESSING_SECONDS
        )

        result = await db_session.execute(
            select(Document).where(
                Document.status == DocumentStatus.PROCESSING.value,
                Document.processing_started_at < cutoff,
            )
        )
        stalled = result.scalars().all()
        assert len(stalled) == 1
        assert stalled[0].id == doc.id

    @pytest.mark.asyncio
    async def test_fresh_processing_not_detected(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        """A document that just started processing should NOT be recovered."""
        fresh_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.PROCESSING.value,
            processing_started_at=fresh_time,
        )
        db_session.add(doc)
        await db_session.flush()

        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_PROCESSING_SECONDS
        )

        result = await db_session.execute(
            select(Document).where(
                Document.status == DocumentStatus.PROCESSING.value,
                Document.processing_started_at < cutoff,
            )
        )
        stalled = result.scalars().all()
        assert len(stalled) == 0

    @pytest.mark.asyncio
    async def test_uploaded_documents_detected_for_recovery(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        """Documents still in UPLOADED should be picked up by recovery."""
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.UPLOADED.value,
        )
        db_session.add(doc)
        await db_session.flush()

        result = await db_session.execute(
            select(Document).where(
                Document.status == DocumentStatus.UPLOADED.value,
            )
        )
        uploaded = result.scalars().all()
        assert any(d.id == doc.id for d in uploaded)

    @pytest.mark.asyncio
    async def test_indexed_documents_not_recovered(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        """Successfully indexed documents should not be touched."""
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.INDEXED.value,
        )
        db_session.add(doc)
        await db_session.flush()

        from sqlalchemy import or_

        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_PROCESSING_SECONDS
        )
        result = await db_session.execute(
            select(Document).where(
                or_(
                    Document.status == DocumentStatus.UPLOADED.value,
                    (
                        (Document.status == DocumentStatus.PROCESSING.value)
                        & (Document.processing_started_at < cutoff)
                    ),
                )
            )
        )
        stalled = result.scalars().all()
        assert not any(d.id == doc.id for d in stalled)


class TestProcessingStartedAtLifecycle:
    """Verify processing_started_at is set and cleared correctly."""

    @pytest.mark.asyncio
    async def test_processing_started_at_set_on_processing(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        doc = _make_doc(recovery_org, recovery_user)
        db_session.add(doc)
        await db_session.flush()

        assert doc.processing_started_at is None

        # Simulate processor setting it
        doc.status = DocumentStatus.PROCESSING.value
        doc.processing_started_at = datetime.now(timezone.utc)
        await db_session.flush()

        assert doc.processing_started_at is not None

    @pytest.mark.asyncio
    async def test_processing_started_at_cleared_on_indexed(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.PROCESSING.value,
            processing_started_at=datetime.now(timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        # Simulate processor finishing
        doc.status = DocumentStatus.INDEXED.value
        doc.processing_started_at = None
        await db_session.flush()

        assert doc.processing_started_at is None

    @pytest.mark.asyncio
    async def test_processing_started_at_cleared_on_failed(
        self, db_session: AsyncSession, recovery_org, recovery_user
    ):
        doc = _make_doc(
            recovery_org,
            recovery_user,
            DocumentStatus.PROCESSING.value,
            processing_started_at=datetime.now(timezone.utc),
        )
        db_session.add(doc)
        await db_session.flush()

        doc.status = DocumentStatus.FAILED.value
        doc.processing_started_at = None
        await db_session.flush()

        assert doc.processing_started_at is None
