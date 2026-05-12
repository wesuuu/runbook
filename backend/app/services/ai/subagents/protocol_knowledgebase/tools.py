"""Tools for the protocol_knowledgebase subagent (F-0084).

v1 scope: OpenWetWare only. Searches and fetches public protocols, parses
the wiki-text into a structured payload the parent agent can hand off to
protocol_creator after a human-in-the-loop approval.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from uuid import UUID

import httpx
from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps

# ─── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class ExternalProtocolStep:
    text: str
    duration_min: int | None  # parsed from "X min" / "X h" / "X s" in step text


@dataclass
class ExternalProtocolPayload:
    title: str
    source_url: str
    summary: str
    materials: list[str] = field(default_factory=list)
    steps: list[ExternalProtocolStep] = field(default_factory=list)
    notes: str | None = None
    license: str = "CC BY-SA 3.0"
    attribution: str = ""


@dataclass
class OpenWetWareHit:
    title: str
    url: str
    snippet: str


@dataclass
class OpenWetWareSearchResult:
    total: int
    hits: list[OpenWetWareHit] = field(default_factory=list)
    message: str = ""


# ─── Pure parser ───────────────────────────────────────────────────────────────

_LICENSE = "CC BY-SA 3.0"

# Section name synonyms (lowercase, no spaces)
_MATERIAL_HEADINGS = {"materials", "reagents", "supplies", "whatyouneed"}
_PROCEDURE_HEADINGS = {"procedure", "method", "protocol", "steps", "instructions"}
_NOTES_HEADINGS = {"notes", "tips", "comments", "troubleshooting"}
_SUMMARY_HEADINGS = {"description", "background", "summary", "overview", "abstract"}

_DURATION_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(min(?:s|utes?)?|h(?:rs?|ours?)?|s(?:ec(?:onds?)?)?)\b",
    re.IGNORECASE,
)

_HEADING_RE = re.compile(r"^==+\s*(.+?)\s*==+\s*$")
_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+\|)?([^\]]+)\]\]")
_BOLD_ITALIC_RE = re.compile(r"'{2,5}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL)
_TEMPLATE_RE = re.compile(r"\{\{[^}]+\}\}")


def _clean_wiki_inline(text: str) -> str:
    """Strip inline wiki markup so a step/material reads naturally."""
    t = _REF_RE.sub("", text)
    t = _TEMPLATE_RE.sub("", t)
    # [[Page|label]] -> label; [[Page]] -> Page
    t = _WIKI_LINK_RE.sub(lambda m: m.group(2), t)
    t = _BOLD_ITALIC_RE.sub("", t)
    t = _HTML_TAG_RE.sub("", t)
    return t.strip()


def _normalize_heading(h: str) -> str:
    return re.sub(r"\s+", "", h).lower()


def _split_sections(text: str) -> dict[str, str]:
    """Split wiki-text on `==Heading==` lines into a {normalized_heading: body}."""
    sections: dict[str, str] = {}
    current_key = ""
    current_buf: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if current_buf or current_key:
                sections[current_key] = "\n".join(current_buf).strip()
            current_key = _normalize_heading(m.group(1))
            current_buf = []
        else:
            current_buf.append(line)
    if current_buf or current_key:
        sections[current_key] = "\n".join(current_buf).strip()
    return sections


def _bulleted_items(body: str) -> list[str]:
    """Pull top-level `* …` lines; nested `**` sub-items are skipped."""
    out: list[str] = []
    for raw in body.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            out.append(_clean_wiki_inline(stripped.lstrip("*").strip()))
    return [s for s in out if s]


def _numbered_items(body: str) -> list[str]:
    """Pull top-level `# …` lines; nested `##` sub-steps are skipped."""
    out: list[str] = []
    for raw in body.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#") and not stripped.startswith("##"):
            out.append(_clean_wiki_inline(stripped.lstrip("#").strip()))
    return [s for s in out if s]


def _parse_duration_minutes(text: str) -> int | None:
    """Find first `<n> min/h/s` in text and convert to minutes (rounded up)."""
    m = _DURATION_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("h"):
        minutes = value * 60.0
    elif unit.startswith("s"):
        minutes = value / 60.0
    else:
        minutes = value
    return max(1, math.ceil(minutes))


def parse_openwetware_wikitext(
    wikitext: str, displaytitle: str, source_url: str
) -> ExternalProtocolPayload:
    """Parse an OpenWetWare wiki-text page into a structured payload.

    Lossy by design — the loose dataclass shape is what protocol_creator
    expects as a seed. Section names matched via the synonym sets above;
    pages that defy all synonyms still return a populated `summary`,
    `license`, and `attribution`.
    """
    sections = _split_sections(wikitext)

    # Summary: explicit summary-like section if present, else the first
    # non-empty body line of the page (pre-heading).
    summary = ""
    for key in _SUMMARY_HEADINGS:
        if key in sections and sections[key]:
            summary = _clean_wiki_inline(sections[key].split("\n\n")[0])
            break
    if not summary:
        pre = sections.get("", "")
        if pre:
            for line in pre.splitlines():
                cleaned = _clean_wiki_inline(line)
                if cleaned:
                    summary = cleaned
                    break

    materials: list[str] = []
    for key in _MATERIAL_HEADINGS:
        if key in sections:
            materials = _bulleted_items(sections[key])
            if materials:
                break

    step_texts: list[str] = []
    for key in _PROCEDURE_HEADINGS:
        if key in sections:
            step_texts = _numbered_items(sections[key])
            if step_texts:
                break
    steps = [
        ExternalProtocolStep(text=t, duration_min=_parse_duration_minutes(t))
        for t in step_texts
    ]

    notes_text: str | None = None
    for key in _NOTES_HEADINGS:
        if key in sections and sections[key]:
            notes_text = _clean_wiki_inline(sections[key])
            break

    return ExternalProtocolPayload(
        title=displaytitle,
        source_url=source_url,
        summary=summary,
        materials=materials,
        steps=steps,
        notes=notes_text,
        license=_LICENSE,
        attribution=f"OpenWetWare contributors, {displaytitle}",
    )


# ─── HTTP tools + rate limit ───────────────────────────────────────────────────

# Human-readable labels for the chat thinking indicator (F-0083). Adding a
# tool here MUST also update the entry — enforced by
# tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_openwetware": "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
}

_OWW_HOST = "openwetware.org"
# OpenWetWare's MediaWiki API lives under /mediawiki/, not /wiki/. The
# `/wiki/` path is for human-readable pages and 404s the api.php script.
_OWW_API = "https://openwetware.org/mediawiki/api.php"

# Test-injectable monotonic clock — tests override this.
_now: Callable[[], float] = time.monotonic

# In-process token bucket — per-org timestamps for the last 60s window.
# Single-replica deploy assumption; revisit when we go multi-worker.
_RECENT_REQUESTS: dict[UUID, deque[float]] = {}
_LIMIT_LOCK = asyncio.Lock()


def _require_enabled() -> None:
    if not settings.features.external_protocols.enabled:
        raise ValueError(
            "External protocols feature is disabled. Ask an admin to enable "
            "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED."
        )


async def _check_rate_limit(org_id: UUID) -> None:
    limit = settings.features.external_protocols.rate_limit_per_minute
    async with _LIMIT_LOCK:
        now = _now()
        bucket = _RECENT_REQUESTS.setdefault(org_id, deque())
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ValueError(
                f"OpenWetWare rate limit hit ({limit}/min). Try again in a minute."
            )
        bucket.append(now)


def _require_oww_url(url: str) -> None:
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception as exc:
        raise ValueError(f"Invalid URL: {url}") from exc
    # Allow exact host or `www.` subdomain.
    if host != _OWW_HOST and host != f"www.{_OWW_HOST}":
        raise ValueError(f"URL must be on openwetware.org (got {host!r}).")


def _page_title_from_url(url: str) -> str:
    """`/wiki/Some:Page_Title` → `Some:Page Title`."""
    path = urllib.parse.urlparse(url).path
    leaf = path.rsplit("/", 1)[-1]
    return urllib.parse.unquote(leaf).replace("_", " ")


async def search_openwetware(
    ctx: RunContext[ChatDeps],
    query: str,
    limit: int = 5,
) -> OpenWetWareSearchResult:
    """Search OpenWetWare for protocol pages matching a free-text query.

    Returns up to `limit` candidate hits (title, URL, snippet). Use this
    first; pass each interesting URL to ``fetch_openwetware_protocol`` to
    get the structured payload.

    Args:
        ctx: Run context with shared deps.
        query: Free-text search query (e.g. "heat shock transformation").
        limit: Maximum number of hits to return (default 5, capped at 10).
    """
    _require_enabled()
    await _check_rate_limit(ctx.deps.org_id)

    limit = max(1, min(int(limit), 10))
    timeout = settings.features.external_protocols.request_timeout_seconds
    params = {
        "action": "opensearch",
        "search": query,
        "limit": str(limit),
        "format": "json",
        "namespace": "0",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(_OWW_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

    # MediaWiki opensearch returns [query, titles[], descriptions[], urls[]].
    titles = data[1] if len(data) > 1 else []
    snippets = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    hits = [
        OpenWetWareHit(
            title=t,
            url=u,
            snippet=(snippets[i] if i < len(snippets) else ""),
        )
        for i, (t, u) in enumerate(zip(titles, urls))
    ]

    ctx.deps.tool_calls.append(
        {
            "tool": "search_openwetware",
            "subagent": "protocol_knowledgebase",
            "query": query,
            "results": len(hits),
        }
    )

    if not hits:
        return OpenWetWareSearchResult(total=0, message="No OpenWetWare results.")
    return OpenWetWareSearchResult(total=len(hits), hits=hits)


async def fetch_openwetware_protocol(
    ctx: RunContext[ChatDeps],
    url: str,
) -> ExternalProtocolPayload:
    """Fetch a single OpenWetWare protocol page and parse it into a structured payload.

    The URL must point to openwetware.org (host allowlist enforced).
    Steps are copied verbatim from the page; do not paraphrase before
    handoff to protocol_creator.

    Args:
        ctx: Run context with shared deps.
        url: Full URL of an OpenWetWare wiki page (returned by search_openwetware).
    """
    _require_enabled()
    _require_oww_url(url)
    await _check_rate_limit(ctx.deps.org_id)

    page_title = _page_title_from_url(url)
    timeout = settings.features.external_protocols.request_timeout_seconds
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext|displaytitle",
        "format": "json",
        "formatversion": "1",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(_OWW_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

    parse = data.get("parse") or {}
    displaytitle = parse.get("displaytitle") or page_title
    wikitext = ((parse.get("wikitext") or {}).get("*")) or ""

    payload = parse_openwetware_wikitext(
        wikitext=wikitext, displaytitle=displaytitle, source_url=url
    )

    ctx.deps.tool_calls.append(
        {
            "tool": "fetch_openwetware_protocol",
            "subagent": "protocol_knowledgebase",
            "source_url": url,
            "steps": len(payload.steps),
        }
    )
    return payload
