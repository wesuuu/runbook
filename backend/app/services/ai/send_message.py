"""send_message orchestration — ties together sessions, compaction, agent, persistence.

This module is the single entry-point for chat message handling and replaces the
_call_llm + send_message pair in chat_service.py (see Task 19 for the cutover).
"""
import logging
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.runtime.compaction import CompactionState
from app.services.ai.runtime.sanitize import sanitize_output

logger = logging.getLogger(__name__)


async def send_message(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
) -> tuple[ChatMessage, ChatMessage, list[RetrievedChunk]]:
    """Send a user message and get an AI response.

    Orchestrates:
    1. Persist user message, auto-title session if "New Chat".
    2. Build CompactionState + ChatDeps.
    3. Build agent via build_chat_agent, deserialize message history.
    4. Run the agent.
    5. If compaction triggered, write a ChatMessage(role=SUMMARY) row.
    6. Persist ai_message_history on session.
    7. De-dup sources by chunk_id.
    8. Sanitize output, persist assistant message with metadata.
    9. Return (user_msg, assistant_msg, sources).

    Args:
        db: Database session.
        session: The chat session ORM object.
        user_content: The raw user message text.
        user_id: Authenticated user ID.
        is_org_admin: Whether the user is an org admin.

    Returns:
        Tuple of (user_message, assistant_message, deduplicated_sources).
    """
    # ── 1. Persist user message ──────────────────────────────────────────────
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

    # ── 2. Build CompactionState + ChatDeps ──────────────────────────────────
    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session.org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )

    # ── 3. Build agent + deserialize message history ─────────────────────────
    agent = await build_chat_agent(db, session.org_id, state)

    message_history = None
    if session.ai_message_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                session.ai_message_history
            )
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history for session %s, "
                "starting fresh",
                session.id,
            )
            message_history = None

    # ── 4. Run the agent ─────────────────────────────────────────────────────
    result = await agent.run(
        user_content,
        deps=deps,
        message_history=message_history,
    )

    # ── 5. Write SUMMARY row if compaction triggered ─────────────────────────
    if state.triggered and state.summary_text:
        summary_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.SUMMARY,
            content=state.summary_text,
            metadata_=state.audit_metadata(),
        )
        db.add(summary_msg)
        await db.flush()

    # ── 6. Persist ai_message_history on session ─────────────────────────────
    session.ai_message_history = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )
    await db.flush()

    # ── 7. De-dup sources by chunk_id ─────────────────────────────────────────
    seen_chunk_ids: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for source in deps.sources:
        if source.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(source.chunk_id)
            unique_sources.append(source)

    # ── 8. Sanitize output + persist assistant message ────────────────────────
    assistant_content = sanitize_output(result.output)

    meta: dict[str, Any] = {}
    if unique_sources:
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
            for s in unique_sources
        ]
    if deps.tool_calls:
        meta["tool_calls"] = deps.tool_calls

    assistant_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.ASSISTANT,
        content=assistant_content,
        metadata_=meta if meta else None,
    )
    db.add(assistant_msg)
    await db.flush()

    # ── 9. Return ─────────────────────────────────────────────────────────────
    return user_msg, assistant_msg, unique_sources
