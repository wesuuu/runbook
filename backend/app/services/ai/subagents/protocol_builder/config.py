"""Config builder for the protocol_builder subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.cache_settings import CHAT_AGENT_MODEL_SETTINGS
from app.services.ai.subagents.protocol_builder.tools import (
    add_protocol_role, add_protocol_step, create_draft, create_protocol,
    create_unit_op, elevate_unit_op_scope, get_protocol, list_projects,
    list_protocol_roles, list_protocols, list_unit_ops,
    relayout_protocol_chain, remove_protocol_role, remove_protocol_step,
    reorder_protocol_steps, replace_step_unit_op, update_protocol_metadata,
    update_protocol_role, update_protocol_step, update_unit_op,
    validate_protocol)

_PROMPT_PATH = Path(__file__).parent / "prompt.md"


def build(model: str) -> SubAgentConfig:
    """Return a SubAgentConfig for the protocol_builder subagent.

    Args:
        model: The model string to use (e.g. ``"openai:gpt-4.1-mini"``).
    """
    instructions = _PROMPT_PATH.read_text(encoding="utf-8")

    return SubAgentConfig(
        name="protocol_builder",
        description=(
            "Collaborates with the user to design, build, and edit Protocol "
            "records and their roles, plus manage custom unit-op definitions. "
            "Dispatch when the user wants to create a new protocol, edit an "
            "existing draft protocol's steps/metadata/roles, or modify or "
            "elevate the scope of a custom unit op."
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
                # Validation
                validate_protocol,
                # Draft lifecycle
                create_draft,
                # Mutations (DRAFT or active draft of APPROVED)
                update_protocol_metadata,
                add_protocol_step,
                update_protocol_step,
                remove_protocol_step,
                reorder_protocol_steps,
                replace_step_unit_op,
                relayout_protocol_chain,
                # Roles
                add_protocol_role,
                update_protocol_role,
                remove_protocol_role,
                # Unit op mutations
                update_unit_op,
                elevate_unit_op_scope,
            ],
        },
    )
