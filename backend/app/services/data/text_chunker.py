from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    token_count: int
    page_number: Optional[int] = None


@dataclass
class PageData:
    """One page of extracted content from a PDF."""

    page_number: int  # 1-indexed
    text: str  # markdown (or plain) text for this page
    has_images: bool = False  # whether the page contains embedded images
    image_bytes: Optional[bytes] = None  # rendered page as PNG (transient, for LLM)


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    page_boundaries: Optional[list[int]] = None,
) -> list[TextChunk]:
    """Split text into overlapping chunks using recursive splitting.

    Tries splitting on paragraph breaks (\\n\\n), then newlines (\\n),
    then sentence endings (. ), then spaces ( ) as a last resort.

    Args:
        text: The text to split.
        chunk_size: Target maximum token count per chunk.
        overlap: Number of tokens to overlap between chunks.
        page_boundaries: List of character offsets where new pages start.

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

    raw_chunks = _recursive_split(text, chunk_size, overlap)
    result: list[TextChunk] = []
    for i, chunk_text_content in enumerate(raw_chunks):
        stripped = chunk_text_content.strip()
        if not stripped:
            continue
        page_num = None
        if page_boundaries:
            # Find the character offset of this chunk in the original text
            char_offset = (
                text.find(stripped[:50]) if len(stripped) >= 50 else text.find(stripped)
            )
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


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Recursively split text, trying separators from most to least ideal."""
    separators = ["\n\n", "\n", ". ", " "]
    return _split_with_separators(text, chunk_size, overlap, separators)


def _split_with_separators(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[str]:
    """Split text using the first separator that produces useful splits."""
    if not separators:
        # Last resort: split by word count
        return _split_by_words(text, chunk_size, overlap)

    sep = separators[0]
    parts = text.split(sep)

    if len(parts) <= 1:
        # This separator doesn't help, try next
        return _split_with_separators(text, chunk_size, overlap, separators[1:])

    chunks: list[str] = []
    current_chunk = ""

    for part in parts:
        candidate = current_chunk + sep + part if current_chunk else part
        if len(candidate.split()) > chunk_size and current_chunk:
            chunks.append(current_chunk)
            # Add overlap from end of previous chunk
            overlap_text = _get_overlap_text(current_chunk, overlap)
            current_chunk = overlap_text + sep + part if overlap_text else part
        else:
            current_chunk = candidate

    if current_chunk.strip():
        chunks.append(current_chunk)

    # If any chunk is still too large, recursively split with next separator
    result: list[str] = []
    for chunk in chunks:
        if len(chunk.split()) > chunk_size * 1.5:
            sub_chunks = _split_with_separators(
                chunk, chunk_size, overlap, separators[1:]
            )
            result.extend(sub_chunks)
        else:
            result.append(chunk)

    return result


def _split_by_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text by word count as a last resort."""
    words = text.split()
    chunks: list[str] = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap if end < len(words) else end

    return chunks


def _get_overlap_text(text: str, overlap_tokens: int) -> str:
    """Get the last N tokens from text for overlap."""
    if overlap_tokens <= 0:
        return ""
    words = text.split()
    if len(words) <= overlap_tokens:
        return text
    return " ".join(words[-overlap_tokens:])


def _get_page_number(char_offset: int, page_boundaries: list[int]) -> int:
    """Determine the page number for a given character offset."""
    page = 1
    for boundary in sorted(page_boundaries):
        if char_offset >= boundary:
            page += 1
        else:
            break
    return page
