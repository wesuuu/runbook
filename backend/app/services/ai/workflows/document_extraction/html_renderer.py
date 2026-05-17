"""HTML rendering for StructuredDoc.

Phase 1 uses docling's native ``export_to_html()`` so the eval can
visually compare images, columns, tables, and figures against the
original. Later phases may add a styled wrapper for the doc library
viewer.
"""

from __future__ import annotations

import logging

from app.services.ai.workflows.document_extraction.models import StructuredDoc

logger = logging.getLogger(__name__)


def render_html(doc: StructuredDoc) -> str:
    """Render the structured doc to standalone HTML.

    Uses docling's native exporter when ``doc.raw`` is present. Falls
    back to a minimal markdown-wrapped page when the raw document is
    missing (e.g. deserialized from cache).
    """
    raw = doc.raw
    if raw is None:
        return _fallback_html(doc.markdown)

    # Inline picture bytes as base64 so the HTML is self-contained
    # for figures, columns, and tables.
    try:
        from docling_core.types.doc import ImageRefMode

        return raw.export_to_html(image_mode=ImageRefMode.EMBEDDED)
    except Exception as exc:
        logger.warning("docling export_to_html failed: %s — falling back", exc)
        return _fallback_html(doc.markdown)


def _fallback_html(markdown: str) -> str:
    body = markdown.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Document</title></head><body><pre>"
        f"{body}</pre></body></html>"
    )
