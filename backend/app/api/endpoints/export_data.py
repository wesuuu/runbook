import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User, ObjectType, PermissionLevel
from app.models.science import Protocol, Run
from app.schemas.export import (
    ExportPreviewRequest,
    ExportPreviewResponse,
    ExportDownloadRequest,
)
from app.services.export import build_export_data, filter_columns, get_strategy
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Data Export ---

async def _load_exportable_runs(
    run_ids: list[UUID],
    user: User,
    db: AsyncSession,
) -> list[dict]:
    """Load runs by IDs, validate permissions and status, resolve user names."""
    result = await db.execute(
        select(Run).where(Run.id.in_(run_ids))
    )
    run_objs = result.scalars().all()

    if len(run_objs) != len(run_ids):
        found = {r.id for r in run_objs}
        missing = [str(rid) for rid in run_ids if rid not in found]
        raise HTTPException(
            status_code=404,
            detail=f"Runs not found: {', '.join(missing)}",
        )

    # Validate permissions and status
    exportable_statuses = {"COMPLETED", "EDITED"}
    for run_obj in run_objs:
        allowed = await check_permission(
            db, user.id, ObjectType.RUN,
            run_obj.id, PermissionLevel.VIEW,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"No VIEW permission on run {run_obj.id}",
            )
        status_str = (
            run_obj.status if isinstance(run_obj.status, str)
            else run_obj.status.value
        )
        if status_str not in exportable_statuses:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Run '{run_obj.name}' has status {status_str}. "
                    "Only COMPLETED or EDITED runs can be exported."
                ),
            )

    # Collect all user IDs for name resolution
    user_ids: set[str] = set()
    for run_obj in run_objs:
        if run_obj.execution_data:
            for step_data in run_obj.execution_data.values():
                if isinstance(step_data, dict):
                    uid = step_data.get("completed_by_user_id")
                    if uid:
                        user_ids.add(uid)
                    editor_uid = step_data.get("edited_by_user_id")
                    if editor_uid:
                        user_ids.add(editor_uid)
        if run_obj.started_by_id:
            user_ids.add(str(run_obj.started_by_id))

    user_map: dict[str, str] = {}
    if user_ids:
        result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        for u in result.scalars().all():
            user_map[str(u.id)] = u.full_name or u.email

    # Resolve protocol names
    protocol_ids = {
        run_obj.protocol_id for run_obj in run_objs if run_obj.protocol_id
    }
    proto_map: dict[str, str] = {}
    if protocol_ids:
        result = await db.execute(
            select(Protocol).where(Protocol.id.in_(protocol_ids))
        )
        for p in result.scalars().all():
            proto_map[str(p.id)] = p.name

    # Build run dicts
    runs = []
    for run_obj in run_objs:
        status_str = (
            run_obj.status if isinstance(run_obj.status, str)
            else run_obj.status.value
        )
        runs.append({
            "id": str(run_obj.id),
            "name": run_obj.name,
            "status": status_str,
            "graph": run_obj.graph or {},
            "execution_data": run_obj.execution_data or {},
            "user_map": user_map,
            "protocol_name": proto_map.get(
                str(run_obj.protocol_id), ""
            ) if run_obj.protocol_id else "",
            "created_at": str(run_obj.created_at) if run_obj.created_at else "",
            "updated_at": str(run_obj.updated_at) if run_obj.updated_at else "",
        })

    return runs


@router.post("/export/preview", response_model=ExportPreviewResponse)
async def export_preview(
    body: ExportPreviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview export data as JSON rows."""
    runs = await _load_exportable_runs(body.run_ids, user, db)
    columns, rows = build_export_data(runs, body.layout.value)
    return ExportPreviewResponse(
        columns=[
            {"key": c["key"], "label": c["label"], "group": c["group"]}
            for c in columns
        ],
        rows=rows,
        run_count=len(runs),
    )


@router.post("/export/download")
async def export_download(
    body: ExportDownloadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download exported run data in the requested format."""
    runs = await _load_exportable_runs(body.run_ids, user, db)
    columns, rows = build_export_data(runs, body.layout.value)
    columns, rows = filter_columns(columns, rows, body.columns)

    strategy = get_strategy(body.format.value)

    from datetime import date

    metadata = {
        "export_date": str(date.today()),
        "run_count": len(runs),
        "layout": body.layout.value,
        "runs": [
            {
                "name": r["name"],
                "status": r["status"],
                "protocol_name": r["protocol_name"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in runs
        ],
    }

    file_bytes = strategy.export(columns, rows, metadata)

    if len(runs) == 1:
        base_name = runs[0]["name"].replace(" ", "_")
    else:
        base_name = f"export_{len(runs)}_runs"

    filename = f"{base_name}.{strategy.file_extension}"

    return Response(
        content=file_bytes,
        media_type=strategy.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
