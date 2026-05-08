"""Register the bundled DancingScript font with the OS so LibreOffice
can render the cursive initials fallback when converting docx -> PDF.

Idempotent. Safe to call from FastAPI startup. Failures are logged at
WARN level -- the document still renders, just in the document's body
font instead of cursive.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from app.services.documents.fonts import FONTS_DIR

logger = logging.getLogger(__name__)

_FONT_FILENAME = "DancingScript-Regular.ttf"


def ensure_cursive_font_registered() -> None:
    """Copy DancingScript into ~/.fonts and refresh fontconfig cache."""
    src = FONTS_DIR / _FONT_FILENAME
    if not src.exists():
        logger.warning("Cursive font missing from %s; skipping", src)
        return

    dest_dir = Path.home() / ".fonts"
    dest = dest_dir / _FONT_FILENAME

    needs_install = (
        not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime
    )
    if not needs_install:
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    try:
        subprocess.run(
            ["fc-cache", "-f", str(dest_dir)],
            check=True,
            timeout=10,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning(
            "fc-cache failed; cursive fallback may not render: %s", e
        )
