"""LLM-guided document structure analysis.

Two-step pipeline:
1. Build a heading outline from sampled page images
2. Classify each page in batches using the outline as context

The LLM never modifies source text — it only produces structural
metadata (heading hierarchy, page roles, lines to strip).
"""

import base64
import json
import logging
from typing import Any, Awaitable, Callable, Literal, Optional

import httpx
from pydantic import BaseModel, Field
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_config import get_full_config, get_model, ModelType

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

BATCH_SIZE = 30  # pages per LLM call
SAMPLE_PAGES = 15  # pages sampled for outline step
LLM_TIMEOUT_SECONDS = 180
CAPABILITY = "doc_structure"

# ── Output models ────────────────────────────────────────────────────

PageRole = Literal[
    "front_matter",
    "toc",
    "body",
    "appendix",
    "index",
    "bibliography",
    "blank",
]


class DocumentOutline(BaseModel):
    """High-level document structure from the initial scan."""

    heading_levels: int = 1
    heading_pattern: str = ""
    front_matter_end_page: int | None = None
    toc_start_page: int | None = None
    toc_end_page: int | None = None
    body_start_page: int | None = None
    running_headers: list[str] = Field(default_factory=list)
    running_footers: list[str] = Field(default_factory=list)


class PageHeading(BaseModel):
    level: int  # 1 = h1, 2 = h2, etc.
    text: str


class PageAnalysis(BaseModel):
    page: int
    role: PageRole = "body"
    layout: str = "single_column"  # single_column | multi_column
    headings: list[PageHeading] = Field(default_factory=list)
    skip_lines: list[str] = Field(default_factory=list)
    has_figure: bool = False


class DocumentStructure(BaseModel):
    outline: DocumentOutline = Field(default_factory=DocumentOutline)
    pages: list[PageAnalysis] = Field(default_factory=list)


# ── Internal model for pydantic-ai structured output ─────────────────


class _BatchResult(BaseModel):
    """Wrapper for batch analysis pydantic-ai output."""

    pages: list[PageAnalysis] = Field(default_factory=list)


# ── Prompts ──────────────────────────────────────────────────────────

_OUTLINE_SYSTEM_PROMPT = """\
You are a document structure analyzer. You will receive images of \
sample pages from a PDF document (not every page — just a \
representative sample).

Analyze these pages to determine the document's overall structure. \
Output a JSON object with:
- heading_levels: number of heading levels used (e.g., 3 for h1/h2/h3)
- heading_pattern: how headings are formatted (e.g., \
"Chapter N. Title for h1, N.N Title for h2, N.N.N Title for h3")
- front_matter_end_page: last page of front matter \
(title, copyright, preface), or null
- toc_start_page: first page of table of contents, or null
- toc_end_page: last page of table of contents, or null
- body_start_page: first page of main body content, or null
- running_headers: list of short repeated header texts at the top of \
many pages
- running_footers: list of repeated footer text patterns \
(e.g., page numbers, book title)

Rules:
- Focus on the BIG PICTURE structure, not individual page details
- running_headers/footers are short text repeated across many pages \
— do NOT include section headings
- If you can't determine a field from the sample, use null or empty list
- Page numbers refer to PDF page numbers (1-indexed), \
not printed page numbers"""

_OUTLINE_JSON_FORMAT = """

Respond with valid JSON matching this schema:
{
  "heading_levels": 3,
  "heading_pattern": "Chapter N. Title for h1, N.N Title for h2",
  "front_matter_end_page": 5,
  "toc_start_page": 6,
  "toc_end_page": 12,
  "body_start_page": 13,
  "running_headers": ["CULTURE OF ANIMAL CELLS"],
  "running_footers": ["page numbers"]
}

Return ONLY the JSON object, no other text."""

