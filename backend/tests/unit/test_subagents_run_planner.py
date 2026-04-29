"""Tests for run_planner stub."""

from app.services.ai.subagents.run_planner import build


def test_build_returns_placeholder_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "run_planner"
    assert (
        "(placeholder)" in cfg["instructions"].lower()
        or "not yet" in cfg["instructions"].lower()
    )
    assert cfg["agent_kwargs"].get("tools", []) == []
