"""Dev-only endpoints for testing integrations.

Only mounted when RUNBOOK_DEBUG=true.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger("dev")

router = APIRouter()


@router.post("/webhook-echo")
async def webhook_echo(request: Request):
    """Catch-all webhook receiver for testing. Logs the full payload."""
    body = await request.json()
    logger.info(
        "Webhook echo received:\n%s",
        json.dumps(body, indent=2, default=str),
    )
    return {
        "status": "received",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": body,
    }
