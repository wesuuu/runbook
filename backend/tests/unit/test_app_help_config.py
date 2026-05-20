"""Tests for the app_help subagent config builder (F-0089)."""

from app.services.ai.subagents.app_help.config import build


def test_build_returns_named_subagent_config():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["name"] == "app_help"
    assert "Batchrite" in cfg["description"]
    # The description must steer the parent away from user-data questions.
    assert "does not" in cfg["description"].lower()


def test_build_inlines_corpus_not_tools():
    cfg = build("openai:gpt-4.1-mini")
    # The corpus is inlined into the system prompt — no retrieval tools.
    assert "tools" not in cfg["agent_kwargs"]
    instructions = cfg["instructions"]
    preamble, marker, corpus = instructions.partition(
        "=== BATCHRITE USER GUIDE ==="
    )
    assert marker, "expected the user-guide marker between preamble and corpus"
    assert "Batchrite" in preamble
    assert corpus.strip(), "expected the user-guide corpus inlined after marker"


def test_build_uses_passed_model():
    cfg = build("openai:gpt-4.1-mini")
    assert cfg["model"] == "openai:gpt-4.1-mini"
