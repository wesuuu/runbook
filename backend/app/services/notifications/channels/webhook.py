import hashlib
import hmac
import json
import logging

import httpx

from app.services.notifications.channels.base import (
    BaseChannel, FormattedMessage, TransientError, PermanentError,
)

logger = logging.getLogger("notifications.webhook")

# Timeout for outbound HTTP calls
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class WebhookChannel(BaseChannel):
    """Generic HTTP POST webhook.

    Config:
        url (str): Required. Target URL.
        secret (str): Optional. HMAC-SHA256 signing key.
        headers (dict): Optional. Extra headers.
    """

    async def send(self, message: FormattedMessage) -> str:
        url = self.config.get("url")
        if not url:
            raise PermanentError("Webhook URL not configured")

        payload = {
            "event_type": message.event_type,
            "title": message.title,
            "body": message.body,
            "recipient": message.recipient,
            "url": message.url,
        }

        headers = {"Content-Type": "application/json"}
        headers.update(self.config.get("headers", {}))

        secret = self.config.get("secret")
        if secret:
            sig = hmac.new(
                secret.encode(), json.dumps(payload).encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Runbook-Signature"] = f"sha256={sig}"

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)

            if resp.status_code >= 500:
                raise TransientError(
                    f"Webhook returned {resp.status_code}: {resp.text[:200]}"
                )
            if resp.status_code == 429:
                raise TransientError("Webhook rate limited (429)")
            if resp.status_code >= 400:
                raise PermanentError(
                    f"Webhook returned {resp.status_code}: {resp.text[:200]}"
                )

            return f"{resp.status_code} OK"

        except httpx.TimeoutException as e:
            raise TransientError(f"Webhook timeout: {e}") from e
        except httpx.ConnectError as e:
            raise TransientError(f"Webhook connection error: {e}") from e
