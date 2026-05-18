"""Smoke tests for the docling-based extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ai.workflows.document_extraction import (
    StructuredDoc,
    extract_docx,
    extract_pdf,
    render_html,
)

FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "templates"


@pytest.mark.parametrize(
    "filename",
    [
        "sop_simple.pdf",
        "batch_record_filled_simple.pdf",
    ],
)
def test_extract_pdf_returns_structured_doc(filename: str) -> None:
    doc = extract_pdf(FIXTURES / filename)

    assert isinstance(doc, StructuredDoc)
    assert doc.markdown.strip(), "expected non-empty markdown"
    assert doc.page_count >= 1
    assert doc.page_spans, "expected at least one page span"
    # spans must be contiguous
    for prev, cur in zip(doc.page_spans, doc.page_spans[1:]):
        assert prev.end == cur.start
    assert doc.page_spans[-1].end == len(doc.markdown)


def test_extract_pdf_collects_toc() -> None:
    doc = extract_pdf(FIXTURES / "sop_role_based.pdf")
    assert doc.toc, "expected at least one heading"
    for entry in doc.toc:
        assert entry.text.strip()
        assert entry.level >= 1


def test_extract_docx_returns_structured_doc() -> None:
    doc = extract_docx(FIXTURES / "sop_simple.docx")
    assert isinstance(doc, StructuredDoc)
    assert doc.markdown.strip()
    # DOCX has no native pages — extractor synthesizes one span
    assert len(doc.page_spans) == 1
    assert doc.page_spans[0].start == 0
    assert doc.page_spans[0].end == len(doc.markdown)


def test_render_html_embeds_images() -> None:
    # DOCX preserves image objects directly, so docling reliably emits
    # <figure>/data:image bytes. PDFs with rasterized figures need the
    # layout detector to classify regions as pictures, which depends
    # on the generator and isn't guaranteed for synthetic fixtures.
    doc = extract_docx(FIXTURES / "batch_record_filled_figures.docx")
    html = render_html(doc)
    assert html.startswith("<!DOCTYPE html>") or html.startswith("<!doctype html>")
    assert "data:image/" in html
    assert "<figure" in html


def test_render_html_fallback_when_raw_missing() -> None:
    doc = StructuredDoc(markdown="hello <world>", raw=None)
    html = render_html(doc)
    assert "&lt;world&gt;" in html
