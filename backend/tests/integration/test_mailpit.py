"""Mailpit integration test — sends a real email via SMTP and verifies delivery.

Run with: pytest -m mailpit
Requires Mailpit running on localhost:1025 (SMTP) and localhost:8025 (API).
"""

import httpx
import pytest

from app.services.email_service import SMTPProvider


@pytest.mark.mailpit
@pytest.mark.asyncio
async def test_verification_email_arrives_in_mailpit():
    """Send a real email via SMTP and verify it arrives in Mailpit."""
    mailpit_api = "http://localhost:8025"
    test_email = "mailpit-test@example.com"

    # Clear Mailpit inbox first
    async with httpx.AsyncClient() as http:
        await http.delete(f"{mailpit_api}/api/v1/messages")

    # Send via SMTPProvider
    provider = SMTPProvider(
        host="localhost",
        port=1025,
        from_addr="noreply@batchrite.local",
    )
    await provider.send(
        to=test_email,
        subject="Verify your email — Batchrite",
        html_body='<p>Click <a href="http://localhost:8000/auth/verify-email?token=test123">here</a></p>',
        text_body="Verify: http://localhost:8000/auth/verify-email?token=test123",
    )

    # Check Mailpit API
    async with httpx.AsyncClient() as http:
        res = await http.get(f"{mailpit_api}/api/v1/messages")
        data = res.json()

    assert data["total"] >= 1
    msg = data["messages"][0]
    assert msg["To"][0]["Address"] == test_email
    assert "Verify" in msg["Subject"]

    # Cleanup
    async with httpx.AsyncClient() as http:
        await http.delete(f"{mailpit_api}/api/v1/messages")
