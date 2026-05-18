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
    assert (
        tool_names == EXPECTED_TOOL_NAMES
    ), f"Expected exactly {EXPECTED_TOOL_NAMES}, got {tool_names}"
