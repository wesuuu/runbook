# F-0083 Chat Tool-Call Indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the chat agent runs tools mid-turn, swap the static 3-dot indicator for a short live label naming the active tool ("Searching documents…"); fall back to dots when no tool is in flight.

**Architecture:** Convert the chat send-message endpoint to SSE. Hook pydantic-ai 1.75's `event_stream_handler` to emit `tool_start`/`tool_end` events as `FunctionToolCallEvent` / `FunctionToolResultEvent` fire, then a final `done` event carrying the existing `ChatCompletionResponse` payload. Each subagent's `tools.py` declares a `TOOL_LABELS` dict at the top of the file; a shared `resolve_tool_label()` helper aggregates them; the resolved label rides on the SSE event so the frontend renders it verbatim.

**Tech Stack:** Python 3.13, FastAPI, pydantic-ai 1.75, subagents-pydantic-ai 0.2.2. Frontend: Svelte 5 (runes), fetch streaming + ReadableStream + TextDecoder, Vitest.

**Spec:** `docs/superpowers/specs/2026-05-11-f-0083-chat-tool-indicator-design.md`

---

## File Structure

**Backend — create:**
- `backend/app/services/ai/tool_labels.py` — aggregates each subagent's `TOOL_LABELS` into `resolve_tool_label(name)` with a "Working…" fallback.
- `backend/tests/unit/test_tool_labels.py` — invariant: every audited tool name resolves to a non-fallback label.
- `backend/tests/unit/test_send_message_streaming.py` — async-generator behavior, event ordering, error path.
- `backend/tests/integration/test_chat_stream_endpoint.py` — SSE wire-format integration test.

**Backend — modify:**
- `backend/app/services/ai/subagents/research_library/tools.py` — add `TOOL_LABELS` constant at module top.
- `backend/app/services/ai/subagents/protocol_builder/tools.py` — add `TOOL_LABELS` constant at module top.
- `backend/app/services/ai/send_message.py` — `send_message` becomes `send_message_streaming() -> AsyncIterator[dict]`. The synchronous `send_message` is removed; the only caller is the new SSE endpoint.
- `backend/app/api/endpoints/chat.py:215-272` — replace `send_chat_message` POST with `stream_chat_message` returning `StreamingResponse(media_type="text/event-stream")`.
- `backend/tests/unit/test_send_message.py` — deleted (replaced by streaming version).
- `backend/tests/integration/test_chat_api.py` — message-send tests updated to consume SSE.

**Frontend — create:**
- `frontend/src/lib/ai/sse-stream.ts` — `streamSse(endpoint, body, callbacks)` helper using fetch + ReadableStream + TextDecoder, line-buffered.
- `frontend/src/lib/components/ai/ThinkingIndicator.svelte` — renders `{currentToolLabel} + dot wiggle` or dots-only when null.
- `frontend/src/lib/chat-store.test.ts` — streaming-store unit test (mocked fetch with ReadableStream).
- `frontend/src/lib/ai/sse-stream.test.ts` — SSE line buffering unit test.

**Frontend — modify:**
- `frontend/src/lib/chat-store.svelte.ts:186-269` — `sendMessage` uses `streamSse`; new exported `currentToolLabel` state.
- `frontend/src/routes/chat/+page.svelte:349-359` — replace inline indicator with `<ThinkingIndicator />`.

---

## Task 1: Add TOOL_LABELS to research_library/tools.py

**Files:**
- Modify: `backend/app/services/ai/subagents/research_library/tools.py` (top of file, after imports)

- [ ] **Step 1: Identify the exact tool names this subagent audits**

Confirm the four `ctx.deps.tool_calls.append({"tool": "..."})` sites at lines 116, 194, 228, 281 use tool names: `search_documents`, `read_section`, `list_documents`. (`read_section` appears twice — same tool, two call sites.)

Run: `grep -hE '"tool":\s*"[a-z_]+"' backend/app/services/ai/subagents/research_library/tools.py | sort -u`
Expected output:
```
            "tool": "list_documents",
            "tool": "read_section",
                "tool": "read_section",
            "tool": "search_documents",
```

- [ ] **Step 2: Add the TOOL_LABELS constant**

Insert at the top of the file, after the imports and before the first tool function. The exact placement is right after the last `import` / `from` line.

```python
# Human-readable labels for each tool, shown live in the chat thinking
# indicator while the tool is in flight (F-0083). Adding a new tool in this
# file MUST also add an entry here -- enforced by
# tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_documents": "Searching documents…",
    "read_section": "Reading document section…",
    "list_documents": "Listing documents…",
}
```

- [ ] **Step 3: Verify the module still imports**

Run: `cd backend && source .venv/bin/activate && python -c "from app.services.ai.subagents.research_library import tools; print(sorted(tools.TOOL_LABELS))"`
Expected: `['list_documents', 'read_section', 'search_documents']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ai/subagents/research_library/tools.py
git commit -m "feat(chat): add TOOL_LABELS for research_library tools"
```

---

