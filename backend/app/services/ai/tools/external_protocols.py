"""Parent-agent approval tool for the F-0084 external protocol flow.

Registered with `requires_approval=True` so the agent run terminates with
a `DeferredToolRequests` when the LLM calls it. The tool body runs only
after the user clicks Approve in the frontend, at which point we record
an audit row and return a sentinel string the parent agent recognises as
"go dispatch protocol_creator with this payload."
"""

from __future__ import annotations

import json

from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps

APPROVED_SENTINEL = "EXTERNAL_PROTOCOL_APPROVED"

TOOL_LABELS: dict[str, str] = {
    "create_protocol_from_external_source": "Awaiting approval…",
}


async def create_protocol_from_external_source(
    ctx: RunContext[ChatDeps],
    payload_json: str,
    title: str,
    source_url: str,
) -> str:
    """Approve-and-hand-off an external protocol payload to protocol_creator.

    Registered with `requires_approval=True` on the parent agent. Calling
    it pauses the agent run; the body runs only after the user approves.
    Records an audit row and returns ``EXTERNAL_PROTOCOL_APPROVED\\n<json>``,
    which the parent prompt is instructed to feed to protocol_creator
    verbatim.

    Args:
        ctx: Run context with shared deps.
        payload_json: The chosen ExternalProtocolPayload as a JSON string.
        title: Protocol title, surfaced on the approval card.
        source_url: Source URL, surfaced on the approval card.
    """
    if not settings.features.external_protocols.enabled:
        raise ValueError("External protocols feature is disabled.")

    try:
        json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("payload_json must be valid JSON") from exc

    ctx.deps.tool_calls.append(
        {
            "tool": "create_protocol_from_external_source",
            "title": title,
            "source_url": source_url,
            "approved": True,
        }
    )
    return f"{APPROVED_SENTINEL}\n{payload_json}"
