"""Config builder for the protocol_editor subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.shared.protocols.tools import (
    add_protocol_role,
    add_protocol_step,
    elevate_unit_op_scope,
    get_protocol,
    list_projects,
    list_protocol_roles,
    list_protocols,
    list_unit_ops,
    remove_protocol_role,
    remove_protocol_step,
    reorder_protocol_steps,
    replace_step_unit_op,
    update_protocol_metadata,
    update_protocol_role,
    update_protocol_step,
    update_unit_op,
    validate_protocol,
)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_editor subagent.

    Args:
        model: The model string to use (e.g. ``"ollama:gpt-oss:120b-cloud"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_editor",
        description=(
            "Modifies an existing draft Protocol — step add/update/remove/"
            "reorder, role changes, metadata, custom-unit-op edits, and "
            "scope elevation. Dispatch when the user wants to change a "
            "protocol they already have. Does NOT create new protocols — "
            "dispatch protocol_creator for that."
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
                # Validation
                validate_protocol,
                # Metadata
                update_protocol_metadata,
                # Step mutations
                add_protocol_step,
                update_protocol_step,
                remove_protocol_step,
                reorder_protocol_steps,
                replace_step_unit_op,
                # Role mutations
                add_protocol_role,
                update_protocol_role,
                remove_protocol_role,
                # Unit op mutations
                update_unit_op,
                elevate_unit_op_scope,
            ],
        },
    )
