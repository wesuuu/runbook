import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from app.models.science import UnitOpDefinition
from app.services.ai.ai_config import get_context_window, get_model

logger = logging.getLogger(__name__)

# ─── System Prompt ───

SYSTEM_PROMPT = """You are Batchrite AI, a concise assistant for biotech Process Development scientists.

RULES:
- Never show your reasoning, thought process, or <think> tags. Respond directly.
- Never show JSON, IDs, or tool schemas. Speak in plain language.
- Be concise. Use markdown for formatting.

WHEN THE USER WANTS TO CREATE A PROTOCOL:
→ Call load_skill("generate-protocol") and follow its instructions exactly.
→ Do NOT just summarize documents. You must guide the user through steps and call create_protocol().

DOCUMENT SEARCH:
- Use search_documents() when the user asks questions that library docs could answer.
- Use read_document_section() for more context after a search.
- Use list_documents() when the user asks what's in the library.
- Cite sources with [1], [2] when using document content.
- If no docs found, answer from knowledge with this disclaimer:
  > ⚠️ This is from general AI knowledge, not your organization's documents. Verify independently.
- Never fabricate document titles or pretend info came from the library."""

SUMMARIZATION_PROMPT = """Summarize the following conversation between a user and an AI assistant.
Preserve: key decisions, user preferences, protocols/experiments discussed, specific values/parameters mentioned, and any unresolved questions.
Be concise (2-3 paragraphs). Write in third person ("The user discussed...").
Do NOT include greetings, pleasantries, or meta-commentary about the summary itself."""

RAG_TOP_K = 8
RAG_MAX_CONTEXT_CHARS = 12000
RAG_MIN_SCORE = 0.05
LLM_MAX_TOKENS = 16384


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
    user_id: UUID
    is_org_admin: bool
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


class UnitOpInfo(BaseModel):
    name: str
    category: str


class ListUnitOpsResult(BaseModel):
    unit_ops: list[UnitOpInfo]
    total: int
    message: str


class CreateUnitOpResult(BaseModel):
    id: str
    name: str
    category: str


class CreateProtocolResult(BaseModel):
    protocol_id: str
    protocol_name: str
    project_id: str


# ─── Document Tool Functions ───