## Task 2: Add TOOL_LABELS to protocol_builder/tools.py

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_builder/tools.py` (top of file, after imports)

- [ ] **Step 1: Confirm the exact tool name set**

Run: `grep -hE '"tool":\s*"[a-z_]+"' backend/app/services/ai/subagents/protocol_builder/tools.py | sed -nE 's/.*"tool":\s*"([a-z_]+)".*/\1/p' | sort -u`
Expected (20 names):
```
add_protocol_role
add_protocol_step
create_draft
create_protocol
create_unit_op
elevate_unit_op_scope
get_protocol
list_projects
list_protocol_roles
list_protocols
list_unit_ops
remove_protocol_role
remove_protocol_step
reorder_protocol_steps
replace_step_unit_op
update_protocol_metadata
update_protocol_role
update_protocol_step
update_unit_op
validate_protocol
```

- [ ] **Step 2: Add the TOOL_LABELS constant**

Insert at the top of the file, immediately after the imports.

```python
# Human-readable labels for each tool, shown live in the chat thinking
# indicator while the tool is in flight (F-0083). Adding a new tool in this
# file MUST also add an entry here -- enforced by
# tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    # Discovery / read
    "list_protocols": "Listing protocols…",
    "get_protocol": "Reading the protocol…",
    "list_projects": "Listing projects…",
    "list_unit_ops": "Listing unit ops…",
    "list_protocol_roles": "Listing protocol roles…",
    # Draft / metadata
    "create_draft": "Creating a draft…",
    "create_protocol": "Drafting a protocol…",
    "update_protocol_metadata": "Updating protocol details…",
    "validate_protocol": "Validating the protocol…",
    # Steps
    "add_protocol_step": "Adding a step…",
    "update_protocol_step": "Updating a step…",
    "remove_protocol_step": "Removing a step…",
    "reorder_protocol_steps": "Reordering steps…",
    "replace_step_unit_op": "Swapping a step's unit op…",
    # Roles
    "add_protocol_role": "Adding a role…",
    "update_protocol_role": "Updating a role…",
    "remove_protocol_role": "Removing a role…",
    # Unit ops
    "create_unit_op": "Creating a unit op…",
    "update_unit_op": "Updating a unit op…",
    "elevate_unit_op_scope": "Promoting a unit op…",
}
```

- [ ] **Step 3: Verify**

Run: `cd backend && source .venv/bin/activate && python -c "from app.services.ai.subagents.protocol_builder import tools; print(len(tools.TOOL_LABELS))"`
Expected: `20`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_builder/tools.py
git commit -m "feat(chat): add TOOL_LABELS for protocol_builder tools"
```

---

## Task 3: Central tool-label registry + coverage test

**Files:**
- Create: `backend/app/services/ai/tool_labels.py`
- Create: `backend/tests/unit/test_tool_labels.py`

- [ ] **Step 1: Write the failing coverage test**

Create `backend/tests/unit/test_tool_labels.py`:

```python
"""Invariants for the chat tool-label registry (F-0083).

Ensures every tool name audited via ctx.deps.tool_calls.append({"tool": ...})
under app/services/ai/subagents/ has a corresponding TOOL_LABELS entry and
resolves to a non-fallback human label.
"""
import re
from pathlib import Path

import pytest

from app.services.ai.tool_labels import FALLBACK_LABEL, resolve_tool_label

SUBAGENTS_DIR = Path(__file__).resolve().parents[2] / "app" / "services" / "ai" / "subagents"
_TOOL_AUDIT_RE = re.compile(r'"tool"\s*:\s*"([a-z_][a-z0-9_]*)"')


def _audited_tool_names() -> set[str]:
    names: set[str] = set()
    for tools_py in SUBAGENTS_DIR.glob("*/tools.py"):
        names.update(_TOOL_AUDIT_RE.findall(tools_py.read_text()))
    return names


def test_audited_tools_discovered():
    """Sanity: the scan finds the known tools."""
    names = _audited_tool_names()
    assert "search_documents" in names
    assert "create_protocol" in names
    assert len(names) >= 20


@pytest.mark.parametrize("tool_name", sorted(_audited_tool_names()))
def test_every_audited_tool_has_a_label(tool_name: str):
    """Each audited tool must resolve to a non-fallback label."""
    label = resolve_tool_label(tool_name)
    assert label != FALLBACK_LABEL, (
        f"Tool {tool_name!r} has no TOOL_LABELS entry. Add it to the "
        f"subagent's tools.py TOOL_LABELS dict."
    )
    assert label.endswith("…"), f"Label for {tool_name!r} should end with an ellipsis"


def test_subagent_dispatch_tools_have_labels():
    """Auto-injected subagent toolset (task/check_task/answer_subagent) is labeled."""
    assert resolve_tool_label("task") != FALLBACK_LABEL
    assert resolve_tool_label("check_task") != FALLBACK_LABEL
    assert resolve_tool_label("answer_subagent") != FALLBACK_LABEL


def test_unknown_tool_falls_back():
    assert resolve_tool_label("nonexistent_tool_xyz") == FALLBACK_LABEL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_tool_labels.py -v`
