import asyncio
import html as _html
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings
from app.services.core.notifications.channels.base import (
    BaseChannel,
    FormattedMessage,
    PermanentError,
    TransientError,
)

logger = logging.getLogger("notifications.email")


class EmailChannel(BaseChannel):
    """SMTP email channel.

    Config:
        smtp_host (str): SMTP server hostname. Default: localhost.
        smtp_port (int): SMTP server port. Default: 1025 (Mailpit dev).
        smtp_user (str): Optional. SMTP username.
        smtp_pass (str): Optional. SMTP password.
        use_tls (bool): Use STARTTLS. Default: False.
        from_address (str): Sender address. Default: noreply@batchrite.local.
    """

    async def send(self, message: FormattedMessage) -> str:
        if not settings.notification_email_enabled:
            raise PermanentError(
                "Email delivery disabled by ops kill-switch"
            )

        host = self.config.get("smtp_host", "localhost")
        port = self.config.get("smtp_port", 1025)
        user = self.config.get("smtp_user")
        password = self.config.get("smtp_pass")
        use_tls = self.config.get("use_tls", False)
        from_addr = self.config.get("from_address", "noreply@batchrite.local")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.title
        msg["From"] = from_addr
        msg["To"] = message.recipient
        msg["List-Unsubscribe"] = (
            f"<mailto:{settings.notification_unsubscribe_mailto}>"
        )
        # NOTE: do not set List-Unsubscribe-Post until a signed-token POST
        # endpoint exists per RFC 8058.

        text_body = message.body
        if message.url:
            text_body += f"\n\nView in Batchrite: {message.url}"

        manage_url = f"{settings.frontend_url.rstrip('/')}/settings/notifications"
        if message.html_body:
            html_inner = message.html_body
        else:
            url_link = (
                f"<p><a href='{_html.escape(message.url)}' "
                f"style='color: #2563eb;'>View in Batchrite</a></p>"
                if message.url
                else ""
            )
            html_inner = (
                f"<h2 style=\"color: #1a1a1a;\">{_html.escape(message.title)}</h2>"
                f"<p style=\"color: #333; line-height: 1.6;\">"
                f"{_html.escape(message.body)}</p>{url_link}"
            )
        html_footer = (
            "<hr style=\"border: none; border-top: 1px solid #e5e7eb; "
            "margin-top: 24px;\">"
            "<p style=\"color: #9ca3af; font-size: 12px;\">"
            "Batchrite — Laboratory Execution System. "
            f"<a href=\"{_html.escape(manage_url)}\" "
            "style=\"color: #6b7280;\">Manage preferences</a>."
            "</p>"
        )
        html_body = (
            f"<div style=\"font-family: sans-serif; max-width: 600px;\">"
            f"{html_inner}{html_footer}</div>"
        )

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            response = await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user,
                password=password,
                start_tls=use_tls,
                timeout=10,
            )
            return str(response)
        except aiosmtplib.SMTPAuthenticationError as e:
            raise PermanentError(f"SMTP auth failed: {e}") from e
        except aiosmtplib.SMTPRecipientsRefused as e:
            raise PermanentError(f"Invalid recipient: {e}") from e
        except (
            aiosmtplib.SMTPConnectError,
            TimeoutError,
            asyncio.TimeoutError,
        ) as e:
            raise TransientError(f"smtp_timeout: {e}") from e
        except aiosmtplib.SMTPException as e:
            raise TransientError(f"SMTP error: {e}") from e
