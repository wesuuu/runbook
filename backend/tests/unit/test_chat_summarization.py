"""Integration guard for the chat summarization prompt.

Exercises the real ``ContextManagerCapability`` (configured as ``chat_agent``
configures it) with the real summarization prompt and a fake summary model,
forcing a compaction event with a tiny token budget.

The fake summary model records every prompt it is handed, so the test can
assert the conversation actually reaches the summary model. That contract was
violated when ``summarization.md`` shipped without a ``{messages}`` slot:
``SummarizationProcessor._create_summary`` calls ``summary_prompt.format(
messages=...)``, so a prompt with no placeholder silently drops the
conversation and the summary model summarizes nothing — replying with a
confused "paste the conversation" message that leaks into chat output.
"""

import pytest
from pydantic_ai.messages import (ModelMessage, ModelRequest, ModelResponse,
                                  SystemPromptPart, TextPart, UserPromptPart)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_summarization import ContextManagerCapability

from app.services.ai.chat_agent import _SUMMARY_PROMPT
from app.services.ai.runtime.token_counting import tiktoken_counter

_SUMMARY_OUTPUT = "The user requested a buffer prep protocol draft."


def _capturing_summary_model(captured: list[str]) -> FunctionModel:
    """A fake summary model that records every prompt string it receives."""

    async def call(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        for msg in messages:
            if not isinstance(msg, ModelRequest):
                continue
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    captured.append(part.content)
        return ModelResponse(parts=[TextPart(content=_SUMMARY_OUTPUT)])

    return FunctionModel(function=call)


@pytest.mark.asyncio
async def test_compaction_feeds_conversation_to_summary_model():
    """When compaction fires, the conversation must reach the summary model.

    Without the ``{messages}`` placeholder in summarization.md the prompt
    template is handed to the summary model verbatim and the conversation is
    silently dropped (BUG-004).
    """
    captured: list[str] = []
    # max_tokens=10 + threshold 0.5 => compaction fires once history exceeds
    # ~5 tokens, which any real turn does. Mirrors chat_agent.py wiring:
    # summary_prompt and summarization_model flow straight to the processor.
    cap = ContextManagerCapability(
        max_tokens=10,
        compress_threshold=0.5,
        summarization_model=_capturing_summary_model(captured),
        summary_prompt=_SUMMARY_PROMPT,
        token_counter=tiktoken_counter,
    )

    conversation: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(content="Draft a buffer prep protocol")]),
        ModelResponse(
            parts=[TextPart(content="Created protocol draft 'Buffer Prep'.")]
        ),
    ]

    compacted = await cap.compact(conversation)

    # The summary model was invoked, and the conversation was embedded in the
    # prompt it received — proving the {messages} placeholder is filled.
    assert captured, "summary model was never invoked — compaction did not fire"
    prompt_seen = "\n".join(captured)
    assert "Draft a buffer prep protocol" in prompt_seen
    assert "Created protocol draft 'Buffer Prep'." in prompt_seen
    # The literal placeholder must never survive into the model-facing prompt.
    assert "{messages}" not in prompt_seen

    # The compacted history carries the model's real summary, not the unfilled
    # template echoed back.
    assert len(compacted) == 1
    first = compacted[0]
    assert isinstance(first, ModelRequest)
    summary_parts = [p for p in first.parts if isinstance(p, SystemPromptPart)]
    assert summary_parts, "compacted history is missing the summary message"
    summary_text = summary_parts[-1].content
    assert _SUMMARY_OUTPUT in summary_text
    assert "{messages}" not in summary_text
