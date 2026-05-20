"""protocol_knowledgebase build() — wired with both sources' tool pairs."""

from app.services.ai.subagents import protocol_knowledgebase


def test_build_returns_config_with_all_source_tools():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_knowledgebase"
    tool_names = [t.__name__ for t in cfg["agent_kwargs"]["tools"]]
    assert "search_openwetware" in tool_names
    assert "fetch_openwetware_protocol" in tool_names
    assert "search_protocols_io" in tool_names
    assert "fetch_protocols_io" in tool_names


def test_description_mentions_both_sources():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert "protocols.io" in cfg["description"]


def test_prompt_includes_handoff_contract():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "EXTERNAL_PROTOCOL_SOURCE" in instructions
    assert "verbatim" in instructions
    assert "source_url" in instructions


def test_prompt_covers_license_restricted_handling():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "import_allowed" in instructions
    assert "protocols.io" in instructions
