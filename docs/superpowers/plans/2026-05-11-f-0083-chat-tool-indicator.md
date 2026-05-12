# F-0083 Chat Tool-Call Indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the chat agent runs tools mid-turn, swap the static 3-dot indicator for a short live label naming the active tool ("Searching documents…"); fall back to dots when no tool is in flight.

**Architecture:** Convert the chat send-message endpoint to SSE. Hook pydantic-ai 1.75's `event_stream_handler` to emit `tool_start`/`tool_end` events as `FunctionToolCallEvent` / `FunctionToolResultEvent` fire, then a final `done` event carrying the existing `ChatCompletionResponse` payload. Each subagent's `tools.py` declares a `TOOL_LABELS` dict at the top of the file; a shared `resolve_tool_label()` helper aggregates them; the resolved label rides on the SSE event so the frontend renders it verbatim.

**Tech Stack:** Python 3.13, FastAPI, pydantic-ai 1.75, subagents-pydantic-ai 0.2.2. Frontend: Svelte 5 (runes), fetch streaming + ReadableStream + TextDecoder, Vitest.

**Spec:** `docs/superpowers/specs/2026-05-11-f-0083-chat-tool-indicator-design.md`

---

## Rebase context (post-`main` merge)

The worktree was rebased onto `main` after these landed; the plan accounts for them:

- **TD-0086 subagent split.** `protocol_builder` is now legacy (unwired in `chat_agent.py`). The active subagents are `research_library`, `protocol_creator`, `protocol_editor`, `run_planner`. Protocol tools (21 of them — adds `set_node_position`) live in `backend/app/services/ai/subagents/shared/protocols/tools.py` and are imported by both `protocol_creator/config.py` and `protocol_editor/config.py`. The legacy `subagents/protocol_builder/` package stays on disk but is **excluded** from the tool-label scan.
- **Chat resilience (`d562655`).** `send_message()` now commits the user message **before** the LLM call (so a slow/failed tool can't poison the SQLAlchemy session) and persists the assistant message + summary + `ai_message_history` on a **fresh `AsyncSessionLocal()` writer session**. The streaming rewrite must preserve both invariants — the `done` event must only fire after the writer commits.
- **Chat-store recovery polling.** `frontend/src/lib/chat-store.svelte.ts` now polls `/chat/sessions/{id}` after a refresh during a slow turn (`maybeStartAwaitingPoll` / `stalePendingMessage` / `retryStalePending`). Streaming covers the *active* turn; polling covers *refresh-during-LLM* recovery. Both code paths must coexist after this PR.
- **Indicator block.** The 3-dot wiggle in `frontend/src/routes/chat/+page.svelte` now lives at lines **352-362** behind `{#if sending && !stalePending}` (the stale-pending warning is rendered separately). Our `ThinkingIndicator` swap goes inside that same guard.
- **Tool name fix-up.** The research_library tool is `read_section` (not `read_document_section`).

---

## File Structure

**Backend — create:**
- `backend/app/services/ai/tool_labels.py` — aggregates each subagent's `TOOL_LABELS` into `resolve_tool_label(name)` with a "Working…" fallback.
- `backend/tests/unit/test_tool_labels.py` — invariant: every audited tool name resolves to a non-fallback label.
- `backend/tests/unit/test_send_message_streaming.py` — async-generator behavior, event ordering, error path.
- `backend/tests/integration/test_chat_stream_endpoint.py` — SSE wire-format integration test.

**Backend — modify:**
- `backend/app/services/ai/subagents/research_library/tools.py` — add `TOOL_LABELS` constant at module top.
- `backend/app/services/ai/subagents/shared/protocols/tools.py` — add `TOOL_LABELS` constant at module top (covers protocol_creator + protocol_editor).
- `backend/app/services/ai/send_message.py` — `send_message` becomes `send_message_streaming() -> AsyncIterator[dict]`. Preserves the rebased resilience pattern (commit user msg early, fresh writer for assistant msg). The synchronous `send_message` is removed; the only caller is the new SSE endpoint.
- `backend/app/api/endpoints/chat.py:216-310` — replace `send_chat_message` POST with `stream_chat_message` returning `StreamingResponse(media_type="text/event-stream")`. Preserves the forensic ERROR-row write on failure (currently rendered as JSONResponse 500; re-implemented as an `error` SSE event with `error_code`).
- `backend/tests/unit/test_send_message.py` — deleted (replaced by streaming version).
- `backend/tests/integration/test_chat_api.py` — message-send tests updated to consume SSE.

**Frontend — create:**
- `frontend/src/lib/ai/sse-stream.ts` — `streamSse(endpoint, body, onEvent)` helper using fetch + ReadableStream + TextDecoder, line-buffered.
- `frontend/src/lib/components/ai/ThinkingIndicator.svelte` — renders `{currentToolLabel} + dot wiggle` or dots-only when null.
- `frontend/src/lib/chat-store.test.ts` — streaming-store unit test (mocked fetch with ReadableStream).
- `frontend/src/lib/ai/sse-stream.test.ts` — SSE line buffering unit test.

**Frontend — modify:**
- `frontend/src/lib/chat-store.svelte.ts:300-392` — `sendMessage` uses `streamSse` instead of `api.post`; new exported `currentToolLabel` state. **All existing polling / stalePending logic stays untouched.**
- `frontend/src/routes/chat/+page.svelte:352-362` — replace the inline three-dot block with `<ThinkingIndicator label={currentToolLabel} />`, keeping the `{#if sending && !stalePending}` guard.

---

## Task 1: Add TOOL_LABELS to research_library/tools.py

**Files:**
- Modify: `backend/app/services/ai/subagents/research_library/tools.py` (top of file, after imports)

- [ ] **Step 1: Identify the exact tool names this subagent audits**

Confirm the four `ctx.deps.tool_calls.append({"tool": "..."})` sites use tool names: `search_documents`, `read_section`, `list_documents`. (`read_section` appears twice — same tool, two call sites.)

Run: `grep -hE '"tool":\s*"[a-z_]+"' backend/app/services/ai/subagents/research_library/tools.py | sed -nE 's/.*"tool":\s*"([a-z_]+)".*/\1/p' | sort -u`
Expected:
```
list_documents
read_section
search_documents
```

- [ ] **Step 2: Add the TOOL_LABELS constant**

Insert at the top of the file, after the imports and before the first tool function.

```python
# Human-readable labels for each tool, shown live in the chat thinking
# indicator while the tool is in flight (F-0083). Adding a new tool in this
# file MUST also add an entry here — enforced by
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

## Task 2: Add TOOL_LABELS to shared/protocols/tools.py

**Files:**
- Modify: `backend/app/services/ai/subagents/shared/protocols/tools.py` (top of file, after imports)

This file is the shared tool module imported by both `protocol_creator/config.py` and `protocol_editor/config.py`. One `TOOL_LABELS` dict here covers both subagents — there is no per-subagent override.

- [ ] **Step 1: Confirm the exact tool name set**

Run: `grep -hE '"tool":\s*"[a-z_]+"' backend/app/services/ai/subagents/shared/protocols/tools.py | sed -nE 's/.*"tool":\s*"([a-z_]+)".*/\1/p' | sort -u`
Expected (21 names):
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
set_node_position
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
# file MUST also add an entry here — enforced by
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
    "set_node_position": "Repositioning a step…",
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

Run: `cd backend && source .venv/bin/activate && python -c "from app.services.ai.subagents.shared.protocols import tools; print(len(tools.TOOL_LABELS))"`
Expected: `21`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/ai/subagents/shared/protocols/tools.py
git commit -m "feat(chat): add TOOL_LABELS for shared protocol tools"
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
under app/services/ai/subagents/ (excluding the legacy, unwired
protocol_builder package) has a corresponding TOOL_LABELS entry and resolves
to a non-fallback human label.
"""
import re
from pathlib import Path

import pytest

from app.services.ai.tool_labels import FALLBACK_LABEL, resolve_tool_label

SUBAGENTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "app" / "services" / "ai" / "subagents"
)
_TOOL_AUDIT_RE = re.compile(r'"tool"\s*:\s*"([a-z_][a-z0-9_]*)"')

# protocol_builder is on-disk legacy — unregistered in chat_agent.py since the
# TD-0086 split into protocol_creator + protocol_editor. Skip its audits.
_LEGACY_DIRS = {"protocol_builder"}


def _audited_tool_names() -> set[str]:
    names: set[str] = set()
    for tools_py in SUBAGENTS_DIR.rglob("tools.py"):
        # Exclude the legacy package and anything else marked legacy.
        if any(part in _LEGACY_DIRS for part in tools_py.parts):
            continue
        names.update(_TOOL_AUDIT_RE.findall(tools_py.read_text()))
    return names


def test_audited_tools_discovered():
    """Sanity: the scan finds the known tools from the active subagents."""
    names = _audited_tool_names()
    assert "search_documents" in names           # research_library
    assert "create_protocol" in names            # shared/protocols
    assert "set_node_position" in names          # shared/protocols (post-TD-0086)
    # research_library (3) + shared/protocols (21) = 24+
    assert len(names) >= 24


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

from app.services.ai.subagents.research_library.tools import (
    TOOL_LABELS as _RESEARCH_LIBRARY_LABELS,
)
from app.services.ai.subagents.shared.protocols.tools import (
    TOOL_LABELS as _PROTOCOL_LABELS,
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
    **_PROTOCOL_LABELS,
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
Expected: all tests PASS (24+ parametrized cases for individual tools, plus the four named ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/tool_labels.py backend/tests/unit/test_tool_labels.py
git commit -m "feat(chat): add resolve_tool_label() registry + coverage test"
```

---

## Task 4: Refactor send_message to async generator (preserve resilience pattern)

**Files:**
- Modify: `backend/app/services/ai/send_message.py` (full rewrite of the function)
- Create: `backend/tests/unit/test_send_message_streaming.py`
- Delete: `backend/tests/unit/test_send_message.py`

The post-rebase `send_message()` already has a careful resilience pattern: it captures session identity into locals up front, commits the user message **before** the LLM call (so an asyncpg connection killed mid-LLM can't poison the SQLAlchemy session), and persists the assistant message + summary + `ai_message_history` via a **fresh `AsyncSessionLocal()` writer session**. The streaming version must preserve all of this — the only change is wiring `event_stream_handler` into `agent.run(...)` and yielding events as they fire.

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


@pytest.fixture(autouse=True)
def _stub_writer_session():
    """send_message_streaming uses AsyncSessionLocal() for the assistant-msg
    writer. Stub it so tests don't need a real DB."""
    writer = AsyncMock()
    writer.add = MagicMock()
    writer.execute = AsyncMock()
    writer.commit = AsyncMock()
    writer.refresh = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__.return_value = writer
    cm.__aexit__.return_value = None

    with patch(
        "app.services.ai.send_message.AsyncSessionLocal",
        return_value=cm,
    ):
        yield writer


@pytest.mark.asyncio
async def test_emits_tool_start_end_then_done():
    """A turn with one tool call emits tool_start, tool_end, done in order."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
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
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
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
async def test_user_message_committed_before_agent_run():
    """Resilience invariant: user msg must be committed on `db` BEFORE
    agent.run is awaited, so a slow/failed LLM can't lose the user turn."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    session = _make_session()

    call_order: list[str] = []

    async def _record_commit():
        call_order.append("commit")

    async def _record_run(*a, event_stream_handler=None, **kw):
        call_order.append("agent.run")
        if event_stream_handler is not None:
            async def _gen():
                if False:
                    yield None
            await event_stream_handler(MagicMock(), _gen())
        r = MagicMock()
        r.output = "ok"
        r.all_messages.return_value = []
        return r

    db.commit.side_effect = _record_commit

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
        fake_agent.run = _record_run
        mock_build.return_value = fake_agent

        _ = [
            ev async for ev in send_message_streaming(
                db, session, "hi", user_id=uuid.uuid4(), is_org_admin=False,
            )
        ]

    # commit happened at least once before agent.run.
    assert call_order.index("commit") < call_order.index("agent.run")


@pytest.mark.asyncio
async def test_agent_error_yields_error_event():
    """A raised exception from agent.run is converted to an error event."""
    from app.services.ai.send_message import send_message_streaming

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
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

Replace the entire file. This preserves the rebased resilience pattern (commit user msg early, fresh writer session for assistant + summary + history) and adds the event bridge.

```python
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

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessagesTypeAdapter,
)
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
    # Capture session identity into locals up front. After the LLM call, a
    # failed tool can poison `db`; reading these into locals now means the
    # post-LLM path never has to touch the ORM `session` object again.
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

    # Commit before the LLM call so the asyncpg connection isn't holding an
    # open transaction during a network round-trip that can take 30s+.
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

    # ── 4. Event bridge: pydantic-ai event_stream_handler → asyncio.Queue ────
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
    # Tool writes that succeeded fully are preserved by commit; partial writes
    # are discarded by rollback. Either way, our forensic write on the fresh
    # session below still lands the chat history.
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

    # Best-effort: keep in-memory ChatSession consistent.
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
```

The `ChatMessageResponse` schema (alias for `user_message` / `assistant_message` in `ChatCompletionResponse`) lives at `backend/app/schemas/chat.py:27`.

- [ ] **Step 4: Delete the old test**

```bash
git rm backend/tests/unit/test_send_message.py
```

- [ ] **Step 5: Run streaming tests to verify pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_send_message_streaming.py -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Run the whole AI unit-test slice to verify no other tests broke**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_ai_*.py tests/unit/test_chat_*.py tests/unit/test_tool_labels.py tests/unit/test_send_message_streaming.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/tests/unit/test_send_message_streaming.py backend/tests/unit/test_send_message.py
git commit -m "refactor(chat): make send_message a streaming async generator (F-0083)"
```

---

## Task 5: Replace chat POST endpoint with SSE streaming (preserve forensic ERROR write)

**Files:**
- Modify: `backend/app/api/endpoints/chat.py:216-310`
- Create: `backend/tests/integration/test_chat_stream_endpoint.py`
- Modify: `backend/tests/integration/test_chat_api.py` (any test that POSTs `/chat/sessions/{id}/messages`)

The existing endpoint persists a forensic `ChatMessage(role=ERROR, ...)` row with traceback + a short `error_code` when the agent run fails, then returns a 500 with the code so users can reference it in support. The SSE rewrite preserves the same persistence path; the failure surface becomes an `error` SSE event carrying that `error_code` instead of a 500.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_chat_stream_endpoint.py`:

```python
"""Integration test for SSE chat-message endpoint (F-0083)."""

import json
from unittest.mock import patch

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
        await resp.aread()
        assert resp.status_code == 404
```

Note: the `chat_session_id` fixture should already exist in `tests/integration/conftest.py`. If not, look at `test_chat_api.py` for how it creates a session inline; copy that pattern.

- [ ] **Step 2: Run test to confirm it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_chat_stream_endpoint.py -v`
Expected: 404 on the new `/messages/stream` route (endpoint not yet implemented).

- [ ] **Step 3: Replace the endpoint**

In `backend/app/api/endpoints/chat.py`, replace the existing `send_chat_message` function (currently lines ~216-310, ending after the forensic ERROR-row write block) with the streaming endpoint. Keep the forensic write path — only the response surface changes.

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
        except Exception as exc:
            # Forensic write on a fresh session — `db` may be poisoned.
            error_code = secrets.token_hex(4)
            logger.exception(
                "Chat stream failed [error_code=%s] for session %s",
                error_code,
                session_id,
            )
            try:
                async with AsyncSessionLocal() as writer:
                    writer.add(
                        ChatMessage(
                            session_id=session_id,
                            role=ChatMessageRole.ERROR,
                            content=str(exc),
                            metadata_={
                                "error_code": error_code,
                                "error_type": type(exc).__name__,
                                "traceback": traceback.format_exc(),
                            },
                        )
                    )
                    await writer.commit()
            except Exception:
                logger.exception("Failed to persist forensic ERROR row")
            yield (
                f'data: {{"type": "error", "detail": "Failed to generate AI '
                f'response", "error_code": "{error_code}"}}\n\n'
            )

    return StreamingResponse(_sse_iter(), media_type="text/event-stream")
```

Also at the top of the file, add (if not already present):

```python
import json

from fastapi.responses import StreamingResponse

from app.db.session import AsyncSessionLocal
from app.services.ai.send_message import send_message_streaming
```

Remove the old `send_chat_message` function entirely and drop the `from app.services.ai.send_message import send_message` import.

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

Leave `ChatCompletionResponse` in `app/schemas/chat.py` for now — the `done` event payload matches its shape and the schema continues to document the contract.

- [ ] **Step 5: Run integration tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_chat_stream_endpoint.py tests/integration/test_chat_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Run full backend suite once**

Run: `cd backend && source .venv/bin/activate && pytest`
Expected: all PASS.

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
    | { type: 'error'; detail: string; error_code?: string };

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

Match the existing chat bubble styling at `+page.svelte:352-362` so the indicator visually replaces the current block 1-for-1.

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

## Task 8: chat-store switches to streaming (preserve polling/stalePending logic)

**Files:**
- Modify: `frontend/src/lib/chat-store.svelte.ts:300-392` (the `sendMessage` body, lines may drift after Task 6 import)
- Create: `frontend/src/lib/chat-store.test.ts`

The chat store already has a robust recovery mechanism for "refresh during a slow LLM call" (the polling block: `clearPoll`, `maybeStartAwaitingPoll`, `stalePendingMessage`, `retryStalePending`, `dismissStalePending`). **Keep all of that intact** — streaming handles the *active* turn; polling handles *refresh-during-LLM* recovery. The only change to `sendMessage` is swapping the `api.post(...)` body for a `streamSse(...)` call plus new `currentToolLabel` tracking.

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
    ApiError: class ApiError extends Error {},
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
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
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
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        });
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
Expected: `__test_setActiveSession` / `getCurrentToolLabel` / `streamSse` symbols are undefined.