Expected: ImportError on `app.services.ai.tool_labels` (module doesn't exist yet).

- [ ] **Step 3: Implement the registry**

Create `backend/app/services/ai/tool_labels.py`:

```python
"""Central resolver for chat-agent tool display labels (F-0083).

Each subagent's tools.py exposes its own TOOL_LABELS dict next to the tool
functions. This module aggregates them and exposes a single lookup, with a
hardcoded entry for the auto-injected subagent-dispatch toolset (task,
check_task, answer_subagent) from subagents-pydantic-ai.
"""

from app.services.ai.subagents.protocol_builder.tools import (
    TOOL_LABELS as _PROTOCOL_BUILDER_LABELS,
)
from app.services.ai.subagents.research_library.tools import (
    TOOL_LABELS as _RESEARCH_LIBRARY_LABELS,
)

FALLBACK_LABEL = "Working…"

# Auto-injected by subagents-pydantic-ai capability — fired on the PARENT
# agent when it dispatches to a subagent or receives a subagent answer.
_DISPATCH_LABELS: dict[str, str] = {
    "task": "Thinking…",
    "check_task": "Checking progress…",
    "answer_subagent": "Wrapping up…",
}

_ALL_LABELS: dict[str, str] = {
    **_RESEARCH_LIBRARY_LABELS,
    **_PROTOCOL_BUILDER_LABELS,
    **_DISPATCH_LABELS,
}


def resolve_tool_label(tool_name: str) -> str:
    """Return the human-readable label for a tool name.

    Falls back to FALLBACK_LABEL for unknown tools so the indicator still
    updates; the coverage test in tests/unit/test_tool_labels.py prevents
    real tools from hitting this path.
    """
    return _ALL_LABELS.get(tool_name, FALLBACK_LABEL)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_tool_labels.py -v`
Expected: all tests PASS (23+ parametrized cases for individual tools, plus the four named ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/tool_labels.py backend/tests/unit/test_tool_labels.py
git commit -m "feat(chat): add resolve_tool_label() registry + coverage test"
```

---

## Task 4: Refactor send_message to async generator

**Files:**
- Modify: `backend/app/services/ai/send_message.py` (full rewrite of the function)
- Create: `backend/tests/unit/test_send_message_streaming.py`
- Delete: `backend/tests/unit/test_send_message.py`

- [ ] **Step 1: Write the failing streaming-generator test**

Create `backend/tests/unit/test_send_message_streaming.py`:

```python
"""Tests for send_message_streaming (F-0083)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat import ChatSession
from app.services.ai.runtime.compaction import CompactionState


def _make_session(**kwargs):
    s = MagicMock(spec=ChatSession)
    s.id = uuid.uuid4()
    s.org_id = uuid.uuid4()
    s.title = kwargs.get("title", "New Chat")
    s.ai_message_history = kwargs.get("ai_message_history", None)
    return s


async def _fake_run_with_events(events_to_emit):
    """Helper: build a fake agent.run that invokes event_stream_handler with the
    given pydantic-ai events, then returns a result mock."""

    async def _run(*args, event_stream_handler=None, **kwargs):
        if event_stream_handler is not None:
            async def _gen():
                for ev in events_to_emit:
                    yield ev
            # pydantic-ai passes (ctx, stream) - we just need the second arg.
            await event_stream_handler(MagicMock(), _gen())
        result = MagicMock()
        result.output = "ok"
        result.all_messages.return_value = []
        return result

    return _run


def _tool_call_event(tool_name: str, call_id: str = "c1"):
    from pydantic_ai.messages import FunctionToolCallEvent, ToolCallPart

    return FunctionToolCallEvent(
        part=ToolCallPart(tool_name=tool_name, args="{}", tool_call_id=call_id),
    )


def _tool_result_event(tool_name: str, call_id: str = "c1"):
    from pydantic_ai.messages import FunctionToolResultEvent, ToolReturnPart

    return FunctionToolResultEvent(
        result=ToolReturnPart(
            tool_name=tool_name, content="ok", tool_call_id=call_id,
        ),
    )


@pytest.mark.asyncio
async def test_emits_tool_start_end_then_done():
    """A turn with one tool call emits tool_start, tool_end, done in order."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    session = _make_session()

    events = [
        _tool_call_event("search_documents"),
        _tool_result_event("search_documents"),
    ]
    run_fn = await _fake_run_with_events(events)

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=CompactionState(),
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter"),
        patch("app.services.ai.send_message.sanitize_output", return_value="ok"),
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent

        emitted = [
            ev async for ev in send_message_streaming(
                db, session, "hi", user_id=uuid.uuid4(), is_org_admin=False,
            )
        ]

    types = [e["type"] for e in emitted]
    assert types == ["tool_start", "tool_end", "done"], emitted
    assert emitted[0]["tool"] == "search_documents"
    assert emitted[0]["label"] == "Searching documents…"
    assert emitted[1]["tool"] == "search_documents"
    done = emitted[2]
    assert "user_message" in done
    assert "assistant_message" in done
    assert "sources" in done


@pytest.mark.asyncio
async def test_done_only_when_no_tool_calls():
    """Pure LLM turn emits a single done event."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    session = _make_session()

    run_fn = await _fake_run_with_events([])

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=CompactionState(),
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter"),
        patch("app.services.ai.send_message.sanitize_output", return_value="ok"),
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent

        emitted = [
            ev async for ev in send_message_streaming(
                db, session, "hi", user_id=uuid.uuid4(), is_org_admin=False,
            )
        ]

    assert [e["type"] for e in emitted] == ["done"]


@pytest.mark.asyncio
async def test_agent_error_yields_error_event():
    """A raised exception from agent.run is converted to an error event."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    session = _make_session()

    async def _bad_run(*a, **kw):
        raise RuntimeError("model exploded")

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=CompactionState(),
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter"),
    ):
        fake_agent = MagicMock()
        fake_agent.run = _bad_run
        mock_build.return_value = fake_agent

        emitted = [
            ev async for ev in send_message_streaming(
                db, session, "hi", user_id=uuid.uuid4(), is_org_admin=False,
            )
        ]

    assert emitted[-1]["type"] == "error"
    assert "detail" in emitted[-1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_send_message_streaming.py -v`
Expected: ImportError on `send_message_streaming`.

- [ ] **Step 3: Rewrite send_message.py**

Replace the entire file contents:

```python
"""send_message_streaming — orchestrates a chat turn as an async event stream.

Yields a sequence of dicts:
  {"type": "tool_start", "tool": <name>, "label": <human label>}
  {"type": "tool_end",   "tool": <name>}
  ... (repeats per tool) ...
  {"type": "done", "user_message": {...}, "assistant_message": {...}, "sources": [...]}

Or, on failure:
  {"type": "error", "detail": <str>}

The caller (chat SSE endpoint) is responsible for serializing each dict as
an SSE `data:` line.
"""

import asyncio
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
)
from sqlalchemy.ext.asyncio import AsyncSession

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
    # ── 1. Persist user message ──────────────────────────────────────────────
    user_msg = ChatMessage(
        session_id=session.id,
        role=ChatMessageRole.USER,
        content=user_content,
    )
    db.add(user_msg)
    await db.flush()

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

    # ── 4. Event bridge: pydantic-ai event_stream_handler → asyncio.Queue ────
    # The handler is called once per agent "node" with an async-iterable of
    # events. We forward FunctionTool{Call,Result}Event onto a queue that the
    # outer generator drains concurrently with agent.run.
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _handler(_ctx, stream):
        async for event in stream:
            if isinstance(event, FunctionToolCallEvent):
                name = event.part.tool_name
                await event_queue.put({
                    "type": "tool_start",
                    "tool": name,
                    "label": resolve_tool_label(name),
                })
            elif isinstance(event, FunctionToolResultEvent):
                name = event.result.tool_name
                await event_queue.put({"type": "tool_end", "tool": name})
            # other event kinds intentionally ignored

    # ── 5. Run the agent in a background task; drain the queue ───────────────
    run_task: asyncio.Task = asyncio.create_task(
        agent.run(
            user_content,
            deps=deps,
            message_history=message_history,
            event_stream_handler=_handler,
        )
    )

    try:
        while not run_task.done() or not event_queue.empty():
            queue_get = asyncio.create_task(event_queue.get())
            done, _pending = await asyncio.wait(
                {queue_get, run_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_get in done:
                ev = queue_get.result()
                if ev is not None:
                    yield ev
            else:
                queue_get.cancel()
        result = await run_task
    except Exception as exc:
        logger.exception("Chat agent run failed for session %s", session.id)
        if not run_task.done():
            run_task.cancel()
        yield {"type": "error", "detail": "Failed to generate AI response"}
        return

    # ── 6. Finalize (mirrors the pre-streaming send_message tail) ────────────
    if state.triggered and state.summary_text:
        summary_msg = ChatMessage(
            session_id=session.id,
            role=ChatMessageRole.SUMMARY,
            content=state.summary_text,
            metadata_=state.audit_metadata(),
        )
        db.add(summary_msg)
        await db.flush()

    session.ai_message_history = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )
    await db.flush()

    seen_chunk_ids: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for source in deps.sources:
        if source.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(source.chunk_id)
            unique_sources.append(source)

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
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

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
```

The `ChatMessageResponse` schema (alias for `user_message` / `assistant_message` in `ChatCompletionResponse`) lives at `backend/app/schemas/chat.py:27`.

- [ ] **Step 4: Delete the old test**

```bash
git rm backend/tests/unit/test_send_message.py
```

- [ ] **Step 5: Run streaming tests to verify pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_send_message_streaming.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Run the whole AI unit-test slice to verify no other tests broke**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_ai_*.py tests/unit/test_chat_*.py tests/unit/test_tool_labels.py tests/unit/test_send_message_streaming.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/tests/unit/test_send_message_streaming.py backend/tests/unit/test_send_message.py
git commit -m "refactor(chat): make send_message a streaming async generator (F-0083)"
```

---

## Task 5: Replace chat POST endpoint with SSE streaming

**Files:**
- Modify: `backend/app/api/endpoints/chat.py:215-272`
- Create: `backend/tests/integration/test_chat_stream_endpoint.py`
- Modify: `backend/tests/integration/test_chat_api.py` (any test that POSTs `/chat/sessions/{id}/messages`)

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_chat_stream_endpoint.py`:

```python
"""Integration test for SSE chat-message endpoint (F-0083)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def _parse_sse_lines(body: str) -> list[dict]:
    """Parse a body of SSE 'data: {json}\\n\\n' frames into a list of dicts."""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


async def _yield_canned_events(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_stream_endpoint_emits_tool_events_then_done(
    client: AsyncClient, auth_headers: dict, chat_session_id: str
):
    """SSE response carries tool_start / tool_end / done in order."""
    canned = [
        {"type": "tool_start", "tool": "search_documents", "label": "Searching documents…"},
        {"type": "tool_end", "tool": "search_documents"},
        {
            "type": "done",
            "user_message": {"id": "u1", "role": "user", "content": "hi"},
            "assistant_message": {"id": "a1", "role": "assistant", "content": "ok"},
            "sources": [],
        },
    ]

    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        return_value=_yield_canned_events(*canned),
    ):
        async with client.stream(
            "POST",
            f"/chat/sessions/{chat_session_id}/messages/stream",
            json={"content": "hi"},
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk

    events = _parse_sse_lines(body)
    assert [e["type"] for e in events] == ["tool_start", "tool_end", "done"]
    assert events[0]["label"] == "Searching documents…"


@pytest.mark.asyncio
async def test_stream_endpoint_404_when_session_missing(
    client: AsyncClient, auth_headers: dict
):
    async with client.stream(
        "POST",
        "/chat/sessions/00000000-0000-0000-0000-000000000000/messages/stream",
        json={"content": "hi"},
        headers=auth_headers,
    ) as resp:
        # Read the body to allow the response to close cleanly.
        await resp.aread()
        assert resp.status_code == 404
```

Note: the `chat_session_id` fixture should already exist in `tests/integration/conftest.py`. If not, look at `test_chat_api.py` for how it creates a session inline; copy that pattern.

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_chat_stream_endpoint.py -v`
Expected: 404 on the new `/messages/stream` route (endpoint not yet implemented).

- [ ] **Step 3: Replace the endpoint**

In `backend/app/api/endpoints/chat.py`, replace the `send_chat_message` function (lines 215-272) with the streaming endpoint:

```python
@router.post("/sessions/{session_id}/messages/stream")
async def stream_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Stream a chat turn as SSE: emits tool_start/tool_end events live and
    a final `done` event carrying user_message, assistant_message, sources.

    See docs/superpowers/specs/2026-05-11-f-0083-chat-tool-indicator-design.md.
    """
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")

    _, org_roles = await _get_user_org(current_user, db)
    is_org_admin = OrgRole.ADMIN.value in org_roles

    async def _sse_iter():
        try:
            async for event in send_message_streaming(
                db,
                session,
                body.content,
                user_id=current_user.id,
                is_org_admin=is_org_admin,
            ):
                yield f"data: {json.dumps(event)}\n\n"
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "Chat stream failed for session %s", session_id
            )
            yield (
                'data: {"type": "error", '
                '"detail": "Failed to generate AI response"}\n\n'
            )

    return StreamingResponse(_sse_iter(), media_type="text/event-stream")
```

Also at the top of the file:

```python
import json

from fastapi.responses import StreamingResponse

from app.services.ai.send_message import send_message_streaming
```

Remove the old `send_chat_message` function and the `from app.services.ai.send_message import send_message` import (replaced by `send_message_streaming`).

- [ ] **Step 4: Update existing integration tests**

In `backend/tests/integration/test_chat_api.py`, find every test that POSTs to `/chat/sessions/{id}/messages` (without `/stream`). For each:

1. Change the URL to `/chat/sessions/{id}/messages/stream`.
2. Use `client.stream("POST", ...)` instead of `client.post(...)`.
3. Read the SSE body, parse `data:` lines, find the `done` event, and assert against `done["user_message"]` / `done["assistant_message"]` / `done["sources"]` instead of `resp.json()`.

Helper to add at the top of the file:

```python
import json

def _drain_sse(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out

def _done(events: list[dict]) -> dict:
    return next(e for e in events if e["type"] == "done")
```

If `ChatCompletionResponse` is no longer imported anywhere, leave the schema in `app/schemas/chat.py` for now (the `done` event payload happens to match the same fields — keeping the schema around documents the contract).

- [ ] **Step 5: Run integration tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_chat_stream_endpoint.py tests/integration/test_chat_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Run full backend suite once**

Run: `cd backend && source .venv/bin/activate && pytest`
Expected: all PASS (no other endpoint references the removed POST).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/chat.py backend/tests/integration/test_chat_stream_endpoint.py backend/tests/integration/test_chat_api.py
git commit -m "feat(chat): SSE streaming endpoint for chat messages (F-0083)"
```

---

## Task 6: Frontend SSE stream reader helper

**Files:**
- Create: `frontend/src/lib/ai/sse-stream.ts`
- Create: `frontend/src/lib/ai/sse-stream.test.ts`

- [ ] **Step 1: Write the failing helper test**

Create `frontend/src/lib/ai/sse-stream.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Stub auth + config before importing the module under test.
vi.mock('$lib/auth.svelte', () => ({ getToken: () => 'TEST_TOKEN' }));
vi.mock('$lib/config', () => ({ API_BASE: 'http://test.local' }));

import { streamSse } from './sse-stream';

function makeReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
    const enc = new TextEncoder();
    let i = 0;
    return new ReadableStream({
        pull(ctrl) {
            if (i >= chunks.length) {
                ctrl.close();
                return;
            }
            ctrl.enqueue(enc.encode(chunks[i++]));
        },
    });
}

describe('streamSse', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('parses single SSE event split across two chunks', async () => {
        const fetchMock = vi.fn(async () => ({
            ok: true,
            status: 200,
            body: makeReadableStream([
                'data: {"type":"tool_st',
                'art","tool":"x","label":"X…"}\n\n',
            ]),
        }) as unknown as Response);
        vi.stubGlobal('fetch', fetchMock);

        const events: unknown[] = [];
        await streamSse('/chat/test', { content: 'hi' }, (e) => events.push(e));

        expect(events).toEqual([
            { type: 'tool_start', tool: 'x', label: 'X…' },
        ]);
    });

    it('parses three events in one chunk', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            status: 200,
            body: makeReadableStream([
                'data: {"type":"tool_start","tool":"a","label":"A…"}\n\n' +
                'data: {"type":"tool_end","tool":"a"}\n\n' +
                'data: {"type":"done"}\n\n',
            ]),
        }) as unknown as Response));

        const events: unknown[] = [];
        await streamSse('/chat/test', {}, (e) => events.push(e));

        expect((events as { type: string }[]).map((e) => e.type)).toEqual([
            'tool_start', 'tool_end', 'done',
        ]);
    });

    it('throws on non-ok response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false,
            status: 500,
            statusText: 'Server Error',
            text: async () => 'boom',
            body: null,
        }) as unknown as Response));

        await expect(
            streamSse('/chat/test', {}, () => {}),
        ).rejects.toThrow(/500/);
    });
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend && npx vitest run src/lib/ai/sse-stream.test.ts`
Expected: module not found.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/lib/ai/sse-stream.ts`:

```typescript
import { getToken } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';

export type SseEvent =
    | { type: 'tool_start'; tool: string; label: string }
    | { type: 'tool_end'; tool: string }
    | { type: 'done'; user_message: unknown; assistant_message: unknown; sources: unknown[] }
    | { type: 'error'; detail: string };

/**
 * POST a JSON body and stream back a `text/event-stream` response.
 * Invokes `onEvent` once per parsed `data:` JSON object, in order.
 *
 * Throws on non-2xx HTTP status. Returns after the server closes the stream.
 */
export async function streamSse(
    endpoint: string,
    body: unknown,
    onEvent: (event: SseEvent) => void,
): Promise<void> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
    };
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(`SSE request failed: ${response.status} ${detail}`);
    }
    if (!response.body) {
        throw new Error('SSE response has no body');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line (\n\n). Split, keep the
        // remainder in the buffer for the next read.
        let sep: number;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            for (const line of frame.split('\n')) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data:')) {
                    const json = trimmed.slice('data:'.length).trim();
                    if (json) {
                        try {
                            onEvent(JSON.parse(json) as SseEvent);
                        } catch (e) {
                            console.error('Bad SSE payload', json, e);
                        }
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/lib/ai/sse-stream.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/ai/sse-stream.ts frontend/src/lib/ai/sse-stream.test.ts
git commit -m "feat(chat): add streamSse() fetch+ReadableStream SSE helper"
```

---

## Task 7: ThinkingIndicator component

**Files:**
- Create: `frontend/src/lib/components/ai/ThinkingIndicator.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/lib/components/ai/ThinkingIndicator.svelte`:

```svelte
<script lang="ts">
    interface Props {
        label: string | null;
    }
    let { label }: Props = $props();
</script>

<div class="flex justify-start">
    <div class="bg-muted/70 rounded-xl px-4 py-3">
        <div class="flex items-center gap-2">
            {#if label}
                <span class="text-sm text-muted-foreground/80">{label}</span>
            {/if}
            <div class="flex items-center gap-1.5">
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 0ms"></div>
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 150ms"></div>
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 300ms"></div>
            </div>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Verify svelte-check passes**

Run: `cd frontend && npx svelte-check --workspace src/lib/components/ai 2>&1 | tail -10`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/ai/ThinkingIndicator.svelte
git commit -m "feat(chat): add ThinkingIndicator component (label + dot wiggle)"
```

---

## Task 8: chat-store switches to streaming

**Files:**
- Modify: `frontend/src/lib/chat-store.svelte.ts:186-269`
- Create: `frontend/src/lib/chat-store.test.ts`

- [ ] **Step 1: Write the failing store test**

Create `frontend/src/lib/chat-store.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({ getToken: () => 'T' }));
vi.mock('$lib/config', () => ({ API_BASE: 'http://test.local' }));

// chat-store imports api for the session creation step; stub the lot.
vi.mock('$lib/api', () => ({
    api: {
        post: vi.fn(),
        get: vi.fn(),
    },
}));

// Import after mocks.
import * as store from './chat-store.svelte';
import * as sse from './ai/sse-stream';

describe('chat-store streaming', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('updates currentToolLabel as tool_start/tool_end events arrive', async () => {
        // Seed an active session so sendMessage skips lazy creation.
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
        });

        // Capture the label value between event dispatches by polling
        // getCurrentToolLabel() synchronously from inside the mock callback.
        const snapshots: (string | null)[] = [];

        vi.spyOn(sse, 'streamSse').mockImplementation(async (_ep, _b, cb) => {
            cb({ type: 'tool_start', tool: 'search_documents', label: 'Searching documents…' });
            snapshots.push(store.getCurrentToolLabel());
            cb({ type: 'tool_end', tool: 'search_documents' });
            snapshots.push(store.getCurrentToolLabel());
            cb({
                type: 'done',
                user_message: { id: 'u1', session_id: 'S1', role: 'user', content: 'hi', metadata_: null, created_at: '2026-01-01' },
                assistant_message: { id: 'a1', session_id: 'S1', role: 'assistant', content: 'ok', metadata_: null, created_at: '2026-01-01' },
                sources: [],
            });
        });

        store.setMessageInput('hi');
        await store.sendMessage();

        expect(snapshots).toEqual(['Searching documents…', null]);
        expect(store.getCurrentToolLabel()).toBeNull(); // cleared in finally
    });

    it('clears currentToolLabel on stream error', async () => {
        store.__test_setActiveSession({ id: 'S1', messages: [], title: 'New Chat' });
        vi.spyOn(sse, 'streamSse').mockImplementation(async () => {
            throw new Error('boom');
        });
        store.setMessageInput('hi');
        await store.sendMessage();
        expect(store.getCurrentToolLabel()).toBeNull();
    });
});
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd frontend && npx vitest run src/lib/chat-store.test.ts`
Expected: `__test_setActiveSession` / `__test_watchToolLabel` / `getCurrentToolLabel` / `streamSse` are undefined.

- [ ] **Step 3: Refactor chat-store.svelte.ts**

In `frontend/src/lib/chat-store.svelte.ts`:

a) Add the new state near the existing `messageInput` / `sending` declarations (around the top of the file):

```typescript
let currentToolLabel = $state<string | null>(null);
let currentToolName: string | null = null; // raw name, for matching tool_start/tool_end

