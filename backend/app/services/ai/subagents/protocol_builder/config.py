"""Config builder for the protocol_builder subagent."""

from __future__ import annotations

from pathlib import Path

from subagents_pydantic_ai import SubAgentConfig

from app.services.ai.subagents.protocol_builder.tools import (
    create_protocol, create_unit_op, list_projects, list_unit_ops,
    update_protocol_step, validate_protocol)

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
            "Collaborates with the user to design and create a draft Protocol "
            "record. Dispatch when the user wants to build, scaffold, or "
            "generate a new protocol from scratch or from a description."
        ),
        instructions=instructions,
        model=model,
        typically_needs_context=True,
        agent_kwargs={
            "tools": [
                list_projects,
                list_unit_ops,
                create_unit_op,
                create_protocol,
                validate_protocol,
                update_protocol_step,
            ],
        },
    )
