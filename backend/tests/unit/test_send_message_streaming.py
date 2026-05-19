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
    """Build a fake agent.run that invokes event_stream_handler with the
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
            tool_name=tool_name,
            content="ok",
            tool_call_id=call_id,
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


def _patch_schema_serialization():
    """Patch ChatMessageResponse and ChatSourceReference so tests don't need
    real ORM objects with DB-populated fields (id, created_at, etc.)."""
    fake_msg_resp = MagicMock()
    fake_msg_resp.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": "hi",
    }

    mock_cmr = MagicMock()
    mock_cmr.model_validate.return_value = fake_msg_resp

    mock_csr = MagicMock()
    mock_csr.return_value.model_dump.return_value = {}

    return (
        patch("app.services.ai.send_message.ChatMessageResponse", mock_cmr),
        patch("app.services.ai.send_message.ChatSourceReference", mock_csr),
    )


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

    cmr_patch, csr_patch = _patch_schema_serialization()

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
        cmr_patch,
        csr_patch,
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent

        emitted = [
            ev
            async for ev in send_message_streaming(
                db,
                session,
                "hi",
                user_id=uuid.uuid4(),
                is_org_admin=False,
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

    cmr_patch, csr_patch = _patch_schema_serialization()

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
        cmr_patch,
        csr_patch,
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent

        emitted = [
            ev
            async for ev in send_message_streaming(
                db,
                session,
                "hi",
                user_id=uuid.uuid4(),
                is_org_admin=False,
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

    cmr_patch, csr_patch = _patch_schema_serialization()

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
        cmr_patch,
        csr_patch,
    ):
        fake_agent = MagicMock()
        fake_agent.run = _record_run
        mock_build.return_value = fake_agent

        _ = [
            ev
            async for ev in send_message_streaming(
                db,
                session,
                "hi",
                user_id=uuid.uuid4(),
                is_org_admin=False,
            )
        ]

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
            ev
            async for ev in send_message_streaming(
                db,
                session,
                "hi",
                user_id=uuid.uuid4(),
                is_org_admin=False,
            )
        ]

    assert emitted[-1]["type"] == "error"
    assert "detail" in emitted[-1]


async def _fake_run_capturing(captured: dict):
    """A fake agent.run that records the prompt it was given."""

    async def _run(*args, event_stream_handler=None, **kwargs):
        captured["prompt"] = args[0]
        result = MagicMock()
        result.output = "ok"
        result.all_messages.return_value = []
        return result

    return _run


async def _drain_streaming(db, session, content, **kwargs):
    from app.services.ai.send_message import send_message_streaming

    captured: dict = {}
    run_fn = await _fake_run_capturing(captured)
    cmr_patch, csr_patch = _patch_schema_serialization()
    with (
        patch(
            "app.services.ai.send_message.build_chat_agent",
            new_callable=AsyncMock,
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=CompactionState(),
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter"),
        patch("app.services.ai.send_message.sanitize_output", return_value="ok"),
        cmr_patch,
        csr_patch,
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent
        [ev async for ev in send_message_streaming(db, session, content, **kwargs)]
    return captured, db


def _fresh_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_current_route_prepends_page_marker():
    """current_route prepends [page:<route>] to the model-visible prompt."""
    captured, db = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "how do I publish this?",
        user_id=uuid.uuid4(),
        is_org_admin=False,
        current_route="/protocols/abc/edit",
    )
    assert captured["prompt"] == ("[page:/protocols/abc/edit] how do I publish this?")
    # Persisted user message keeps the clean text.
    user_msg = db.add.call_args_list[0].args[0]
    assert user_msg.content == "how do I publish this?"


@pytest.mark.asyncio
async def test_no_route_means_no_prefix():
    """Absent current_route leaves the prompt unprefixed."""
    captured, _ = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "hello",
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    assert captured["prompt"] == "hello"


@pytest.mark.asyncio
async def test_skill_marker_precedes_page_marker():
    """[skill:<id>] stays first so 'message begins with [skill:' holds."""
    captured, _ = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "draft a protocol",
        user_id=uuid.uuid4(),
        is_org_admin=False,
        skill_id="new-protocol",
        current_route="/protocols",
    )
    assert captured["prompt"] == (
        "[skill:new-protocol] [page:/protocols] draft a protocol"
    )
