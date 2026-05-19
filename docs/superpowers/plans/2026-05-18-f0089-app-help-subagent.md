# App Help Subagent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the global chat agent grounded knowledge of Batchrite itself — how features work, where pages live, what terms mean, troubleshooting — via a new `app_help` chat subagent backed by a curated in-repo Markdown corpus, plus page-context awareness so the agent knows which route the user is viewing.

**Architecture:** A new `app_help` subagent (matching the existing `protocol_knowledgebase` package shape) gets two filesystem tools — `list_user_guide_pages` and `read_user_guide_page` — over `docs/user-guide/*.md`. No retrieval engine, no embeddings: the LLM picks the relevant page from a cheap frontmatter index and reads it. Page-context awareness reuses the existing `[skill:<id>]` server-prefix mechanism: a `[page:<route>]` marker is prepended to the model-visible prompt only.

**Tech Stack:** FastAPI, pydantic-ai 1.75+ (`SubAgentConfig` / `subagents-pydantic-ai`), PyYAML (already a dependency, used by `app/core/yaml_source.py`), Svelte 5 runes, pytest-asyncio, Vitest.

**Spec:** `docs/superpowers/specs/2026-05-18-f0089-app-help-subagent-design.md` (approved + grilled 2026-05-18).

---

## File Structure

**Created:**
- `docs/user-guide/README.md` — human-facing index + Phase-1 audit record
- `docs/user-guide/*.md` — one curated page per verified-shipped surface
- `backend/app/services/ai/subagents/app_help/__init__.py`
- `backend/app/services/ai/subagents/app_help/config.py` — `build(model) -> SubAgentConfig`
- `backend/app/services/ai/subagents/app_help/prompt.md` — end-user-tone instructions
- `backend/app/services/ai/subagents/app_help/tools.py` — the two tools, dataclasses, `TOOL_LABELS`
- `backend/tests/unit/test_subagents_app_help.py` — tool unit tests
- `backend/tests/unit/test_app_help_config.py` — config-builder test
- `backend/tests/integration/test_app_help_corpus.py` — real-corpus quality guard

**Modified:**
- `backend/app/core/config.py` — `Settings.user_guide_dir`
- `backend/app/services/ai/subagents/__init__.py` — register `app_help` package
- `backend/app/services/ai/chat_agent.py` — add `app_help` to the `subagents` list
- `backend/app/services/ai/prompts/chat_agent.md` — `app_help` dispatch entry + `[page:<route>]` paragraph
- `backend/app/schemas/chat.py` — `ChatMessageCreate.current_route`
- `backend/app/services/ai/send_message.py` — `current_route` param + `[page:<route>]` prefix
- `backend/app/api/endpoints/chat.py` — pass `current_route` through
- `backend/tests/unit/test_send_message_streaming.py` — `[page:<route>]` prefix tests
- `backend/tests/unit/test_chat_agent_prompt_guardrail.py` — assert the `app_help` and `[page:<route>]` prompt blocks
- `frontend/src/lib/chat-store.svelte.ts` — attach `current_route` to send body
- `frontend/src/lib/chat-store.test.ts` — `current_route` assertions
- `.claude/rules/backend-ai.md` — `app_help` note in the subagents directory tree

**Validation tier:** All F-0089 rules are **T1 (backend-only)**. The subagent registration and the corpus are entirely server-side; there is no frontend predicate to mirror and no primary action button gated by this feature. `current_route` is additive request metadata, not a rule.

---

## Phase 1 — Feature audit

### Task 1: Audit which surfaces are shipped and on-by-default

The corpus may document only features an end user can use **today on production defaults**. Flag-gated-off features (offline mode, external protocols) and unbuilt features (voice/dictation) are excluded. This task verifies the surface list before any page is written.

**Files:**
- Create: `docs/user-guide/README.md`

- [ ] **Step 1: Enumerate shipped frontend routes**

Run:
```bash
find frontend/src/routes -name '+page.svelte' | sort
```
Expected: a list of route files. Note each top-level surface (protocols, runs/experiments, library, chat, settings, sites/equipment, etc.).

- [ ] **Step 2: Check which features are flag-gated**

Run:
```bash
grep -n 'class .*FeatureConfig' backend/app/core/config.py
grep -rn 'features\.' backend/app/services/ backend/app/api/ | grep -i enabled
```
Expected: confirms `offline_mode` and `external_protocols` are the only flag-gated features and both default `false`. **Exclude both from the corpus.**

- [ ] **Step 3: Confirm voice/dictation is not built**

Run:
```bash
grep -rin 'dictation\|speech.*recognition\|voice' frontend/src backend/app || echo 'NOT BUILT'
```
Expected: no real feature implementation. **Exclude voice/dictation.**

- [ ] **Step 4: Confirm ambiguous surfaces (lot producer, billing)**

Run:
```bash
ls frontend/src/routes | grep -iE 'billing|lot'
grep -rin 'lot.*producer\|stripe' backend/app/api/endpoints/ | head
```
Decide per surface: if it ships on-by-default with no flag, it gets a page; if flag-gated or unbuilt, it is excluded. Record the decision.

- [ ] **Step 5: Write `docs/user-guide/README.md`**

This file is the human-facing index and the audit record. It is **not** surfaced to the model (the `list_user_guide_pages` tool skips `README.md`). Use this exact content, replacing the page list with the audited surfaces from Steps 1–4:

```markdown
# Batchrite User Guide

This directory is the curated knowledge corpus for the in-app **App Help**
chat subagent (`app_help`, F-0089). Each `.md` page documents one shipped
Batchrite feature surface in end-user voice.

## How it works

The chat agent dispatches the `app_help` subagent for product questions
("how do I…", "what is…", "where is…"). The subagent lists these pages by
their frontmatter, reads the relevant one, and answers with a citation.
Adding or editing a page takes effect immediately — the tools read disk on
every call. (Adding a *new subagent* or changing prompts needs a process
restart; editing corpus `.md` files does not.)

## Authoring rules

- End-user voice — second person ("You can…"), no developer jargon, no
  internal file paths in user-facing prose.
- Document only features shipped and on-by-default. Flag-gated-off features
  (offline mode, external protocols) and unbuilt features (voice/dictation)
  are excluded until shipped on by default.
- Every page starts with YAML frontmatter: `title`, `summary`, `keywords`.
- ~150–500 words per page. Follow the template: overview → "What you can
  do" bullets → "How to …" sections.

## Pages

- `getting-started.md` — <one-line description>
- `protocols-and-editor.md` — <one-line description>
- ... (one line per audited surface from Phase 1)

## Excluded (not shipped on production defaults)

- Offline / PWA mode — flag-gated off (`features.offline_mode`).
- External protocols / OpenWetWare — flag-gated off (`features.external_protocols`).
- Voice / dictation — not built.
```

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide corpus index + feature audit"
```

---

## Phase 2 — Subagent infrastructure

### Task 2: Configuration — the `user_guide_dir` setting

> **Spec deviation — no feature flag.** The approved spec gated `app_help`
> behind an `AppHelpFeatureConfig` flag. Plan review (grill Branch 7)
> dropped the flag: `app_help` only reads in-repo Markdown — no external
> dependency, no cost, no rollout risk — the corpus ships in this same
> feature, and a static prompt file cannot conditionally hide a specialist
> without breaking dispatch when the flag is off. `app_help` is a core,
> always-registered specialist like `research_library`. `user_guide_dir`
> below is a *path* setting (a location), not a gate.

**Files:**
- Modify: `backend/app/core/config.py` — the `Settings` body near `:164` (next to `skills_dir`)
- Test: `backend/tests/unit/test_subagents_app_help.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_subagents_app_help.py` with:

```python
"""Unit tests for the app_help subagent (F-0089)."""

from pathlib import Path

from app.core.config import settings


