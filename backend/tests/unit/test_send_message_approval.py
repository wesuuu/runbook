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
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
            "project_name": "Cell Culture",
        },
        tool_call_id="call_abc",
    )
    deferred = DeferredToolRequests(calls=[], approvals=[call_part])
    fake_result = SimpleNamespace(
        output=deferred,
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        # Simulate the subagent having cached the payload server-side before
        # the parent reached the approval gate.
        deps = kw.get("deps")
        if deps is not None:
            deps.external_protocol_cache["https://openwetware.org/wiki/X"] = (
                '{"title":"X","source_url":"https://openwetware.org/wiki/X",'
                '"steps":[{"text":"s1"}]}'
            )
        return fake_result

    fake_agent = SimpleNamespace(run=_fake_run)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )
    # The persisted user_msg is an unsaved ORM mock (no id/created_at), so
    # the real ChatMessageResponse.model_validate would raise. Stub it — the
    # approval path does not surface the user_message payload anyway.
    monkeypatch.setattr(
        "app.services.ai.send_message.ChatMessageResponse",
        SimpleNamespace(
            model_validate=lambda _obj: SimpleNamespace(
                model_dump=lambda **_kw: {"id": "u", "role": "user", "content": "x"}
            )
        ),
    )

    placeholder_holder: dict = {}
    executed_sql: list[str] = []

    class _FakeWriter:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def add(self, msg):
            placeholder_holder["msg"] = msg
            msg.id = uuid.uuid4()

        async def execute(self, stmt, *a, **kw):
            executed_sql.append(str(stmt))
            return None

        async def commit(self):
            return None

        async def refresh(self, msg):
            return None

    monkeypatch.setattr(
        "app.services.ai.send_message.AsyncSessionLocal",
        lambda: _FakeWriter(),
    )
    # Defensively stub the heartbeat refresher so a slow run cannot make the
    # background task issue its own active_turn_heartbeat_at UPDATE through
    # the monkeypatched AsyncSessionLocal (which would pollute executed_sql).
    monkeypatch.setattr(
        "app.services.ai.turn_status._write_heartbeat", AsyncMock()
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
    # Preview's step_count comes from the server cache, not the tool args.
    assert approval["payload_preview"]["step_count"] == 1
    # Project name from the tool args surfaces on the approval card.
    assert approval["payload_preview"]["project_name"] == "Cell Culture"
    # Placeholder metadata must persist the cached payload so resume can
    # rehydrate the cache for the deferred tool body.
    persisted_meta = placeholder_holder["msg"].metadata_
    pending = persisted_meta["pending_approval"]
    assert "payload_json" in pending
    assert "https://openwetware.org/wiki/X" in pending["payload_json"]
    # BUG-005: the HITL-pause placeholder writer clears the turn heartbeat
    # — the turn is suspended awaiting approval, not in progress.
    assert any("active_turn_heartbeat_at" in sql for sql in executed_sql)
