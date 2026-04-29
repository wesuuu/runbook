"""Tests for the extracted output sanitization utility."""
from app.services.ai.runtime.sanitize import sanitize_output


def test_strips_think_blocks():
    text = "Hello <think>internal</think> world"
    assert sanitize_output(text) == "Hello  world"


def test_strips_thought_process_section():
    text = "**Thought Process:**\nlots of reasoning\n---\nThe answer is 42"
    out = sanitize_output(text)
    assert "Thought Process" not in out
    assert "42" in out


def test_wraps_bare_json_in_code_fence():
    text = 'Here is the data: {"key": "longer than twenty chars value here"}'
    out = sanitize_output(text)
    assert "```json" in out


def test_preserves_already_fenced_json():
    text = 'Here:\n```json\n{"key": "longer than twenty chars value here"}\n```'
    out = sanitize_output(text)
    # Should not double-wrap
    assert out.count("```json") == 1


def test_returns_original_when_sanitization_empties_text():
    text = "<think>only thinking</think>"
    out = sanitize_output(text)
    # All-thinking text returns original to avoid blank responses
    assert out == text
