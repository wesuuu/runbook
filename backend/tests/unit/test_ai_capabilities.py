from app.models.ai import DEFAULT_CONFIGS, SUPPORTED_CAPABILITIES


def test_document_refinement_capability_registered():
    assert "document_refinement" in SUPPORTED_CAPABILITIES
    cfg = DEFAULT_CONFIGS["document_refinement"]
    assert cfg["provider"] == "anthropic"
    assert cfg["model_name"].startswith("claude-sonnet-4")


def test_doc_structure_capability_removed():
    assert "doc_structure" not in SUPPORTED_CAPABILITIES
    assert "doc_structure" not in DEFAULT_CONFIGS
