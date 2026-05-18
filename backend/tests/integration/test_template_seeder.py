"""Seeder re-installs the new system defaults at app startup."""
from app.services.protocols.template_seeder import seed_system_templates


def test_seed_copies_default_templates_to_storage(tmp_path):
    seed_system_templates(storage_root=str(tmp_path))
    dest = tmp_path / "system" / "document_templates"
    sop = dest / "sop_default.docx"
    br = dest / "batch_record_default.docx"
    assert sop.exists() and sop.stat().st_size > 0
    assert br.exists() and br.stat().st_size > 0
