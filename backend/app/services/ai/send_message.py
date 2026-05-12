"""send_message orchestration — ties together sessions, compaction, agent, persistence.

This module is the single entry-point for chat message handling and replaces the
_call_llm + send_message pair in chat_service.py (see Task 19 for the cutover).
"""

import logging
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
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
    # Capture session identity into locals up front. After the LLM call, a
    # failed tool can poison `db`; if our subsequent rollback also fails, the
    # ORM `session` object's attributes become unreloadable and any access
    # raises PendingRollbackError. Reading these into locals now means the
    # post-LLM path never has to touch the ORM object again.
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    # ── 1. Persist user message ──────────────────────────────────────────────
    user_msg = ChatMessage(
        session_id=session_pk,
        role=ChatMessageRole.USER,
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()

    # Auto-title from first message
    if session.title == "New Chat":
        session.title = user_content[:100].strip()
        await db.flush()

    # Commit before the LLM call so the asyncpg connection isn't holding an
    # open transaction during a network round-trip that can take 30s+. If
    # postgres/the proxy kills the idle conn mid-call, an open txn prevents
    # SQLAlchemy from recovering — flushes afterward fail with
    # PendingRollbackError. Committing here releases the txn; the next flush
    # transparently re-checks-out a fresh conn from the pool.
    await db.commit()

    # ── 2. Build CompactionState + ChatDeps ──────────────────────────────────
    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session_org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )

    # ── 3. Build agent + deserialize message history ─────────────────────────
    agent = await build_chat_agent(db, session_org_id, state)

    message_history = None
    if existing_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(
                existing_history
            )
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history for session %s, "
                "starting fresh",
                session_pk,
            )
            message_history = None

    # ── 4. Run the agent ─────────────────────────────────────────────────────
    result = await agent.run(
        user_content,
        deps=deps,
        message_history=message_history,
    )

    # ── 5. De-dup sources by chunk_id ─────────────────────────────────────────
    seen_chunk_ids: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for source in deps.sources:
        if source.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(source.chunk_id)
            unique_sources.append(source)

    # ── 6. Sanitize output + assemble assistant message ───────────────────────
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
        session_id=session_pk,
        role=ChatMessageRole.ASSISTANT,
        content=assistant_content,
        metadata_=meta if meta else None,
    )

    history_payload = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )

    # Finalize any tool side effects on the original session. If a tool
    # poisoned the txn (raised after partial work) or the conn was killed,
    # rolling back keeps the endpoint's outer commit from re-raising. Tool
    # writes that succeeded fully are preserved by commit; partial writes
    # are correctly discarded by rollback.
    try:
        await db.commit()
    except Exception as exc:
        logger.warning(
            "Tool-call session commit failed (%s); rolling back. "
            "User-facing chat history will still be persisted via a fresh "
            "session.",
            exc.__class__.__name__,
        )
        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback of poisoned tool-call session failed")

    # ── 7. Persist post-LLM writes on a FRESH session ────────────────────────
    # The original `db` was used by subagent tool calls during agent.run().
    # If any tool query raised an asyncpg error, the implicit transaction is
    # poisoned (PendingRollbackError on next flush). Even when nothing failed,
    # the conn may have been killed by pgbouncer / idle_in_transaction_session
    # _timeout while the LLM was thinking. Using a clean session for the
    # ChatMessage rows + ai_message_history update guarantees the user's chat
    # history is saved regardless of what happened to `db` inside tools.
    summary_msg: ChatMessage | None = None
    if state.triggered and state.summary_text:
        summary_msg = ChatMessage(
            session_id=session_pk,
            role=ChatMessageRole.SUMMARY,
            content=state.summary_text,
            metadata_=state.audit_metadata(),
        )

    async with AsyncSessionLocal() as writer:
        if summary_msg is not None:
            writer.add(summary_msg)
        writer.add(assistant_msg)
        await writer.execute(
            update(ChatSession)
            .where(ChatSession.id == session_pk)
            .values(ai_message_history=history_payload)
        )
        await writer.commit()
        await writer.refresh(assistant_msg)
        if summary_msg is not None:
            await writer.refresh(summary_msg)

    # Keep the in-memory ChatSession instance consistent with what we just
    # wrote, so any caller that still reads from `session` sees current data.
    # Guarded against ORM expiry: if `db` was poisoned and rollback also failed,
    # the assignment below would trigger a load before the SET. Skip silently —
    # the row in DB is correct; in-memory consistency is best-effort.
    try:
        session.ai_message_history = history_payload
    except Exception:
        logger.debug(
            "Could not refresh in-memory session.ai_message_history (db likely "
            "poisoned). DB row is correct; returning to caller.",
        )

    # ── 8. Return ─────────────────────────────────────────────────────────────
    return user_msg, assistant_msg, unique_sources
