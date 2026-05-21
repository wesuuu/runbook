import json
import logging
import os
import re
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.config import settings
from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.library import (
    ALLOWED_DOCUMENT_TYPES,
    MAX_DOCUMENT_SIZE_BYTES,
    MIME_EXTENSION_MAP,
    Document,
    DocumentChunk,
    DocumentStatus,
    validate_file_content,
)
from app.schemas.jobs import ProcessingProgress
from app.schemas.library import (
    DocumentChunkResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    ImportUrlRequest,
    MarkdownPayload,
    ProcessingAuditResponse,
    ProcessingJobAudit,
    RefineCompleteRequest,
    SearchResponse,
    SearchResultGroup,
    SearchResultItem,
    TOCEntry,
)
from app.services.core.audit import log_audit
from app.services.core.background_handler import get_background_handler
from app.services.core.background_jobs import BackgroundJobService
from app.services.core.file_storage import FileStorageService
from app.services.core.permissions import check_permission

# Side-effect imports: @register_job decorators populate JOB_REGISTRY.
from app.services.documents.extraction import extract_job  # noqa: F401
from app.services.documents.extraction.source_page import render_source_page
from app.services.documents.refinement import index_job  # noqa: F401
from app.services.documents.refinement.refinement_service import (
    mark_complete,
    reopen,
    save_markdown,
)
from app.services.protocols.url_importer import import_from_url
from app.services.slugs import assign_slug_or_422

router = APIRouter()


async def _can_delete_document(
    db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> bool:
    """Check if user has EDIT permission on a document (required for delete)."""
    return await check_permission(
        db,
        user_id,
        ObjectType.DOCUMENT,
        document_id,
        PermissionLevel.EDIT,
    )


async def _get_user_org_id(user: User, db: AsyncSession) -> uuid.UUID:
    """Resolve the user's organization ID from their membership."""
    result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(
            status_code=403,
            detail="User is not a member of any organization",
        )
    return org_id


def _sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal and special chars."""
    # Remove path separators and null bytes
    clean = filename.replace("\x00", "").replace("/", "_").replace("\\", "_")
    # Remove .. sequences
    clean = clean.replace("..", "_")
    # Strip leading/trailing whitespace and dots
    clean = clean.strip(". ")
    # Remove non-printable characters
    clean = re.sub(r"[^\w.\- ]", "_", clean)
    return clean or "unnamed"


def _validate_extension_matches_mime(filename: str, mime_type: str) -> bool:
    """Validate that the file extension matches the claimed MIME type."""
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        return True  # No extension — can't validate
    allowed_exts = MIME_EXTENSION_MAP.get(mime_type)
    if allowed_exts is None:
        return True  # Unknown MIME type — skip check
    return ext in allowed_exts


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    title: str = Form(...),
    project_id: Optional[uuid.UUID] = Form(None),
    tags: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    org_id = await _get_user_org_id(current_user, db)

    # Title length check
    if len(title) > 150:
        raise HTTPException(
            status_code=422,
            detail="Title must be 150 characters or fewer.",
        )

    # Read file content into memory for validation
    content = await file.read()

    # Size check
    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large: {len(content)} bytes "
                f"(max {MAX_DOCUMENT_SIZE_BYTES})"
            ),
        )

    # MIME type check
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {mime_type}",
        )

    # Sanitize filename
    original_filename = _sanitize_filename(file.filename or "unnamed")

    # Extension cross-check
    if not _validate_extension_matches_mime(original_filename, mime_type):
        raise HTTPException(
            status_code=422,
            detail="File extension does not match content type",
        )

    # Magic byte validation
    if not validate_file_content(content, mime_type):
        raise HTTPException(
            status_code=422,
            detail="File content does not match claimed type",
        )

    # Parse tags
    parsed_tags: list = []
    if tags:
        try:
            parsed_tags = json.loads(tags)
            if not isinstance(parsed_tags, list):
                parsed_tags = []
        except (json.JSONDecodeError, TypeError):
            parsed_tags = []

    # Store file via FileStorageService (org-scoped path)
    await file.seek(0)
    storage = FileStorageService()
    stored = await storage.store_file(
        file,
        base_dir="documents",
        org_id=org_id,
        path_segments=[],
        allowed_types=ALLOWED_DOCUMENT_TYPES,
        max_size_bytes=MAX_DOCUMENT_SIZE_BYTES,
    )

    # Assign an org-unique slug derived from the title (assigned once at
    # upload; documents are never re-slugged).
    doc_slug = await assign_slug_or_422(
        db, Document, Document.org_id, org_id, title, "document"
    )

    # Create document record
    doc = Document(
        org_id=org_id,
        project_id=project_id,
        uploaded_by_id=current_user.id,
        title=title,
        slug=doc_slug,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size_bytes=stored.size_bytes,
        file_path=stored.relative_path,
        tags=parsed_tags,
    )
    db.add(doc)
    await db.flush()

    # Auto-grant uploader ADMIN permission on the document
    db.add(
        ObjectPermission(
            principal_type=PrincipalType.USER.value,
            principal_id=current_user.id,
            object_type=ObjectType.DOCUMENT.value,
            object_id=doc.id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    await db.commit()
    await db.refresh(doc)

    # Trigger background processing via background handler. Pass the live
    # base URL so the docling subprocess heartbeats back to whatever port
    # this process actually bound (not whatever was in settings).
    await get_background_handler().launch(
        "document_extract",
        document_id=doc.id,
        heartbeat_base_url=str(request.base_url).rstrip("/"),
    )

    resp = DocumentResponse.model_validate(doc)
    resp.can_delete = True  # Uploader always has ADMIN
    return resp


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    project_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

    query = select(Document).where(Document.org_id == org_id)

    if project_id is not None:
        query = query.where(Document.project_id == project_id)
    if status is not None:
        query = query.where(Document.status == status)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    # Fetch page
    query = query.order_by(Document.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    documents = list(result.scalars().all())

    # Compute chunk + embedding coverage per document in one round-trip.
    doc_ids = [doc.id for doc in documents]
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    if doc_ids:
        counts_result = await db.execute(
            select(
                DocumentChunk.document_id,
                func.count().label("chunks"),
                func.count(DocumentChunk.embedding).label("embedded"),
            )
            .where(DocumentChunk.document_id.in_(doc_ids))
            .group_by(DocumentChunk.document_id)
        )
        counts = {
            row.document_id: (row.chunks, row.embedded) for row in counts_result.all()
        }

    # Compute can_delete for each document
    items = []
    for doc in documents:
        resp = DocumentResponse.model_validate(doc)
        resp.can_delete = await _can_delete_document(db, current_user.id, doc.id)
        chunk_total, embedded_total = counts.get(doc.id, (0, 0))
        resp.chunk_count = chunk_total
        resp.embedded_count = embedded_total
        items.append(resp)

    return DocumentListResponse(items=items, total=total)


@router.get(
    "/documents/by-slug/{slug}",
    response_model=DocumentDetailResponse,
)
async def get_document_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up a library document by slug within the current organization."""
    result = await db.execute(
        select(Document.id).where(
            Document.org_id == current_user.selected_org_id,
            Document.slug == slug,
        )
    )
    document_id = result.scalar_one_or_none()
    if document_id is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return await get_document(document_id=document_id, db=db, current_user=current_user)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

    # Load document without eagerly loading all chunks
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Efficient count instead of loading all chunks into memory
    count_result = await db.execute(
        select(
            func.count().label("chunks"),
            func.count(DocumentChunk.embedding).label("embedded"),
        ).where(DocumentChunk.document_id == document_id)
    )
    count_row = count_result.one()
    chunk_count = count_row.chunks or 0
    embedded_count = count_row.embedded or 0

    # Only load the first 5 chunks for preview (exclude embeddings)
    preview_result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(5)
        .options(defer(DocumentChunk.embedding))
    )
    chunks_preview = list(preview_result.scalars().all())

    can_delete = await _can_delete_document(
        db,
        current_user.id,
        document_id,
    )

    # Fetch latest running job's progress (if any)
    progress = None
    if doc.status in (
        DocumentStatus.PROCESSING.value,
        DocumentStatus.INDEXED.value,
    ):
        progress = await BackgroundJobService.get_progress(
            db,
            "document",
            document_id,
        )

    # Build TOC from structure_metadata if available
    toc_entries: list[TOCEntry] = []
    if doc.structure_metadata and "toc" in doc.structure_metadata:
        for entry in doc.structure_metadata["toc"]:
            toc_entries.append(TOCEntry(**entry))

    return DocumentDetailResponse(
        id=doc.id,
        org_id=doc.org_id,
        project_id=doc.project_id,
        uploaded_by_id=doc.uploaded_by_id,
        title=doc.title,
        slug=doc.slug,
        original_filename=doc.original_filename,
        mime_type=doc.mime_type,
        file_size_bytes=doc.file_size_bytes,
        file_path=doc.file_path,
        status=doc.status,
        page_count=doc.page_count,
        tags=doc.tags,
        doc_metadata=doc.doc_metadata,
        error_message=doc.error_message,
        source_url=doc.source_url,
        structure_metadata=doc.structure_metadata,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunk_count=chunk_count,
        embedded_count=embedded_count,
        chunks_preview=chunks_preview,
        can_delete=can_delete,
        processing_progress=progress,
        table_of_contents=toc_entries,
        source_format=doc.source_format,
        refinement_status=doc.refinement_status,
        refinement_flags=doc.refinement_flags,
        refined_by_id=doc.refined_by_id,
        refined_at=doc.refined_at,
    )


@router.get(
    "/documents/{document_id}/chunks",
    response_model=list[DocumentChunkResponse],
)
async def get_document_chunks(
    document_id: uuid.UUID,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

    # Verify document exists and belongs to user's org
    doc_result = await db.execute(
        select(Document.id).where(Document.id == document_id, Document.org_id == org_id)
    )
    if doc_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .offset(offset)
        .limit(limit)
        .options(defer(DocumentChunk.embedding))
    )
    return list(result.scalars().all())


@router.get(
    "/documents/{document_id}/processing",
    response_model=ProcessingAuditResponse,
)
async def get_processing_audit(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the indexing/processing job history for a document plus the
    current chunk + embedding counts. Used by the UI to surface partial
    indexing state and recent failures.
    """
    from app.models.jobs import BackgroundJob

    org_id = await _get_user_org_id(current_user, db)

    doc_result = await db.execute(
        select(Document.id, Document.status).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    row = doc_result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_status = row.status

    count_result = await db.execute(
        select(
            func.count().label("chunks"),
            func.count(DocumentChunk.embedding).label("embedded"),
        ).where(DocumentChunk.document_id == document_id)
    )
    counts = count_result.one()

    jobs_result = await db.execute(
        select(BackgroundJob)
        .where(
            BackgroundJob.entity_type == "document",
            BackgroundJob.entity_id == document_id,
        )
        .order_by(
            BackgroundJob.created_at.desc(),
            BackgroundJob.started_at.desc().nullslast(),
        )
    )
    jobs = []
    for job in jobs_result.scalars().all():
        od = job.output_data or {}
        jobs.append(
            ProcessingJobAudit(
                id=job.id,
                job_type=job.job_type,
                status=job.status,
                started_at=job.started_at,
                completed_at=job.completed_at,
                heartbeat_at=job.heartbeat_at,
                attempts=job.attempts,
                error_message=job.error_message,
                stage=od.get("stage"),
                stage_label=od.get("stage_label"),
                current=od.get("current"),
                total=od.get("total"),
                percent=od.get("percent"),
            )
        )

    return ProcessingAuditResponse(
        document_id=document_id,
        document_status=doc_status,
        chunk_count=counts.chunks or 0,
        embedded_count=counts.embedded or 0,
        jobs=jobs,
    )


async def _get_user_for_download(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve user from header auth or query-param token (for iframes)."""
    from app.core.security import decode_access_token

    # Try standard header-based auth first
    payload = getattr(request.state, "token_payload", None)
    if payload is None and token:
        payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(
        select(User).where(User.id == payload.user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_get_user_for_download),
):
    """Serve a document file with authentication and org-scoping."""
    org_id = await _get_user_org_id(current_user, db)

    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = FileStorageService()
    try:
        full_path = storage.resolve_path_for_org(doc.file_path, org_id)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=404, detail="Document file not found")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")

    # Inline for PDFs and images (browser rendering), attachment for others
    inline_types = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
    }
    disposition = "inline" if doc.mime_type in inline_types else "attachment"

    return FileResponse(
        path=str(full_path),
        media_type=doc.mime_type,
        filename=doc.original_filename,
        content_disposition_type=disposition,
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    org_id = await _get_user_org_id(current_user, db)

    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Permission check: require EDIT on the document
    allowed = await check_permission(
        db,
        current_user.id,
        ObjectType.DOCUMENT,
        document_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Audit log before deletion
    await log_audit(
        db,
        actor_id=current_user.id,
        action="DELETE",
        entity_type="Document",
        entity_id=document_id,
        changes={
            "title": doc.title,
            "original_filename": doc.original_filename,
            "uploaded_by_id": doc.uploaded_by_id,
        },
    )

    # Remove file from disk
    try:
        storage = FileStorageService()
        storage.delete_file(doc.file_path)
    except (OSError, ValueError):
        pass  # Best effort cleanup

    await db.delete(doc)
    await db.commit()


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentResponse,
)
async def retry_processing(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    org_id = await _get_user_org_id(current_user, db)

    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Retry is only meaningful for failed documents. Anything still in
    # flight (QUEUED/EXTRACTING/INDEXING/PROCESSING/AWAITING_REFINEMENT)
    # or already terminal-successful (READY/INDEXED/ENRICHED/UPLOADED)
    # is rejected — the user should wait, delete, or just re-upload.
    if doc.status != DocumentStatus.FAILED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not in a failed state (status={doc.status})",
        )

    # Reset status
    doc.status = DocumentStatus.UPLOADED.value
    doc.error_message = None
    doc.processing_started_at = None
    await db.commit()
    await db.refresh(doc)

    # Re-trigger processing via background handler. See upload_document for
    # the rationale on passing ``heartbeat_base_url``.
    await get_background_handler().launch(
        "document_extract",
        document_id=doc.id,
        heartbeat_base_url=str(request.base_url).rstrip("/"),
    )

    return doc


@router.get("/search", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hybrid search: combines vector similarity with keyword matching.

    Falls back to keyword-only if embedding service is unavailable.
    Results are grouped by document, returning the best-matching chunk
    per document.
    """
    org_id = await _get_user_org_id(current_user, db)

    from sqlalchemy import text as sa_text

    # Attempt to get query embedding for vector search
    query_embedding = None
    try:
        from app.services.ai.embedding import embed_query
        from app.services.documents.document_processor import _pad_embedding

        raw = await embed_query(q, db, org_id=org_id)
        query_embedding = _pad_embedding(raw)
    except Exception:
        logger.warning(
            "Embedding search failed, falling back to keyword-only", exc_info=True
        )

    # Determine search mode and build query
    # We fetch extra rows (limit * 3) to have enough for grouping
    fetch_limit = limit * 3

    if query_embedding is not None:
        # Check if any chunks have embeddings
        has_embeddings = await db.execute(
            sa_text(
                """
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.org_id = :org_id AND dc.embedding IS NOT NULL
                LIMIT 1
            """
            ),
            {"org_id": str(org_id)},
        )

        if has_embeddings.fetchone() is not None:
            # Hybrid: vector + keyword
            search_mode = "hybrid"
            result = await db.execute(
                sa_text(
                    """
                    SELECT
                        dc.id AS chunk_id,
                        dc.document_id,
                        dc.chunk_index,
                        dc.content,
                        dc.page_number,
                        d.title AS document_title,
                        d.slug AS document_slug,
                        CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END AS vector_score,
                        CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END AS keyword_score,
                        ts_headline(
                            'english', dc.content,
                            plainto_tsquery('english', :query),
                            'MaxFragments=2, MaxWords=30, MinWords=10, StartSel=<mark>, StopSel=</mark>'
                        ) AS highlighted
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE d.org_id = :org_id
                      AND (
                          dc.embedding IS NOT NULL
                          OR dc.search_vector @@ plainto_tsquery('english', :query)
                      )
                    ORDER BY (
                        0.7 * CASE WHEN dc.embedding IS NOT NULL
                            THEN (1.0 - (dc.embedding <=> :query_vec))
                            ELSE 0.0
                        END
                        + 0.3 * CASE WHEN dc.search_vector @@ plainto_tsquery('english', :query)
                            THEN ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                            ELSE 0.0
                        END
                    ) DESC
                    LIMIT :limit
                """
                ),
                {
                    "query_vec": str(query_embedding),
                    "query": q,
                    "org_id": str(org_id),
                    "limit": fetch_limit,
                },
            )
        else:
            # Have embedding but no chunks are embedded yet — keyword only
            search_mode = "keyword"
            result = await _keyword_search(db, q, org_id, fetch_limit)
    else:
        # No embedding available — keyword only
        search_mode = "keyword"
        result = await _keyword_search(db, q, org_id, fetch_limit)

    rows = result.fetchall()

    # Group by document, keeping the best-scoring chunk per document
    groups: dict[str, SearchResultGroup] = {}
    for row in rows:
        doc_id = str(row.document_id)

        if search_mode == "hybrid":
            score = round(0.7 * row.vector_score + 0.3 * row.keyword_score, 4)
            highlighted = row.highlighted
        else:
            score = round(float(row.keyword_score), 4)
            highlighted = row.highlighted

        item = SearchResultItem(
            document_id=row.document_id,
            document_title=row.document_title,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            content=row.content,
            highlighted_content=highlighted,
            page_number=row.page_number,
            score=score,
        )

        if doc_id not in groups:
            groups[doc_id] = SearchResultGroup(
                document_id=row.document_id,
                document_slug=row.document_slug,
                document_title=row.document_title,
                match_count=1,
                best_score=score,
                best_chunk=item,
            )
        else:
            groups[doc_id].match_count += 1
            if score > groups[doc_id].best_score:
                groups[doc_id].best_score = score
                groups[doc_id].best_chunk = item

    # Sort groups by best score and take top N
    sorted_groups = sorted(groups.values(), key=lambda g: g.best_score, reverse=True)[
        :limit
    ]

    return SearchResponse(
        query=q,
        items=sorted_groups,
        total=len(sorted_groups),
        search_mode=search_mode,
    )


async def _keyword_search(db, query, org_id, limit):
    """Keyword-only search using tsvector."""
    from sqlalchemy import text as sa_text

    return await db.execute(
        sa_text(
            """
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.page_number,
                d.title AS document_title,
                d.slug AS document_slug,
                ts_rank(dc.search_vector, plainto_tsquery('english', :query))
                    AS keyword_score,
                ts_headline(
                    'english', dc.content,
                    plainto_tsquery('english', :query),
                    'MaxFragments=2, MaxWords=30, MinWords=10, StartSel=<mark>, StopSel=</mark>'
                ) AS highlighted
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.org_id = :org_id
              AND dc.search_vector @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(dc.search_vector, plainto_tsquery('english', :query)) DESC
            LIMIT :limit
        """
        ),
        {
            "query": query,
            "org_id": str(org_id),
            "limit": limit,
        },
    )


@router.post("/documents/backfill-embeddings")
async def backfill_embeddings(
    batch_size: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    """Embed chunks that don't have embeddings yet. Idempotent."""
    org_id = await _get_user_org_id(current_user, db)

    # Find chunks without embeddings, scoped to user's org
    result = await db.execute(
        select(DocumentChunk)
        .join(Document)
        .where(
            Document.org_id == org_id,
            DocumentChunk.embedding == None,  # noqa: E711
        )
        .limit(batch_size)
    )
    chunks = list(result.scalars().all())

    if not chunks:
        return {"embedded": 0, "remaining": 0}

    try:
        from app.services.ai.embedding import embed_texts
        from app.services.documents.document_processor import _pad_embedding

        texts = [c.content for c in chunks]
        embeddings = await embed_texts(texts, db)

        for i, chunk in enumerate(chunks):
            if i < len(embeddings):
                chunk.embedding = _pad_embedding(embeddings[i])

        await db.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding failed: {str(exc)[:200]}",
        )

    # Count remaining
    count_result = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .join(Document)
        .where(
            Document.org_id == org_id,
            DocumentChunk.embedding == None,  # noqa: E711
        )
    )
    remaining = count_result.scalar_one()

    return {
        "embedded": len(chunks),
        "remaining": remaining,
    }


@router.post(
    "/documents/from-url",
    response_model=DocumentResponse,
    status_code=201,
)
async def import_document_from_url(
    body: ImportUrlRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    org_id = await _get_user_org_id(current_user, db)

    try:
        doc = await import_from_url(
            url=str(body.url),
            org_id=org_id,
            user_id=current_user.id,
            title=body.title,
            project_id=body.project_id,
            db=db,
        )
    except ValueError as exc:
        # Determine appropriate status code
        msg = str(exc)
        if "robots.txt" in msg:
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    await db.commit()
    await db.refresh(doc)

    # Trigger background processing via background handler. See
    # upload_document for the rationale on passing ``heartbeat_base_url``.
    await get_background_handler().launch(
        "document_extract",
        document_id=doc.id,
        heartbeat_base_url=str(request.base_url).rstrip("/"),
    )

    return doc


@router.get("/documents/{document_id}/markdown")
async def get_document_markdown(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Markdown not available")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")
    if doc.stored_markdown is None:
        raise HTTPException(404, "Markdown not available")
    return {"markdown": doc.stored_markdown}


@router.put("/documents/{document_id}/markdown", response_model=DocumentResponse)
async def put_document_markdown(
    document_id: uuid.UUID,
    payload: MarkdownPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.EDIT
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")
    await save_markdown(db, doc, payload.markdown, user_id=current_user.id)
    await db.commit()
    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.post(
    "/documents/{document_id}/refine/complete",
    response_model=DocumentResponse,
)
async def refine_complete(
    document_id: uuid.UUID,
    payload: RefineCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Document not found")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.EDIT
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")

    if payload.reopen:
        try:
            await reopen(db, doc)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)

    try:
        await mark_complete(db, doc, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()

    # Indexing now runs as a background job so the user gets the live
    # shimmer card and the doc survives worker restarts via the
    # heartbeat / recovery machinery. See document_index in
    # services/documents/refinement/index_job.py.
    handler = get_background_handler()
    await handler.launch("document_index", document_id=doc.id)

    await db.refresh(doc)
    return DocumentResponse.model_validate(doc)


@router.get("/documents/{document_id}/images/{filename}")
async def get_document_image(
    document_id: uuid.UUID,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not re.fullmatch(r"\d+\.png", filename):
        raise HTTPException(400, "Invalid image filename")
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Image not found")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")
    if doc.images_dir is None:
        raise HTTPException(404, "Image not found")
    path = FileStorageService().storage_root / doc.images_dir / filename
    if not path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


@router.get("/documents/{document_id}/source-page/{page_number}.png")
async def get_document_source_page(
    document_id: uuid.UUID,
    page_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.org_id == org_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(404, "Source page not available")
    allowed = await check_permission(
        db, current_user.id, ObjectType.DOCUMENT, document_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions")
    if doc.mime_type != "application/pdf":
        raise HTTPException(404, "Source page not available")
    path = FileStorageService().resolve_path(doc.file_path)
    try:
        png = render_source_page(path, page_number)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=png, media_type="image/png")
