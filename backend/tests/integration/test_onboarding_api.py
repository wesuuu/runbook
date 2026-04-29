"""Integration tests for /onboarding endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_state_requires_auth(client: AsyncClient):
    resp = await client.get("/onboarding/state")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_state_returns_empty_for_new_user(client: AsyncClient, auth_headers):
    resp = await client.get("/onboarding/state", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"completed": [], "dismissed": []}


@pytest.mark.asyncio
async def test_patch_state_marks_segment_completed(client: AsyncClient, auth_headers):
    resp = await client.patch(
        "/onboarding/state",
        json={"segment": "project", "status": "completed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] == ["project"]
    assert data["dismissed"] == []


@pytest.mark.asyncio
async def test_patch_state_marks_segment_dismissed(client: AsyncClient, auth_headers):
    resp = await client.patch(
        "/onboarding/state",
        json={"segment": "run", "status": "dismissed"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dismissed"] == ["run"]


@pytest.mark.asyncio
async def test_patch_state_rejects_bad_segment(client: AsyncClient, auth_headers):
    resp = await client.patch(
        "/onboarding/state",
        json={"segment": "bogus", "status": "completed"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tour_project_start_returns_project_id(client: AsyncClient, auth_headers):
    resp = await client.post("/onboarding/tour/project/start", headers=auth_headers)
    assert resp.status_code == 200
    assert "project_id" in resp.json()


@pytest.mark.asyncio
async def test_tour_protocol_start_returns_ids(client: AsyncClient, auth_headers):
    resp = await client.post("/onboarding/tour/protocol/start", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "project_id" in data
    assert "protocol_id" in data


@pytest.mark.asyncio
async def test_tour_run_start_returns_run(client: AsyncClient, auth_headers):
    resp = await client.post("/onboarding/tour/run/start", headers=auth_headers)
    assert resp.status_code == 200
    assert "run_id" in resp.json()


@pytest.mark.asyncio
async def test_tour_run_end_is_idempotent(client: AsyncClient, auth_headers):
    resp1 = await client.post("/onboarding/tour/run/end", headers=auth_headers)
    assert resp1.status_code == 200
    resp2 = await client.post("/onboarding/tour/run/end", headers=auth_headers)
    assert resp2.status_code == 200