_BATCH_SYSTEM_PROMPT = """\
You are a document structure analyzer. Classify each page image \
and identify its headings.

For EACH page, output a JSON object with:
- page: the page number (provided in the user message)
- role: one of "front_matter", "toc", "body", "appendix", \
"index", "bibliography", "blank"
- layout: "single_column" or "multi_column"
- headings: array of heading objects, each with:
  - level: heading level (1=chapter/h1, 2=section/h2, \
3=subsection/h3, etc.)
  - text: the exact heading text as it appears on the page
- skip_lines: array of exact text lines to strip \
(running headers, footers, page numbers)
- has_figure: true if page contains figures, charts, or images

Rules:
- Use the heading pattern from the document outline to assign \
correct heading levels
- Only include actual headings — not body text, figure captions, \
or table titles
- skip_lines should list the exact running header/footer text and \
page numbers on each page
- If a page has no headings, use an empty headings array
- Blank pages should have role "blank" and empty arrays"""

_BATCH_JSON_FORMAT = """

Output ONLY a JSON object with a "pages" array:
{
  "pages": [
    {
      "page": 31,
      "role": "body",
      "layout": "single_column",
      "headings": [
        {"level": 1, "text": "Chapter 3. Laboratory Design"},
        {"level": 2, "text": "3.1 Layout and Services"}
      ],
      "skip_lines": ["LABORATORY DESIGN", "25"],
      "has_figure": false
    }
  ]
}

Return ONLY the JSON object, no other text."""


# ── Main entry point ─────────────────────────────────────────────────

ProgressCallback = Callable[[int, int], Awaitable[None]]


async def analyze_document_structure(
    page_images: dict[int, bytes],
    db: AsyncSession,
    on_progress: ProgressCallback | None = None,
    org_id: "UUID | None" = None,
) -> DocumentStructure:
    """Two-step analysis: build outline, then classify pages in batches.

    Args:
        page_images: Mapping of page_number -> PNG bytes.
        db: Database session for AI config resolution.
        on_progress: Optional async callback(current, total) called
            after each batch completes.

    Returns:
        DocumentStructure with outline and per-page analysis.
        On failure, returns default classifications (all pages = body).
    """
    if not page_images:
        return DocumentStructure()

    model = await get_model(CAPABILITY, db, org_id=org_id)
    config = await get_full_config(CAPABILITY, db, org_id=org_id)

    if not await _check_llm_available(model, config):
        raise RuntimeError(
            "LLM service is not reachable for document structure analysis"
        )

    # Step 2a: Build outline from sampled pages
    outline = await _build_outline(page_images, model, config)
    logger.info(
        "Document outline: %d heading levels, body starts page %s",
        outline.heading_levels,
        outline.body_start_page,
    )

    # Step 2b: Process all pages in batches with outline context
    all_pages = await _analyze_pages_batched(
        page_images, outline, model, config, on_progress
    )

    return DocumentStructure(outline=outline, pages=all_pages)


# ── Sample page selection ────────────────────────────────────────────


def _select_sample_pages(
    page_numbers: list[int], max_samples: int = SAMPLE_PAGES
) -> list[int]:
    """Pick representative pages for the outline step.

    Selects first 5, last 3, and evenly spaced from the middle.
    """
    n = len(page_numbers)
    if n <= max_samples:
        return page_numbers

    selected: set[int] = set()
    for pn in page_numbers[:5]:
        selected.add(pn)
    for pn in page_numbers[-3:]:
        selected.add(pn)

    remaining = max_samples - len(selected)
    middle = page_numbers[5:-3]
    if remaining > 0 and middle:
        step = len(middle) / (remaining + 1)
        for i in range(1, remaining + 1):
            idx = int(i * step)
            if idx < len(middle):
                selected.add(middle[idx])

    return sorted(selected)


# ── Heading tree builder ─────────────────────────────────────────────


def _build_heading_tree(pages: list[PageAnalysis]) -> str:
    """Build a compact heading tree from analyzed pages.

    Returns a string like:
        h1: Chapter 1. Introduction
          h2: 1.1 Historical Background
          h2: 1.2 Advantages
        h1: Chapter 2. Biology
          h2: 2.1 Culture Environment
    """
    lines: list[str] = []
    for pa in pages:
        for h in pa.headings:
            indent = "  " * (h.level - 1)
            lines.append(f"{indent}h{h.level}: {h.text}")
    return "\n".join(lines) if lines else "(no headings identified yet)"


