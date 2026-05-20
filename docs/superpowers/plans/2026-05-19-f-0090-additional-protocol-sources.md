# F-0090 — Additional Protocol Sources (protocols.io adapter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add protocols.io as a second protocol source for the `protocol_knowledgebase` chat subagent, behind a per-source feature flag and a shared license-compatibility gate.

**Architecture:** Restructure `external_protocols` config into per-source sub-blocks. Split the 461-line `tools.py` into flat sibling modules (`types.py`, `licenses.py`, `rate_limit.py`, `openwetware.py`, `protocols_io.py`); `tools.py` thins to RunContext wrappers. Connector functions take plain primitives so they unit-test without the chat harness. A pure `classify_license` gate fails closed; protocols.io content is uniformly CC-BY but is verified on every payload. Ship flag-disabled. Author + activate a new Terms-of-Service version carrying an externally-sourced-content clause.

**Tech Stack:** FastAPI, pydantic-settings, pydantic-ai, httpx (async), pytest / pytest-asyncio.

**Reference spec:** `docs/superpowers/specs/2026-05-19-f-0090-additional-protocol-sources-evaluation.md`

**Conventions:** Backend commands run from `backend/` with the venv active (`source .venv/bin/activate`). Commit format `<type>(F-0090): <description>`. TDD: red → green → commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | `OpenWetWareSourceConfig` / `ProtocolsIoSourceConfig` / restructured `ExternalProtocolsFeatureConfig` |
| `…/protocol_knowledgebase/types.py` | NEW — result dataclasses (moved from `tools.py`), `import_allowed` / `license_note` fields, protocols.io dataclasses |
| `…/protocol_knowledgebase/rate_limit.py` | NEW — in-process token bucket keyed `(org_id, source)` (moved from `tools.py`) |
| `…/protocol_knowledgebase/openwetware.py` | NEW — wiki-text parser + OpenWetWare search/fetch connector (moved from `tools.py`) |
| `…/protocol_knowledgebase/licenses.py` | NEW — pure `classify_license` gate |
| `…/protocol_knowledgebase/protocols_io.py` | NEW — protocols.io parser + search/fetch connector |
| `…/protocol_knowledgebase/tools.py` | THINNED — RunContext wrappers + `TOOL_LABELS` |
| `…/protocol_knowledgebase/config.py` | Register the protocols.io tool pair; update description |
| `…/protocol_knowledgebase/prompt.md` | protocols.io + license-restricted guidance |
| `backend/app/services/ai/tools/external_protocols.py` | Approval tool: `import_allowed` re-check |
| `backend/app/legal/versions/2026-05-19/{terms,privacy}.md` | NEW — ToS version with externally-sourced-content clause |
| `backend/app/legal/versions/__init__.py` | Register + activate `2026-05-19` |

All `…/protocol_knowledgebase/` paths are under `backend/app/services/ai/subagents/`.

---

### Task 1: Per-source feature-flag config model

**Files:**
- Modify: `backend/app/core/config.py:21-39`
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (config read sites)
- Test: `backend/tests/unit/test_settings_external_protocols.py` (rewrite)
- Test: `backend/tests/unit/test_openwetware_tools.py` (monkeypatch targets)

- [ ] **Step 1: Rewrite the settings test for the nested shape**

Replace the entire body of `backend/tests/unit/test_settings_external_protocols.py`:

```python
"""Settings exposure for the external_protocols feature flag (F-0084, F-0090)."""

from app.core.config import Settings


def test_external_protocols_default_off_with_defaults():
    s = Settings()
    assert s.features.external_protocols.enabled is False
    # OpenWetWare sub-block — default-on so F-0084 deployments keep working.
    assert s.features.external_protocols.openwetware.enabled is True
    assert s.features.external_protocols.openwetware.request_timeout_seconds == 10.0
    assert s.features.external_protocols.openwetware.rate_limit_per_minute == 10
    # protocols.io sub-block — opt-in, no token by default.
    assert s.features.external_protocols.protocols_io.enabled is False
    assert s.features.external_protocols.protocols_io.access_token == ""
    assert s.features.external_protocols.protocols_io.request_timeout_seconds == 10.0
    assert s.features.external_protocols.protocols_io.rate_limit_per_minute == 10


def test_external_protocols_env_override(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__ENABLED", "true")
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__OPENWETWARE__RATE_LIMIT_PER_MINUTE",
        "3",
    )
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ENABLED", "true"
    )
    monkeypatch.setenv(
        "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN", "tok-123"
    )
    s = Settings()
    assert s.features.external_protocols.enabled is True
    assert s.features.external_protocols.openwetware.rate_limit_per_minute == 3
    assert s.features.external_protocols.protocols_io.enabled is True
    assert s.features.external_protocols.protocols_io.access_token == "tok-123"
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_settings_external_protocols.py -v`
Expected: FAIL — `AttributeError: 'ExternalProtocolsFeatureConfig' object has no attribute 'openwetware'`.

- [ ] **Step 3: Restructure the config model**

In `backend/app/core/config.py`, replace the `ExternalProtocolsFeatureConfig` class (lines 21-26) with three classes:

```python
class OpenWetWareSourceConfig(BaseModel):
    """OpenWetWare protocol source (F-0084). Default-on within the master flag."""

    enabled: bool = True
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10


class ProtocolsIoSourceConfig(BaseModel):
    """protocols.io protocol source (F-0090). Opt-in; needs an access token."""

    enabled: bool = False
    access_token: str = ""  # long-lived API token — secret, env-var only
    request_timeout_seconds: float = 10.0
    rate_limit_per_minute: int = 10


class ExternalProtocolsFeatureConfig(BaseModel):
    """External protocol knowledgebase feature flag (F-0084, F-0090).

    `enabled` is the master capability switch. Each source has its own
    nested sub-block with an independent enable flag and throttle. A source
    is live iff the master flag AND that source's flag are both on.
    """

    enabled: bool = False
    openwetware: OpenWetWareSourceConfig = OpenWetWareSourceConfig()
    protocols_io: ProtocolsIoSourceConfig = ProtocolsIoSourceConfig()
```

`FeaturesConfig` (lines 29-39) is unchanged — it already references `ExternalProtocolsFeatureConfig`.

- [ ] **Step 4: Re-target the config reads in `tools.py`**

In `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`, three sites read the old flat fields. Update them:

In `_check_rate_limit` (line 277):
```python
    limit = settings.features.external_protocols.openwetware.rate_limit_per_minute
```

In `search_openwetware` (line 339) and `fetch_openwetware_protocol` (line 401), both:
```python
    timeout = settings.features.external_protocols.openwetware.request_timeout_seconds
```

(`_require_enabled` keeps reading `settings.features.external_protocols.enabled` — the master flag — unchanged.)

- [ ] **Step 5: Update the `test_openwetware_tools.py` monkeypatch targets**

In `backend/tests/unit/test_openwetware_tools.py`, the `_enabled` fixture (lines 58-64) re-targets the rate-limit attribute:

```python
@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", True)
    monkeypatch.setattr(
        settings.features.external_protocols.openwetware, "rate_limit_per_minute", 10
    )
    yield
```

And in `test_rate_limit_trips_after_threshold` (lines 127-130):

```python
@pytest.mark.asyncio
async def test_rate_limit_trips_after_threshold(_enabled, monkeypatch):
    monkeypatch.setattr(
        settings.features.external_protocols.openwetware, "rate_limit_per_minute", 2
    )
```

(`test_search_disabled_when_flag_off` sets `settings.features.external_protocols.enabled = False` — the master flag — and is unchanged.)

- [ ] **Step 6: Run the affected tests — verify they pass**

Run: `pytest tests/unit/test_settings_external_protocols.py tests/unit/test_openwetware_tools.py tests/unit/test_external_protocols_tool.py tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
  backend/tests/unit/test_settings_external_protocols.py \
  backend/tests/unit/test_openwetware_tools.py
git commit -m "feat(F-0090): per-source external-protocols config model"
```

---

