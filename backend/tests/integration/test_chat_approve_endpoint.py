"""POST /chat/sessions/{id}/messages/approve — endpoint contract (F-0084)."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.iam import Organization


@pytest.mark.asyncio
async def test_returns_404_for_unknown_session(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    resp = await client.post(
        f"/chat/sessions/{uuid.uuid4()}/messages/approve",
        json={"tool_call_id": "x", "approved": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_returns_409_when_no_pending_approval(
    client: AsyncClient, auth_headers: dict, test_org: Organization
):
    create = await client.post(
        "/chat/sessions",
        json={"title": "Approve test"},
        headers=auth_headers,
    )
    assert create.status_code == 201
    session_id = create.json()["id"]

    resp = await client.post(
        f"/chat/sessions/{session_id}/messages/approve",
        json={"tool_call_id": "nothing-here", "approved": True},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"] == "no_pending_approval"
