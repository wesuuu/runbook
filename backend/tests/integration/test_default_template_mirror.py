"""Task 25 — byte-equality drift guard for system .docx templates.

The default SOP and batch-record templates live in
``backend/app/services/documents/templates/`` and are mirrored into
``<storage_root>/system/document_templates/`` by
:func:`seed_system_templates` during startup. The two copies must stay
byte-identical so the seeded ``DocumentTemplate.file_path`` row resolves
to the same .docx the engine renders during preview.

If anyone regenerates the in-tree template (via the python-docx
generator scripts under ``backend/scripts/``) and forgets to wipe the
stale mirror, the system row will keep pointing at the old bytes — this
test fails loudly when that happens.
"""

from pathlib import Path

import pytest

from app.services.protocols.template_seeder import (SYSTEM_TEMPLATES_DEST,
                                                    SYSTEM_TEMPLATES_SOURCE,
                                                    seed_system_templates)

TEMPLATES = ["sop_default.docx", "batch_record_default.docx"]


@pytest.mark.parametrize("filename", TEMPLATES)
def test_seeded_template_matches_source(tmp_path, filename):
    """After seeding, the mirrored .docx must be byte-equal to the source."""
    seed_system_templates(str(tmp_path))

    src = SYSTEM_TEMPLATES_SOURCE / filename
    dst = tmp_path / SYSTEM_TEMPLATES_DEST / filename

    assert src.exists(), f"source missing: {src}"
    assert dst.exists(), f"mirror not seeded: {dst}"

    assert src.read_bytes() == dst.read_bytes(), (
        f"{filename} drifted between source and seeded mirror; "
        f"re-run the seeder or regenerate the source"
    )