async def search_documents_tool(
    ctx: RunContext[ChatDeps], query: str, max_results: int = 5
) -> SearchDocumentsResult:
    """Search the organization's document library for relevant content."""
    chunks = await retrieve_relevant_chunks(
        ctx.deps.db, query=query, org_id=ctx.deps.org_id, top_k=max_results,
    )
    # If no results, retry with shorter query (embeddings degrade on long queries)
    if not chunks and len(query.split()) > 3:
        short_query = " ".join(query.split()[:4])
        chunks = await retrieve_relevant_chunks(
            ctx.deps.db, query=short_query, org_id=ctx.deps.org_id, top_k=max_results,
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


# ─── Protocol Tool Functions ───

async def list_unit_ops_tool(
    ctx: RunContext[ChatDeps],
) -> ListUnitOpsResult:
    """List available unit operation names and categories.

    This returns a SHORT list of names only. Use it to pick the right
    unit op for each protocol step. Do NOT show this list to the user.
    Instead, use the names to propose steps conversationally.
    """
    result = await ctx.deps.db.execute(
        select(UnitOpDefinition)
        .where(
            (UnitOpDefinition.organization_id == ctx.deps.org_id)
            | (UnitOpDefinition.organization_id.is_(None))
        )
        .order_by(UnitOpDefinition.category)
    )
    ops = result.scalars().all()

    ctx.deps.tool_calls.append({"tool": "list_unit_ops", "results": len(ops)})

    return ListUnitOpsResult(
        unit_ops=[
            UnitOpInfo(name=op.name, category=op.category)
            for op in ops
        ],
        total=len(ops),
        message="Use these names when proposing protocol steps. Do not show this list to the user.",
    )


async def create_unit_op_tool(
    ctx: RunContext[ChatDeps],
    name: str,
    category: str,
    description: str,
    param_schema: dict[str, Any],
    scope: str = "project",
    project_id: str | None = None,
) -> CreateUnitOpResult:
    """Create a custom unit operation definition.

    scope must be "org" or "project".
    - "project" requires project_id, any user can do this
    - "org" makes it available org-wide, only admins can do this

    Only call this AFTER the user has confirmed the name, category,
    description, and parameters. Never create a unit op without
    explicit user approval.
    """
    db = ctx.deps.db

    if scope == "org":
        if not ctx.deps.is_org_admin:
            raise ValueError(
                "Only organization admins can create org-wide unit operations. "
                "Use scope='project' instead."
            )
        org_id = ctx.deps.org_id
        proj_id = None
    elif scope == "project":
        if not project_id:
            raise ValueError("project_id is required for project-scoped unit ops")
        org_id = ctx.deps.org_id
        proj_id = UUID(project_id)
    else:
        raise ValueError("scope must be 'org' or 'project'")

    # Check for duplicates at this scope or above
    existing = await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.name == name,
            (UnitOpDefinition.organization_id == ctx.deps.org_id)
            | (UnitOpDefinition.organization_id.is_(None)),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Unit op '{name}' already exists")

    unit_op = UnitOpDefinition(
        name=name,
        category=category,
        description=description,
        param_schema=param_schema,
        organization_id=org_id,
        project_id=proj_id,
    )
    db.add(unit_op)
    await db.flush()

    ctx.deps.tool_calls.append({
        "tool": "create_unit_op",
        "unit_op_id": str(unit_op.id),
        "name": name,
    })

    return CreateUnitOpResult(
        id=str(unit_op.id),
        name=unit_op.name,
        category=unit_op.category,
    )


async def create_protocol_tool(
    ctx: RunContext[ChatDeps],
    project_name: str,
    protocol_name: str,
    protocol_description: str,
    steps_text: str,
) -> CreateProtocolResult:
    """Create a protocol in a project.

    Args:
        project_name: Name of the project (e.g. "mAb Production v2").
        protocol_name: Name for the new protocol.
        protocol_description: Short description.
        steps_text: Steps as a simple text list, one per line.
            Format each line as: step_name | unit_op_name | duration_min
            Example: "Dissolve Tris | Buffer Preparation | 15"
    """
    import json as json_mod
    from app.models.science import Protocol, Project
    from app.services.ai.protocol_generator import (
        build_graph,
        GeneratedStep,
        GeneratedProtocol,
    )
    from app.services.permissions import check_permission
    from app.models.iam import ObjectType, PermissionLevel

    db = ctx.deps.db

    # Look up project by name
    result = await db.execute(
        select(Project).where(Project.name.ilike(f"%{project_name}%"))
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise ValueError(f"Project '{project_name}' not found")

    pid = project.id

    # Check EDIT permission
    allowed = await check_permission(
        db, ctx.deps.user_id, ObjectType.PROJECT, pid, PermissionLevel.EDIT
    )
    if not allowed:
        raise ValueError("You don't have edit permission on this project")

    # Parse steps from simple text format
    parsed_steps: list[GeneratedStep] = []
    for line in steps_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        step_name = parts[0] if len(parts) > 0 else "Step"
        unit_op_name = parts[1] if len(parts) > 1 else parts[0]
        duration = 30
        if len(parts) > 2:
            try:
                duration = int(parts[2])
            except ValueError:
                pass
        parsed_steps.append(GeneratedStep(
            name=step_name,
            unit_op_name=unit_op_name,
            duration_min=duration,
        ))

    if not parsed_steps:
        raise ValueError("No steps provided")

    # Fetch unit ops for matching
    result = await db.execute(select(UnitOpDefinition))
    unit_ops = list(result.scalars().all())

    generated = GeneratedProtocol(
        name=protocol_name,
        description=protocol_description,
        steps=parsed_steps,
    )

    graph = build_graph(generated, unit_ops, UUID(int=0), ctx.deps.user_id)

    protocol = Protocol(
        name=protocol_name,
        description=protocol_description,
        project_id=pid,
        status="DRAFT",
        graph=graph,
    )
    db.add(protocol)
    await db.flush()

    ctx.deps.tool_calls.append({
        "tool": "create_protocol",
        "protocol_id": str(protocol.id),
        "project_id": str(pid),
    })

    return CreateProtocolResult(
        protocol_id=str(protocol.id),
        protocol_name=protocol.name,
        project_id=str(pid),
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
    user_id: UUID,
    is_org_admin: bool,
    skill_inject: str | None = None,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    """Send a user message and get an AI response with tool-based RAG.

    Args:
        db: Database session.
        session: The chat session.
        user_content: User's message content.
        user_id: Authenticated user ID (injected server-side).
        is_org_admin: Whether the user is an org admin.
        skill_inject: Optional skill instructions to inject (button path).

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
    assistant_content, sources, tool_calls, new_history, context_warning = (
        await _call_llm(
            db,
            session_id=session.id,
            user_content=user_content,
            org_id=session.org_id,
            user_id=user_id,
            is_org_admin=is_org_admin,
            ai_message_history=session.ai_message_history,
            skill_inject=skill_inject,
        )
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
    if context_warning:
        meta.update(context_warning)
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


# ─── Skills Toolset (lazy singleton) ───

_skills_toolset = None


def _get_skills_toolset():
    """Lazy-init the SkillsToolset to avoid import-time side effects."""
    global _skills_toolset
    if _skills_toolset is None:
        from pydantic_ai_skills import SkillsToolset
        from app.core.config import settings
        _skills_toolset = SkillsToolset(directories=[settings.skills_dir])
    return _skills_toolset


# ─── Output Sanitization ───

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_THOUGHT_HEADER_PATTERN = re.compile(
    r"\*{0,2}(?:Thought Process|Internal Reasoning|My Reasoning|Analysis|Planning)"
    r"[:\*]*\s*\n.*?(?=\n---|\n\*{0,2}(?:Answer|Response)[:\*]|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_BARE_JSON_PATTERN = re.compile(
    r"(?<!\`\`\`)([\{\[]\s*\".{20,}?[\}\]])", re.DOTALL
)


def _sanitize_output(text: str) -> str:
    """Clean up LLM output: strip reasoning tags, wrap bare JSON in code fences."""
    # Strip <think>...</think> blocks
    cleaned = _THINK_PATTERN.sub("", text).strip()

    # Strip bold "Thought Process:" / "Internal Reasoning:" sections
    cleaned = _THOUGHT_HEADER_PATTERN.sub("", cleaned).strip()

    # Strip leading "---" or "**Answer:**" wrappers left behind
    cleaned = re.sub(r"^---\s*\n", "", cleaned)
    cleaned = re.sub(r"^\*{0,2}Answer\*{0,2}[:\s]*\n?", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return text

    # Wrap bare JSON blocks in code fences for readability
    def _wrap_json(m: re.Match) -> str:
        json_str = m.group(1)
        # Skip if already inside a code fence
        prefix = cleaned[:m.start()]
        if prefix.count("```") % 2 == 1:
            return m.group(0)
        return f"\n```json\n{json_str}\n```\n"

    cleaned = _BARE_JSON_PATTERN.sub(_wrap_json, cleaned)
    return cleaned.strip()


# ─── Token Estimation ───


def estimate_tokens(text: str) -> int:
    """Estimate token count using 4 chars/token heuristic."""
    return len(text) // 4


def estimate_messages_tokens(messages: list) -> int:
    """Estimate total tokens across serialized pydantic-ai messages.

    Strips SystemPromptPart entries before counting since pydantic-ai
    re-injects the system prompt on each agent.run() call.
    """
    total = 0
    for msg in messages:
        # Work on a copy to avoid mutating the original
        if isinstance(msg, dict):
            msg_copy = msg.copy()
            # Strip system prompt parts from requests
            if msg_copy.get("kind") == "request" and "parts" in msg_copy:
                msg_copy["parts"] = [
                    p for p in msg_copy["parts"]
                    if p.get("part_kind") != "system-prompt"
                ]
        else:
            msg_copy = msg
        total += estimate_tokens(json.dumps(msg_copy, default=str))
    return total


# ─── Context Compaction ───


async def compact_history(
    db: AsyncSession,
    session_id: UUID,
    messages: list,
    token_budget: int,
    model,
    org_id: UUID,
) -> tuple[list, str | None]:
    """Compact message history if it exceeds the token budget.

    When over budget:
    1. Find the last summary message in the session
    2. Summarize [existing_summary + messages - latest] via LLM
    3. Insert a ChatMessage(role="summary") into the DB
    4. Return compacted pydantic-ai history: [SystemPromptPart(summary)] + [latest]

    Returns (compacted_messages, summary_text_or_none).
    """
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        ModelResponse,
        SystemPromptPart,
        TextPart,
        UserPromptPart,
    )

    # Serialize to dicts for accurate token estimation
    serialized = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    total_tokens = estimate_messages_tokens(serialized)
    if total_tokens <= token_budget:
        return messages, None

    logger.info(
        "Compaction triggered for session %s: %d tokens > %d budget",
        session_id, total_tokens, token_budget,
    )

    # Find the latest message (will be kept raw)
    if not messages:
        return messages, None
    latest_message = messages[-1]
    older_messages = messages[:-1]

    # Build text representation of older messages for summarization
    existing_summary = await _get_last_summary(db, session_id)
    conversation_text = _build_conversation_text(older_messages, existing_summary)

    # Summarize via a lightweight LLM call
    summary_text = await _generate_summary(conversation_text, model)

    # Get message stats in a single query (cast UUID to text for min/max)
    stats = await db.execute(
        select(
            func.count(ChatMessage.id),
            func.min(ChatMessage.created_at),
            func.max(ChatMessage.created_at),
        ).where(
            ChatMessage.session_id == session_id,
            ChatMessage.role != ChatMessageRole.SUMMARY,
        )
    )
    db_message_count, _first_at, _last_at = stats.one()
    # Get IDs from timestamps (single extra query, but avoids UUID min/max)
    boundary_result = await db.execute(
        select(ChatMessage.id)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.role != ChatMessageRole.SUMMARY,
            ChatMessage.created_at.in_([_first_at, _last_at]),
        )
        .order_by(ChatMessage.created_at)
    )
    boundary_ids = [row[0] for row in boundary_result.all()]
    first_id = boundary_ids[0] if boundary_ids else None
    last_id = boundary_ids[-1] if boundary_ids else None

    # Insert summary message into DB
    summary_msg = ChatMessage(
        session_id=session_id,
        role=ChatMessageRole.SUMMARY,
        content=summary_text,
        metadata_={
            "type": "summary",
            "summarized_message_count": db_message_count,
            "first_summarized_message_id": str(first_id) if first_id else None,
            "last_summarized_message_id": str(last_id) if last_id else None,
        },
    )
    db.add(summary_msg)
    await db.flush()

    # Build compacted pydantic-ai history: [summary as SystemPromptPart] + [latest]
    summary_request = ModelRequest(parts=[
        SystemPromptPart(
            content=f"[CONVERSATION SUMMARY]\n{summary_text}\n[END SUMMARY]"
        ),
    ])
    compacted = [summary_request, latest_message]

    logger.info(
        "Compaction complete for session %s: %d tokens -> %d tokens",
        session_id, total_tokens, estimate_messages_tokens(compacted),
    )

    return compacted, summary_text


async def _get_last_summary(db: AsyncSession, session_id: UUID) -> str | None:
    """Get the content of the last summary message for a session."""
    result = await db.execute(
        select(ChatMessage.content)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.role == ChatMessageRole.SUMMARY,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _build_conversation_text(
    messages: list, existing_summary: str | None = None
) -> str:
    """Build a plain-text representation of messages for summarization."""
    parts: list[str] = []

    if existing_summary:
        parts.append(f"[Previous summary]: {existing_summary}")
        parts.append("")

    for msg in messages:
        if isinstance(msg, dict):
            kind = msg.get("kind")
            if kind == "request":
                for part in msg.get("parts", []):
                    pk = part.get("part_kind")
                    if pk == "user-prompt":
                        content = part.get("content", "")
                        if isinstance(content, str):
                            parts.append(f"User: {content}")
                    elif pk == "tool-return":
                        tool_name = part.get("tool_name", "tool")
                        content = part.get("content", "")
                        if isinstance(content, str) and len(content) > 200:
                            content = content[:200] + "..."
                        parts.append(f"[Tool {tool_name}]: {content}")
            elif kind == "response":
                for part in msg.get("parts", []):
                    pk = part.get("part_kind")
                    if pk == "text":
                        parts.append(f"Assistant: {part.get('content', '')}")
                    elif pk == "tool-call":
                        parts.append(
                            f"[Tool call: {part.get('tool_name', 'unknown')}]"
                        )
        else:
            # Handle deserialized pydantic-ai message objects
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if hasattr(part, "part_kind"):
                        if part.part_kind == "user-prompt":
                            content = part.content if isinstance(
                                part.content, str
                            ) else str(part.content)
                            parts.append(f"User: {content}")
                        elif part.part_kind == "text":
                            parts.append(f"Assistant: {part.content}")
                        elif part.part_kind == "tool-return":
                            content = str(part.content)
                            if len(content) > 200:
                                content = content[:200] + "..."
                            parts.append(f"[Tool {part.tool_name}]: {content}")
                        elif part.part_kind == "tool-call":
                            parts.append(
                                f"[Tool call: {part.tool_name}]"
                            )

    return "\n".join(parts)


async def _generate_summary(conversation_text: str, model) -> str:
    """Generate a conversation summary using the LLM."""
    from pydantic_ai import Agent

    agent = Agent(
        model,
        system_prompt=SUMMARIZATION_PROMPT,
    )
    result = await agent.run(conversation_text)
    return result.output


def _truncate_to_fit(messages: list, max_tokens: int) -> list:
    """Hard-truncate message history from the front to fit within token limit.

    Pre-calculates per-message token counts to avoid O(N^2) re-estimation.
    Always preserves at least the last message.
    """
    if not messages:
        return messages
    msg_tokens = [estimate_tokens(json.dumps(m, default=str)) for m in messages]
    total = sum(msg_tokens)
    idx = 0
    while idx < len(messages) - 1 and total > max_tokens:
        total -= msg_tokens[idx]
        idx += 1
    return messages[idx:]


# ─── LLM Call ───

async def _call_llm(
    db: AsyncSession,
    session_id: UUID,
    user_content: str,
    org_id: UUID,
    user_id: UUID,
    is_org_admin: bool,
    ai_message_history: list | None = None,
    skill_inject: str | None = None,
) -> tuple[str, list[RetrievedChunk], list[dict], list, dict | None]:
    """Call the LLM with tool access and native message history.

    Args:
        db: Database session.
        session_id: Chat session ID (for compaction DB writes).
        user_content: User's message.
        org_id: Organization ID.
        user_id: Authenticated user ID.
        is_org_admin: Whether user is org admin.
        ai_message_history: Serialized pydantic-ai message history.
        skill_inject: Optional skill instructions (button-triggered).

    Returns (assistant_content, sources, tool_calls, new_message_history,
             context_warning).
    """
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    model = await get_model("chat", db, org_id=org_id)
    deps = ChatDeps(
        db=db, org_id=org_id, user_id=user_id, is_org_admin=is_org_admin
    )

    # Build system prompt — append user context and skill if button-triggered
    system = SYSTEM_PROMPT
    system += f"\n\nUSER CONTEXT: is_org_admin={is_org_admin}"
    if skill_inject:
        system += f"\n\n---\n\nACTIVE SKILL INSTRUCTIONS:\n{skill_inject}"

    skills_toolset = _get_skills_toolset()

    agent = Agent(
        model,
        system_prompt=system,
        tools=[
            list_documents_tool,
            search_documents_tool,
            read_document_section_tool,
            list_unit_ops_tool,
            create_unit_op_tool,
            create_protocol_tool,
        ],
        toolsets=[skills_toolset],
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

    # ── Compaction ──
    context_warning = None
    if message_history:
        context_window = await get_context_window("chat", db, org_id=org_id)
        budget = int(context_window * settings.compaction_threshold)

        message_history, _summary = await compact_history(
            db=db,
            session_id=session_id,
            messages=message_history,
            token_budget=budget,
            model=model,
            org_id=org_id,
        )

        # Safety net: if still over the full context window, hard-truncate
        serialized = ModelMessagesTypeAdapter.dump_python(
            message_history, mode="json"
        )
        total_tokens = estimate_messages_tokens(serialized)
        if total_tokens > context_window:
            logger.warning(
                "History still %d tokens after compaction (limit %d), truncating",
                total_tokens, context_window,
            )
            truncated = _truncate_to_fit(serialized, context_window)
            message_history = ModelMessagesTypeAdapter.validate_python(truncated)
            context_warning = {
                "context_warning": (
                    "This conversation's history has been heavily compacted. "
                    "Response quality may degrade — consider starting a new "
                    "chat session."
                )
            }

    result = await agent.run(
        user_content,
        deps=deps,
        message_history=message_history,
        model_settings={"max_tokens": LLM_MAX_TOKENS},
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

    # Clean up LLM output: strip reasoning tags, wrap bare JSON
    output = _sanitize_output(result.output)

    return output, unique_sources, deps.tool_calls, new_history, context_warning
