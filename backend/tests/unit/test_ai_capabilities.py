from app.models.ai import DEFAULT_CONFIGS, SUPPORTED_CAPABILITIES


def test_doc_structure_capability_removed():
    assert "doc_structure" not in SUPPORTED_CAPABILITIES
    assert "doc_structure" not in DEFAULT_CONFIGS


def test_document_refinement_capability_removed():
    """Dropped along with the AI-fix feature — users edit refined
    markdown directly in the Tiptap editor instead."""
    assert "document_refinement" not in SUPPORTED_CAPABILITIES
    assert "document_refinement" not in DEFAULT_CONFIGS
