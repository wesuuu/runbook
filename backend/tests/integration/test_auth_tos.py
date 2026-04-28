"""Integration tests for POST /auth/accept-tos."""

import pytest
from sqlalchemy import select

from app.legal.service import get_current_version
from app.models.execution import AuditLog


@pytest.mark.asyncio
async def test_accept_tos_requires_auth(client):
    resp = await client.post("/auth/accept-tos")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_accept_tos_sets_user_fields(client, auth_headers, test_user, db_session):
    resp = await client.post("/auth/accept-tos", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tos_version"] == get_current_version()
    assert body["tos_accepted_at"] is not None
    assert body["tos_current"] is True

    # Verify in DB
    await db_session.refresh(test_user)
    assert test_user.tos_version == get_current_version()
    assert test_user.tos_accepted_at is not None


@pytest.mark.asyncio
async def test_accept_tos_writes_audit_log(client, auth_headers, test_user, db_session):
    resp = await client.post(
        "/auth/accept-tos",
        headers={**auth_headers, "User-Agent": "test-suite/1.0"},
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "user")
        .where(AuditLog.entity_id == test_user.id)
        .where(AuditLog.action == "ACCEPT_TOS")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == test_user.id
    assert row.changes["version"] == get_current_version()
    assert row.changes["user_agent"] == "test-suite/1.0"
    assert "ip_address" in row.changes


@pytest.mark.asyncio
async def test_accept_tos_idempotent_writes_two_audit_rows(
    client, auth_headers, test_user, db_session
):
    await client.post("/auth/accept-tos", headers=auth_headers)
    await client.post("/auth/accept-tos", headers=auth_headers)

    result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "user")
        .where(AuditLog.entity_id == test_user.id)
        .where(AuditLog.action == "ACCEPT_TOS")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    # User row still has only the latest acceptance
    await db_session.refresh(test_user)
    assert test_user.tos_version == get_current_version()


@pytest.mark.asyncio
async def test_auth_me_reports_tos_current_after_acceptance(
    client, auth_headers, test_user, db_session
):
    me_before = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me_before["tos_current"] is False

    await client.post("/auth/accept-tos", headers=auth_headers)

    me_after = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me_after["tos_current"] is True
    assert me_after["tos_version"] == get_current_version()
