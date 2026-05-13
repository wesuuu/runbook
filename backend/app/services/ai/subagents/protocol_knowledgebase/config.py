"""Config builder for the protocol_knowledgebase subagent (F-0084)."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.protocol_knowledgebase.tools import (
    fetch_openwetware_protocol,
    search_openwetware,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_knowledgebase subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")
    return SubAgentConfig(
        name="protocol_knowledgebase",
        description=(
            "Searches public protocol repositories (OpenWetWare) and returns "
            "candidate protocols with structured, verbatim summaries. "
            "Dispatch when the user asks for an external/public protocol or "
            "to find a protocol for technique X from open repositories. "
            "Does NOT create or modify protocols — the parent agent handles "
            "the human-in-the-loop conversion after the user confirms."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [search_openwetware, fetch_openwetware_protocol],
        },
    )
