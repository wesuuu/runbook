"""Tests for the protocol_editor subagent config."""

from app.services.ai.subagents import protocol_editor


EXPECTED_TOOL_NAMES = {
    # Reads
    "list_projects",
    "list_protocols",
    "get_protocol",
    "list_unit_ops",
    "list_protocol_roles",
    # Validation
    "validate_protocol",
    # Draft lifecycle
    "create_draft",
    # Metadata
    "update_protocol_metadata",
    # Step mutations
    "add_protocol_step",
    "update_protocol_step",
    "remove_protocol_step",
    "reorder_protocol_steps",
    "replace_step_unit_op",
    # Role mutations
    "add_protocol_role",
    "update_protocol_role",
    "remove_protocol_role",
    # Unit op mutations
    "update_unit_op",
    "elevate_unit_op_scope",
}


def test_protocol_editor_build_returns_subagent_config():
    config = protocol_editor.build("openai:gpt-4.1-mini")
    assert config["name"] == "protocol_editor"
    assert config["model"] == "openai:gpt-4.1-mini"
    assert config["instructions"]
    assert "protocol" in config["description"].lower()


def test_protocol_editor_tool_set():
    config = protocol_editor.build("openai:gpt-4.1-mini")
    tool_names = {fn.__name__ for fn in config["agent_kwargs"]["tools"]}
    assert tool_names == EXPECTED_TOOL_NAMES, (
        f"Expected exactly {EXPECTED_TOOL_NAMES}, got {tool_names}"
    )
    assert len(tool_names) == 18
