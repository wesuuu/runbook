"""Compaction state + hooks for ContextManagerCapability.

The capability's on_before_compress / on_after_compress callbacks are sync.
We capture state via closures into a CompactionState, then the orchestrator
inspects state after agent.run() returns and writes the audit
ChatMessage(role=SUMMARY) row. Avoids scheduling coroutines from sync hooks.
"""
from dataclasses import dataclass
from typing import Any, Callable

from pydantic_ai.messages import ModelMessage, ModelRequest, SystemPromptPart


@dataclass
class CompactionState:
    """Per-request capture of compaction events."""

    summary_text: str | None = None
    summarized_message_count: int = 0
    triggered: bool = False

    def audit_metadata(self) -> dict[str, Any]:
        if not self.triggered:
            return {}
        return {
            "type": "summary",
            "summarized_message_count": self.summarized_message_count,
        }


def make_compaction_hooks(
    state: CompactionState,
) -> tuple[
    Callable[[list[ModelMessage], int], None],
    Callable[[list[ModelMessage]], str | None],
]:
    """Return (on_before, on_after) closures for ContextManagerCapability."""

    def on_before(messages: list[ModelMessage], cutoff_index: int) -> None:
        state.triggered = True
        state.summarized_message_count = cutoff_index

    def on_after(messages: list[ModelMessage]) -> str | None:
        if messages:
            first = messages[0]
            if isinstance(first, ModelRequest):
                for part in first.parts:
                    if isinstance(part, SystemPromptPart):
                        state.summary_text = part.content
                        break
        return None  # don't modify the summary

    return on_before, on_after