export function getCurrentToolLabel(): string | null {
    return currentToolLabel;
}
```

b) Add a `streamSse` import near the top:

```typescript
import { streamSse, type SseEvent } from '$lib/ai/sse-stream';
```

c) Replace the body of `sendMessage` (lines 186-269) `try { ... } catch { ... } finally { ... }` with the streaming version. The lazy session-creation block stays unchanged. Replace from the `const res = await api.post(...)` block downward with:

```typescript
    try {
        const body: Record<string, string> = { content };
        if (skillId) body.skill_id = skillId;

        currentToolLabel = null;
        currentToolName = null;

        let donePayload: { user_message: ChatMessage; assistant_message: ChatMessage; sources: ChatSourceReference[] } | null = null;
        let errorDetail: string | null = null;

        await streamSse(
            `/chat/sessions/${activeSession.id}/messages/stream`,
            body,
            (event: SseEvent) => {
                if (event.type === 'tool_start') {
                    currentToolName = event.tool;
                    currentToolLabel = event.label;
                } else if (event.type === 'tool_end') {
                    if (currentToolName === event.tool) {
                        currentToolName = null;
                        currentToolLabel = null;
                    }
                } else if (event.type === 'done') {
                    donePayload = event as never;
                } else if (event.type === 'error') {
                    errorDetail = event.detail;
                }
            },
        );

        if (errorDetail || !donePayload) {
            throw new Error(errorDetail ?? 'Stream ended without a result');
        }

        // Replace temp message with real one + assistant response.
        activeSession.messages = [
            ...activeSession.messages.filter((m) => m.id !== tempUserMsg.id),
            donePayload.user_message,
            donePayload.assistant_message,
        ];

        if (donePayload.sources && donePayload.sources.length > 0) {
            activeSources = donePayload.sources;
            sourcePanelOpen = true;
        }

        const idx = sessions.findIndex((s) => s.id === activeSession!.id);
        if (idx !== -1 && sessions[idx].title === 'New Chat') {
            sessions[idx] = { ...sessions[idx], title: content.slice(0, 100) };
            sessions = [...sessions];
        }

        await tick();
        scrollFn?.();
    } catch {
        activeSession.messages = activeSession.messages.filter(
            (m) => m.id !== tempUserMsg.id,
        );
        toast.error('Failed to send message');
    } finally {
        currentToolLabel = null;
        currentToolName = null;
        sending = false;
    }