- [ ] **Step 3: Refactor chat-store.svelte.ts**

In `frontend/src/lib/chat-store.svelte.ts`:

a) Add the new state near the existing `messageInput` / `sending` declarations (top of file):

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

c) Replace the `try / catch / finally` body of `sendMessage` (currently the inner block starting around `try { const body: Record<string, string> = { content }; ... const res = await api.post(...) ... }`). Keep everything **above** that try block (lazy session creation, `messageInput = ''`, `clearPoll()`, `sending = true`, optimistic temp message append) and everything outside the function untouched. Replace from the `try {` opener through its `} finally {` close:

```typescript
    try {
        const body: Record<string, string> = { content };
        if (skillId) {
            body.skill_id = skillId;
        }

        currentToolLabel = null;
        currentToolName = null;

        let donePayload: {
            user_message: ChatMessage;
            assistant_message: ChatMessage;
            sources: ChatSourceReference[];
        } | null = null;
        let errorDetail: string | null = null;
        let errorCode: string | null = null;

        await streamSse(
            `/chat/sessions/${activeSession.id}/messages/stream`,
            body,
            (event: SseEvent) => {
                if (event.type === 'tool_start') {
                    currentToolName = event.tool;
                    currentToolLabel = event.label;
                } else if (event.type === 'tool_end') {
                    // Only clear if the end matches the active tool — avoids
                    // clobbering a newer tool_start when a stale end arrives.
                    if (currentToolName === event.tool) {
                        currentToolName = null;
                        currentToolLabel = null;
                    }
                } else if (event.type === 'done') {
                    donePayload = event as typeof donePayload;
                } else if (event.type === 'error') {
                    errorDetail = event.detail;
                    errorCode = (event as { error_code?: string }).error_code ?? null;
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
        const codeSuffix = errorCode ? ` (E${errorCode})` : '';
        toast.error(`Failed to send message${codeSuffix}`);
    } finally {
        currentToolLabel = null;
        currentToolName = null;
        sending = false;
    }
```

