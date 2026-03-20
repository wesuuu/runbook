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

from app.models.library import (
    EMBEDDING_DIMENSIONS,
    Document,
    DocumentChunk,
    DocumentStatus,
)
from app.services.markdown_chunker import chunk_markdown
from app.services.task_runner import get_task_runner
from app.services.text_chunker import chunk_text

logger = logging.getLogger(__name__)


async def process_document(document_id: UUID, db_url: str) -> None:
    """Background task to extract text, chunk, and store for a document.

    Creates its own database session since it runs outside the request
    lifecycle via FastAPI BackgroundTasks.

    This function is idempotent: it deletes any existing chunks before
    re-inserting, so it is safe to re-run after a crash. It uses
    SELECT ... FOR UPDATE SKIP LOCKED to claim the document row,
    preventing two pods from processing the same document concurrently.
    """
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        try:
            # --- Claim the document with a row-level lock ---
            # SKIP LOCKED means if another pod already holds this row,
            # we silently get no result and exit without blocking.
            result = await session.execute(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update(skip_locked=True)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                # Either the document doesn't exist, or another worker
                # already locked it — both are fine, just exit.
                logger.info(
                    "Document %s not found or locked by another worker",
                    document_id,
                )
                return

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
            file_path = Path(doc.file_path)
            text = ""
            page_count = None
            page_boundaries: list[int] | None = None

            try:
                if doc.mime_type == "application/pdf":
                    text, page_count, page_boundaries = (
                        await runner.run_sync(extract_pdf, file_path)
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
                    # Images: store with 0 chunks, Phase 3 adds OCR
                    doc.status = DocumentStatus.INDEXED.value
                    doc.page_count = 0
                    doc.processing_started_at = None
                    await session.commit()
                    return
                else:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = (
                        f"Unsupported MIME type: {doc.mime_type}"
                    )
                    doc.processing_started_at = None
                    await session.commit()
                    return
            except Exception as exc:
                logger.exception(
                    "Extraction failed for document %s", document_id
                )
                doc.status = DocumentStatus.FAILED.value
                doc.error_message = f"Extraction error: {str(exc)[:500]}"
                doc.processing_started_at = None
                await session.commit()
                return

            if not text.strip():
                doc.status = DocumentStatus.INDEXED.value
                doc.page_count = page_count or 0
                doc.processing_started_at = None
                await session.commit()
                return

            # Determine content format based on MIME type
            MARKDOWN_MIMES = {"application/pdf"}
            content_format = (
                "markdown"
                if doc.mime_type in MARKDOWN_MIMES
                else "plaintext"
            )

            # Chunk the extracted text (CPU-bound — offload to thread)
            if content_format == "markdown":
                chunks = await runner.run_sync(
                    chunk_markdown,
                    text,
                    1000,
                    200,
                    page_boundaries,
                )
            else:
                chunks = await runner.run_sync(
                    chunk_text,
                    text,
                    1000,
                    200,
                    page_boundaries,
                )

            # Generate embeddings (best-effort — skip on failure)
            embeddings: list[list[float]] = []
            try:
                from app.services.embedding import embed_texts, EmbeddingError

                chunk_texts = [c.content for c in chunks]
                embeddings = await embed_texts(chunk_texts, session)
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
            await session.commit()

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
                    await session.commit()
            except Exception:
                logger.exception(
                    "Failed to update error status for %s", document_id
                )
        finally:
            await engine.dispose()


def extract_pdf(path: Path) -> tuple[str, int, list[int]]:
    """Extract text from a PDF as Markdown using pymupdf4llm.

    Uses pymupdf4llm.to_markdown() to preserve headings, bold/italic,
    tables, and lists. Falls back to plain pymupdf text extraction
    if pymupdf4llm fails.

    Page boundaries are computed from pymupdf's fast get_text() and
    then scaled proportionally to the markdown text length. This avoids
    calling to_markdown() per-page (which is O(N) and very slow for
    large PDFs).

    Returns:
        Tuple of (markdown_text, page_count, page_boundaries) where
        page_boundaries is a list of character offsets.
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        page_count = len(doc)

        # Always compute fast plain-text page lengths for boundaries
        plain_page_lengths = [len(page.get_text()) for page in doc]
        plain_total = sum(plain_page_lengths)

        # Try pymupdf4llm for Markdown extraction
        try:
            import pymupdf4llm

            md_text = pymupdf4llm.to_markdown(doc)
            md_total = len(md_text)

            # Scale plain-text page boundaries proportionally to
            # markdown length. This is approximate but avoids calling
            # to_markdown() per-page which is extremely slow.
            page_boundaries: list[int] = []
            if plain_total > 0 and page_count > 1:
                offset = 0
                for i in range(page_count - 1):
                    offset += int(
                        plain_page_lengths[i] / plain_total * md_total
                    )
                    page_boundaries.append(offset)

            return md_text, page_count, page_boundaries
        except Exception:
            logger.warning(
                "pymupdf4llm extraction failed for %s, "
                "falling back to plain text",
                path,
            )

        # Fallback: plain pymupdf text extraction
        texts: list[str] = []
        page_boundaries_fallback: list[int] = []
        offset = 0

        for i, page in enumerate(doc):
            page_text = page.get_text()
            if i > 0:
                page_boundaries_fallback.append(offset)
            texts.append(page_text)
            offset += len(page_text)

        full_text = "".join(texts)
        return full_text, page_count, page_boundaries_fallback
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