```

d) Remove the unused import of `ChatCompletionResponseSchema` if nothing else uses it. Keep `ChatSourceReference` and `ChatMessage` imports.

e) Add a single test-only setter at the bottom of the file so unit tests can seed an active session:

```typescript
// --- Test-only export ---
export function __test_setActiveSession(s: ChatSessionDetail | null): void {
    activeSession = s;
}
```

The runtime state mutates via `$state` so calling `getCurrentToolLabel()` synchronously after each callback in the test (see Task 8 Step 1) gives correct, current values without needing a `$effect.root` watcher.

- [ ] **Step 4: Run unit tests**

Run: `cd frontend && npx vitest run src/lib/chat-store.test.ts src/lib/ai/sse-stream.test.ts`
Expected: all PASS.

- [ ] **Step 5: svelte-check the whole frontend**

Run: `cd frontend && npm run check 2>&1 | tail -20`
Expected: 0 errors. Fix any type errors before continuing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/chat-store.svelte.ts frontend/src/lib/chat-store.test.ts
git commit -m "feat(chat): stream chat responses; track currentToolLabel (F-0083)"
```

---

## Task 9: Wire ThinkingIndicator into chat route

**Files:**
- Modify: `frontend/src/routes/chat/+page.svelte:349-359` (inline indicator → component)

