"""Tests for the protocol_creator subagent config."""

from app.services.ai.subagents import protocol_creator


EXPECTED_TOOL_NAMES = {
    "list_projects",
    "list_protocols",
    "get_protocol",
    "list_unit_ops",
    "list_protocol_roles",
    "create_unit_op",
    "create_protocol",
    "create_draft",
}


def test_protocol_creator_build_returns_subagent_config():
    config = protocol_creator.build("openai:gpt-4.1-mini")
    assert config["name"] == "protocol_creator"
    assert config["model"] == "openai:gpt-4.1-mini"
    assert config["instructions"]
    assert "protocol" in config["description"].lower()


def test_protocol_creator_tool_set():
    config = protocol_creator.build("openai:gpt-4.1-mini")
    tool_names = {fn.__name__ for fn in config["agent_kwargs"]["tools"]}
    assert tool_names == EXPECTED_TOOL_NAMES, (
        f"Expected exactly {EXPECTED_TOOL_NAMES}, got {tool_names}"
    )


def test_protocol_creator_prompt_instructs_external_param_extraction():
    """External-protocol seeds: prompt must teach the agent to parse step
    prose for measurable values and emit a populated ``param_schema`` per
    custom unit op + matching ``params`` on the step.

    Regression guard: F-0084 imports from OpenWetWare were landing with
    empty ``{notes}`` schemas because the prompt only told the agent to
    copy the raw step text into ``description``.
    """
    config = protocol_creator.build("openai:gpt-4.1-mini")
    prompt = config["instructions"].lower()

    # Names a few of the conventional param keys the agent should emit.
    for key in ("volume_ml", "temperature_c", "time_min", "concentration"):
        assert key in prompt, (
            f"Prompt is missing conventional param name '{key}' — the agent "
            f"needs explicit guidance to extract typed parameters from step "
            f"prose for imported external protocols."
        )

    # Must explicitly tell the agent to extract from the source step text.
    assert "extract" in prompt or "parse" in prompt
    assert "param_schema" in prompt
