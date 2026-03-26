import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from app.services.ai_config import get_model

logger = logging.getLogger(__name__)

# ─── System Prompt ───

SYSTEM_PROMPT = """You are Trellis AI, an expert assistant for biotech Process Development scientists.

You help with:
- Answering questions about cell biology, genetics, protein purification, and biotech domains
- Discussing protocols and experimental procedures
- Explaining scientific concepts and best practices
- Providing guidance on process development workflows

Be concise, accurate, and scientifically rigorous. Format responses in markdown when helpful.

TOOLS:
1. list_documents() — List all documents in the organization's library.
   Use when the user asks what's in the library, what documents are available, or wants an inventory.
2. search_documents(query, max_results) — Search the document library by topic/keyword.
   Use when the user asks a question that could be answered by organizational documents.
3. read_document_section(document_id, chunk_index, window) — Read surrounding chunks
   of a document for deeper context after an initial search.

PRIORITY ORDER — follow this strictly:
1. When the user asks what documents or materials are available, use list_documents().
2. When the user asks a question that could be answered by organizational documents
   (SOPs, protocols, procedures, reference materials, experimental data), use
   search_documents() to find relevant content.
3. If a search result is incomplete, use read_document_section() to get more context.
4. If the library search returns relevant results, ground your answer in those documents
   and cite sources using [1], [2], etc.
5. If the library search returns NO relevant results, OR if the question is clearly
   about general scientific knowledge (not org-specific), you may answer from your
   internal knowledge — but you MUST prepend a disclaimer:

   > ⚠️ **Note:** This answer is based on general AI knowledge, not your organization's
   > documents. It may be outdated or inaccurate. Verify with authoritative sources.

6. NEVER fabricate document titles, ISBNs, library contents, or pretend information
   came from the organization's library when it did not.
7. If you are unsure whether the answer should come from documents or general knowledge,
   search first — it is always safer to check."""

MAX_CONTEXT_MESSAGES = 50
RAG_TOP_K = 8
RAG_MAX_CONTEXT_CHARS = 12000
RAG_MIN_SCORE = 0.3


# ─── Data Classes ───

@dataclass
class RetrievedChunk:
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    score: float


@dataclass
class ChatDeps:
    """Dependencies injected into pydantic-ai tools via RunContext."""
    db: AsyncSession
    org_id: UUID
    sources: list[RetrievedChunk] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)


# ─── Tool Return Models ───

class DocumentChunkResult(BaseModel):
    document_id: str
    document_title: str
    chunk_index: int
    page_number: int | None
    relevance: float
    content: str


class SearchDocumentsResult(BaseModel):
    results: list[DocumentChunkResult]
    total: int
    message: str


class SectionChunk(BaseModel):
    chunk_index: int
    page_number: int | None
    content: str
    is_target: bool


class DocumentSectionResult(BaseModel):
    document_id: str
    document_title: str
    chunks: list[SectionChunk]


class DocumentListItem(BaseModel):
    document_id: str
    title: str
    status: str
    page_count: int | None


class ListDocumentsResult(BaseModel):
    documents: list[DocumentListItem]
    total: int
    message: str


# ─── Tool Functions ───

async def search_documents_tool(
    ctx: RunContext[ChatDeps], query: str, max_results: int = 5
) -> SearchDocumentsResult:
    """Search the organization's document library for relevant content."""
    chunks = await retrieve_relevant_chunks(
        ctx.deps.db, query=query, org_id=ctx.deps.org_id, top_k=max_results,
    )
    ctx.deps.sources.extend(chunks)
    ctx.deps.tool_calls.append({
        "tool": "search_documents",
        "query": query,
        "results": len(chunks),
    })

    return SearchDocumentsResult(
        results=[
            DocumentChunkResult(
                document_id=str(c.document_id),
                document_title=c.document_title,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                relevance=c.score,
                content=c.content,
            )
            for c in chunks
        ],
        total=len(chunks),
        message=f"Found {len(chunks)} results" if chunks
        else "No matching documents found in the library",
    )


