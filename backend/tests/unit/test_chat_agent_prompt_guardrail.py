"""Tests that chat_agent.md contains the F-0089 skill activation rules.

These are content-level assertions on the prompt file. They guard against
silent drift — if someone removes the dispatch rule or the guardrail
block, the source-picker contract breaks without crashing anything.
"""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "app"
    / "services"
    / "ai"
    / "prompts"
    / "chat_agent.md"
)


def test_chat_agent_prompt_includes_skill_prefix_dispatch_rule() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert (
        "[skill:" in text
    ), "chat_agent.md must reference the [skill:<id>] prefix dispatch rule"
    assert (
        "load_skill" in text or "load that skill" in text
    ), "chat_agent.md must instruct the model to load the prefixed skill"


def test_chat_agent_prompt_includes_new_protocol_guardrail() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert (
        "## Skill: new-protocol" in text
    ), "chat_agent.md must contain the named guardrail section"
    # Anti-patterns enumerated so the model knows when NOT to load
    lower = text.lower()
    for keyword in ("summarize", "edits to an open protocol", "library lookups"):
        assert keyword in lower, f"Guardrail must list anti-pattern: {keyword}"
    # Positive triggers
    for keyword in ("draft", "create"):
        assert keyword in lower, f"Guardrail must list trigger word: {keyword}"


def test_chat_agent_prompt_includes_mid_flow_continuation_rule() -> None:
    """Turn 2 of the source-picker flow must not re-load the skill."""
    text = PROMPT_PATH.read_text(encoding="utf-8").lower()
    assert (
        "mid-flow" in text or "source picker" in text
    ), "Guardrail must instruct the model on multi-turn continuation"
    assert (
        "do not re-load" in text or "do not load it again" in text
    ), "Guardrail must explicitly forbid re-loading on the source-reply turn"


def test_chat_agent_prompt_includes_app_help_contract() -> None:
    """app_help specialist line, dispatch block, and negative-routing rule."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert (
        "`app_help`" in text
    ), "chat_agent.md must list app_help in the specialist bullet list"
    assert (
        "## Subagent: app_help" in text
    ), "chat_agent.md must contain the ## Subagent: app_help guardrail block"
    assert (
        "own data" in text
    ), "Guardrail must include the negative-routing rule referencing 'own data'"
