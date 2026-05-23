"""TD-0091c: EmailChannel adds List-Unsubscribe (mailto only), a manage-
preferences footer link, and honors FormattedMessage.html_body when set."""

from unittest.mock import patch

import pytest

from app.services.core.notifications.channels.base import (
    FormattedMessage,
    PermanentError,
)
from app.services.core.notifications.channels.email import EmailChannel


def _msg(html_body: str | None = None):
    return FormattedMessage(
        event_type="ROLE_ASSIGNED",
        title="t",
        body="b",
        recipient="x@y.example",
        html_body=html_body,
    )


@pytest.mark.asyncio
async def test_send_includes_list_unsubscribe_mailto_header():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    captured: dict = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(_msg())

    m = captured["message"]
    header = m["List-Unsubscribe"]
    assert header, "List-Unsubscribe header missing"
    assert header.startswith("<mailto:"), header
    assert "@" in header
    # One-Click POST header MUST NOT be set until a signed-token endpoint exists.
    assert m.get("List-Unsubscribe-Post") is None


@pytest.mark.asyncio
async def test_send_html_footer_contains_manage_preferences():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    captured: dict = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(_msg())

    html_part = next(
        p for p in captured["message"].walk()
        if p.get_content_type() == "text/html"
    )
    html = html_part.get_payload(decode=True).decode(html_part.get_content_charset() or "utf-8")
    assert "settings/notifications" in html
    assert "Manage preferences" in html


@pytest.mark.asyncio
async def test_send_uses_provided_html_body_when_present():
    """Producer-supplied html_body (e.g., the invite template) wins over
    the auto-generated boilerplate."""
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    captured: dict = {}

    async def fake_send(message, *args, **kwargs):
        captured["message"] = message
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(_msg(html_body="<p>CUSTOM_BODY_TOKEN</p>"))

    html_part = next(
        p for p in captured["message"].walk()
        if p.get_content_type() == "text/html"
    )
    html = html_part.get_payload(decode=True).decode(html_part.get_content_charset() or "utf-8")
    assert "CUSTOM_BODY_TOKEN" in html
    # Footer still appended.
    assert "Manage preferences" in html


@pytest.mark.asyncio
async def test_kill_switch_raises_permanent_error(monkeypatch):
    """When BATCHRITE_NOTIFICATION_EMAIL_ENABLED=False, send must not call
    SMTP and must raise PermanentError so the delivery is FAILED-not-RETRY."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notification_email_enabled", False)
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})

    called = {"n": 0}

    async def fake_send(*a, **kw):
        called["n"] += 1
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        with pytest.raises(PermanentError, match="kill-switch"):
            await channel.send(_msg())
    assert called["n"] == 0
