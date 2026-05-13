from app.core.config import Settings


def test_background_handler_and_docling_settings_have_sensible_defaults():
    s = Settings()
    assert s.background_handler == "local"
    assert s.docling_num_threads == 4
    # Default paths point at the ext/ project relative to the repo root.
    assert s.docling_script_python.endswith(
        "ext/docling-extractor/.venv/bin/python"
    )
    assert s.docling_script_path.endswith(
        "ext/docling-extractor/extract.py"
    )


def test_document_refinement_capability_env_fields_exist():
    s = Settings()
    assert s.ai_document_refinement_provider == ""
    assert s.ai_document_refinement_model == ""


def test_doc_structure_capability_fields_removed():
    s = Settings()
    assert not hasattr(s, "ai_doc_structure_provider")
    assert not hasattr(s, "ai_doc_structure_model")