# ── Step 2a: Build outline ───────────────────────────────────────────


async def _build_outline(
    page_images: dict[int, bytes],
    model: ModelType,
    config: dict[str, Any],
) -> DocumentOutline:
    """Build document outline from sampled page images."""
    page_numbers = sorted(page_images.keys())
    sample_pages = _select_sample_pages(page_numbers)
    sample_images = {pn: page_images[pn] for pn in sample_pages}

    try:
        if _is_ollama_model(model):
            return await _outline_ollama(
                sample_pages, sample_images, config
            )
        return await _outline_pydantic_ai(
            sample_pages, sample_images, model
        )
    except Exception:
        logger.exception("Failed to build document outline, using defaults")
        return DocumentOutline()


async def _outline_ollama(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    config: dict[str, Any],
) -> DocumentOutline:
    """Build outline via Ollama's native API."""
    base_url = config.get("base_url") or "http://localhost:11434"
    model_name = config.get("model_name", "llama3.2-vision")

    images_b64 = [
        base64.b64encode(page_images[pn]).decode("utf-8")
        for pn in page_numbers
    ]

    user_text = (
        f"These are {len(page_numbers)} sample pages from a PDF. "
        f"Page numbers: {page_numbers}. "
        "Analyze the document's overall structure."
    )

    messages = [
        {
            "role": "system",
            "content": _OUTLINE_SYSTEM_PROMPT + _OUTLINE_JSON_FORMAT,
        },
        {
            "role": "user",
            "content": user_text,
            "images": images_b64,
        },
    ]

    async with httpx.AsyncClient(
        timeout=LLM_TIMEOUT_SECONDS
    ) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"num_predict": 2048},
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    return _parse_outline_response(content)


async def _outline_pydantic_ai(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    model: ModelType,
) -> DocumentOutline:
    """Build outline via pydantic-ai Agent."""
    agent: Agent[None, DocumentOutline] = Agent(
        model,
        output_type=DocumentOutline,
        instructions=_OUTLINE_SYSTEM_PROMPT,
    )

    user_content: list[Any] = []
    for pn in page_numbers:
        user_content.append(
            BinaryContent(
                data=page_images[pn], media_type="image/png"
            )
        )
    user_content.append(
        f"These are {len(page_numbers)} sample pages from a PDF. "
        f"Page numbers: {page_numbers}. "
        "Analyze the document's overall structure."
    )

    result = await agent.run(user_content)
    return result.output


def _parse_outline_response(content: str) -> DocumentOutline:
    """Parse LLM JSON response into DocumentOutline."""
    try:
        parsed = json.loads(content)
        return DocumentOutline.model_validate(parsed)
    except Exception:
        logger.warning(
            "Failed to parse outline JSON, using defaults"
        )
        return DocumentOutline()


# ── Step 2b: Batch page analysis ─────────────────────────────────────


async def _analyze_pages_batched(
    page_images: dict[int, bytes],
    outline: DocumentOutline,
    model: ModelType,
    config: dict[str, Any],
    on_progress: ProgressCallback | None = None,
) -> list[PageAnalysis]:
    """Process all pages in batches with outline context."""
    page_numbers = sorted(page_images.keys())
    batches = [
        page_numbers[i : i + BATCH_SIZE]
        for i in range(0, len(page_numbers), BATCH_SIZE)
    ]

    all_pages: list[PageAnalysis] = []
    consecutive_failures = 0
    total = len(page_numbers)
    done = 0

    for batch_nums in batches:
        outline_tree = _build_heading_tree(all_pages)
        try:
            batch_images = {n: page_images[n] for n in batch_nums}
            result = await _classify_batch(
                batch_nums,
                batch_images,
                outline,
                outline_tree,
                model,
                config,
            )
            all_pages.extend(result)
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "Batch analysis failed for pages %d-%d",
                batch_nums[0],
                batch_nums[-1],
            )

            if consecutive_failures >= 3:
                logger.error(
                    "Aborting structure analysis after %d "
                    "consecutive batch failures",
                    consecutive_failures,
                )
                raise RuntimeError(
                    f"LLM unavailable: {consecutive_failures} "
                    "consecutive batch failures"
                )

            # Graceful fallback: mark failed pages as body
            for pn in batch_nums:
                all_pages.append(PageAnalysis(page=pn))

        done += len(batch_nums)
        if on_progress:
            await on_progress(done, total)

    return all_pages


