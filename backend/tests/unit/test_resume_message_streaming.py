"""resume_message_streaming: resumes a deferred tool call with DeferredToolResults."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.send_message import resume_message_streaming


@pytest.mark.asyncio
async def test_resume_yields_done_with_assistant_message(monkeypatch):
    session = MagicMock()
    session.id = uuid.uuid4()
    session.org_id = uuid.uuid4()
    session.title = "Test"
    session.ai_message_history = []

    placeholder = MagicMock()
    placeholder.id = uuid.uuid4()
    placeholder.session_id = session.id
    placeholder.role = "ASSISTANT"
    placeholder.content = ""
    placeholder.created_at = datetime.now(timezone.utc)
    placeholder.metadata_ = {
        "pending_approval": {
            "tool_call_id": "call_abc",
            "tool_name": "create_protocol_from_external_source",
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
            "payload_preview": {},
        }
    }

    fake_result = SimpleNamespace(
        output="Drafted [X](/protocols/123).",
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        assert "deferred_tool_results" in kw
        return fake_result

    fake_agent = SimpleNamespace(run=_fake_run)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )

    class _FakeWriter:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, *a, **kw):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.ai.send_message.AsyncSessionLocal",
        lambda: _FakeWriter(),
    )

    def _db_add(msg):
        msg.id = uuid.uuid4()
        msg.created_at = datetime.now(timezone.utc)

    db = AsyncMock()
    db.add = MagicMock(side_effect=_db_add)
    events = []
    async for ev in resume_message_streaming(
        db=db,
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=True,
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert "Drafted" in done["assistant_message"]["content"]
