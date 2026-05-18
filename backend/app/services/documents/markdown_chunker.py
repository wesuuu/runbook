"""Markdown-aware text chunker.

Splits Markdown text into chunks that preserve structural elements:
headings stay with their content, tables are not split mid-row,
code fences are kept intact, and list items are grouped.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.data.text_chunker import PageData, TextChunk, _get_page_number

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
        page_num = _get_page_number(0, page_boundaries) if page_boundaries else None
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
            overlap_text = _get_overlap_from_parts(current_parts, overlap)
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


def _get_overlap_from_parts(parts: list[str], overlap_tokens: int) -> str:
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


def _split_long_page(text: str, page_number: int, max_tokens: int) -> list[str]:
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
