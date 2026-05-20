"""API endpoints for paper batch record import."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_or_404, require_active_subscription
from app.db.session import get_db
from app.models.batch_record_import import BatchRecordImport, BatchRecordImportStatus
from app.models.execution import AuditLog
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.protocols import Protocol
from app.models.runs import Run, RunStatus
from app.schemas.batch_record_import import (
    BatchRecordFinalizeRequest,
    BatchRecordFinalizeResponse,
    BatchRecordImportResponse,
    ExtractionResponse,
    StepMappingResponse,
)
from app.schemas.jobs import ProcessingProgress
from app.services.batch.batch_record_extractor import (
    map_values_to_execution_data,
    run_batch_record_extraction,
)
from app.services.core.audit import log_audit
from app.services.core.background_jobs import BackgroundJobService
from app.services.core.file_storage import FileStorageService
from app.services.core.permissions import check_permission
from app.services.core.task_runner import get_task_runner

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_IMPORT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/heic",
}
MAX_IMPORT_SIZE = 50 * 1024 * 1024  # 50 MB


# ── POST /batch-record-imports ───────────────────────────────────────


@router.post(
    "/batch-record-imports",
    response_model=BatchRecordImportResponse,
    status_code=201,
)
async def upload_batch_record(
    file: UploadFile = File(...),
    project_id: UUID = Form(...),
    protocol_id: UUID = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Upload a paper batch record and start AI extraction."""
    # Permission: EDIT on project
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        project_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Insufficient permissions on project")

    # Validate protocol exists and is accessible
    protocol = await db.get(Protocol, protocol_id)
    if not protocol:
        raise HTTPException(404, "Protocol not found")
    if protocol.status == "ARCHIVED":
        raise HTTPException(422, "Cannot import against an archived protocol")
    # Protocol must be scoped to this project or the user's org
    if (
        protocol.project_id != project_id
        and protocol.organization_id != user.selected_org_id
    ):
        raise HTTPException(403, "Protocol is not accessible from this project")

    # Store file
    storage = FileStorageService()
    stored = await storage.store_file(
        file,
        base_dir="batch-imports",
        org_id=user.selected_org_id,
        path_segments=[str(project_id)],
        allowed_types=ALLOWED_IMPORT_TYPES,
        max_size_bytes=MAX_IMPORT_SIZE,
    )

    # Create import session
    import_row = BatchRecordImport(
        org_id=user.selected_org_id,
        project_id=project_id,
        uploaded_by_id=user.id,
        status=BatchRecordImportStatus.EXTRACTING.value,
        original_filename=stored.original_filename,
        mime_type=stored.mime_type,
        file_path=stored.relative_path,
        file_size_bytes=stored.size_bytes,
        protocol_id=protocol_id,
    )
    db.add(import_row)
    await db.flush()

    # Fire background extraction
    get_task_runner().submit(
        run_batch_record_extraction(
            import_row.id,
            settings.database_url,
            user.selected_org_id,
            protocol_id,
        )
    )

    await db.commit()
    await db.refresh(import_row)

    return BatchRecordImportResponse(
        import_id=import_row.id,
        status=import_row.status,
        protocol_id=import_row.protocol_id,
        original_filename=import_row.original_filename,
        created_at=import_row.created_at,
    )


# ── GET /batch-record-imports/{id} ───────────────────────────────────


@router.get(
    "/batch-record-imports/{import_id}",
    response_model=BatchRecordImportResponse,
)
async def get_batch_record_import(
    import_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get import session status, progress, or extraction results."""
    import_row = await get_or_404(db, BatchRecordImport, import_id)

    # Permission: must be in user's org
    if import_row.org_id != user.selected_org_id:
        raise HTTPException(403, "Not authorized")

    response = BatchRecordImportResponse(
        import_id=import_row.id,
        status=import_row.status,
        protocol_id=import_row.protocol_id,
        original_filename=import_row.original_filename,
        page_count=import_row.page_count,
        created_run_id=import_row.created_run_id,
        error_message=import_row.error_message,
        created_at=import_row.created_at,
    )

    if import_row.status == BatchRecordImportStatus.EXTRACTING.value:
        # Return progress from background job
        response.progress = await BackgroundJobService.get_progress(
            db,
            "batch_record_import",
            import_row.id,
        )

    elif import_row.status == BatchRecordImportStatus.REVIEW.value:
        # Return extraction results + step mappings
        if import_row.extraction_result:
            er = import_row.extraction_result
            step_mappings_raw = er.pop("step_mappings", [])
            response.extraction = ExtractionResponse(**er)
            response.step_mappings = [
                StepMappingResponse(**m) for m in step_mappings_raw
            ]

    return response


# ── POST /batch-record-imports/{id}/finalize ─────────────────────────


@router.post(
    "/batch-record-imports/{import_id}/finalize",
    response_model=BatchRecordFinalizeResponse,
    status_code=201,
)
async def finalize_batch_record_import(
    import_id: UUID,
    request: BatchRecordFinalizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Create a completed Run from reviewed batch record extraction."""
    import_row = await get_or_404(db, BatchRecordImport, import_id)

    # Must be in REVIEW status
    if import_row.status != BatchRecordImportStatus.REVIEW.value:
        raise HTTPException(
            409,
            f"Import is in {import_row.status} status, expected REVIEW",
        )

    # Permission: must be in user's org
    if import_row.org_id != user.selected_org_id:
        raise HTTPException(403, "Not authorized")

    # Load protocol and copy graph
    protocol = await get_or_404(db, Protocol, request.protocol_id)
    graph = (protocol.graph or {}).copy()

    # Build execution_data from finalized mappings
    execution_data = map_values_to_execution_data(
        [m.model_dump() for m in request.step_mappings],
        graph,
        user.id,
    )

    # Create completed Run
    run = Run(
        name=request.run_name,
        project_id=import_row.project_id,
        protocol_id=request.protocol_id,
        status=RunStatus.COMPLETED,
        graph=graph,
        execution_data=execution_data,
        started_by_id=user.id,
        attachments=[
            {
                "id": str(uuid4()),
                "file_path": import_row.file_path,
                "filename": import_row.original_filename,
                "content_type": import_row.mime_type,
                "size_bytes": import_row.file_size_bytes,
                "uploaded_by_id": str(user.id),
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "step_id": None,
                "run_status": "COMPLETED",
                "deleted": False,
            }
        ],
    )
    db.add(run)
    await db.flush()

    # Audit log
    extraction_result = import_row.extraction_result or {}
    await log_audit(
        db,
        user.id,
        "IMPORT",
        "Run",
        run.id,
        {
            "source": "batch_record_import",
            "import_id": str(import_row.id),
            "source_document": import_row.original_filename,
            "protocol_id": str(request.protocol_id),
            "overall_confidence": extraction_result.get("overall_confidence"),
            "values_accepted": sum(
                1 for m in request.step_mappings for v in m.values if v.accepted
            ),
            "values_rejected": sum(
                1 for m in request.step_mappings for v in m.values if not v.accepted
            ),
            "values_edited": sum(
                1 for m in request.step_mappings for v in m.values if v.edited
            ),
            "steps_na": sum(1 for m in request.step_mappings if m.na),
        },
    )

    # Update import session
    import_row.status = BatchRecordImportStatus.FINALIZED.value
    import_row.created_run_id = run.id
    import_row.reviewed_data = {
        "step_mappings": [m.model_dump() for m in request.step_mappings],
    }

    await db.commit()

    return BatchRecordFinalizeResponse(
        run_id=run.id,
        run_name=run.name,
        import_id=import_row.id,
    )
