from pathlib import Path

import pymupdf
import pytest

from app.services.documents.extraction.source_page import render_source_page


def _make_pdf(path: Path, page_count: int) -> None:
    doc = pymupdf.open()
    for _ in range(page_count):
        doc.new_page()
    doc.save(str(path))
    doc.close()


def test_render_source_page_returns_png_bytes(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, page_count=2)
    png = render_source_page(pdf, page_number=1, dpi=72)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_source_page_raises_for_out_of_range(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    _make_pdf(pdf, page_count=2)
    with pytest.raises(ValueError, match="page 99"):
        render_source_page(pdf, page_number=99)
