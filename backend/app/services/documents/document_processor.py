import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.jobs import BackgroundJob, JobStatus
from app.core.config import settings
from app.services.core.background_jobs import BackgroundJobService
from app.services.core.file_storage import FileStorageService
from app.models.library import (
    EMBEDDING_DIMENSIONS,
    Document,
    DocumentChunk,
    DocumentStatus,
)
from app.services.documents.markdown_chunker import (
    chunk_by_pages,
    chunk_markdown,
    rechunk_with_structure,
)
from app.services.core.task_runner import get_task_runner
from app.services.data.text_chunker import PageData, chunk_text

logger = logging.getLogger(__name__)

# How often to flush progress (every N pages)
_PROGRESS_FLUSH_INTERVAL = 10




async def process_document(document_id: UUID, db_url: str) -> None:
    """Background task to extract text, chunk, and store for a document.

    Creates its own database session since it runs outside the request
    lifecycle via FastAPI BackgroundTasks.

    This function is idempotent: it deletes any existing chunks before
    re-inserting, so it is safe to re-run after a crash. It uses
    SELECT ... FOR UPDATE SKIP LOCKED to claim the document row,
    preventing two pods from processing the same document concurrently.
    """
    # Ensure all models are registered so SQLAlchemy can resolve FKs
    import app.db.base  # noqa: F401

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    job: BackgroundJob | None = None

    async with session_factory() as session:
        try:
            # --- Claim the document with a row-level lock ---
            result = await session.execute(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update(skip_locked=True)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                logger.info(
                    "Document %s not found or locked by another worker",
                    document_id,
                )
                return

            # --- Create a BackgroundJob to track this work ---
            job = await BackgroundJobService.create(
                session, "document_process", "document", document_id,
                input_data={"mime_type": doc.mime_type},
            )

            doc.status = DocumentStatus.PROCESSING.value
            doc.processing_started_at = datetime.now(timezone.utc)
            await session.commit()

            # --- Idempotent: delete any chunks from a prior attempt ---
            await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_id == document_id
                )
            )
            await session.commit()

            # Extract text based on mime type.
            # Extraction and chunking are CPU-bound — offload to
            # the task runner's thread pool so the event loop stays free.
            runner = get_task_runner()
            file_path = FileStorageService().resolve_path(doc.file_path)
            pages: list[PageData] = []
            text = ""
            page_count = None

            try:
                if doc.mime_type == "application/pdf":
                    # Get page count first (fast)
                    page_count = await runner.run_sync(
                        _get_pdf_page_count, file_path
                    )
                    await BackgroundJobService.update_progress(
                        session, job,
                        "extracting", "Extracting text",
                        0, page_count,
                    )

                    # Extract in batches with progress updates
                    pages = []
                    batch_size = _PROGRESS_FLUSH_INTERVAL
                    for batch_start in range(0, page_count, batch_size):
                        batch_end = min(batch_start + batch_size, page_count)
                        batch_pages = await runner.run_sync(
                            _extract_pdf_page_range,
                            file_path,
                            batch_start,
                            batch_end,
                        )
                        pages.extend(batch_pages)
                        await BackgroundJobService.update_progress(
                            session, job,
                            "extracting", "Extracting text",
                            batch_end, page_count,
                        )
                elif doc.mime_type == (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ):
                    text = await runner.run_sync(extract_docx, file_path)
                elif doc.mime_type in (
                    "text/plain",
                    "text/markdown",
                    "application/rtf",
                    "text/html",
                ):
                    text = await runner.run_sync(
                        extract_text_file, file_path
                    )
                elif doc.mime_type.startswith("image/"):
                    doc.status = DocumentStatus.INDEXED.value
                    doc.page_count = 0
                    doc.processing_started_at = None
                    await BackgroundJobService.complete(session, job, output_data={"page_count": 0, "chunk_count": 0})
                    await session.commit()
                    return
                else:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = (
                        f"Unsupported MIME type: {doc.mime_type}"
                    )
                    doc.processing_started_at = None
                    await BackgroundJobService.fail(session, job, doc.error_message)
                    await session.commit()
                    return
            except Exception as exc:
                logger.exception(
                    "Extraction failed for document %s", document_id
                )
                doc.status = DocumentStatus.FAILED.value
                doc.error_message = f"Extraction error: {str(exc)[:500]}"
                doc.processing_started_at = None
                await BackgroundJobService.fail(session, job, doc.error_message)
                await session.commit()
                return

            # --- Chunk extracted content ---
            await BackgroundJobService.update_progress(
                session, job,
                "chunking", "Chunking content",
                0, 1,
            )

            if pages:
                # PDF path: page-level chunking (no overlap)
                content_format = "plaintext"
                all_text = "\n\n".join(p.text for p in pages)
                if not all_text.strip():
                    doc.status = DocumentStatus.INDEXED.value
                    doc.page_count = page_count or 0
                    doc.processing_started_at = None
                    await BackgroundJobService.complete(session, job, output_data={
                        "page_count": page_count, "chunk_count": 0
                    })
                    await session.commit()
                    return

                chunks = await runner.run_sync(chunk_by_pages, pages)
            else:
                # Non-PDF path: token-based chunking with overlap
                if not text.strip():
                    doc.status = DocumentStatus.INDEXED.value
                    doc.page_count = 0
                    doc.processing_started_at = None
                    await BackgroundJobService.complete(session, job, output_data={"page_count": 0, "chunk_count": 0})
                    await session.commit()
                    return

                if doc.mime_type == "text/markdown":
                    content_format = "markdown"
                    chunks = await runner.run_sync(
                        chunk_markdown, text, 1000, 200, None
                    )
                else:
                    content_format = "plaintext"
                    chunks = await runner.run_sync(
                        chunk_text, text, 1000, 200, None
                    )

            # Generate embeddings (best-effort — skip on failure)
            await BackgroundJobService.update_progress(
                session, job,
                "embedding", "Generating embeddings",
                0, len(chunks),
            )
            embeddings: list[list[float]] = []
            try:
                from app.services.ai.embedding import embed_texts

                async def _emb_progress(current: int, total: int) -> None:
                    await BackgroundJobService.update_progress(
                        session, job,
                        "embedding", "Generating embeddings",
                        current, total,
                    )

                chunk_texts = [c.content for c in chunks]
                embeddings = await embed_texts(
                    chunk_texts, session, on_progress=_emb_progress,
                    org_id=doc.org_id,
                )
            except Exception as emb_err:
                logger.warning(
                    "Embedding generation failed for document %s, "
                    "indexing without embeddings: %s",
                    document_id,
                    str(emb_err)[:200],
                )

            # Bulk insert chunks (with embeddings if available)
            chunk_meta = {"content_format": content_format}
            for i, chunk in enumerate(chunks):
                emb = None
                if i < len(embeddings):
                    emb = _pad_embedding(embeddings[i])
                db_chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    chunk_metadata=chunk_meta,
                    embedding=emb,
                )
                session.add(db_chunk)

            doc.status = DocumentStatus.INDEXED.value
            doc.page_count = page_count
            doc.processing_started_at = None

            # Extract PDF bookmarks for sidebar TOC
            if doc.mime_type == "application/pdf":
                try:
                    pdf_toc = await runner.run_sync(
                        _extract_pdf_toc, file_path
                    )
                    if pdf_toc:
                        doc.structure_metadata = {
                            **(doc.structure_metadata or {}),
                            "toc": pdf_toc,
                        }
                except Exception:
                    logger.debug(
                        "Could not extract PDF TOC for %s",
                        document_id,
                    )

            await BackgroundJobService.complete(session, job, output_data={
                "page_count": page_count,
                "chunk_count": len(chunks),
            })
            await session.commit()

            # --- Submit async enrichment if LLM is configured ---
            if doc.mime_type == "application/pdf":
                try:
                    from app.services.ai.ai_config import get_full_config

                    cfg = await get_full_config("doc_structure", session, org_id=doc.org_id)
                    if cfg.get("is_enabled", True):
                        get_task_runner().submit(
                            enrich_document(document_id, db_url)
                        )
                        logger.info(
                            "Submitted enrichment job for document %s",
                            document_id,
                        )
                except Exception:
                    logger.debug(
                        "Skipping enrichment for %s (config unavailable)",
                        document_id,
                    )

        except Exception as exc:
            logger.exception(
                "Processing failed for document %s", document_id
            )
            try:
                await session.rollback()
                result = await session.execute(
                    select(Document).where(Document.id == document_id)
                )
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = f"Processing error: {str(exc)[:500]}"
                    doc.processing_started_at = None
                if job:
                    # Re-fetch job since we rolled back
                    job_result = await session.execute(
                        select(BackgroundJob).where(
                            BackgroundJob.id == job.id
                        )
                    )
                    job = job_result.scalar_one_or_none()
                    if job:
                        await BackgroundJobService.fail(session, job, str(exc)[:500])
                await session.commit()
            except Exception:
                logger.exception(
                    "Failed to update error status for %s", document_id
                )
        finally:
            await engine.dispose()


