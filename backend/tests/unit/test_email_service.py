from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_service import SMTPProvider, get_email_provider


@pytest.mark.asyncio
async def test_smtp_provider_sends_email():
    """SMTPProvider constructs correct MIME message and calls aiosmtplib."""
    with patch("app.services.email_service.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = ({}, "OK")
        provider = SMTPProvider(
            host="localhost", port=1025, from_addr="noreply@test.com"
        )
        await provider.send(
            to="user@test.com",
            subject="Test Subject",
            html_body="<h1>Hello</h1>",
            text_body="Hello",
        )
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["To"] == "user@test.com"
        assert msg["From"] == "noreply@test.com"
        assert msg["Subject"] == "Test Subject"


@pytest.mark.asyncio
async def test_smtp_provider_passes_credentials():
    """SMTPProvider passes user/password/tls to aiosmtplib."""
    with patch("app.services.email_service.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = ({}, "OK")
        provider = SMTPProvider(
            host="smtp.example.com",
            port=587,
            from_addr="noreply@example.com",
            user="apikey",
            password="secret",
            use_tls=True,
        )
        await provider.send(
            to="user@test.com",
            subject="Test",
            html_body="<p>Hi</p>",
            text_body="Hi",
        )
        kwargs = mock_send.call_args[1]
        assert kwargs["hostname"] == "smtp.example.com"
        assert kwargs["port"] == 587
        assert kwargs["username"] == "apikey"
        assert kwargs["password"] == "secret"
        assert kwargs["start_tls"] is True


def test_get_email_provider_returns_smtp():
    """Factory returns SMTPProvider by default."""
    provider = get_email_provider()
    assert isinstance(provider, SMTPProvider)
    assert provider.host == "localhost"
    assert provider.port == 1025
