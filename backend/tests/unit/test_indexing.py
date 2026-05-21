"""Unit tests for the refined-document indexer (TD-0085 Phase 3)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.library import Document, DocumentStatus, RefinementStatus
from app.services.documents.refinement.indexing import (
    IndexingError,
    index_refined_document,
)


def _doc(test_org, test_user, stored_markdown: str | None) -> Document:
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
        stored_markdown=stored_markdown,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        slug=f"t-{uuid.uuid4().hex[:8]}",
    )


@pytest.mark.asyncio
async def test_empty_markdown_raises(db_session, test_org, test_user):
    doc = _doc(test_org, test_user, stored_markdown=None)
    db_session.add(doc)
    await db_session.flush()

    with pytest.raises(IndexingError, match="no stored_markdown"):
        await index_refined_document(db_session, doc)


@pytest.mark.asyncio
async def test_embed_failure_raises_indexing_error(db_session, test_org, test_user):
    from unittest.mock import patch

    from app.services.ai.embedding import EmbeddingError

    doc = _doc(
        test_org,
        test_user,
        stored_markdown="# A heading\n\nSome body content.",
    )
    db_session.add(doc)
    await db_session.flush()

    with patch(
        "app.services.documents.refinement.indexing.embed_texts",
        side_effect=EmbeddingError("Ollama unreachable"),
    ):
        with pytest.raises(IndexingError, match="Embedding failed"):
            await index_refined_document(db_session, doc)


@pytest.mark.asyncio
async def test_progress_callback_forwarded_to_embed_texts(
    db_session, test_org, test_user
):
    from unittest.mock import patch

    doc = _doc(
        test_org,
        test_user,
        stored_markdown="# H\n\n" + ("word " * 3000),  # >1 chunk
    )
    db_session.add(doc)
    await db_session.flush()

    seen: list[tuple[int, int]] = []

    async def cb(current: int, total: int) -> None:
        seen.append((current, total))

    async def fake_embed_texts(texts, db, on_progress=None, org_id=None):
        # Simulate embed_texts: fire on_progress once per BATCH_SIZE
        # batch and return one zero-vector per text.
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
