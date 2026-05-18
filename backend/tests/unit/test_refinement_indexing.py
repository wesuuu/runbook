from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.library import DocumentStatus
from app.services.ai.embedding import EmbeddingError
from app.services.documents.refinement.indexing import (
    IndexingError,
    index_refined_document,
)


def _doc(markdown: str | None = "# Heading\n\nBody paragraph.\n"):
    d = MagicMock()
    d.id = uuid4()
    d.org_id = uuid4()
    d.stored_markdown = markdown
    d.status = DocumentStatus.INDEXING.value
    return d


@pytest.mark.asyncio
async def test_index_refined_document_chunks_and_calls_embedder():
    doc = _doc()
    db = AsyncMock()
    db.execute = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[
            MagicMock(
                content="# Heading", chunk_index=0, token_count=2, page_number=None
            )
        ],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    ):
        await index_refined_document(db, doc)

    # one DocumentChunk added; doc transitioned to READY
    assert db.add.called
    assert doc.status == DocumentStatus.READY.value


@pytest.mark.asyncio
async def test_index_refined_document_raises_on_missing_markdown():
    """Indexer must refuse to run on a doc without stored_markdown — it's
    a programmer error (job claim should have prevented this) and we'd
    rather fail loudly than silently READY-transition an empty doc."""
    doc = _doc(markdown=None)
    db = AsyncMock()

    with pytest.raises(IndexingError, match="no stored_markdown"):
        await index_refined_document(db, doc)

    # No chunks added, no transition.
    assert not db.add.called


@pytest.mark.asyncio
async def test_index_refined_document_handles_whitespace_only_markdown():
    """Non-empty but unsplittable markdown (only whitespace, broken
    chunker output) must still transition the doc to READY rather than
    leaving it stuck INDEXING. No embed call should be issued."""
    doc = _doc(markdown="   \n\n   \n")
    db = AsyncMock()
    db.execute = AsyncMock()

    embed_mock = AsyncMock()
    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        embed_mock,
    ):
        await index_refined_document(db, doc)

    assert doc.status == DocumentStatus.READY.value
    embed_mock.assert_not_called()
    assert not db.add.called


@pytest.mark.asyncio
async def test_index_refined_document_drops_prior_chunks_first():
    """Idempotency: indexer issues a DELETE for prior chunks BEFORE
    inserting new ones — so a recovery re-run produces one final set,
    not duplicates."""
    from sqlalchemy import delete

    from app.models.library import DocumentChunk

    doc = _doc()
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[
            MagicMock(content="c", chunk_index=0, token_count=1, page_number=None)
        ],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    ):
        await index_refined_document(db, doc)

    # The first db.execute call must be a DELETE on DocumentChunk
    # scoped to this document. Compile to string for an exact assertion
    # that doesn't depend on private SQLAlchemy internals.
    assert db.execute.call_count >= 1
    first_stmt = db.execute.call_args_list[0].args[0]
    rendered = str(first_stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "DELETE FROM document_chunks" in rendered


@pytest.mark.asyncio
async def test_index_refined_document_wraps_embed_error_as_indexing_error():
    """An EmbeddingError from the embedder is wrapped as IndexingError
    with the doc id in the message — so logs / error_message surface
    which doc failed, not just 'Ollama unreachable'."""
    doc = _doc()
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[
            MagicMock(content="c", chunk_index=0, token_count=1, page_number=None)
        ],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        AsyncMock(side_effect=EmbeddingError("Ollama unreachable")),
    ):
        with pytest.raises(IndexingError, match="Embedding failed for document"):
            await index_refined_document(db, doc)
