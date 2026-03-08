import logging

import httpx

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
)

logger = logging.getLogger("notifications.discord")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class DiscordChannel(BaseChannel):
    """Discord webhook channel.

    Config:
        webhook_url (str): Discord webhook URL.
    """

    async def send(self, message: FormattedMessage) -> str:
        url = self.config.get("webhook_url")
        if not url:
            raise PermanentError("Discord webhook URL not configured")

        # Discord rich embed format
        embed = {
            "title": message.title,
            "description": message.body,
            "color": 0x2563EB,  # Blue accent
        }
        if message.url:
            embed["url"] = message.url

        payload = {
            "embeds": [embed],
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)

            if resp.status_code == 429:
                raise TransientError("Discord rate limited (429)")
            if resp.status_code >= 500:
                raise TransientError(f"Discord {resp.status_code}")
            if resp.status_code in (401, 403, 404):
                raise PermanentError(
                    f"Discord {resp.status_code}: invalid webhook"
                )
            if resp.status_code >= 400:
                raise PermanentError(
                    f"Discord {resp.status_code}: {resp.text[:200]}"
                )

            return f"{resp.status_code} OK"

        except httpx.TimeoutException as e:
            raise TransientError(f"Discord timeout: {e}") from e
        except httpx.ConnectError as e:
            raise TransientError(f"Discord connection error: {e}") from e
