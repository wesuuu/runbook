import logging
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailProvider(ABC):
    """Abstract base for email providers. Subclass for SendGrid, SES, etc."""

    @abstractmethod
    async def send(
        self, to: str, subject: str, html_body: str, text_body: str
    ) -> None: ...


class SMTPProvider(EmailProvider):
    def __init__(
        self,
        host: str,
        port: int,
        from_addr: str,
        user: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
    ):
        self.host = host
        self.port = port
        self.from_addr = from_addr
        self.user = user
        self.password = password
        self.use_tls = use_tls

    async def send(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.user or None,
            password=self.password or None,
            start_tls=self.use_tls,
        )


def get_email_provider() -> EmailProvider:
    """Factory — returns the configured email provider."""
    return SMTPProvider(
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_addr=settings.smtp_from,
        user=settings.smtp_user or None,
        password=settings.smtp_pass or None,
        use_tls=settings.smtp_tls,
    )


async def send_invitation_email(
    to_email: str,
    org_name: str,
    inviter_name: str,
    token: str,
) -> None:
    """Send org invitation email. Fire-and-forget."""
    from datetime import datetime, timedelta, timezone

    from app.services.core.notifications.templates import invite_html

    accept_url = f"{settings.backend_url}/auth/accept-invite?token={token}"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=settings.invitation_ttl_days)
    ).date().isoformat()
    html_body = invite_html(org_name, inviter_name, accept_url, expires_at)
    text_body = (
        f"{inviter_name} has invited you to join {org_name} on Batchrite.\n\n"
        f"Accept the invitation: {accept_url}\n\n"
        f"This invitation expires in {settings.invitation_ttl_days} days."
    )
    try:
        provider = get_email_provider()
        await provider.send(
            to=to_email,
            subject=f"You've been invited to {org_name} — Batchrite",
            html_body=html_body,
            text_body=text_body,
        )
    except Exception:
        logger.exception("Failed to send invitation email to %s", to_email)
