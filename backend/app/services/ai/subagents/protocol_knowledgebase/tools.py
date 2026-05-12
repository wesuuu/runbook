"""Tools for the protocol_knowledgebase subagent (F-0084).

v1 scope: OpenWetWare only. Searches and fetches public protocols, parses
the wiki-text into a structured payload the parent agent can hand off to
protocol_creator after a human-in-the-loop approval.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

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
