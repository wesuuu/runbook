"""TD-0091c: EmailChannel passes a 10s timeout and converts TimeoutError
to TransientError so the retry sweep can pick it up."""

import asyncio
from unittest.mock import patch

import pytest

from app.services.core.notifications.channels.base import (
    FormattedMessage,
    TransientError,
)
from app.services.core.notifications.channels.email import EmailChannel


def _msg():
    return FormattedMessage(
        event_type="TEST", title="t", body="b", recipient="x@y.example",
    )


@pytest.mark.asyncio
async def test_smtp_timeout_raises_transient_error():
    channel = EmailChannel({"smtp_host": "1.2.3.4", "smtp_port": 25})

    async def boom(*a, **kw):
        raise asyncio.TimeoutError()

    with patch("aiosmtplib.send", side_effect=boom):
        with pytest.raises(TransientError, match="smtp_timeout"):
            await channel.send(_msg())


@pytest.mark.asyncio
async def test_smtp_send_passes_timeout_kwarg():
    channel = EmailChannel({"smtp_host": "localhost", "smtp_port": 1025})
    captured: dict = {}

    async def fake_send(*args, **kwargs):
        captured.update(kwargs)
        return "OK"

    with patch("aiosmtplib.send", side_effect=fake_send):
        await channel.send(_msg())
    assert captured.get("timeout") == 10
