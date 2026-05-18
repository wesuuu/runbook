"""Tests that the new-protocol SKILL.md is well-formed and discoverable."""

from pathlib import Path

import pytest
import yaml

from pydantic_ai_skills import SkillsCapability

# backend/app/services/ai/skills/new-protocol/SKILL.md
SKILL_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "services"
    / "ai"
    / "skills"
    / "new-protocol"
    / "SKILL.md"
)


def test_skill_md_exists() -> None:
    assert SKILL_PATH.is_file(), f"SKILL.md missing at {SKILL_PATH}"


def test_skill_md_has_required_frontmatter() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must begin with YAML frontmatter"
    parts = text.split("---", 2)
    assert len(parts) >= 3, "Frontmatter is malformed"
    meta = yaml.safe_load(parts[1])
    assert meta["name"] == "new-protocol"
    assert isinstance(meta.get("description"), str) and meta["description"]
    assert isinstance(meta.get("icon"), str) and meta["icon"]


def test_skill_md_body_covers_four_sources() -> None:
    body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2]
    lower = body.lower()
    for keyword in ("library", "openwetware", "from scratch", "search all"):
        assert keyword in lower, f"SKILL.md body must mention '{keyword}'"


def test_skill_md_hard_fails_library_empty_with_redirect() -> None:
    """Library miss must offer a redirect to Search all, not silently fall through."""
    body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2].lower()
    assert "search all" in body
    assert "no matching library" in body or "no library matches" in body, (
        "Body must include the Library-empty redirect message"
    )


def test_skill_is_discovered_by_skills_capability() -> None:
    """pydantic_ai_skills must parse our SKILL.md.

    Discovery surface in pydantic-ai-skills 0.6.0 is `cap.toolset.skills`,
    a `dict[str, Skill]` keyed by skill name. The bare `cap.skills` attribute
    does not exist — see the grilling notes attached to F-0089.
    """
    cap = SkillsCapability(directories=[str(SKILL_PATH.parent.parent)])
    assert "new-protocol" in cap.toolset.skills
    skill = cap.toolset.skills["new-protocol"]
    assert skill.description
    assert skill.metadata.get("icon") == "file-plus"
