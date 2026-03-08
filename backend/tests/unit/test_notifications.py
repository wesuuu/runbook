"""Unit tests for the notification service layer."""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
)
from app.services.notifications.channels.console import ConsoleChannel
from app.services.notifications.channels.webhook import WebhookChannel
from app.services.notifications.templates import TEMPLATES


# ── Template Tests ───────────────────────────────────────────────────────

class TestTemplates:
    def test_all_event_types_have_templates(self):
        from app.models.notifications import NotificationEventType
        for evt in NotificationEventType:
            assert evt.value in TEMPLATES, f"Missing template for {evt.value}"

    def test_role_assigned_personal(self):
        title, body = TEMPLATES["ROLE_ASSIGNED"](
            {"run_name": "Run-1", "role_name": "Upstream Lead",
             "assigned_by": "Alice"},
            personal=True,
        )
        assert "Run-1" in title
        assert "Upstream Lead" in body
        assert "You've been assigned" in body

    def test_role_assigned_broadcast(self):
        title, body = TEMPLATES["ROLE_ASSIGNED"](
            {"run_name": "Run-1", "role_name": "Upstream Lead",
             "assigned_by": "Alice", "assignee_name": "Bob"},
            personal=False,
        )
        assert "Bob" in body
        assert "You" not in body

    def test_run_started_personal(self):
        title, body = TEMPLATES["RUN_STARTED"](
            {"run_name": "CHO-042", "started_by": "Alice"},
            personal=True,
        )
        assert "CHO-042" in title
        assert "assigned" in body.lower()

    def test_run_completed(self):
        title, body = TEMPLATES["RUN_COMPLETED"](
            {"run_name": "CHO-042", "completed_by": "Alice"},
        )
        assert "completed" in title.lower()

    def test_invite_sent(self):
        title, body = TEMPLATES["INVITE_SENT"](
            {"org_name": "Trellis Bio", "invited_by": "Admin"},
        )
        assert "Trellis Bio" in title
        assert "invited" in body.lower()

    def test_protocol_reverted(self):
        title, body = TEMPLATES["PROTOCOL_REVERTED"](
            {"protocol_name": "CHO Protocol v2", "edited_by": "Scientist"},
        )
        assert "DRAFT" in body

    def test_step_deviation(self):
        title, body = TEMPLATES["STEP_DEVIATION"](
            {"run_name": "Run-1", "step_name": "pH Adjustment",
             "edited_by": "Alice"},
        )
        assert "pH Adjustment" in body
        assert "post-completion" in body


# ── Console Channel Tests ────────────────────────────────────────────────

class TestConsoleChannel:
    @pytest.mark.asyncio
    async def test_send_logs_message(self, caplog):
        channel = ConsoleChannel({})
        msg = FormattedMessage(
            event_type="TEST",
            title="Test Title",
            body="Test body",
            recipient="user@example.com",
        )
        with caplog.at_level("INFO", logger="notifications.console"):
            result = await channel.send(msg)

        assert result == "logged"
        assert "Test Title" in caplog.text

    @pytest.mark.asyncio
    async def test_send_includes_url(self, caplog):
        channel = ConsoleChannel({})
        msg = FormattedMessage(
            event_type="TEST",
            title="Title",
            body="Body",
            recipient="test",
            url="http://localhost:5173/#/runs/abc",
        )
        with caplog.at_level("INFO", logger="notifications.console"):
            await channel.send(msg)

        assert "http://localhost:5173/#/runs/abc" in caplog.text


# ── Webhook Channel Tests ────────────────────────────────────────────────

class TestWebhookChannel:
    @pytest.mark.asyncio
    async def test_missing_url_raises_permanent(self):
        channel = WebhookChannel({})
        msg = FormattedMessage(
            event_type="TEST", title="T", body="B", recipient="test",
        )
        with pytest.raises(PermanentError, match="URL not configured"):
            await channel.send(msg)

    @pytest.mark.asyncio
    async def test_successful_send(self):
        channel = WebhookChannel({"url": "http://localhost:8000/dev/webhook-echo"})
        msg = FormattedMessage(
            event_type="TEST", title="T", body="B", recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await channel.send(msg)
        assert "200" in result

    @pytest.mark.asyncio
    async def test_5xx_raises_transient(self):
        channel = WebhookChannel({"url": "http://example.com/hook"})
        msg = FormattedMessage(
            event_type="TEST", title="T", body="B", recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(TransientError):
                await channel.send(msg)

    @pytest.mark.asyncio
    async def test_4xx_raises_permanent(self):
        channel = WebhookChannel({"url": "http://example.com/hook"})
        msg = FormattedMessage(
            event_type="TEST", title="T", body="B", recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(PermanentError):
                await channel.send(msg)

    @pytest.mark.asyncio
    async def test_hmac_signature_added(self):
        channel = WebhookChannel({
            "url": "http://example.com/hook",
            "secret": "mysecret",
        })
        msg = FormattedMessage(
            event_type="TEST", title="T", body="B", recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            await channel.send(msg)

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "X-Runbook-Signature" in headers
        assert headers["X-Runbook-Signature"].startswith("sha256=")


# ── FakeChannel for Integration-Style Tests ──────────────────────────────

class FakeChannel(BaseChannel):
    """In-memory channel for testing dispatch logic."""

    def __init__(self):
        super().__init__({})
        self.sent: list[FormattedMessage] = []

    async def send(self, message: FormattedMessage) -> str:
        self.sent.append(message)
        return "fake-ok"
