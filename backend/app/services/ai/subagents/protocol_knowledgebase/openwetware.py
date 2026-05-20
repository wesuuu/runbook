"""OpenWetWare connector — search, fetch, and wiki-text parser (F-0084).

Harness-free: functions take primitives, not a pydantic-ai RunContext, so
they unit-test without the chat harness. The tools.py wrappers adapt
RunContext to these signatures and handle the audit row + payload cache.
"""

from __future__ import annotations

import math
import re
import urllib.parse

import httpx

from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    OpenWetWareHit,
    OpenWetWareSearchResult,
)

_LICENSE = "CC BY-SA 3.0"
_OWW_HOST = "openwetware.org"
# OpenWetWare's MediaWiki API lives under /mediawiki/, not /wiki/.
_OWW_API = "https://openwetware.org/mediawiki/api.php"

# Section-name synonyms (lowercase, no spaces).
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
_BIBLIO_RE = re.compile(r"<biblio[^>]*>.*?</biblio>", re.DOTALL | re.IGNORECASE)
_TEMPLATE_RE = re.compile(r"\{\{[^}]+\}\}")
_TOP_LEVEL_NUMBERED_RE = re.compile(r"^#(?:\s+|[A-Za-z0-9])")
_SNIPPET_TAG_RE = re.compile(r"<[^>]+>")


def _clean_wiki_inline(text: str) -> str:
    """Strip inline wiki markup so a step/material reads naturally."""
    t = _REF_RE.sub("", text)
    t = _TEMPLATE_RE.sub("", t)
    t = _WIKI_LINK_RE.sub(lambda m: m.group(2), t)
    t = _BOLD_ITALIC_RE.sub("", t)
    t = _HTML_TAG_RE.sub("", t)
    return t.strip()


def _normalize_heading(h: str) -> str:
    return re.sub(r"\s+", "", h).lower()


def _split_sections(text: str) -> dict[str, str]:
    """Split wiki-text on ``==Heading==`` lines into {normalized_heading: body}."""
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
    """Pull top-level ``* …`` lines; nested ``**`` sub-items are skipped."""
    out: list[str] = []
    for raw in body.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            out.append(_clean_wiki_inline(stripped.lstrip("*").strip()))
    return [s for s in out if s]


def _numbered_items(body: str) -> list[str]:
    """Pull top-level ``# …`` lines; sub-items and ``<biblio>`` are skipped."""
    cleaned_body = _BIBLIO_RE.sub("", body)
    out: list[str] = []
    for raw in cleaned_body.splitlines():
        stripped = raw.lstrip()
        if _TOP_LEVEL_NUMBERED_RE.match(stripped):
            out.append(_clean_wiki_inline(stripped.lstrip("#").strip()))
    return [s for s in out if s]


def _parse_duration_minutes(text: str) -> int | None:
    """Find first ``<n> min/h/s`` in text and convert to minutes (round up)."""
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


def _find_matching_section(
    sections: dict[str, str], synonyms: set[str]
) -> str | None:
    """Body of the first section whose normalized heading contains a synonym."""
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
    expects as a seed. If no procedure-like section matches, falls back to
    scanning the whole page for top-level numbered items.
    """
    sections = _split_sections(wikitext)

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


def require_openwetware_url(url: str) -> None:
    """Raise ValueError unless ``url`` is hosted on openwetware.org."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception as exc:  # noqa: BLE001 — malformed URL → caller-facing error
        raise ValueError(f"Invalid URL: {url}") from exc
    if host != _OWW_HOST and host != f"www.{_OWW_HOST}":
        raise ValueError(f"URL must be on openwetware.org (got {host!r}).")


def _page_title_from_url(url: str) -> str:
    """``/wiki/Some:Page_Title`` → ``Some:Page Title``."""
    path = urllib.parse.urlparse(url).path
    leaf = path.rsplit("/", 1)[-1]
    return urllib.parse.unquote(leaf).replace("_", " ")


def _title_to_url(title: str) -> str:
    """``Agarose gel electrophoresis`` → full openwetware.org/wiki URL."""
    slug = urllib.parse.quote(title.replace(" ", "_"), safe=":/_")
    return f"https://openwetware.org/wiki/{slug}"


async def search(query: str, limit: int, *, timeout: float) -> OpenWetWareSearchResult:
    """Search OpenWetWare protocol pages via the MediaWiki full-text API."""
    limit = max(1, min(int(limit), 10))
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
    if not hits:
        return OpenWetWareSearchResult(
            total=0, message="No OpenWetWare protocol pages match this query."
        )
    return OpenWetWareSearchResult(total=len(hits), hits=hits)


async def fetch(url: str, *, timeout: float) -> ExternalProtocolPayload:
    """Fetch one OpenWetWare page and parse it into a structured payload.

    Returns a recoverable payload (``steps=[]``, ``error`` set) on a fetch
    or parse failure so the subagent loop can skip and try another URL.
    """
    require_openwetware_url(url)
    page_title = _page_title_from_url(url)
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

    error = data.get("error")
    if isinstance(error, dict):
        info = error.get("info") or error.get("code") or "unknown error"
        return ExternalProtocolPayload(
            title=page_title,
            source_url=url,
            summary="",
            error=(
                f"fetch failed: {info}. Skip and try a different URL "
                "from search_openwetware."
            ),
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
        payload.error = (
            "parsed to 0 steps (stub or non-protocol page). "
            "Skip and try another URL."
        )
    return payload
