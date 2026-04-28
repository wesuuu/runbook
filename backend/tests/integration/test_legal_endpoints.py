"""Integration tests for the public /legal/* endpoints.

These endpoints must work WITHOUT authentication so prospective users
and the marketing-page footer links function properly.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def unauthed_client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_legal_current_returns_version_and_effective_date(unauthed_client):
    resp = await unauthed_client.get("/legal/current")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert "effective_date" in body
    assert body["version"] == body["effective_date"]


@pytest.mark.asyncio
async def test_legal_current_does_not_require_auth(unauthed_client):
    resp = await unauthed_client.get("/legal/current")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_legal_terms_returns_markdown(unauthed_client):
    current = (await unauthed_client.get("/legal/current")).json()["version"]
    resp = await unauthed_client.get(f"/legal/versions/{current}/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == current
    assert body["effective_date"] == current
    assert isinstance(body["markdown"], str)
    assert "Research Use Only" in body["markdown"]


@pytest.mark.asyncio
async def test_legal_privacy_returns_markdown(unauthed_client):
    current = (await unauthed_client.get("/legal/current")).json()["version"]
    resp = await unauthed_client.get(f"/legal/versions/{current}/privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == current
    assert "do not use customer data to train" in body["markdown"]


@pytest.mark.asyncio
async def test_legal_versions_unknown_returns_404(unauthed_client):
    resp = await unauthed_client.get("/legal/versions/does-not-exist/terms")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_legal_versions_unknown_doc_type_returns_404(unauthed_client):
    current = (await unauthed_client.get("/legal/current")).json()["version"]
    resp = await unauthed_client.get(f"/legal/versions/{current}/wat")
    assert resp.status_code == 404
