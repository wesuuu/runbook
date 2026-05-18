"""Integration test for SSE chat-message streaming endpoint (F-0083)."""

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.models.iam import Organization


def _parse_sse_lines(body: str) -> list[dict]:
    """Parse a body of SSE 'data: {json}\\n\\n' frames into a list of dicts."""
    events = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:") :].strip()))
    return events


async def _yield_canned_events(*items):
    for item in items:
        yield item


async def _create_session(
    client: AsyncClient,
    auth_headers: dict,
    title: str = "Test Chat",
) -> str:
    resp = await client.post(
        "/chat/sessions",
        json={"title": title},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_stream_endpoint_emits_tool_events_then_done(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    """SSE response carries tool_start / tool_end / done in order."""
    session_id = await _create_session(client, auth_headers)

    canned = [
        {
            "type": "tool_start",
            "tool": "search_documents",
            "label": "Searching documents…",
        },
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
            f"/chat/sessions/{session_id}/messages/stream",
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
async def test_stream_endpoint_done_only_when_no_tools(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    """SSE response emits a single done event when no tools are called."""
    session_id = await _create_session(client, auth_headers)

    canned = [
        {
            "type": "done",
            "user_message": {"id": "u1", "role": "user", "content": "hello"},
            "assistant_message": {"id": "a1", "role": "assistant", "content": "Hello!"},
            "sources": [],
        },
    ]

    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        return_value=_yield_canned_events(*canned),
    ):
        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "hello"},
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk

    events = _parse_sse_lines(body)
    assert len(events) == 1
    assert events[0]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_endpoint_404_when_session_missing(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    """Non-existent session returns 404 before any SSE is emitted."""
    async with client.stream(
        "POST",
        "/chat/sessions/00000000-0000-0000-0000-000000000000/messages/stream",
        json={"content": "hi"},
        headers=auth_headers,
    ) as resp:
        await resp.aread()
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_endpoint_requires_auth(
    client: AsyncClient, test_org: Organization
):
    """Unauthenticated request returns 401."""
    async with client.stream(
        "POST",
        "/chat/sessions/00000000-0000-0000-0000-000000000000/messages/stream",
        json={"content": "hi"},
    ) as resp:
        await resp.aread()
        assert resp.status_code == 401
