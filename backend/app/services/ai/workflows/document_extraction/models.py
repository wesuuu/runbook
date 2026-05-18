"""Result types for docling-based extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PageSpan:
    """A page's slice within the full markdown string.

    ``start`` is inclusive, ``end`` is exclusive, both are character
    offsets into ``StructuredDoc.markdown``. Used to map chunks back to
    PDF page numbers.
    """

    page_number: int
    start: int
    end: int


@dataclass(slots=True)
class TocEntry:
    """A heading entry suitable for the document sidebar TOC."""

    level: int
    text: str
    page_number: int | None = None


@dataclass(slots=True)
class StructuredDoc:
    """Output of a docling extraction pass.

    ``markdown`` is the canonical text used by the chunker.
    ``page_spans`` lets callers map character offsets back to page
    numbers. ``toc`` is a flat heading list. ``raw`` is the underlying
    ``DoclingDocument`` for callers that need the full structure (e.g.
    the HTML renderer); typed as Any to keep this module import-light.
    """

    markdown: str
    page_spans: list[PageSpan] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    page_count: int = 0
    raw: Any = None

    def page_boundaries(self) -> list[int]:
        """Character offsets where each new page starts.

        Compatible with the ``page_boundaries`` arg on
        ``markdown_chunker.chunk_markdown``.
        """
        return [span.start for span in self.page_spans]
