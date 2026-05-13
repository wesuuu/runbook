"""resume_message_streaming: resumes a deferred tool call with DeferredToolResults."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.send_message import resume_message_streaming


def _make_session():
    session = MagicMock()
    session.id = uuid.uuid4()
    session.org_id = uuid.uuid4()
    session.title = "Test"
    session.ai_message_history = []
    return session


def _make_placeholder(pending: dict):
    placeholder = MagicMock()
    placeholder.id = uuid.uuid4()
    placeholder.session_id = uuid.uuid4()
    placeholder.role = "ASSISTANT"
    placeholder.content = ""
    placeholder.created_at = datetime.now(timezone.utc)
    placeholder.metadata_ = {"pending_approval": pending}
    return placeholder


class _FakeWriter:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def execute(self, *a, **kw):
        return None

    async def commit(self):
        return None


def _install_fakes(monkeypatch, run_fn):
    fake_agent = SimpleNamespace(run=run_fn)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )
    monkeypatch.setattr(
        "app.services.ai.send_message.AsyncSessionLocal",
        lambda: _FakeWriter(),
    )


def _make_db(persisted: list[str] | None = None):
    def _db_add(msg):
        msg.id = uuid.uuid4()
        msg.created_at = datetime.now(timezone.utc)
        if persisted is not None and getattr(msg, "content", None):
            persisted.append(msg.content)

    db = AsyncMock()
    db.add = MagicMock(side_effect=_db_add)
    return db


@pytest.mark.asyncio
async def test_resume_yields_done_with_assistant_message(monkeypatch):
    session = _make_session()
    placeholder = _make_placeholder(
        {
            "tool_call_id": "call_abc",
            "tool_name": "create_protocol_from_external_source",
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
            "payload_preview": {},
        }
    )

    fake_result = SimpleNamespace(
        output="Drafted [X](/protocols/123).",
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        assert "deferred_tool_results" in kw
        return fake_result

    _install_fakes(monkeypatch, _fake_run)

    events = []
    async for ev in resume_message_streaming(
        db=_make_db(),
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


@pytest.mark.asyncio
async def test_resume_rehydrates_external_protocol_cache(monkeypatch):
    """Resume must seed ``deps.external_protocol_cache`` from the placeholder
    metadata so the deferred-approval tool body finds the cached payload
    when pydantic-ai replays it."""
    session = _make_session()
    cached_url = "https://openwetware.org/wiki/X"
    cached_json = (
        '{"title":"X","source_url":"https://openwetware.org/wiki/X",'
        '"steps":[{"text":"s1"}]}'
    )
    placeholder = _make_placeholder(
        {
            "tool_call_id": "call_abc",
            "tool_name": "create_protocol_from_external_source",
            "source_url": cached_url,
            "payload_json": cached_json,
        }
    )

    captured_kwargs: dict = {}

    async def _fake_run(*a, **kw):
        captured_kwargs.update(kw)
        return SimpleNamespace(output="Drafted X.", all_messages=lambda: [])

    _install_fakes(monkeypatch, _fake_run)

    async for _ in resume_message_streaming(
        db=_make_db(),
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=True,
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        pass

    deps = captured_kwargs["deps"]
    assert deps.external_protocol_cache.get(cached_url) == cached_json


@pytest.mark.asyncio
async def test_resume_applies_edited_steps_to_cached_payload(monkeypatch):
    """When the user inline-edits the procedure on the approval card, the
    edited steps replace the cached payload's ``steps`` before the
    approval tool body runs — so the sentinel reflects the user-approved
    version."""
    session = _make_session()
    cached_url = "https://openwetware.org/wiki/X"
    cached_json = json.dumps(
        {
            "title": "X",
            "source_url": cached_url,
            "steps": [
                {"text": "Step 1 original", "duration_min": 5},
                {"text": "Step 2 original"},
            ],
        }
    )
    placeholder = _make_placeholder(
        {
            "tool_call_id": "call_abc",
            "tool_name": "create_protocol_from_external_source",
            "source_url": cached_url,
            "payload_json": cached_json,
        }
    )

    captured_kwargs: dict = {}

    async def _fake_run(*a, **kw):
        captured_kwargs.update(kw)
        return SimpleNamespace(output="Drafted X.", all_messages=lambda: [])

    _install_fakes(monkeypatch, _fake_run)

    edited = [
        {"text": "Step 1 edited", "duration_min": 10},
        {"text": "Step 2 original", "duration_min": None},
        {"text": "Step 3 added", "duration_min": 3},
    ]
    deviations = [
        "Edited step: ~~Step 1 original~~ Step 1 edited",
        "Added step: Step 3 added",
    ]

    async for _ in resume_message_streaming(
        db=_make_db(),
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=True,
        user_id=uuid.uuid4(),
        is_org_admin=False,
        edited_steps=edited,
        deviations=deviations,
    ):
        pass

    deps = captured_kwargs["deps"]
    cached_after = json.loads(deps.external_protocol_cache[cached_url])
    assert [s["text"] for s in cached_after["steps"]] == [
        "Step 1 edited",
        "Step 2 original",
        "Step 3 added",
    ]
    assert cached_after["steps"][0]["duration_min"] == 10
    assert deps.user_deviations == deviations


@pytest.mark.asyncio
async def test_resume_ignores_edits_on_rejection(monkeypatch):
    """edited_steps + deviations are approval-only — a rejection must not
    rewrite the cached payload or set user_deviations."""
    session = _make_session()
    cached_url = "https://openwetware.org/wiki/X"
    cached_json = json.dumps(
        {"title": "X", "source_url": cached_url, "steps": [{"text": "orig"}]}
    )
    placeholder = _make_placeholder(
        {
            "tool_call_id": "call_abc",
            "source_url": cached_url,
            "payload_json": cached_json,
        }
    )

    captured_kwargs: dict = {}

    async def _fake_run(*a, **kw):
        captured_kwargs.update(kw)
        return SimpleNamespace(output="Got it.", all_messages=lambda: [])

    _install_fakes(monkeypatch, _fake_run)

    async for _ in resume_message_streaming(
        db=_make_db(),
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=False,
        user_id=uuid.uuid4(),
        is_org_admin=False,
        edited_steps=[{"text": "ignored"}],
        deviations=["ignored"],
    ):
        pass

    deps = captured_kwargs["deps"]
    cached_after = json.loads(deps.external_protocol_cache[cached_url])
    assert cached_after["steps"] == [{"text": "orig"}]
    assert deps.user_deviations == []


@pytest.mark.asyncio
async def test_resume_no_longer_injects_user_prompt(monkeypatch):
    """The rejection-with-reason redraft path is gone — agent.run is never
    called with a user_prompt on resume. Corrections are expressed via
    inline edits to the approval card, not via free-form rejection text."""
    session = _make_session()
    placeholder = _make_placeholder({"tool_call_id": "call_abc"})

    captured_kwargs: dict = {}

    async def _fake_run(*a, **kw):
        captured_kwargs.update(kw)
        return SimpleNamespace(output="Got it.", all_messages=lambda: [])

    _install_fakes(monkeypatch, _fake_run)

    async for _ in resume_message_streaming(
        db=_make_db(),
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=False,
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        pass

    assert "user_prompt" not in captured_kwargs
    assert "deferred_tool_results" in captured_kwargs