def _format_outline_context(outline: DocumentOutline) -> str:
    """Format the outline as compact context for batch prompts."""
    parts = [
        f"Heading levels: {outline.heading_levels}",
        f"Heading pattern: {outline.heading_pattern}",
    ]
    if outline.front_matter_end_page:
        parts.append(
            f"Front matter ends: page {outline.front_matter_end_page}"
        )
    if outline.toc_start_page and outline.toc_end_page:
        parts.append(
            f"TOC: pages {outline.toc_start_page}"
            f"-{outline.toc_end_page}"
        )
    if outline.body_start_page:
        parts.append(f"Body starts: page {outline.body_start_page}")
    if outline.running_headers:
        parts.append(f"Running headers: {outline.running_headers}")
    if outline.running_footers:
        parts.append(f"Running footers: {outline.running_footers}")
    return "\n".join(parts)


async def _classify_batch(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    outline: DocumentOutline,
    outline_tree: str,
    model: ModelType,
    config: dict[str, Any],
) -> list[PageAnalysis]:
    """Classify a batch of pages via the LLM."""
    if _is_ollama_model(model):
        return await _batch_ollama(
            page_numbers, page_images, outline, outline_tree, config
        )
    return await _batch_pydantic_ai(
        page_numbers, page_images, outline, outline_tree, model
    )


async def _batch_ollama(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    outline: DocumentOutline,
    outline_tree: str,
    config: dict[str, Any],
) -> list[PageAnalysis]:
    """Classify batch via Ollama's native API."""
    base_url = config.get("base_url") or "http://localhost:11434"
    model_name = config.get("model_name", "llama3.2-vision")

    images_b64 = [
        base64.b64encode(page_images[pn]).decode("utf-8")
        for pn in page_numbers
    ]

    outline_ctx = _format_outline_context(outline)
    user_text = (
        f"DOCUMENT OUTLINE:\n{outline_ctx}\n\n"
        f"HEADING TREE SO FAR:\n{outline_tree}\n\n"
        f"Classify the following {len(page_numbers)} pages. "
        f"Page numbers: {page_numbers}."
    )

    messages = [
        {
            "role": "system",
            "content": _BATCH_SYSTEM_PROMPT + _BATCH_JSON_FORMAT,
        },
        {
            "role": "user",
            "content": user_text,
            "images": images_b64,
        },
    ]

    async with httpx.AsyncClient(
        timeout=LLM_TIMEOUT_SECONDS
    ) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"num_predict": 4096},
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    return _parse_batch_response(content, page_numbers)


async def _batch_pydantic_ai(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    outline: DocumentOutline,
    outline_tree: str,
    model: ModelType,
) -> list[PageAnalysis]:
    """Classify batch via pydantic-ai Agent."""
    agent: Agent[None, _BatchResult] = Agent(
        model,
        output_type=_BatchResult,
        instructions=_BATCH_SYSTEM_PROMPT,
    )

    outline_ctx = _format_outline_context(outline)
    user_content: list[Any] = []
    for pn in page_numbers:
        user_content.append(
            BinaryContent(
                data=page_images[pn], media_type="image/png"
            )
        )
    user_content.append(
        f"DOCUMENT OUTLINE:\n{outline_ctx}\n\n"
        f"HEADING TREE SO FAR:\n{outline_tree}\n\n"
        f"Classify these {len(page_numbers)} pages. "
        f"Page numbers: {page_numbers}."
    )

    result = await agent.run(user_content)
    return result.output.pages


