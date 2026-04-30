"""Tests for per-page PDF extraction via extract_pdf_pages()."""

import tempfile
from pathlib import Path

import pymupdf
import pytest


class TestExtractPdfPages:
    def _create_test_pdf(
        self, pages: list[list[tuple[str, float, float, float]]]
    ) -> Path:
        """Create a test PDF with text on specified pages.

        Args:
            pages: List of pages, each containing (text, x, y, fontsize) tuples.

        Returns:
            Path to the temporary PDF file.
        """
        doc = pymupdf.open()
        for page_items in pages:
            page = doc.new_page()
            for text, x, y, fontsize in page_items:
                page.insert_text(
                    pymupdf.Point(x, y),
                    text,
                    fontsize=fontsize,
                )
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        doc.save(tmp.name)
        doc.close()
        return Path(tmp.name)

    def test_returns_page_data_list(self):
        from app.services.documents.document_processor import extract_pdf_pages

        path = self._create_test_pdf(
            [
                [("Hello World", 72, 72, 12)],
            ]
        )
        try:
            pages = extract_pdf_pages(path)
            assert len(pages) == 1
            assert pages[0].page_number == 1
            assert "Hello" in pages[0].text
            assert "World" in pages[0].text
        finally:
            path.unlink()

    def test_multi_page_extraction(self):
        from app.services.documents.document_processor import extract_pdf_pages

        path = self._create_test_pdf(
            [
                [("Page One Content", 72, 72, 12)],
                [("Page Two Content", 72, 72, 12)],
                [("Page Three Content", 72, 72, 12)],
            ]
        )
        try:
            pages = extract_pdf_pages(path)
            assert len(pages) == 3
            assert pages[0].page_number == 1
            assert pages[1].page_number == 2
            assert pages[2].page_number == 3
            assert "Page One" in pages[0].text
            assert "Page Two" in pages[1].text
            assert "Page Three" in pages[2].text
        finally:
            path.unlink()

    def test_page_text_is_independent(self):
        """Each page's text should only contain that page's content."""
        from app.services.documents.document_processor import extract_pdf_pages

        path = self._create_test_pdf(
            [
                [("ALPHA content", 72, 72, 12)],
                [("BETA content", 72, 72, 12)],
            ]
        )
        try:
            pages = extract_pdf_pages(path)
            # Page 1 should NOT contain page 2's text
            assert "BETA" not in pages[0].text
            assert "ALPHA" not in pages[1].text
        finally:
            path.unlink()

    def test_empty_pdf_returns_empty_page(self):
        from app.services.documents.document_processor import extract_pdf_pages

        doc = pymupdf.open()
        doc.new_page()
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        doc.save(tmp.name)
        doc.close()
        path = Path(tmp.name)

        try:
            pages = extract_pdf_pages(path)
            assert len(pages) == 1
            assert pages[0].page_number == 1
            assert pages[0].text.strip() == ""
        finally:
            path.unlink()

    def test_has_images_flag(self):
        """Pages with images should have has_images=True."""
        from app.services.documents.document_processor import extract_pdf_pages

        doc = pymupdf.open()
        # Page 1: text only
        page1 = doc.new_page()
        page1.insert_text(pymupdf.Point(72, 72), "Text only", fontsize=12)

        # Page 2: with an image
        page2 = doc.new_page()
        page2.insert_text(pymupdf.Point(72, 72), "With image", fontsize=12)
        # Insert a tiny 2x2 red PNG
        import struct
        import zlib

        def _make_tiny_png() -> bytes:
            # 2x2 red PNG
            raw_data = b"\x00\xff\x00\x00\xff\x00\x00" * 2
            compressed = zlib.compress(raw_data)

            def _chunk(ctype, data):
                c = ctype + data
                return (
                    struct.pack(">I", len(data))
                    + c
                    + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
                )

            return (
                b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
                + _chunk(b"IDAT", compressed)
                + _chunk(b"IEND", b"")
            )

        png_bytes = _make_tiny_png()
        page2.insert_image(pymupdf.Rect(100, 100, 200, 200), stream=png_bytes)

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        doc.save(tmp.name)
        doc.close()
        path = Path(tmp.name)

        try:
            pages = extract_pdf_pages(path)
            assert len(pages) == 2
            assert pages[0].has_images is False
            assert pages[1].has_images is True
        finally:
            path.unlink()

    def test_plain_text_extraction_preserves_content(self):
        """Plain pymupdf extraction preserves all text content."""
        from app.services.documents.document_processor import extract_pdf_pages

        path = self._create_test_pdf(
            [
                [
                    ("Title Text", 72, 72, 24),
                    ("Body paragraph with details.", 72, 120, 12),
                ],
            ]
        )
        try:
            pages = extract_pdf_pages(path)
            assert len(pages) == 1
            assert "Title" in pages[0].text
            assert "Body paragraph" in pages[0].text
        finally:
            path.unlink()