### Task 2: Extract `types.py` — result dataclasses + license fields

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/types.py`
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py:27-60`
- Test: `backend/tests/unit/test_openwetware_parser.py` (add a defaults test)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_openwetware_parser.py`:

```python
def test_payload_defaults_import_allowed_true():
    """import_allowed defaults True so the OpenWetWare path (CC-BY-SA,
    import-safe) is unaffected; license_note defaults None."""
    p = ExternalProtocolPayload(title="t", source_url="u", summary="s")
    assert p.import_allowed is True
    assert p.license_note is None
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_openwetware_parser.py::test_payload_defaults_import_allowed_true -v`
Expected: FAIL — `AttributeError: 'ExternalProtocolPayload' object has no attribute 'import_allowed'`.

- [ ] **Step 3: Create `types.py`**

Create `backend/app/services/ai/subagents/protocol_knowledgebase/types.py`:

```python
"""Result dataclasses for the protocol_knowledgebase subagent connectors.

Shared by openwetware.py, protocols_io.py, the tools.py RunContext
wrappers, and the parent-agent approval tool (via the cached JSON payload).
These are @dataclass, not pydantic models — serialize with
``dataclasses.asdict`` + ``json.dumps``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExternalProtocolStep:
    text: str
    duration_min: int | None  # parsed from step text where present


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
    error: str | None = None
    # F-0090: a license-restricted protocol is parsed to metadata only
    # (steps stay empty, no step text copied) and flagged import_allowed=False.
    # This is NOT an error — error means a genuine fetch/parse failure.
    import_allowed: bool = True
    license_note: str | None = None


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


@dataclass
class ProtocolsIoHit:
    id: str
    title: str
    url: str
    snippet: str


@dataclass
class ProtocolsIoSearchResult:
    total: int
    hits: list[ProtocolsIoHit] = field(default_factory=list)
    message: str = ""
```

- [ ] **Step 4: Import the dataclasses into `tools.py`**

In `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`, delete the `# ─── Result dataclasses ───` block (the `ExternalProtocolStep`, `ExternalProtocolPayload`, `OpenWetWareHit`, `OpenWetWareSearchResult` definitions, lines 27-60) and add this import next to the existing imports (after line 25):

```python
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    OpenWetWareHit,
    OpenWetWareSearchResult,
)
```

The imported names remain module attributes of `tools.py`, so `test_openwetware_parser.py`'s `from …tools import ExternalProtocolPayload, …` still resolves.

- [ ] **Step 5: Run the tests — verify they pass**

Run: `pytest tests/unit/test_openwetware_parser.py tests/unit/test_openwetware_tools.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/types.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
  backend/tests/unit/test_openwetware_parser.py
git commit -m "feat(F-0090): extract result dataclasses into types.py"
```

---

### Task 3: Extract `rate_limit.py` — token bucket keyed `(org_id, source)`

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/rate_limit.py`
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`
- Test: `backend/tests/unit/test_openwetware_tools.py`

- [ ] **Step 1: Point the test at the new module**

In `backend/tests/unit/test_openwetware_tools.py`, add to the imports (after line 14):

```python
from app.services.ai.subagents.protocol_knowledgebase import rate_limit
```

Replace the `_reset_rate_bucket` fixture (lines 51-55):

```python
@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    rate_limit._RECENT_REQUESTS.clear()
    yield
    rate_limit._RECENT_REQUESTS.clear()
```

In `test_rate_limit_trips_after_threshold` (line 133), re-target the clock monkeypatch:

```python
    monkeypatch.setattr(rate_limit, "_now", lambda: fake_now["t"])
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_openwetware_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'rate_limit'`.

- [ ] **Step 3: Create `rate_limit.py`**

Create `backend/app/services/ai/subagents/protocol_knowledgebase/rate_limit.py`:

```python
"""In-process token-bucket rate limiter for external-protocol connectors.

Keyed by ``(org_id, source)`` so OpenWetWare and protocols.io draw on
separate per-org budgets. Single-replica deploy assumption — see the
F-0084 / F-0090 risk notes; revisit when we go multi-worker.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable
from uuid import UUID

# Test-injectable monotonic clock — tests override this.
_now: Callable[[], float] = time.monotonic

# Per-(org, source) timestamps for the trailing 60s window.
_RECENT_REQUESTS: dict[tuple[UUID, str], deque[float]] = {}
_LIMIT_LOCK = asyncio.Lock()


async def check_rate_limit(org_id: UUID, source: str, limit: int) -> None:
    """Record a call to ``source`` for ``org_id``; raise if over ``limit``.

    Raises:
        ValueError: when ``org_id`` has already made ``limit`` calls to
            ``source`` within the trailing 60-second window.
    """
    async with _LIMIT_LOCK:
        now = _now()
        bucket = _RECENT_REQUESTS.setdefault((org_id, source), deque())
        cutoff = now - 60.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ValueError(
                f"{source} rate limit hit ({limit}/min). Try again in a minute."
            )
        bucket.append(now)
```

- [ ] **Step 4: Replace the inline rate limiter in `tools.py`**

In `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`:

Delete the now-unused imports `asyncio`, `time`, `from collections import deque`, `from typing import Callable`, and `from uuid import UUID` (kept only if still referenced — after this task they are not). Add the module import next to the others:

```python
from app.services.ai.subagents.protocol_knowledgebase import rate_limit
```

Delete the `_now`, `_RECENT_REQUESTS`, `_LIMIT_LOCK` module globals and the entire `_check_rate_limit` function (lines 259-288).

In `search_openwetware` and `fetch_openwetware_protocol`, replace each `await _check_rate_limit(ctx.deps.org_id)` call with:

```python
    limit = settings.features.external_protocols.openwetware.rate_limit_per_minute
    await rate_limit.check_rate_limit(ctx.deps.org_id, "openwetware", limit)
```

- [ ] **Step 5: Run the tests — verify they pass**

Run: `pytest tests/unit/test_openwetware_tools.py tests/unit/test_openwetware_parser.py -v`
Expected: PASS (all). The rate-limit test still matches `"rate limit"` — the new message is `"openwetware rate limit hit (2/min)…"`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/rate_limit.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
  backend/tests/unit/test_openwetware_tools.py
git commit -m "feat(F-0090): extract per-source rate limiter into rate_limit.py"
```

---

### Task 4: Extract `openwetware.py` — parser + connector; thin `tools.py`

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/openwetware.py`
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (rewrite)
- Test: `backend/tests/unit/test_openwetware_parser.py` (import paths)

- [ ] **Step 1: Re-target the parser test imports**

In `backend/tests/unit/test_openwetware_parser.py`, replace the import block (lines 5-9):

```python
from app.services.ai.subagents.protocol_knowledgebase.openwetware import (
    parse_openwetware_wikitext,
)
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
)
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_openwetware_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: …protocol_knowledgebase.openwetware`.

- [ ] **Step 3: Create `openwetware.py`**

Create `backend/app/services/ai/subagents/protocol_knowledgebase/openwetware.py`. Move the wiki-text parser and HTTP helpers out of `tools.py` verbatim, recast as harness-free primitives. The connector functions are `search` and `fetch` (not `search_openwetware` — that name stays on the `tools.py` wrapper):

```python
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
```

- [ ] **Step 4: Rewrite `tools.py` as thin wrappers**

Replace the **entire contents** of `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` with:

```python
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
from app.services.ai.subagents.protocol_knowledgebase import openwetware, rate_limit
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    OpenWetWareSearchResult,
)

