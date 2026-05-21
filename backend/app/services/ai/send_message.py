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
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
)
from pydantic_ai.exceptions import ModelHTTPError
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
from app.services.ai.turn_status import clear_turn_heartbeat, turn_heartbeat

logger = logging.getLogger(__name__)


def _build_approval_payload_preview(
    pending_approval_call: Any,
    deps: ChatDeps,
) -> tuple[str, str, str, dict[str, Any], str]:
    """Extract args + assemble the payload preview for an approval pause.

    Returns ``(title, source_url, project_name, payload_preview, payload_raw)``.
    Shared by the initial-turn pause in ``send_message_streaming`` and the
    re-pause case in ``resume_message_streaming`` (e.g. when the agent redrafts
    after a rejection-with-reason).
    """
    args = pending_approval_call.args or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            args = {}
    title = str(args.get("title") or "")
    source_url = str(args.get("source_url") or "")
    project_name = str(args.get("project_name") or "").strip()
    # Deviations are computed by the frontend from the user's inline edits
    # to the approval card; on the initial pause the LLM has not seen any
    # edits yet, so this is always empty here.
    user_deviations: list[str] = []
    payload_raw = deps.external_protocol_cache.get(source_url)
    if not payload_raw and len(deps.external_protocol_cache) == 1:
        payload_raw = next(iter(deps.external_protocol_cache.values()))
    payload_raw = payload_raw or "{}"
    if payload_raw == "{}":
        logger.warning(
            "External protocol payload cache miss for source_url=%r "
            "(cache keys: %s). Approval card will show 0 steps.",
            source_url,
            list(deps.external_protocol_cache.keys()),
        )
    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    steps = payload.get("steps") if isinstance(payload, dict) else None
    step_count = len(steps) if isinstance(steps, list) else 0
    durations = [s.get("duration_min") for s in (steps or []) if isinstance(s, dict)]
    duration_min_total = sum(d for d in durations if isinstance(d, int)) or None
    step_previews: list[dict[str, Any]] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        text = step.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        duration = step.get("duration_min")
        step_previews.append(
            {
                "text": text.strip(),
                "duration_min": duration if isinstance(duration, int) else None,
            }
        )

    payload_preview = {
        "title": title,
        "source_url": source_url,
        "project_name": project_name or None,
        "step_count": step_count,
        "duration_min_total": duration_min_total,
        "license": (payload.get("license") if isinstance(payload, dict) else None)
        or "CC BY-SA 3.0",
        "deviations": user_deviations,
        "steps": step_previews,
    }
    return title, source_url, project_name, payload_preview, payload_raw


# Hard cap on cached entries per session, applied at flush time. Average
# sessions never hit this; long-running ones won't bloat the row.
_EXTERNAL_PROTOCOL_CACHE_MAX = 50


def _trim_external_protocol_cache(cache: dict[str, str]) -> dict[str, str]:
    """Drop the oldest entries when the cache exceeds the per-session cap.

    Python dicts preserve insertion order, and Postgres JSONB round-trips
    that order, so the first keys are the oldest fetches.
    """
    if len(cache) <= _EXTERNAL_PROTOCOL_CACHE_MAX:
        return cache
    overflow = len(cache) - _EXTERNAL_PROTOCOL_CACHE_MAX
    keys = list(cache.keys())
    for k in keys[:overflow]:
        cache.pop(k, None)
    return cache


def _apply_edited_steps(
    cached_payload: str,
    edited_steps: list[dict[str, Any]] | None,
    session_pk: UUID,
) -> str:
    """Rewrite the cached payload's ``steps`` with the user's edited list.

    Returns the original cached string when there's nothing to apply or the
    payload doesn't parse — the approval tool then sees the unedited
    procedure, which is the safe fallback.
    """
    if not edited_steps:
        return cached_payload
    try:
        parsed = json.loads(cached_payload)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "Could not parse cached payload to apply edited_steps for "
            "session %s; falling back to original.",
            session_pk,
        )
        return cached_payload
    if not isinstance(parsed, dict):
        return cached_payload
    parsed["steps"] = [
        {
            "text": str(s.get("text", "")),
            "duration_min": s.get("duration_min"),
        }
        for s in edited_steps
        if isinstance(s, dict) and str(s.get("text", "")).strip()
    ]
    return json.dumps(parsed)


