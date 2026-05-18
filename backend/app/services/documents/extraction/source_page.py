"""Renders one PDF page to PNG bytes for the editor's left-rail thumbnail."""

from pathlib import Path


def render_source_page(pdf_path: Path, page_number: int, dpi: int = 96) -> bytes:
    """Return PNG bytes for page `page_number` (1-indexed) of a PDF.

    Raises ValueError if the page is out of range. Uses pymupdf which
    is already a runtime dependency.
    """
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"page {page_number} out of range (1..{len(doc)})")
        page = doc[page_number - 1]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()