- [ ] **Step 1: Import the component and the store getter**

In the `<script>` block of `frontend/src/routes/chat/+page.svelte`, add:

```typescript
import ThinkingIndicator from '$lib/components/ai/ThinkingIndicator.svelte';
import { getCurrentToolLabel } from '$lib/chat-store.svelte';

const currentToolLabel = $derived(getCurrentToolLabel());
```

(Place near the other store-derivation lines.)

- [ ] **Step 2: Replace the inline indicator markup**

Replace lines 349-359 (the `{#if sending} … {/if}` block with the bg-muted/70 + three bouncing dots) with:

```svelte
{#if sending}
    <div in:fade={{ duration: blockDuration() }}>
        <ThinkingIndicator label={currentToolLabel} />
    </div>
{/if}
```

- [ ] **Step 3: svelte-check**

Run: `cd frontend && npm run check 2>&1 | tail -20`
Expected: 0 errors.

- [ ] **Step 4: Build the frontend to confirm everything compiles**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/chat/+page.svelte
git commit -m "feat(chat): show live tool label in chat thinking indicator (F-0083)"
```

---

## Task 10: Run full test suites

**Files:** none

- [ ] **Step 1: Backend**

Run: `cd backend && source .venv/bin/activate && pytest`
Expected: all green.

- [ ] **Step 2: Frontend unit + svelte-check**

Run: `cd frontend && npm run check && npm run test`
Expected: 0 type errors, all unit tests pass.

If either suite is red, fix root cause and re-run before continuing to browser verification. Do NOT proceed if any test is failing.

---

## Task 11: Browser verification

**Files:** none

- [ ] **Step 1: Start dev servers**

In the worktree, use the alternate ports per CLAUDE.md worktree convention:

Backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010`
Frontend: `VITE_API_PORT=8010 npm --prefix frontend run dev -- --port 5183`

