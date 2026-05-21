"""Unit tests for the notification service layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.core.notifications.channels.base import (
    BaseChannel,
    FormattedMessage,
    PermanentError,
    TransientError,
)
from app.services.core.notifications.channels.console import ConsoleChannel
from app.services.core.notifications.channels.webhook import WebhookChannel
from app.services.core.notifications.templates import TEMPLATES

from datetime import datetime, timedelta, timezone

from app.models.notifications import (
    DeliveryStatus,
    NotificationChannel,
    NotificationDelivery,
)
from app.services.core.notifications import dispatcher
from app.services.core.notifications.dispatcher import retry_pending

# ── Template Tests ───────────────────────────────────────────────────────


class TestTemplates:
    def test_all_event_types_have_templates(self):
        """Enum and TEMPLATES must stay in exact sync — drift either way fails."""
        from app.models.notifications import NotificationEventType

        enum_values = {e.value for e in NotificationEventType}
        template_keys = set(TEMPLATES.keys())
        assert enum_values == template_keys, (
            f"enum-only: {enum_values - template_keys}; "
            f"template-only: {template_keys - enum_values}"
        )

    def test_role_assigned_personal(self):
        title, body = TEMPLATES["ROLE_ASSIGNED"](
            {"run_name": "Run-1", "role_name": "Upstream Lead", "assigned_by": "Alice"},
            personal=True,
        )
        assert "Run-1" in title
        assert "Upstream Lead" in body
        assert "You've been assigned" in body

    def test_role_assigned_broadcast(self):
        title, body = TEMPLATES["ROLE_ASSIGNED"](
            {
                "run_name": "Run-1",
                "role_name": "Upstream Lead",
                "assigned_by": "Alice",
                "assignee_name": "Bob",
            },
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
            {"org_name": "Batchrite", "invited_by": "Admin"},
        )
        assert "Batchrite" in title
        assert "invited" in body.lower()

    def test_protocol_reverted(self):
        title, body = TEMPLATES["PROTOCOL_REVERTED"](
            {"protocol_name": "CHO Protocol v2", "edited_by": "Scientist"},
        )
        assert "DRAFT" in body

    def test_step_deviation(self):
        title, body = TEMPLATES["STEP_DEVIATION"](
            {"run_name": "Run-1", "step_name": "pH Adjustment", "edited_by": "Alice"},
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
            event_type="TEST",
            title="T",
            body="B",
            recipient="test",
        )
        with pytest.raises(PermanentError, match="URL not configured"):
            await channel.send(msg)

    @pytest.mark.asyncio
    async def test_successful_send(self):
        channel = WebhookChannel({"url": "http://localhost:8000/dev/webhook-echo"})
        msg = FormattedMessage(
            event_type="TEST",
            title="T",
            body="B",
            recipient="test",
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
            event_type="TEST",
            title="T",
            body="B",
            recipient="test",
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
            event_type="TEST",
            title="T",
            body="B",
            recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(PermanentError):
                await channel.send(msg)

    @pytest.mark.asyncio
    async def test_hmac_signature_added(self):
        channel = WebhookChannel(
            {
                "url": "http://example.com/hook",
                "secret": "mysecret",
            }
        )
        msg = FormattedMessage(
            event_type="TEST",
            title="T",
            body="B",
            recipient="test",
        )

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            await channel.send(msg)

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "X-Batchrite-Signature" in headers
        assert headers["X-Batchrite-Signature"].startswith("sha256=")


# ── FakeChannel for Integration-Style Tests ──────────────────────────────


class FakeChannel(BaseChannel):
    """In-memory channel for testing dispatch logic."""

    def __init__(self):
        super().__init__({})
        self.sent: list[FormattedMessage] = []

    async def send(self, message: FormattedMessage) -> str:
        self.sent.append(message)
        return "fake-ok"


# ── FailingChannel for retry_pending tests ───────────────────────────────


class FailingChannel(BaseChannel):
    """Channel double that always raises the configured error on send."""

    def __init__(self, error: Exception):
        super().__init__({})
        self._error = error

    async def send(self, message: FormattedMessage) -> str:
        raise self._error


# ── retry_pending Tests (Fix 2) ──────────────────────────────────────────


class TestRetryPending:
    """retry_pending drains due RETRYING deliveries with batch isolation."""

    async def _make_channel(self, db_session, test_user, channel_type="CONSOLE",
                            enabled=True):
        channel = NotificationChannel(
            user_id=test_user.id,
            name="Retry Test Channel",
            channel_type=channel_type,
            config={},
            enabled=enabled,
        )
        db_session.add(channel)
        await db_session.flush()
        return channel

    async def _make_delivery(self, db_session, channel, attempts=1,
                             due_offset_seconds=-30):
        delivery = NotificationDelivery(
            channel_id=channel.id,
            event_type="RUN_STARTED",
            recipient_info={"recipient": "x@example.com"},
            status=DeliveryStatus.RETRYING,
            attempts=attempts,
            next_retry_at=datetime.now(timezone.utc)
            + timedelta(seconds=due_offset_seconds),
        )
        db_session.add(delivery)
        await db_session.flush()
        return delivery

    @pytest.mark.asyncio
    async def test_due_delivery_is_retried_and_sent(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.SENT

    @pytest.mark.asyncio
    async def test_not_yet_due_delivery_is_skipped(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(
            db_session, channel, due_offset_seconds=3600
        )

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.RETRYING

    @pytest.mark.asyncio
    async def test_transient_failure_stays_retrying(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        delivery = await self._make_delivery(db_session, channel, attempts=1)
        original_retry_at = delivery.next_retry_at

        with patch(
            "app.services.core.notifications.dispatcher.get_channel",
            return_value=FailingChannel(TransientError("network blip")),
        ):
            count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.RETRYING
        assert delivery.attempts == 2
        assert delivery.next_retry_at > original_retry_at

    @pytest.mark.asyncio
    async def test_transient_failure_on_last_attempt_fails(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user)
        # attempts=2 => _execute_send increments to 3 => not < MAX_RETRIES.
        delivery = await self._make_delivery(db_session, channel, attempts=2)

        with patch(
            "app.services.core.notifications.dispatcher.get_channel",
            return_value=FailingChannel(TransientError("still down")),
        ):
            count = await retry_pending(db_session)

        assert count == 1
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_disabled_channel_marks_failed_without_send(
        self, db_session, test_user
    ):
        channel = await self._make_channel(db_session, test_user, enabled=False)
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.status_detail == "Channel disabled or deleted"

    @pytest.mark.asyncio
    async def test_unknown_channel_type_is_isolated(
        self, db_session, test_user
    ):
        """A channel_type not in the registry makes get_channel raise
        ValueError — the row is marked FAILED, the batch is not aborted."""
        channel = await self._make_channel(
            db_session, test_user, channel_type="PIGEON"
        )
        delivery = await self._make_delivery(db_session, channel)

        count = await retry_pending(db_session)

        assert count == 0
        await db_session.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED

    @pytest.mark.asyncio
    async def test_poison_row_does_not_abort_batch(
        self, db_session, test_user
    ):
        """One poison row plus good rows: good rows still SEND and are not
        re-selected on a second sweep."""
        good_channel = await self._make_channel(db_session, test_user)
        poison_channel = await self._make_channel(
            db_session, test_user, channel_type="PIGEON"
        )
        good1 = await self._make_delivery(db_session, good_channel)
        good2 = await self._make_delivery(db_session, good_channel)
        poison = await self._make_delivery(db_session, poison_channel)

        count = await retry_pending(db_session)

        assert count == 2  # two good rows sent; poison row not counted
        for d in (good1, good2):
            await db_session.refresh(d)
            assert d.status == DeliveryStatus.SENT
        await db_session.refresh(poison)
        assert poison.status == DeliveryStatus.FAILED

        # A second sweep finds nothing still RETRYING.
        second_count = await retry_pending(db_session)
        assert second_count == 0

    @pytest.mark.asyncio
    async def test_execute_send_failure_does_not_poison_batch(
        self, db_session, test_user
    ):
        """If _execute_send raises on one row, the per-row SAVEPOINT isolates
        it: that row is marked FAILED and the remaining good rows still SEND
        in the same sweep — no session poisoning, no aborted batch."""
        channel = await self._make_channel(db_session, test_user)
        good1 = await self._make_delivery(db_session, channel)
        poison = await self._make_delivery(db_session, channel)
        good2 = await self._make_delivery(db_session, channel)

        real_execute_send = dispatcher._execute_send

        async def flaky_execute_send(db, delivery, ch, msg):
            # Fail only the poison row; identified by id so the result does
            # not depend on the order rows are processed.
            if delivery.id == poison.id:
                raise RuntimeError("simulated delivery-row failure")
            return await real_execute_send(db, delivery, ch, msg)

        with patch(
            "app.services.core.notifications.dispatcher._execute_send",
            side_effect=flaky_execute_send,
        ):
            count = await retry_pending(db_session)

        assert count == 2  # both good rows sent; poison row not counted
        for d in (good1, good2):
            await db_session.refresh(d)
            assert d.status == DeliveryStatus.SENT
        await db_session.refresh(poison)
        assert poison.status == DeliveryStatus.FAILED


# ── _retry_pending_deliveries sweep wiring (Fix 2) ───────────────────────


class TestRetryPendingDeliveriesSweep:
    """The recovery-loop sweep opens a session, calls retry_pending, commits."""

    @pytest.mark.asyncio
    async def test_sweep_calls_retry_pending_and_commits(self):
        from app.main import _retry_pending_deliveries

        fake_session = AsyncMock()
        session_cm = AsyncMock()
        session_cm.__aenter__.return_value = fake_session
        session_cm.__aexit__.return_value = False
        session_factory = MagicMock(return_value=session_cm)
        retry_mock = AsyncMock(return_value=3)

        with patch(
            "app.db.session.AsyncSessionLocal", session_factory
        ), patch(
            "app.services.core.notifications.dispatcher.retry_pending",
            retry_mock,
        ):
            await _retry_pending_deliveries()

        # Sweep opened exactly one session, ran the retry, and committed.
        session_factory.assert_called_once()
        retry_mock.assert_awaited_once_with(fake_session)
        fake_session.commit.assert_awaited_once()
