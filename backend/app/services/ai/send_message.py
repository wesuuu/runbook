"""send_message_streaming — orchestrates a chat turn as an async event stream.

Yields a sequence of dicts:
  {"type": "tool_start", "tool": <name>, "label": <human label>}
  {"type": "tool_end",   "tool": <name>}
  ... (repeats per tool) ...
  {"type": "done", "user_message": {...}, "assistant_message": {...}, "sources": [...]}

Or, on failure:
  {"type": "error", "detail": <str>}

Resilience pattern (preserved from the pre-streaming send_message):
  - The user message is committed on the request `db` *before* the LLM call so
    a slow/failed tool can't poison the SQLAlchemy session.
  - The assistant message + optional SUMMARY row + ai_message_history update
    are written on a fresh AsyncSessionLocal() writer session, so even if
    `db` was poisoned by a tool's asyncpg error, chat history still lands.

The caller (chat SSE endpoint) serializes each dict as an SSE `data:` line.
"""

import asyncio
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic_ai.messages import (FunctionToolCallEvent,
                                  FunctionToolResultEvent,
                                  ModelMessagesTypeAdapter)
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.schemas.chat import ChatMessageResponse, ChatSourceReference
from app.services.ai.chat_agent import build_chat_agent
from app.services.ai.deps import ChatDeps, RetrievedChunk
from app.services.ai.runtime.compaction import CompactionState
from app.services.ai.runtime.sanitize import sanitize_output
from app.services.ai.tool_labels import resolve_tool_label

logger = logging.getLogger(__name__)


async def send_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat turn as SSE-shaped event dicts. See module docstring."""
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

    if session.title == "New Chat":
        session.title = user_content[:100].strip()
        await db.flush()

    await db.commit()
    await db.refresh(user_msg)

    # ── 2. Build CompactionState + ChatDeps ──────────────────────────────────
    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session_org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )

    # ── 3. Event bridge: parent agent → asyncio.Queue ────────────────────────
    # Two paths feed this queue:
    #   1. Parent agent tool calls — via pydantic-ai's `event_stream_handler`
    #      (passed to agent.run below).
    #   2. Subagent tool calls — via `deps.tool_event_callback`, invoked from
    #      tool wrappers in chat_agent.py. We can't use event_stream_handler
    #      on subagents because it forces streaming mode, which some models
    #      (Ollama gpt-oss) reject on multi-turn tool dialogs.
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _parent_event_handler(_ctx, stream):
        async for event in stream:
            if isinstance(event, FunctionToolCallEvent):
                name = event.part.tool_name
                await event_queue.put(
                    {
                        "type": "tool_start",
                        "tool": name,
                        "label": resolve_tool_label(name),
                    }
                )
            elif isinstance(event, FunctionToolResultEvent):
                name = event.result.tool_name
                await event_queue.put({"type": "tool_end", "tool": name})

    async def _subagent_tool_event(event_type: str, name: str) -> None:
        if event_type == "tool_start":
            await event_queue.put(
                {
                    "type": "tool_start",
                    "tool": name,
                    "label": resolve_tool_label(name),
                }
            )
        else:
            await event_queue.put({"type": "tool_end", "tool": name})

    deps.tool_event_callback = _subagent_tool_event

    # ── 4. Build agent + deserialize message history ─────────────────────────
    agent = await build_chat_agent(db, session_org_id, state)

    message_history = None
    if existing_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(existing_history)
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history for session %s, "
                "starting fresh",
                session_pk,
            )
            message_history = None

    # ── 5. Run the agent in a background task; drain the queue ───────────────
    run_task: asyncio.Task = asyncio.create_task(
        agent.run(
            user_content,
            deps=deps,
            message_history=message_history,
            event_stream_handler=_parent_event_handler,
        )
    )

    try:
        while not run_task.done() or not event_queue.empty():
            queue_get = asyncio.create_task(event_queue.get())
            done_set, _pending = await asyncio.wait(
                {queue_get, run_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_get in done_set:
                ev = queue_get.result()
                if ev is not None:
                    yield ev
            else:
                queue_get.cancel()
        result = await run_task
    except Exception:
        logger.exception("Chat agent run failed for session %s", session_pk)
        if not run_task.done():
            run_task.cancel()
        yield {"type": "error", "detail": "Failed to generate AI response"}
        return

    # ── 6. Finalize tool side effects on the original session ────────────────
    try:
        await db.commit()
    except Exception as exc:
        logger.warning(
            "Tool-call session commit failed (%s); rolling back.",
            exc.__class__.__name__,
        )
        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback of poisoned tool-call session failed")

    # ── 7. De-dup sources by chunk_id ─────────────────────────────────────────
    seen_chunk_ids: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for source in deps.sources:
        if source.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(source.chunk_id)
            unique_sources.append(source)

    # ── 8. Sanitize output + assemble assistant message ───────────────────────
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

    summary_msg: ChatMessage | None = None
    if state.triggered and state.summary_text:
        summary_msg = ChatMessage(
            session_id=session_pk,
            role=ChatMessageRole.SUMMARY,
            content=state.summary_text,
            metadata_=state.audit_metadata(),
        )

    # ── 9. Fresh writer session for assistant + summary + history ────────────
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

    try:
        session.ai_message_history = history_payload
    except Exception:
        logger.debug(
            "Could not refresh in-memory session.ai_message_history "
            "(db likely poisoned); DB row is correct.",
        )

    # ── 10. Emit done event ──────────────────────────────────────────────────
    yield {
        "type": "done",
        "user_message": ChatMessageResponse.model_validate(user_msg).model_dump(
            mode="json"
        ),
        "assistant_message": ChatMessageResponse.model_validate(
            assistant_msg
        ).model_dump(mode="json"),
        "sources": [
            ChatSourceReference(
                document_id=s.document_id,
                document_title=s.document_title,
                chunk_id=s.chunk_id,
                chunk_index=s.chunk_index,
                page_number=s.page_number,
                score=s.score,
                snippet=s.content[:200],
            ).model_dump(mode="json")
            for s in unique_sources
        ],
    }
