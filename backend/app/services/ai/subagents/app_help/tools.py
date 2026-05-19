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
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
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

    if not filename or "\x00" in filename or not _FILENAME_RE.match(filename):
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
