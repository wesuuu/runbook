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
import re

from app.services.ai.subagents.protocol_knowledgebase.licenses import classify_license
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(text: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    stripped = _HTML_TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", html.unescape(stripped)).strip()


def parse_protocols_io_json(
    detail_json: dict, source_url: str
) -> ExternalProtocolPayload:
    """Map a protocols.io protocol-detail JSON object to a payload.

    Pure — no HTTP. ``detail_json`` is the full response body; the protocol
    lives under the ``payload`` key.
    """
    obj = detail_json.get("payload") or {}
    title = (obj.get("title") or "").strip() or "Untitled protocol"
    summary = _clean_html(obj.get("description") or "")

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

    materials = [
        (m.get("name") or "").strip()
        for m in (obj.get("materials") or [])
        if (m.get("name") or "").strip()
    ]
    steps = [
        ExternalProtocolStep(text=text, duration_min=None)
        for s in (obj.get("steps") or [])
        if (text := _clean_html(s.get("description") or ""))
    ]
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
