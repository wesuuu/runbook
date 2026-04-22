"""Markdown-aware text chunker.

Splits Markdown text into chunks that preserve structural elements:
headings stay with their content, tables are not split mid-row,
code fences are kept intact, and list items are grouped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from app.services.data.text_chunker import (PageData, TextChunk,
                                            _get_page_number)

if TYPE_CHECKING:
    from app.services.documents.document_structure import (DocumentStructure,
                                                           PageHeading)


# Patterns for Markdown block boundaries
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)


def chunk_markdown(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    page_boundaries: Optional[list[int]] = None,
) -> list[TextChunk]:
    """Split Markdown text into chunks preserving structural elements.

    First segments text into atomic blocks (heading+body, table, code fence,
    list group), then merges small blocks until chunk_size is reached.

    Args:
        text: Markdown text to split.
        chunk_size: Target maximum token count per chunk.
        overlap: Number of tokens to overlap between chunks.
        page_boundaries: Character offsets where new pages start (for PDFs).

    Returns:
        List of TextChunk objects with sequential indices.
    """
    if not text or not text.strip():
        return []

    tokens = text.split()
    if len(tokens) <= chunk_size:
        page_num = (
            _get_page_number(0, page_boundaries) if page_boundaries else None
        )
        return [
            TextChunk(
                content=text.strip(),
                chunk_index=0,
                token_count=len(tokens),
                page_number=page_num,
            )
        ]

    blocks = _segment_into_blocks(text)
    merged = _merge_blocks(blocks, chunk_size, overlap)

    result: list[TextChunk] = []
    for chunk_content in merged:
        stripped = chunk_content.strip()
        if not stripped:
            continue
        page_num = None
        if page_boundaries:
            needle = stripped[:50] if len(stripped) >= 50 else stripped
            char_offset = text.find(needle)
            if char_offset >= 0:
                page_num = _get_page_number(char_offset, page_boundaries)
        result.append(
            TextChunk(
                content=stripped,
                chunk_index=len(result),
                token_count=len(stripped.split()),
                page_number=page_num,
            )
        )
    return result


def _segment_into_blocks(text: str) -> list[str]:
    """Segment Markdown into atomic blocks.

    Splits on headings as primary boundaries, keeping each heading with
    the content that follows it. Code fences and tables are kept as
    single blocks even if they span many lines.
    """
    lines = text.split("\n")
    blocks: list[str] = []
    current: list[str] = []
    in_code_fence = False

    for line in lines:
        # Track code fence state
        if line.strip().startswith("```"):
            if in_code_fence:
                # Closing fence — end of code block
                current.append(line)
                in_code_fence = False
                continue
            else:
                # Opening fence — start new block if we have content
                if current:
                    blocks.append("\n".join(current))
                    current = []
                current.append(line)
                in_code_fence = True
                continue

        if in_code_fence:
            current.append(line)
            continue

        # Heading starts a new block
        if _HEADING_RE.match(line):
            if current:
                blocks.append("\n".join(current))
                current = []
            current.append(line)
        # Blank line can be a block separator for non-heading content
        elif line.strip() == "" and current:
            # Only split on blank lines if current block is large enough
            current_tokens = len("\n".join(current).split())
            if current_tokens > 100:
                blocks.append("\n".join(current))
                current = []
            else:
                current.append(line)
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks


def _merge_blocks(
    blocks: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """Merge small blocks into chunks up to chunk_size tokens.

    If a single block exceeds chunk_size, it is included as-is
    (we don't split atomic blocks like tables or code fences).
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for block in blocks:
        block_tokens = len(block.split())

        # If adding this block would exceed the limit, finalize current
        if current_parts and current_tokens + block_tokens > chunk_size:
            chunks.append("\n\n".join(current_parts))

            # Create overlap from the end of the current chunk
            overlap_text = _get_overlap_from_parts(
                current_parts, overlap
            )
            current_parts = []
            current_tokens = 0
            if overlap_text:
                current_parts.append(overlap_text)
                current_tokens = len(overlap_text.split())

        current_parts.append(block)
        current_tokens += block_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def _get_overlap_from_parts(
    parts: list[str], overlap_tokens: int
) -> str:
    """Extract the last N tokens from the combined parts for overlap."""
    if overlap_tokens <= 0:
        return ""
    combined = "\n\n".join(parts)
    words = combined.split()
    if len(words) <= overlap_tokens:
        return combined
    return " ".join(words[-overlap_tokens:])


# ── Page-level chunking ────────────────────────────────────────────


_SHORT_PAGE_TOKENS = 100
_LONG_PAGE_TOKENS = 2000


def chunk_by_pages(
    pages: list[PageData],
    merge_short: int = _SHORT_PAGE_TOKENS,
    split_long: int = _LONG_PAGE_TOKENS,
) -> list[TextChunk]:
    """Chunk a list of extracted pages into TextChunks.

    Each page normally becomes one chunk.  Consecutive short pages
    (< *merge_short* tokens) are merged into a single chunk.  Pages
    exceeding *split_long* tokens are split at heading boundaries.

    No overlap is applied — this is for sequential reading, not RAG.
    """
    if not pages:
        return []

    result: list[TextChunk] = []
    pending_text: list[str] = []
    pending_tokens = 0
    pending_page: int | None = None

    def _flush() -> None:
        nonlocal pending_text, pending_tokens, pending_page
        if not pending_text:
            return
        combined = "\n\n".join(pending_text).strip()
        if combined:
            result.append(
                TextChunk(
                    content=combined,
                    chunk_index=len(result),
                    token_count=len(combined.split()),
                    page_number=pending_page,
                )
            )
        pending_text = []
        pending_tokens = 0
        pending_page = None

    for page in pages:
        text = page.text.strip()
        if not text:
            continue

        tokens = len(text.split())

        # Long page → flush pending, then split at headings
        if tokens > split_long:
            _flush()
            for sub in _split_long_page(text, page.page_number, split_long):
                result.append(
                    TextChunk(
                        content=sub.strip(),
                        chunk_index=len(result),
                        token_count=len(sub.split()),
                        page_number=page.page_number,
                    )
                )
            continue

        # Short page → accumulate with neighbours
        if tokens < merge_short:
            if pending_page is None:
                pending_page = page.page_number
            pending_text.append(text)
            pending_tokens += tokens
            # If accumulated enough, flush
            if pending_tokens >= merge_short:
                _flush()
            continue

        # Normal page → flush pending, emit this page as its own chunk
        _flush()
        result.append(
            TextChunk(
                content=text,
                chunk_index=len(result),
                token_count=tokens,
                page_number=page.page_number,
            )
        )

    _flush()

    # Re-index chunks sequentially
    for i, chunk in enumerate(result):
        chunk.chunk_index = i

    return result


def _split_long_page(
    text: str, page_number: int, max_tokens: int
) -> list[str]:
    """Split a long page's text at heading boundaries.

    Falls back to paragraph boundaries if there are no headings.
    """
    blocks = _segment_into_blocks(text)

    # If segmentation produced only one oversized block, split by paragraphs
    if len(blocks) == 1 and len(blocks[0].split()) > max_tokens:
        paragraphs = text.split("\n\n")
        if len(paragraphs) > 1:
            blocks = [p for p in paragraphs if p.strip()]

    # Merge blocks up to max_tokens (no overlap)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for block in blocks:
        block_tokens = len(block.split())
        if current_parts and current_tokens + block_tokens > max_tokens:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_tokens = 0
        current_parts.append(block)
        current_tokens += block_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


# ── Structure-aware re-chunking ──────────────────────────────────────

_SECTION_MAX_TOKENS = 3000
_SHORT_SECTION_TOKENS = 50


def rechunk_with_structure(
    pages: list[PageData],
    structure: "DocumentStructure",
    max_section_tokens: int = _SECTION_MAX_TOKENS,
) -> list[TextChunk]:
    """Re-chunk pages using LLM structure metadata.

    Uses per-page analysis to:
    - Strip skip_lines (running headers, footers, page numbers)
    - Inject heading markdown prefixes (``# ``, ``## ``, etc.)
    - Merge non-body pages (front_matter, toc) by role
    - Split body content at heading boundaries
    - Split oversized sections at paragraph boundaries

    Returns TextChunk objects.  The caller should set ``chunk_metadata``
    when inserting into the database.
    """
    if not pages or not structure.pages:
        return chunk_by_pages(pages)

    # Detect useless classification (all body, no headings, no skip_lines)
    has_useful = any(
        pa.role != "body" or pa.headings or pa.skip_lines
        for pa in structure.pages
    )
    if not has_useful:
        return chunk_by_pages(pages)

    # Build a lookup from page_number -> analysis
    pa_map = {pa.page: pa for pa in structure.pages}

    # Process each page: strip skip_lines, inject headings
    processed: list[tuple[PageData, str, str]] = []  # (page, text, role)
    for page in pages:
        pa = pa_map.get(page.page_number)
        role = pa.role if pa else "body"
        text = page.text.strip()

        if pa and text:
            text = _strip_skip_lines(text, pa.skip_lines)
            text = _inject_headings(text, pa.headings)

        processed.append((page, text, role))

    # Group pages by role, then split body at heading boundaries
    result: list[TextChunk] = []
    pending_texts: list[str] = []
    pending_page: int = 1
    pending_role: str = ""

    def _flush_pending() -> None:
        nonlocal pending_texts
        if not pending_texts:
            return
        combined = "\n\n".join(
            t for t in pending_texts if t.strip()
        ).strip()
        pending_texts = []
        if not combined:
            return

        if pending_role == "toc":
            # Convert TOC lines into a proper markdown list
            combined = toc_lines_to_markdown(combined)

        if pending_role == "body":
            # Split body content at heading boundaries
            for sub in _split_at_headings(
                combined, max_section_tokens
            ):
                sub = sub.strip()
                if sub:
                    result.append(
                        TextChunk(
                            content=sub,
                            chunk_index=0,
                            token_count=len(sub.split()),
                            page_number=pending_page,
                        )
                    )
        else:
            # Non-body: emit as single chunk (split if too large)
            tokens = len(combined.split())
            if tokens > max_section_tokens:
                for sub in _split_long_page(
                    combined, pending_page, max_section_tokens
                ):
                    sub = sub.strip()
                    if sub:
                        result.append(
                            TextChunk(
                                content=sub,
                                chunk_index=0,
                                token_count=len(sub.split()),
                                page_number=pending_page,
                            )
                        )
            else:
                result.append(
                    TextChunk(
                        content=combined,
                        chunk_index=0,
                        token_count=tokens,
                        page_number=pending_page,
                    )
                )

    for page, text, role in processed:
        if not text.strip():
            continue

        # Role transition → flush
        if role != pending_role and pending_texts:
            _flush_pending()

        if not pending_texts:
            pending_page = page.page_number
            pending_role = role

        pending_texts.append(text)

    _flush_pending()

    # Re-index
    for i, chunk in enumerate(result):
        chunk.chunk_index = i

    return result


def _strip_skip_lines(text: str, skip_lines: list[str]) -> str:
    """Remove lines matching any of the skip_lines patterns."""
    if not skip_lines:
        return text
    skip_set = {s.strip().lower() for s in skip_lines if s.strip()}
    if not skip_set:
        return text
    lines = text.split("\n")
    filtered = [
        line for line in lines
        if line.strip().lower() not in skip_set
    ]
    return "\n".join(filtered)


def _inject_headings(
    text: str, headings: list["PageHeading"]
) -> str:
    """Inject markdown heading prefixes into extracted text.

    Finds lines containing the heading text and prefixes them
    with ``# `` / ``## `` / ``### `` etc.  The LLM identifies
    headings; this function marks them in the extracted text.
    """
    if not headings:
        return text

    lines = text.split("\n")

    for heading in headings:
        prefix = "#" * heading.level + " "
        h_text = heading.text.strip()
        if not h_text:
            continue

        h_lower = h_text.lower()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            s_lower = stripped.lower()
            # Exact match or close substring match
            if s_lower == h_lower:
                lines[i] = prefix + stripped
                break
            if (
                h_lower in s_lower or s_lower in h_lower
            ) and len(stripped) < len(h_text) * 2:
                lines[i] = prefix + stripped
                break

    return "\n".join(lines)


def _split_at_headings(
    text: str, max_tokens: int
) -> list[str]:
    """Split text at markdown heading boundaries.

    Each heading (line starting with ``#``) starts a new chunk.
    Oversized chunks are split at paragraph boundaries.
    Short chunks (< 50 tokens) are merged with the next chunk.
    """
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        if _HEADING_RE.match(line) and current:
            chunks.append("\n".join(current))
            current = []
        current.append(line)

    if current:
        chunks.append("\n".join(current))

    # Split oversized chunks at paragraph boundaries
    split_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk.split()) > max_tokens:
            paragraphs = chunk.split("\n\n")
            parts: list[str] = []
            part_tokens = 0
            for para in paragraphs:
                p_tokens = len(para.split())
                if parts and part_tokens + p_tokens > max_tokens:
                    split_chunks.append("\n\n".join(parts))
                    parts = []
                    part_tokens = 0
                parts.append(para)
                part_tokens += p_tokens
            if parts:
                split_chunks.append("\n\n".join(parts))
        else:
            split_chunks.append(chunk)

    # Merge short chunks with the next one
    merged: list[str] = []
    for chunk in split_chunks:
        if merged and len(merged[-1].split()) < _SHORT_SECTION_TOKENS:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)

    return merged


