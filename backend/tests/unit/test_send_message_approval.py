"""send_message_streaming emits approval_required when agent.run returns
DeferredToolRequests, persists the placeholder assistant row, and does NOT
emit `done`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import DeferredToolRequests

from app.services.ai.send_message import send_message_streaming


@pytest.mark.asyncio
async def test_emits_approval_required_when_deferred(monkeypatch):
    session = MagicMock()
    session.id = uuid.uuid4()
    session.org_id = uuid.uuid4()
    session.title = "Test"
    session.ai_message_history = None

    call_part = ToolCallPart(
        tool_name="create_protocol_from_external_source",
        args={
            "payload_json": (
                '{"title":"X",'
                '"source_url":"https://openwetware.org/wiki/X",'
                '"steps":[]}'
            ),
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
        },
        tool_call_id="call_abc",
    )
    deferred = DeferredToolRequests(calls=[], approvals=[call_part])
    fake_result = SimpleNamespace(
        output=deferred,
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        return fake_result

    fake_agent = SimpleNamespace(run=_fake_run)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )

    placeholder_holder: dict = {}

    class _FakeWriter:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def add(self, msg):
            placeholder_holder["msg"] = msg
            msg.id = uuid.uuid4()

        async def execute(self, *a, **kw):
            return None

        async def commit(self):
            return None

        async def refresh(self, msg):
            return None

    monkeypatch.setattr(
        "app.services.ai.send_message.AsyncSessionLocal",
        lambda: _FakeWriter(),
    )

    db = AsyncMock()
    events = []
    async for ev in send_message_streaming(
        db=db,
        session=session,
        user_content="convert it",
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "approval_required" in types
    assert "done" not in types
    approval = next(e for e in events if e["type"] == "approval_required")
    assert approval["tool_call_id"] == "call_abc"
    assert approval["tool_name"] == "create_protocol_from_external_source"
    assert approval["title"] == "X"
    assert approval["source_url"] == "https://openwetware.org/wiki/X"
    assert "assistant_message_id" in approval
