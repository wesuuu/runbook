import logging

import httpx

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
)

logger = logging.getLogger("notifications.slack")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class SlackChannel(BaseChannel):
    """Slack notification channel.

    Supports two modes:
    - Incoming Webhook (simpler, org-level): config.webhook_url
    - Bot Token (richer, user-level DMs): config.bot_token + config.channel

    Config:
        webhook_url (str): Slack incoming webhook URL.
        bot_token (str): Slack bot OAuth token (xoxb-...).
        channel (str): Channel ID or user ID for bot token mode.
    """

    async def send(self, message: FormattedMessage) -> str:
        webhook_url = self.config.get("webhook_url")
        bot_token = self.config.get("bot_token")

        if webhook_url:
            return await self._send_webhook(webhook_url, message)
        elif bot_token:
            return await self._send_bot(bot_token, message)
        else:
            raise PermanentError(
                "Slack channel requires either webhook_url or bot_token"
            )

    async def _send_webhook(
        self, url: str, message: FormattedMessage
    ) -> str:
        payload = {
            "text": f"*{message.title}*\n{message.body}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{message.title}*\n{message.body}",
                    },
                },
            ],
        }
        if message.url:
            payload["blocks"].append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Runbook"},
                    "url": message.url,
                }],
            })

        return await self._post(url, payload)

    async def _send_bot(
        self, token: str, message: FormattedMessage
    ) -> str:
        channel = self.config.get("channel")
        if not channel:
            raise PermanentError("Bot token mode requires a channel ID")

        payload = {
            "channel": channel,
            "text": f"*{message.title}*\n{message.body}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{message.title}*\n{message.body}",
                    },
                },
            ],
        }
        if message.url:
            payload["blocks"].append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Runbook"},
                    "url": message.url,
                }],
            })

        headers = {"Authorization": f"Bearer {token}"}
        return await self._post(
            "https://slack.com/api/chat.postMessage", payload, headers
        )

    async def _post(
        self, url: str, payload: dict, headers: dict | None = None
    ) -> str:
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    url, json=payload, headers=req_headers
                )

            if resp.status_code == 429:
                raise TransientError("Slack rate limited (429)")
            if resp.status_code >= 500:
                raise TransientError(f"Slack {resp.status_code}")

            body = resp.json() if resp.headers.get(
                "content-type", ""
            ).startswith("application/json") else {}

            # Slack API returns 200 with ok=false for errors
            if body.get("ok") is False:
                error = body.get("error", "unknown")
                if error in ("invalid_auth", "account_inactive",
                             "channel_not_found", "not_in_channel"):
                    raise PermanentError(f"Slack API error: {error}")
                raise TransientError(f"Slack API error: {error}")

            if resp.status_code >= 400:
                raise PermanentError(f"Slack {resp.status_code}: {resp.text[:200]}")

            return f"{resp.status_code} OK"

        except httpx.TimeoutException as e:
            raise TransientError(f"Slack timeout: {e}") from e
        except httpx.ConnectError as e:
            raise TransientError(f"Slack connection error: {e}") from e
