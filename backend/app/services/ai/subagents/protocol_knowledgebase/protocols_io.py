"""protocols.io connector — search, fetch, and detail-JSON parser (F-0090).

Harness-free: functions take primitives, not a pydantic-ai RunContext.

protocols.io public content is uniformly CC-BY. The license field is still
classified on every payload (fail-closed verification): if a payload comes
back as anything other than an import-safe license, the protocol is parsed
to metadata only — no step or material text is copied — and flagged
import_allowed=False so it surfaces as a link, never an automatic import.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse

import httpx

from app.services.ai.subagents.protocol_knowledgebase.licenses import classify_license
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    ProtocolsIoHit,
    ProtocolsIoSearchResult,
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(text: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    stripped = _HTML_TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", html.unescape(stripped)).strip()


def _draftjs_to_text(raw: str | None) -> str:
    """Extract plain text from a Draft.js JSON blob or fall back to _clean_html.

    protocols.io v4 stores rich-text fields (description, step, materials_text)
    as Draft.js JSON strings.  Plain-HTML strings (legacy or alternative shape)
    are handled by _clean_html as before.

    Empty / None / un-parseable inputs return an empty string.
    """
    if not raw:
        return ""
    # If the string looks like JSON, try to parse it as a Draft.js document.
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            doc = json.loads(stripped)
            texts = [
                (b.get("text") or "").strip()
                for b in (doc.get("blocks") or [])
                if (b.get("text") or "").strip()
            ]
            return _WS_RE.sub(" ", " ".join(texts)).strip()
        except (ValueError, AttributeError):
            pass
    # Fallback: treat as HTML.
    return _clean_html(raw)


def parse_protocols_io_json(
    detail_json: dict, source_url: str
) -> ExternalProtocolPayload:
    """Map a protocols.io protocol-detail JSON object to a payload.

    Pure — no HTTP. ``detail_json`` is the full response body; the protocol
    lives under the ``payload`` key.

    The v4 API stores rich-text fields as Draft.js JSON strings (``step``,
    ``description``, ``materials_text``).  ``_draftjs_to_text`` extracts plain
    text from these, with an HTML fallback for any older or alternative shapes.
    """
    obj = detail_json.get("payload") or {}
    title = (obj.get("title") or "").strip() or "Untitled protocol"
    summary = _draftjs_to_text(obj.get("description") or "")

    raw_license = (obj.get("license") or {}).get("title") or ""
    verdict = classify_license(raw_license)

    authors = ", ".join(
        (a.get("name") or "").strip()
        for a in (obj.get("authors") or [])
        if (a.get("name") or "").strip()
    )
    attribution = (
        f"protocols.io — {authors}, {title}" if authors else f"protocols.io — {title}"
    )

    if not verdict.import_allowed:
        # License-restricted: metadata only. Never copy step/material text.
        return ExternalProtocolPayload(
            title=title,
            source_url=source_url,
            summary=summary,
            materials=[],
            steps=[],
            license=raw_license or verdict.normalized,
            attribution=attribution,
            error=None,
            import_allowed=False,
            license_note=verdict.reason,
        )

    # Materials: v4 API returns an empty ``materials`` array and stores the
    # list in ``materials_text`` (Draft.js JSON).  Support both shapes.
    raw_materials = obj.get("materials") or []
    if raw_materials:
        materials = [
            (m.get("name") or "").strip()
            for m in raw_materials
            if (m.get("name") or "").strip()
        ]
    else:
        # ``materials_text`` is a Draft.js JSON string; each block is one item.
        raw_mt = (obj.get("materials_text") or "").strip()
        if raw_mt.startswith("{"):
            try:
                doc = json.loads(raw_mt)
                materials = [
                    (b.get("text") or "").strip()
                    for b in (doc.get("blocks") or [])
                    if (b.get("text") or "").strip()
                ]
            except (ValueError, AttributeError):
                materials = []
        else:
            materials = []

    # Steps: v4 API encodes step text in ``step`` (Draft.js JSON).  The legacy
    # ``description`` key (plain HTML) is also supported as a fallback.
    steps = []
    for s in obj.get("steps") or []:
        text = _draftjs_to_text(s.get("step") or "") or _clean_html(
            s.get("description") or ""
        )
        if text:
            steps.append(ExternalProtocolStep(text=text, duration_min=None))
    return ExternalProtocolPayload(
        title=title,
        source_url=source_url,
        summary=summary,
        materials=materials,
        steps=steps,
        license=raw_license or verdict.normalized,
        attribution=attribution,
        error=None,
        import_allowed=True,
        license_note=verdict.reason,
    )


_PROTOCOLS_IO_HOSTS = {"protocols.io", "www.protocols.io"}
_SEARCH_URL = "https://www.protocols.io/api/v3/protocols"
_DETAIL_URL = "https://www.protocols.io/api/v4/protocols"


def require_protocols_io_url(url: str) -> None:
    """Raise ValueError unless ``url`` is hosted on protocols.io."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception as exc:  # noqa: BLE001 — malformed URL → caller-facing error
        raise ValueError(f"Invalid URL: {url}") from exc
    if host not in _PROTOCOLS_IO_HOSTS:
        raise ValueError(f"URL must be on protocols.io (got {host!r}).")


