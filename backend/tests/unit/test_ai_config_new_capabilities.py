from app.models.ai import DEFAULT_CONFIGS, SUPPORTED_CAPABILITIES


def test_chat_subagent_in_supported_capabilities():
    assert "chat_subagent" in SUPPORTED_CAPABILITIES


def test_chat_summary_in_supported_capabilities():
    assert "chat_summary" in SUPPORTED_CAPABILITIES


def test_chat_subagent_default_config():
    assert "chat_subagent" in DEFAULT_CONFIGS
    cfg = DEFAULT_CONFIGS["chat_subagent"]
    assert "provider" in cfg
    assert "model_name" in cfg
    assert cfg["provider"]
    assert cfg["model_name"]


def test_chat_summary_default_config():
    assert "chat_summary" in DEFAULT_CONFIGS
    cfg = DEFAULT_CONFIGS["chat_summary"]
    assert "provider" in cfg
    assert "model_name" in cfg
    assert cfg["provider"]
    assert cfg["model_name"]