async def read_document_section_tool(
    ctx: RunContext[ChatDeps],
    document_id: str,
    chunk_index: int,
    window: int = 2,
) -> DocumentSectionResult:
    """Read a section of a document by fetching chunks around a given index.

    Use this after search_documents finds a relevant but incomplete chunk
    and you need more surrounding context.
    """
    result = await ctx.deps.db.execute(
        sa_text("""
            SELECT dc.id AS chunk_id, dc.document_id, dc.chunk_index,
                   dc.content, dc.page_number, d.title AS document_title
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.document_id = :doc_id
              AND d.org_id = :org_id
              AND dc.chunk_index BETWEEN :start AND :end
            ORDER BY dc.chunk_index
        """),
        {
            "doc_id": document_id,
            "org_id": str(ctx.deps.org_id),
            "start": max(0, chunk_index - window),
            "end": chunk_index + window,
        },
    )
    rows = result.fetchall()

    if not rows:
        return DocumentSectionResult(
            document_id=document_id,
            document_title="Unknown",
            chunks=[],
        )

    # Accumulate as sources
    for row in rows:
        ctx.deps.sources.append(RetrievedChunk(
            document_id=row.document_id,
            document_title=row.document_title,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            content=row.content,
            score=1.0,
        ))

    ctx.deps.tool_calls.append({
        "tool": "read_document_section",
        "document_id": document_id,
        "chunk_index": chunk_index,
        "window": window,
        "results": len(rows),
    })

    return DocumentSectionResult(
        document_id=document_id,
        document_title=rows[0].document_title,
        chunks=[
            SectionChunk(
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=row.content,
                is_target=row.chunk_index == chunk_index,
            )
            for row in rows
        ],
    )


async def list_documents_tool(
    ctx: RunContext[ChatDeps],
) -> ListDocumentsResult:
    """List all documents in the organization's library.

    Use this when the user asks what documents are available, what's in
    the library, or wants an inventory of uploaded materials.
    """
    result = await ctx.deps.db.execute(
        sa_text("""
            SELECT id, title, status, page_count
            FROM documents
            WHERE org_id = :org_id
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"org_id": str(ctx.deps.org_id)},
    )
    rows = result.fetchall()

    ctx.deps.tool_calls.append({
        "tool": "list_documents",
        "results": len(rows),
    })

    return ListDocumentsResult(
        documents=[
            DocumentListItem(
                document_id=str(row.id),
                title=row.title,
                status=row.status,
                page_count=row.page_count,
            )
            for row in rows
        ],
        total=len(rows),
        message=f"{len(rows)} documents in the library" if rows
        else "No documents have been uploaded to the library yet",
    )


# ─── Session CRUD ───

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


# ─── Send Message (main entry point) ───

async def send_message(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    """Send a user message and get an AI response with tool-based RAG.

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

    # Call LLM — agent decides when to search via tools
    assistant_content, sources, tool_calls, new_history = await _call_llm(
        db,
        user_content=user_content,
        org_id=session.org_id,
        ai_message_history=session.ai_message_history,
    )

    # Persist pydantic-ai message history on session
    session.ai_message_history = new_history
    await db.flush()

    # Build metadata
    metadata: dict | None = None
    meta: dict[str, Any] = {}
    if sources:
        meta["sources"] = [
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
    if tool_calls:
        meta["tool_calls"] = tool_calls
    if meta:
        metadata = meta

    assistant_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.ASSISTANT,
        content=assistant_content,
        metadata_=metadata,
    )
    db.add(assistant_msg)
    await db.flush()

    return user_msg, assistant_msg, sources


# ─── RAG Search (used by tool) ───

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


# ─── Message History ───

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


# ─── LLM Call ───

async def _call_llm(
    db: AsyncSession,
    user_content: str,
    org_id: UUID,
    ai_message_history: list | None = None,
) -> tuple[str, list[RetrievedChunk], list[dict], list]:
    """Call the LLM with tool access and native message history.

    Returns (assistant_content, sources, tool_calls, new_message_history).
    """
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    model = await get_model("chat", db, org_id=org_id)
    deps = ChatDeps(db=db, org_id=org_id)

    agent = Agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        tools=[list_documents_tool, search_documents_tool, read_document_section_tool],
        deps_type=ChatDeps,
    )

    # Deserialize stored message history if available
    message_history = None
    if ai_message_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                ai_message_history
            )
        except Exception:
            logger.warning("Failed to deserialize ai_message_history, starting fresh")
            message_history = None

    result = await agent.run(
        user_content, deps=deps, message_history=message_history,
    )

    # Deduplicate sources by chunk_id
    seen_ids: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for s in deps.sources:
        if s.chunk_id not in seen_ids:
            seen_ids.add(s.chunk_id)
            unique_sources.append(s)

    # Serialize full message history for cross-turn persistence
    new_history = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )

    return result.output, unique_sources, deps.tool_calls, new_history
