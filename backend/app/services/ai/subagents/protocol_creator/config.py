"""Config builder for the protocol_creator subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.shared.protocols.tools import (
    create_draft,
    create_protocol,
    create_unit_op,
    get_protocol,
    list_projects,
    list_protocol_roles,
    list_protocols,
    list_unit_ops,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_creator subagent.

    Args:
        model: The model string to use (e.g. ``"ollama:gpt-oss:120b-cloud"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_creator",
        description=(
            "Collaborates with the user to design and create a NEW Protocol "
            "record (and any new custom unit ops it needs). Dispatch when "
            "the user wants to build a protocol from scratch or define a "
            "new custom unit op. Does NOT modify existing protocols — "
            "dispatch protocol_editor for that."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "model_settings": CHAT_AGENT_MODEL_SETTINGS,
            "tools": [
                # Reads
                list_projects,
                list_protocols,
                get_protocol,
                list_unit_ops,
                list_protocol_roles,
                # Creation
                create_unit_op,
                create_protocol,
                # Draft lifecycle
                create_draft,
            ],
        },
    )