> Note: `errorCode` is declared inside the `try {}` block in the snippet above, but referenced in the `catch`. Hoist it to a `let errorCode: string | null = null;` above the try so it's in scope in the catch. (Tests don't exercise this path beyond "label cleared", but TypeScript will flag the scope issue.)

d) Remove the unused import of `ChatCompletionResponseSchema` if nothing else uses it. Keep `ChatSourceReference` and `ChatMessage` imports.

e) Add a single test-only setter at the bottom of the file so unit tests can seed an active session:

```typescript
// --- Test-only export (DO NOT USE FROM APP CODE) ---
export function __test_setActiveSession(s: ChatSessionDetail | null): void {
    activeSession = s;
}
```

The runtime state mutates via `$state` so calling `getCurrentToolLabel()` synchronously after each callback in the test gives correct, current values without needing a `$effect.root` watcher.

> **Do not touch** any code in the polling/stale-pending region (`pollTimer`, `staleTimer`, `pollSessionId`, `stalePendingMessage`, `clearPoll`, `pollForAssistantReply`, `maybeStartAwaitingPoll`, `getStalePendingMessage`, `retryStalePending`, `dismissStalePending`, or the `clearPoll()` call near the top of `sendMessage`). Streaming and polling are complementary — leave the polling intact so a refresh mid-stream still recovers.

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
- Modify: `frontend/src/routes/chat/+page.svelte:352-362` (inline indicator → component, keep `!stalePending` guard)

