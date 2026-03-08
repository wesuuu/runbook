import logging

import httpx

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
)

logger = logging.getLogger("notifications.teams")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class TeamsChannel(BaseChannel):
    """Microsoft Teams incoming webhook channel.

    Config:
        webhook_url (str): Teams incoming webhook URL.
    """

    async def send(self, message: FormattedMessage) -> str:
        url = self.config.get("webhook_url")
        if not url:
            raise PermanentError("Teams webhook URL not configured")

        # Teams Adaptive Card format
        payload = {
            "type": "message",
            "attachments": [{
                "contentType":
                    "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema":
                        "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": message.title,
                            "weight": "Bolder",
                            "size": "Medium",
                        },
                        {
                            "type": "TextBlock",
                            "text": message.body,
                            "wrap": True,
                        },
                    ],
                    "actions": ([{
                        "type": "Action.OpenUrl",
                        "title": "View in Runbook",
                        "url": message.url,
                    }] if message.url else []),
                },
            }],
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)

            if resp.status_code == 429:
                raise TransientError("Teams rate limited (429)")
            if resp.status_code >= 500:
                raise TransientError(f"Teams {resp.status_code}")
            if resp.status_code == 404:
                raise PermanentError("Teams webhook URL not found (404)")
            if resp.status_code >= 400:
                raise PermanentError(
                    f"Teams {resp.status_code}: {resp.text[:200]}"
                )

            return f"{resp.status_code} OK"

        except httpx.TimeoutException as e:
            raise TransientError(f"Teams timeout: {e}") from e
        except httpx.ConnectError as e:
            raise TransientError(f"Teams connection error: {e}") from e
