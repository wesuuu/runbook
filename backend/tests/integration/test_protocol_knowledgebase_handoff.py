"""F-0084: SSE handshake for external-protocol approval (stream → approve).

This is a wiring-level integration test. The agent layer is mocked so the
test is deterministic and does not hit a real LLM. The unit tests
(`test_send_message_approval.py`, `test_resume_message_streaming.py`)
already pin the per-function contract; this file checks that the two
endpoints compose: a stream turn that yields `approval_required` is
followed by an approve turn that yields `done`, and that the rejection
path returns cleanly without erroring.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatMessageRole
from app.models.iam import Organization


def _parse_sse_lines(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


async def _create_session(client: AsyncClient, auth_headers: dict) -> str:
    resp = await client.post(
        "/chat/sessions",
        json={"title": "F-0084 handshake"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _persist_placeholder(
    db: AsyncSession, session_id: str, tool_call_id: str
) -> ChatMessage:
    """Mirror what send_message_streaming would persist when it pauses."""
    msg = ChatMessage(
        session_id=uuid.UUID(session_id),
        role=ChatMessageRole.ASSISTANT,
        content="",
        metadata_={
            "pending_approval": {
                "tool_call_id": tool_call_id,
                "tool_name": "create_protocol_from_external_source",
                "title": "Heat-shock transformation",
                "source_url": "https://openwetware.org/wiki/X",
                "payload_preview": {
                    "title": "Heat-shock transformation",
                    "source_url": "https://openwetware.org/wiki/X",
                    "step_count": 5,
                    "license": "CC BY-SA 3.0",
                    "deviations": [],
                },
            }
        },
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)
    return msg


async def _yield_canned(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_stream_then_approve_completes_turn(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    """approval_required → approve resumes → done."""
    session_id = await _create_session(client, auth_headers)
    tool_call_id = "call_handshake_1"
    placeholder = await _persist_placeholder(db_session, session_id, tool_call_id)

    stream_events = [
        {
            "type": "approval_required",
            "tool_call_id": tool_call_id,
            "tool_name": "create_protocol_from_external_source",
            "title": "Heat-shock transformation",
            "source_url": "https://openwetware.org/wiki/X",
            "payload_preview": {
                "title": "Heat-shock transformation",
                "source_url": "https://openwetware.org/wiki/X",
                "step_count": 5,
                "license": "CC BY-SA 3.0",
                "deviations": [],
            },
            "assistant_message_id": str(placeholder.id),
        },
    ]

    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        return_value=_yield_canned(*stream_events),
    ):
        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "convert that one"},
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk

    events = _parse_sse_lines(body)
    types = [e["type"] for e in events]
    assert "approval_required" in types
    assert "done" not in types

    resume_events = [
        {
            "type": "done",
            "user_message": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "USER",
                "content": "Approved external protocol conversion.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "assistant_message": {
                "id": str(placeholder.id),
                "session_id": session_id,
                "role": "ASSISTANT",
                "content": "Drafted Heat-shock transformation.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "sources": [],
        }
    ]

    with patch(
        "app.api.endpoints.chat.resume_message_streaming",
        return_value=_yield_canned(*resume_events),
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages/approve",
            json={"tool_call_id": tool_call_id, "approved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    events = _parse_sse_lines(body)
    assert [e["type"] for e in events] == ["done"]
    assert "Drafted" in events[0]["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_rejection_path_resumes_cleanly(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    """approved=False also reaches the resume endpoint and returns done."""
    session_id = await _create_session(client, auth_headers)
    tool_call_id = "call_handshake_2"
    placeholder = await _persist_placeholder(db_session, session_id, tool_call_id)

    resume_events = [
        {
            "type": "done",
            "user_message": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "USER",
                "content": "Rejected the external protocol conversion.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "assistant_message": {
                "id": str(placeholder.id),
                "session_id": session_id,
                "role": "ASSISTANT",
                "content": "Skipped the import. Let me know how you'd like to proceed.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "sources": [],
        }
    ]

    with patch(
        "app.api.endpoints.chat.resume_message_streaming",
        return_value=_yield_canned(*resume_events),
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages/approve",
            json={"tool_call_id": tool_call_id, "approved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    events = _parse_sse_lines(body)
    assert events[-1]["type"] == "done"