def _get_pdf_page_count(path: Path) -> int:
    """Quickly get the number of pages in a PDF without extracting text."""
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


def _extract_pdf_toc(path: Path) -> list[dict]:
    """Extract PDF bookmarks/outline as a TOC list.

    Uses pymupdf's ``get_toc()`` which reads the PDF's built-in
    outline entries (bookmarks). Returns a list of dicts matching
    the ``TOCEntry`` schema.
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        raw_toc = doc.get_toc()
        if not raw_toc:
            return []
        return [
            {
                "level": level,
                "text": title.strip(),
                "page_number": page,
                "chunk_index": None,
            }
            for level, title, page in raw_toc
            if title.strip()
        ]
    finally:
        doc.close()


def _extract_page_text(page) -> str:
    """Extract text from a PDF page with correct word spacing.

    Some PDFs use character positioning (kerning) instead of explicit
    space characters between words.  Plain ``page.get_text()`` merges
    these into concatenated strings like ``OFANIMALCELLS``.

    This function uses pymupdf's ``rawdict`` output to examine the
    gap between consecutive characters.  When the gap exceeds a
    threshold relative to the font size, a space is inserted.
    Falls back to ``page.get_text()`` if character data is
    unavailable.
    """
    try:
        d = page.get_text("rawdict")
    except Exception:
        return page.get_text()

    block_texts: list[str] = []

    for block in d.get("blocks", []):
        if block.get("type") != 0:  # skip image blocks
            continue

        line_texts: list[str] = []
        for line in block.get("lines", []):
            chars: list[str] = []
            prev_end: float | None = None

            for span in line.get("spans", []):
                span_chars = span.get("chars")
                if not span_chars:
                    # rawdict always has chars, but guard anyway
                    chars.append(span.get("text", ""))
                    if span.get("bbox"):
                        prev_end = span["bbox"][2]
                    continue

                font_size = span.get("size", 12)
                # Threshold: gap > 10% of font size → word boundary.
                # PDFs without explicit space chars use ~11-14% of
                # font size for word gaps; intra-word gaps are 0.
                space_thresh = max(font_size * 0.10, 1.0)

                for c in span_chars:
                    c_x0 = c["bbox"][0]
                    if prev_end is not None:
                        gap = c_x0 - prev_end
                        if gap > space_thresh:
                            chars.append(" ")
                    chars.append(c["c"])
                    prev_end = c["bbox"][2]

            line_text = "".join(chars)
            if line_text.strip():
                line_texts.append(line_text)

        if line_texts:
            block_texts.append("\n".join(line_texts))

    return "\n\n".join(block_texts) if block_texts else page.get_text()


def _extract_pdf_page_range(
    path: Path, start: int, end: int
) -> list[PageData]:
    """Extract a range of pages [start, end) from a PDF.

    Uses character-level positioning to reconstruct word spacing
    that plain ``page.get_text()`` misses.  Page images are rendered
    for the LLM enrichment pass.
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        pages: list[PageData] = []
        for i in range(start, min(end, len(doc))):
            page = doc[i]
            has_images = len(page.get_images(full=True)) > 0
            text = _extract_page_text(page)

            # Render page image for LLM classification
            image_bytes = None
            try:
                pix = page.get_pixmap(dpi=PAGE_IMAGE_DPI)
                image_bytes = pix.tobytes("png")
            except Exception:
                pass

            pages.append(
                PageData(
                    page_number=i + 1,
                    text=text.strip() if text else "",
                    has_images=has_images,
                    image_bytes=image_bytes,
                )
            )
        return pages
    finally:
        doc.close()


