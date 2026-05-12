# F-0084 — protocol_knowledgebase subagent + HITL approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `protocol_knowledgebase` chat subagent that searches OpenWetWare for public protocols, presents candidates, and — only after an explicit pydantic-ai `requires_approval` gate — hands the chosen payload to `protocol_creator` to draft a Batchrite protocol.

**Architecture:** New subagent package next to `research_library`. New parent-agent approval tool in `services/ai/tools/external_protocols.py`. `send_message.py` learns to detect `DeferredToolRequests`, emit a new `approval_required` SSE event, persist the deferred call to `ai_message_history`, and resume on a new `POST /sessions/{id}/messages/approve` endpoint. Frontend gets one new component (`ApprovalCard.svelte`) inside the existing chat panel.

**Tech Stack:** FastAPI · SQLAlchemy async · pydantic-ai 1.75 (`requires_approval` / `DeferredToolRequests`) · subagents-pydantic-ai · httpx.AsyncClient · Svelte 5 runes · Tailwind 4 · shadcn-svelte · Vitest · Playwright (not extended).

**Spec:** [docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md](../specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md)

---

### Task 1: Feature flag in Settings

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/settings.example.yaml`
- Test: `backend/tests/unit/test_settings_external_protocols.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_settings_external_protocols.py
"""Settings exposure for the external_protocols feature flag."""

from app.core.config import Settings


def test_external_protocols_default_off_with_defaults():
    s = Settings()
    assert s.features.external_protocols.enabled is False
    assert s.features.external_protocols.request_timeout_seconds == 10.0
    assert s.features.external_protocols.rate_limit_per_minute == 10


def test_external_protocols_env_override(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED", "true")
    monkeypatch.setenv("BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__RATE_LIMIT_PER_MINUTE", "3")
    s = Settings()
    assert s.features.external_protocols.enabled is True
    assert s.features.external_protocols.rate_limit_per_minute == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_settings_external_protocols.py -v`
Expected: FAIL with `AttributeError: ... 'external_protocols'`.

- [ ] **Step 3: Add the config class**

In `backend/app/core/config.py`, add the model near the existing `OfflineModeFeatureConfig` and register it in `FeaturesConfig`:

```python
class ExternalProtocolsFeatureConfig(BaseModel):
    """External protocol knowledgebase feature flag (F-0084)."""

    enabled: bool = False
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10


class FeaturesConfig(BaseModel):
    """Top-level feature-flag namespace.

    Configure via `settings.yaml` (preferred) or env vars using the
    `BATCHRITE_FEATURES__<FEATURE>__<FIELD>` form.
    """

    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = ExternalProtocolsFeatureConfig()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_settings_external_protocols.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Document the flag in `backend/settings.example.yaml`**

Append a commented-out section at the bottom of `backend/settings.example.yaml` so operators can copy it into their `settings.yaml`:

```yaml
# --- Features ---
# Feature flags follow nested env-var form:
#   BATCHRITE_FEATURES__<FEATURE>__<FIELD>=value
# YAML keys use snake_case under `features:`.
#
# features:
#   external_protocols:
#     # Enable the protocol_knowledgebase chat subagent + HITL approval gate.
#     # Talks to OpenWetWare's MediaWiki API; requires outbound HTTPS. (F-0084)
#     enabled: false
#     # Hard timeout for any single MediaWiki request, in seconds.
#     request_timeout_seconds: 10.0
#     # Per-org token-bucket cap on outbound OpenWetWare requests.
#     rate_limit_per_minute: 10
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/settings.example.yaml backend/tests/unit/test_settings_external_protocols.py
git commit -m "feat(config): add external_protocols feature flag (F-0084)"
```

---

### Task 2: Pure OpenWetWare wiki-text parser

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/__init__.py`
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (parser + result dataclasses only — HTTP tools follow in Task 3)
- Create: `backend/tests/fixtures/openwetware/transformation_of_ecoli.wikitext`
- Create: `backend/tests/unit/test_openwetware_parser.py`

- [ ] **Step 1: Drop in the fixture wiki-text**

Write the fixture verbatim — a real-shaped OpenWetWare protocol page (we are not network-fetching this in tests, we just need representative wiki-text):

```wikitext
'''Sauer: Heat-shock transformation of competent ''E. coli'''''

==Description==
Standard CaCl<sub>2</sub>-prepared chemically competent ''E. coli'' transformation
by 42 °C heat shock. Used by the Sauer lab for routine cloning.

==Materials==
* 100 µL chemically competent DH5α cells (on ice)
* 1–5 µL plasmid DNA (10–100 ng total)
* 900 µL SOC medium, prewarmed to 37 °C
* LB agar plates with 50 µg/mL ampicillin

==Procedure==
# Thaw competent cells on ice for 10 min.
# Add 1–5 µL plasmid DNA, mix gently, incubate on ice for 30 min.
# Heat shock at 42 °C for 90 s. Do not vortex.
# Return tubes to ice for 2 min.
# Add 900 µL prewarmed SOC, recover at 37 °C with shaking for 60 min.
# Plate 100 µL on LB+amp; incubate inverted at 37 °C overnight.
# Count colonies the next day.

==Notes==
* Yields vary 10× across competent-cell preps. Always include a no-DNA control.
* For ligation reactions, plate 200 µL undiluted.
```

- [ ] **Step 2: Write the failing parser test**

```python
# backend/tests/unit/test_openwetware_parser.py
"""Pure parser for OpenWetWare wiki-text — fixture-driven, no HTTP."""

from pathlib import Path

from app.services.ai.subagents.protocol_knowledgebase.tools import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    parse_openwetware_wikitext,
)

FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "openwetware"
    / "transformation_of_ecoli.wikitext"
).read_text()
SOURCE_URL = (
    "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"
)


def test_parser_extracts_title():
    p = parse_openwetware_wikitext(
        FIXTURE,
        displaytitle="Sauer: Heat-shock transformation of competent E. coli",
        source_url=SOURCE_URL,
    )
    assert p.title == "Sauer: Heat-shock transformation of competent E. coli"
    assert p.source_url == SOURCE_URL


def test_parser_extracts_materials():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert len(p.materials) == 4
    assert "competent DH5α" in p.materials[0]


def test_parser_extracts_steps_with_durations():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert len(p.steps) == 7
    assert isinstance(p.steps[0], ExternalProtocolStep)
    # Step 1: "10 min" → 10
    assert p.steps[0].duration_min == 10
    # Step 2: "30 min" → 30
    assert p.steps[1].duration_min == 30
    # Step 3: "90 s" → ceil(90/60)=2 OR exact representation; we want minutes
    #         → spec says int|None; 90 s = 1.5 min → rounded to 2
    assert p.steps[2].duration_min == 2
    # Step 7: no duration → None
    assert p.steps[6].duration_min is None


def test_parser_extracts_notes_and_license():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert "no-DNA control" in (p.notes or "")
    assert p.license == "CC BY-SA 3.0"
    assert "OpenWetWare contributors" in p.attribution


def test_parser_extracts_summary():
    p = parse_openwetware_wikitext(FIXTURE, "Sauer", SOURCE_URL)
    assert "CaCl" in p.summary and "42" in p.summary


def test_parser_handles_missing_sections_gracefully():
    minimal = "''Just a stub page with no sections.''"
    p = parse_openwetware_wikitext(minimal, "stub", SOURCE_URL)
    assert p.title == "stub"
    assert p.materials == []
    assert p.steps == []
    assert p.summary == "" or "stub" in p.summary
    assert p.license == "CC BY-SA 3.0"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_openwetware_parser.py -v`
Expected: FAIL with `ModuleNotFoundError` for the new package.

- [ ] **Step 4: Implement the package marker + parser**

`backend/app/services/ai/subagents/protocol_knowledgebase/__init__.py`:

```python
"""protocol_knowledgebase subagent — external protocol search (F-0084)."""

from app.services.ai.subagents.protocol_knowledgebase.config import build

__all__ = ["build"]
```

`backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (parser portion only — HTTP tools added in Task 3):

```python
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
    r"\b(\d+(?:\.\d+)?)\s*(min(?:s|utes?)?|h(?:rs?|ours?)?|s(?:ec(?:onds?)?)?|seconds?)\b",
    re.IGNORECASE,
)

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
    return re.sub(r"\s+", "", h).strip().lower()


def _split_sections(text: str) -> dict[str, str]:
    """Split wiki-text on `==Heading==` lines into a {normalized_heading: body}."""
    sections: dict[str, str] = {}
    current_key = ""
    current_buf: list[str] = []
    heading_re = re.compile(r"^==+\s*(.+?)\s*==+\s*$")
    for line in text.splitlines():
        m = heading_re.match(line)
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
    """Pull `* …` lines into a list, stripping inline markup."""
    out: list[str] = []
    for raw in body.splitlines():
        if raw.lstrip().startswith("*"):
            out.append(_clean_wiki_inline(raw.lstrip().lstrip("*").strip()))
    return [s for s in out if s]


def _numbered_items(body: str) -> list[str]:
    """Pull `# …` lines into a list, stripping inline markup."""
    out: list[str] = []
    for raw in body.splitlines():
        if raw.lstrip().startswith("#"):
            out.append(_clean_wiki_inline(raw.lstrip().lstrip("#").strip()))
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_openwetware_parser.py -v`
Expected: PASS (all six tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/ \
        backend/tests/fixtures/openwetware/transformation_of_ecoli.wikitext \
        backend/tests/unit/test_openwetware_parser.py
git commit -m "feat(ai): OpenWetWare wiki-text parser for protocol_knowledgebase (F-0084)"
```

---

