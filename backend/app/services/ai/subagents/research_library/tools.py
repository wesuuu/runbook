"""Tools for the research_library subagent.

Provides semantic + keyword document search, section reading,
and document listing over the org's document library.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai import RunContext
from sqlalchemy import text as sa_text

from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.documents.retrieval import retrieve_relevant_chunks

logger = logging.getLogger(__name__)

# ─── Result Models ─────────────────────────────────────────────────────────────


@dataclass
class DocumentChunkResult:
    """A single chunk returned by search_documents."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    page_number: int | None
    content: str
    score: float


@dataclass
class SearchDocumentsResult:
    """Result of a search_documents call."""

    total: int
    chunks: list[DocumentChunkResult] = field(default_factory=list)
    message: str = ""


@dataclass
class SectionChunk:
    """A single chunk from a document section."""

    chunk_index: int
    page_number: int | None
    content: str


@dataclass
class DocumentSectionResult:
    """Result of a read_section call."""

    document_id: UUID
    document_title: str
    chunks: list[SectionChunk] = field(default_factory=list)
    message: str = ""


@dataclass
class DocumentListItem:
    """Metadata for a single document in the library."""

    document_id: UUID
    title: str
    chunk_count: int


@dataclass
class ListDocumentsResult:
    """Result of a list_documents call."""

    total: int
    documents: list[DocumentListItem] = field(default_factory=list)
    message: str = ""


# ─── Tools ─────────────────────────────────────────────────────────────────────


async def search_documents(
    ctx: RunContext[ChatDeps],
    query: str,
    document_ids: list[UUID] | None = None,
    top_k: int = 8,
) -> SearchDocumentsResult:
    """Hybrid semantic + keyword search over the org's document library.

    Returns the most relevant chunks for the query. Use this first when the
    user asks a question that might be answered by library content.

    Args:
        ctx: Run context with shared deps.
        query: The search query.
        document_ids: Optional list of document IDs to restrict the search.
        top_k: Maximum number of chunks to return (default 8).
    """
    chunks = await retrieve_relevant_chunks(
        db=ctx.deps.db,
        query=query,
        org_id=ctx.deps.org_id,
        document_ids=document_ids,
        top_k=top_k,
    )

    # Append to shared sources list for citation aggregation
    ctx.deps.sources.extend(chunks)

    # Audit
    ctx.deps.tool_calls.append(
        {
            "tool": "search_documents",
            "subagent": "research_library",
            "query": query,
            "results": len(chunks),
        }
    )

    if not chunks:
        return SearchDocumentsResult(
            total=0,
            message="No matching documents found for the given query.",
        )

    return SearchDocumentsResult(
        total=len(chunks),
        chunks=[
            DocumentChunkResult(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                content=c.content,
                score=c.score,
            )
            for c in chunks
        ],
    )


async def read_section(
    ctx: RunContext[ChatDeps],
    document_id: UUID,
    around_chunk_index: int,
    window: int = 2,
) -> DocumentSectionResult:
    """Read a window of chunks surrounding a specific chunk index.

    Use this to get more context around a promising chunk found by
    search_documents (e.g., to read the full paragraph or procedure step).

    Args:
        ctx: Run context with shared deps.
        document_id: The document to read from.
        around_chunk_index: The chunk index to centre the window on.
        window: Number of chunks to read on each side of the target (default 2).
    """
    low = max(0, around_chunk_index - window)
    high = around_chunk_index + window

    result = await ctx.deps.db.execute(
        sa_text(
            """
            SELECT
                dc.chunk_index,
                dc.page_number,
                dc.content,
                d.title AS document_title
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.document_id = :document_id
              AND d.org_id = :org_id
              AND dc.chunk_index BETWEEN :low AND :high
            ORDER BY dc.chunk_index
            """
        ),
        {
            "document_id": str(document_id),
            "org_id": str(ctx.deps.org_id),
            "low": low,
            "high": high,
        },
    )
    rows = result.fetchall()

    if not rows:
        ctx.deps.tool_calls.append(
            {
                "tool": "read_section",
                "subagent": "research_library",
                "document_id": str(document_id),
                "around_chunk_index": around_chunk_index,
                "results": 0,
            }
        )
        return DocumentSectionResult(
            document_id=document_id,
            document_title="",
            message=f"No chunks found for document {document_id} around index {around_chunk_index}.",
        )

    document_title = rows[0].document_title

    # Build RetrievedChunk objects so they appear in citations
    retrieved: list[RetrievedChunk] = [
        RetrievedChunk(
            document_id=document_id,
            document_title=document_title,
            chunk_id=UUID(int=0),  # section reads don't have a chunk UUID from the query
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            content=row.content,
            score=1.0,
        )
        for row in rows
    ]
    ctx.deps.sources.extend(retrieved)

    ctx.deps.tool_calls.append(
        {
            "tool": "read_section",
            "subagent": "research_library",
            "document_id": str(document_id),
            "around_chunk_index": around_chunk_index,
            "results": len(rows),
        }
    )

    return DocumentSectionResult(
        document_id=document_id,
        document_title=document_title,
        chunks=[
            SectionChunk(
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=row.content,
            )
            for row in rows
        ],
    )


async def list_documents(
    ctx: RunContext[ChatDeps],
) -> ListDocumentsResult:
    """List all documents available in the org's library.

    Use this only when the user explicitly asks what documents are available,
    not as a substitute for searching.

    Args:
        ctx: Run context with shared deps.
    """
    result = await ctx.deps.db.execute(
        sa_text(
            """
            SELECT
                d.id AS document_id,
                d.title,
                COUNT(dc.id) AS chunk_count
            FROM documents d
            LEFT JOIN document_chunks dc ON dc.document_id = d.id
            WHERE d.org_id = :org_id
            GROUP BY d.id, d.title
            ORDER BY d.title
            """
        ),
        {"org_id": str(ctx.deps.org_id)},
    )
    rows = result.fetchall()

    ctx.deps.tool_calls.append(
        {
            "tool": "list_documents",
            "subagent": "research_library",
            "results": len(rows),
        }
    )

    if not rows:
        return ListDocumentsResult(
            total=0,
            message="No documents found in the library.",
        )

    return ListDocumentsResult(
        total=len(rows),
        documents=[
            DocumentListItem(
                document_id=UUID(str(row.document_id)),
                title=row.title,
                chunk_count=row.chunk_count,
            )
            for row in rows
        ],
    )