PAGE_IMAGE_DPI = 150  # Resolution for rendering page images for LLM


def extract_pdf_pages(
    path: Path, render_images: bool = True
) -> list[PageData]:
    """Extract text from a PDF page-by-page using plain pymupdf.

    Uses ``page.get_text()`` for each page, which handles columns
    correctly and is fast. When *render_images* is True (default),
    each page is also rendered as a PNG for the LLM structure
    classifier.

    Returns:
        List of PageData objects, one per PDF page (1-indexed).
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        page_count = len(doc)
        pages: list[PageData] = []

        for i in range(page_count):
            page = doc[i]
            has_images = len(page.get_images(full=True)) > 0
            text = _extract_page_text(page)

            # Render page as PNG for LLM classification
            image_bytes = None
            if render_images:
                try:
                    pix = page.get_pixmap(dpi=PAGE_IMAGE_DPI)
                    image_bytes = pix.tobytes("png")
                except Exception:
                    logger.debug(
                        "Failed to render page %d as image", i + 1
                    )

            pages.append(
                PageData(
                    page_number=i + 1,
                    text=text.strip() if text else "",
                    has_images=has_images,
                    image_bytes=image_bytes,
                )
            )

        return pages
    finally:
        doc.close()


def extract_docx(path: Path) -> str:
    """Extract text from a DOCX file using python-docx."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def extract_text_file(path: Path) -> str:
    """Extract text from a plain text file."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _pad_embedding(
    embedding: list[float],
) -> list[float]:
    """Pad or truncate an embedding to EMBEDDING_DIMENSIONS.

    Different models produce different dimensions (e.g., nomic-embed-text
    produces 768d, OpenAI text-embedding-3-small produces 1536d). The
    database column is fixed at EMBEDDING_DIMENSIONS. Shorter vectors
    are zero-padded; longer vectors are truncated.
    """
    if len(embedding) == EMBEDDING_DIMENSIONS:
        return embedding
    if len(embedding) < EMBEDDING_DIMENSIONS:
        return embedding + [0.0] * (
            EMBEDDING_DIMENSIONS - len(embedding)
        )
    return embedding[:EMBEDDING_DIMENSIONS]


# ── Enrichment pipeline ──────────────────────────────────────────────


async def enrich_document(document_id: UUID, db_url: str) -> None:
    """Async second pass: LLM-guided structure analysis.

    Two-step pipeline:
    1. Build a heading outline from sampled page images
    2. Classify each page in batches using the outline as context
    3. Re-chunk using the structure metadata (heading injection,
       skip_lines stripping, heading-boundary chunking)

    The document is already readable at this point (status=INDEXED).
    This just makes it better. If it fails, the document stays INDEXED.
    """
    from app.services.documents.document_structure import analyze_document_structure

    import app.db.base  # noqa: F401

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        job: BackgroundJob | None = None
        try:
            # Load document
            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                logger.info(
                    "Document %s not found for enrichment",
                    document_id,
                )
                return

            if doc.mime_type != "application/pdf":
                logger.info(
                    "Skipping enrichment for non-PDF document %s",
                    document_id,
                )
                return

            # Create tracking job
            job = await BackgroundJobService.create(
                session, "document_enrich", "document", document_id,
                input_data={"mime_type": doc.mime_type},
            )
            await session.commit()

            # Re-extract pages with images (CPU-bound → thread pool)
            runner = get_task_runner()
            file_path = FileStorageService().resolve_path(doc.file_path)

            total_pages = doc.page_count or 0
            await BackgroundJobService.update_progress(
                session, job,
                "rendering", "Rendering page images",
                0, total_pages,
            )

            pages: list[PageData] = []
            batch_size = _PROGRESS_FLUSH_INTERVAL
            for batch_start in range(0, total_pages, batch_size):
                batch_end = min(batch_start + batch_size, total_pages)
                batch_pages = await runner.run_sync(
                    _extract_pdf_page_range,
                    file_path,
                    batch_start,
                    batch_end,
                )
                pages.extend(batch_pages)
                await BackgroundJobService.update_progress(
                    session, job,
                    "rendering", "Rendering page images",
                    batch_end, total_pages,
                )

            # Build page_images dict for LLM
            page_images: dict[int, bytes] = {}
            for page in pages:
                if page.image_bytes:
                    page_images[page.page_number] = page.image_bytes

            if not page_images:
                logger.warning(
                    "No page images available for document %s, "
                    "skipping enrichment",
                    document_id,
                )
                await BackgroundJobService.complete(session, job, output_data={
                    "skipped": True, "reason": "no_images"
                })
                await session.commit()
                return

            # Step 1: Signal outline stage
            await BackgroundJobService.update_progress(
                session, job,
                "outline", "Building document outline",
                0, 1,
            )

            # Step 2: Analyze structure (outline + batched pages)
            async def _analyze_progress(
                current: int, total: int
            ) -> None:
                await BackgroundJobService.update_progress(
                    session, job,
                    "analyzing", "Analyzing pages",
                    current, total,
                )

            structure = await analyze_document_structure(
                page_images, session,
                on_progress=_analyze_progress,
                org_id=doc.org_id,
            )

            # Store structure metadata on document
            doc.structure_metadata = structure.model_dump()

            # Step 3: Re-chunk using structure metadata
            await BackgroundJobService.update_progress(
                session, job,
                "rechunking", "Re-chunking document",
                0, 1,
            )

            new_chunks = await runner.run_sync(
                rechunk_with_structure, pages, structure
            )

            if new_chunks:
                # Delete existing chunks and insert structure-aware ones
                await session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.document_id == document_id
                    )
                )

                # Build role/section lookup from structure
                pa_map = {pa.page: pa for pa in structure.pages}
                chunk_meta_base = {"content_format": "markdown"}

                for chunk in new_chunks:
                    pa = pa_map.get(chunk.page_number)
                    section_heading = None
                    if pa and pa.headings:
                        section_heading = pa.headings[0].text
                    meta = {
                        **chunk_meta_base,
                        "role": pa.role if pa else "body",
                        "section_heading": section_heading,
                    }
                    db_chunk = DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        page_number=chunk.page_number,
                        chunk_metadata=meta,
                    )
                    session.add(db_chunk)

            doc.status = DocumentStatus.ENRICHED.value

            await BackgroundJobService.complete(session, job, output_data={
                "pages_analyzed": len(structure.pages),
                "chunks_created": (
                    len(new_chunks) if new_chunks else 0
                ),
                "heading_levels": (
                    structure.outline.heading_levels
                ),
                "roles": list(
                    {p.role for p in structure.pages}
                ),
            })
            await session.commit()

            logger.info(
                "Enrichment complete for document %s: "
                "%d pages analyzed, %d heading levels",
                document_id,
                len(structure.pages),
                structure.outline.heading_levels,
            )

        except Exception as exc:
            logger.exception(
                "Enrichment failed for document %s", document_id
            )
            try:
                await session.rollback()
                if job:
                    job_result = await session.execute(
                        select(BackgroundJob).where(
                            BackgroundJob.id == job.id
                        )
                    )
                    job = job_result.scalar_one_or_none()
                    if job:
                        await BackgroundJobService.fail(session, job, str(exc)[:500])
                await session.commit()
            except Exception:
                logger.exception(
                    "Failed to update enrichment error for %s",
                    document_id,
                )
        finally:
            await engine.dispose()



def _build_toc_from_structure(
    structure: "DocumentStructure",
) -> list[dict]:
    """Build a flat TOC array from the LLM structure analysis.

    Extracts all headings from page analyses and returns them
    as a list of dicts ready for JSON storage.
    """
    from app.services.documents.document_structure import DocumentStructure

    toc: list[dict] = []
    for pa in structure.pages:
        for h in pa.headings:
            toc.append({
                "level": h.level,
                "text": h.text,
                "page_number": pa.page,
                "chunk_index": None,  # filled in after chunking
            })
    return toc


def _assign_toc_chunk_indices(
    toc: list[dict], chunks: list, pages: list[PageData]
) -> list[dict]:
    """Map each TOC entry's page_number to the chunk_index
    that contains that page's content."""
    # Build page -> chunk_index lookup from chunks
    page_to_chunk: dict[int, int] = {}
    for chunk in chunks:
        pn = chunk.page_number
        if pn and pn not in page_to_chunk:
            page_to_chunk[pn] = chunk.chunk_index

    for entry in toc:
        pn = entry.get("page_number")
        if pn and pn in page_to_chunk:
            entry["chunk_index"] = page_to_chunk[pn]

    return toc


