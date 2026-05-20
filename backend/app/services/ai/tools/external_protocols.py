"""Parent-agent approval tool for the external protocol import flow.

Registered with ``requires_approval=True`` so the agent run terminates with
a ``DeferredToolRequests`` when the LLM calls it. The tool body runs after
the user approves, reads the cached payload (kept server-side to avoid a
fragile multi-KB JSON round-trip through the LLM), and returns a sentinel
string the parent prompt feeds to ``protocol_creator``.
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
    source_url: str,
    title: str,
    project_name: str,
) -> str:
    """Approve-and-hand-off an external protocol payload to protocol_creator.

    Registered with `requires_approval=True` on the parent agent. Calling
    it pauses the agent run; the body runs only after the user approves.
    Looks up the cached payload (populated by
    ``fetch_openwetware_protocol`` and possibly mutated by the resume path
    to reflect the user's inline edits) and returns
    ``EXTERNAL_PROTOCOL_APPROVED\\n<project_name>\\n<deviations_json>\\n<payload_json>``,
    which the parent prompt feeds to protocol_creator verbatim.

    Args:
        ctx: Run context with shared deps.
        source_url: Source URL (key into ``deps.external_protocol_cache``),
            surfaced on the approval card.
        title: Protocol title, surfaced on the approval card.
        project_name: Target project for the new protocol. The parent agent
            asks the user for this before calling the tool so the user can
            confirm the destination on the approval card.
    """
    if not settings.features.external_protocols.enabled:
        raise ValueError("External protocols feature is disabled.")

    if not project_name or not project_name.strip():
        raise ValueError(
            "project_name is required; ask the user which project this "
            "protocol belongs to before calling the approval tool."
        )

    cached = ctx.deps.external_protocol_cache.get(source_url)
    if not cached:
        raise ValueError(
            "External protocol payload missing from cache for "
            f"{source_url!r}. Call fetch_openwetware_protocol first."
        )

    # Re-check the license verdict straight off the cached payload — a plain
    # boolean read, no classify_license call. A stale cache (or a payload
    # mutated by the resume path) cannot slip a license-restricted protocol
    # past the import. The connector already set this; we only enforce it.
    try:
        import_allowed = json.loads(cached).get("import_allowed", True)
    except (json.JSONDecodeError, AttributeError, TypeError):
        # Fail closed: an unparseable cache entry is unverifiable, so it
        # must not slip a possibly license-restricted protocol through.
        import_allowed = False
    if not import_allowed:
        raise ValueError(
            "This protocol is under a license that does not permit automatic "
            "import. It can only be added to the library manually."
        )

    deviation_list = [
        d.strip()
        for d in (ctx.deps.user_deviations or [])
        if isinstance(d, str) and d.strip()
    ]
    ctx.deps.tool_calls.append(
        {
            "tool": "create_protocol_from_external_source",
            "title": title,
            "source_url": source_url,
            "project_name": project_name,
            "deviations": deviation_list,
            "approved": True,
        }
    )
    return (
        f"{APPROVED_SENTINEL}\n"
        f"{project_name}\n"
        f"{json.dumps(deviation_list)}\n"
        f"{cached}"
    )
