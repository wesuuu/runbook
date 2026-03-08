import logging

from app.services.notifications.channels.base import BaseChannel, FormattedMessage

logger = logging.getLogger("notifications.console")


class ConsoleChannel(BaseChannel):
    """Dev-only channel that logs notifications to stdout."""

    async def send(self, message: FormattedMessage) -> str:
        output = (
            f"\n{'─' * 50}\n"
            f"📨 NOTIFICATION [{message.event_type}]\n"
            f"   To: {message.recipient}\n"
            f"   Title: {message.title}\n"
            f"   Body: {message.body}\n"
        )
        if message.url:
            output += f"   URL: {message.url}\n"
        output += f"{'─' * 50}"
        logger.info(output)
        return "logged"