async def send_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
    skill_id: str | None = None,
    current_route: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat turn as SSE-shaped event dicts. See module docstring.

    ``skill_id`` (F-0089) activates a server-side skill by prepending
    ``[skill:<id>] `` to the **model-visible** user content only. The
    DB-persisted ChatMessage keeps the clean ``user_content`` so the user
    sees what they typed in the thread history. The prefix tells the chat
    agent (via the dispatch rule in its system prompt) to load the matching
    SKILL.md and follow its recipe.

    ``current_route`` (F-0089) adds page-context awareness by prepending
    ``[page:<route>] `` to the model-visible content only (the persisted
    message stays clean). This lets the chat agent and the ``app_help``
    subagent pick the help page that covers the user's current surface
    without requiring the user to describe where they are in the app.
    When both ``skill_id`` and ``current_route`` are set, ``[skill:<id>]``
    comes first so the "message begins with [skill:...]" dispatch rule
    continues to hold.
    """
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    # Compose the model-visible content. The clean ``user_content`` is what
    # gets persisted; ``model_visible_content`` is what the agent.run prompt
    # carries. Markers reach the LLM and land in the serialized history for
    # turn N+1. The [skill:<id>] marker stays first so the chat-agent prompt
    # rule "if a message begins with [skill:...]" still holds when a
    # [page:<route>] marker (F-0089) is also present.
    markers = ""
    if skill_id:
        markers += f"[skill:{skill_id}] "
    if current_route:
        markers += f"[page:{current_route}] "
    model_visible_content = f"{markers}{user_content}" if markers else user_content

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

    # BUG-005: stamp the turn heartbeat in the SAME commit as the user message
    # so a poll landing between "user message persisted" and "agent started"
    # sees turn_in_progress=true rather than a false "interrupted" banner.
    session.active_turn_heartbeat_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(user_msg)

    # Snapshot the user_msg fields now — the request session can be expired or
    # detached by the time the agent run finishes (60s+), and pydantic ORM
    # validation would trigger lazy I/O outside an async greenlet.
    user_msg_payload = ChatMessageResponse.model_validate(user_msg).model_dump(
        mode="json"
    )

    # ── 2. Build CompactionState + ChatDeps ──────────────────────────────────
    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session_org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )
    # ChatDeps is per-request, so the external_protocol_cache populated by the
    # subagent in an earlier turn is gone by the time the user confirms and the
    # parent agent calls create_protocol_from_external_source. Load the
    # session's persisted cache (stored out-of-band from ai_message_history
    # because pydantic-ai compaction elides large tool returns).
    deps.external_protocol_cache = dict(session.external_protocol_cache or {})

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
    # The turn heartbeat is refreshed for the whole agent run so a slow turn
    # keeps reporting turn_in_progress=true to the poll-recovery path (BUG-005).
    async with turn_heartbeat(session_pk):
        run_task: asyncio.Task = asyncio.create_task(
            agent.run(
                model_visible_content,
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
        except ModelHTTPError as exc:
            # The model provider (e.g. Ollama Cloud) returned an HTTP error.
            # The OpenAI client already retried transient 5xx/429 twice;
            # reaching here means the provider is sustainedly unavailable. Tell
            # the user it is transient and retryable so an outage is not
            # mistaken for a bug.
            logger.warning(
                "Chat agent run hit upstream model error %s for session %s",
                exc.status_code,
                session_pk,
            )
            if not run_task.done():
                run_task.cancel()
            # BUG-005: clear the heartbeat explicitly — the error path has no
            # writer UPDATE to fold the clear into.
            await clear_turn_heartbeat(session_pk)
            transient = exc.status_code in (429, 500, 502, 503, 504)
            yield {
                "type": "error",
                "detail": (
                    "The AI service is temporarily unavailable. Please send "
                    "your message again in a moment."
                    if transient
                    else "Failed to generate AI response"
                ),
            }
            return
        except Exception:
            logger.exception("Chat agent run failed for session %s", session_pk)
            if not run_task.done():
                run_task.cancel()
            # BUG-005: the error path has no writer UPDATE to fold the clear
            # into — clear the heartbeat explicitly so the orphaned turn does
            # not keep reporting turn_in_progress=true until the 60s expiry.
            await clear_turn_heartbeat(session_pk)
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
        (
            title,
            source_url,
            _project_name,
            payload_preview,
            payload_raw,
        ) = _build_approval_payload_preview(pending_approval_call, deps)

        # Refuse to render an empty approval card. This happens when the LLM
        # synthesizes a source_url that the subagent never fetched (cache
        # miss + ambiguous fallback). Better to surface a clear error so the
        # user re-prompts than to show a 0-step card the user can't act on.
        if payload_preview.get("step_count", 0) == 0:
            logger.warning(
                "Refusing to emit approval_required for source_url=%r "
                "because cached payload has 0 steps. Cache keys: %s",
                source_url,
                list(deps.external_protocol_cache.keys()),
            )
            # BUG-005: early return — no writer UPDATE downstream, so clear here.
            await clear_turn_heartbeat(session_pk)
            yield {
                "type": "error",
                "detail": (
                    f"I tried to import {title or source_url!r} but couldn't "
                    "find any steps in the cached source. The URL probably "
                    "wasn't one of the candidates I fetched — ask me to "
                    "search OpenWetWare for that protocol first."
                ),
                "error_code": "EXTERNAL_PROTOCOL_EMPTY",
            }
            return

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
                # Persist the cached payload so resume can rehydrate
                # deps.external_protocol_cache and the tool body can return it.
                "payload_json": payload_raw,
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
                .values(
                    ai_message_history=history_payload,
                    external_protocol_cache=_trim_external_protocol_cache(
                        deps.external_protocol_cache
                    ),
                    # BUG-005: clear the heartbeat — the turn is suspended
                    # awaiting human approval, not in progress.
                    active_turn_heartbeat_at=None,
                )
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
            .values(
                ai_message_history=history_payload,
                external_protocol_cache=_trim_external_protocol_cache(
                    deps.external_protocol_cache
                ),
                # BUG-005: clear the heartbeat atomically with the assistant
                # message landing — the turn is complete.
                active_turn_heartbeat_at=None,
            )
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
        "user_message": user_msg_payload,
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
    edited_steps: list[dict[str, Any]] | None = None,
    deviations: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Resume a chat turn that paused on a DeferredToolRequests gate.

    Persists the user's approval/rejection as a USER ChatMessage, then resumes
    ``agent.run`` with ``deferred_tool_results=DeferredToolResults(...)`` and
    the session's existing message history. The placeholder ASSISTANT row is
    updated in place with the final content — no duplicate is created.

    On approval, the frontend may pass ``edited_steps`` (user's inline
    edits to the procedure) and ``deviations`` (a human-readable diff like
    ``["Removed step: spin 5 min"]``). We rewrite the cached payload's
    ``steps`` with the edited list and stash ``deviations`` on
    ``deps.user_deviations`` so the approval tool body folds them into its
    sentinel + audit row. Both are ignored on rejection.
    """
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    if approved:
        decision_text = "Approved external protocol conversion."
    else:
        decision_text = "Rejected the external protocol conversion."
    user_msg = ChatMessage(
        session_id=session_pk,
        role=ChatMessageRole.USER,
        content=decision_text,
    )
    db.add(user_msg)
    await db.flush()
    # BUG-005: stamp the turn heartbeat in the same commit as the decision
    # message so the resume turn reports turn_in_progress=true while it runs.
    session.active_turn_heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user_msg)

    user_msg_payload = ChatMessageResponse.model_validate(user_msg).model_dump(
        mode="json"
    )

    state = CompactionState()
    deps = ChatDeps(
        db=db,
        org_id=session_org_id,
        user_id=user_id,
        is_org_admin=is_org_admin,
    )

    # Seed from the session's persisted cache first, then layer the placeholder
    # metadata on top (it may contain the user's edited steps applied below).
    deps.external_protocol_cache = dict(session.external_protocol_cache or {})

    # Rehydrate the server-side payload cache from the placeholder metadata so
    # the approval tool body (which runs during this resume) finds the payload
    # that was originally fetched in the initial turn.
    pending = (placeholder.metadata_ or {}).get("pending_approval") or {}
    cached_url = pending.get("source_url")
    cached_payload = pending.get("payload_json")
    if cached_url and cached_payload:
        payload_for_cache = _apply_edited_steps(
            cached_payload,
            edited_steps if approved else None,
            session_pk,
        )
        deps.external_protocol_cache[cached_url] = payload_for_cache

    if approved and deviations:
        deps.user_deviations = [
            d.strip() for d in deviations if isinstance(d, str) and d.strip()
        ]

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

    async with turn_heartbeat(session_pk):
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
        except ModelHTTPError as exc:
            logger.warning(
                "Chat agent resume hit upstream model error %s for session %s",
                exc.status_code,
                session_pk,
            )
            if not run_task.done():
                run_task.cancel()
            # BUG-005: error path has no writer UPDATE — clear explicitly.
            await clear_turn_heartbeat(session_pk)
            transient = exc.status_code in (429, 500, 502, 503, 504)
            yield {
                "type": "error",
                "detail": (
                    "The AI service is temporarily unavailable. Please try the "
                    "approval again in a moment."
                    if transient
                    else "Failed to resume AI response"
                ),
            }
            return
        except Exception:
            logger.exception("Chat agent resume failed for session %s", session_pk)
            if not run_task.done():
                run_task.cancel()
            # BUG-005: error path has no writer UPDATE — clear explicitly.
            await clear_turn_heartbeat(session_pk)
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
            .values(
                ai_message_history=history_payload,
                external_protocol_cache=_trim_external_protocol_cache(
                    deps.external_protocol_cache
                ),
                # BUG-005: the assistant reply has landed — the turn is over.
                active_turn_heartbeat_at=None,
            )
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
        "user_message": user_msg_payload,
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
