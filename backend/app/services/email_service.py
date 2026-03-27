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

    async def send(
        self, to: str, subject: str, html_body: str, text_body: str
    ) -> None:
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