def test_user_guide_dir_points_at_repo_docs():
    """user_guide_dir resolves to the repo-root docs/user-guide directory."""
    path = Path(settings.user_guide_dir)
    assert path.name == "user-guide"
    assert path.parent.name == "docs"
    # Absolute so it resolves regardless of process CWD (backend/ at runtime).
    assert path.is_absolute()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_subagents_app_help.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'user_guide_dir'`.

- [ ] **Step 3: Add the `user_guide_dir` setting**

In `backend/app/core/config.py`, directly after the `skills_dir` block (line ~166):

```python
    # App-help corpus directory (F-0089). Repo-root docs/user-guide — an
    # absolute path computed from __file__ so it resolves regardless of the
    # process CWD (backend/ at runtime). parents[3] is the repo root, the
    # same anchor docling_script_path uses. Override via env in deploy.
    user_guide_dir: str = str(
        Path(__file__).resolve().parents[3] / "docs" / "user-guide"
    )
```

> **Spec correction:** the spec sketched `user_guide_dir: str = "docs/user-guide"` (relative). A relative path resolves against the process CWD, which is `backend/` at runtime — that would point at the nonexistent `backend/docs/user-guide`. The corpus lives at repo-root `docs/user-guide`, so the default must be the absolute `parents[3]` form, matching `docling_script_path`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_subagents_app_help.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_subagents_app_help.py
git commit -m "feat(F-0089): add user_guide_dir setting for the app_help corpus"
```

---

### Task 3: Tools — `list_user_guide_pages` and `read_user_guide_page`

**Files:**
- Create: `backend/app/services/ai/subagents/app_help/__init__.py`
- Create: `backend/app/services/ai/subagents/app_help/tools.py`
- Test: `backend/tests/unit/test_subagents_app_help.py` (extend)

- [ ] **Step 1: Create the package marker**

Create `backend/app/services/ai/subagents/app_help/__init__.py`:

```python
"""app_help subagent — product Q&A from the docs/user-guide corpus (F-0089)."""
```

- [ ] **Step 2: Write the failing tests**

Add these imports to the top of `backend/tests/unit/test_subagents_app_help.py` (the file already imports `Path` and `settings` from Task 2 — merge, do not duplicate):

```python
import logging
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from app.services.ai.subagents.app_help import tools as app_help_tools
```

Then append the test helpers and functions:

```python


@dataclass
class _FakeDeps:
    tool_calls: list


def _ctx() -> MagicMock:
    """A RunContext stand-in exposing .deps.tool_calls."""
    ctx = MagicMock()
    ctx.deps = _FakeDeps(tool_calls=[])
    return ctx


def _write(dir_path, name: str, body: str) -> None:
    (dir_path / name).write_text(body, encoding="utf-8")


_PAGE = """\
---
title: Protocols and the protocol editor
summary: How to create and edit protocols.
keywords: [protocol, editor]
---

# Protocols and the protocol editor

You build protocols on a visual canvas.
"""


@pytest.mark.asyncio
async def test_list_parses_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "protocols.md", _PAGE)

    result = await app_help_tools.list_user_guide_pages(_ctx())

    assert result.total == 1
    page = result.pages[0]
    assert page.filename == "protocols.md"
    assert page.title == "Protocols and the protocol editor"
    assert page.summary == "How to create and edit protocols."
    assert page.keywords == ["protocol", "editor"]


@pytest.mark.asyncio
async def test_list_sorted_alphabetically(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "zebra.md", _PAGE)
    _write(tmp_path, "alpha.md", _PAGE)

    result = await app_help_tools.list_user_guide_pages(_ctx())

    assert [p.filename for p in result.pages] == ["alpha.md", "zebra.md"]


@pytest.mark.asyncio
async def test_list_skips_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "README.md", "# index\n")
    _write(tmp_path, "protocols.md", _PAGE)

    result = await app_help_tools.list_user_guide_pages(_ctx())

    assert [p.filename for p in result.pages] == ["protocols.md"]


@pytest.mark.asyncio
async def test_list_frontmatter_fallback_logs_warning(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "getting-started.md", "# No frontmatter here\n\nBody.")

    with caplog.at_level(logging.WARNING):
        result = await app_help_tools.list_user_guide_pages(_ctx())

    page = result.pages[0]
    assert page.title == "Getting Started"  # filename-derived fallback
    assert page.summary == ""
    assert page.keywords == []
    assert "getting-started.md" in caplog.text


@pytest.mark.asyncio
async def test_list_missing_directory_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings,
        "user_guide_dir",
        str(tmp_path / "does-not-exist"),
    )
    result = await app_help_tools.list_user_guide_pages(_ctx())
    assert result.total == 0
    assert result.pages == []


@pytest.mark.asyncio
async def test_list_empty_directory_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    result = await app_help_tools.list_user_guide_pages(_ctx())
    assert result.total == 0
    assert result.pages == []


@pytest.mark.asyncio
async def test_read_strips_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "protocols.md", _PAGE)

    result = await app_help_tools.read_user_guide_page(_ctx(), "protocols.md")

    assert result.error is None
    assert result.title == "Protocols and the protocol editor"
    assert result.content.startswith("# Protocols and the protocol editor")
    assert "---" not in result.content


@pytest.mark.asyncio
async def test_read_path_traversal_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    result = await app_help_tools.read_user_guide_page(
        _ctx(), "../../etc/passwd"
    )
    assert result.error is not None
    assert result.content == ""


@pytest.mark.asyncio
async def test_read_missing_file_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    result = await app_help_tools.read_user_guide_page(
        _ctx(), "nonexistent.md"
    )
    assert result.error is not None


@pytest.mark.asyncio
async def test_read_non_markdown_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        app_help_tools.settings, "user_guide_dir", str(tmp_path)
    )
    _write(tmp_path, "notes.txt", "plain text")
    result = await app_help_tools.read_user_guide_page(_ctx(), "notes.txt")
    assert result.error is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_subagents_app_help.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai.subagents.app_help.tools'`.

- [ ] **Step 4: Implement `tools.py`**

Create `backend/app/services/ai/subagents/app_help/tools.py`:

```python
"""Tools for the app_help subagent (F-0089).

Two filesystem tools over the curated docs/user-guide corpus:
``list_user_guide_pages`` returns a cheap frontmatter index, and
``read_user_guide_page`` returns one page body. No retrieval engine — the
LLM picks the relevant page from the index. Both tools re-read disk on
every call (no caching), so corpus edits take effect immediately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic_ai import RunContext

from app.core.config import settings
from app.services.ai.deps import ChatDeps

logger = logging.getLogger(__name__)

# Human-readable labels for the chat thinking indicator. Adding a tool here
# MUST also update the entry — enforced by tests/unit/test_tool_labels.py.
TOOL_LABELS: dict[str, str] = {
    "list_user_guide_pages": "Looking up help topics…",
    "read_user_guide_page": "Reading help page…",
}

# A bare corpus filename: letters, digits, dot, dash, underscore only. This
# alone rejects path separators ("/", "\\") and traversal segments — a "/"
# in "../../etc/passwd" fails the match. The .md extension check and the
# resolved-path-under-root check below are belt-and-suspenders.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# Splits "---\n<yaml>\n---\n<body>" into (yaml, body).
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


# ─── Result dataclasses ────────────────────────────────────────────────────


@dataclass
class UserGuidePageMeta:
    filename: str
    title: str
    summary: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class ListUserGuidePagesResult:
    total: int
    pages: list[UserGuidePageMeta] = field(default_factory=list)


@dataclass
class ReadUserGuidePageResult:
    filename: str
    title: str
    content: str
    error: str | None = None


# ─── Frontmatter parsing (lenient) ─────────────────────────────────────────


def _title_from_filename(filename: str) -> str:
    """`getting-started.md` -> `Getting Started`."""
    stem = filename[:-3] if filename.endswith(".md") else filename
    return stem.replace("-", " ").replace("_", " ").strip().title()


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Malformed/absent -> ({}, raw)."""
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, match.group(2)
    if not isinstance(meta, dict):
        return {}, match.group(2)
    return meta, match.group(2)


def _page_meta(filename: str, raw: str) -> UserGuidePageMeta:
    """Build page metadata, falling back leniently on bad frontmatter.

    Every fallback logs a WARNING so corpus-quality issues surface in logs,
    but the page stays discoverable.
    """
    frontmatter, _ = _split_frontmatter(raw)

    title = frontmatter.get("title")
    if not isinstance(title, str) or not title.strip():
        title = _title_from_filename(filename)
        logger.warning(
            "user-guide page %s missing/blank 'title'; using %r",
            filename,
            title,
        )

    summary = frontmatter.get("summary")
    if not isinstance(summary, str):
        if summary is not None:
            logger.warning(
                "user-guide page %s has non-string 'summary'; using empty",
                filename,
            )
        summary = ""

    keywords = frontmatter.get("keywords")
    if not isinstance(keywords, list) or not all(
        isinstance(k, str) for k in keywords
    ):
        if keywords is not None:
            logger.warning(
                "user-guide page %s has malformed 'keywords'; using []",
                filename,
            )
        keywords = []

    return UserGuidePageMeta(
        filename=filename,
        title=title.strip(),
        summary=summary.strip(),
        keywords=list(keywords),
    )


# ─── Tools ─────────────────────────────────────────────────────────────────


async def list_user_guide_pages(
    ctx: RunContext[ChatDeps],
) -> ListUserGuidePagesResult:
    """List every Batchrite user-guide page with its title, summary, and keywords.

    Call this first to see what help topics exist, then read the page whose
    title/summary/keywords best match the question. A missing or empty
    corpus directory returns ``total=0`` (not an error).

    Args:
        ctx: Run context with shared deps.
    """
    root = Path(settings.user_guide_dir)
    pages: list[UserGuidePageMeta] = []
    if root.is_dir():
        for path in sorted(root.glob("*.md")):
            if path.name == "README.md":
                continue  # human-facing index, not a help page
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                logger.warning("user-guide page %s unreadable; skipping", path.name)
                continue
            pages.append(_page_meta(path.name, raw))

    ctx.deps.tool_calls.append(
        {
            "tool": "list_user_guide_pages",
            "subagent": "app_help",
            "pages": len(pages),
        }
    )
    return ListUserGuidePagesResult(total=len(pages), pages=pages)


async def read_user_guide_page(
    ctx: RunContext[ChatDeps],
    filename: str,
) -> ReadUserGuidePageResult:
    """Read one Batchrite user-guide page by its bare filename.

    Pass a filename exactly as returned by ``list_user_guide_pages`` (e.g.
    ``protocols-and-editor.md``). On any problem — bad filename, missing
    file, traversal attempt — a populated ``error`` field is returned
    instead of raising, so you can try a different filename.

    Args:
        ctx: Run context with shared deps.
        filename: Bare ``.md`` filename from list_user_guide_pages.
    """
    audit: dict = {
        "tool": "read_user_guide_page",
        "subagent": "app_help",
        "filename": filename,
    }

    def _fail(message: str) -> ReadUserGuidePageResult:
        ctx.deps.tool_calls.append({**audit, "error": message})
        return ReadUserGuidePageResult(
            filename=filename, title="", content="", error=message
        )

    if (
        not filename
        or "\x00" in filename
        or not _FILENAME_RE.match(filename)
    ):
        return _fail(
            "Invalid filename. Pass a bare .md filename from "
            "list_user_guide_pages — no paths."
        )
    if not filename.endswith(".md"):
        return _fail("Only .md user-guide pages can be read.")

    root = Path(settings.user_guide_dir).resolve()
    target = (root / filename).resolve()
    if root != target.parent:
        return _fail("Filename resolves outside the user-guide directory.")
    if not target.is_file():
        return _fail(
            f"No user-guide page named {filename!r}. Call "
            "list_user_guide_pages to see valid filenames."
        )

    raw = target.read_text(encoding="utf-8")
    meta = _page_meta(filename, raw)
    _, body = _split_frontmatter(raw)

    ctx.deps.tool_calls.append({**audit, "ok": True})
    return ReadUserGuidePageResult(
        filename=filename,
        title=meta.title,
        content=body.strip(),
        error=None,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_subagents_app_help.py -v`
Expected: PASS (all tests from Task 2 + Task 3).

- [ ] **Step 6: Run the tool-label invariant test**

Run: `cd backend && pytest tests/unit/test_tool_labels.py -v`
Expected: PASS — `test_tool_labels.py` scans every `tools.py` for audited tool names; both `list_user_guide_pages` and `read_user_guide_page` already have `TOOL_LABELS` entries, so the parametrized label test passes with no extra change.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/subagents/app_help/ backend/tests/unit/test_subagents_app_help.py
git commit -m "feat(F-0089): app_help corpus tools (list/read user-guide pages)"
```

---

### Task 4: Subagent prompt and config builder

**Files:**
- Create: `backend/app/services/ai/subagents/app_help/prompt.md`
- Create: `backend/app/services/ai/subagents/app_help/config.py`
- Test: `backend/tests/unit/test_app_help_config.py`

- [ ] **Step 1: Write the failing config test**

Create `backend/tests/unit/test_app_help_config.py`:

```python
"""Tests for the app_help subagent config builder (F-0089)."""

from app.services.ai.subagents.app_help.config import build


def test_build_returns_named_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "app_help"
    assert "Batchrite" in cfg["description"]
    # The description must steer the parent away from user-data questions.
    assert "does not" in cfg["description"].lower()


def test_build_registers_both_tools():
    cfg = build("openai:gpt-4.1-mini")
    tool_names = {t.__name__ for t in cfg["agent_kwargs"]["tools"]}
    assert tool_names == {"list_user_guide_pages", "read_user_guide_page"}


def test_build_uses_passed_model():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["model"] == "openai:gpt-4.1-mini"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_app_help_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ai.subagents.app_help.config'`.

- [ ] **Step 3: Write `prompt.md`**

Create `backend/app/services/ai/subagents/app_help/prompt.md`:

```markdown
You answer questions about Batchrite, a Laboratory Execution System for
biotech process development scientists. You speak to end users — lab
scientists — not developers.

To answer:

1. Call `list_user_guide_pages` to see what help topics exist.
2. Read the page (or pages) whose title, summary, or keywords best match
   the question. Pick by content, not list position.
3. Answer concisely in end-user voice — second person ("You can…"). No
   code, no file paths, no jargon unless the page itself uses it.
4. Cite each page you read, at the end, as plain text — no markdown link,
   no bracketed link target. One page:

       Source: Protocols and the protocol editor

   Multiple pages:

       Sources:
       - Protocols and the protocol editor
       - GLP sign-offs

If `list_user_guide_pages` returns nothing relevant, or you read a page
and it does not answer the question, say exactly:

"I don't have documentation on that topic. If this is about a Batchrite
feature, the docs may not be written yet — please email
support@batchrite.com."

If the question could plausibly be about the user's own data (their
uploaded documents, their protocols, their runs) rather than about how
Batchrite works, also add: "If you meant to ask about something in your
own documents or protocols, try rephrasing — I can search those too."

Do NOT fall back to general knowledge about lab software, FastAPI, or
PostgreSQL. You only know what the user-guide pages say.

If the dispatched task mentions the user's current route (for example
"/protocols/abc-123/edit"), use it to pick the page that covers that
surface.

Do not engage in conversation. Return a single answer to the caller and
stop.
```

- [ ] **Step 4: Write `config.py`**

Create `backend/app/services/ai/subagents/app_help/config.py`:

```python
"""Config builder for the app_help subagent (F-0089)."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.app_help.tools import (
    list_user_guide_pages,
    read_user_guide_page,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the app_help subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")
    return SubAgentConfig(
        name="app_help",
        description=(
            "Answers questions about Batchrite itself — how features work, "
            "where to find things, what terms mean, troubleshooting. "
            "Dispatch when the user asks 'how do I…', 'what is…', "
            "'where is…', or 'why can't I…' about the product. Does NOT "
            "answer questions about the user's own data (their uploaded "
            "documents, protocols, runs) — those route to research_library "
            "or the protocol/run tools."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=False,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [list_user_guide_pages, read_user_guide_page],
        },
    )
```

> `typically_needs_context=False`: help is fire-and-forget. This controls *execution mode* (sync dispatch, no mid-task clarification pause), not chat-history visibility. The parent agent retains full history and rewrites follow-ups into self-contained task descriptions before dispatching.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_app_help_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ai/subagents/app_help/prompt.md backend/app/services/ai/subagents/app_help/config.py backend/tests/unit/test_app_help_config.py
git commit -m "feat(F-0089): app_help subagent prompt and config builder"
```

---

### Task 5: Register the `app_help` subagent

`app_help` is registered **unconditionally**, alongside the other five
specialists — exactly how `protocol_knowledgebase` sits in the list. There
is no feature flag and no `_build_subagents` helper (grill Branch 7); the
registration is a static list entry, like every other subagent.

**Files:**
- Modify: `backend/app/services/ai/subagents/__init__.py`
- Modify: `backend/app/services/ai/chat_agent.py:26-32` (import) and `:182-188` (subagent list)
- Modify: `backend/app/services/ai/prompts/chat_agent.md`
- Modify: `backend/tests/unit/test_chat_agent_prompt_guardrail.py`

- [ ] **Step 1: Register the `app_help` package in `subagents/__init__.py`**

Edit `backend/app/services/ai/subagents/__init__.py` — add `app_help` to both the import and `__all__`:

```python
"""Chat agent subagent registry.

protocol_builder is legacy — unregistered in chat_agent.py but kept on
disk this cycle.
"""

from . import (
    app_help,
    protocol_builder,
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)

__all__ = [
    "app_help",
    "protocol_builder",
    "protocol_creator",
    "protocol_editor",
    "protocol_knowledgebase",
    "research_library",
    "run_planner",
]
```

- [ ] **Step 2: Add `app_help` to the `subagents` list in `chat_agent.py`**

In `backend/app/services/ai/chat_agent.py`, add `app_help` to the subagent import block (the existing `from app.services.ai.subagents import (...)` near line 26):

```python
from app.services.ai.subagents import (
    app_help,
    protocol_creator,
    protocol_editor,
    protocol_knowledgebase,
    research_library,
    run_planner,
)
```

Then append `app_help.build(subagent_model)` to the inline `subagents = [...]` list inside the `if key not in _AGENT_CACHE:` block (lines ~182-188):

```python
        subagents = [
            research_library.build(subagent_model),
            protocol_creator.build(creation_model),
            protocol_editor.build(editing_model),
            run_planner.build(subagent_model),
            protocol_knowledgebase.build(subagent_model),
            app_help.build(subagent_model),
        ]
```

The downstream tool-wrapping loop (`for sub in subagents: ...`, lines ~192-197) is unchanged.

- [ ] **Step 3: Verify the subagent constructs**

Run:
```bash
cd backend && python -c "from app.services.ai.subagents import app_help; print(app_help.build('openai:gpt-4.1-mini')['name'])"
```
Expected: prints `app_help`.

- [ ] **Step 4: Add the `app_help` dispatch entry to `chat_agent.md`**

In `backend/app/services/ai/prompts/chat_agent.md`, add `app_help` to the specialist list (after the `run_planner` line, ~line 11):

```markdown
- `app_help` — questions about Batchrite the product itself: how features work, where pages are, what terms mean, troubleshooting.
```

Then add a guardrail block after the `## External protocols (OpenWetWare)` section (so it sits alongside the other subagent guidance — search for the existing `## Skill: new-protocol` block and place this just above it):

```markdown
## Subagent: app_help

Dispatch `app_help` for questions about Batchrite the product: how
features work, where pages live, what terms mean, troubleshooting.
Examples: "how do I publish a protocol?", "what's the difference between
an experiment and a run?", "why is my chat sidebar empty?", "where do I
add equipment?".

Do NOT dispatch `app_help` for questions about the user's own data —
their uploaded documents, their specific protocols, their runs. Route
those to `research_library` or the protocol/run subagents.
```

- [ ] **Step 5: Extend the prompt-drift guardrail test**

`backend/tests/unit/test_chat_agent_prompt_guardrail.py` runs content-level assertions on `chat_agent.md` so prompt edits can't silently drop a contract (existing tests assert things like `assert "[skill:" in text` and `assert "## Skill: new-protocol" in text`). Open the file, follow its existing pattern for loading the prompt text, and add a test asserting the `app_help` contract:

- the specialist line — assert `` "`app_help`" `` is in the prompt text
- the dispatch block — assert `"## Subagent: app_help"` is in the text
- the negative-routing rule — assert `"own data"` is in the text

- [ ] **Step 6: Run the guardrail test**

Run: `cd backend && pytest tests/unit/test_chat_agent_prompt_guardrail.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ai/subagents/__init__.py backend/app/services/ai/chat_agent.py backend/app/services/ai/prompts/chat_agent.md backend/tests/unit/test_chat_agent_prompt_guardrail.py
git commit -m "feat(F-0089): register app_help subagent and chat-agent dispatch entry"
```

---

## Phase 3 — Page-context awareness

### Task 6: Backend — `current_route` schema field and `[page:<route>]` prefix

**Files:**
- Modify: `backend/app/schemas/chat.py:15-17`
- Modify: `backend/app/services/ai/send_message.py:177-204`
- Modify: `backend/app/api/endpoints/chat.py:262-269`
- Test: `backend/tests/unit/test_send_message_streaming.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_send_message_streaming.py`:

```python
async def _fake_run_capturing(captured: dict):
    """A fake agent.run that records the prompt it was given."""

    async def _run(*args, event_stream_handler=None, **kwargs):
        captured["prompt"] = args[0]
        result = MagicMock()
        result.output = "ok"
        result.all_messages.return_value = []
        return result

    return _run


async def _drain_streaming(db, session, content, **kwargs):
    from app.services.ai.send_message import send_message_streaming

    captured: dict = {}
    run_fn = await _fake_run_capturing(captured)
    cmr_patch, csr_patch = _patch_schema_serialization()
    with (
        patch(
            "app.services.ai.send_message.build_chat_agent",
            new_callable=AsyncMock,
        ) as mock_build,
        patch(
            "app.services.ai.send_message.CompactionState",
            return_value=CompactionState(),
        ),
        patch("app.services.ai.send_message.ModelMessagesTypeAdapter"),
        patch("app.services.ai.send_message.sanitize_output", return_value="ok"),
        cmr_patch,
        csr_patch,
    ):
        fake_agent = MagicMock()
        fake_agent.run = run_fn
        mock_build.return_value = fake_agent
        [
            ev
            async for ev in send_message_streaming(
                db, session, content, **kwargs
            )
        ]
    return captured, db


def _fresh_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_current_route_prepends_page_marker():
    """current_route prepends [page:<route>] to the model-visible prompt."""
    captured, db = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "how do I publish this?",
        user_id=uuid.uuid4(),
        is_org_admin=False,
        current_route="/protocols/abc/edit",
    )
    assert captured["prompt"] == (
        "[page:/protocols/abc/edit] how do I publish this?"
    )
    # Persisted user message keeps the clean text.
    user_msg = db.add.call_args_list[0].args[0]
    assert user_msg.content == "how do I publish this?"


@pytest.mark.asyncio
async def test_no_route_means_no_prefix():
    """Absent current_route leaves the prompt unprefixed."""
    captured, _ = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "hello",
        user_id=uuid.uuid4(),
        is_org_admin=False,
    )
    assert captured["prompt"] == "hello"


@pytest.mark.asyncio
async def test_skill_marker_precedes_page_marker():
    """[skill:<id>] stays first so 'message begins with [skill:' holds."""
    captured, _ = await _drain_streaming(
        _fresh_db(),
        _make_session(),
        "draft a protocol",
        user_id=uuid.uuid4(),
        is_org_admin=False,
        skill_id="new-protocol",
        current_route="/protocols",
    )
    assert captured["prompt"] == (
        "[skill:new-protocol] [page:/protocols] draft a protocol"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_send_message_streaming.py -k "route or marker" -v`
Expected: FAIL — `send_message_streaming() got an unexpected keyword argument 'current_route'`.

- [ ] **Step 3: Add `current_route` to the request schema**

In `backend/app/schemas/chat.py`, extend `ChatMessageCreate`:

```python
class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    skill_id: Optional[str] = None
    current_route: Optional[str] = Field(default=None, max_length=512)
```

> `max_length=512`: `current_route` is a client-supplied string prepended into the LLM prompt. A real route never approaches 512 chars; the cap is cheap hardening against a malformed/abusive client.

- [ ] **Step 4: Thread `current_route` through `send_message_streaming`**

In `backend/app/services/ai/send_message.py`, update the signature (line ~177) and docstring:

```python
async def send_message_streaming(
    db: AsyncSession,
    session: ChatSession,
    user_content: str,
    user_id: UUID,
    is_org_admin: bool,
    skill_id: str | None = None,
    current_route: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
```

Replace the `model_visible_content` assignment (lines ~202-204) with:

```python
    # Compose the model-visible content. The clean ``user_content`` is what
    # gets persisted; ``model_visible_content`` is what the agent.run prompt
    # carries. Markers reach the LLM and land in the serialized history for
    # turn N+1. The [skill:<id>] marker stays first so the chat-agent prompt
    # rule "if a message begins with [skill:...]" still holds when a
    # [page:<route>] marker (F-0089) is also present.
    markers = ""
    if skill_id:
        markers += f"[skill:{skill_id}] "
    if current_route:
        markers += f"[page:{current_route}] "
    model_visible_content = (
        f"{markers}{user_content}" if markers else user_content
    )
```

- [ ] **Step 5: Pass `current_route` from the endpoint**

In `backend/app/api/endpoints/chat.py`, in `stream_chat_message`'s `_sse_iter` (the `send_message_streaming(...)` call, lines ~262-269), add the argument:

```python
            async for event in send_message_streaming(
                db,
                session,
                body.content,
                user_id=current_user.id,
                is_org_admin=is_org_admin,
                skill_id=body.skill_id,
                current_route=body.current_route,
            ):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_send_message_streaming.py -v`
Expected: PASS (existing streaming tests + 3 new prefix tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/chat.py backend/app/services/ai/send_message.py backend/app/api/endpoints/chat.py backend/tests/unit/test_send_message_streaming.py
git commit -m "feat(F-0089): page-context [page:<route>] prefix on chat sends"
```

---

### Task 7: Frontend — attach `current_route` to the send body

**Files:**
- Modify: `frontend/src/lib/chat-store.svelte.ts:490-494`
- Test: `frontend/src/lib/chat-store.test.ts:419-497`

- [ ] **Step 1: Update the failing tests**

In `frontend/src/lib/chat-store.test.ts`, the two existing `capturedBody` assertions will start failing once the store attaches `current_route`. Update them now (jsdom's default `window.location.pathname` is `/`):

Line ~452 — change:
```typescript
        expect(capturedBody).toEqual({ content: 'draft me a protocol', skill_id: 'new-protocol' });
```
to:
```typescript
        expect(capturedBody).toEqual({ content: 'draft me a protocol', skill_id: 'new-protocol', current_route: '/' });
```

Line ~496 — change:
```typescript
        expect(capturedBody).toEqual({ content: 'hello' });
```
to:
```typescript
        expect(capturedBody).toEqual({ content: 'hello', current_route: '/' });
```

Then add a dedicated test after the `clearActiveSkill` test (after line ~497, inside the same `describe` block):

```typescript
    it('sendMessage attaches current_route from window.location', async () => {
        store.__test_setActiveSession({
            id: 'S1', messages: [], title: 'New Chat', created_at: '2026-01-01',
            user_id: 'U1', org_id: 'O1', ai_message_history: null,
        } as never);

        const original = window.location.pathname;
        window.history.pushState({}, '', '/protocols/abc-123/edit');

        let capturedBody: Record<string, unknown> | null = null;
        vi.spyOn(sse, 'streamSse').mockImplementation(
            async (_ep, body, cb) => {
                capturedBody = body as Record<string, unknown>;
                cb({
                    type: 'done',
                    user_message: { id: 'u1', session_id: 'S1', role: 'user', content: 'how does this work?', metadata_: null, created_at: '2026-01-01' },
                    assistant_message: { id: 'a1', session_id: 'S1', role: 'assistant', content: 'ok', metadata_: null, created_at: '2026-01-01' },
                    sources: [],
                });
            },
        );

        store.setMessageInput('how does this work?');
        await store.sendMessage();
        window.history.pushState({}, '', original);

        expect(capturedBody).toEqual({
            content: 'how does this work?',
            current_route: '/protocols/abc-123/edit',
        });
    });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && CI=true npm run test -- chat-store`
Expected: FAIL — the new test and the two updated assertions all fail (`current_route` not yet attached).

- [ ] **Step 3: Attach `current_route` in `sendMessage`**

In `frontend/src/lib/chat-store.svelte.ts`, in `sendMessage`, update the body construction (lines ~491-494):

```typescript
        const body: Record<string, string> = {
            content,
            // F-0089: page-context awareness — the chat agent prepends a
            // [page:<route>] marker so it can disambiguate vague questions
            // ("how does this work?") against the route the user is viewing.
            current_route: window.location.pathname,
        };
        if (skillId) {
            body.skill_id = skillId;
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && CI=true npm run test -- chat-store`
Expected: PASS (all chat-store tests).

- [ ] **Step 5: Type-check**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/chat-store.svelte.ts frontend/src/lib/chat-store.test.ts
git commit -m "feat(F-0089): send current_route with chat messages"
```

---

### Task 8: Parent prompt — explain the `[page:<route>]` marker

**Files:**
- Modify: `backend/app/services/ai/prompts/chat_agent.md`

- [ ] **Step 1: Add the page-context paragraph**

In `backend/app/services/ai/prompts/chat_agent.md`, find the `### Prefix-based activation` section (the `[skill:<skill_id>]` block, ~line 158). Add a new subsection immediately after the two `[skill:...]` paragraphs (before `## Skill: new-protocol`):

```markdown
### Page context

A user message may contain a `[page:<route>]` marker (for example
`[page:/protocols/abc-123/edit]`). It is injected by the UI and means the
user is currently viewing that route in the app. Use it to disambiguate
vague questions like "how does this work?" or "what can I do here?".

When you dispatch `app_help` for such a question, include the route in the
task description so the subagent can pick the page covering that surface —
for example `task("app_help", "User is on /protocols/abc/edit and asks
how publishing works")`.

The `[page:<route>]` marker is for your eyes only. Do not echo it back to
the user or mention the brackets. A message can carry both a
`[skill:<id>]` and a `[page:<route>]` marker; `[skill:<id>]` always comes
first.
```

- [ ] **Step 2: Extend the prompt-drift guardrail test**

In `backend/tests/unit/test_chat_agent_prompt_guardrail.py`, following its existing pattern for loading the prompt text, add a test asserting the page-context contract:

- `assert "[page:" in text`
- `assert "### Page context" in text`

- [ ] **Step 3: Run the guardrail test**

Run: `cd backend && pytest tests/unit/test_chat_agent_prompt_guardrail.py -v`
Expected: PASS.

- [ ] **Step 4: Verify the prompt still loads**

Run:
```bash
cd backend && python -c "from app.services.ai.chat_agent import _CHAT_PROMPT; print(len(_CHAT_PROMPT))"
```
Expected: prints a positive integer (the prompt file reads without error).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai/prompts/chat_agent.md backend/tests/unit/test_chat_agent_prompt_guardrail.py
git commit -m "docs(F-0089): document [page:<route>] marker in chat agent prompt"
```

---

## Phase 4 — Corpus authoring

Phase 4 is **one task per page** plus a shared authoring recipe (grill
Branch 6). Task 9 states the recipe in full and applies it once;
Tasks 10–18 each author one page by following that recipe. The page set
below is the *expected* corpus — `docs/user-guide/README.md` produced in
Task 1 is authoritative if the audit found a different set.

### Task 9: Authoring recipe + `getting-started.md`

This task defines the **authoring recipe** that Tasks 10–18 follow, and
applies it once to produce the first page, `getting-started.md`. The
recipe is stated here in full and is never repeated per page.

**Files:**
- Create: `docs/user-guide/getting-started.md`
- Modify: `docs/user-guide/README.md`

#### The recipe (Tasks 10–18 each follow these six steps)

Corpus pages are **authored from the live frontend**, not pre-written in
this plan (grill Branch 5). Guessing a button label or a navigation path
produces a confidently-wrong help answer — the exact failure mode this
feature exists to avoid. So every page task:

1. **Identify the route(s)** the page documents.
2. **Read the real components** for that surface (each task names the
   directories). Note the actual page titles, button labels, menu item
   names, and tab names — copy them verbatim into the prose.
3. **Write the page** using the Template below — frontmatter values and
   the section list are given per task.
4. **Verify frontmatter parses** with the single-page check below.
5. **Add the page's line** to the `## Pages` list in
   `docs/user-guide/README.md`.
6. **Commit.**

Authoring rules (also recorded in `README.md`): end-user voice, second
person ("You can…"); no developer jargon, no internal file paths in
user-facing prose; ~150–500 words; document only shipped, on-by-default
behavior.

**Template** — every page matches this shape:

```markdown
---
title: <Human-readable page title>
summary: <One sentence — what this feature is, used by the help index>
keywords: [<lowercase>, <search>, <terms>]
---

# <Title>

<Short overview paragraph — what this feature is and who uses it.>

## What you can do

- <feature bullet — answers "what can X do?">
- <feature bullet>
- <feature bullet>

## How to <task>

<numbered step-by-step>

## How to <another task>

<numbered step-by-step>
```

The `## What you can do` bullets answer feature-discovery questions; the
`## How to …` sections answer task questions. Both live in the same file.

**Single-page frontmatter check** — substitute the page filename for
`PAGE.md`:

```bash
cd backend && python -c "
import yaml, pathlib
f = pathlib.Path('../docs/user-guide/PAGE.md')
raw = f.read_text()
assert raw.startswith('---'), f
meta = yaml.safe_load(raw.split('---', 2)[1])
assert meta.get('title') and meta.get('summary') and meta.get('keywords'), meta
print('OK', f)
"
```

#### Apply the recipe to `getting-started.md`

- [ ] **Step 1: Read the navigation and layout components**

Run:
```bash
ls frontend/src/routes
ls frontend/src/lib/components/layout/
```
Read `frontend/src/routes/+layout.svelte` and the `layout/` nav
components. Note the real top-level area names, how the user menu works,
and how the chat assistant (FAB / sidebar) is opened.

- [ ] **Step 2: Write `docs/user-guide/getting-started.md`**

Frontmatter:
- `title`: Getting started with Batchrite
- `summary`: What Batchrite is and how to find your way around the app.
- `keywords`: [getting started, overview, navigation, help, chat assistant]

Sections and what each must answer:
- Overview — Batchrite is a Laboratory Execution System (LES) for biotech
  process development scientists; a tablet-friendly digital lab notebook.
- `## What you can do` — the main areas of the app (projects, protocols,
  runs/experiments, library, sites & equipment, settings), in end-user
  terms.
- `## How to find your way around` — navigating between the main areas
  using the real nav labels read in Step 1.
- `## How to get help` — opening the chat assistant and asking product
  questions.

- [ ] **Step 3: Verify frontmatter parses**

Run the single-page frontmatter check above with `PAGE.md` =
`getting-started.md`. Expected: `OK`.

- [ ] **Step 4: Add the page to the README index**

In `docs/user-guide/README.md`, under `## Pages`, add:
```markdown
- `getting-started.md` — What Batchrite is and how to navigate the app.
```

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/getting-started.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — getting started"
```

---

### Task 10: User-guide page — `protocols-and-editor.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/protocols-and-editor.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/routes` — locate the protocol-editor route and the project routes
- `frontend/src/lib/components/protocol/` — editor canvas, nodes, inspector, sidebar
- `frontend/src/lib/components/project/` — where protocols are created and listed

**Frontmatter:**
- `title`: Protocols and the protocol editor
- `summary`: How to create, edit, validate, and publish protocols using the visual editor.
- `keywords`: [protocol, editor, swimlane, unit op, graph, publish, validate]

**Sections and what each must answer:**
- Overview — a protocol is a reusable template for a lab process, built on
  a visual canvas of connected unit operations; running it snapshots an
  experiment so the template stays clean.
- `## What you can do` — add unit operations, connect steps, group into
  swimlanes, set parameters/durations in the inspector, switch layout,
  validate, publish.
- `## How to create a protocol` — start from the real entry point (see note).
- `## How to validate and publish a protocol`.
- `## How to edit a step`.

> **Page-specific note — navigation correction (grill Branch 4):** there
> is **no** top-level `/protocols` list route. Protocols are reached and
> created from **within a project** (`/projects` → open a project). The
> "How to create a protocol" steps MUST start from opening a project — do
> not write "open the Protocols page." Confirm the exact entry point and
> button label in the `project/` components before writing.

- [ ] **Step 1: Read the source components; list the real page titles, button labels, and the protocol-creation entry point.**
- [ ] **Step 2: Write `docs/user-guide/protocols-and-editor.md`** per the recipe Template and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `protocols-and-editor.md`. Expected: `OK`.
- [ ] **Step 4: Add `` - `protocols-and-editor.md` — … `` to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/protocols-and-editor.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — protocols and editor"
```

---

### Task 11: User-guide page — `experiments-and-runs.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/experiments-and-runs.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/run/` — run execution surfaces (edit mode, history, role wizard)
- `frontend/src/lib/components/project/` — runs are launched from within a project
- `frontend/src/routes` — locate the run/experiment routes

**Frontmatter:**
- `title`: Experiments and runs
- `summary`: How runs work — planning, executing, completing, and recording deviations.
- `keywords`: [experiment, run, execution, deviation, complete, step]

**Sections and what each must answer:**
- Overview — the distinction between a **protocol** (the reusable
  template), an **experiment** (the snapshot taken when you run it), and a
  **run** (the execution itself).
- `## What you can do` — plan a run, start it, execute steps, record data
  and equipment usage, record deviations, complete the run.
- `## How to plan a run`.
- `## How to execute and complete a run`.

> **Page-specific note:** the protocol / experiment / run distinction is
> the most-confused term set in the product. State it precisely — confirm
> the exact meanings against the run components and the model definitions
> before writing.

- [ ] **Step 1: Read the source components; list the real labels and the run-creation entry point.**
- [ ] **Step 2: Write `docs/user-guide/experiments-and-runs.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `experiments-and-runs.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/experiments-and-runs.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — experiments and runs"
```

---

### Task 12: User-guide page — `library-and-documents.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/library-and-documents.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/document-refinement/` — library refinement surfaces
- `frontend/src/lib/components/media/` — upload, PDF, image handling
- `frontend/src/routes` — locate the library routes

**Frontmatter:**
- `title`: Document library
- `summary`: Uploading documents and how the chat assistant searches them.
- `keywords`: [library, documents, upload, search, sources]

**Sections and what each must answer:**
- Overview — the library holds your organization's documents; the chat
  assistant can search them and cite results.
- `## What you can do` — upload documents, the supported document types,
  search the library, get assistant answers cited to your documents.
- `## How to upload a document`.
- `## How to search the library`.

- [ ] **Step 1: Read the source components; list the real labels and supported document types.**
- [ ] **Step 2: Write `docs/user-guide/library-and-documents.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `library-and-documents.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/library-and-documents.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — document library"
```

---

### Task 13: User-guide page — `chat-agent.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/chat-agent.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/ai/` — chat and agent UX

**Frontmatter:**
- `title`: The chat assistant
- `summary`: What the in-app chat assistant can do and how to use it.
- `keywords`: [chat, assistant, ai, skills, sources, help]

**Sections and what each must answer:**
- Overview — what the assistant is and the kinds of things it helps with.
- `## What you can do` — ask product questions, search your documents,
  draft protocols, use skill chips, get answers cited to sources.
- `## How to ask a question`.
- `## How skills work` — what a skill chip is and when to use one.

> **Page-specific note:** explain the difference between *product help*
> (questions about Batchrite itself) and *document search* (questions
> about the user's own uploaded content) — this mirrors the `app_help`
> vs `research_library` routing.

- [ ] **Step 1: Read the source components; list the real labels, skill chips, and chat entry points.**
- [ ] **Step 2: Write `docs/user-guide/chat-agent.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `chat-agent.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/chat-agent.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — the chat assistant"
```

---

### Task 14: User-guide page — `glp-and-signoffs.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/glp-and-signoffs.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/run/` and `protocol/` — sign-off surfaces
- `frontend/src/lib/components/analytics/` — audit trail / version history
- `frontend/src/lib/components/settings/` — where GLP mode is toggled

**Frontmatter:**
- `title`: GLP sign-offs
- `summary`: GLP mode, sign-offs, QAU independence, and approval gating.
- `keywords`: [glp, signoff, qau, approval, compliance, audit]

**Sections and what each must answer:**
- Overview — what GLP mode is and why it exists.
- `## What you can do` — sign off on protocols and runs, view the audit
  trail, see sign-off status.
- `## How to sign off`.
- `## How approval gating works` — QAU independence and how approval
  gating affects starting runs.

- [ ] **Step 1: Read the source components; list the real labels, sign-off controls, and status indicators.**
- [ ] **Step 2: Write `docs/user-guide/glp-and-signoffs.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `glp-and-signoffs.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/glp-and-signoffs.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — GLP sign-offs"
```

---

### Task 15: User-guide page — `ai-configuration.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/ai-configuration.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/settings/` — the AI configuration settings tab

**Frontmatter:**
- `title`: AI configuration
- `summary`: Where AI settings live and how to choose a provider and model.
- `keywords`: [ai, configuration, provider, model, settings, tier]

**Sections and what each must answer:**
- Overview — Batchrite uses AI for several capabilities; this is where you
  configure them.
- `## What you can do` — choose a provider and model, see what each AI
  capability does, understand what changes by subscription tier.
- `## How to configure an AI provider`.

- [ ] **Step 1: Read the source components; list the real labels, the AI capabilities shown, and tier-dependent behavior.**
- [ ] **Step 2: Write `docs/user-guide/ai-configuration.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `ai-configuration.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/ai-configuration.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — AI configuration"
```

---

### Task 16: User-guide page — `org-roles-permissions.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/org-roles-permissions.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/settings/` — the members / roles settings tab

**Frontmatter:**
- `title`: Organizations, roles, and permissions
- `summary`: Organizations, member roles, and permission levels.
- `keywords`: [organization, roles, permissions, members, invite]

**Sections and what each must answer:**
- Overview — what an organization is and how members belong to it.
- `## What you can do` — invite members, assign roles, control access.
- `## The roles` — the available roles and what each can do.
- `## Permission levels` — view vs edit access on objects.
- `## How to invite a member`.

- [ ] **Step 1: Read the source components; list the real role names and permission-level labels.**
- [ ] **Step 2: Write `docs/user-guide/org-roles-permissions.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `org-roles-permissions.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/org-roles-permissions.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — organizations, roles, and permissions"
```

---

### Task 17: User-guide page — `sites-and-equipment.md`

Follow the six-step recipe in Task 9.

**Files:**
- Create: `docs/user-guide/sites-and-equipment.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/sites/` — sites management surfaces
- `frontend/src/lib/components/equipment/` — equipment table, form, attachments

**Frontmatter:**
- `title`: Sites and equipment
- `summary`: Registering sites and managing equipment, calibration, and expiry.
- `keywords`: [site, room, equipment, calibration, expiry, location]

**Sections and what each must answer:**
- Overview — sites and rooms describe where work happens; equipment is
  registered against them.
- `## What you can do` — register sites and rooms, add equipment, track
  calibration and expiry, select equipment during a run.
- `## How to register a site`.
- `## How to add equipment`.

- [ ] **Step 1: Read the source components; list the real labels for sites, rooms, equipment fields, and calibration/expiry.**
- [ ] **Step 2: Write `docs/user-guide/sites-and-equipment.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `sites-and-equipment.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/sites-and-equipment.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — sites and equipment"
```

---

### Task 18: User-guide page — `billing.md`

Follow the six-step recipe in Task 9. Billing was confirmed in Task 1's
audit as shipped on-by-default with no flag (grill Branch 4). If Task 1
found otherwise, skip this task and record the exclusion in `README.md`.

**Files:**
- Create: `docs/user-guide/billing.md`
- Modify: `docs/user-guide/README.md`

**Source — read for real labels and navigation:**
- `frontend/src/lib/components/settings/` — the billing settings tab
- `frontend/src/routes` — locate the billing route

**Frontmatter:**
- `title`: Billing and plans
- `summary`: Subscription plans, billing settings, and managing your subscription.
- `keywords`: [billing, subscription, plan, tier, invoice, payment]

**Sections and what each must answer:**
- Overview — Batchrite subscriptions and where billing is managed.
- `## What you can do` — view the current plan, see subscription tiers,
  manage the subscription.
- `## The subscription tiers` — the available tiers in end-user terms.
- `## How to manage your subscription`.

- [ ] **Step 1: Read the source components; list the real labels, tier names, and billing controls.**
- [ ] **Step 2: Write `docs/user-guide/billing.md`** per the recipe and the frontmatter/sections above.
- [ ] **Step 3: Verify frontmatter parses** — single-page check, `PAGE.md` = `billing.md`. Expected: `OK`.
- [ ] **Step 4: Add the page's line to `## Pages` in `README.md`.**
- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/billing.md docs/user-guide/README.md
git commit -m "docs(F-0089): user-guide page — billing and plans"
```

---

## Phase 5 — Integration tests and docs sync

### Task 19: Integration test — corpus quality guard

This test points `app_help`'s tools at the **real** `docs/user-guide` corpus authored in Phase 4 and asserts it is well-formed. It is the regression guard that a future corpus edit cannot silently break frontmatter or empty a page.

> **Note on scope:** the spec's testing section also described driving the full chat agent end-to-end ("send 'how do I create a protocol?' → assert `app_help` dispatched + citation"). This codebase's chat integration tests mock `send_message_streaming` with canned events (see `tests/integration/test_chat_stream_endpoint.py`) rather than running a real LLM, because a live-model assertion is flaky and costs money in CI. The testable equivalents are already covered: subagent registration and `chat_agent.md` prompt wiring by `test_chat_agent_prompt_guardrail.py` (Tasks 5, 8), the `[page:<route>]` prefix by `test_send_message_streaming.py` (Task 6), config resolution by `test_app_help_config.py` (Task 4), and tool behavior by `test_subagents_app_help.py` (Task 3). This task adds the remaining gap — real-corpus integrity.

**Files:**
- Create: `backend/tests/integration/test_app_help_corpus.py`

- [ ] **Step 1: Write the test**

Create `backend/tests/integration/test_app_help_corpus.py`:

```python
"""Integration test: the real docs/user-guide corpus is well-formed (F-0089).

Points the app_help tools at the actual corpus authored in Phase 4 and
asserts every page parses cleanly — no frontmatter fallbacks, no empty
bodies. Guards against a future corpus edit silently breaking a page.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from app.services.ai.subagents.app_help import tools as app_help_tools


@dataclass
class _FakeDeps:
    tool_calls: list


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.deps = _FakeDeps(tool_calls=[])
    return ctx


@pytest.mark.asyncio
async def test_real_corpus_lists_pages():
    """The shipped corpus has at least the core surfaces."""
    result = await app_help_tools.list_user_guide_pages(_ctx())
    assert result.total >= 5, "expected the authored user-guide corpus"
    # README is the human index — it must not surface as a help page.
    assert "README.md" not in {p.filename for p in result.pages}


@pytest.mark.asyncio
async def test_real_corpus_pages_have_complete_frontmatter():
    """Every shipped page has a non-empty title and summary."""
    result = await app_help_tools.list_user_guide_pages(_ctx())
    for page in result.pages:
        assert page.title, f"{page.filename} has no title"
        assert page.summary, f"{page.filename} has no summary"
        assert page.keywords, f"{page.filename} has no keywords"


@pytest.mark.asyncio
async def test_real_corpus_pages_are_readable_and_non_empty():
    """Every listed page reads back with a non-empty body."""
    listing = await app_help_tools.list_user_guide_pages(_ctx())
    for page in listing.pages:
        read = await app_help_tools.read_user_guide_page(
            _ctx(), page.filename
        )
        assert read.error is None, f"{page.filename}: {read.error}"
        assert len(read.content) > 50, f"{page.filename} body too short"
        assert read.content.startswith("#"), (
            f"{page.filename} body should start with a heading"
        )
```

- [ ] **Step 2: Run the test**

Run: `cd backend && pytest tests/integration/test_app_help_corpus.py -v`
Expected: PASS (3 tests). `settings.user_guide_dir` already resolves to the real repo-root `docs/user-guide` (Task 2's absolute default), so no monkeypatch is needed.

- [ ] **Step 3: Run the full backend AI suite as a regression check**

Run: `cd backend && pytest tests/unit/test_subagents_app_help.py tests/unit/test_app_help_config.py tests/unit/test_chat_agent_prompt_guardrail.py tests/unit/test_send_message_streaming.py tests/unit/test_tool_labels.py tests/integration/test_app_help_corpus.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_app_help_corpus.py
git commit -m "test(F-0089): integration guard for user-guide corpus integrity"
```

---

### Task 20: Documentation sync

> **Spec deviation — no feature flag.** Spec §4 called for a `CLAUDE.md` feature-flags row and a `settings.example.yaml` stanza. `app_help` ships unconditionally (grill Branch 7) — there is no flag to document, so those two edits are dropped. Only the subagents-tree note remains.

**Files:**
- Modify: `.claude/rules/backend-ai.md` (subagents directory tree)

- [ ] **Step 1: Note `app_help` in `.claude/rules/backend-ai.md`**

In `.claude/rules/backend-ai.md`, in the `subagents/` directory tree under "Package Layout", add an `app_help/` entry alongside the other subagent packages:

```
│   ├── app_help/        #   build(model) -> SubAgentConfig (F-0089)
│   │   ├── config.py    #   product Q&A from docs/user-guide/
│   │   └── tools.py     #   list_user_guide_pages, read_user_guide_page
```

- [ ] **Step 2: Verify nothing else references the corpus path incorrectly**

Run:
```bash
grep -rn 'user_guide_dir\|user-guide' backend/app .claude/rules/backend-ai.md
```
Expected: references are consistent — `settings.user_guide_dir` in `config.py` and `app_help/tools.py`, and the tree entry in `backend-ai.md`.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/backend-ai.md
git commit -m "docs(F-0089): note app_help subagent in backend-ai rules"
```

---

## Final verification

- [ ] **Backend lint:** `cd backend && black app tests && isort app tests && mypy app`
- [ ] **Backend tests:** `cd backend && pytest tests/unit/test_subagents_app_help.py tests/unit/test_app_help_config.py tests/unit/test_chat_agent_prompt_guardrail.py tests/unit/test_send_message_streaming.py tests/unit/test_tool_labels.py tests/integration/test_app_help_corpus.py tests/integration/test_chat_stream_endpoint.py -v`
- [ ] **Frontend tests:** `cd frontend && CI=true npm run test -- chat-store && npm run check`
- [ ] **Manual smoke:** restart the backend, open the chat FAB, ask "how do I publish a protocol?" — confirm a grounded answer with a `Source: …` line. Ask "how do I integrate with Salesforce?" — confirm the "email support@batchrite.com" phrasing and no fabricated citation. (`app_help` is always registered; no flag to set.)
- [ ] **Corpus accuracy spot-check (qa-verify):** for 2–3 user-guide pages, open the matching app surface in the browser and confirm the page's labels, button names, and navigation steps match what the UI actually shows. Phase 4 authors the corpus from frontend components, but components drift — this catches stale instructions before they reach users (grill Branch 5).

---

## Spec coverage map

| Spec section | Task(s) |
| --- | --- |
| §1 Corpus (`docs/user-guide/`, frontmatter, lenient parsing) | 1, 3, 9–18 |
| §2 Subagent package (`config.py`, `prompt.md`, `tools.py`, path safety, no caching) | 3, 4 |
| §3 Configuration (`user_guide_dir`) | 2 |
| §4 Feature flag (`AppHelpFeatureConfig`, gating, `settings.example.yaml`) | **Dropped** — see deviation; `app_help` is registered unconditionally |
| §5 Chat-agent registration (`__init__.py`, `chat_agent.py`, `chat_agent.md`) | 5 |
| §6 Page-context awareness (schema, `[page:<route>]` prefix, frontend, prompt) | 6, 7, 8 |
| Testing — unit (tools, config, tool labels, prefix) | 3, 4, 6 |
| Testing — registration / integration (prompt guardrail, real corpus) | 5, 8, 19 |
| Testing — frontend Vitest | 7 |
| Phase 1 feature audit | 1 |
| `backend-ai.md` subagents-tree note | 20 |

**Deliberate deviations from the spec, documented inline:**
- **No feature flag.** Spec §4 gated `app_help` behind `AppHelpFeatureConfig` with `CLAUDE.md`/`settings.example.yaml` plumbing. Per grill Branch 7, app help ships unconditionally — `app_help` is registered alongside the other five specialists in `chat_agent.py` (Task 5) and is always named in `chat_agent.md`. No flag, no config row, no env var.
- **Corpus authored from live frontend components.** Each Phase 4 page task reads the actual UI source (`frontend/src/lib/components/...`, routes) for real labels and navigation, and Final Verification adds a qa-verify browser spot-check (grill Branch 5) — rather than authoring pages from the spec's prose alone.
- **Phase 4 is one task per user-guide page plus a shared recipe.** Tasks 10–18 each author a single page against the six-step recipe stated in Task 9 (grill Branch 6), rather than one bulk corpus-authoring task — keeps each task a reviewable unit.
- `user_guide_dir` default is an absolute `parents[3]`-anchored path, not the spec's relative `"docs/user-guide"` (Task 2 Step 4) — a relative path resolves against the backend CWD and would miss the repo-root corpus.
- Test file paths are flat in `tests/unit/` / `tests/integration/` (`test_subagents_app_help.py`, `test_app_help_config.py`, `test_app_help_corpus.py`), matching this codebase's convention, not the spec's nested `tests/unit/services/ai/subagents/...` sketch.
- The spec's live-LLM "dispatch + citation" integration test is replaced by structural equivalents (prompt-drift guardrail, `[page:]` prefix, tool unit tests) plus a real-corpus integrity test (Task 19) — this codebase mocks `send_message_streaming` rather than running models in CI.
