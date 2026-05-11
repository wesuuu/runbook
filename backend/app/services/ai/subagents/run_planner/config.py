"""run_planner SubAgentConfig builder (placeholder)."""

from pathlib import Path
from typing import Any

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS

_PROMPT = (Path(__file__).parent / "prompt.md").read_text()


def build(model: Any) -> SubAgentConfig:
    return {
        "name": "run_planner",
        "description": (
            "(Placeholder) Use when the user wants to plan a run. "
            "Currently returns a not-yet-available message."
        ),
        "instructions": _PROMPT,
        "model": model,
        "agent_kwargs": {
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [],
        },
    }
