import asyncio
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
from app.models.templates import DocumentTemplate
from app.schemas.science import GraphPayload
from app.services.file_storage import FileStorageService
from app.services.graph_processing import _parse_graph_roles_and_steps
from app.services.permissions import check_permission
from app.services.protocols.template_engine import build_context, render_to_pdf

logger = logging.getLogger(__name__)

router = APIRouter()

storage = FileStorageService()


async def _load_template(db: AsyncSession, template_id: UUID | None) -> DocumentTemplate | None:
    """Load a DocumentTemplate by ID."""
    if not template_id:
        return None
    result = await db.execute(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


def _resolve_template_path(template: DocumentTemplate) -> str:
    """Get the filesystem path for a template."""
    return str(storage.resolve_path_for_org(template.file_path, template.org_id))


# --- Protocol PDF ---

@router.get("/protocols/{protocol_id}/pdf/sop")
async def get_protocol_sop_pdf(
    protocol_id: UUID,
    disposition: Optional[str] = Query(None),
    template_id: Optional[UUID] = Query(None),
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

    template = await _load_template(db, template_id or protocol.sop_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="SOP template not found")

    template_path = _resolve_template_path(template)
    graph = protocol.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    context = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y")
            if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

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
    template_id: Optional[UUID] = Query(None),
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

    template = await _load_template(db, template_id or protocol.batch_record_template_id)
    if not template:
        raise HTTPException(
            status_code=404, detail="Batch record template not found"
        )

    template_path = _resolve_template_path(template)
    graph = protocol.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    context = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name="Preview",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y")
            if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

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
    template_id: Optional[UUID] = Query(None),
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

    template = await _load_template(db, template_id or protocol.sop_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="SOP template not found")

    template_path = _resolve_template_path(template)
    graph = body.graph
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    context = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y")
            if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

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
    template_id: Optional[UUID] = Query(None),
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

    template = await _load_template(db, template_id or protocol.batch_record_template_id)
    if not template:
        raise HTTPException(
            status_code=404, detail="Batch record template not found"
        )

    template_path = _resolve_template_path(template)
    graph = body.graph
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    context = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name="Preview",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y")
            if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
    )
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    disp = disposition or "inline"
    filename = f"BatchRecord_Preview_{protocol.name}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )
