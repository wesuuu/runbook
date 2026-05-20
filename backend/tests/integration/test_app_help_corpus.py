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
