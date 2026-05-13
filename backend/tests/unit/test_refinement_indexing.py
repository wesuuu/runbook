from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.documents.refinement.indexing import index_refined_document


@pytest.mark.asyncio
async def test_index_refined_document_chunks_and_calls_embedder():
    doc = MagicMock()
    doc.id = uuid4()
    doc.org_id = uuid4()
    doc.stored_markdown = "# Heading\n\nBody paragraph.\n"

    db = AsyncMock()
    db.execute = AsyncMock()

    with patch(
        "app.services.documents.refinement.indexing.chunk_markdown",
        return_value=[MagicMock(content="# Heading", chunk_index=0,
                                token_count=2, page_number=None)],
    ), patch(
        "app.services.documents.refinement.indexing.embed_texts",
        AsyncMock(return_value=[[0.1] * 1536]),
    ):
        await index_refined_document(db, doc)

    # one DocumentChunk added
    assert db.add.called