Wait for both to be ready (frontend prints "Local: http://localhost:5183/").

- [ ] **Step 2: Hand off to qa-verify**

Launch the qa-verify agent with this brief:

> **Feature:** F-0083 — Show chat agent tool calls in the thinking indicator.
> **What changed:** Chat send-message is now SSE. While the agent runs tools, the 3-dot wiggle is replaced by a short human label (e.g., "Searching documents…", "Drafting a protocol…"); the label disappears as soon as the final assistant message renders. Pure LLM thinking (no tool) keeps the dot wiggle.
> **Login:** localhost:5183, any registered dev user. Dev DB: `localhost:5432`, postgres/postgres/batchrite, any password works in dev.
> **Pages:** /chat
> **Acceptance to test:**
> 1. Ask "find the SOP for cell culture and draft a protocol from it" — confirm labels switch as the agent moves between tools (search_documents → create_draft / add_protocol_step / validate_protocol).
> 2. Indicator label disappears the instant the assistant message text appears.
> 3. Ask "what's 2+2" — only the 3-dot wiggle, never a label.
> 4. Open the Network panel and confirm the request is to `/chat/sessions/{id}/messages/stream` with `text/event-stream` content-type; multiple `data:` frames arrive before the response closes.
> 5. UI audit: label text doesn't overflow, indicator alignment matches the existing chat bubble style, no layout shift between "label + dots" and "dots only" modes.
> Fix any FAIL or POLISH issue before returning.