# ── Unified book builder pipeline ───────────────────────────────────


async def build_book(document_id: UUID, db_url: str) -> None:
    """Single-pass document processing pipeline.

    Combines extraction, LLM structure analysis, and assembly
    into one pipeline. The LLM is required for PDFs — if
    unavailable, the document is set to QUEUED for later retry.

    Stages:
    1. Extract text + render/store page images
    2. LLM: build outline (or QUEUED if unavailable)
    3. LLM: classify pages in batches
    4. Assemble: strip noise, inject headings, build TOC, re-chunk
    5. Generate embeddings
    """
    import app.db.base  # noqa: F401
    from app.services.documents.document_structure import (
        DocumentStructure,
        analyze_document_structure,
    )

    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    job: BackgroundJob | None = None

    async with session_factory() as session:
        try:
            # --- Claim the document with a row-level lock ---
            result = await session.execute(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update(skip_locked=True)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                logger.info(
                    "Document %s not found or locked by another worker",
                    document_id,
                )
                return

            # --- Create tracking job ---
            job = await BackgroundJobService.create(
                session, "document_build_book", "document", document_id,
                input_data={"mime_type": doc.mime_type},
            )

            doc.status = DocumentStatus.PROCESSING.value
            doc.processing_started_at = datetime.now(timezone.utc)
            await session.commit()

            # --- Idempotent: delete prior chunks ---
            await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_id == document_id
                )
            )
            await session.commit()

            # ─── Stage 1: Extract text + render page images ─────────
            runner = get_task_runner()
            file_path = FileStorageService().resolve_path(doc.file_path)
            pages: list[PageData] = []
            text = ""
            page_count = None
            is_pdf = doc.mime_type == "application/pdf"

            try:
                if is_pdf:
                    page_count = await runner.run_sync(
                        _get_pdf_page_count, file_path
                    )
                    await BackgroundJobService.update_progress(
                        session, job,
                        "extracting", "Extracting text & rendering pages",
                        0, page_count,
                    )

                    batch_size = _PROGRESS_FLUSH_INTERVAL
                    for batch_start in range(0, page_count, batch_size):
                        batch_end = min(
                            batch_start + batch_size, page_count
                        )
                        batch_pages = await runner.run_sync(
                            _extract_pdf_page_range,
                            file_path, batch_start, batch_end,
                        )
                        pages.extend(batch_pages)
                        await BackgroundJobService.update_progress(
                            session, job,
                            "extracting",
                            "Extracting text & rendering pages",
                            batch_end, page_count,
                        )

                elif doc.mime_type == (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ):
                    text = await runner.run_sync(extract_docx, file_path)
                elif doc.mime_type in (
                    "text/plain", "text/markdown",
                    "application/rtf", "text/html",
                ):
                    text = await runner.run_sync(
                        extract_text_file, file_path
                    )
                elif doc.mime_type.startswith("image/"):
                    doc.status = DocumentStatus.READY.value
                    doc.page_count = 0
                    doc.processing_started_at = None
                    await BackgroundJobService.complete(session, job, output_data={
                        "page_count": 0, "chunk_count": 0
                    })
                    await session.commit()
                    return
                else:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = (
                        f"Unsupported MIME type: {doc.mime_type}"
                    )
                    doc.processing_started_at = None
                    await BackgroundJobService.fail(session, job, doc.error_message)
                    await session.commit()
                    return
            except Exception as exc:
                logger.exception(
                    "Extraction failed for document %s", document_id
                )
                doc.status = DocumentStatus.FAILED.value
                doc.error_message = (
                    f"Extraction error: {str(exc)[:500]}"
                )
                doc.processing_started_at = None
                await BackgroundJobService.fail(session, job, doc.error_message)
                await session.commit()
                return

            # Check for empty content
            if is_pdf:
                all_text = "\n\n".join(p.text for p in pages)
                if not all_text.strip():
                    doc.status = DocumentStatus.READY.value
                    doc.page_count = page_count or 0
                    doc.processing_started_at = None
                    await BackgroundJobService.complete(session, job, output_data={
                        "page_count": page_count, "chunk_count": 0
                    })
                    await session.commit()
                    return
            elif not text.strip():
                doc.status = DocumentStatus.READY.value
                doc.page_count = 0
                doc.processing_started_at = None
                await BackgroundJobService.complete(session, job, output_data={"page_count": 0, "chunk_count": 0})
                await session.commit()
                return

            # ─── Stages 2-3: LLM structure analysis (PDF only) ─────
            structure: DocumentStructure | None = None
            toc: list[dict] = []

            if is_pdf:
                # Build page_images dict for LLM
                page_images: dict[int, bytes] = {}
                for page in pages:
                    if page.image_bytes:
                        page_images[page.page_number] = page.image_bytes

                if page_images:
                    # Check LLM availability
                    from app.services.ai.ai_config import (
                        get_full_config, get_model,
                    )
                    from app.services.documents.document_structure import (
                        _check_llm_available, _is_ollama_model,
                    )

                    try:
                        model = await get_model("doc_structure", session, org_id=doc.org_id)
                        config = await get_full_config(
                            "doc_structure", session, org_id=doc.org_id
                        )
                        llm_ok = await _check_llm_available(model, config)
                    except Exception:
                        llm_ok = False

                    if not llm_ok:
                        # LLM unavailable → queue for later
                        logger.info(
                            "LLM unavailable, queueing document %s",
                            document_id,
                        )
                        doc.status = DocumentStatus.QUEUED.value
                        doc.processing_started_at = None
                        doc.page_count = page_count
                        await BackgroundJobService.complete(session, job, output_data={
                            "queued": True,
                            "reason": "llm_unavailable",
                            "page_count": page_count,
                        })
                        await session.commit()
                        return

                    # LLM is available — run structure analysis
                    await BackgroundJobService.update_progress(
                        session, job,
                        "outline", "Building document outline",
                        0, 1,
                    )

                    async def _analyze_progress(
                        current: int, total: int
                    ) -> None:
                        await BackgroundJobService.update_progress(
                            session, job,
                            "classifying", "Analyzing pages",
                            current, total,
                        )

                    try:
                        structure = await analyze_document_structure(
                            page_images, session,
                            on_progress=_analyze_progress,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Structure analysis failed for %s, "
                            "continuing without: %s",
                            document_id, str(exc)[:200],
                        )
                        structure = None

                    # Extract TOC via LLM (separate, focused call)
                    if structure:
                        await BackgroundJobService.update_progress(
                            session, job,
                            "toc", "Extracting table of contents",
                            0, 1,
                        )
                        try:
                            from app.services.documents.document_structure import (
                                extract_toc,
                            )
                            toc = await extract_toc(
                                page_images,
                                structure.outline,
                                structure,
                                session,
                                org_id=doc.org_id,
                            )
                        except Exception as toc_exc:
                            logger.warning(
                                "TOC extraction failed for %s, "
                                "falling back to headings: %s",
                                document_id,
                                str(toc_exc)[:200],
                            )
                            toc = _build_toc_from_structure(
                                structure
                            )

            # ─── Stage 4: Assemble — chunk + build TOC ─────────────
            await BackgroundJobService.update_progress(
                session, job,
                "assembling", "Assembling document",
                0, 1,
            )

            if is_pdf and structure and structure.pages:
                # Structure-aware re-chunking
                new_chunks = await runner.run_sync(
                    rechunk_with_structure, pages, structure
                )

                if new_chunks:
                    pa_map = {
                        pa.page: pa for pa in structure.pages
                    }
                    chunk_meta_base = {"content_format": "markdown"}

                    for chunk in new_chunks:
                        pa = pa_map.get(chunk.page_number)
                        section_heading = None
                        if pa and pa.headings:
                            section_heading = pa.headings[0].text
                        meta = {
                            **chunk_meta_base,
                            "role": pa.role if pa else "body",
                            "section_heading": section_heading,
                        }
                        db_chunk = DocumentChunk(
                            document_id=document_id,
                            chunk_index=chunk.chunk_index,
                            content=chunk.content,
                            token_count=chunk.token_count,
                            page_number=chunk.page_number,
                            chunk_metadata=meta,
                        )
                        session.add(db_chunk)

                    # Assign chunk indices to TOC entries
                    toc = _assign_toc_chunk_indices(
                        toc, new_chunks, pages
                    )
                    chunks_for_embed = new_chunks
                else:
                    # Fallback to page-level chunking
                    chunks_for_embed = await runner.run_sync(
                        chunk_by_pages, pages
                    )
                    for chunk in chunks_for_embed:
                        db_chunk = DocumentChunk(
                            document_id=document_id,
                            chunk_index=chunk.chunk_index,
                            content=chunk.content,
                            token_count=chunk.token_count,
                            page_number=chunk.page_number,
                            chunk_metadata={
                                "content_format": "plaintext"
                            },
                        )
                        session.add(db_chunk)
            elif is_pdf:
                # PDF without structure — page-level chunking
                chunks_for_embed = await runner.run_sync(
                    chunk_by_pages, pages
                )
                for chunk in chunks_for_embed:
                    db_chunk = DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        page_number=chunk.page_number,
                        chunk_metadata={
                            "content_format": "plaintext"
                        },
                    )
                    session.add(db_chunk)
            else:
                # Non-PDF: use markdown chunker for .md files,
                # plain text chunker for everything else
                is_markdown = doc.mime_type == "text/markdown"
                if is_markdown:
                    content_format = "markdown"
                    chunks_for_embed = await runner.run_sync(
                        chunk_markdown, text, 1000, 200, None
                    )
                else:
                    content_format = "plaintext"
                    chunks_for_embed = await runner.run_sync(
                        chunk_text, text, 1000, 200, None
                    )
                for chunk in chunks_for_embed:
                    db_chunk = DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        token_count=chunk.token_count,
                        page_number=chunk.page_number,
                        chunk_metadata={
                            "content_format": content_format
                        },
                    )
                    session.add(db_chunk)

            # ─── Stage 5: Generate embeddings ──────────────────────
            await BackgroundJobService.update_progress(
                session, job,
                "embedding", "Generating embeddings",
                0, len(chunks_for_embed),
            )

            embeddings: list[list[float]] = []
            try:
                from app.services.ai.embedding import embed_texts

                async def _emb_progress(
                    current: int, total: int
                ) -> None:
                    await BackgroundJobService.update_progress(
                        session, job,
                        "embedding", "Generating embeddings",
                        current, total,
                    )

                chunk_texts = [c.content for c in chunks_for_embed]
                embeddings = await embed_texts(
                    chunk_texts, session, on_progress=_emb_progress,
                    org_id=doc.org_id,
                )
            except Exception as emb_err:
                logger.warning(
                    "Embedding generation failed for document %s: %s",
                    document_id, str(emb_err)[:200],
                )

            # Apply embeddings to chunks already added to session
            if embeddings:
                # Flush to get the chunks into the session
                await session.flush()
                # Fetch chunks back to apply embeddings
                chunk_result = await session.execute(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == document_id
                    )
                    .order_by(DocumentChunk.chunk_index)
                )
                db_chunks = list(chunk_result.scalars().all())
                for i, db_chunk in enumerate(db_chunks):
                    if i < len(embeddings):
                        db_chunk.embedding = _pad_embedding(
                            embeddings[i]
                        )

            # ─── Finalize ──────────────────────────────────────────
            doc.status = DocumentStatus.READY.value
            doc.page_count = page_count
            doc.processing_started_at = None

            # Store structure metadata with TOC
            if structure:
                sm = structure.model_dump()
                sm["toc"] = toc
                doc.structure_metadata = sm
            elif toc:
                doc.structure_metadata = {"toc": toc}

            await BackgroundJobService.complete(session, job, output_data={
                "page_count": page_count,
                "chunk_count": len(chunks_for_embed),
                "has_toc": len(toc) > 0,
                "has_structure": structure is not None,
            })
            await session.commit()

            logger.info(
                "Book build complete for document %s: "
                "%d chunks, %d TOC entries",
                document_id,
                len(chunks_for_embed),
                len(toc),
            )

        except Exception as exc:
            logger.exception(
                "build_book failed for document %s", document_id
            )
            try:
                await session.rollback()
                result = await session.execute(
                    select(Document).where(
                        Document.id == document_id
                    )
                )
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = (
                        f"Processing error: {str(exc)[:500]}"
                    )
                    doc.processing_started_at = None
                if job:
                    job_result = await session.execute(
                        select(BackgroundJob).where(
                            BackgroundJob.id == job.id
                        )
                    )
                    job = job_result.scalar_one_or_none()
                    if job:
                        await BackgroundJobService.fail(session, job, str(exc)[:500])
                await session.commit()
            except Exception:
                logger.exception(
                    "Failed to update error status for %s",
                    document_id,
                )
        finally:
            await engine.dispose()
