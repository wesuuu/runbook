"""Docling-based document extraction.

Replaces the home-built pymupdf + LLM-guided structure pipeline for the
document-library ingestion path. Returns structured markdown plus page
mapping so downstream chunking and rendering can stay accurate without
a separate LLM pass.

Non-library consumers (protocol_importer, batch_record_extractor) still
use the cheap pymupdf helpers in ``app.services.documents.document_processor``
because they feed downstream vision/text LLMs and don't need layout
fidelity.
"""

from app.services.ai.workflows.document_extraction.extractor import (
    extract_docx,
    extract_pdf,
)
from app.services.ai.workflows.document_extraction.html_renderer import (
    render_html,
)
from app.services.ai.workflows.document_extraction.models import (
    PageSpan,
    StructuredDoc,
    TocEntry,
)

__all__ = [
    "PageSpan",
    "StructuredDoc",
    "TocEntry",
    "extract_docx",
    "extract_pdf",
    "render_html",
]