- [ ] **Step 3: Stop dev servers**

After qa-verify returns clean, kill the background servers.

---

## Task 12: Update project rules (CLAUDE.md / .claude/rules/*)

**Files:**
- Modify: `.claude/rules/backend-ai.md` (small addition under chat agent harness section)

- [ ] **Step 1: Add the SSE+tool-label note**

In `.claude/rules/backend-ai.md`, find the "Tool Functions" section and add a single sentence at the bottom:

> Each subagent's `tools.py` MUST declare a module-level `TOOL_LABELS: dict[str, str]` mapping each tool name to a short human label (ending in "…"); the chat SSE endpoint sends these to the UI as the tool fires. `tests/unit/test_tool_labels.py` enforces full coverage.

- [ ] **Step 2: Prune stale**

Skim the file end-to-end. Anything in this rule file that referenced the old non-streaming chat-message POST? If so, fix or delete. Skip if nothing's affected.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/backend-ai.md
git commit -m "docs(rules): note TOOL_LABELS requirement for chat subagent tools"
```

---

## Task 13: Close out

**Files:** none

- [ ] **Step 1: Present results to the user**

Summary template (fill in actual values from the run):

> F-0083 implemented:
> - Backend: SSE endpoint `POST /chat/sessions/{id}/messages/stream`; `send_message_streaming` async generator using pydantic-ai's `event_stream_handler`; `app/services/ai/tool_labels.py` aggregator.
> - Frontend: `streamSse()` helper, `ThinkingIndicator.svelte`, `chat-store.svelte.ts` consumes the stream and tracks `currentToolLabel`.
> - Tool labels live in each subagent's `tools.py` (`TOOL_LABELS` dict). Coverage test in `tests/unit/test_tool_labels.py` blocks PRs that add tools without labels.
> - Tests: <N> backend, <M> frontend; all pass. Browser verified.

Ask the user to confirm before closing.

- [ ] **Step 2: After user confirmation, close the ClickUp task**

Post a summary comment on F-0083 listing the files changed and tests added, then set status to `complete`.

- [ ] **Step 3: Exit the worktree (action: keep — commits go onto main per worktree convention)**

```
ExitWorktree action=keep
```
