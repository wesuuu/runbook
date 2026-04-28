"""End-to-end tests for the two ToS gate bypass mechanisms:
1. Settings.legal_gate_enabled = False  (deployment-level)
2. Organization.legal_terms_overridden = True  (per-org)
"""

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_gate_disabled_makes_tos_current_true(
    client, auth_headers, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "legal_gate_enabled", False)
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me["tos_current"] is True


@pytest.mark.asyncio
async def test_org_override_makes_tos_current_true(
    client, auth_headers, test_user, test_org, db_session
):
    test_org.legal_terms_overridden = True
    await db_session.flush()
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me["tos_current"] is True


@pytest.mark.asyncio
async def test_org_override_false_and_stale_version_means_not_current(
    client, auth_headers, test_user, test_org, db_session
):
    test_org.legal_terms_overridden = False
    test_user.tos_version = None
    await db_session.flush()
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me["tos_current"] is False


@pytest.mark.asyncio
async def test_no_selected_org_falls_back_to_version_check(
    client, auth_headers, test_user, db_session
):
    test_user.selected_org_id = None
    test_user.tos_version = None
    await db_session.flush()
    me = (await client.get("/auth/me", headers=auth_headers)).json()
    assert me["tos_current"] is False
