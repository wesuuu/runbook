"""Tools for the protocol_knowledgebase subagent.

v1 scope: OpenWetWare only. Searches and fetches public protocols, parses
the wiki-text into a structured payload the parent agent can hand off to
protocol_creator after a human-in-the-loop approval.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from dataclasses import asdict

import httpx
from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps
from app.services.ai.subagents.protocol_knowledgebase import rate_limit
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    OpenWetWareHit,
    OpenWetWareSearchResult,
)

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
# Biblio blocks contain `#cite-id pmid=...` entries that look like top-level
# numbered steps to a naive scan — strip them before extracting steps.
_BIBLIO_RE = re.compile(r"<biblio[^>]*>.*?</biblio>", re.DOTALL | re.IGNORECASE)
_TEMPLATE_RE = re.compile(r"\{\{[^}]+\}\}")

# A *top-level* numbered list item is exactly one `#` followed by whitespace
# or a word character — `#*`, `#:`, `##`, `#;` are sub-items / non-step
# markup and must be skipped. The whitespace optional class catches lines
# like `#Grow…` (OWW frequently omits the space).
_TOP_LEVEL_NUMBERED_RE = re.compile(r"^#(?:\s+|[A-Za-z0-9])")


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
    """Pull top-level ``# …`` lines. Sub-items (``##``, ``#*``, ``#:``,
    ``#;``) are skipped, and ``<biblio>`` blocks are stripped first so their
    ``#cite-id pmid=…`` entries don't masquerade as steps.
    """
    cleaned_body = _BIBLIO_RE.sub("", body)
    out: list[str] = []
    for raw in cleaned_body.splitlines():
        stripped = raw.lstrip()
        if _TOP_LEVEL_NUMBERED_RE.match(stripped):
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


def _find_matching_section(sections: dict[str, str], synonyms: set[str]) -> str | None:
    """Return the body of the first section whose normalized heading
    contains any synonym as a substring. Real OWW pages use names like
    "General Procedure" or "Casting Gels" — exact equality misses them.
    """
    for heading, body in sections.items():
        if not heading:
            continue
        if any(syn in heading for syn in synonyms):
            return body
    return None


def parse_openwetware_wikitext(
    wikitext: str, displaytitle: str, source_url: str
) -> ExternalProtocolPayload:
    """Parse an OpenWetWare wiki-text page into a structured payload.

    Lossy by design — the loose dataclass shape is what protocol_creator
    expects as a seed. Section names matched via substring against the
    synonym sets above. If no procedure-like section matches, falls back
    to scanning the whole page for top-level numbered items so semantic
    headings (e.g. "Phusion", "Casting Gels") still yield steps.
    """
    sections = _split_sections(wikitext)

    # Summary: explicit summary-like section if present, else the first
    # non-empty body line of the page (pre-heading).
    summary = ""
    body = _find_matching_section(sections, _SUMMARY_HEADINGS)
    if body:
        summary = _clean_wiki_inline(body.split("\n\n")[0])
    if not summary:
        pre = sections.get("", "")
        if pre:
            for line in pre.splitlines():
                cleaned = _clean_wiki_inline(line)
                if cleaned:
                    summary = cleaned
                    break

    materials: list[str] = []
    mat_body = _find_matching_section(sections, _MATERIAL_HEADINGS)
    if mat_body is not None:
        materials = _bulleted_items(mat_body)

    step_texts: list[str] = []
    proc_body = _find_matching_section(sections, _PROCEDURE_HEADINGS)
    if proc_body is not None:
        step_texts = _numbered_items(proc_body)
    if not step_texts:
        # Fallback: gather every top-level # line across the whole page.
        step_texts = _numbered_items(wikitext)
    steps = [
        ExternalProtocolStep(text=t, duration_min=_parse_duration_minutes(t))
        for t in step_texts
    ]

    notes_text: str | None = None
    notes_body = _find_matching_section(sections, _NOTES_HEADINGS)
    if notes_body:
        notes_text = _clean_wiki_inline(notes_body)

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

# Human-readable labels for the chat thinking indicator. Adding a tool
# here MUST also update the entry — enforced by
# tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_openwetware": "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
}

_OWW_HOST = "openwetware.org"
# OpenWetWare's MediaWiki API lives under /mediawiki/, not /wiki/. The
# `/wiki/` path is for human-readable pages and 404s the api.php script.
_OWW_API = "https://openwetware.org/mediawiki/api.php"


def _require_enabled() -> None:
    if not settings.features.external_protocols.enabled:
        raise ValueError(
            "External protocols feature is disabled. Ask an admin to enable "
            "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED."
        )


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


_SNIPPET_TAG_RE = re.compile(r"<[^>]+>")


def _title_to_url(title: str) -> str:
    """`Agarose gel electrophoresis` → full openwetware.org/wiki URL."""
    slug = urllib.parse.quote(title.replace(" ", "_"), safe=":/_")
    return f"https://openwetware.org/wiki/{slug}"


async def search_openwetware(
    ctx: RunContext[ChatDeps],
    query: str,
    limit: int = 5,
) -> OpenWetWareSearchResult:
    """Search OpenWetWare protocol pages matching a free-text query.

    Uses MediaWiki full-text `list=search` constrained to
    `Category:Protocol`, which excludes review/survey articles. Returns
    up to `limit` candidate hits (title, URL, snippet). Pass each
    interesting URL to ``fetch_openwetware_protocol`` to get the
    structured payload.

    Args:
        ctx: Run context with shared deps.
        query: Free-text search query (e.g. "heat shock transformation").
        limit: Maximum number of hits to return (default 5, capped at 10).
    """
    _require_enabled()
    _rate_limit = settings.features.external_protocols.openwetware.rate_limit_per_minute
    await rate_limit.check_rate_limit(ctx.deps.org_id, "openwetware", _rate_limit)

    limit = max(1, min(int(limit), 10))
    timeout = settings.features.external_protocols.openwetware.request_timeout_seconds
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{query} incategory:Protocol",
        "srlimit": str(limit),
        "srnamespace": "0",
        "srprop": "snippet",
        "format": "json",
        "formatversion": "1",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(_OWW_API, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

    raw_hits = (data.get("query") or {}).get("search") or []
    hits = [
        OpenWetWareHit(
            title=h.get("title", ""),
            url=_title_to_url(h.get("title", "")),
            snippet=_SNIPPET_TAG_RE.sub("", h.get("snippet", "")).strip(),
        )
        for h in raw_hits
        if h.get("title")
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
        return OpenWetWareSearchResult(
            total=0, message="No OpenWetWare protocol pages match this query."
        )
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
    limit = settings.features.external_protocols.openwetware.rate_limit_per_minute
    await rate_limit.check_rate_limit(ctx.deps.org_id, "openwetware", limit)

    page_title = _page_title_from_url(url)
    timeout = settings.features.external_protocols.openwetware.request_timeout_seconds
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

    # MediaWiki returns 200 with {"error": {...}} on missingtitle, invalid
    # params, etc. Return a recoverable payload (steps=[], error set) so the
    # subagent's loop can skip and try another hit instead of pydantic-ai
    # bubbling the exception up through the task tool and killing the run.
    error = data.get("error")
    if isinstance(error, dict):
        info = error.get("info") or error.get("code") or "unknown error"
        return ExternalProtocolPayload(
            title=page_title,
            source_url=url,
            summary="",
            error=f"fetch failed: {info}. Skip and try a different URL from search_openwetware.",
        )
    parse = data.get("parse") or {}
    raw_displaytitle = parse.get("displaytitle") or page_title
    displaytitle = _HTML_TAG_RE.sub("", raw_displaytitle).strip() or page_title
    wikitext = ((parse.get("wikitext") or {}).get("*")) or ""
    if not wikitext.strip():
        return ExternalProtocolPayload(
            title=displaytitle,
            source_url=url,
            summary="",
            error="no wiki-text content. Skip and try a different URL.",
        )

    payload = parse_openwetware_wikitext(
        wikitext=wikitext, displaytitle=displaytitle, source_url=url
    )
    if not payload.steps:
        payload.error = "parsed to 0 steps (stub or non-protocol page). Skip and try another URL."
        return payload

    # Cache the canonical payload so the approval tool can read it directly
    # without the LLM re-serializing multi-KB JSON. The payload is a
    # @dataclass, not a pydantic model — asdict() is the right serializer.
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
