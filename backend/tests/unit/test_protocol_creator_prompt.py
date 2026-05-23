"""Static assertions over the protocol_creator subagent prompt."""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app/services/ai/subagents/protocol_creator/prompt.md"
)


def _read_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_prompt_does_not_instruct_uuid_url_construction():
    """The buggy template /protocols/<protocol_id> must not appear."""
    prompt = _read_prompt()
    assert "/protocols/<protocol_id>" not in prompt


def test_prompt_references_protocol_markdown_link():
    """The end-of-turn section must point the model at the
    pre-formatted protocol_markdown_link from the tool result."""
    prompt = _read_prompt()
    assert "protocol_markdown_link" in prompt


def test_prompt_includes_fallback_for_missing_link():
    """If protocol_markdown_link is None, the model must know what to do."""
    prompt = _read_prompt()
    assert "If `protocol_markdown_link` is `None`" in prompt or \
        "If protocol_markdown_link is None" in prompt
