import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from app.services.ai_config import get_model

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Trellis AI, an expert assistant for biotech Process Development scientists.

You help with:
- Answering questions about cell biology, genetics, protein purification, and other biotech domains
- Discussing protocols and experimental procedures
- Explaining scientific concepts and best practices
- Providing guidance on process development workflows

Be concise, accurate, and scientifically rigorous. When you're uncertain, say so.
Format responses in markdown when helpful (lists, code blocks, tables).

When document context is provided below, ground your answers in that context and cite sources
using inline footnote numbers like [1], [2], etc. that correspond to the numbered sources.
If the context doesn't contain relevant information, say so and answer from general knowledge.
If no document context is provided, answer from your general scientific knowledge."""

SYSTEM_PROMPT_NO_DOCS = """You are Trellis AI, an expert assistant for biotech Process Development scientists.

You help with:
- Answering questions about cell biology, genetics, protein purification, and other biotech domains
- Discussing protocols and experimental procedures
- Explaining scientific concepts and best practices
- Providing guidance on process development workflows

Be concise, accurate, and scientifically rigorous. When you're uncertain, say so.
Format responses in markdown when helpful (lists, code blocks, tables).

Note: This organization has no documents in their library yet. Answer from your
general scientific knowledge. If the user asks about specific documents, let them
know they can upload documents to the Library for document-grounded answers."""

MAX_CONTEXT_MESSAGES = 50
RAG_TOP_K = 8
RAG_MAX_CONTEXT_CHARS = 12000
RAG_MIN_SCORE = 0.3


@dataclass
class RetrievedChunk:
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float


async def create_session(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    title: Optional[str] = None,
    context_document_ids: Optional[list[UUID]] = None,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        org_id=org_id,
        title=title or "New Chat",
        context_document_ids=[str(did) for did in context_document_ids]
        if context_document_ids
        else None,
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(
    db: AsyncSession, session_id: UUID
) -> Optional[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatSession], int]:
    base_query = select(ChatSession).where(
        ChatSession.user_id == user_id,
        ChatSession.org_id == org_id,
        ChatSession.status == ChatSessionStatus.ACTIVE,
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = list(result.scalars().all())
    return sessions, total


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    await db.delete(session)
    await db.flush()


async def send_message(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    """Send a user message and get an AI response with RAG.

    Returns (user_message, assistant_message, sources).
    """
    # Save user message
    user_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.USER,
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()

    # Auto-title from first message
    if session.title == "New Chat":
        session.title = user_content[:100].strip()
        await db.flush()

    # RAG: retrieve relevant document chunks
    sources = await retrieve_relevant_chunks(
        db,
        query=user_content,
        org_id=session.org_id,
    )

    # Check if org has any documents at all
    has_documents = await _org_has_documents(db, session.org_id)

    # Build conversation history for LLM
    history = await _get_message_history(db, session.id)

    # Call LLM with RAG context
    assistant_content = await _call_llm(db, history, sources, has_documents)

    # Save assistant message with source metadata
    source_metadata = None
    if sources:
        source_metadata = {
            "sources": [
                {
                    "document_id": str(s.document_id),
                    "document_title": s.document_title,
                    "chunk_id": str(s.chunk_id),
                    "chunk_index": s.chunk_index,
                    "page_number": s.page_number,
                    "score": s.score,
                    "snippet": s.content[:200],
                }
                for s in sources
            ]
        }

    assistant_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.ASSISTANT,
        content=assistant_content,
        metadata_=source_metadata,
    )
    db.add(assistant_msg)
    await db.flush()

    return user_msg, assistant_msg, sources


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

    Returns top-K chunks sorted by relevance, limited to max_chars total.
    Falls back to keyword-only if embedding service is unavailable.
    """
    # Try to get query embedding
    query_embedding = None
    try:
        from app.services.embedding import embed_query
        from app.services.document_processor import _pad_embedding

        raw = await embed_query(query, db)
        query_embedding = _pad_embedding(raw)
    except Exception:
        logger.debug("Embedding unavailable for RAG, using keyword-only")

    fetch_limit = top_k * 3  # Fetch extra for filtering

    if query_embedding is not None:
        # Check if any chunks have embeddings
        has_embeddings = await db.execute(
            sa_text("""
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.org_id = :org_id AND dc.embedding IS NOT NULL
                LIMIT 1
            """),
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
                sa_text(f"""
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
                """),
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

        chunks.append(RetrievedChunk(
            document_id=row.document_id,
            document_title=row.document_title,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            content=content,
            score=score,
        ))
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
        sa_text(f"""
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
        """),
        params,
    )


async def _org_has_documents(db: AsyncSession, org_id: UUID) -> bool:
    result = await db.execute(
        sa_text("""
            SELECT 1 FROM documents
            WHERE org_id = :org_id
            LIMIT 1
        """),
        {"org_id": str(org_id)},
    )
    return result.fetchone() is not None


def _format_rag_context(sources: list[RetrievedChunk]) -> str:
    """Format retrieved chunks as numbered context for the system prompt."""
    if not sources:
        return ""

    parts = ["\n--- DOCUMENT CONTEXT ---"]
    parts.append(
        "The following excerpts from the user's document library are relevant. "
        "Cite sources using [1], [2], etc."
    )
    for i, chunk in enumerate(sources, 1):
        page_info = f", page {chunk.page_number}" if chunk.page_number else ""
        parts.append(
            f"\n[{i}] \"{chunk.document_title}\"{page_info}:\n"
            f"{chunk.content}"
        )
    parts.append("--- END CONTEXT ---")
    return "\n".join(parts)


async def _get_message_history(
    db: AsyncSession, session_id: UUID
) -> list[dict[str, str]]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()

    # Truncate to last N messages
    recent = list(messages)[-MAX_CONTEXT_MESSAGES:]

    return [{"role": m.role, "content": m.content} for m in recent]


async def _call_llm(
    db: AsyncSession,
    history: list[dict[str, str]],
    sources: list[RetrievedChunk] | None = None,
    has_documents: bool = True,
) -> str:
    """Call the LLM with conversation history and optional RAG context."""
    from pydantic_ai import Agent

    # Choose system prompt based on context
    if sources:
        system = SYSTEM_PROMPT + _format_rag_context(sources)
    elif not has_documents:
        system = SYSTEM_PROMPT_NO_DOCS
    else:
        system = SYSTEM_PROMPT

    model = await get_model("chat", db)
    agent = Agent(model, system_prompt=system)

    # Build the conversation as a single user message with history context
    # pydantic-ai doesn't have native multi-turn, so we format history
    if len(history) <= 1:
        prompt = history[-1]["content"] if history else ""
    else:
        parts = []
        for msg in history[:-1]:
            role_label = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {msg['content']}")
        parts.append(f"User: {history[-1]['content']}")
        prompt = "\n\n".join(parts)

    result = await agent.run(prompt)
    return result.output
