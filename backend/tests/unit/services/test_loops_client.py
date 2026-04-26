"""Unit tests for the Loops REST wrapper.

Covers the three public calls (contacts_create, contacts_update, events_send),
plus the is_configured + no-op behavior when BATCHRITE_LOOPS_API_KEY is unset.
HTTP is mocked; we never hit the network.
"""

from unittest.mock import MagicMock

import httpx
import pytest

from app.services.lifecycle import loops_client


@pytest.fixture(autouse=True)
def _reset():
    yield
    loops_client._reset_cache()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key",
        "sk_loops_fake",
    )
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_base_url",
        "https://app.loops.so/api/v1",
    )
    loops_client._reset_cache()


def _ok_response(payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=payload if payload is not None else {"success": True},
        request=httpx.Request("POST", "https://app.loops.so/api/v1/x"),
    )


def test_is_configured_true_when_key_set(monkeypatch):
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", "x"
    )
    assert loops_client.is_configured() is True


def test_is_configured_false_when_key_missing(monkeypatch):
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", ""
    )
    assert loops_client.is_configured() is False


def test_contacts_create_posts_email_and_properties(configured, monkeypatch):
    calls = []

    def fake_post(self, url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers})
        return _ok_response()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    loops_client.contacts_create(
        email="alice@example.com",
        properties={"firstName": "Alice", "org_id": "abc"},
    )

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/contacts/create")
    assert calls[0]["json"]["email"] == "alice@example.com"
    assert calls[0]["json"]["firstName"] == "Alice"
    assert calls[0]["json"]["org_id"] == "abc"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk_loops_fake"


def test_contacts_update_posts_email_and_properties(configured, monkeypatch):
    calls = []

    def fake_post(self, url, json, headers, timeout):
        calls.append({"url": url, "json": json})
        return _ok_response()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    loops_client.contacts_update(email="bob@example.com", properties={"plan": "pro"})

    assert calls[0]["url"].endswith("/contacts/update")
    assert calls[0]["json"] == {"email": "bob@example.com", "plan": "pro"}


def test_events_send_posts_event_name_and_properties(configured, monkeypatch):
    calls = []

    def fake_post(self, url, json, headers, timeout):
        calls.append({"url": url, "json": json})
        return _ok_response()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    loops_client.events_send(
        email="carol@example.com",
        event_name="signed_up",
        event_properties={"source": "web"},
        contact_properties={"plan": "essentials", "org_id": "org123"},
    )

    assert calls[0]["url"].endswith("/events/send")
    body = calls[0]["json"]
    assert body["email"] == "carol@example.com"
    assert body["eventName"] == "signed_up"
    assert body["eventProperties"] == {"source": "web"}
    # Loops accepts contact properties on events/send too (merged into contact)
    assert body["plan"] == "essentials"
    assert body["org_id"] == "org123"


def test_noop_when_unconfigured(monkeypatch):
    """All three methods must no-op (and not crash) when api key is empty."""
    monkeypatch.setattr(
        "app.services.lifecycle.loops_client.settings.loops_api_key", ""
    )
    loops_client._reset_cache()

    sentinel = MagicMock()

    def fake_post(*args, **kwargs):
        sentinel(*args, **kwargs)
        return _ok_response()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    loops_client.contacts_create(email="x@example.com", properties={})
    loops_client.contacts_update(email="x@example.com", properties={})
    loops_client.events_send(
        email="x@example.com",
        event_name="signed_up",
        event_properties={},
        contact_properties={},
    )

    sentinel.assert_not_called()


def test_http_error_is_swallowed_and_logged(configured, monkeypatch, caplog):
    """A non-2xx response must be logged and swallowed; never raise upward.

    Lifecycle is fire-and-forget -- Loops being down should never break
    user-facing flows like registration or webhook handling.
    """

    def fake_post(self, url, json, headers, timeout):
        return httpx.Response(
            status_code=500,
            json={"message": "internal error"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    import logging

    with caplog.at_level(logging.WARNING):
        loops_client.contacts_create(email="err@example.com", properties={})

    assert any("loops" in r.message.lower() for r in caplog.records)


def test_network_error_is_swallowed(configured, monkeypatch):
    """Network-level exceptions must also be swallowed."""

    def fake_post(self, url, json, headers, timeout):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    # Should not raise
    loops_client.contacts_create(email="err@example.com", properties={})


def test_set_fake_client_for_tests():
    """set_fake_client injects a MagicMock-like recorder for tests to inspect."""
    fake = MagicMock()
    loops_client.set_fake_client(fake)

    loops_client.contacts_create(email="a@b.com", properties={"x": 1})

    fake.contacts_create.assert_called_once_with(email="a@b.com", properties={"x": 1})
