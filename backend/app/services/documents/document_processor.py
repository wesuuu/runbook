"""Lightweight document extraction utilities.

The full ingestion pipeline (extract → refine → index) now lives under
``app.services.documents.extraction`` (docling-based).  This module keeps
only the cheap pymupdf/python-docx helpers that are still called by:

- ``app.services.protocols.protocol_importer`` — PDF/DOCX text for AI conversion
- ``app.services.batch.batch_record_extractor``  — PDF text for batch records
- ``app.services.documents.retrieval``           — embedding padding
- ``app.api.endpoints.library``                  — embedding padding
"""

import logging
from pathlib import Path

from app.models.library import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)

# Resolution for rendering page images for LLM (used by protocol_importer,
# batch_record_extractor via extract_pdf_pages).
PAGE_IMAGE_DPI = 150


def _extract_page_text(page) -> str:
    """Extract text from a PDF page with correct word spacing.

    Some PDFs use character positioning (kerning) instead of explicit
    space characters between words.  Plain ``page.get_text()`` merges
    these into concatenated strings like ``OFANIMALCELLS``.

    This function uses pymupdf's ``rawdict`` output to examine the
    gap between consecutive characters.  When the gap exceeds a
    threshold relative to the font size, a space is inserted.
    Falls back to ``page.get_text()`` if character data is
    unavailable.
    """
    try:
        d = page.get_text("rawdict")
    except Exception:
        return page.get_text()

    block_texts: list[str] = []

    for block in d.get("blocks", []):
        if block.get("type") != 0:  # skip image blocks
            continue

        line_texts: list[str] = []
        for line in block.get("lines", []):
            chars: list[str] = []
            prev_end: float | None = None

            for span in line.get("spans", []):
                span_chars = span.get("chars")
                if not span_chars:
                    # rawdict always has chars, but guard anyway
                    chars.append(span.get("text", ""))
                    if span.get("bbox"):
                        prev_end = span["bbox"][2]
                    continue

                font_size = span.get("size", 12)
                # Threshold: gap > 10% of font size → word boundary.
                # PDFs without explicit space chars use ~11-14% of
                # font size for word gaps; intra-word gaps are 0.
                space_thresh = max(font_size * 0.10, 1.0)

                for c in span_chars:
                    c_x0 = c["bbox"][0]
                    if prev_end is not None:
                        gap = c_x0 - prev_end
                        if gap > space_thresh:
                            chars.append(" ")
                    chars.append(c["c"])
                    prev_end = c["bbox"][2]

            line_text = "".join(chars)
            if line_text.strip():
                line_texts.append(line_text)

        if line_texts:
            block_texts.append("\n".join(line_texts))

    return "\n\n".join(block_texts) if block_texts else page.get_text()


def extract_pdf_pages(path: Path, render_images: bool = True) -> list:
    """Extract text from a PDF page-by-page using plain pymupdf.

    Uses ``page.get_text()`` for each page, which handles columns
    correctly and is fast. When *render_images* is True (default),
    each page is also rendered as a PNG for the LLM structure
    classifier.

    Returns:
        List of PageData objects, one per PDF page (1-indexed).
    """
    from app.services.data.text_chunker import PageData

    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        page_count = len(doc)
        pages: list[PageData] = []

        for i in range(page_count):
            page = doc[i]
            has_images = len(page.get_images(full=True)) > 0
            text = _extract_page_text(page)

            # Render page as PNG for LLM classification
            image_bytes = None
            if render_images:
                try:
                    pix = page.get_pixmap(dpi=PAGE_IMAGE_DPI)
                    image_bytes = pix.tobytes("png")
                except Exception:
                    logger.debug("Failed to render page %d as image", i + 1)

            pages.append(
                PageData(
                    page_number=i + 1,
                    text=text.strip() if text else "",
                    has_images=has_images,
                    image_bytes=image_bytes,
                )
            )

        return pages
    finally:
        doc.close()


def extract_docx(path: Path) -> str:
    """Extract text from a DOCX file using python-docx."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _pad_embedding(
    embedding: list[float],
) -> list[float]:
    """Pad or truncate an embedding to EMBEDDING_DIMENSIONS.

    Different models produce different dimensions (e.g., nomic-embed-text
    produces 768d, OpenAI text-embedding-3-small produces 1536d). The
    database column is fixed at EMBEDDING_DIMENSIONS. Shorter vectors
    are zero-padded; longer vectors are truncated.
    """
    if len(embedding) == EMBEDDING_DIMENSIONS:
        return embedding
    if len(embedding) < EMBEDDING_DIMENSIONS:
        return embedding + [0.0] * (EMBEDDING_DIMENSIONS - len(embedding))
    return embedding[:EMBEDDING_DIMENSIONS]
