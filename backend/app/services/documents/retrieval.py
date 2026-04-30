"""RAG retrieval for document chunks via pgvector + keyword fallback.

Extracted from services/ai/chat_service.py during TD-0081 migration.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.deps import RetrievedChunk

logger = logging.getLogger(__name__)

# ─── Constants ───

RAG_TOP_K = 8
RAG_MAX_CONTEXT_CHARS = 12000
RAG_MIN_SCORE = 0.05


# ─── Public API ───


async def retrieve_relevant_chunks(
    db: AsyncSession,
    query: str,
    org_id: UUID,
    document_ids: list[UUID] | None = None,
    top_k: int = RAG_TOP_K,
    max_chars: int = RAG_MAX_CONTEXT_CHARS,
    min_score: float = RAG_MIN_SCORE,
) -> list[RetrievedChunk]:
    """Hybrid semantic + keyword search over document chunks.

    Wraps _retrieve_once with a retry-with-shorter-query heuristic:
    if the first pass returns nothing and the query is more than 3 words,
    retries with the first 4 words (embeddings degrade on long queries).

    Returns top-K chunks sorted by relevance, limited to max_chars total.
    Falls back to keyword-only if embedding service is unavailable.
    """
    chunks = await _retrieve_once(
        db, query, org_id, document_ids, top_k, max_chars, min_score
    )

    if not chunks and len(query.split()) > 3:
        short_query = " ".join(query.split()[:4])
        logger.debug("RAG retry with shorter query: %r -> %r", query, short_query)
        chunks = await _retrieve_once(
            db, short_query, org_id, document_ids, top_k, max_chars, min_score
        )

    return chunks


# ─── Internal helpers ───


async def _retrieve_once(
    db: AsyncSession,
    query: str,
    org_id: UUID,
    document_ids: list[UUID] | None,
    top_k: int,
    max_chars: int,
    min_score: float,
) -> list[RetrievedChunk]:
    """Single retrieval pass: pgvector hybrid search or keyword-only fallback."""
    # Try to get query embedding
    query_embedding = None
    try:
        from app.services.ai.embedding import embed_query
        from app.services.documents.document_processor import _pad_embedding

        raw = await embed_query(query, db)
        query_embedding = _pad_embedding(raw)
    except Exception:
        logger.debug("Embedding unavailable for RAG, using keyword-only")

    fetch_limit = top_k * 3  # Fetch extra for filtering

    if query_embedding is not None:
        # Check if any chunks have embeddings
        has_embeddings = await db.execute(
            sa_text(
                """
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.org_id = :org_id AND dc.embedding IS NOT NULL
                LIMIT 1
            """
            ),
            {"org_id": str(org_id)},
        )

        if has_embeddings.fetchone() is not None:
            # Hybrid search
            doc_filter = ""
            params: dict[str, Any] = {
                "query_vec": str(query_embedding),
                "query": query,
                "org_id": str(org_id),
                "limit": fetch_limit,
            }
            if document_ids:
                doc_filter = "AND dc.document_id = ANY(:doc_ids)"
                params["doc_ids"] = [str(d) for d in document_ids]

            result = await db.execute(
                sa_text(
                    f"""
                    SELECT
                        dc.id AS chunk_id,
                        dc.document_id,
                        dc.chunk_index,
                        dc.content,
                        dc.page_number,
                        d.title AS document_title,
                        CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END AS vector_score,
                        CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END AS keyword_score
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE d.org_id = :org_id
                      {doc_filter}
                      AND (
                          dc.embedding IS NOT NULL
                          OR dc.search_vector @@ plainto_tsquery('english', :query)
                      )
                    ORDER BY (
                        0.7 * CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END
                        + 0.3 * CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END
                    ) DESC
                    LIMIT :limit
                """
                ),
                params,
            )
        else:
            result = await _keyword_search_chunks(
                db, query, org_id, document_ids, fetch_limit
            )
    else:
        result = await _keyword_search_chunks(
            db, query, org_id, document_ids, fetch_limit
        )

    rows = result.fetchall()

    # Score, filter, and limit by character budget
    chunks: list[RetrievedChunk] = []
    total_chars = 0

    for row in rows:
        if hasattr(row, "vector_score"):
            score = round(0.7 * row.vector_score + 0.3 * row.keyword_score, 4)
        else:
            score = round(float(row.keyword_score), 4)

        if score < min_score:
            continue

        content = row.content
        if total_chars + len(content) > max_chars:
            break

        chunks.append(
            RetrievedChunk(
                document_id=row.document_id,
                document_title=row.document_title,
                chunk_id=row.chunk_id,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=content,
                score=score,
            )
        )
        total_chars += len(content)

        if len(chunks) >= top_k:
            break

    return chunks


async def _keyword_search_chunks(
    db: AsyncSession,
    query: str,
    org_id: UUID,
    document_ids: list[UUID] | None,
    limit: int,
):
    doc_filter = ""
    params: dict[str, Any] = {
        "query": query,
        "org_id": str(org_id),
        "limit": limit,
    }
    if document_ids:
        doc_filter = "AND dc.document_id = ANY(:doc_ids)"
        params["doc_ids"] = [str(d) for d in document_ids]

    return await db.execute(
        sa_text(
            f"""
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.page_number,
                d.title AS document_title,
                ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                    AS keyword_score
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.org_id = :org_id
              {doc_filter}
              AND dc.search_vector @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(dc.search_vector, plainto_tsquery('english', :query)) DESC
            LIMIT :limit
        """
        ),
        params,
    )