# ── TOC detection and markdown conversion ─────────────────────────

# Standalone section number on its own line: "1.", "1.2.", "4.2.1."
_SECTION_NUM_RE = re.compile(r"^\d+(?:\.\d+)*\.\s*$")

# Section numbering at start of line for depth extraction: "1.2. Title"
_TOC_DEPTH_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s")

# Title line ending with a page number: "Introduction, 1" or "Cell Culture 42"
_TITLE_WITH_PAGE_RE = re.compile(
    r"^.{2,}[,\s]+(?:[xivlcdm]+|\d+)\s*$",  # roman or arabic page num
    re.IGNORECASE,
)


def _merge_toc_lines(text: str) -> list[str]:
    """Pre-process raw TOC text by joining orphaned section numbers.

    PDF extraction often puts section numbers (``1.2.``) on a separate
    line from the title (``Advantages of Tissue Culture, 6``).  Long
    titles may also wrap across lines.  This function merges them::

        1.2.                           →  1.2. Advantages of Tissue Culture, 6
        Advantages of Tissue Culture, 6

        1.2.4.                         →  1.2.4. In vitro Modeling of In vivo Conditions, 7
        In vitro Modeling of In vivo
        Conditions, 7
    """
    raw_lines = text.split("\n")
    merged: list[str] = []
    buf = ""

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            # Blank line: flush buffer
            if buf:
                merged.append(buf)
                buf = ""
            continue

        if _SECTION_NUM_RE.match(stripped):
            # Flush any previous buffer
            if buf:
                merged.append(buf)
            buf = stripped
        elif buf:
            # We have a pending section number or continuation
            candidate = buf + " " + stripped
            if _TITLE_WITH_PAGE_RE.match(stripped):
                # This line ends with a page number → entry is complete
                merged.append(candidate)
                buf = ""
            else:
                # Title wraps to next line, keep accumulating
                buf = candidate
        else:
            # Standalone line (no pending section number)
            merged.append(stripped)

    if buf:
        merged.append(buf)

    return merged


def toc_lines_to_markdown(text: str) -> str:
    """Convert raw TOC text into a markdown list.

    First merges orphaned section numbers with their titles, then
    converts each entry into a list item with indentation based on
    heading depth.
    """
    lines = _merge_toc_lines(text)
    result: list[str] = []

    for line in lines:
        if line.startswith("#"):
            result.append(line)
            continue

        depth = _toc_entry_depth(line)
        if depth > 0 or _TITLE_WITH_PAGE_RE.match(line):
            indent = "  " * max(0, depth - 1)
            result.append(f"{indent}- {line}")
        else:
            # Non-TOC line (e.g. "Contents" heading)
            result.append(line)

    return "\n".join(result)


def _toc_entry_depth(line: str) -> int:
    """Derive nesting depth from section numbering.

    ``1.`` → 1, ``1.2.`` → 2, ``1.2.3.`` → 3.
    Lines without numbering get depth 0.
    """
    m = _TOC_DEPTH_RE.match(line)
    if not m:
        return 0
    return m.group(1).count(".") + 1