# ── Response parsing ─────────────────────────────────────────────────


def _parse_batch_response(
    content: str, page_numbers: list[int]
) -> list[PageAnalysis]:
    """Parse LLM JSON response into PageAnalysis objects."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse batch JSON, returning defaults"
        )
        return [PageAnalysis(page=pn) for pn in page_numbers]

    raw_pages = (
        parsed.get("pages", parsed)
        if isinstance(parsed, dict)
        else parsed
    )
    if not isinstance(raw_pages, list):
        logger.warning(
            "Unexpected batch format, returning defaults"
        )
        return [PageAnalysis(page=pn) for pn in page_numbers]

    results: list[PageAnalysis] = []
    seen: set[int] = set()

    for item in raw_pages:
        if not isinstance(item, dict):
            continue
        try:
            pa = PageAnalysis.model_validate(item)
            results.append(pa)
            seen.add(pa.page)
        except Exception:
            logger.debug(
                "Skipping invalid page analysis: %s", item
            )

    # Fill in any missing pages with defaults
    for pn in page_numbers:
        if pn not in seen:
            results.append(PageAnalysis(page=pn))

    return results


# ── Health check ─────────────────────────────────────────────────────


async def _check_llm_available(
    model: ModelType, config: dict[str, Any]
) -> bool:
    """Quick health check to see if the LLM service is reachable."""
    try:
        if _is_ollama_model(model):
            base_url = (
                config.get("base_url") or "http://localhost:11434"
            )
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/api/tags"
                )
                return resp.status_code == 200
        # For cloud providers, assume reachable
        return True
    except Exception:
        logger.warning(
            "LLM health check failed for doc_structure capability"
        )
        return False


def _is_ollama_model(model: ModelType) -> bool:
    if isinstance(model, OpenAIChatModel):
        from pydantic_ai.providers.ollama import OllamaProvider

        return isinstance(model._provider, OllamaProvider)
    if isinstance(model, str) and model.startswith("ollama:"):
        return True
    return False


# ── TOC extraction ──────────────────────────────────────────────────


class TOCEntryResult(BaseModel):
    level: int  # 1 = chapter, 2 = section, 3 = subsection
    text: str
    page_number: int | None = None


class _TOCResult(BaseModel):
    """Wrapper for TOC extraction pydantic-ai output."""

    entries: list[TOCEntryResult] = Field(default_factory=list)


_TOC_SYSTEM_PROMPT = """\
You are a document structure analyzer. You will receive page images \
from a document.

Your task: extract the Table of Contents from these pages. \
If the pages show an actual TOC/Contents listing, extract every \
entry with its hierarchy level, title text, and page number.

If no TOC is present, analyze the document content to create one \
by identifying chapter headings, section headings, and major topics.

For each entry, provide:
- level: 1 for top-level chapters, 2 for sections, 3 for subsections
- text: the exact heading/title text (clean, no trailing dots or leaders)
- page_number: the page number listed in the TOC, or null if unknown

Rules:
- Include entries up to level 3 (skip deeper nesting like 1.2.3.4)
- Clean up the text: remove trailing dots, leaders (....), and \
extra whitespace
- Preserve the original capitalization and wording
- If the page number is in roman numerals, convert to null
- Keep entries in document order"""

_TOC_JSON_FORMAT = """

Output ONLY a JSON object with an "entries" array:
{
  "entries": [
    {"level": 1, "text": "Introduction", "page_number": 1},
    {"level": 2, "text": "Historical Background", "page_number": 1},
    {"level": 2, "text": "Advantages of Tissue Culture", "page_number": 6},
    {"level": 1, "text": "Biology of Cultured Cells", "page_number": 11}
  ]
}

