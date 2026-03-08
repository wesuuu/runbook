from app.services.notifications.channels.base import (
    BaseChannel,
    FormattedMessage,
    TransientError,
    PermanentError,
)
from app.services.notifications.channels.console import ConsoleChannel
from app.services.notifications.channels.webhook import WebhookChannel
from app.services.notifications.channels.email import EmailChannel
from app.services.notifications.channels.slack import SlackChannel
from app.services.notifications.channels.teams import TeamsChannel
from app.services.notifications.channels.discord import DiscordChannel

CHANNEL_REGISTRY: dict[str, type[BaseChannel]] = {
    "CONSOLE": ConsoleChannel,
    "WEBHOOK": WebhookChannel,
    "EMAIL": EmailChannel,
    "SLACK": SlackChannel,
    "TEAMS": TeamsChannel,
    "DISCORD": DiscordChannel,
}


def get_channel(channel_type: str, config: dict) -> BaseChannel:
    """Instantiate the appropriate channel adapter."""
    cls = CHANNEL_REGISTRY.get(channel_type)
    if cls is None:
        raise ValueError(f"Unknown channel type: {channel_type}")
    return cls(config)
