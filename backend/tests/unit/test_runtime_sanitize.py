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


def test_preserves_section_header_containing_planning():
    """A legit header that merely contains 'Planning'/'Analysis' must survive.

    Regression: the reasoning-header stripper matched the bare word inside
    `**Runs & Planning**` and deleted everything after it to end-of-text,
    silently truncating the response mid-word.
    """
    text = (
        "Here is what I can help with:\n\n"
        "**Protocols**\n- Create and edit protocols\n\n"
        "**Runs & Planning**\n- Plan an upcoming run\n\n"
        "**Knowledge**\n- Answer questions\n\n"
        "What would you like to do?"
    )
    out = sanitize_output(text)
    assert out == text
    assert "Runs & Planning" in out
    assert out.rstrip().endswith("What would you like to do?")


def test_does_not_strip_reasoning_header_without_terminator():
    """Without a `---` / Answer: terminator, nothing is stripped.

    A runaway match would delete the real answer; absent a terminator the
    text is treated as ordinary content.
    """
    text = "**My Reasoning**\nthe user wants X so I will do Y and then finish"
    out = sanitize_output(text)
    assert out == text


def test_strips_reasoning_header_only_on_its_own_line():
    """An embedded keyword is not a reasoning header."""
    text = "The Analysis section below explains the result.\n---\nDetails here"
    out = sanitize_output(text)
    assert "Analysis section" in out


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
