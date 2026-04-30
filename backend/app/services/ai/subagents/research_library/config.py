"""Config builder for the research_library subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.subagents.research_library.tools import (list_documents,
                                                              read_section,
                                                              search_documents)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the research_library subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="research_library",
        description=(
            "Searches and reads from the organisation's document library. "
            "Dispatch when the user asks a question that may be answered by "
            "uploaded SOPs, protocols, or reference documents."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "tools": [search_documents, read_section, list_documents],
        },
    )
