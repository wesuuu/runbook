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