def _protocol_id_from_url(url: str) -> str:
    """``…/view/<slug>`` → ``<slug>`` (v4 detail accepts the slug as id)."""
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if "view" in parts:
        i = parts.index("view")
        if i + 1 < len(parts):
            return parts[i + 1]
    return parts[-1] if parts else ""


async def search_protocols_io(
    query: str, *, access_token: str, limit: int, timeout: float
) -> ProtocolsIoSearchResult:
    """Search public protocols.io protocols matching a free-text query."""
    limit = max(1, min(int(limit), 10))
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"filter": "public", "key": query, "page_size": str(limit)}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _SEARCH_URL, params=params, headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()

    raw = data.get("items") or []
    hits = [
        ProtocolsIoHit(
            id=str(it.get("id") or ""),
            title=(it.get("title") or "").strip(),
            url=(it.get("url") or "").strip(),
            snippet=_clean_html(it.get("description") or "")[:280],
        )
        for it in raw
        if it.get("id") and it.get("title") and it.get("url")
    ]
    if not hits:
        return ProtocolsIoSearchResult(
            total=0, message="No protocols.io protocols match this query."
        )
    return ProtocolsIoSearchResult(total=len(hits), hits=hits)


async def fetch_protocols_io(
    url: str, *, access_token: str, timeout: float
) -> ExternalProtocolPayload:
    """Fetch one protocols.io protocol and parse it into a payload.

    Has its own terminal logic — a license-restricted protocol legitimately
    parses to ``steps=[]`` with ``import_allowed=False`` and ``error=None``;
    only an *import-safe* protocol that parsed 0 steps is a stub (error set).
    """
    require_protocols_io_url(url)
    protocol_id = _protocol_id_from_url(url)
    if not protocol_id:
        return ExternalProtocolPayload(
            title="",
            source_url=url,
            summary="",
            error="could not extract a protocol id from the URL. Skip it.",
        )
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_DETAIL_URL}/{protocol_id}", headers=headers, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()

    # protocols.io wraps responses with a status_code (0/absent = success).
    status = data.get("status_code")
    if status not in (None, 0):
        info = data.get("error_message") or f"status {status}"
        return ExternalProtocolPayload(
            title="",
            source_url=url,
            summary="",
            error=f"protocols.io fetch failed: {info}. Skip and try another URL.",
        )

    payload = parse_protocols_io_json(data, url)
    # The 0-steps stub guard applies ONLY to an import-safe protocol — a
    # restricted protocol's empty steps are intentional, not a stub.
    if payload.import_allowed and not payload.steps:
        payload.error = (
            "parsed to 0 steps (stub or non-protocol page). "
            "Skip and try another URL."
        )
    return payload