- [ ] **Step 1: Import the component and the store getter**

In the `<script>` block of `frontend/src/routes/chat/+page.svelte`, add:

```typescript
import ThinkingIndicator from '$lib/components/ai/ThinkingIndicator.svelte';
import { getCurrentToolLabel } from '$lib/chat-store.svelte';

const currentToolLabel = $derived(getCurrentToolLabel());
```

(Place near the other store-derivation lines such as `const sending = $derived(isSending())`.)

- [ ] **Step 2: Replace the inline indicator markup**

Replace lines 352-362 (the `{#if sending && !stalePending} ... {/if}` block with the wrapping `<div class="flex justify-start"><div class="bg-muted/70 rounded-xl px-4 py-3"><div class="flex items-center gap-1.5">` and three bouncing dots) with:

```svelte
{#if sending && !stalePending}
    <div in:fade={{ duration: blockDuration() }}>
        <ThinkingIndicator label={currentToolLabel} />
    </div>
{/if}
```

The component already wraps with `flex justify-start` + the muted bubble, so the outer wrapper just keeps the page-level fade transition.

> Do NOT touch the immediately-following `{#if stalePending} ... {/if}` block — that's the recovery banner and is unrelated.

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
> **What changed:** Chat send-message is now SSE. While the agent runs tools, the 3-dot wiggle is replaced by a short human label (e.g., "Searching documents…", "Drafting a protocol…"); the label disappears as soon as the final assistant message renders. Pure LLM thinking (no tool) keeps the dot wiggle. Refresh-during-LLM recovery (the "No reply yet" banner) still works.
> **Login:** localhost:5183, any registered dev user. Dev DB: `localhost:5432`, postgres/postgres/batchrite, any password works in dev.
> **Pages:** /chat
> **Acceptance to test:**
> 1. Ask "find the SOP for cell culture and draft a protocol from it" — confirm labels switch as the agent moves between tools (search_documents → create_draft / add_protocol_step / validate_protocol).
> 2. Indicator label disappears the instant the assistant message text appears.
> 3. Ask "what's 2+2" — only the 3-dot wiggle, never a label.
> 4. Open the Network panel and confirm the request is to `/chat/sessions/{id}/messages/stream` with `text/event-stream` content-type; multiple `data:` frames arrive before the response closes.
> 5. Regression: send a slow message ("draft a long protocol about cell culture"), refresh the page mid-turn, return to the chat. The user message should still be there and the indicator should pick back up (polling). After 90s of no reply, the "No reply yet" amber banner appears with Retry / Keep waiting buttons.
> 6. UI audit: label text doesn't overflow, indicator alignment matches the existing chat bubble style, no layout shift between "label + dots" and "dots only" modes.
> Fix any FAIL or POLISH issue before returning.

