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
import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic_ai.messages import (FunctionToolCallEvent,
                                  FunctionToolResultEvent,
                                  ModelMessagesTypeAdapter)
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults
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

    # ── 7b. Branch: deferred-tool approval gate? ─────────────────────────────
    deferred = (
        result.output if isinstance(result.output, DeferredToolRequests) else None
    )
    pending_approval_call = (
        deferred.approvals[0] if deferred and deferred.approvals else None
    )

    if pending_approval_call is not None:
        args = pending_approval_call.args or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args = {}
        title = str(args.get("title") or "")
        source_url = str(args.get("source_url") or "")
        payload_raw = args.get("payload_json") or "{}"
        try:
            payload = (
                json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            )
        except (json.JSONDecodeError, ValueError):
            payload = {}

        steps = payload.get("steps") if isinstance(payload, dict) else None
        step_count = len(steps) if isinstance(steps, list) else 0
        durations = [
            s.get("duration_min") for s in (steps or []) if isinstance(s, dict)
        ]
        duration_min_total = sum(d for d in durations if isinstance(d, int)) or None

        payload_preview = {
            "title": title,
            "source_url": source_url,
            "step_count": step_count,
            "duration_min_total": duration_min_total,
            "license": (payload.get("license") if isinstance(payload, dict) else None)
            or "CC BY-SA 3.0",
            "deviations": [],
        }

        history_payload = ModelMessagesTypeAdapter.dump_python(
            result.all_messages(), mode="json"
        )
        placeholder_meta: dict[str, Any] = {
            "pending_approval": {
                "tool_call_id": pending_approval_call.tool_call_id,
                "tool_name": pending_approval_call.tool_name,
                "title": title,
                "source_url": source_url,
                "payload_preview": payload_preview,
            }
        }
        if deps.tool_calls:
            placeholder_meta["tool_calls"] = deps.tool_calls

        placeholder = ChatMessage(
            session_id=session_pk,
            role=ChatMessageRole.ASSISTANT,
            content="Awaiting your approval to draft the selected protocol.",
            metadata_=placeholder_meta,
        )
        async with AsyncSessionLocal() as writer:
            writer.add(placeholder)
            await writer.execute(
                update(ChatSession)
                .where(ChatSession.id == session_pk)
                .values(ai_message_history=history_payload)
            )
            await writer.commit()
            await writer.refresh(placeholder)

        try:
            session.ai_message_history = history_payload
        except Exception:
            logger.debug(
                "Could not refresh in-memory session.ai_message_history",
            )

        yield {
            "type": "approval_required",
            "tool_call_id": pending_approval_call.tool_call_id,
            "tool_name": pending_approval_call.tool_name,
            "title": title,
            "source_url": source_url,
            "payload_preview": payload_preview,
            "assistant_message_id": str(placeholder.id),
        }
        return

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


async def resume_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    placeholder: ChatMessage,
    tool_call_id: str,
    approved: bool,
    user_id: UUID,
    is_org_admin: bool,
) -> AsyncIterator[dict[str, Any]]:
    """Resume a chat turn that paused on a DeferredToolRequests gate.

    Persists the user's approval/rejection as a USER ChatMessage, then resumes
    ``agent.run`` with ``deferred_tool_results=DeferredToolResults(...)`` and
    the session's existing message history. The placeholder ASSISTANT row is
    updated in place with the final content — no duplicate is created.
    """
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    decision_text = (
        "Approved external protocol conversion."
        if approved
        else "Rejected the external protocol conversion."
    )
    user_msg = ChatMessage(
        session_id=session_pk,
        role=ChatMessageRole.USER,
        content=decision_text,
    )
    db.add(user_msg)
    await db.flush()
    await db.commit()
    await db.refresh(user_msg)

    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session_org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )

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

    agent = await build_chat_agent(db, session_org_id, state)

    message_history = None
    if existing_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(existing_history)
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history for session %s on resume",
                session_pk,
            )

    deferred_results = DeferredToolResults(approvals={tool_call_id: approved})

    run_task: asyncio.Task = asyncio.create_task(
        agent.run(
            deps=deps,
            message_history=message_history,
            event_stream_handler=_parent_event_handler,
            deferred_tool_results=deferred_results,
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
        logger.exception("Chat agent resume failed for session %s", session_pk)
        if not run_task.done():
            run_task.cancel()
        yield {"type": "error", "detail": "Failed to resume AI response"}
        return

    try:
        await db.commit()
    except Exception as exc:
        logger.warning(
            "Tool-call session commit failed on resume (%s); rolling back.",
            exc.__class__.__name__,
        )
        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback of poisoned session failed on resume")

    seen: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for s in deps.sources:
        if s.chunk_id not in seen:
            seen.add(s.chunk_id)
            unique_sources.append(s)

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

    history_payload = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )

    async with AsyncSessionLocal() as writer:
        await writer.execute(
            update(ChatMessage)
            .where(ChatMessage.id == placeholder.id)
            .values(content=assistant_content, metadata_=meta or None)
        )
        await writer.execute(
            update(ChatSession)
            .where(ChatSession.id == session_pk)
            .values(ai_message_history=history_payload)
        )
        await writer.commit()

    try:
        session.ai_message_history = history_payload
    except Exception:
        logger.debug("Could not refresh in-memory session.ai_message_history on resume")

    placeholder.content = assistant_content
    placeholder.metadata_ = meta or None

    yield {
        "type": "done",
        "user_message": ChatMessageResponse.model_validate(user_msg).model_dump(
            mode="json"
        ),
        "assistant_message": ChatMessageResponse.model_validate(placeholder).model_dump(
            mode="json"
        ),
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
