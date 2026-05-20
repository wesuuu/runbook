"""Unit tests for the app_help subagent (F-0089)."""

import logging
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services.ai.subagents.app_help import tools as app_help_tools


def test_user_guide_dir_points_at_repo_docs():
    """user_guide_dir resolves to the repo-root docs/user-guide directory."""
    path = Path(settings.user_guide_dir)
    assert path.name == "user-guide"
    assert path.parent.name == "docs"
    # Absolute so it resolves regardless of process CWD (backend/ at runtime).
    assert path.is_absolute()


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
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
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
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "zebra.md", _PAGE)
    _write(tmp_path, "alpha.md", _PAGE)

    result = await app_help_tools.list_user_guide_pages(_ctx())

    assert [p.filename for p in result.pages] == ["alpha.md", "zebra.md"]


@pytest.mark.asyncio
async def test_list_skips_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "README.md", "# index\n")
    _write(tmp_path, "protocols.md", _PAGE)

    result = await app_help_tools.list_user_guide_pages(_ctx())

    assert [p.filename for p in result.pages] == ["protocols.md"]


@pytest.mark.asyncio
async def test_list_frontmatter_fallback_logs_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
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
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    result = await app_help_tools.list_user_guide_pages(_ctx())
    assert result.total == 0
    assert result.pages == []


@pytest.mark.asyncio
async def test_read_strips_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "protocols.md", _PAGE)

    result = await app_help_tools.read_user_guide_page(_ctx(), "protocols.md")

    assert result.error is None
    assert result.title == "Protocols and the protocol editor"
    assert result.content.startswith("# Protocols and the protocol editor")
    assert "---" not in result.content


@pytest.mark.asyncio
async def test_read_path_traversal_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    result = await app_help_tools.read_user_guide_page(_ctx(), "../../etc/passwd")
    assert result.error is not None
    assert result.content == ""


@pytest.mark.asyncio
async def test_read_missing_file_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    result = await app_help_tools.read_user_guide_page(_ctx(), "nonexistent.md")
    assert result.error is not None


@pytest.mark.asyncio
async def test_read_non_markdown_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "notes.txt", "plain text")
    result = await app_help_tools.read_user_guide_page(_ctx(), "notes.txt")
    assert result.error is not None


# ─── load_user_guide_text (corpus inlining) ────────────────────────────────


def test_load_user_guide_text_concatenates_bodies(tmp_path, monkeypatch):
    """Every page body is concatenated; frontmatter is stripped."""
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "alpha.md", _PAGE)
    _write(tmp_path, "zebra.md", _PAGE)

    text = app_help_tools.load_user_guide_text()

    # Frontmatter stripped: only the markdown body survives.
    assert "---" not in text
    assert "title: Protocols" not in text
    # Both pages present, each starting at its heading.
    assert text.count("# Protocols and the protocol editor") == 2


def test_load_user_guide_text_skips_readme(tmp_path, monkeypatch):
    """README.md is the human index and must not be inlined."""
    monkeypatch.setattr(app_help_tools.settings, "user_guide_dir", str(tmp_path))
    _write(tmp_path, "README.md", "# index\n\nHuman-facing index.\n")
    _write(tmp_path, "protocols.md", _PAGE)

    text = app_help_tools.load_user_guide_text()

    assert "Human-facing index" not in text
    assert "# Protocols and the protocol editor" in text


def test_load_user_guide_text_missing_directory_returns_empty(
    tmp_path, monkeypatch
):
    """An absent corpus directory yields an empty string, not an error."""
    monkeypatch.setattr(
        app_help_tools.settings,
        "user_guide_dir",
        str(tmp_path / "does-not-exist"),
    )
    assert app_help_tools.load_user_guide_text() == ""
