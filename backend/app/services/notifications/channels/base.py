from abc import ABC, abstractmethod
from dataclasses import dataclass


class TransientError(Exception):
    """Retryable failure (timeouts, rate limits, 5xx)."""
    pass


class PermanentError(Exception):
    """Non-retryable failure (bad credentials, invalid config)."""
    pass


@dataclass
class FormattedMessage:
    event_type: str
    title: str
    body: str
    recipient: str  # email, channel name, webhook URL, etc.
    url: str = ""   # deep link back into the app


class BaseChannel(ABC):
    """Interface that all notification channels implement."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def send(self, message: FormattedMessage) -> str:
        """Send the message. Returns a provider-specific receipt string.

        Raises:
            TransientError: Retryable failure.
            PermanentError: Non-retryable failure.
        """
        ...

    async def test(self) -> str:
        """Send a test message to validate the channel config."""
        msg = FormattedMessage(
            event_type="TEST",
            title="Test Notification",
            body="This is a test notification from Runbook.",
            recipient="test",
        )
        return await self.send(msg)
