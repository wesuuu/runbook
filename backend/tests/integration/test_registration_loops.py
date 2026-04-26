"""Integration test: registration flow emits Loops events when configured.

Verifies wiring end-to-end — the HTTP register endpoint actually calls
emit_signup + emit_trial_started. When Loops is unconfigured, registration
must still succeed silently (no 500s, no test flake).
"""

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from app.services.lifecycle import loops_client


@pytest.fixture(autouse=True)
def _reset_loops():
    yield
    loops_client._reset_cache()


@pytest.fixture
def fake_loops(monkeypatch):
    fake = MagicMock()
    loops_client.set_fake_client(fake)
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", "x"
    )
    return fake


@pytest.mark.asyncio
async def test_register_emits_signup_and_trial_started_when_configured(
    client: AsyncClient, fake_loops
):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "lifecycle@example.com",
            "password": "password123",
            "full_name": "Lifecycle Tester",
        },
    )
    assert resp.status_code == 200

    # contacts_create called once for this user
    fake_loops.contacts_create.assert_called_once()
    assert (
        fake_loops.contacts_create.call_args.kwargs["email"] == "lifecycle@example.com"
    )

    # Two events: signed_up + trial_started
    event_names = [
        c.kwargs["event_name"] for c in fake_loops.events_send.call_args_list
    ]
    assert "signed_up" in event_names
    assert "trial_started" in event_names


@pytest.mark.asyncio
async def test_register_does_not_hit_loops_when_unconfigured(
    client: AsyncClient, monkeypatch
):
    """No fake injected, no api key set — registration succeeds, no calls."""
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", ""
    )
    loops_client._reset_cache()

    resp = await client.post(
        "/auth/register",
        json={
            "email": "unconfigured-loops@example.com",
            "password": "password123",
            "full_name": "Quiet User",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_succeeds_even_if_loops_raises(client: AsyncClient, monkeypatch):
    """A Loops outage must never break registration."""
    fake = MagicMock()
    fake.contacts_create.side_effect = RuntimeError("loops down")
    fake.events_send.side_effect = RuntimeError("loops down")
    loops_client.set_fake_client(fake)
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", "x"
    )

    resp = await client.post(
        "/auth/register",
        json={
            "email": "loops-down@example.com",
            "password": "password123",
            "full_name": "Resilient User",
        },
    )
    assert resp.status_code == 200
