import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
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
        from_address (str): Sender address. Default: noreply@runbook.local.
    """

    async def send(self, message: FormattedMessage) -> str:
        host = self.config.get("smtp_host", "localhost")
        port = self.config.get("smtp_port", 1025)
        user = self.config.get("smtp_user")
        password = self.config.get("smtp_pass")
        use_tls = self.config.get("use_tls", False)
        from_addr = self.config.get("from_address", "noreply@runbook.local")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.title
        msg["From"] = from_addr
        msg["To"] = message.recipient

        text_body = message.body
        if message.url:
            text_body += f"\n\nView in Runbook: {message.url}"

        html_body = f"""<div style="font-family: sans-serif; max-width: 600px;">
  <h2 style="color: #1a1a1a;">{message.title}</h2>
  <p style="color: #333; line-height: 1.6;">{message.body}</p>
  {"<p><a href='" + message.url + "' style='color: #2563eb;'>View in Runbook</a></p>" if message.url else ""}
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin-top: 24px;">
  <p style="color: #9ca3af; font-size: 12px;">Runbook AI Co-Pilot</p>
</div>"""

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
            )
            return str(response)
        except aiosmtplib.SMTPAuthenticationError as e:
            raise PermanentError(f"SMTP auth failed: {e}") from e
        except aiosmtplib.SMTPRecipientsRefused as e:
            raise PermanentError(f"Invalid recipient: {e}") from e
        except (aiosmtplib.SMTPConnectError, TimeoutError) as e:
            raise TransientError(f"SMTP connection error: {e}") from e
        except aiosmtplib.SMTPException as e:
            raise TransientError(f"SMTP error: {e}") from e
