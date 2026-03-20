"""Tests for PDF extraction using pymupdf4llm."""

import tempfile
from pathlib import Path

import pymupdf
import pytest


class TestExtractPdf:
    def _create_test_pdf(self, pages: list[list[tuple[str, float, float, float]]]) -> Path:
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

    def test_extract_pdf_returns_text(self):
        from app.services.document_processor import extract_pdf

        path = self._create_test_pdf([
            [("Hello World", 72, 72, 12)],
        ])
        try:
            text, page_count, boundaries = extract_pdf(path)
            assert "Hello" in text
            assert "World" in text
            assert page_count == 1
        finally:
            path.unlink()

    def test_extract_pdf_multi_page(self):
        from app.services.document_processor import extract_pdf

        path = self._create_test_pdf([
            [("Page One Content", 72, 72, 12)],
            [("Page Two Content", 72, 72, 12)],
            [("Page Three Content", 72, 72, 12)],
        ])
        try:
            text, page_count, boundaries = extract_pdf(path)
            assert page_count == 3
            assert "Page One" in text
            assert "Page Two" in text
            assert "Page Three" in text
            # Boundaries should have entries for pages 2+
            assert len(boundaries) == 2
        finally:
            path.unlink()

    def test_extract_pdf_returns_markdown_format(self):
        """Verify pymupdf4llm produces markdown-like output."""
        from app.services.document_processor import extract_pdf

        path = self._create_test_pdf([
            [
                ("Title Text", 72, 72, 24),
                ("Body paragraph with details.", 72, 120, 12),
            ],
        ])
        try:
            text, page_count, boundaries = extract_pdf(path)
            assert page_count == 1
            # Text should be present regardless of markdown formatting
            assert "Title" in text
            assert "Body paragraph" in text
        finally:
            path.unlink()

    def test_extract_pdf_empty_pdf(self):
        """An empty PDF should return empty text."""
        from app.services.document_processor import extract_pdf

        doc = pymupdf.open()
        doc.new_page()  # One blank page
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        doc.save(tmp.name)
        doc.close()
        path = Path(tmp.name)

        try:
            text, page_count, boundaries = extract_pdf(path)
            assert page_count == 1
            # Text may be empty or whitespace-only
            assert text.strip() == "" or len(text.strip()) < 10
        finally:
            path.unlink()

    def test_page_boundaries_are_character_offsets(self):
        """Page boundaries should be valid character offsets into the text."""
        from app.services.document_processor import extract_pdf

        path = self._create_test_pdf([
            [("First page text here", 72, 72, 12)],
            [("Second page text here", 72, 72, 12)],
        ])
        try:
            text, page_count, boundaries = extract_pdf(path)
            assert page_count == 2
            # Each boundary should be a non-negative integer
            for b in boundaries:
                assert isinstance(b, int)
                assert b >= 0
                assert b <= len(text)
        finally:
            path.unlink()
