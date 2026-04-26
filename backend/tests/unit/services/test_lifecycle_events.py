"""Unit tests for lifecycle event shape correctness.

The events layer is a thin translator: Organization + User -> Loops call.
Tests assert exact event names, contact property names, and payload content
so campaign triggers in the Loops dashboard stay in sync with what we emit.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.iam import Organization, User
from app.services.lifecycle import events, loops_client


@pytest.fixture(autouse=True)
def _fake_loops():
    fake = MagicMock()
    loops_client.set_fake_client(fake)
    yield fake
    loops_client._reset_cache()


def _make_user(**overrides) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        email="alice@example.com",
        full_name="Alice Smith",
    )
    defaults.update(overrides)
    return User(**defaults)


def _make_org(**overrides) -> Organization:
    defaults = dict(
        id=uuid.uuid4(),
        name="Acme Labs",
        subscription_tier="essentials",
        subscription_status="trialing",
        trial_end=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Organization(**defaults)


def test_emit_signup_creates_contact_and_sends_event(_fake_loops):
    org = _make_org()
    user = _make_user()

    events.emit_signup(user, org)

    # Contact created with all synced properties
    _fake_loops.contacts_create.assert_called_once()
    call = _fake_loops.contacts_create.call_args
    assert call.kwargs["email"] == "alice@example.com"
    props = call.kwargs["properties"]
    assert props["firstName"] == "Alice"
    assert props["org_id"] == str(org.id)
    assert props["org_name"] == "Acme Labs"
    assert props["plan"] == "essentials"
    assert props["status"] == "trialing"
    assert props["trial_end"] == "2026-05-24"
    assert "days_in_trial" in props

    # Signup event emitted
    _fake_loops.events_send.assert_called_once()
    ev = _fake_loops.events_send.call_args
    assert ev.kwargs["email"] == "alice@example.com"
    assert ev.kwargs["event_name"] == "signed_up"


def test_emit_signup_handles_missing_full_name(_fake_loops):
    user = _make_user(full_name=None)
    events.emit_signup(user, _make_org())

    props = _fake_loops.contacts_create.call_args.kwargs["properties"]
    # firstName absent (not None) when full_name is missing
    assert "firstName" not in props


def test_emit_trial_started_sends_trial_started_event(_fake_loops):
    user = _make_user()
    org = _make_org()

    events.emit_trial_started(user, org)

    _fake_loops.events_send.assert_called_once()
    ev = _fake_loops.events_send.call_args
    assert ev.kwargs["event_name"] == "trial_started"
    assert ev.kwargs["email"] == "alice@example.com"
    # contact_properties should include trial_end so the Loops "trial ending
    # in N days" workflow condition has fresh data.
    cp = ev.kwargs["contact_properties"]
    assert cp["trial_end"] == "2026-05-24"
    assert cp["plan"] == "essentials"


def test_emit_subscription_changed_emits_event_and_updates_contact(_fake_loops):
    user = _make_user()
    org = _make_org(subscription_tier="pro", subscription_status="active")

    events.emit_subscription_changed(
        user,
        org,
        before={"tier": "essentials", "status": "trialing"},
        after={"tier": "pro", "status": "active"},
    )

    _fake_loops.events_send.assert_called_once()
    ev = _fake_loops.events_send.call_args
    assert ev.kwargs["event_name"] == "subscription_changed"
    ep = ev.kwargs["event_properties"]
    assert ep["previous_plan"] == "essentials"
    assert ep["new_plan"] == "pro"
    assert ep["previous_status"] == "trialing"
    assert ep["new_status"] == "active"

    cp = ev.kwargs["contact_properties"]
    assert cp["plan"] == "pro"
    assert cp["status"] == "active"


def test_emit_trial_expired_emits_event(_fake_loops):
    user = _make_user()
    org = _make_org(subscription_status="canceled")

    events.emit_trial_expired(user, org)

    _fake_loops.events_send.assert_called_once()
    ev = _fake_loops.events_send.call_args
    assert ev.kwargs["event_name"] == "trial_expired"
    cp = ev.kwargs["contact_properties"]
    assert cp["status"] == "canceled"


def test_emit_signup_no_op_when_unconfigured(monkeypatch):
    """When Loops is unconfigured, events layer still calls loops_client --
    the no-op happens in loops_client itself (tests there). This ensures no
    pre-check in events.py causes inconsistent behavior between configured/
    unconfigured environments."""
    # Remove the fake so it falls through to the real path
    loops_client._reset_cache()
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", ""
    )

    # Must not raise
    events.emit_signup(_make_user(), _make_org())
