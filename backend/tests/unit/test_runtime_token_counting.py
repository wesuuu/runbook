"""Tests for runtime/token_counting.py — tiktoken-backed counter."""
from app.services.ai.runtime.token_counting import tiktoken_counter


def test_returns_int_for_simple_string_message():
    msgs = ["hello world"]
    assert isinstance(tiktoken_counter(msgs), int)
    assert tiktoken_counter(msgs) > 0


def test_handles_empty_list():
    assert tiktoken_counter([]) == 0


def test_grows_monotonically_with_text_length():
    short = tiktoken_counter(["one two"])
    long = tiktoken_counter(["one two three four five six seven eight"])
    assert long > short


def test_handles_dict_messages_via_str():
    msgs = [{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]}]
    assert tiktoken_counter(msgs) > 0
