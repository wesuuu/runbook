import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User, ObjectType, PermissionLevel
from app.models.science import Protocol, Project
from app.schemas.science import GraphPayload
from app.services.graph_processing import _parse_graph_roles_and_steps
from app.services.pdf import generate_sop_pdf, generate_batch_record_pdf
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


# --- PDF format helpers ---

async def _get_pdf_format(db, project_id: UUID) -> dict | None:
    """Fetch pdf_format from a project's settings JSONB."""
    result = await db.execute(
        select(Project.settings).where(Project.id == project_id)
    )
    settings = result.scalar_one_or_none()
    if settings and isinstance(settings, dict):
        return settings.get("pdf_format")
    return None


def _build_format_overrides(
    font_size: Optional[str],
    font_family: Optional[str],
    header_color: Optional[str],
    row_spacing: Optional[str],
) -> dict | None:
    """Build a format overrides dict from query params.

    Returns None if no overrides were supplied.
    """
    overrides: dict = {}
    if font_size is not None:
        overrides["font_size"] = font_size
    if font_family is not None:
        overrides["font_family"] = font_family
    if header_color is not None:
        try:
            overrides["header_color"] = [int(c) for c in header_color.split(",")]
        except (ValueError, AttributeError):
            logger.warning("Invalid header_color value: %s", header_color)
    if row_spacing is not None:
        overrides["row_spacing"] = row_spacing
    return overrides or None


def _merge_format(base: dict | None, overrides: dict | None) -> dict | None:
    """Merge format overrides on top of base project format."""
    if not overrides:
        return base
    if not base:
        return overrides
    return {**base, **overrides}


# --- Protocol PDF ---

@router.get("/protocols/{protocol_id}/pdf/sop")
async def get_protocol_sop_pdf(
    protocol_id: UUID,
    disposition: Optional[str] = Query(None),
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF preview from a protocol's graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    graph = protocol.graph or {}
    roles_with_steps, _, _ = _parse_graph_roles_and_steps(graph)
    pdf_format = await _get_pdf_format(db, protocol.project_id)
    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    pdf_bytes = generate_sop_pdf(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name=None,
        roles_with_steps=roles_with_steps,
        format_options=pdf_format,
        version_number=protocol.version_number,
        last_modified=protocol.updated_at.strftime("%B %d, %Y")
        if protocol.updated_at
        else None,
    )

    disp = disposition or "attachment"
    filename = f"SOP_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


@router.get("/protocols/{protocol_id}/pdf/batch-record")
async def get_protocol_batch_record_pdf(
    protocol_id: UUID,
    disposition: Optional[str] = Query(None),
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a batch record PDF preview from a protocol's graph."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    graph = protocol.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)
    pdf_format = await _get_pdf_format(db, protocol.project_id)
    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    # Only build role list for swimlane-based protocols
    if is_role_based:
        roles = [
            {"id": r["role_name"], "name": r["role_name"]}
            for r in roles_with_steps
            if r["role_name"]
        ]
    else:
        roles = []

    pdf_bytes = generate_batch_record_pdf(
        protocol_name=protocol.name,
        run_name="Preview",
        roles=roles,
        steps=flat_steps,
        filled=False,
        execution_data=None,
        format_options=pdf_format,
        roles_with_steps=roles_with_steps,
        is_role_based=is_role_based,
        version_number=protocol.version_number,
        last_modified=protocol.updated_at.strftime("%B %d, %Y")
        if protocol.updated_at
        else None,
    )

    disp = disposition or "attachment"
    filename = f"BatchRecord_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


# --- Protocol PDF Preview from graph payload ---

@router.post("/protocols/{protocol_id}/pdf/sop")
async def preview_protocol_sop_pdf(
    protocol_id: UUID,
    body: GraphPayload,
    disposition: Optional[str] = Query(None),
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an SOP PDF from a graph payload (unsaved preview)."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    graph = body.graph
    roles_with_steps, _, _ = _parse_graph_roles_and_steps(graph)
    pdf_format = await _get_pdf_format(db, protocol.project_id)
    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    pdf_bytes = generate_sop_pdf(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name=None,
        roles_with_steps=roles_with_steps,
        format_options=pdf_format,
        version_number=protocol.version_number,
        last_modified=protocol.updated_at.strftime("%B %d, %Y")
        if protocol.updated_at
        else None,
    )

    disp = disposition or "inline"
    filename = f"SOP_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


@router.post("/protocols/{protocol_id}/pdf/batch-record")
async def preview_protocol_batch_record_pdf(
    protocol_id: UUID,
    body: GraphPayload,
    disposition: Optional[str] = Query(None),
    font_size: Optional[str] = Query(None),
    font_family: Optional[str] = Query(None),
    header_color: Optional[str] = Query(None),
    row_spacing: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a batch record PDF from a graph payload (unsaved preview)."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    graph = body.graph
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)
    pdf_format = await _get_pdf_format(db, protocol.project_id)
    overrides = _build_format_overrides(
        font_size, font_family, header_color, row_spacing,
    )
    pdf_format = _merge_format(pdf_format, overrides)

    # Only build role list for swimlane-based protocols
    if is_role_based:
        roles = [
            {"id": r["role_name"], "name": r["role_name"]}
            for r in roles_with_steps
            if r["role_name"]
        ]
    else:
        roles = []

    pdf_bytes = generate_batch_record_pdf(
        protocol_name=protocol.name,
        run_name="Preview",
        roles=roles,
        steps=flat_steps,
        filled=False,
        execution_data=None,
        format_options=pdf_format,
        roles_with_steps=roles_with_steps,
        is_role_based=is_role_based,
        version_number=protocol.version_number,
        last_modified=protocol.updated_at.strftime("%B %d, %Y")
        if protocol.updated_at
        else None,
    )

    disp = disposition or "inline"
    filename = f"BatchRecord_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )
