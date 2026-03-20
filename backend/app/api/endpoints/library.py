import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import (
    ObjectPermission,
    OrganizationMember,
    PrincipalType,
    ObjectType,
    PermissionLevel,
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
from app.schemas.library import (
    DocumentChunkResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    ImportUrlRequest,
    SearchResponse,
    SearchResultGroup,
    SearchResultItem,
)
from app.services.audit import log_audit
from app.services.document_processor import process_document
from app.services.permissions import check_permission
from app.services.task_runner import get_task_runner
from app.services.url_importer import import_from_url

router = APIRouter()


async def _can_delete_document(
    db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> bool:
    """Check if user has EDIT permission on a document (required for delete)."""
    return await check_permission(
        db, user_id, ObjectType.DOCUMENT, document_id, PermissionLevel.EDIT,
    )


async def _get_user_org_id(
    user: User, db: AsyncSession
) -> uuid.UUID:
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


def _validate_extension_matches_mime(
    filename: str, mime_type: str
) -> bool:
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
    file: UploadFile,
    title: str = Form(...),
    project_id: Optional[uuid.UUID] = Form(None),
    tags: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

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

    # Store file with UUID-based path
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(original_filename)[1]
    storage_dir = Path(settings.document_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / f"{file_id}{ext}"
    file_path.write_bytes(content)

    # Create document record
    doc = Document(
        org_id=org_id,
        project_id=project_id,
        uploaded_by_id=current_user.id,
        title=title,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size_bytes=len(content),
        file_path=str(file_path),
        tags=parsed_tags,
    )
    db.add(doc)
    await db.flush()

    # Auto-grant uploader ADMIN permission on the document
    db.add(ObjectPermission(
        principal_type=PrincipalType.USER.value,
        principal_id=current_user.id,
        object_type=ObjectType.DOCUMENT.value,
        object_id=doc.id,
        permission_level=PermissionLevel.ADMIN.value,
    ))
    await db.commit()
    await db.refresh(doc)

    # Trigger background processing via task runner
    get_task_runner().submit(
        process_document(doc.id, settings.database_url)
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
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    # Fetch page
    query = query.order_by(Document.created_at.desc())
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    documents = list(result.scalars().all())

    # Compute can_delete for each document
    items = []
    for doc in documents:
        resp = DocumentResponse.model_validate(doc)
        resp.can_delete = await _can_delete_document(
            db, current_user.id, doc.id
        )
        items.append(resp)

    return DocumentListResponse(items=items, total=total)


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
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Efficient count instead of loading all chunks into memory
    count_result = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
    )
    chunk_count = count_result.scalar() or 0

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
        db, current_user.id, document_id,
    )

    return DocumentDetailResponse(
        id=doc.id,
        org_id=doc.org_id,
        project_id=doc.project_id,
        uploaded_by_id=doc.uploaded_by_id,
        title=doc.title,
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
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunk_count=chunk_count,
        chunks_preview=chunks_preview,
        can_delete=can_delete,
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
        select(Document.id).where(
            Document.id == document_id, Document.org_id == org_id
        )
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


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Permission check: require EDIT on the document
    allowed = await check_permission(
        db, current_user.id,
        ObjectType.DOCUMENT, document_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403, detail="Insufficient permissions"
        )

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
        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()
    except OSError:
        pass  # Best effort cleanup

    await db.delete(doc)
    await db.commit()


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentResponse,
)
async def retry_processing(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)

    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.org_id == org_id
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.status != DocumentStatus.FAILED.value:
        raise HTTPException(
            status_code=409,
            detail="Only failed documents can be retried",
        )

    # Reset status
    doc.status = DocumentStatus.UPLOADED.value
    doc.error_message = None
    doc.processing_started_at = None
    await db.commit()
    await db.refresh(doc)

    # Re-trigger processing via task runner
    get_task_runner().submit(
        process_document(doc.id, settings.database_url)
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
        from app.services.embedding import embed_query
        from app.services.document_processor import _pad_embedding

        raw = await embed_query(q, db)
        query_embedding = _pad_embedding(raw)
    except Exception:
        logger.warning("Embedding search failed, falling back to keyword-only", exc_info=True)

    # Determine search mode and build query
    # We fetch extra rows (limit * 3) to have enough for grouping
    fetch_limit = limit * 3

    if query_embedding is not None:
        # Check if any chunks have embeddings
        has_embeddings = await db.execute(
            sa_text("""
                SELECT 1 FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE d.org_id = :org_id AND dc.embedding IS NOT NULL
                LIMIT 1
            """),
            {"org_id": str(org_id)},
        )

        if has_embeddings.fetchone() is not None:
            # Hybrid: vector + keyword
            search_mode = "hybrid"
            result = await db.execute(
                sa_text("""
                    SELECT
                        dc.id AS chunk_id,
                        dc.document_id,
                        dc.chunk_index,
                        dc.content,
                        dc.page_number,
                        d.title AS document_title,
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
                """),
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
            result = await _keyword_search(
                db, q, org_id, fetch_limit
            )
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
            score = round(
                0.7 * row.vector_score + 0.3 * row.keyword_score, 4
            )
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
    sorted_groups = sorted(
        groups.values(), key=lambda g: g.best_score, reverse=True
    )[:limit]

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
        sa_text("""
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.page_number,
                d.title AS document_title,
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
        """),
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
        from app.services.embedding import embed_texts
        from app.services.document_processor import _pad_embedding

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # Trigger background processing via task runner
    get_task_runner().submit(
        process_document(doc.id, settings.database_url)
    )

    return doc
