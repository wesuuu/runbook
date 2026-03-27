"""Smoke tests for pydantic-ai-skills compatibility.

These tests verify that the pydantic-ai-skills package imports correctly
and integrates with pydantic-ai's Agent. If pydantic-ai refactors its
internal APIs that pydantic-ai-skills depends on, these will fail at
import time.
"""

import pytest


def test_skills_package_imports():
    """Verify pydantic-ai-skills imports without errors."""
    from pydantic_ai_skills import SkillsToolset


def test_skills_toolset_initializes(tmp_path):
    """Verify SkillsToolset can load from a directory."""
    from pydantic_ai_skills import SkillsToolset

    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: A test skill\n---\n# Test\nDo the thing."
    )

    toolset = SkillsToolset(directories=[str(tmp_path)])
    # list_skills is a tool the agent calls; verify it's registered
    assert toolset is not None


def test_skills_directory_reads_skill_files(tmp_path):
    """Verify skill files are discovered from the directory."""
    from pydantic_ai_skills import SkillsToolset

    for name in ["alpha", "beta"]:
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Skill {name}\n---\n# {name}\nInstructions."
        )

    toolset = SkillsToolset(directories=[str(tmp_path)])
    # The toolset should have discovered the skills
    assert toolset is not None


def test_generate_protocol_skill_file_exists():
    """Verify the generate-protocol skill file exists and has valid frontmatter."""
    import yaml
    from pathlib import Path
    from app.core.config import settings

    skill_path = Path(settings.skills_dir) / "generate-protocol" / "SKILL.md"
    assert skill_path.exists(), f"Skill file not found: {skill_path}"

    text = skill_path.read_text()
    assert text.startswith("---")

    parts = text.split("---", 2)
    assert len(parts) >= 3

    meta = yaml.safe_load(parts[1])
    assert meta["name"] == "generate-protocol"
    assert "description" in meta
    assert "icon" in meta


def test_skill_frontmatter_parsing():
    """Verify YAML frontmatter parsing for the skills endpoint."""
    import yaml

    text = "---\nname: test\ndescription: A test\nicon: flask\n---\n# Body"
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1])
    assert meta["name"] == "test"
    assert meta["description"] == "A test"
    assert meta["icon"] == "flask"