### Task 3: OpenWetWare HTTP tools + token-bucket rate limit

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`
- Create: `backend/tests/fixtures/openwetware/opensearch_response.json`
- Create: `backend/tests/fixtures/openwetware/parse_response.json`
- Create: `backend/tests/unit/test_openwetware_tools.py`

- [ ] **Step 1: Drop in the MediaWiki response fixtures**

`backend/tests/fixtures/openwetware/opensearch_response.json`:

```json
[
  "transformation of e. coli",
  ["Sauer:Heat shock transformation of E. coli"],
  ["Standard heat-shock transformation"],
  ["https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"]
]
```

`backend/tests/fixtures/openwetware/parse_response.json`:

```json
{
  "parse": {
    "title": "Sauer:Heat shock transformation of E. coli",
    "displaytitle": "Sauer: Heat-shock transformation of competent E. coli",
    "wikitext": {
      "*": "'''Sauer: Heat-shock transformation of competent ''E. coli'''''\n\n==Description==\nStandard CaCl<sub>2</sub>-prepared chemically competent ''E. coli'' transformation by 42 °C heat shock. Used by the Sauer lab for routine cloning.\n\n==Materials==\n* 100 µL chemically competent DH5α cells (on ice)\n* 1–5 µL plasmid DNA (10–100 ng total)\n* 900 µL SOC medium, prewarmed to 37 °C\n* LB agar plates with 50 µg/mL ampicillin\n\n==Procedure==\n# Thaw competent cells on ice for 10 min.\n# Add 1–5 µL plasmid DNA, mix gently, incubate on ice for 30 min.\n# Heat shock at 42 °C for 90 s. Do not vortex.\n# Return tubes to ice for 2 min.\n# Add 900 µL prewarmed SOC, recover at 37 °C with shaking for 60 min.\n# Plate 100 µL on LB+amp; incubate inverted at 37 °C overnight.\n# Count colonies the next day.\n\n==Notes==\n* Yields vary 10× across competent-cell preps. Always include a no-DNA control.\n* For ligation reactions, plate 200 µL undiluted."
    }
  }
}
```

- [ ] **Step 2: Write the failing tools test**

```python
# backend/tests/unit/test_openwetware_tools.py
"""HTTP tools, host allowlist, feature flag, rate limit (F-0084)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import tools as kb

FIX_DIR = Path(__file__).parent.parent / "fixtures" / "openwetware"


@dataclass
class _FakeDeps:
    org_id: UUID
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


def _fake_get(json_path: Path):
    payload = json.loads(json_path.read_text())

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, timeout=None):
        return _Resp()

    return _get


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    kb._RECENT_REQUESTS.clear()
    yield
    kb._RECENT_REQUESTS.clear()


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)
    monkeypatch.setattr(settings.features.external_protocols, "rate_limit_per_minute", 10)
    yield


@pytest.mark.asyncio
async def test_search_disabled_when_flag_off():
    settings.features.external_protocols.enabled = False
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with pytest.raises(ValueError, match="disabled"):
        await kb.search_openwetware(ctx, "anything")


@pytest.mark.asyncio
async def test_fetch_rejects_non_openwetware_host(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with pytest.raises(ValueError, match="openwetware.org"):
        await kb.fetch_openwetware_protocol(ctx, "https://example.com/wiki/foo")


@pytest.mark.asyncio
async def test_search_returns_hits_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    with patch("httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "opensearch_response.json")):
        result = await kb.search_openwetware(ctx, "transformation of e. coli", limit=3)
    assert result.total == 1
    assert result.hits[0].url.startswith("https://openwetware.org/wiki/")
    assert ctx.deps.tool_calls[-1]["tool"] == "search_openwetware"


@pytest.mark.asyncio
async def test_fetch_returns_payload_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps(org_id=uuid4()))
    url = "https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli"
    with patch("httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "parse_response.json")):
        payload = await kb.fetch_openwetware_protocol(ctx, url)
    assert payload.source_url == url
    assert len(payload.steps) == 7
    assert payload.steps[2].duration_min == 2  # 90 s -> ceil(1.5)
    assert ctx.deps.tool_calls[-1]["tool"] == "fetch_openwetware_protocol"
    assert ctx.deps.tool_calls[-1]["source_url"] == url


@pytest.mark.asyncio
async def test_rate_limit_trips_after_threshold(_enabled, monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "rate_limit_per_minute", 2)
    org = uuid4()
    fake_now = {"t": 0.0}
    monkeypatch.setattr(kb, "_now", lambda: fake_now["t"])
    ctx = _FakeCtx(deps=_FakeDeps(org_id=org))
    with patch("httpx.AsyncClient.get", new=_fake_get(FIX_DIR / "opensearch_response.json")):
        await kb.search_openwetware(ctx, "q")
        fake_now["t"] = 1.0
        await kb.search_openwetware(ctx, "q")
        fake_now["t"] = 2.0
        with pytest.raises(ValueError, match="rate limit"):
            await kb.search_openwetware(ctx, "q")
        # After 61s the bucket clears.
        fake_now["t"] = 65.0
        await kb.search_openwetware(ctx, "q")


def test_tool_labels_present():
    assert "search_openwetware" in kb.TOOL_LABELS
    assert "fetch_openwetware_protocol" in kb.TOOL_LABELS
    for v in kb.TOOL_LABELS.values():
        assert v.endswith("…")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_openwetware_tools.py -v`
Expected: FAIL with `AttributeError: module 'app.services.ai.subagents.protocol_knowledgebase.tools' has no attribute 'search_openwetware'`.

- [ ] **Step 4: Implement the HTTP tools, rate limit, and TOOL_LABELS**

Append to `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (keep the parser from Task 2; add imports + HTTP code below it):

```python
# Append-to-tools.py — keep existing parser code above.

import asyncio
import logging
import time
import urllib.parse
from collections import deque
from typing import Callable
from uuid import UUID

import httpx
from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps

logger = logging.getLogger(__name__)

# Human-readable labels for the chat thinking indicator (F-0083). Adding a
# tool here MUST also update the entry — enforced by
# tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_openwetware":         "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
}

_OWW_HOST = "openwetware.org"
_OWW_API = "https://openwetware.org/wiki/api.php"

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_openwetware_tools.py tests/unit/test_openwetware_parser.py -v`
Expected: PASS (parser tests still pass, all new tool tests pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
        backend/tests/fixtures/openwetware/ \
        backend/tests/unit/test_openwetware_tools.py
git commit -m "feat(ai): OpenWetWare HTTP tools + per-org rate limit (F-0084)"
```

---

### Task 4: Subagent config + prompt

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/config.py`
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md`
- Test: `backend/tests/unit/test_protocol_knowledgebase_config.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_protocol_knowledgebase_config.py
"""protocol_knowledgebase build() returns a SubAgentConfig wired with both tools."""

from app.services.ai.subagents import protocol_knowledgebase


def test_build_returns_config_with_search_and_fetch():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_knowledgebase"
    assert "OpenWetWare" in cfg["description"] or "public" in cfg["description"]
    tool_names = [t.__name__ for t in cfg["agent_kwargs"]["tools"]]
    assert "search_openwetware" in tool_names
    assert "fetch_openwetware_protocol" in tool_names


def test_prompt_includes_handoff_contract():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "EXTERNAL_PROTOCOL_SOURCE" in instructions
    assert "verbatim" in instructions
    assert "source_url" in instructions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: FAIL with `ModuleNotFoundError` / config import error.

- [ ] **Step 3: Write the prompt**

`backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md`:

```markdown
You are a public-protocol scout for an organisation's lab. Your only source
right now is OpenWetWare.

## What you do

1. **Search OpenWetWare**: call `search_openwetware(query, limit)` with a
   focused biotech query (technique + organism / target). If the first
   query returns nothing, paraphrase once and retry.

2. **Fetch up to 3 promising hits**: call
   `fetch_openwetware_protocol(url)` on each. Skip a hit if its
   `Procedure` section is empty.

3. **Reply with structured candidates**. Format:

   ```
   1. **<title>** — openwetware.org link
      <one-sentence summary in your own words>

   2. **<title>** — openwetware.org link
      <one-sentence summary in your own words>
   ```

   Cap at 3 candidates. After the markdown list, include a fenced JSON
   block labelled `EXTERNAL_PROTOCOL_SOURCE` containing the full payload
   array (one ExternalProtocolPayload per candidate). The parent agent
   uses this block — never invent it, never edit step text.

4. **End with the handoff line**: "Tell me which one to draft from, or ask
   me to refine — I won't create anything until you give the go-ahead."

## Hard rules

- Copy steps **verbatim** from the source page. Do not paraphrase, merge,
  or invent. If a step is unclear, leave it as-is and flag it to the user.
- Always include `source_url` in each candidate's JSON. Always include the
  `license` ("CC BY-SA 3.0") and `attribution` strings the parser already
  populated.
- Never call any other tool. You do not create protocols. You do not
  modify the org library. You hand candidates back to the parent.
- If the feature flag is off, the tools raise a clear error — surface it
  verbatim to the parent and stop.

## End of turn

Return a single reply containing the markdown candidate list and the
`EXTERNAL_PROTOCOL_SOURCE` JSON block, then stop. The parent agent will
keep the conversation going with the user.
```

- [ ] **Step 4: Write the config**

`backend/app/services/ai/subagents/protocol_knowledgebase/config.py`:

```python
"""Config builder for the protocol_knowledgebase subagent (F-0084)."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.protocol_knowledgebase.tools import (
    fetch_openwetware_protocol,
    search_openwetware,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_knowledgebase subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")
    return SubAgentConfig(
        name="protocol_knowledgebase",
        description=(
            "Searches public protocol repositories (OpenWetWare) and returns "
            "candidate protocols with structured, verbatim summaries. "
            "Dispatch when the user asks for an external/public protocol or "
            "to find a protocol for technique X from open repositories. "
            "Does NOT create or modify protocols — the parent agent handles "
            "the human-in-the-loop conversion after the user confirms."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [search_openwetware, fetch_openwetware_protocol],
        },
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/config.py \
        backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md \
        backend/tests/unit/test_protocol_knowledgebase_config.py
git commit -m "feat(ai): protocol_knowledgebase subagent config + prompt (F-0084)"
```

---

### Task 5: Aggregate tool labels + register subagent in chat_agent

**Files:**
- Modify: `backend/app/services/ai/tool_labels.py`
- Modify: `backend/app/services/ai/chat_agent.py`
- Modify: `backend/app/services/ai/subagents/__init__.py`
- Modify: `backend/tests/unit/test_tool_labels.py` (existing coverage test should pick up new tools automatically — only update if it lists tools by hand)

- [ ] **Step 1: Verify the existing coverage test catches the new labels**

Run: `cd backend && pytest tests/unit/test_tool_labels.py -v`
Expected: existing tests pass (they will fail in Step 3 if the aggregator hasn't been updated, which is what we want).

- [ ] **Step 2: Add a focused test for the new labels**

Append to `backend/tests/unit/test_tool_labels.py` (or create if missing):

```python
def test_resolves_protocol_knowledgebase_labels():
    from app.services.ai.tool_labels import resolve_tool_label

    assert resolve_tool_label("search_openwetware") == "Searching OpenWetWare…"
    assert resolve_tool_label("fetch_openwetware_protocol") == "Reading external protocol…"
```

Run: `cd backend && pytest tests/unit/test_tool_labels.py::test_resolves_protocol_knowledgebase_labels -v`
Expected: FAIL — `Working…` returned because aggregator hasn't merged the new labels.

- [ ] **Step 3: Wire the new labels into the aggregator**

`backend/app/services/ai/tool_labels.py`:

```python
"""Central resolver for chat-agent tool display labels (F-0083)."""

from app.services.ai.subagents.protocol_knowledgebase.tools import (
    TOOL_LABELS as _KNOWLEDGEBASE_LABELS,
)
from app.services.ai.subagents.research_library.tools import (
    TOOL_LABELS as _RESEARCH_LIBRARY_LABELS,
)
from app.services.ai.subagents.shared.protocols.tools import (
    TOOL_LABELS as _PROTOCOL_LABELS,
)

FALLBACK_LABEL = "Working…"

_DISPATCH_LABELS: dict[str, str] = {
    "task": "Thinking…",
    "check_task": "Checking progress…",
    "answer_subagent": "Wrapping up…",
}

_ALL_LABELS: dict[str, str] = {
    **_RESEARCH_LIBRARY_LABELS,
    **_PROTOCOL_LABELS,
    **_KNOWLEDGEBASE_LABELS,
    **_DISPATCH_LABELS,
}


def resolve_tool_label(tool_name: str) -> str:
    """Return the human-readable label for a tool name."""
    return _ALL_LABELS.get(tool_name, FALLBACK_LABEL)
```

- [ ] **Step 4: Register the subagent in chat_agent.py**

In `backend/app/services/ai/subagents/__init__.py`, add the import:

```python
from app.services.ai.subagents import (  # noqa: F401
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)
```

In `backend/app/services/ai/chat_agent.py`, two edits — the import block:

```python
from app.services.ai.subagents import (
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)
```

…and inside `build_chat_agent`, add to the `subagents` list:

```python
subagents = [
    research_library.build(subagent_model),
    protocol_creator.build(creation_model),
    protocol_editor.build(editing_model),
    run_planner.build(subagent_model),
    protocol_knowledgebase.build(subagent_model),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_tool_labels.py -v`
Expected: PASS (the new label test plus existing coverage).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/tool_labels.py \
        backend/app/services/ai/chat_agent.py \
        backend/app/services/ai/subagents/__init__.py \
        backend/tests/unit/test_tool_labels.py
git commit -m "feat(ai): register protocol_knowledgebase subagent + tool labels (F-0084)"
```

---

### Task 6: pydantic-ai HITL primitive — sanity test

**Files:**
- Create: `backend/tests/unit/test_approval_flow.py`

This task does **not** add any product code. It locks down our understanding of the `requires_approval=True` flow so the next task (the approval tool) and Task 8 (send_message_streaming) build on a verified contract.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_approval_flow.py
"""Sanity test for pydantic-ai's requires_approval / DeferredToolRequests flow.

Locks down the contract we depend on in send_message_streaming and the
approve endpoint (F-0084).
"""

from __future__ import annotations

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults


@pytest.mark.asyncio
async def test_requires_approval_returns_deferred_requests():
    calls: list[str] = []

    async def _danger(_ctx, payload: str) -> str:
        calls.append(payload)
        return f"executed:{payload}"

    agent: Agent = Agent(
        "test",
        instructions="Always call the `danger` tool with payload='hello'.",
        tools=[Tool(_danger, requires_approval=True)],
        output_type=[str, DeferredToolRequests],
    )

    result = await agent.run("please call danger")
    assert isinstance(result.output, DeferredToolRequests)
    assert len(result.output.approvals) == 1
    assert calls == []  # tool body did NOT run yet

    call_id = result.output.approvals[0].tool_call_id
    resumed = await agent.run(
        deferred_tool_results=DeferredToolResults(approvals={call_id: True}),
        message_history=result.all_messages(),
    )
    assert calls == ["hello"]
    assert "executed:hello" in str(resumed.output) or resumed.output


@pytest.mark.asyncio
async def test_rejection_does_not_execute_tool():
    calls: list[str] = []

    async def _danger(_ctx, payload: str) -> str:
        calls.append(payload)
        return "executed"

    agent: Agent = Agent(
        "test",
        instructions="Call `danger` with payload='hi'.",
        tools=[Tool(_danger, requires_approval=True)],
        output_type=[str, DeferredToolRequests],
    )
    result = await agent.run("call it")
    assert isinstance(result.output, DeferredToolRequests)
    call_id = result.output.approvals[0].tool_call_id
    await agent.run(
        deferred_tool_results=DeferredToolResults(approvals={call_id: False}),
        message_history=result.all_messages(),
    )
    assert calls == []
```

- [ ] **Step 2: Run test to verify it passes (or fails informatively)**

Run: `cd backend && pytest tests/unit/test_approval_flow.py -v`
Expected: PASS using the pydantic-ai `test` model (which deterministically calls the first available tool). If the `test` model API differs in our installed version, adjust the model string per the pydantic-ai docs but keep the assertions — they're the contract we depend on.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_approval_flow.py
git commit -m "test(ai): pin pydantic-ai requires_approval contract (F-0084)"
```

---

### Task 7: Parent-agent approval tool `create_protocol_from_external_source`

**Files:**
- Create: `backend/app/services/ai/tools/__init__.py`
- Create: `backend/app/services/ai/tools/external_protocols.py`
- Modify: `backend/app/services/ai/tool_labels.py`
- Modify: `backend/app/services/ai/chat_agent.py`
- Test: `backend/tests/unit/test_external_protocols_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_external_protocols_tool.py
"""Approval tool: feature flag gating + audit row + sentinel return string."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.ai.tools.external_protocols import (
    APPROVED_SENTINEL,
    TOOL_LABELS,
    create_protocol_from_external_source,
)


@dataclass
class _FakeDeps:
    org_id: UUID = field(default_factory=uuid4)
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)


@pytest.mark.asyncio
async def test_returns_sentinel_with_payload():
    payload = {"title": "X", "source_url": "https://openwetware.org/wiki/X", "steps": []}
    ctx = _FakeCtx(deps=_FakeDeps())
    result = await create_protocol_from_external_source(
        ctx,
        payload_json=json.dumps(payload),
        title="X",
        source_url="https://openwetware.org/wiki/X",
    )
    assert result.startswith(APPROVED_SENTINEL)
    assert "https://openwetware.org/wiki/X" in result
    assert ctx.deps.tool_calls[-1]["tool"] == "create_protocol_from_external_source"
    assert ctx.deps.tool_calls[-1]["approved"] is True


@pytest.mark.asyncio
async def test_raises_when_feature_disabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="disabled"):
        await create_protocol_from_external_source(
            ctx,
            payload_json="{}",
            title="X",
            source_url="https://openwetware.org/wiki/X",
        )


@pytest.mark.asyncio
async def test_rejects_payload_json_that_does_not_parse():
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="payload_json"):
        await create_protocol_from_external_source(
            ctx,
            payload_json="not-json",
            title="X",
            source_url="https://openwetware.org/wiki/X",
        )


def test_label_present():
    assert TOOL_LABELS["create_protocol_from_external_source"].endswith("…")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_external_protocols_tool.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the tool**

`backend/app/services/ai/tools/__init__.py`:

```python
"""Tools wired directly onto the parent chat Agent.

See .claude/rules/backend-ai.md for layout rules. First occupant: F-0084's
`external_protocols.create_protocol_from_external_source` (approval gate
for converting external protocols into Batchrite protocols).
"""
```

`backend/app/services/ai/tools/external_protocols.py`:

```python
"""Parent-agent approval tool for the F-0084 external protocol flow.

Registered with `requires_approval=True` so the agent run terminates with
a `DeferredToolRequests` when the LLM calls it. The tool body runs only
after the user clicks Approve in the frontend, at which point we record
an audit row and return a sentinel string the parent agent recognises as
"go dispatch protocol_creator with this payload."
"""

from __future__ import annotations

import json
import logging

from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps

logger = logging.getLogger(__name__)

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

    This tool is registered with `requires_approval=True` on the parent
    agent. Calling it pauses the agent run and surfaces an approval card
    to the user. The body below runs **only after** the user explicitly
    approves. It records an audit row and returns the sentinel string
    `EXTERNAL_PROTOCOL_APPROVED\\n<json>`, which the parent prompt is
    instructed to feed to protocol_creator verbatim.

    Args:
        ctx: Run context with shared deps.
        payload_json: The chosen ExternalProtocolPayload as a JSON string.
        title: Protocol title, surfaced on the approval card.
        source_url: Source URL, surfaced on the approval card.
    """
    if not settings.features.external_protocols.enabled:
        raise ValueError("External protocols feature is disabled.")

    try:
        # Validate the payload parses — we don't transform it here.
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
```

- [ ] **Step 4: Add the label to the aggregator**

In `backend/app/services/ai/tool_labels.py` add the import and merge:

```python
from app.services.ai.tools.external_protocols import (
    TOOL_LABELS as _EXTERNAL_PROTOCOL_TOOL_LABELS,
)

_ALL_LABELS: dict[str, str] = {
    **_RESEARCH_LIBRARY_LABELS,
    **_PROTOCOL_LABELS,
    **_KNOWLEDGEBASE_LABELS,
    **_EXTERNAL_PROTOCOL_TOOL_LABELS,
    **_DISPATCH_LABELS,
}
```

- [ ] **Step 5: Register the tool on the parent agent**

In `backend/app/services/ai/chat_agent.py`, import the tool and the `Tool` wrapper:

```python
from pydantic_ai import Agent, Tool
from pydantic_ai.tools import DeferredToolRequests  # used in send_message.py
from app.services.ai.tools.external_protocols import (
    create_protocol_from_external_source,
)
```

Replace the `Agent(... tools=[])` construction with:

```python
agent: Agent[ChatDeps, str] = Agent(
    chat_model,
    instructions=_CHAT_PROMPT,
    deps_type=ChatDeps,
    model_settings=CHAT_AGENT_MODEL_SETTINGS,
    capabilities=[
        SubAgentCapability(
            subagents=subagents,
            default_model=subagent_model,
            include_general_purpose=False,
            max_nesting_depth=1,
        ),
        ContextManagerCapability(
            max_tokens=context_window,
            compress_threshold=settings.compaction_threshold,
            summarization_model=summary_model,
            summary_prompt=_SUMMARY_PROMPT,
            max_tool_output_tokens=2000,
            token_counter=tiktoken_counter,
            on_before_compress=on_before,
            on_after_compress=on_after,
        ),
    ],
    tools=[Tool(create_protocol_from_external_source, requires_approval=True)],
    output_type=[str, DeferredToolRequests],
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_external_protocols_tool.py tests/unit/test_tool_labels.py -v`
Expected: PASS for both files.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/tools/ \
        backend/app/services/ai/tool_labels.py \
        backend/app/services/ai/chat_agent.py \
        backend/tests/unit/test_external_protocols_tool.py
git commit -m "feat(ai): create_protocol_from_external_source approval tool (F-0084)"
```

---

### Task 8: Schemas for the approval-required SSE event + approve request

**Files:**
- Modify: `backend/app/schemas/chat.py`
- Test: `backend/tests/unit/test_chat_schemas_approval.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_chat_schemas_approval.py
"""Approval-related chat schemas (F-0084)."""

import uuid

from app.schemas.chat import (
    ApprovalRequest,
    ApprovalRequiredEvent,
    ExternalProtocolPayloadPreview,
)


def test_approval_required_event_validates():
    ev = ApprovalRequiredEvent(
        type="approval_required",
        tool_call_id="call_abc",
        tool_name="create_protocol_from_external_source",
        title="X",
        source_url="https://openwetware.org/wiki/X",
        assistant_message_id=uuid.uuid4(),
        payload_preview=ExternalProtocolPayloadPreview(
            title="X",
            source_url="https://openwetware.org/wiki/X",
            step_count=7,
            duration_min_total=110,
            license="CC BY-SA 3.0",
        ),
    )
    assert ev.type == "approval_required"


def test_approval_request_requires_fields():
    req = ApprovalRequest(tool_call_id="call_abc", approved=True)
    assert req.approved is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_chat_schemas_approval.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/chat.py`:

```python
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ExternalProtocolPayloadPreview(BaseModel):
    """Compact preview of an ExternalProtocolPayload for the approval card."""

    title: str
    source_url: str
    step_count: int
    duration_min_total: int | None = None
    license: str = "CC BY-SA 3.0"
    deviations: list[str] = []  # optional human-readable list for the card


class ApprovalRequiredEvent(BaseModel):
    """SSE event yielded when agent.run terminates on a deferred tool call."""

    type: Literal["approval_required"]
    tool_call_id: str
    tool_name: str
    title: str
    source_url: str
    payload_preview: ExternalProtocolPayloadPreview
    assistant_message_id: UUID


class ApprovalRequest(BaseModel):
    """Body for `POST /sessions/{id}/messages/approve`."""

    tool_call_id: str
    approved: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_chat_schemas_approval.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/chat.py backend/tests/unit/test_chat_schemas_approval.py
git commit -m "feat(schemas): approval-required event + approval request (F-0084)"
```

---

### Task 9: `send_message_streaming` — detect DeferredToolRequests and emit approval_required

**Files:**
- Modify: `backend/app/services/ai/send_message.py`
- Test: `backend/tests/unit/test_send_message_approval.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_send_message_approval.py
"""send_message_streaming emits approval_required when agent.run returns
DeferredToolRequests, persists the placeholder assistant row, and does NOT
emit `done`."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import DeferredToolRequests

from app.services.ai.send_message import send_message_streaming


@pytest.mark.asyncio
async def test_emits_approval_required_when_deferred(monkeypatch):
    """When agent.run returns a DeferredToolRequests, stream should yield
    an approval_required event and persist placeholder + history. No done."""
    session = MagicMock()
    session.id = uuid.uuid4()
    session.org_id = uuid.uuid4()
    session.title = "Test"
    session.ai_message_history = None

    call_part = ToolCallPart(
        tool_name="create_protocol_from_external_source",
        args={
            "payload_json": '{"title":"X","source_url":"https://openwetware.org/wiki/X","steps":[]}',
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
        },
        tool_call_id="call_abc",
    )
    deferred = DeferredToolRequests(calls=[], approvals=[call_part], metadata={})
    fake_result = SimpleNamespace(
        output=deferred,
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        return fake_result

    fake_agent = SimpleNamespace(run=_fake_run)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )

    db = AsyncMock()
    events = []
    async for ev in send_message_streaming(
        db=db,
        session=session,
        user_content="convert it",
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "approval_required" in types
    assert "done" not in types
    approval = next(e for e in events if e["type"] == "approval_required")
    assert approval["tool_call_id"] == "call_abc"
    assert approval["tool_name"] == "create_protocol_from_external_source"
    assert approval["title"] == "X"
    assert approval["source_url"] == "https://openwetware.org/wiki/X"
    assert "assistant_message_id" in approval
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_send_message_approval.py -v`
Expected: FAIL — `done` is currently yielded unconditionally.

- [ ] **Step 3: Modify send_message_streaming**

In `backend/app/services/ai/send_message.py`, add the import:

```python
import json
from pydantic_ai.tools import DeferredToolRequests
```

Between **step 7** (de-dup sources) and **step 8** (sanitize + assemble assistant message) in the existing function, branch on the result type. Replace the existing assistant-message assembly + final `done` yield with:

```python
    # ── 7b. Branch: deferred-tool approval gate? ─────────────────────────────
    deferred = (
        result.output if isinstance(result.output, DeferredToolRequests) else None
    )
    pending_approval_call = (
        deferred.approvals[0] if deferred and deferred.approvals else None
    )

    if pending_approval_call is not None:
        # The agent paused on a requires_approval tool. Persist a placeholder
        # assistant row + the message history (with the deferred call) so the
        # approve endpoint can resume. Do NOT yield `done`.
        args = pending_approval_call.args or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        title = str(args.get("title") or "")
        source_url = str(args.get("source_url") or "")
        payload_json_raw = args.get("payload_json") or "{}"
        try:
            payload = json.loads(payload_json_raw) if isinstance(payload_json_raw, str) else payload_json_raw
        except Exception:
            payload = {}

        steps = payload.get("steps") if isinstance(payload, dict) else None
        step_count = len(steps) if isinstance(steps, list) else 0
        durations = [s.get("duration_min") for s in steps or [] if isinstance(s, dict)]
        duration_min_total = sum(d for d in durations if isinstance(d, int)) or None

        payload_preview = {
            "title": title,
            "source_url": source_url,
            "step_count": step_count,
            "duration_min_total": duration_min_total,
            "license": (payload.get("license") if isinstance(payload, dict) else None) or "CC BY-SA 3.0",
            "deviations": [],
        }

        history_payload = ModelMessagesTypeAdapter.dump_python(
            result.all_messages(), mode="json"
        )
        placeholder_meta = {
            "pending_approval": {
                "tool_call_id": pending_approval_call.tool_call_id,
                "tool_name": pending_approval_call.tool_name,
                "title": title,
                "source_url": source_url,
                "payload_preview": payload_preview,
            }
        }
        if deps.tool_calls:
            placeholder_meta["tool_calls"] = deps.tool_calls

        placeholder = ChatMessage(
            session_id=session_pk,
            role=ChatMessageRole.ASSISTANT,
            content="Awaiting your approval to draft the selected protocol.",
            metadata_=placeholder_meta,
        )
        async with AsyncSessionLocal() as writer:
            writer.add(placeholder)
            await writer.execute(
                update(ChatSession)
                .where(ChatSession.id == session_pk)
                .values(ai_message_history=history_payload)
            )
            await writer.commit()
            await writer.refresh(placeholder)

        try:
            session.ai_message_history = history_payload
        except Exception:
            logger.debug("Could not refresh in-memory session.ai_message_history")

        yield {
            "type": "approval_required",
            "tool_call_id": pending_approval_call.tool_call_id,
            "tool_name": pending_approval_call.tool_name,
            "title": title,
            "source_url": source_url,
            "payload_preview": payload_preview,
            "assistant_message_id": str(placeholder.id),
        }
        return  # explicit: no done event
```

Leave the rest of the function (assistant-message assembly + writer + final `done`) unchanged for the str-output path.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_send_message_approval.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole unit suite to catch regressions**

Run: `cd backend && pytest tests/unit/ -x -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/tests/unit/test_send_message_approval.py
git commit -m "feat(chat): emit approval_required event on deferred tool calls (F-0084)"
```

---

### Task 10: `resume_message_streaming` for the approve endpoint

**Files:**
- Modify: `backend/app/services/ai/send_message.py`
- Test: `backend/tests/unit/test_resume_message_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_resume_message_streaming.py
"""resume_message_streaming: resumes a deferred tool call with DeferredToolResults."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.send_message import resume_message_streaming


@pytest.mark.asyncio
async def test_resume_yields_done_with_assistant_message(monkeypatch):
    session = MagicMock()
    session.id = uuid.uuid4()
    session.org_id = uuid.uuid4()
    session.title = "Test"
    session.ai_message_history = []

    # Pre-existing placeholder assistant row with pending_approval metadata.
    placeholder = MagicMock()
    placeholder.id = uuid.uuid4()
    placeholder.metadata_ = {
        "pending_approval": {
            "tool_call_id": "call_abc",
            "tool_name": "create_protocol_from_external_source",
            "title": "X",
            "source_url": "https://openwetware.org/wiki/X",
            "payload_preview": {},
        }
    }

    # agent.run returns a normal str output this time.
    fake_result = SimpleNamespace(
        output="Drafted [X](/protocols/123).",
        all_messages=lambda: [],
    )

    async def _fake_run(*a, **kw):
        # Assert we passed deferred_tool_results.
        assert "deferred_tool_results" in kw
        return fake_result

    fake_agent = SimpleNamespace(run=_fake_run)
    monkeypatch.setattr(
        "app.services.ai.send_message.build_chat_agent",
        AsyncMock(return_value=fake_agent),
    )

    db = AsyncMock()
    events = []
    async for ev in resume_message_streaming(
        db=db,
        session=session,
        placeholder=placeholder,
        tool_call_id="call_abc",
        approved=True,
        user_id=uuid.uuid4(),
        is_org_admin=False,
    ):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert "Drafted" in done["assistant_message"]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_resume_message_streaming.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement resume_message_streaming**

Append to `backend/app/services/ai/send_message.py`:

```python
from pydantic_ai.tools import DeferredToolResults


async def resume_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    placeholder: ChatMessage,
    tool_call_id: str,
    approved: bool,
    user_id: UUID,
    is_org_admin: bool,
) -> AsyncIterator[dict[str, Any]]:
    """Resume a chat turn that paused on a DeferredToolRequests gate.

    Persists the user's approval/rejection as a user ChatMessage, then resumes
    `agent.run` with `deferred_tool_results=DeferredToolResults(approvals=...)`
    and the session's existing message history. The rest of the stream is
    identical to send_message_streaming.
    """
    session_pk: UUID = session.id
    session_org_id: UUID = session.org_id
    existing_history = session.ai_message_history

    decision_text = (
        "Approved external protocol conversion."
        if approved
        else "Rejected the external protocol conversion."
    )
    user_msg = ChatMessage(
        session_id=session_pk,
        role=ChatMessageRole.USER,
        content=decision_text,
    )
    db.add(user_msg)
    await db.flush()
    await db.commit()
    await db.refresh(user_msg)

    state = CompactionState()
    deps = ChatDeps(
        db=db, org_id=session_org_id, user_id=user_id, is_org_admin=is_org_admin
    )

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _parent_event_handler(_ctx, stream):
        async for event in stream:
            if isinstance(event, FunctionToolCallEvent):
                name = event.part.tool_name
                await event_queue.put(
                    {"type": "tool_start", "tool": name, "label": resolve_tool_label(name)}
                )
            elif isinstance(event, FunctionToolResultEvent):
                name = event.result.tool_name
                await event_queue.put({"type": "tool_end", "tool": name})

    async def _subagent_tool_event(event_type: str, name: str) -> None:
        if event_type == "tool_start":
            await event_queue.put(
                {"type": "tool_start", "tool": name, "label": resolve_tool_label(name)}
            )
        else:
            await event_queue.put({"type": "tool_end", "tool": name})

    deps.tool_event_callback = _subagent_tool_event

    agent = await build_chat_agent(db, session_org_id, state)

    message_history = None
    if existing_history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(existing_history)
        except Exception:
            logger.warning(
                "Failed to deserialize ai_message_history for session %s on resume",
                session_pk,
            )

    deferred_results = DeferredToolResults(approvals={tool_call_id: approved})

    run_task: asyncio.Task = asyncio.create_task(
        agent.run(
            deps=deps,
            message_history=message_history,
            event_stream_handler=_parent_event_handler,
            deferred_tool_results=deferred_results,
        )
    )

    try:
        while not run_task.done() or not event_queue.empty():
            queue_get = asyncio.create_task(event_queue.get())
            done_set, _pending = await asyncio.wait(
                {queue_get, run_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if queue_get in done_set:
                ev = queue_get.result()
                if ev is not None:
                    yield ev
            else:
                queue_get.cancel()
        result = await run_task
    except Exception:
        logger.exception("Chat agent resume failed for session %s", session_pk)
        if not run_task.done():
            run_task.cancel()
        yield {"type": "error", "detail": "Failed to resume AI response"}
        return

    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Tool-call session commit failed on resume: %s", exc)
        try:
            await db.rollback()
        except Exception:
            logger.exception("Rollback failed on resume")

    seen: set[UUID] = set()
    unique_sources: list[RetrievedChunk] = []
    for s in deps.sources:
        if s.chunk_id not in seen:
            seen.add(s.chunk_id)
            unique_sources.append(s)

    assistant_content = sanitize_output(result.output)
    meta: dict[str, Any] = {}
    if unique_sources:
        meta["sources"] = [
            {
                "document_id": str(s.document_id),
                "document_title": s.document_title,
                "chunk_id": str(s.chunk_id),
                "chunk_index": s.chunk_index,
                "page_number": s.page_number,
                "score": s.score,
                "snippet": s.content[:200],
            }
            for s in unique_sources
        ]
    if deps.tool_calls:
        meta["tool_calls"] = deps.tool_calls

    history_payload = ModelMessagesTypeAdapter.dump_python(
        result.all_messages(), mode="json"
    )

    # UPDATE the placeholder row in place; do not create a duplicate.
    async with AsyncSessionLocal() as writer:
        await writer.execute(
            update(ChatMessage)
            .where(ChatMessage.id == placeholder.id)
            .values(content=assistant_content, metadata_=meta or None)
        )
        await writer.execute(
            update(ChatSession)
            .where(ChatSession.id == session_pk)
            .values(ai_message_history=history_payload)
        )
        await writer.commit()

    try:
        session.ai_message_history = history_payload
    except Exception:
        logger.debug("Could not refresh in-memory session.ai_message_history on resume")

    placeholder.content = assistant_content
    placeholder.metadata_ = meta or None
    yield {
        "type": "done",
        "user_message": ChatMessageResponse.model_validate(user_msg).model_dump(mode="json"),
        "assistant_message": ChatMessageResponse.model_validate(placeholder).model_dump(mode="json"),
        "sources": [
            ChatSourceReference(
                document_id=s.document_id,
                document_title=s.document_title,
                chunk_id=s.chunk_id,
                chunk_index=s.chunk_index,
                page_number=s.page_number,
                score=s.score,
                snippet=s.content[:200],
            ).model_dump(mode="json")
            for s in unique_sources
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_resume_message_streaming.py tests/unit/test_send_message_approval.py -v`
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/send_message.py backend/tests/unit/test_resume_message_streaming.py
git commit -m "feat(chat): resume_message_streaming for deferred-tool approval (F-0084)"
```

---

### Task 11: `POST /sessions/{id}/messages/approve` endpoint

**Files:**
- Modify: `backend/app/api/endpoints/chat.py`
- Test: `backend/tests/integration/test_chat_approve_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_chat_approve_endpoint.py
"""POST /sessions/{id}/messages/approve — endpoint contract.

Round-trip behaviour with the agent is covered in
test_protocol_knowledgebase_handoff.py; this file checks the endpoint
plumbing (auth, 404, 409, schema).
"""

from __future__ import annotations

import json
import uuid

import pytest

# fixtures from conftest: async_client, auth_headers, db, make_session, make_message


@pytest.mark.asyncio
async def test_returns_404_for_unknown_session(async_client, auth_headers):
    resp = await async_client.post(
        f"/api/v1/chat/sessions/{uuid.uuid4()}/messages/approve",
        json={"tool_call_id": "x", "approved": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_returns_409_when_no_pending_approval(
    async_client, auth_headers, make_session
):
    session = await make_session()
    resp = await async_client.post(
        f"/api/v1/chat/sessions/{session.id}/messages/approve",
        json={"tool_call_id": "nothing-here", "approved": True},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["error"] == "no_pending_approval"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_chat_approve_endpoint.py -v`
Expected: FAIL — endpoint doesn't exist (404 from FastAPI itself, or import errors in the test).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/endpoints/chat.py`, add (near the streaming endpoint; follow the same auth/dep pattern):

```python
from fastapi import HTTPException
from sqlalchemy import select, desc
from app.schemas.chat import ApprovalRequest
from app.services.ai.send_message import resume_message_streaming


@router.post("/sessions/{session_id}/messages/approve")
async def approve_message(
    session_id: UUID,
    body: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Resume a chat turn that paused on a DeferredToolRequests gate."""
    session = await db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.org_id == current_user.org_id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    placeholder = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    pending = (placeholder.metadata_ or {}).get("pending_approval") if placeholder else None
    if not pending or pending.get("tool_call_id") != body.tool_call_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "no_pending_approval"},
        )

    async def _stream():
        async for ev in resume_message_streaming(
            db=db,
            session=session,
            placeholder=placeholder,
            tool_call_id=body.tool_call_id,
            approved=body.approved,
            user_id=current_user.id,
            is_org_admin=current_user.is_org_admin,
        ):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_chat_approve_endpoint.py -v`
Expected: PASS (both 404 and 409 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/chat.py backend/tests/integration/test_chat_approve_endpoint.py
git commit -m "feat(chat): POST /sessions/{id}/messages/approve endpoint (F-0084)"
```

---

### Task 12: Prompt updates (parent chat + protocol_creator)

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`
- Modify: `backend/app/services/ai/subagents/protocol_creator/prompt.md`

No code test — covered end-to-end by Task 13.

- [ ] **Step 1: Update `prompts/chat_agent.md`**

Append a new section under the existing dispatch guidance:

```markdown
## External protocols (OpenWetWare)

When the user asks for a public protocol, a protocol they don't have, or
something "from OpenWetWare", dispatch the `protocol_knowledgebase`
subagent. It returns a markdown list of candidates plus a fenced
`EXTERNAL_PROTOCOL_SOURCE` JSON block.

Surface the candidates to the user. Do NOT call any creation tool yet.

If the user wants to refine — different selection, different organism,
different steps — chat with them. You may re-dispatch
`protocol_knowledgebase` with a refined query. Reflect any user-requested
parameter overrides back at them in plain language before proceeding.

When the user explicitly confirms ("yes, convert it" / "create it" /
"draft this one"), call the parent tool
`create_protocol_from_external_source(payload_json, title, source_url)`
with the chosen candidate's JSON from the `EXTERNAL_PROTOCOL_SOURCE`
block. This tool requires the user's approval — the run will pause and a
confirmation card will be shown to the user.

After the tool returns a string starting with `EXTERNAL_PROTOCOL_APPROVED`,
extract the JSON that follows and dispatch `protocol_creator` with a
prompt of the form:

  "Draft a protocol from the following external source. Copy steps
  verbatim. Cite the source URL in the description.
  EXTERNAL_PROTOCOL_SOURCE:
  <payload JSON>"

Never call `create_protocol_from_external_source` without an explicit
in-turn user confirmation. Never invent a payload.
```

- [ ] **Step 2: Update `protocol_creator/prompt.md`**

Insert a new section after the existing "Workflow" section (before "Creating custom unit ops"):

```markdown
## External protocol seeds (F-0084)

If the brief from the parent contains a fenced `EXTERNAL_PROTOCOL_SOURCE`
JSON block, treat it as the source of truth:

- Copy each `steps[].text` verbatim into the new step's `description`.
- Use `steps[].duration_min` where present; otherwise estimate as you
  normally would.
- Include `source_url` and `attribution` in the protocol description.
- Note the license: "CC BY-SA 3.0 — OpenWetWare".
- Do **not** invent steps not present in the source. If the source is
  missing a step you'd normally expect, leave the gap and flag it to the
  user.
- If the source contains parameter overrides the user negotiated in chat
  (e.g. "100 µg/mL ampicillin instead of 50 µg/mL"), apply those
  overrides and note the deviation in the protocol description.
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/ai/prompts/chat_agent.md \
        backend/app/services/ai/subagents/protocol_creator/prompt.md
git commit -m "docs(ai): chat + protocol_creator prompts for HITL external protocols (F-0084)"
```

---

### Task 13: End-to-end integration test (subagent → approval → protocol_creator)

**Files:**
- Create: `backend/tests/integration/test_protocol_knowledgebase_handoff.py`

This test is **the** acceptance test for the feature. It mocks `httpx.AsyncClient.get` and (for the agent layer) uses a `FunctionModel` from pydantic-ai's test utilities to deterministically drive tool calls, so it does not depend on a real LLM.

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/integration/test_protocol_knowledgebase_handoff.py
"""End-to-end: protocol_knowledgebase → approval gate → protocol_creator.

Mocks httpx for OpenWetWare and pydantic-ai's model to drive deterministic
tool calls. Does not hit any real network.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import httpx

from app.core.config import settings
from app.models.science import Protocol
from sqlalchemy import select

FIX = Path(__file__).parent.parent / "fixtures" / "openwetware"


def _fake_get_factory():
    """Return an async get() that routes by `params['action']`."""
    opensearch = json.loads((FIX / "opensearch_response.json").read_text())
    parse = json.loads((FIX / "parse_response.json").read_text())

    async def _get(self, url, params=None, timeout=None):
        action = (params or {}).get("action")

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        return _Resp(opensearch if action == "opensearch" else parse)

    return _get


@pytest.mark.asyncio
async def test_full_flow_creates_protocol_after_approval(
    async_client, auth_headers, make_session, db, monkeypatch
):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)
    session = await make_session()

    captured = {"tool_call_id": None}

    with patch.object(httpx.AsyncClient, "get", new=_fake_get_factory()):
        # 1) Search turn → candidates surfaced
        async with async_client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session.id}/messages/stream",
            headers=auth_headers,
            json={"content": "find an OpenWetWare protocol for transformation of E. coli"},
        ) as resp:
            assert resp.status_code == 200
            saw_search_tool = False
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[len("data: "):])
                if ev.get("type") == "tool_start" and ev["tool"] == "search_openwetware":
                    saw_search_tool = True
                if ev.get("type") == "done":
                    break
            assert saw_search_tool

        # 2) Convert turn → approval gate
        async with async_client.stream(
            "POST",
            f"/api/v1/chat/sessions/{session.id}/messages/stream",
            headers=auth_headers,
            json={"content": "use that one, convert it to a Batchrite protocol"},
        ) as resp:
            assert resp.status_code == 200
            saw_done = False
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[len("data: "):])
                if ev.get("type") == "approval_required":
                    captured["tool_call_id"] = ev["tool_call_id"]
                    assert ev["tool_name"] == "create_protocol_from_external_source"
                    assert "openwetware.org" in ev["source_url"]
                if ev.get("type") == "done":
                    saw_done = True
            assert captured["tool_call_id"] is not None
            assert not saw_done

        # 3) Approve → protocol_creator runs → Protocol row created
        resp = await async_client.post(
            f"/api/v1/chat/sessions/{session.id}/messages/approve",
            headers=auth_headers,
            json={"tool_call_id": captured["tool_call_id"], "approved": True},
        )
        assert resp.status_code == 200
        # consume stream
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
        assert b'"type": "done"' in body or b'"type":"done"' in body

    # Protocol row exists with the OWW title
    rows = (await db.scalars(select(Protocol).where(Protocol.org_id == session.org_id))).all()
    assert any("Heat-shock" in (p.name or "") for p in rows)


@pytest.mark.asyncio
async def test_rejection_path_does_not_create_protocol(
    async_client, auth_headers, make_session, db, monkeypatch
):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)
    session = await make_session()
    captured = {"tool_call_id": None}

    with patch.object(httpx.AsyncClient, "get", new=_fake_get_factory()):
        async with async_client.stream(
            "POST", f"/api/v1/chat/sessions/{session.id}/messages/stream",
            headers=auth_headers,
            json={"content": "find an OWW protocol for transformation, then convert it"},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[len("data: "):])
                    if ev.get("type") == "approval_required":
                        captured["tool_call_id"] = ev["tool_call_id"]
        assert captured["tool_call_id"] is not None

        resp = await async_client.post(
            f"/api/v1/chat/sessions/{session.id}/messages/approve",
            headers=auth_headers,
            json={"tool_call_id": captured["tool_call_id"], "approved": False},
        )
        assert resp.status_code == 200
        async for _ in resp.aiter_bytes():
            pass

    rows = (await db.scalars(select(Protocol).where(Protocol.org_id == session.org_id))).all()
    assert len(rows) == 0
```

- [ ] **Step 2: Run the integration test**

Run: `cd backend && pytest tests/integration/test_protocol_knowledgebase_handoff.py -v -s`
Expected: PASS for both cases. If the LLM model used by the test fixtures is non-deterministic, this test may need a `FunctionModel` injected — extend the existing chat test fixtures rather than mocking the agent directly.

If the LLM in the test environment isn't deterministic, this is the right place to switch over to pydantic-ai's `FunctionModel` to script the tool calls. Bias the fix toward keeping the assertions intact.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_protocol_knowledgebase_handoff.py
git commit -m "test(integration): F-0084 round-trip approval + draft + rejection"
```

---

### Task 14: Frontend — Zod schemas + api helper

**Files:**
- Modify: `frontend/src/lib/schemas/chat.ts`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/schemas/chat.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/schemas/chat.test.ts
import { describe, it, expect } from 'vitest';
import {
  ApprovalRequiredEventSchema,
  ExternalProtocolPayloadPreviewSchema,
  ApprovalRequestSchema,
} from '$lib/schemas/chat';

describe('approval schemas', () => {
  it('validates an approval_required event', () => {
    const ev = ApprovalRequiredEventSchema.parse({
      type: 'approval_required',
      tool_call_id: 'call_abc',
      tool_name: 'create_protocol_from_external_source',
      title: 'X',
      source_url: 'https://openwetware.org/wiki/X',
      assistant_message_id: '00000000-0000-0000-0000-000000000001',
      payload_preview: {
        title: 'X',
        source_url: 'https://openwetware.org/wiki/X',
        step_count: 7,
        license: 'CC BY-SA 3.0',
      },
    });
    expect(ev.tool_call_id).toBe('call_abc');
  });

  it('rejects malformed payload_preview', () => {
    expect(() =>
      ExternalProtocolPayloadPreviewSchema.parse({ title: 'X' }),
    ).toThrow();
  });

  it('validates an approval request', () => {
    const req = ApprovalRequestSchema.parse({
      tool_call_id: 'call_abc',
      approved: true,
    });
    expect(req.approved).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/schemas/chat.test.ts`
Expected: FAIL — schemas not exported.

- [ ] **Step 3: Add the schemas**

Append to `frontend/src/lib/schemas/chat.ts`:

```ts
import { z } from 'zod';

export const ExternalProtocolPayloadPreviewSchema = z.object({
  title: z.string(),
  source_url: z.string().url(),
  step_count: z.number().int().nonnegative(),
  duration_min_total: z.number().int().nullable().optional(),
  license: z.string().default('CC BY-SA 3.0'),
  deviations: z.array(z.string()).default([]),
});
export type ExternalProtocolPayloadPreview = z.infer<typeof ExternalProtocolPayloadPreviewSchema>;

export const ApprovalRequiredEventSchema = z.object({
  type: z.literal('approval_required'),
  tool_call_id: z.string(),
  tool_name: z.string(),
  title: z.string(),
  source_url: z.string().url(),
  payload_preview: ExternalProtocolPayloadPreviewSchema,
  assistant_message_id: z.string().uuid(),
});
export type ApprovalRequiredEvent = z.infer<typeof ApprovalRequiredEventSchema>;

export const ApprovalRequestSchema = z.object({
  tool_call_id: z.string(),
  approved: z.boolean(),
});
export type ApprovalRequest = z.infer<typeof ApprovalRequestSchema>;
```

- [ ] **Step 4: Add the api helper**

Append to `frontend/src/lib/api.ts` (alongside the existing `streamChatMessage` or equivalent):

```ts
import type { ApprovalRequest } from '$lib/schemas/chat';

/** Approve or reject a pending external-protocol conversion. Returns the
 *  SSE Response so the caller can stream events. */
export async function approveChatMessage(
  sessionId: string,
  body: ApprovalRequest,
): Promise<Response> {
  return fetch(`/api/v1/chat/sessions/${sessionId}/messages/approve`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/schemas/chat.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/schemas/chat.ts frontend/src/lib/api.ts frontend/src/lib/schemas/chat.test.ts
git commit -m "feat(frontend): approval schemas + approveChatMessage api helper (F-0084)"
```

---

### Task 15: `ApprovalCard.svelte` + unit test

**Files:**
- Create: `frontend/src/lib/components/ai/ApprovalCard.svelte`
- Create: `frontend/src/lib/components/ai/ApprovalCard.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/components/ai/ApprovalCard.test.ts
import { render, fireEvent, screen } from '@testing-library/svelte';
import { describe, it, expect, vi } from 'vitest';
import ApprovalCard from './ApprovalCard.svelte';

const baseProps = {
  toolCallId: 'call_abc',
  toolName: 'create_protocol_from_external_source',
  title: 'Sauer: Heat-shock transformation of competent E. coli',
  sourceUrl: 'https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli',
  payloadPreview: {
    title: 'Sauer: Heat-shock transformation of competent E. coli',
    source_url: 'https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli',
    step_count: 7,
    duration_min_total: 110,
    license: 'CC BY-SA 3.0',
    deviations: [],
  },
};

describe('ApprovalCard', () => {
  it('renders title, source url, and step count', () => {
    render(ApprovalCard, { ...baseProps, onApprove: vi.fn(), onReject: vi.fn() });
    expect(screen.getByText(/Sauer: Heat-shock/)).toBeTruthy();
    expect(screen.getByText(/openwetware\.org/)).toBeTruthy();
    expect(screen.getByText(/7/)).toBeTruthy();
  });

  it('fires onApprove with the tool_call_id', async () => {
    const onApprove = vi.fn();
    render(ApprovalCard, { ...baseProps, onApprove, onReject: vi.fn() });
    await fireEvent.click(screen.getByRole('button', { name: /approve/i }));
    expect(onApprove).toHaveBeenCalledWith('call_abc');
  });

  it('fires onReject with the tool_call_id', async () => {
    const onReject = vi.fn();
    render(ApprovalCard, { ...baseProps, onApprove: vi.fn(), onReject });
    await fireEvent.click(screen.getByRole('button', { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith('call_abc');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/components/ai/ApprovalCard.test.ts`
Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component**

`frontend/src/lib/components/ai/ApprovalCard.svelte`:

```svelte
<script lang="ts">
    import type { ExternalProtocolPayloadPreview } from "$lib/schemas/chat";

    interface Props {
        toolCallId: string;
        toolName: string;
        title: string;
        sourceUrl: string;
        payloadPreview: ExternalProtocolPayloadPreview;
        onApprove: (toolCallId: string) => void;
        onReject: (toolCallId: string) => void;
    }
    let {
        toolCallId,
        toolName,
        title,
        sourceUrl,
        payloadPreview,
        onApprove,
        onReject,
    }: Props = $props();

    const sourceHost = $derived.by(() => {
        try {
            return new URL(sourceUrl).host;
        } catch {
            return sourceUrl;
        }
    });
</script>

<div
    class="rounded-lg border border-border/60 bg-background overflow-hidden"
    role="region"
    aria-label="Approval required"
>
    <div
        class="flex items-center justify-between px-3.5 py-2 border-b border-border/40 bg-primary/5"
    >
        <div class="flex items-center gap-2">
            <div
                class="w-5 h-5 rounded-md bg-primary/10 flex items-center justify-center"
            >
                <svg
                    viewBox="0 0 24 24"
                    class="w-3 h-3 text-primary"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                >
                    <path d="M9 12l2 2 4-4" />
                    <circle cx="12" cy="12" r="9" />
                </svg>
            </div>
            <span class="text-[12px] font-semibold tracking-tight"
                >Confirm protocol creation</span
            >
        </div>
        <span
            class="text-[10px] uppercase tracking-wider text-muted-foreground font-mono"
            >human in the loop</span
        >
    </div>

    <div class="px-3.5 py-3 space-y-2.5">
        <div>
            <div
                class="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-0.5"
            >
                name
            </div>
            <div class="text-sm font-medium">{title}</div>
        </div>
        <div>
            <div
                class="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mb-0.5"
            >
                source
            </div>
            <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                class="text-[13px] text-primary underline underline-offset-2 break-all font-mono"
            >
                {sourceHost}{new URL(sourceUrl).pathname}
            </a>
        </div>
        <div class="grid grid-cols-2 gap-2.5 pt-1">
            <div class="rounded-md bg-muted/40 px-2.5 py-1.5">
                <div
                    class="text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
                >
                    steps
                </div>
                <div class="text-sm font-medium mt-0.5">
                    {payloadPreview.step_count}
                    <span class="text-muted-foreground font-normal text-xs"
                        >verbatim</span
                    >
                </div>
            </div>
            <div class="rounded-md bg-muted/40 px-2.5 py-1.5">
                <div
                    class="text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
                >
                    duration
                </div>
                <div class="text-sm font-medium mt-0.5">
                    {payloadPreview.duration_min_total
                        ? `~${payloadPreview.duration_min_total} min`
                        : "—"}
                </div>
            </div>
            {#if payloadPreview.deviations && payloadPreview.deviations.length > 0}
                <div class="rounded-md bg-muted/40 px-2.5 py-1.5 col-span-2">
                    <div
                        class="text-[10px] uppercase tracking-[0.18em] text-muted-foreground"
                    >
                        deviations from source
                    </div>
                    <ul class="text-[13px] mt-1 space-y-0.5">
                        {#each payloadPreview.deviations as d}
                            <li>{d}</li>
                        {/each}
                    </ul>
                </div>
            {/if}
        </div>
        <p
            class="text-[11.5px] text-muted-foreground leading-snug pt-1"
        >
            Steps will be copied verbatim from the source page. License:
            <span class="font-mono">{payloadPreview.license}</span>. You can
            edit everything after creation.
        </p>
    </div>

    <div
        class="flex items-center justify-end gap-2 px-3.5 py-2.5 border-t border-border/40 bg-muted/40"
    >
        <button
            type="button"
            onclick={() => onReject(toolCallId)}
            class="text-[13px] font-medium px-3 py-1.5 rounded-md text-muted-foreground hover:bg-background transition-colors cursor-pointer"
        >
            Reject
        </button>
        <button
            type="button"
            onclick={() => onApprove(toolCallId)}
            class="text-[13px] font-semibold px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:brightness-110 transition flex items-center gap-1.5 cursor-pointer"
        >
            <svg
                viewBox="0 0 24 24"
                class="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                aria-hidden="true"
            >
                <path d="M5 12l5 5L20 7" />
            </svg>
            Approve &amp; draft
        </button>
    </div>
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/components/ai/ApprovalCard.test.ts`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/ai/ApprovalCard.svelte \
        frontend/src/lib/components/ai/ApprovalCard.test.ts
git commit -m "feat(frontend): ApprovalCard component for HITL approvals (F-0084)"
```

---

### Task 16: Chat-store SSE handling + ChatPanel render

**Files:**
- Modify: `frontend/src/lib/chat-store.svelte.ts` (the SSE consumer that drives ChatPanel — confirm exact filename with `grep -ln "registerScrollFn" frontend/src/lib/`)
- Modify: `frontend/src/lib/components/ai/ChatPanel.svelte`

No new unit test — ApprovalCard.test.ts covers the component; the integration test in Task 13 covers the round-trip backend; this task glues them together.

- [ ] **Step 1: Wire the SSE handler**

In the existing SSE stream consumer in `chat-store.svelte.ts`, locate the per-event switch (where `tool_start`, `tool_end`, `done` are handled) and add a `case "approval_required"` arm. Behaviour:

- Validate with `ApprovalRequiredEventSchema.parse(ev)`.
- Set the in-flight assistant message's `metadata_.pending_approval = ev` (use the existing assistant draft message that the store creates while streaming).
- Set a store-level `pendingApproval` flag so the input can be disabled.
- Stop streaming (the backend has already ended the stream).

Also add the resume helpers:

```ts
import { approveChatMessage } from '$lib/api';
import { ApprovalRequiredEventSchema, type ApprovalRequiredEvent } from '$lib/schemas/chat';

let pendingApproval = $state<ApprovalRequiredEvent | null>(null);
export function getPendingApproval() { return pendingApproval; }

export async function approveExternalProtocol(toolCallId: string, approved: boolean) {
  const session = activeSession;
  if (!session) return;
  pendingApproval = null;
  // Drop the metadata_.pending_approval on the placeholder message locally,
  // we'll get the real assistant content back from the resumed stream.
  const placeholder = session.messages.find(
    (m) => m.metadata_?.pending_approval?.tool_call_id === toolCallId,
  );
  if (placeholder && placeholder.metadata_) {
    delete (placeholder.metadata_ as Record<string, unknown>).pending_approval;
  }
  const resp = await approveChatMessage(session.id, { tool_call_id: toolCallId, approved });
  // Reuse the existing SSE consumer with this response.
  await consumeSSEResponse(resp); // existing helper in this file
}
```

(`consumeSSEResponse` is whatever helper your store already uses to iterate `text/event-stream` lines; reuse it.)

Inside the SSE-event switch:

```ts
case 'approval_required': {
  const ev = ApprovalRequiredEventSchema.parse(raw);
  pendingApproval = ev;
  // Find or create the placeholder assistant message and stash the event on it.
  const placeholder = ensureAssistantPlaceholder(session); // existing helper
  placeholder.metadata_ = {
    ...(placeholder.metadata_ ?? {}),
    pending_approval: ev,
  };
  return; // stream is already ended by the server
}
```

(If `ensureAssistantPlaceholder` doesn't exist by that name, follow the same pattern your store already uses to update the in-flight assistant message.)

- [ ] **Step 2: Render ApprovalCard inside ChatPanel.svelte**

In `frontend/src/lib/components/ai/ChatPanel.svelte`, import the card and the resume helper:

```ts
import ApprovalCard from "$lib/components/ai/ApprovalCard.svelte";
import { approveExternalProtocol, getPendingApproval } from "$lib/chat-store.svelte";
```

Inside the message-render loop, after the existing protocol-CTA rendering and before the closing bubble div, add:

```svelte
{#if msg.role === "assistant" && (msg.metadata_ as any)?.pending_approval}
  {@const pa = (msg.metadata_ as any).pending_approval}
  <div class="mt-2.5">
    <ApprovalCard
      toolCallId={pa.tool_call_id}
      toolName={pa.tool_name}
      title={pa.title}
      sourceUrl={pa.source_url}
      payloadPreview={pa.payload_preview}
      onApprove={(id) => approveExternalProtocol(id, true)}
      onReject={(id) => approveExternalProtocol(id, false)}
    />
  </div>
{/if}
```

Disable the chat input while a pending approval is outstanding. Near where the input is currently rendered:

```svelte
{@const pending = getPendingApproval()}
<textarea
  bind:this={inputEl}
  disabled={pending !== null}
  placeholder={pending ? "Approve or reject above first…" : "Reply…"}
  …
/>
```

- [ ] **Step 3: Run the frontend type-checker**

Run: `cd frontend && npm run check`
Expected: PASS.

- [ ] **Step 4: Smoke-test in dev**

Run: `cd backend && BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED=true uvicorn app.main:app --reload` in one terminal, `cd frontend && npm run dev` in another. Open the app, ask the chat: "find me an OpenWetWare protocol for transformation". Verify the candidates list renders, the input is enabled, you can ask "convert it", the ApprovalCard appears, and Approve drafts a protocol. (Production verification happens in the browser-verification step after Task 18.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/chat-store.svelte.ts \
        frontend/src/lib/components/ai/ChatPanel.svelte
git commit -m "feat(frontend): wire ApprovalCard into chat stream + disable input on pending (F-0084)"
```

---

### Task 17: Update `CLAUDE.md` flags table + `.claude/rules/backend-ai.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/rules/backend-ai.md`

- [ ] **Step 1: Add the new feature flag to the table in `CLAUDE.md`**

Add one row to the flags table:

```markdown
| External protocols (OpenWetWare) | `features.external_protocols.enabled` (yaml) or `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED` (env) | — | `false` | `protocol_knowledgebase` chat subagent + HITL approval gate. Backend-only flag — no frontend env var needed. (F-0084) |
```

- [ ] **Step 2: Document HITL pattern in `.claude/rules/backend-ai.md`**

Add a short subsection under "Tool Functions":

```markdown
### Human-in-the-loop tools (`requires_approval`)

Tools wired onto the parent agent can be registered with
`Tool(fn, requires_approval=True)`. When the LLM calls such a tool,
`agent.run()` terminates with `DeferredToolRequests` instead of a string.
`send_message_streaming` detects this, persists a placeholder assistant
`ChatMessage` row with `metadata_.pending_approval`, and emits an
`approval_required` SSE event. The frontend renders an inline approval
card; on click it POSTs to `/sessions/{id}/messages/approve`, which calls
`resume_message_streaming` with `DeferredToolResults`. The tool body
runs only after approval.

Use this for any tool that mutates org state from an external/untrusted
source. Don't reach for it for routine tool calls — natural-language
confirmation is fine when the action is reversible or low-stakes.

First occupant: `services/ai/tools/external_protocols.py`
(F-0084's `create_protocol_from_external_source`).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .claude/rules/backend-ai.md
git commit -m "docs: external_protocols flag + HITL pattern in backend-ai rules (F-0084)"
```

---

### Task 18: Final test sweep + browser verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -x -q`
Expected: all tests pass. Specifically confirm no regressions in `tests/integration/test_chat*.py` or the protocol-creation suite.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm run test -- --run`
Expected: all tests pass.

- [ ] **Step 3: Type-check + lint**

Run: `cd frontend && npm run check`
Run: `cd backend && source .venv/bin/activate && black app tests && isort app tests && mypy app`
Expected: no errors. (Worktree port note: alternate ports per `.claude/rules/conventions.md`.)

- [ ] **Step 4: Browser verification (manual)**

Start dev servers (worktree ports if applicable). With `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED=true` set on the backend:

1. Log in, open chat.
2. Send "find an OpenWetWare protocol for transformation of E. coli". Verify candidate list renders with three (or fewer) titled cards, each with a working openwetware.org link, and the closing "I won't create anything until you give the go-ahead" line. The thinking trail should show `Searching OpenWetWare…` and `Reading external protocol…` events.
3. Send "convert the first one". Verify the ApprovalCard appears inline in the assistant bubble with title, source URL, step count, duration, license. Verify the chat input is disabled with a "Approve or reject above first…" placeholder.
4. Click Approve. Verify a "Approved external protocol conversion" chip appears as the next user message, the thinking trail shows `Thinking…` (protocol_creator dispatch), and the final assistant message contains a clickable link to the new protocol. Open it to confirm the protocol exists, has the candidate's name, and its description cites `openwetware.org/...`.
5. Repeat step 2-3 in a new chat session, click Reject. Verify no protocol is created, the placeholder assistant message updates to "Rejected the external protocol conversion." in the user transcript, and the chat input becomes enabled again.

If any UI/UX issues surface (oversized inputs, overflow, layout shifts when the card appears), dispatch the `qa-verify` agent with the specific symptoms.

- [ ] **Step 5: Hand off to the user for final acceptance test**

Stop driving the keyboard. Post a summary message to the user listing: files changed, tests added, what to try (the same five scenarios from Step 4), and the env var they need set (`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED=true`). Explicitly ask them to walk through the flow themselves and confirm everything works.

Do not proceed to closing the ClickUp task until the user replies with explicit approval (e.g. "looks good", "ship it", "confirmed"). If they report any issue, treat the task as still in-progress — re-open the failing step, fix, re-test, and ask again.

- [ ] **Step 6: Close out (only after user confirmation)**

After explicit user sign-off:
1. Update `.claude/rules/*.md` / `CLAUDE.md` if any conventions changed during implementation that weren't already captured in Task 17.
2. Post a summary comment on ClickUp task `86e1b8ud1` listing files modified and tests added.
3. Set the ClickUp task status to `complete`.
4. Exit the worktree with `ExitWorktree` action `keep` (so the commits stay on the branch for integration).

---

## Self-review checklist (already applied)

- All AC items from the spec map to tasks: subagent (T2-T4), tool labels (T5), `requires_approval` tool (T7), HITL plumbing (T9-T11), prompt updates (T12), feature flag (T1), rate limit (T3), tests (T2, T3, T6, T9, T10, T13, T14, T15), frontend (T14-T16), docs (T17).
- No `TODO` / `TBD` placeholders. All steps have either complete code or a pinned spec command.
- Type/name consistency: `ExternalProtocolPayload`, `ExternalProtocolStep`, `OpenWetWareHit`, `OpenWetWareSearchResult`, `ExternalProtocolPayloadPreview`, `ApprovalRequest`, `ApprovalRequiredEvent`, `APPROVED_SENTINEL`, `create_protocol_from_external_source`, `approveChatMessage`, `approveExternalProtocol` — used consistently across backend, schemas, frontend, and tests.
- The `chat-store.svelte.ts` filename is the most plausible match for the existing import path `$lib/chat-store.svelte`. Confirm with `grep -ln "registerScrollFn" frontend/src/lib/` at execution time; if the actual filename differs, update Task 16 in place.
