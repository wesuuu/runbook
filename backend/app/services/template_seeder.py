"""Seed system .docx templates into the file storage directory.

Copies bundled .docx template files from the source directory
(app/services/templates/) into the FileStorageService storage root
under system/document_templates/. Idempotent — skips files that
already exist.
"""

import shutil
from pathlib import Path


SYSTEM_TEMPLATES_SOURCE = Path(__file__).parent / "templates"
SYSTEM_TEMPLATES_DEST = "system/document_templates"


def seed_system_templates(storage_root: str = "./uploads") -> None:
    """Copy bundled system templates to the file storage directory."""
    dest = Path(storage_root) / SYSTEM_TEMPLATES_DEST
    dest.mkdir(parents=True, exist_ok=True)

    for src_file in SYSTEM_TEMPLATES_SOURCE.glob("*.docx"):
        target = dest / src_file.name
        if not target.exists() or src_file.stat().st_mtime > target.stat().st_mtime:
            shutil.copy2(src_file, target)
