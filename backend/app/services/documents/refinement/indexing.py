"""Chunks refined markdown into DocumentChunks and embeds them.

Called from the document_index background job (services/documents/
refinement/index_job.py). The function is idempotent — it deletes
existing chunks before re-indexing — so a worker restart that lands
on the recovery sweep can safely re-run from scratch.
"""

import logging
from typing import Awaitable, Callable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Document, DocumentChunk, DocumentStatus
from app.services.ai.embedding import EmbeddingError, embed_texts
from app.services.documents.document_processor import _pad_embedding
from app.services.documents.markdown_chunker import chunk_markdown

logger = logging.getLogger(__name__)


class IndexingError(Exception):
    """Raised when indexing cannot proceed (no markdown, embed failed, etc.).

    The document_index job wrapper catches this and transitions the
    document to FAILED with the error message.
    """


# Type for batch-progress callbacks: async fn(current, total).
ProgressCallback = Callable[[int, int], Awaitable[None]]


async def index_refined_document(
    db: AsyncSession,
    doc: Document,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Chunk + embed the refined markdown. Idempotent — drops prior chunks first.

    Raises IndexingError on empty markdown or embed failure. The caller
    (background job) owns transitioning doc.status to READY/FAILED and
    committing.
    """
    if not doc.stored_markdown:
        raise IndexingError(
            f"Document {doc.id} has no stored_markdown to index"
        )

    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )
    await db.flush()

    chunks = chunk_markdown(doc.stored_markdown, 1000, 200, None)
    if not chunks:
        # Markdown was non-empty but only whitespace / unsplittable.
        doc.status = DocumentStatus.READY.value
        return

    try:
        embeddings = await embed_texts(
            [c.content for c in chunks],
            db,
            on_progress=on_progress,
            org_id=doc.org_id,
        )
    except EmbeddingError as exc:
        raise IndexingError(
            f"Embedding failed for document {doc.id}: {exc}"
        ) from exc

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
