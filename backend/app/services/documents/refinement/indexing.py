"""Chunks refined markdown into DocumentChunks and embeds them.

Called from the endpoint that marks refinement complete. Replaces
the old build_book + rechunk_with_structure path; the input is the
already-clean refined markdown so there's no need for AI-driven
structure recovery.
"""

import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import (EMBEDDING_DIMENSIONS, Document, DocumentChunk,
                                DocumentStatus)
from app.services.ai.embedding import embed_texts
from app.services.documents.markdown_chunker import chunk_markdown

logger = logging.getLogger(__name__)


def _pad_embedding(vec: list[float]) -> list[float]:
    if len(vec) >= EMBEDDING_DIMENSIONS:
        return vec[:EMBEDDING_DIMENSIONS]
    return list(vec) + [0.0] * (EMBEDDING_DIMENSIONS - len(vec))


async def index_refined_document(
    db: AsyncSession, doc: Document
) -> None:
    """Chunk + embed the refined markdown. Idempotent: drops prior chunks."""
    if not doc.stored_markdown:
        doc.status = DocumentStatus.READY.value
        return

    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )

    chunks = chunk_markdown(doc.stored_markdown, 1000, 200, None)
    try:
        embeddings = await embed_texts(
            [c.content for c in chunks], db, org_id=doc.org_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Embedding failed for refined doc %s: %s",
            doc.id,
            str(exc)[:200],
        )
        embeddings = []

    for i, chunk in enumerate(chunks):
        emb = _pad_embedding(embeddings[i]) if i < len(embeddings) else None
        db.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                chunk_metadata={"content_format": "markdown"},
                embedding=emb,
            )
        )

    doc.status = DocumentStatus.READY.value
