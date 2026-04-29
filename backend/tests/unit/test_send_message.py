"""Tests for send_message orchestration (Task 18 — TD-0081)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession
from app.services.ai.deps import RetrievedChunk
from app.services.ai.runtime.compaction import CompactionState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(**kwargs):
    """Return a minimal ChatSession-like object."""
    s = MagicMock(spec=ChatSession)
    s.id = uuid.uuid4()
    s.org_id = uuid.uuid4()
    s.title = kwargs.get("title", "New Chat")
    s.ai_message_history = kwargs.get("ai_message_history", None)
    return s


def _make_chunk(**kwargs):
    return RetrievedChunk(
        document_id=uuid.uuid4(),
        document_title=kwargs.get("document_title", "Doc A"),
        chunk_id=kwargs.get("chunk_id", uuid.uuid4()),
        chunk_index=0,
        page_number=1,
        content="Some content about the topic.",
        score=0.9,
    )


# ---------------------------------------------------------------------------
# Test 1: happy path — no compaction, single source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_happy_path():
    """send_message persists both messages and returns correct tuple."""
    from app.services.ai.send_message import send_message

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    session = _make_session()
    user_id = uuid.uuid4()

    chunk = _make_chunk()
    fake_state = CompactionState()

    fake_result = MagicMock()
    fake_result.output = "Hello, world!"
    fake_result.all_messages.return_value = []

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=fake_state,
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter") as mock_adapter,
        patch(
            "app.services.ai.send_message.sanitize_output",
            return_value="Hello, world!",
        ),
    ):
        fake_agent = AsyncMock()
        fake_agent.run = AsyncMock(return_value=fake_result)
        mock_build.return_value = fake_agent

        mock_adapter.validate_python.return_value = []
        mock_adapter.dump_python.return_value = []

        # Inject a source via deps side-effect
        async def _run_side_effect(user_content, deps, message_history, **kwargs):
            deps.sources.append(chunk)
            return fake_result

        fake_agent.run.side_effect = _run_side_effect

        user_msg, assistant_msg, sources = await send_message(
            db=db,
            session=session,
            user_content="What is the protocol for buffer prep?",
            user_id=user_id,
            is_org_admin=False,
        )

    assert isinstance(user_msg, ChatMessage)
    assert user_msg.role == ChatMessageRole.USER
    assert user_msg.content == "What is the protocol for buffer prep?"

    assert isinstance(assistant_msg, ChatMessage)
    assert assistant_msg.role == ChatMessageRole.ASSISTANT
    assert assistant_msg.content == "Hello, world!"

    assert len(sources) == 1
    assert sources[0].chunk_id == chunk.chunk_id


# ---------------------------------------------------------------------------
# Test 2: auto-title when session.title == "New Chat"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_title_on_new_chat():
    """Session title is updated from the first message when it is 'New Chat'."""
    from app.services.ai.send_message import send_message

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    session = _make_session(title="New Chat")
    user_id = uuid.uuid4()

    fake_state = CompactionState()
    fake_result = MagicMock()
    fake_result.output = "Response text."
    fake_result.all_messages.return_value = []

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=fake_state,
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter") as mock_adapter,
        patch(
            "app.services.ai.send_message.sanitize_output",
            return_value="Response text.",
        ),
    ):
        fake_agent = AsyncMock()
        fake_agent.run = AsyncMock(return_value=fake_result)
        mock_build.return_value = fake_agent
        mock_adapter.validate_python.return_value = []
        mock_adapter.dump_python.return_value = []

        long_message = "A" * 200
        await send_message(
            db=db,
            session=session,
            user_content=long_message,
            user_id=user_id,
            is_org_admin=False,
        )

    # Title should be truncated to 100 chars
    assert session.title == long_message[:100].strip()


# ---------------------------------------------------------------------------
# Test 3: compaction triggered → SUMMARY row written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writes_summary_row_when_compaction_triggered():
    """A ChatMessage with role=SUMMARY is persisted when compaction triggers."""
    from app.services.ai.send_message import send_message

    db = AsyncMock()
    added_objects: list = []
    db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    db.flush = AsyncMock()

    session = _make_session(title="Existing Title")
    user_id = uuid.uuid4()

    # Simulate compaction having triggered
    fake_state = CompactionState()
    fake_state.triggered = True
    fake_state.summary_text = "This is a compact summary of past turns."
    fake_state.summarized_message_count = 4

    fake_result = MagicMock()
    fake_result.output = "Agent response after compaction."
    fake_result.all_messages.return_value = []

    with (
        patch(
            "app.services.ai.send_message.build_chat_agent", new_callable=AsyncMock
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=fake_state,
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter") as mock_adapter,
        patch(
            "app.services.ai.send_message.sanitize_output",
            return_value="Agent response after compaction.",
        ),
    ):
        fake_agent = AsyncMock()
        fake_agent.run = AsyncMock(return_value=fake_result)
        mock_build.return_value = fake_agent
        mock_adapter.validate_python.return_value = []
        mock_adapter.dump_python.return_value = []

        await send_message(
            db=db,
            session=session,
            user_content="Continue the experiment.",
            user_id=user_id,
            is_org_admin=False,
        )

    summary_rows = [
        o
        for o in added_objects
        if isinstance(o, ChatMessage) and o.role == ChatMessageRole.SUMMARY
    ]
    assert len(summary_rows) == 1
    assert summary_rows[0].content == "This is a compact summary of past turns."