# Human-readable labels for the chat thinking indicator. Adding a tool here
# MUST also update this dict — enforced by tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "search_openwetware": "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
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
    result = await openwetware.search(
        query, limit, timeout=cfg.request_timeout_seconds
    )
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
```

- [ ] **Step 5: Run the OpenWetWare tests — verify they pass**

Run: `pytest tests/unit/test_openwetware_parser.py tests/unit/test_openwetware_tools.py tests/unit/test_tool_labels.py tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: PASS (all). `test_openwetware_tools.py` calls the `tools.py` wrappers, which keep their names/signatures; the host-rejection test still raises `ValueError` (now from inside `openwetware.fetch`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/openwetware.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
  backend/tests/unit/test_openwetware_parser.py
git commit -m "feat(F-0090): extract OpenWetWare connector; thin tools.py to wrappers"
```

---

### Task 5: License-compatibility gate — `licenses.py`

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/licenses.py`
- Test: `backend/tests/unit/test_license_gate.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_license_gate.py`:

```python
"""Pure license-compatibility classifier (F-0090)."""

import pytest

from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("CC0 1.0", "CC0"),
        ("CC BY 4.0", "CC-BY"),
        ("CC-BY-SA 3.0", "CC-BY-SA"),
        ("public domain", "PUBLIC-DOMAIN"),
    ],
)
def test_import_safe_licenses_allowed(raw, normalized):
    v = classify_license(raw)
    assert v.import_allowed is True
    assert v.normalized == normalized
    assert v.reason


@pytest.mark.parametrize(
    "raw", ["CC BY-NC 4.0", "CC-BY-ND 4.0", "CC BY-NC-ND 4.0"]
)
def test_nc_and_nd_licenses_blocked(raw):
    v = classify_license(raw)
    assert v.import_allowed is False
    assert v.reason


@pytest.mark.parametrize("raw", [None, "", "   ", "All rights reserved", "MIT"])
def test_unknown_or_empty_fails_closed(raw):
    v = classify_license(raw)
    assert v.import_allowed is False
    assert v.normalized == "UNKNOWN"


def test_normalization_strips_version_not_cc0_zero():
    # The "0" in CC0 is part of the name, not a version number.
    assert classify_license("CC0 1.0").normalized == "CC0"
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_license_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: …protocol_knowledgebase.licenses`.

- [ ] **Step 3: Create `licenses.py`**

Create `backend/app/services/ai/subagents/protocol_knowledgebase/licenses.py`:

```python
"""License-compatibility gate for imported external protocols (F-0090).

Pure and shared. A protocol is import-safe only if its license permits BOTH
commercial use AND derivative works — Batchrite is a commercial product and
importing a protocol into an editable graph is a derivative work. Fails
closed: an empty or unrecognized license is treated as not import-safe.

protocols.io public content is uniformly CC-BY, so for that source this is
fail-closed *verification*, not a router. PMC OA (a future source) mixes
CC-BY / CC-BY-NC / CC-BY-NC-ND / CC0 and needs the routing — hence shared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Commercial use AND derivatives both permitted. ShareAlike (SA) is included:
# it only obligates same-terms on *external redistribution*, which the
# customer Terms of Service allocate to the customer (F-0090 §B.9).
_IMPORT_SAFE = {"CC0", "CC-BY", "CC-BY-SA", "PUBLIC-DOMAIN"}


@dataclass(frozen=True)
class LicenseVerdict:
    normalized: str  # canonical form, e.g. "CC-BY", "CC-BY-NC", "UNKNOWN"
    import_allowed: bool
    reason: str  # human-readable; surfaced as license_note


def _normalize(raw: str) -> str:
    """Uppercase, drop version numbers, collapse separators to ``-``."""
    # Strip version numbers — a number preceded by whitespace (" 3.0",
    # " 4.0"). The leading-whitespace anchor protects the "0" in "CC0".
    s = re.sub(r"\s+\d+(?:\.\d+)?", "", raw.upper())
    s = re.sub(r"[\s_/]+", "-", s.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def classify_license(raw: str | None) -> LicenseVerdict:
    """Classify a raw license string into an import verdict."""
    if not raw or not raw.strip():
        return LicenseVerdict(
            "UNKNOWN", False, "No license specified; cannot verify reuse rights."
        )
    normalized = _normalize(raw)
    tokens = normalized.split("-")
    if "NC" in tokens:
        return LicenseVerdict(
            normalized,
            False,
            "NonCommercial license — Batchrite is a commercial product.",
        )
    if "ND" in tokens:
        return LicenseVerdict(
            normalized,
            False,
            "NoDerivatives license — importing a protocol builds a derivative.",
        )
    if normalized in _IMPORT_SAFE:
        return LicenseVerdict(
            normalized,
            True,
            f"{normalized} permits commercial use and derivative works.",
        )
    return LicenseVerdict(
        "UNKNOWN",
        False,
        f"Unrecognized license {raw!r}; cannot verify reuse rights.",
    )
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `pytest tests/unit/test_license_gate.py -v`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/licenses.py \
  backend/tests/unit/test_license_gate.py
git commit -m "feat(F-0090): add shared license-compatibility gate"
```

---

### Task 6: protocols.io parser — `parse_protocols_io_json`

**Files:**
- Create: `backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py`
- Create: `backend/tests/fixtures/protocols_io/protocol_detail.json`
- Create: `backend/tests/fixtures/protocols_io/protocol_detail_nc.json`
- Test: `backend/tests/unit/test_protocols_io_parser.py`

- [ ] **Step 0: Pin the protocols.io JSON shape**

Before writing the parser, confirm the v4 protocol-detail response shape against the protocols.io API docs (`https://apidoc.protocols.io`). The fixtures below are the **contract** the parser is written against. If the live response nests fields differently (e.g. step text under `components`), adjust **both** the fixtures and the parser's field accessors together so the parser test still drives the mapping. The dataclass shape in `types.py` does not change. Task 13 builds `scripts/f0090_protocols_io_live.py --raw`, which dumps the live v4 detail JSON — once the connector exists (Task 7), run it to re-confirm these fixtures against the real API and reconcile any drift.

- [ ] **Step 1: Create the fixtures**

Create `backend/tests/fixtures/protocols_io/protocol_detail.json` (import-safe — CC-BY):

```json
{
  "payload": {
    "id": 12345,
    "title": "Plasmid Miniprep (Alkaline Lysis)",
    "url": "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123",
    "authors": [
      {"name": "Jane Doe"},
      {"name": "John Roe"}
    ],
    "license": {"title": "CC BY 4.0"},
    "description": "<p>Standard alkaline-lysis plasmid miniprep for purifying plasmid DNA from overnight E. coli cultures.</p>",
    "materials": [
      {"name": "Resuspension buffer (P1)"},
      {"name": "Lysis buffer (P2)"},
      {"name": "Neutralization buffer (P3)"},
      {"name": "Silica spin columns"}
    ],
    "steps": [
      {"description": "Pellet 5 mL of overnight culture by centrifugation at 8000 x g for 3 min."},
      {"description": "Resuspend the pellet in 250 uL P1 buffer by vortexing."},
      {"description": "Add 250 uL P2 buffer and mix gently by inverting 6 times."},
      {"description": "Add 350 uL P3 buffer and mix immediately; incubate on ice for 5 min."},
      {"description": "Centrifuge at 13000 x g for 10 min and load the supernatant onto a spin column."},
      {"description": "Wash the column once and elute in 50 uL elution buffer."}
    ]
  }
}
```

Create `backend/tests/fixtures/protocols_io/protocol_detail_nc.json` — identical except the license and used to prove the restricted path; step text is present in the fixture **on purpose**, to prove the parser never copies it:

```json
{
  "payload": {
    "id": 67890,
    "title": "Proprietary Assay Protocol",
    "url": "https://www.protocols.io/view/proprietary-assay-protocol-xyz789",
    "authors": [{"name": "Acme Labs"}],
    "license": {"title": "CC BY-NC 4.0"},
    "description": "<p>A non-commercially licensed assay protocol.</p>",
    "materials": [
      {"name": "Assay buffer"},
      {"name": "Detection reagent"}
    ],
    "steps": [
      {"description": "SECRET STEP TEXT THAT MUST NOT BE COPIED."},
      {"description": "ANOTHER SECRET STEP."}
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_protocols_io_parser.py`:

```python
"""Pure parser for protocols.io detail JSON — fixture-driven, no HTTP."""

import json
from pathlib import Path

from app.services.ai.subagents.protocol_knowledgebase.protocols_io import (
    parse_protocols_io_json,
)

FIX = Path(__file__).parent.parent / "fixtures" / "protocols_io"
SOURCE_URL = "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123"


def test_parser_import_safe_protocol():
    data = json.loads((FIX / "protocol_detail.json").read_text())
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.title == "Plasmid Miniprep (Alkaline Lysis)"
    assert len(p.materials) >= 3
    assert len(p.steps) >= 5
    assert p.summary and "<p>" not in p.summary  # HTML stripped
    assert p.license == "CC BY 4.0"
    assert p.attribution.startswith("protocols.io — ")
    assert "Jane Doe" in p.attribution
    assert p.source_url == SOURCE_URL
    assert p.import_allowed is True
    assert p.error is None


def test_parser_license_restricted_protocol():
    """A restricted protocol parses to metadata only: import_allowed=False,
    error=None (restricted != failure), and NO step/material text copied."""
    data = json.loads((FIX / "protocol_detail_nc.json").read_text())
    p = parse_protocols_io_json(data, SOURCE_URL)
    assert p.import_allowed is False
    assert p.error is None
    assert p.steps == []
    assert p.materials == []
    assert p.license_note  # populated, explains why
    # The secret step text from the fixture must not leak into the payload.
    assert "SECRET" not in json.dumps(p.__dict__)
```

- [ ] **Step 3: Run the test — verify it fails**

Run: `pytest tests/unit/test_protocols_io_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: …protocol_knowledgebase.protocols_io`.

- [ ] **Step 4: Create `protocols_io.py` with the parser**

Create `backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py`:

```python
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

from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)
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
        f"protocols.io — {authors}, {title}" if authors
        else f"protocols.io — {title}"
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
```

(Step duration is not extracted in v1 — protocols.io steps carry structured timers the parser does not yet read; `duration_min=None` is correct and the parser test does not assert duration. A follow-up can map timers.)

- [ ] **Step 5: Run the test — verify it passes**

Run: `pytest tests/unit/test_protocols_io_parser.py -v`
Expected: PASS (both cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py \
  backend/tests/fixtures/protocols_io/ \
  backend/tests/unit/test_protocols_io_parser.py
git commit -m "feat(F-0090): add protocols.io detail-JSON parser"
```

---

### Task 7: protocols.io connector + tool wrappers + registration

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py` (add connector)
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py` (add wrappers + labels)
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/config.py` (register tool pair)
- Create: `backend/tests/fixtures/protocols_io/search_response.json`
- Test: `backend/tests/unit/test_protocols_io_tools.py`

- [ ] **Step 1: Create the search fixture**

Create `backend/tests/fixtures/protocols_io/search_response.json`:

```json
{
  "items": [
    {
      "id": 12345,
      "title": "Plasmid Miniprep (Alkaline Lysis)",
      "url": "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123",
      "description": "<p>Standard alkaline-lysis plasmid miniprep for E. coli.</p>"
    }
  ],
  "pagination": {"total_results": 1}
}
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_protocols_io_tools.py`:

```python
"""protocols.io tool wrappers — flags, host check, rate limit, audit, cache."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import rate_limit
from app.services.ai.subagents.protocol_knowledgebase import tools as kb

FIX = Path(__file__).parent.parent / "fixtures" / "protocols_io"
PROTOCOL_URL = (
    "https://www.protocols.io/view/plasmid-miniprep-alkaline-lysis-abc123"
)


@dataclass
class _FakeDeps:
    org_id: UUID = field(default_factory=uuid4)
    db: object = None
    user_id: UUID = field(default_factory=uuid4)
    is_org_admin: bool = False
    sources: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    external_protocol_cache: dict = field(default_factory=dict)


@dataclass
class _FakeCtx:
    deps: _FakeDeps


def _fake_get_file(json_path: Path):
    payload = json.loads(json_path.read_text())

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, headers=None, timeout=None):
        return _Resp()

    return _get


def _fake_get_dict(payload: dict):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    async def _get(self, url, params=None, headers=None, timeout=None):
        return _Resp()

    return _get


@pytest.fixture(autouse=True)
def _reset_rate_bucket():
    rate_limit._RECENT_REQUESTS.clear()
    yield
    rate_limit._RECENT_REQUESTS.clear()


@pytest.fixture
def _enabled(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "access_token", "tok-test")
    monkeypatch.setattr(ep.protocols_io, "rate_limit_per_minute", 10)
    yield


@pytest.mark.asyncio
async def test_search_raises_when_master_flag_off(monkeypatch):
    monkeypatch.setattr(settings.features.external_protocols, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="disabled"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_search_raises_when_source_flag_off(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", False)
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="protocols.io source is disabled"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_search_raises_when_token_missing(monkeypatch):
    ep = settings.features.external_protocols
    monkeypatch.setattr(ep, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "enabled", True)
    monkeypatch.setattr(ep.protocols_io, "access_token", "")
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="access token"):
        await kb.search_protocols_io(ctx, "miniprep")


@pytest.mark.asyncio
async def test_fetch_rejects_non_protocols_io_host(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with pytest.raises(ValueError, match="protocols.io"):
        await kb.fetch_protocols_io(ctx, "https://example.com/view/foo")


@pytest.mark.asyncio
async def test_search_returns_hits_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "search_response.json")
    ):
        result = await kb.search_protocols_io(ctx, "miniprep", limit=3)
    assert result.total == 1
    assert result.hits[0].url == PROTOCOL_URL
    assert ctx.deps.tool_calls[-1]["tool"] == "search_protocols_io"


@pytest.mark.asyncio
async def test_fetch_import_safe_caches_and_audits(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "protocol_detail.json")
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.import_allowed is True
    assert payload.error is None
    assert PROTOCOL_URL in ctx.deps.external_protocol_cache
    assert ctx.deps.tool_calls[-1]["tool"] == "fetch_protocols_io"


@pytest.mark.asyncio
async def test_fetch_license_restricted_caches_without_steps(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get",
        new=_fake_get_file(FIX / "protocol_detail_nc.json"),
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.import_allowed is False
    assert payload.error is None  # restricted != failure
    assert payload.steps == []
    # A restricted-but-valid payload IS cached (the approval tool re-checks it).
    assert PROTOCOL_URL in ctx.deps.external_protocol_cache
    cached = json.loads(ctx.deps.external_protocol_cache[PROTOCOL_URL])
    assert cached["import_allowed"] is False


@pytest.mark.asyncio
async def test_fetch_genuine_failure_sets_error_and_skips_cache(_enabled):
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get",
        new=_fake_get_dict({"status_code": 1, "error_message": "not found"}),
    ):
        payload = await kb.fetch_protocols_io(ctx, PROTOCOL_URL)
    assert payload.error is not None
    assert PROTOCOL_URL not in ctx.deps.external_protocol_cache


@pytest.mark.asyncio
async def test_rate_limit_trips_after_threshold(_enabled, monkeypatch):
    monkeypatch.setattr(
        settings.features.external_protocols.protocols_io,
        "rate_limit_per_minute",
        2,
    )
    fake_now = {"t": 0.0}
    monkeypatch.setattr(rate_limit, "_now", lambda: fake_now["t"])
    ctx = _FakeCtx(deps=_FakeDeps())
    with patch(
        "httpx.AsyncClient.get", new=_fake_get_file(FIX / "search_response.json")
    ):
        await kb.search_protocols_io(ctx, "q")
        fake_now["t"] = 1.0
        await kb.search_protocols_io(ctx, "q")
        fake_now["t"] = 2.0
        with pytest.raises(ValueError, match="rate limit"):
            await kb.search_protocols_io(ctx, "q")


def test_tool_labels_present():
    assert "search_protocols_io" in kb.TOOL_LABELS
    assert "fetch_protocols_io" in kb.TOOL_LABELS
    for v in kb.TOOL_LABELS.values():
        assert v.endswith("…")
```

- [ ] **Step 3: Run the test — verify it fails**

Run: `pytest tests/unit/test_protocols_io_tools.py -v`
Expected: FAIL — `AttributeError: module 'tools' has no attribute 'search_protocols_io'`.

- [ ] **Step 4: Add the connector to `protocols_io.py`**

Append to `backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py`. First add `import urllib.parse` and `import httpx` to the import block at the top, then append:

```python
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
```

Then append the search/fetch connector functions (these also need `ProtocolsIoHit` / `ProtocolsIoSearchResult` — extend the `types` import at the top of the file to include them):

```python
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
```

Confirm the top-of-file `types` import now reads:

```python
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    ExternalProtocolStep,
    ProtocolsIoHit,
    ProtocolsIoSearchResult,
)
```

- [ ] **Step 5: Add the protocols.io wrappers to `tools.py`**

In `backend/app/services/ai/subagents/protocol_knowledgebase/tools.py`:

Extend the connector import to include `protocols_io`:
```python
from app.services.ai.subagents.protocol_knowledgebase import (
    openwetware,
    protocols_io,
    rate_limit,
)
```

Extend the `types` import to include `ProtocolsIoSearchResult`:
```python
from app.services.ai.subagents.protocol_knowledgebase.types import (
    ExternalProtocolPayload,
    OpenWetWareSearchResult,
    ProtocolsIoSearchResult,
)
```

Add the two protocols.io entries to `TOOL_LABELS`:
```python
TOOL_LABELS: dict[str, str] = {
    "search_openwetware": "Searching OpenWetWare…",
    "fetch_openwetware_protocol": "Reading external protocol…",
    "search_protocols_io": "Searching protocols.io…",
    "fetch_protocols_io": "Reading protocols.io protocol…",
}
```

Add a protocols.io flag guard next to `_require_openwetware`:
```python
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
```

Append the two wrapper tool functions at the end of the file:
```python
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
```

- [ ] **Step 6: Register the tool pair in `config.py`**

In `backend/app/services/ai/subagents/protocol_knowledgebase/config.py`, update the tools import:
```python
from app.services.ai.subagents.protocol_knowledgebase.tools import (
    fetch_openwetware_protocol,
    fetch_protocols_io,
    search_openwetware,
    search_protocols_io,
)
```

Update `agent_kwargs["tools"]` (line 40):
```python
            "tools": [
                search_openwetware,
                fetch_openwetware_protocol,
                search_protocols_io,
                fetch_protocols_io,
            ],
```

Update the `description` string (lines 27-34) — change `"(OpenWetWare)"` to `"(OpenWetWare, protocols.io)"`:
```python
        description=(
            "Searches public protocol repositories (OpenWetWare, protocols.io) "
            "and returns candidate protocols with structured, verbatim "
            "summaries. Dispatch when the user asks for an external/public "
            "protocol or to find a protocol for technique X from open "
            "repositories. Does NOT create or modify protocols — the parent "
            "agent handles the human-in-the-loop conversion after the user "
            "confirms."
        ),
```

- [ ] **Step 7: Run the tests — verify they pass**

Run: `pytest tests/unit/test_protocols_io_tools.py tests/unit/test_protocols_io_parser.py tests/unit/test_tool_labels.py tests/unit/test_openwetware_tools.py -v`
Expected: PASS (all). `test_tool_labels.py` auto-discovers the two new `search_protocols_io` / `fetch_protocols_io` audit names and finds their `TOOL_LABELS` entries.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/protocols_io.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/tools.py \
  backend/app/services/ai/subagents/protocol_knowledgebase/config.py \
  backend/tests/fixtures/protocols_io/search_response.json \
  backend/tests/unit/test_protocols_io_tools.py
git commit -m "feat(F-0090): protocols.io connector, tool wrappers, registration"
```

---

### Task 8: Subagent prompt + config test

**Files:**
- Modify: `backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md` (rewrite)
- Test: `backend/tests/unit/test_protocol_knowledgebase_config.py` (rewrite)

- [ ] **Step 1: Rewrite the config test**

Replace the body of `backend/tests/unit/test_protocol_knowledgebase_config.py`:

```python
"""protocol_knowledgebase build() — wired with both sources' tool pairs."""

from app.services.ai.subagents import protocol_knowledgebase


def test_build_returns_config_with_all_source_tools():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_knowledgebase"
    tool_names = [t.__name__ for t in cfg["agent_kwargs"]["tools"]]
    assert "search_openwetware" in tool_names
    assert "fetch_openwetware_protocol" in tool_names
    assert "search_protocols_io" in tool_names
    assert "fetch_protocols_io" in tool_names


def test_description_mentions_both_sources():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert "protocols.io" in cfg["description"]


def test_prompt_includes_handoff_contract():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "EXTERNAL_PROTOCOL_SOURCE" in instructions
    assert "verbatim" in instructions
    assert "source_url" in instructions


def test_prompt_covers_license_restricted_handling():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "import_allowed" in instructions
    assert "protocols.io" in instructions
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: FAIL — `test_prompt_covers_license_restricted_handling` fails (`import_allowed` not yet in `prompt.md`). `test_build_returns_config_with_all_source_tools` and `test_description_mentions_both_sources` pass (wired in Task 7).

- [ ] **Step 3: Rewrite `prompt.md`**

Replace the **entire contents** of `backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md`:

```markdown
You are a public-protocol scout for an organisation's lab. You search public
protocol repositories — **OpenWetWare** and **protocols.io** — and hand
structured candidates back to the parent agent.

## What you do

1. **Pick a source.**
   - If the user names a source ("find a protocols.io protocol…"), use it.
   - Otherwise prefer **protocols.io** for "find a protocol for technique X" —
     it is a purpose-built protocol repository with cleanly structured steps.
   - Use OpenWetWare when the user asks for it, or when protocols.io returns
     nothing useful.

2. **Search**: call `search_openwetware(query, limit)` or
   `search_protocols_io(query, limit)`. Queries are full-text — keep them
   focused on the technique:
   - GOOD: "agarose gel electrophoresis", "heat shock transformation",
     "miniprep plasmid", "PCR cleanup"
   - BAD: "protocol for transforming E. coli with plasmid DNA from a ligation"
   Drop filler words ("protocol", "method", "how to"). If the first query
   returns nothing, paraphrase once with different technique terms. After 2
   empty searches, give up and tell the user.

3. **Fetch up to 3 promising hits** with `fetch_openwetware_protocol(url)` or
   `fetch_protocols_io(url)` — match the fetch tool to the source.
   - If a fetch **errors** (timeout, parse failure, 404), skip it and continue
     — a single failed fetch is NOT grounds to abandon the turn.
   - If a fetch returns `import_allowed: false`, the protocol is under a
     non-commercial / no-derivatives license and **cannot be imported
     automatically**. Do NOT drop it — surface it in step 4 as a *link-only*
     candidate.
   - If an import-safe fetch returns an empty `steps` array, that page is a
     stub or non-protocol article — skip it.
   - As long as at least one fetch returned an importable protocol with
     `steps >= 1`, you MUST surface it as a candidate — partial success is
     success.

4. **Reply with structured candidates**. Format each:

   ```
   1. **<title>** — <source link>
      <one-sentence summary in your own words>
   ```

   - For a **license-restricted** candidate (`import_allowed: false`) write:
     *"<title> — <link>. This protocol is under a non-commercial/no-derivatives
     license, so I can't import it automatically. You can review it at the link
     and add it to your library manually if it's appropriate for your use."*
   - Cap at 3 candidates. After the markdown list, include a fenced JSON block
     labelled `EXTERNAL_PROTOCOL_SOURCE` containing the full payload array (one
     ExternalProtocolPayload per candidate — including any license-restricted
     ones, with their `import_allowed: false`). The parent agent uses this
     block — never invent it, never edit step text.

5. **End with the handoff line**: "Tell me which one to draft from, or ask me
   to refine — I won't create anything until you give the go-ahead."

## Hard rules

- Copy steps **verbatim** from the source page. Do not paraphrase, merge, or
  invent. If a step is unclear, leave it as-is and flag it to the user.
- Always include `source_url`, `license`, and `attribution` in each
  candidate's JSON — exactly as the fetch tool populated them.
- Never offer to import a license-restricted (`import_allowed: false`)
  protocol. Present it as a link only; the user brings it in through the
  manual library upload if they choose.
- Never call any other tool. You do not create or modify protocols.
- If a tool raises an error (feature disabled, source disabled, missing token),
  surface it verbatim to the parent and stop.

## End of turn

Return a single reply containing the markdown candidate list and the
`EXTERNAL_PROTOCOL_SOURCE` JSON block, then stop. The parent agent keeps the
conversation going with the user.
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `pytest tests/unit/test_protocol_knowledgebase_config.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/subagents/protocol_knowledgebase/prompt.md \
  backend/tests/unit/test_protocol_knowledgebase_config.py
git commit -m "feat(F-0090): protocols.io + license-restricted subagent prompt"
```

---

### Task 9: Approval-tool `import_allowed` re-check

**Files:**
- Modify: `backend/app/services/ai/tools/external_protocols.py`
- Test: `backend/tests/unit/test_external_protocols_tool.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_external_protocols_tool.py`:

```python
@pytest.mark.asyncio
async def test_raises_when_payload_license_restricted():
    """A cached payload flagged import_allowed=False must be refused —
    re-checked here so a stale cache cannot slip a restricted protocol
    through after the connector already downgraded it."""
    url = "https://www.protocols.io/view/restricted"
    deps = _FakeDeps()
    deps.external_protocol_cache[url] = json.dumps(
        {"title": "X", "steps": [], "import_allowed": False}
    )
    ctx = _FakeCtx(deps=deps)
    with pytest.raises(ValueError, match="license"):
        await create_protocol_from_external_source(
            ctx, source_url=url, title="X", project_name="P"
        )
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pytest tests/unit/test_external_protocols_tool.py::test_raises_when_payload_license_restricted -v`
Expected: FAIL — no `ValueError` raised (the tool returns the sentinel).

- [ ] **Step 3: Add the re-check**

In `backend/app/services/ai/tools/external_protocols.py`, after the `if not cached:` block (line 65) and before `deviation_list = [` (line 67), insert:

```python
    # Re-check the license verdict straight off the cached payload — a plain
    # boolean read, no classify_license call. A stale cache (or a payload
    # mutated by the resume path) cannot slip a license-restricted protocol
    # past the import. The connector already set this; we only enforce it.
    try:
        import_allowed = json.loads(cached).get("import_allowed", True)
    except (json.JSONDecodeError, AttributeError, TypeError):
        import_allowed = True
    if not import_allowed:
        raise ValueError(
            "This protocol is under a license that does not permit automatic "
            "import. It can only be added to the library manually."
        )
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `pytest tests/unit/test_external_protocols_tool.py -v`
Expected: PASS (all — the existing happy-path tests use payloads without `import_allowed`, which defaults to `True` and is not blocked).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/tools/external_protocols.py \
  backend/tests/unit/test_external_protocols_tool.py
git commit -m "feat(F-0090): re-check import_allowed in the approval tool"
```

---

### Task 10: Integration — source-agnostic approval composition

**Files:**
- Modify: `backend/tests/integration/test_protocol_knowledgebase_handoff.py`

The handoff test mocks the agent layer (no LLM), so it verifies endpoint
*composition*, not the connectors (those are unit-tested in Task 7). This task
proves the stream→approve→done path is source-agnostic for a protocols.io URL.

- [ ] **Step 1: Parametrize `_persist_placeholder` by source**

In `backend/tests/integration/test_protocol_knowledgebase_handoff.py`, change the `_persist_placeholder` signature (line ~46) to accept source fields with OpenWetWare defaults so existing callers are unaffected:

```python
async def _persist_placeholder(
    db: AsyncSession,
    session_id: str,
    tool_call_id: str,
    source_url: str = "https://openwetware.org/wiki/X",
    license: str = "CC BY-SA 3.0",
) -> ChatMessage:
```

Inside, use `source_url` and `license` in the `payload_preview` dict in place of the two hardcoded literals.

- [ ] **Step 2: Add the protocols.io composition test**

Add at the end of `backend/tests/integration/test_protocol_knowledgebase_handoff.py`:

```python
@pytest.mark.asyncio
async def test_protocols_io_source_approval_composes(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    db_session: AsyncSession,
):
    """The approval handshake is source-agnostic: a protocols.io candidate
    streams approval_required and resolves to done on approve."""
    session_id = await _create_session(client, auth_headers)
    tool_call_id = "call_protocols_io_1"
    source_url = "https://www.protocols.io/view/plasmid-miniprep-abc123"
    placeholder = await _persist_placeholder(
        db_session, session_id, tool_call_id,
        source_url=source_url, license="CC BY 4.0",
    )

    stream_events = [
        {
            "type": "approval_required",
            "tool_call_id": tool_call_id,
            "tool_name": "create_protocol_from_external_source",
            "title": "Plasmid Miniprep",
            "source_url": source_url,
            "payload_preview": {
                "title": "Plasmid Miniprep",
                "source_url": source_url,
                "step_count": 6,
                "license": "CC BY 4.0",
                "deviations": [],
            },
            "assistant_message_id": str(placeholder.id),
        },
    ]
    with patch(
        "app.api.endpoints.chat.send_message_streaming",
        return_value=_yield_canned(*stream_events),
    ):
        async with client.stream(
            "POST",
            f"/chat/sessions/{session_id}/messages/stream",
            json={"content": "find a protocols.io miniprep"},
            headers=auth_headers,
        ) as resp:
            assert resp.status_code == 200
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
    assert "approval_required" in [e["type"] for e in _parse_sse_lines(body)]

    resume_events = [
        {
            "type": "done",
            "user_message": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "USER",
                "content": "Approved external protocol conversion.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "assistant_message": {
                "id": str(placeholder.id),
                "session_id": session_id,
                "role": "ASSISTANT",
                "content": "Drafted Plasmid Miniprep.",
                "metadata_": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            "sources": [],
        }
    ]
    with patch(
        "app.api.endpoints.chat.resume_message_streaming",
        return_value=_yield_canned(*resume_events),
    ):
        resp = await client.post(
            f"/chat/sessions/{session_id}/messages/approve",
            json={"tool_call_id": tool_call_id, "approved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    events = _parse_sse_lines(body)
    assert [e["type"] for e in events] == ["done"]
    assert "Drafted" in events[0]["assistant_message"]["content"]
```

- [ ] **Step 3: Run the integration test — verify it passes**

Run: `pytest tests/integration/test_protocol_knowledgebase_handoff.py -v`
Expected: PASS (all — the two pre-existing tests plus the new one).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_protocol_knowledgebase_handoff.py
git commit -m "test(F-0090): protocols.io approval composition is source-agnostic"
```

---

### Task 11: Terms of Service — externally-sourced-content clause + activation

**Files:**
- Create: `backend/app/legal/versions/2026-05-19/terms.md`
- Create: `backend/app/legal/versions/2026-05-19/privacy.md`
- Modify: `backend/app/legal/versions/__init__.py`
- Test: `backend/tests/unit/test_legal_content.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/unit/test_legal_content.py`:

Update `test_terms_has_version_header` (lines 51-54) and `test_privacy_has_version_header` (lines 57-60) — change both `2026-04-27` literals in each to `2026-05-19`:

```python
def test_terms_has_version_header():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "**Version:** 2026-05-19" in terms
    assert "**Effective Date:** 2026-05-19" in terms


def test_privacy_has_version_header():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    assert "**Version:** 2026-05-19" in privacy
    assert "**Effective Date:** 2026-05-19" in privacy
```

Add two new tests at the end of the file:

```python
def test_terms_contains_externally_sourced_content_section():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "Externally-Sourced Protocol Content" in terms


def test_2026_05_19_version_registered_and_loadable():
    assert "2026-05-19" in legal_service.list_versions()
    doc = legal_service.get_document("2026-05-19", "terms")
    assert doc["effective_date"] == "2026-05-19"
```

- [ ] **Step 2: Run the tests — verify they fail**

Run: `pytest tests/unit/test_legal_content.py -v`
Expected: FAIL — version-header tests fail (`CURRENT_VERSION` is still `2026-04-27`); the registry test fails (`KeyError: '2026-05-19'`).

- [ ] **Step 3: Create the new version directory from the current one**

Run:
```bash
cp -r backend/app/legal/versions/2026-04-27 backend/app/legal/versions/2026-05-19
```

- [ ] **Step 4: Bump the version headers in both new files**

In `backend/app/legal/versions/2026-05-19/terms.md`, change the header lines (4-5):
```markdown
**Version:** 2026-05-19
**Effective Date:** 2026-05-19
```

In `backend/app/legal/versions/2026-05-19/privacy.md`, make the same two-line header change to `2026-05-19`. (The privacy policy body is otherwise unchanged — the version header is the sole edit, since every document in a version directory names that version.)

- [ ] **Step 5: Insert the new section into the new `terms.md`**

In `backend/app/legal/versions/2026-05-19/terms.md`, insert a new section immediately after the end of `## 7. Customer Data; License to Us` (after its paragraph, before `## 8. Acceptable Use`):

```markdown
## 8. Externally-Sourced Protocol Content

The Service may let you import protocol content that originates from third-party public repositories and is made available under an open-content license (for example, a Creative Commons license). Imported content remains subject to its original license, and the rights you have in it are only those that license grants. Batchrite surfaces the source and the license of imported content but does not grant you, and does not assume on your behalf, any rights or obligations in that content. You are responsible for complying with the original license — including its attribution requirements and, for "ShareAlike" licenses, the obligation to license a derivative under the same terms if you redistribute it outside your organization. The ownership representation in Section 7 does not extend to imported third-party content; that content is hosted as Customer Data but is not owned by you.
```

- [ ] **Step 6: Renumber the subsequent sections**

In the same file, renumber every section heading from the old §8 onward by +1 (the headings only — body text references are handled in Step 7):

```
## 8. Acceptable Use            → ## 9. Acceptable Use
## 9. Intellectual Property     → ## 10. Intellectual Property
## 10. Confidentiality          → ## 11. Confidentiality
## 11. Fees & Payment           → ## 12. Fees & Payment
## 12. Term & Termination       → ## 13. Term & Termination
## 13. Warranty Disclaimer      → ## 14. Warranty Disclaimer
## 14. Limitation of Liability  → ## 15. Limitation of Liability
## 15. Indemnification          → ## 16. Indemnification
## 16. Governing Law; Dispute Resolution → ## 17. Governing Law; Dispute Resolution
## 17. Changes to These Terms   → ## 18. Changes to These Terms
## 18. Contact                  → ## 19. Contact
```

- [ ] **Step 7: Fix the in-body section cross-references**

Two body sentences cite section numbers and must be updated for the +1 shift and the new survivor:

In `## 13. Term & Termination` (the renumbered §13), the survival list currently reads
`(e.g., 4, 7, 9, 10, 13, 14, 15, 16)` — change it to `(e.g., 4, 7, 8, 10, 11, 14, 15, 16, 17)`.

In `## 16. Indemnification` (the renumbered §16), the sentence
`arising from your breach of Sections 4 (PHI), 7 (Customer Data rights), or 8 (Acceptable Use)`
— `8 (Acceptable Use)` becomes `9 (Acceptable Use)`.

(The §15 Limitation-of-Liability internal `Section 14` reference is itself §14 after renumbering — verify the Indemnification clause's `subject to the limitations in Section 14` becomes `Section 15`.)

- [ ] **Step 8: Register and activate the new version**

Replace the body of `backend/app/legal/versions/__init__.py` below the docstring:

```python
CURRENT_VERSION = "2026-05-19"

ALL_VERSIONS = [
    "2026-04-27",
    "2026-05-19",
]

assert (
    CURRENT_VERSION in ALL_VERSIONS
), f"CURRENT_VERSION={CURRENT_VERSION!r} is not in ALL_VERSIONS"
```

- [ ] **Step 9: Run the legal tests — verify they pass**

Run: `pytest tests/unit/test_legal_content.py tests/unit/test_legal_service.py tests/unit/test_config_legal.py tests/integration/test_legal_endpoints.py -v`
Expected: PASS (all). The required-section and counsel-TODO assertions still pass — the new `terms.md` is a superset of 2026-04-27.

- [ ] **Step 10: Commit (activation-convention message)**

```bash
git add backend/app/legal/versions/2026-05-19/ \
  backend/app/legal/versions/__init__.py \
  backend/tests/unit/test_legal_content.py
git commit -m "feat(legal): activate ToS/Privacy version 2026-05-19

Adds the Externally-Sourced Protocol Content clause (F-0090) and bumps
CURRENT_VERSION. Pre-launch, no production users — no re-acceptance churn.
Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Documentation & rule corrections

**Files:**
- Modify: `CLAUDE.md` (feature-flag table)
- Modify: `CONTEXT.md` (glossary)
- Modify: `.claude/rules/backend-ai.md`
- Modify: `.claude/rules/backend-services.md`
- Modify: `docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md`

- [ ] **Step 1: Update the CLAUDE.md feature-flag row**

In `CLAUDE.md`, in the feature-flags table, replace the `External protocols` row's Backend cell and Notes cell so they describe the per-source structure. New Backend cell:
`features.external_protocols.enabled (master) + features.external_protocols.<source>.enabled (yaml) or BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__<SOURCE>__ENABLED (env)`
New Notes cell — append to the existing note:
`Per-source sub-blocks: openwetware (default on), protocols_io (default off, needs access_token). A source is live iff master AND source flag. (F-0084, F-0090)`

- [ ] **Step 2: Update the CONTEXT.md glossary**

In `CONTEXT.md`, add glossary entries (alphabetical, matching the file's existing format):
- **External protocol source** — A public repository the `protocol_knowledgebase` subagent searches (OpenWetWare, protocols.io). Each has its own connector module and feature sub-flag under `external_protocols`.
- **License-compatibility gate** — `licenses.classify_license`: a pure classifier that only marks a protocol import-safe if its license permits commercial use AND derivatives (CC0/CC-BY/CC-BY-SA/public-domain). Fails closed on NC/ND/unknown.
- **`import_allowed`** — Field on `ExternalProtocolPayload`. `False` means a license-restricted protocol parsed to metadata only (no step text copied); the subagent surfaces it as a link, never an automatic import.

- [ ] **Step 3: Correct `.claude/rules/backend-ai.md`**

In `.claude/rules/backend-ai.md`, find the bullet under "Where things go":
`- **Pure validators / business rules** the agent uses (e.g. graph validation): live in the domain service, not here. Example: services/protocols/validation.py. Tools wrap them.`

Replace it with:
```markdown
- **Pure logic the agent uses** — connectors, parsers, source-specific gates,
  validators. If it is genuinely shared across multiple consumers (a non-chat
  path also calls it), put it in the domain service — e.g.
  `services/protocols/validation.py`. If it is owned by a single subagent, keep
  it as sibling modules inside that subagent's own package (e.g.
  `subagents/protocol_knowledgebase/openwetware.py`, `licenses.py`) so the
  agent's logic stays next to the agent and stays independently testable.
  Tools wrap it either way.
```

- [ ] **Step 4: Correct `.claude/rules/backend-services.md`**

In `.claude/rules/backend-services.md`, under "AI Tools vs Domain Services", replace the sentence:
`Pure business logic — graph validation, parameter checks, structural transforms — belongs in services/<domain>/, not in the AI package.`

with:
```markdown
Pure business logic belongs in `services/<domain>/` **when it is genuinely
shared** — a non-chat code path also calls it (e.g. graph validation, used by
both the chat tool and the publish endpoint). Logic owned by a single subagent
— connectors, parsers, source-specific gates — lives as sibling modules inside
that subagent's own package (e.g. `subagents/protocol_knowledgebase/openwetware.py`,
`licenses.py`), keeping the agent's logic next to the agent and independently
testable. Favor locality; reserve `services/<domain>/` for shared code.
```

- [ ] **Step 5: Forward-pointer in the F-0084 spec**

Open `docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md`. Locate the non-goal / scope bullet stating OpenWetWare is the only source (a "v1 scope: OpenWetWare only" type statement). Append a parenthetical forward pointer to it:
`(Superseded by F-0090, which adds protocols.io as a second source — see docs/superpowers/specs/2026-05-19-f-0090-additional-protocol-sources-evaluation.md.)`

- [ ] **Step 6: Run the full backend suite — verify nothing regressed**

Run: `pytest tests/unit tests/integration -q`
Expected: PASS (no failures).

- [ ] **Step 7: Lint**

Run: `black app tests && isort app tests && mypy app`
Expected: clean (no diffs from black/isort; no new mypy errors in the touched modules).

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md CONTEXT.md .claude/rules/backend-ai.md \
  .claude/rules/backend-services.md \
  docs/superpowers/specs/2026-05-12-f-0084-protocol-knowledgebase-subagent-design.md
git commit -m "docs(F-0090): per-source flags, locality rule, glossary, F-0084 pointer"
```

---

### Task 13: Live protocols.io smoke-test script

A standalone harness — like `scripts/f0089_hitl_live.py` — that exercises the
real protocols.io API end-to-end through the F-0090 connector. It is **not** a
unit test and never runs in CI; running it manually *is* the verification. It
also doubles as the executable form of Task 6 Step 0: `--raw` dumps the live
v4 detail JSON so the parser fixtures can be checked against reality.

**Files:**
- Create: `backend/scripts/f0090_protocols_io_live.py`

**Prerequisite:** depends on the Task 7 connector (`protocols_io.search_protocols_io`,
`fetch_protocols_io`, `_protocol_id_from_url`, `_DETAIL_URL`) and the Task 5
license gate — do Task 13 only after Task 7. There is no red/green cycle here:
the script wraps already-built code, and a manual run is the assertion.

- [ ] **Step 1: Create the script**

Create `backend/scripts/f0090_protocols_io_live.py`:

```python
"""F-0090 live smoke test for the protocols.io connector.

Usage (from backend/, venv active):
    python scripts/f0090_protocols_io_live.py [--query QUERY] [--url URL] [--raw]

Hits the real protocols.io v3 search + v4 detail endpoints with the configured
access token, then runs the F-0090 connector + parser + license gate over the
live response and prints the result. With --raw it also dumps the raw v4
detail JSON so the Task 6 parser fixtures can be confirmed against the live
shape.

Calls the connector module directly, so it works regardless of the
external_protocols / protocols_io feature flags — it only needs a token:
    BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN

This is a manual harness — never run in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import protocols_io
from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)


def _config() -> object:
    return settings.features.external_protocols.protocols_io


async def _dump_raw_detail(url: str, token: str, timeout: float) -> None:
    """Print the raw v4 detail JSON — the executable form of Task 6 Step 0.

    Uses the connector's private id/URL helpers deliberately: this script is a
    sibling of the connector and exists to confirm the very shape the parser
    expects.
    """
    protocol_id = protocols_io._protocol_id_from_url(url)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{protocols_io._DETAIL_URL}/{protocol_id}",
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
    print(
        "--- raw v4 detail JSON "
        "(compare to tests/fixtures/protocols_io/protocol_detail.json) ---"
    )
    print(json.dumps(resp.json(), indent=2))
    print("--- end raw JSON ---\n")


async def _run(args: argparse.Namespace) -> int:
    cfg = _config()
    token = cfg.access_token.strip()
    if not token:
        print(
            "ERROR: no protocols.io access token configured. Set "
            "BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN "
            "in backend/.env and retry.",
            file=sys.stderr,
        )
        return 1
    timeout = cfg.request_timeout_seconds

    if args.url:
        url = args.url
    else:
        print(f"[search] query={args.query!r} …")
        result = await protocols_io.search_protocols_io(
            args.query, access_token=token, limit=5, timeout=timeout
        )
        print(f"[search] {result.total} hit(s)")
        for hit in result.hits:
            print(f"  - {hit.title}\n    {hit.url}")
        if not result.hits:
            print("[search] no hits — nothing to fetch. Try another --query.")
            return 0
        url = result.hits[0].url

    print(f"\n[fetch] {url}")
    if args.raw:
        await _dump_raw_detail(url, token, timeout)

    payload = await protocols_io.fetch_protocols_io(
        url, access_token=token, timeout=timeout
    )
    if payload.error:
        print(f"[fetch] ERROR: {payload.error}", file=sys.stderr)
        return 1

    verdict = classify_license(payload.license)
    print(f"[fetch] title:           {payload.title}")
    print(f"[fetch] license raw:     {payload.license!r}")
    print(
        f"[fetch] license verdict: {verdict.normalized} "
        f"(import_allowed={verdict.import_allowed})"
    )
    print(f"[fetch] import_allowed:  {payload.import_allowed}")
    print(f"[fetch] license_note:    {payload.license_note}")
    print(f"[fetch] materials:       {len(payload.materials)}")
    print(f"[fetch] steps:           {len(payload.steps)}")
    print(f"[fetch] summary:         {payload.summary[:200]}")
    print("\n[ok] live protocols.io connector round-trip succeeded.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F-0090 protocols.io live smoke test"
    )
    parser.add_argument("--query", default="miniprep", help="search query")
    parser.add_argument(
        "--url", default="", help="skip search; fetch this protocol URL directly"
    )
    parser.add_argument(
        "--raw", action="store_true", help="also dump the raw v4 detail JSON"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the live API**

Run (from `backend/`, venv active, token in `backend/.env` under
`BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN`):

`python scripts/f0090_protocols_io_live.py --query miniprep --raw`

Expected: `[search]` prints ≥1 hit; `[fetch]` prints a title, a `license raw`
that classifies to `CC-BY` with `import_allowed=True`, and a non-zero step
count; the run ends with `[ok] live protocols.io connector round-trip
succeeded.` and exit code 0. With no token configured it prints the
`ERROR: no protocols.io access token …` message and exits 1.

Then compare the `--raw` JSON dump against
`tests/fixtures/protocols_io/protocol_detail.json`. If the live shape differs
(e.g. steps nested under `components`, license under a different key), fix the
fixture **and** the Task 6 parser's field accessors together, then re-run
`pytest tests/unit/test_protocols_io_parser.py -v`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/f0090_protocols_io_live.py
git commit -m "test(F-0090): live protocols.io connector smoke-test script"
```

---

### Task 14: Marked live integration tests

Repeatable pytest coverage that hits the real protocols.io API, carrying a
`live` marker so it is excluded from the default CI run and auto-skipped when
no access token is configured. Like Task 13 this wraps already-built code —
write the tests, then run them; there is no red phase.

**Files:**
- Modify: `backend/pyproject.toml` (register the `live` marker)
- Test: `backend/tests/integration/test_protocols_io_live.py`

- [ ] **Step 1: Register the `live` marker**

In `backend/pyproject.toml`, under `[tool.pytest.ini_options]`, add a second
entry to the `markers` list:

```toml
markers = [
    "benchmark: LLM accuracy and E2E protocol import benchmarks (requires AI provider)",
    "live: hits a real external API (requires network + credentials); run with -m live",
]
```

- [ ] **Step 2: Write the live tests**

Create `backend/tests/integration/test_protocols_io_live.py`:

```python
"""Live protocols.io API tests (F-0090).

Carry the ``live`` marker — excluded from the default CI run (`pytest -m
"not live"`) and auto-skipped when no access token is configured, so an
unconfigured CI environment never makes a network call.

Run explicitly:
    pytest -m live tests/integration/test_protocols_io_live.py -v

They call the connector module directly, so the external_protocols /
protocols_io feature flags need not be on — only an access token is required.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ai.subagents.protocol_knowledgebase import protocols_io
from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)

pytestmark = pytest.mark.live

_CFG = settings.features.external_protocols.protocols_io
_NO_TOKEN = not _CFG.access_token.strip()
_SKIP_REASON = (
    "no protocols.io access token "
    "(BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN)"
)


@pytest.mark.skipif(_NO_TOKEN, reason=_SKIP_REASON)
async def test_live_search_returns_hits():
    """The v3 search endpoint accepts the token and returns parseable hits."""
    result = await protocols_io.search_protocols_io(
        "miniprep",
        access_token=_CFG.access_token,
        limit=5,
        timeout=_CFG.request_timeout_seconds,
    )
    assert result.total > 0, "expected at least one public protocols.io hit"
    first = result.hits[0]
    assert first.url.startswith("https://www.protocols.io/")
    assert first.title


@pytest.mark.skipif(_NO_TOKEN, reason=_SKIP_REASON)
async def test_live_fetch_round_trips_through_parser():
    """A live protocol fetch round-trips through the parser + license gate."""
    search = await protocols_io.search_protocols_io(
        "miniprep",
        access_token=_CFG.access_token,
        limit=5,
        timeout=_CFG.request_timeout_seconds,
    )
    assert search.hits, "search returned no hits — cannot fetch"

    payload = await protocols_io.fetch_protocols_io(
        search.hits[0].url,
        access_token=_CFG.access_token,
        timeout=_CFG.request_timeout_seconds,
    )
    # A live public protocol must parse cleanly — no genuine-failure error.
    assert payload.error is None, f"live fetch failed: {payload.error}"
    assert payload.title
    # The license must classify to a real verdict, not crash the parser.
    verdict = classify_license(payload.license)
    assert verdict.normalized
    # Import-safe protocols carry step text; restricted ones must not.
    if payload.import_allowed:
        assert payload.steps, "import-safe protocol parsed to 0 steps"
    else:
        assert payload.steps == []
```

- [ ] **Step 3: Run them — with and without a token**

With a token configured in `backend/.env`:
Run: `pytest -m live tests/integration/test_protocols_io_live.py -v`
Expected: PASS (both tests) — the live API is reachable and the connector
round-trips.

The CI guarantee — simulate an unconfigured environment by overriding the
token to empty (env vars take priority over `.env`):
Run: `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN= pytest -m live tests/integration/test_protocols_io_live.py -v`
Expected: SKIPPED (both) with reason "no protocols.io access token …" — no
network call is made.

Confirm the default suite excludes them:
Run: `pytest -m "not live" tests/integration/test_protocols_io_live.py -q`
Expected: `2 deselected`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/tests/integration/test_protocols_io_live.py
git commit -m "test(F-0090): marked live protocols.io integration tests"
```

---

## Self-Review

**Spec coverage:**
- Part A (evaluation) — documentation-only; lives in the spec, no code task. ✔
- B.1 per-source config — Task 1. ✔
- B.2 flat sibling modules — Tasks 2–7. ✔
- B.3 protocols.io connector (explicit primitives) — Tasks 6–7. ✔
- B.4 license gate + three terminal states + cache-iff-`error is None` — Tasks 5, 6, 7. ✔
- B.5 multi-source dispatch + `(org, source)` rate key — Tasks 3, 7. ✔
- B.6 tools & prompt — Tasks 7, 8. ✔
- B.7 HITL `import_allowed` re-check — Task 9. ✔
- B.8 frontend untouched — no task (correct). ✔
- B.9 ToS clause + activation — Task 11. ✔
- D.1 unit tests — Tasks 1–9. D.2 integration — Task 10. ✔
- E files touched — all covered; §E rule corrections — Task 12. ✔
- Live protocols.io API verification — smoke-test script (Task 13) + marked
  `live` integration tests (Task 14). Confirms the real API works with the
  configured token and that the connector/parser/license gate round-trip live
  data, beyond the fixture-driven unit tests. ✔

**Type consistency:** `ExternalProtocolPayload` / `ExternalProtocolStep` / `OpenWetWareSearchResult` / `ProtocolsIoSearchResult` / `ProtocolsIoHit` defined once in `types.py` (Task 2) and imported everywhere. Connector functions: `openwetware.search` / `openwetware.fetch`; `protocols_io.search_protocols_io` / `protocols_io.fetch_protocols_io`; wrappers `tools.search_openwetware` / `fetch_openwetware_protocol` / `search_protocols_io` / `fetch_protocols_io`. `rate_limit.check_rate_limit(org_id, source, limit)` — same 3-arg signature at every call site. `classify_license(raw) -> LicenseVerdict` — single definition, single consumer (`protocols_io.parse_protocols_io_json`).

**Note on protocols.io API shape:** Task 6 Step 0 pins the live v4 JSON shape; the fixtures are the parser's contract. This is a deliberate, spec-sanctioned implementation-time confirmation, not a placeholder — the fixture + parser are concrete and consistent today. Task 13's `--raw` flag makes that confirmation executable: once the connector exists, the script dumps the real v4 JSON so any drift between fixture and live response is caught and reconciled before the feature ships.

**Note on the access-token env var:** the token is read from the nested config `settings.features.external_protocols.protocols_io.access_token`, so the env var name is the fully nested `BATCHRITE_FEATURES__EXTERNAL_PROTOCOLS__PROTOCOLS_IO__ACCESS_TOKEN` (Task 1 test asserts exactly this). A shorter name such as `BATCHRITE_PROTOCOLS_IO__ACCESS_TOKEN` is silently ignored — it does not match the config path.
