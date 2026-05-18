"""Docling extraction entry points.

Both functions are synchronous and CPU/IO heavy — callers should
dispatch them via ``runner.run_sync`` (or ``asyncio.to_thread``) so the
event loop stays responsive.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.ai.workflows.document_extraction.models import (
    PageSpan,
    StructuredDoc,
    TocEntry,
)

logger = logging.getLogger(__name__)


def extract_pdf(path: Path | str) -> StructuredDoc:
    """Extract a PDF into structured markdown + page mapping."""
    return _extract(Path(path), kind="pdf")


def extract_docx(path: Path | str) -> StructuredDoc:
    """Extract a DOCX into structured markdown + page mapping.

    DOCX has no native page concept until rendered; docling assigns
    synthetic page numbers based on its conversion pipeline, which is
    sufficient for our chunking needs.
    """
    return _extract(Path(path), kind="docx")


# ── Internal ─────────────────────────────────────────────────────────


def _extract(path: Path, *, kind: str) -> StructuredDoc:
    """Run docling once and turn its output into StructuredDoc.

    docling is imported lazily so importing this module stays cheap
    (it pulls heavy ML deps on first use). Picture images are
    generated for PDFs so the HTML renderer can embed figures.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pdf_options = PdfPipelineOptions()
    pdf_options.images_scale = 2.0
    pdf_options.generate_picture_images = True
    pdf_options.generate_table_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        }
    )
    result = converter.convert(str(path))
    doc = result.document

    markdown = doc.export_to_markdown()
    page_spans = _build_page_spans(doc, markdown)
    toc = _build_toc(doc)
    page_count = _page_count(doc)

    logger.info(
        "docling extracted %s: %d pages, %d headings, %d md chars",
        path.name,
        page_count,
        len(toc),
        len(markdown),
    )

    return StructuredDoc(
        markdown=markdown,
        page_spans=page_spans,
        toc=toc,
        page_count=page_count,
        raw=doc,
    )


def _page_count(doc) -> int:
    pages = getattr(doc, "pages", None)
    if pages is None:
        return 0
    try:
        return len(pages)
    except TypeError:
        return 0


def _build_page_spans(doc, markdown: str) -> list[PageSpan]:
    """Approximate per-page character ranges in the exported markdown.

    docling assigns page numbers to most items but does not expose
    per-page markdown directly. We export each page's items via
    ``export_to_markdown(page_no=...)`` when supported, otherwise we
    fall back to a single span covering the whole document.
    """
    page_count = _page_count(doc)
    if page_count <= 1:
        return [PageSpan(page_number=1, start=0, end=len(markdown))]

    # Try the per-page export path first (docling >= 2.x).
    try:
        spans: list[PageSpan] = []
        cursor = 0
        for page_no in range(1, page_count + 1):
            chunk = doc.export_to_markdown(page_no=page_no)
            if not chunk:
                continue
            idx = markdown.find(chunk, cursor)
            if idx < 0:
                # Markdown export reorders or alters whitespace; fall
                # back to anchoring on the first ~80 chars.
                anchor = chunk.strip()[:80]
                idx = markdown.find(anchor, cursor) if anchor else -1
            if idx < 0:
                continue
            spans.append(
                PageSpan(
                    page_number=page_no,
                    start=idx,
                    end=idx + len(chunk),
                )
            )
            cursor = idx + len(chunk)
        if spans:
            # Stretch each span's end up to the next span's start so
            # we cover the full markdown contiguously.
            for i in range(len(spans) - 1):
                spans[i].end = spans[i + 1].start
            spans[-1].end = len(markdown)
            return spans
    except TypeError:
        # Older docling: export_to_markdown doesn't accept page_no.
        pass
    except Exception as exc:
        logger.debug("Per-page markdown export failed: %s", exc)

    return [PageSpan(page_number=1, start=0, end=len(markdown))]


def _build_toc(doc) -> list[TocEntry]:
    """Flatten docling's heading items into a TOC list.

    docling exposes headings via the section header item type. We walk
    the document body and pick up any item whose label indicates a
    heading.
    """
    toc: list[TocEntry] = []
    iter_items = getattr(doc, "iterate_items", None)
    if not callable(iter_items):
        return toc

    for item, _level in iter_items():
        label = getattr(item, "label", None)
        label_value = getattr(label, "value", label)
        if label_value not in {"section_header", "title"}:
            continue

        text = getattr(item, "text", "") or ""
        text = text.strip()
        if not text:
            continue

        heading_level = _heading_level(item, fallback=1 if label_value == "title" else 2)
        page_no = _first_page(item)

        toc.append(
            TocEntry(
                level=heading_level,
                text=text,
                page_number=page_no,
            )
        )

    return toc


def _heading_level(item, fallback: int) -> int:
    """Pull a 1-based heading level off a docling item if available."""
    level = getattr(item, "level", None)
    if isinstance(level, int) and level > 0:
        return level
    # Some docling versions encode level on the label name (e.g. h2).
    label = getattr(item, "label", None)
    label_value = getattr(label, "value", label)
    if isinstance(label_value, str) and label_value.startswith("h"):
        suffix = label_value[1:]
        if suffix.isdigit():
            return int(suffix)
    return fallback


def _first_page(item) -> int | None:
    """Return the first page number referenced by a docling item."""
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    try:
        for entry in prov:
            page_no = getattr(entry, "page_no", None)
            if isinstance(page_no, int):
                return page_no
    except TypeError:
        return None
    return None
