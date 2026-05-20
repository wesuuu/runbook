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
    assert (
        "no matching library" in body or "no library matches" in body
    ), "Body must include the Library-empty redirect message"


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


@pytest.mark.asyncio
async def test_chat_agent_includes_skills_capability(monkeypatch) -> None:
    """build_chat_agent must register a SkillsCapability that discovers new-protocol.

    Verified in pydantic-ai 1.75 via REPL exploration:
      - Multiple capabilities compose into a `CombinedCapability` at
        `agent._root_capability` (private — see comment below).
      - That CombinedCapability exposes `.capabilities` (list of the
        per-capability instances we passed in).
      - SkillsCapability discovery lives at `cap.toolset.skills`
        (a `dict[str, Skill]`), NOT at `cap.skills` (which doesn't exist).

    Follows the construction-only mocking pattern used by
    test_chat_agent_factory.py so this test does not require a Pro+ org or a
    real LLM provider.
    """
    import os
    from unittest.mock import MagicMock, patch

    from pydantic_ai_skills import SkillsCapability

    from app.services.ai.chat_agent import _reset_cache_for_tests, build_chat_agent
    from app.services.ai.runtime.compaction import CompactionState

    db = MagicMock()
    org_id = MagicMock()
    state = CompactionState()

    fake_model = "openai:gpt-4.1-mini"

    async def fake_get_model(cap, db_, org_id=None):
        return fake_model

    async def fake_get_context_window(cap, db_, org_id=None):
        return 100_000

    _reset_cache_for_tests()
    with patch("app.services.ai.chat_agent.get_model", fake_get_model), patch(
        "app.services.ai.chat_agent.get_context_window", fake_get_context_window
    ), patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-unit"}):
        agent = await build_chat_agent(db, org_id, state)

    # NOTE: _root_capability is a private API in pydantic-ai 1.75. If a
    # future minor bump renames it, this test fails loudly — update the
    # one access path and move on. The behavior-only alternative (asserting
    # `load_skill` is a callable tool) is more durable but more elaborate;
    # the brittleness here is bounded and acceptable.
    caps = agent._root_capability.capabilities
    skill_caps = [c for c in caps if isinstance(c, SkillsCapability)]
    assert len(skill_caps) == 1, "Exactly one SkillsCapability must be registered"
    assert "new-protocol" in skill_caps[0].toolset.skills