- [ ] **Step 3: Stop dev servers**

After qa-verify returns clean, kill the background servers.

---

## Task 12: Update project rules (CLAUDE.md / .claude/rules/*)

**Files:**
- Modify: `.claude/rules/backend-ai.md`

- [ ] **Step 1: Add the SSE+tool-label note**

In `.claude/rules/backend-ai.md`, find the "Tool Functions" section and add a single sentence at the bottom:

> Each subagent's `tools.py` (or `shared/<domain>/tools.py` for shared modules) MUST declare a module-level `TOOL_LABELS: dict[str, str]` mapping each tool name to a short human label (ending in "…"); the chat SSE endpoint sends these to the UI as the tool fires. `tests/unit/test_tool_labels.py` enforces full coverage and excludes the legacy `protocol_builder` package.

- [ ] **Step 2: Note the SSE endpoint**

Add a short paragraph after "Chat Agent Harness Pattern" describing the streaming endpoint:

> The chat API exposes `POST /chat/sessions/{id}/messages/stream` returning `text/event-stream`. Each `data:` frame carries a JSON object with a `type` discriminator: `tool_start` (with `tool`, `label`), `tool_end` (with `tool`), `done` (full `ChatCompletionResponse` shape), or `error` (with `detail`, optional `error_code`). The orchestration logic lives in `send_message_streaming` (async generator) in `services/ai/send_message.py`.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/backend-ai.md
git commit -m "docs(rules): note TOOL_LABELS + SSE chat endpoint for F-0083"
```

---

## Task 13: Close out

**Files:** none

- [ ] **Step 1: Present results to the user**

Summary template (fill in actual values from the run):

> F-0083 implemented:
> - Backend: SSE endpoint `POST /chat/sessions/{id}/messages/stream`; `send_message_streaming` async generator using pydantic-ai's `event_stream_handler`; `app/services/ai/tool_labels.py` aggregator. Preserves the post-rebase resilience pattern (commit user msg early, fresh writer session for assistant msg) and the forensic ERROR-row persistence on failure.
> - Frontend: `streamSse()` helper, `ThinkingIndicator.svelte`, `chat-store.svelte.ts` consumes the stream and tracks `currentToolLabel`. Existing refresh-recovery polling kept intact.
> - Tool labels live in each subagent's `tools.py` (`TOOL_LABELS` dict); `shared/protocols/tools.py` covers protocol_creator + protocol_editor in one place. Coverage test in `tests/unit/test_tool_labels.py` blocks PRs that add tools without labels.
> - Tests: <N> backend, <M> frontend; all pass. Browser verified including the refresh-during-LLM regression.

Ask the user to confirm before closing.

- [ ] **Step 2: After user confirmation, close the ClickUp task**

Post a summary comment on F-0083 listing the files changed and tests added, then set status to `complete`.

- [ ] **Step 3: Exit the worktree (action: keep — commits go onto main per worktree convention)**

```
ExitWorktree action=keep
```
