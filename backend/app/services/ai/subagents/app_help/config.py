"""Config builder for the app_help subagent (F-0089)."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.app_help.tools import load_user_guide_text

_PROMPT_PATH = Path(__file__).parent / "prompt.md"

# Separator line the prompt preamble points to. The builder inserts it
# between the instruction preamble (prompt.md) and the concatenated corpus.
_GUIDE_MARKER = "=== BATCHRITE USER GUIDE ==="


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the app_help subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    preamble = _PROMPT_PATH.read_text(encoding="utf-8").rstrip()
    corpus = load_user_guide_text()
    instructions = f"{preamble}\n\n{_GUIDE_MARKER}\n\n{corpus}\n"
    return SubAgentConfig(
        name="app_help",
        description=(
            "Answers questions about Batchrite itself — how features work, "
            "where to find things, what terms mean, troubleshooting. "
            "Dispatch when the user asks 'how do I…', 'what is…', "
            "'where is…', or 'why can't I…' about the product. Does NOT "
            "answer questions about the user's own data (their uploaded "
            "documents, protocols, runs) — those route to research_library "
            "or the protocol/run tools."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=False,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
        },
    )
