from pathlib import Path

# Cursive font now lives under app/data/fonts (used by both the
# deprecated fpdf2 path and the new font-registration helper for
# LibreOffice).
FONTS_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "fonts"
)
