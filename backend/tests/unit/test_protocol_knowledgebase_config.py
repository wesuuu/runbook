"""protocol_knowledgebase build() returns a SubAgentConfig wired with both tools."""

from app.services.ai.subagents import protocol_knowledgebase


def test_build_returns_config_with_search_and_fetch():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    assert cfg["name"] == "protocol_knowledgebase"
    assert "OpenWetWare" in cfg["description"] or "public" in cfg["description"]
    tool_names = [t.__name__ for t in cfg["agent_kwargs"]["tools"]]
    assert "search_openwetware" in tool_names
    assert "fetch_openwetware_protocol" in tool_names


def test_prompt_includes_handoff_contract():
    cfg = protocol_knowledgebase.build("openai:gpt-4.1-mini")
    instructions = cfg["instructions"]
    assert "EXTERNAL_PROTOCOL_SOURCE" in instructions
    assert "verbatim" in instructions
    assert "source_url" in instructions