Return ONLY the JSON object, no other text."""


async def extract_toc(
    page_images: dict[int, bytes],
    outline: DocumentOutline,
    structure: "DocumentStructure",
    db: AsyncSession,
    org_id: "UUID | None" = None,
) -> list[dict]:
    """Extract TOC entries from identified TOC pages.

    If the outline identifies TOC pages, sends those page images
    to the LLM for structured extraction. If no TOC pages are
    identified, sends a sample of body pages and asks the LLM
    to generate a TOC from headings.

    Returns a list of dicts with keys: level, text, page_number.
    """
    model = await get_model(CAPABILITY, db, org_id=org_id)
    config = await get_full_config(CAPABILITY, db, org_id=org_id)

    # Determine which pages to send
    toc_page_nums: list[int] = []

    # 1. Use outline's TOC page range
    if outline.toc_start_page and outline.toc_end_page:
        toc_page_nums = [
            p for p in range(
                outline.toc_start_page, outline.toc_end_page + 1
            )
            if p in page_images
        ]

    # 2. Fall back to pages classified as "toc" by the batch analysis
    if not toc_page_nums and structure.pages:
        toc_page_nums = [
            pa.page for pa in structure.pages
            if pa.role == "toc" and pa.page in page_images
        ]

    # 3. No TOC found — send sample body pages for LLM to generate one
    if not toc_page_nums:
        body_pages = [
            pa.page for pa in structure.pages
            if pa.role == "body" and pa.page in page_images
        ]
        toc_page_nums = _select_sample_pages(body_pages, max_samples=10)

    if not toc_page_nums:
        return []

    toc_images = {p: page_images[p] for p in toc_page_nums}

    try:
        if _is_ollama_model(model):
            return await _toc_ollama(toc_page_nums, toc_images, config)
        return await _toc_pydantic_ai(toc_page_nums, toc_images, model)
    except Exception:
        logger.exception("TOC extraction failed")
        return []


async def _toc_ollama(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    config: dict[str, Any],
) -> list[dict]:
    """Extract TOC via Ollama's native API."""
    base_url = config.get("base_url") or "http://localhost:11434"
    model_name = config.get("model_name", "llama3.2-vision")

    images_b64 = [
        base64.b64encode(page_images[pn]).decode("utf-8")
        for pn in page_numbers
    ]

    user_text = (
        f"These are {len(page_numbers)} pages from a document. "
        "Extract the table of contents entries."
    )

    messages = [
        {
            "role": "system",
            "content": _TOC_SYSTEM_PROMPT + _TOC_JSON_FORMAT,
        },
        {
            "role": "user",
            "content": user_text,
            "images": images_b64,
        },
    ]

    async with httpx.AsyncClient(
        timeout=LLM_TIMEOUT_SECONDS
    ) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/chat",
            json={
                "model": model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"num_predict": 8192},
            },
        )
        resp.raise_for_status()

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    return _parse_toc_response(content)


async def _toc_pydantic_ai(
    page_numbers: list[int],
    page_images: dict[int, bytes],
    model: ModelType,
) -> list[dict]:
    """Extract TOC via pydantic-ai Agent."""
    agent: Agent[None, _TOCResult] = Agent(
        model,
        output_type=_TOCResult,
        instructions=_TOC_SYSTEM_PROMPT,
    )

    user_content: list[Any] = []
    for pn in page_numbers:
        user_content.append(
            BinaryContent(
                data=page_images[pn], media_type="image/png"
            )
        )
    user_content.append(
        f"These are {len(page_numbers)} pages from a document. "
        "Extract the table of contents entries."
    )

    result = await agent.run(user_content)
    return [e.model_dump() for e in result.output.entries]


def _parse_toc_response(content: str) -> list[dict]:
    """Parse LLM JSON response into TOC entry dicts."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse TOC JSON")
        return []

    raw_entries = (
        parsed.get("entries", parsed)
        if isinstance(parsed, dict)
        else parsed
    )
    if not isinstance(raw_entries, list):
        return []

    results: list[dict] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        try:
            entry = TOCEntryResult.model_validate(item)
            results.append(entry.model_dump())
        except Exception:
            pass

    return results
