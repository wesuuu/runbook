"""Tests for runtime/compaction.py — CompactionState + capability hooks."""
from pydantic_ai.messages import ModelRequest, SystemPromptPart

from app.services.ai.runtime.compaction import (
    CompactionState, make_compaction_hooks,
)


def test_initial_state_is_untriggered():
    s = CompactionState()
    assert s.triggered is False
    assert s.summary_text is None
    assert s.summarized_message_count == 0


def test_audit_metadata_when_untriggered_returns_empty_dict():
    s = CompactionState()
    assert s.audit_metadata() == {}


def test_on_before_marks_triggered_and_records_cutoff():
    s = CompactionState()
    on_before, _ = make_compaction_hooks(s)
    on_before(["msg1", "msg2", "msg3"], cutoff_index=2)
    assert s.triggered is True
    assert s.summarized_message_count == 2


def test_on_after_extracts_summary_from_first_message():
    s = CompactionState()
    _, on_after = make_compaction_hooks(s)
    summary_msg = ModelRequest(parts=[SystemPromptPart(content="conversation summary text")])
    result = on_after([summary_msg, "next-real-message"])
    assert s.summary_text == "conversation summary text"
    assert result is None


def test_on_after_handles_no_system_prompt_part_gracefully():
    s = CompactionState()
    _, on_after = make_compaction_hooks(s)
    on_after(["plain-string-no-parts"])
    assert s.summary_text is None


def test_audit_metadata_when_triggered():
    s = CompactionState()
    on_before, on_after = make_compaction_hooks(s)
    on_before(["a", "b", "c"], cutoff_index=2)
    summary_msg = ModelRequest(parts=[SystemPromptPart(content="sum")])
    on_after([summary_msg])
    meta = s.audit_metadata()
    assert meta["type"] == "summary"
    assert meta["summarized_message_count"] == 2
