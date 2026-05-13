"""Heartbeat receiver endpoint — token check + last_heartbeat_at update."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.library import Document


@pytest.mark.asyncio
async def test_heartbeat_updates_last_heartbeat_at(
    async_session, seed_document_extracting
):
    doc: Document = seed_document_extracting
    doc.heartbeat_token = "test-token-abc"
    await async_session.commit()

    # Override the DB dep so the endpoint sees the same session + data
    from app.db.session import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/internal/extraction/{doc.id}/heartbeat",
                json={"ts": datetime.now(timezone.utc).isoformat()},
                headers={"X-Heartbeat-Token": "test-token-abc"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    await async_session.refresh(doc)
    assert doc.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_rejects_bad_token(async_session, seed_document_extracting):
    doc: Document = seed_document_extracting
    doc.heartbeat_token = "real-token"
    await async_session.commit()

    from app.db.session import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/internal/extraction/{doc.id}/heartbeat",
                json={"ts": datetime.now(timezone.utc).isoformat()},
                headers={"X-Heartbeat-Token": "wrong-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_heartbeat_rejects_unknown_document(async_session):
    from app.db.session import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/internal/extraction/{uuid.uuid4()}/heartbeat",
                json={"ts": datetime.now(timezone.utc).isoformat()},
                headers={"X-Heartbeat-Token": "anything"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
