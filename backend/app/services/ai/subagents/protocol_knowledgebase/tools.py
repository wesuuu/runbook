"""RunContext tool wrappers for the protocol_knowledgebase subagent.

Each wrapper checks the feature flags, applies the per-source rate limit,
delegates to a connector module (openwetware.py / protocols_io.py), caches
importable payloads, and appends a tool_calls audit row. All parsing,
HTTP, and licensing logic lives in the connector modules and licenses.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.protocol_knowledgebase import (
    openwetware,
    protocols_io,
    rate_limit,
)
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    OpenWetWareSearchResult,
    ProtocolsIoSearchResult,
)

# Human-readable labels for the chat thinking indicator. Adding a tool here
# MUST also update this dict — enforced by tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_openwetware": "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
    "search_protocols_io": "Searching protocols.io…",
    "fetch_protocols_io": "Reading protocols.io protocol…",
}


def _require_master_enabled() -> None:
    if not settings.features.external_protocols.enabled:
        raise ValueError(
            "External protocols feature is disabled. Ask an admin to enable "
            "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED."
        )


def _require_openwetware() -> None:
    _require_master_enabled()
    if not settings.features.external_protocols.openwetware.enabled:
        raise ValueError(
            "The OpenWetWare source is disabled "
            "(BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__OPENWETWARE__ENABLED)."
        )


def _require_protocols_io() -> str:
    """Assert protocols.io is live and configured; return the access token."""
    _require_master_enabled()
    cfg = settings.features.external_protocols.protocols_io
    if not cfg.enabled:
        raise ValueError(
            "The protocols.io source is disabled "
            "(BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED)."
        )
    if not cfg.access_token.strip():
        raise ValueError(
            "protocols.io is enabled but no access token is configured "
            "(BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN)."
        )
    return cfg.access_token


async def search_openwetware(
    ctx: RunContext[ChatDeps],
    query: str,
    limit: int = 5,
) -> OpenWetWareSearchResult:
    """Search OpenWetWare protocol pages matching a free-text query.

    Returns up to ``limit`` candidate hits (title, URL, snippet). Pass each
    interesting URL to ``fetch_openwetware_protocol``.

    Args:
        ctx: Run context with shared deps.
        query: Free-text search query (e.g. "heat shock transformation").
        limit: Maximum number of hits to return (default 5, capped at 10).
    """
    _require_openwetware()
    cfg = settings.features.external_protocols.openwetware
    await rate_limit.check_rate_limit(
        ctx.deps.org_id, "openwetware", cfg.rate_limit_per_minute
    )
    result = await openwetware.search(query, limit, timeout=cfg.request_timeout_seconds)
    ctx.deps.tool_calls.append(
        {
            "tool": "search_openwetware",
            "subagent": "protocol_knowledgebase",
            "query": query,
            "results": len(result.hits),
        }
    )
    return result


async def fetch_openwetware_protocol(
    ctx: RunContext[ChatDeps],
    url: str,
) -> ExternalProtocolPayload:
    """Fetch a single OpenWetWare protocol page and parse it.

    The URL must point to openwetware.org (host allowlist enforced). Steps
    are copied verbatim; do not paraphrase before handoff to
    protocol_creator.

    Args:
        ctx: Run context with shared deps.
        url: Full URL of an OpenWetWare wiki page (from search_openwetware).
    """
    _require_openwetware()
    cfg = settings.features.external_protocols.openwetware
    await rate_limit.check_rate_limit(
        ctx.deps.org_id, "openwetware", cfg.rate_limit_per_minute
    )
    payload = await openwetware.fetch(url, timeout=cfg.request_timeout_seconds)

    # Cache iff this is not a genuine failure — the approval tool reads it
    # back. (For OpenWetWare, error is None iff steps were parsed.)
    if payload.error is None:
        cache = getattr(ctx.deps, "external_protocol_cache", None)
        if cache is not None:
            cache[url] = json.dumps(asdict(payload))

    ctx.deps.tool_calls.append(
        {
            "tool": "fetch_openwetware_protocol",
            "subagent": "protocol_knowledgebase",
            "source_url": url,
            "steps": len(payload.steps),
        }
    )
    return payload


async def search_protocols_io(
    ctx: RunContext[ChatDeps],
    query: str,
    limit: int = 5,
) -> ProtocolsIoSearchResult:
    """Search public protocols.io protocols matching a free-text query.

    Returns up to ``limit`` candidate hits (id, title, URL, snippet). Pass
    each interesting URL to ``fetch_protocols_io``.

    Args:
        ctx: Run context with shared deps.
        query: Free-text search query (e.g. "plasmid miniprep").
        limit: Maximum number of hits to return (default 5, capped at 10).
    """
    token = _require_protocols_io()
    cfg = settings.features.external_protocols.protocols_io
    await rate_limit.check_rate_limit(
        ctx.deps.org_id, "protocols.io", cfg.rate_limit_per_minute
    )
    result = await protocols_io.search_protocols_io(
        query, access_token=token, limit=limit, timeout=cfg.request_timeout_seconds
    )
    ctx.deps.tool_calls.append(
        {
            "tool": "search_protocols_io",
            "subagent": "protocol_knowledgebase",
            "query": query,
            "results": len(result.hits),
        }
    )
    return result


async def fetch_protocols_io(
    ctx: RunContext[ChatDeps],
    url: str,
) -> ExternalProtocolPayload:
    """Fetch a single protocols.io protocol and parse it into a payload.

    The URL must point to protocols.io (host allowlist enforced). A protocol
    under a non-commercial / no-derivatives license comes back with
    ``import_allowed=False`` and no step text — present it as a link only.

    Args:
        ctx: Run context with shared deps.
        url: Full protocols.io protocol URL (from search_protocols_io).
    """
    token = _require_protocols_io()
    cfg = settings.features.external_protocols.protocols_io
    await rate_limit.check_rate_limit(
        ctx.deps.org_id, "protocols.io", cfg.rate_limit_per_minute
    )
    payload = await protocols_io.fetch_protocols_io(
        url, access_token=token, timeout=cfg.request_timeout_seconds
    )

    # Cache iff not a genuine failure — a license-restricted but valid
    # payload IS cached so the approval tool can re-check import_allowed.
    if payload.error is None:
        cache = getattr(ctx.deps, "external_protocol_cache", None)
        if cache is not None:
            cache[url] = json.dumps(asdict(payload))

    ctx.deps.tool_calls.append(
        {
            "tool": "fetch_protocols_io",
            "subagent": "protocol_knowledgebase",
            "source_url": url,
            "steps": len(payload.steps),
            "import_allowed": payload.import_allowed,
        }
    )
    return payload
