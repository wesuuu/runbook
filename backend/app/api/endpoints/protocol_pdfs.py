import asyncio
import logging
from typing import Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import ObjectType, PermissionLevel, User
from app.models.science import (Project, Protocol, ProtocolApprovalEvent,
                                UnitOpDefinition)
from app.models.templates import DocumentTemplate
from app.schemas.science import GraphPayload
from app.services.core.file_storage import FileStorageService
from app.services.core.permissions import check_permission
from app.services.data.graph_processing import _parse_graph_roles_and_steps
from app.services.protocols.equipment_context import build_equipment_context
from app.services.protocols.template_engine import build_context, render_to_pdf
from app.services.protocols.validation import assert_no_branch_errors

logger = logging.getLogger(__name__)

router = APIRouter()

storage = FileStorageService()


async def _load_template(
    db: AsyncSession, template_id: UUID | None
) -> DocumentTemplate | None:
    """Load a DocumentTemplate by ID."""
    if not template_id:
        return None
    result = await db.execute(
        select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def _build_user_signatures(
    db: AsyncSession, user_ids: list[str | UUID]
) -> dict[str, dict[str, str]]:
    """Build {user_id: {kind: absolute_path}} for users with stored
    signatures. Each entry contains optional keys
    'signature_initials_path' (drawn initials) and/or
    'signature_full_path' (drawn full signature). Users with neither
    path are omitted. Empty dict when no IDs are provided."""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(
                User.id,
                User.signature_initials_path,
                User.signature_full_path,
            )
            .where(User.id.in_(user_ids))
            .where(
                or_(
                    User.signature_initials_path.is_not(None),
                    User.signature_full_path.is_not(None),
                )
            )
        )
    ).all()
    out: dict[str, dict[str, str]] = {}
    for uid, initials_path, full_path in rows:
        entry: dict[str, str] = {}
        if initials_path:
            entry["signature_initials_path"] = str(storage.resolve_path(initials_path))
        if full_path:
            entry["signature_full_path"] = str(storage.resolve_path(full_path))
        if entry:
            out[str(uid)] = entry
    return out


async def _build_approval_context(
    db: AsyncSession,
    protocol: Protocol,
    project: Project | None,
) -> dict:
    """Return {approval, approval_history, unapproved_warning} for a
    protocol, used by SOP/batch-record templates.

    - ``approval``: the latest APPROVED event (or None) with approver
      identity, version, statement, and the absolute path to the
      approver's full-signature image when registered.
    - ``approval_history``: every event for this protocol, newest
      first. Each item exposes ``action``, ``actor_name``, ``comment``,
      ``signature_statement``, ``created_at``. Missing actors fall back
      to ``"(deleted user)"``.
    - ``unapproved_warning``: True iff the project requires approval
      AND the protocol is designated AND the protocol is not currently
      APPROVED.
    """
    project_settings: dict = (project.settings or {}) if project is not None else {}
    project_requires = bool(project_settings.get("require_protocol_approval"))
    unapproved_warning = (
        project_requires
        and bool(protocol.requires_approval)
        and protocol.status != "APPROVED"
    )

    events_result = await db.execute(
        select(ProtocolApprovalEvent)
        .where(ProtocolApprovalEvent.protocol_id == protocol.id)
        .order_by(ProtocolApprovalEvent.created_at.desc())
        .options(selectinload(ProtocolApprovalEvent.actor))
    )
    events = list(events_result.scalars().all())

    history = []
    latest_approved: ProtocolApprovalEvent | None = None
    for ev in events:
        actor = ev.actor
        actor_name = (
            (actor.full_name or actor.email) if actor is not None else "(deleted user)"
        )
        history.append(
            {
                "action": ev.action,
                "actor_name": actor_name,
                "comment": ev.comment,
                "signature_statement": ev.signature_statement,
                "created_at": ev.created_at,
            }
        )
        if ev.action == "APPROVED" and latest_approved is None:
            latest_approved = ev

    approval = None
    if latest_approved is not None:
        actor = latest_approved.actor
        if actor is not None:
            sigs = await _build_user_signatures(db, [actor.id])
            sig_path = (sigs.get(str(actor.id), {}) or {}).get("signature_full_path")
            approver_name = actor.full_name or actor.email
            approver_email = actor.email
        else:
            sig_path = None
            approver_name = "(deleted user)"
            approver_email = ""
        approval = {
            "approver_name": approver_name,
            "approver_email": approver_email,
            "approved_at": latest_approved.created_at,
            "signature_statement": latest_approved.signature_statement,
            "signature_image_path": sig_path,
            "protocol_version": protocol.version_number,
        }

    return {
        "approval": approval,
        "approval_history": history,
        "unapproved_warning": unapproved_warning,
    }


def _resolve_template_path(template: DocumentTemplate) -> str:
    """Get the filesystem path for a template."""
    return str(storage.resolve_path_for_org(template.file_path, template.org_id))


def _pdf_response(
    pdf_bytes: bytes,
    *,
    filename: str,
    disposition: str,
    unresolved: list[str],
) -> Response:
    """Build a PDF response and attach X-Unresolved-Placeholders when needed.

    Filenames may include unicode (em-dashes, accents) when a protocol
    name does — Content-Disposition headers are encoded as latin-1, so
    we emit RFC 6266 form: an ASCII-safe ``filename=`` fallback plus a
    ``filename*=UTF-8''<percent-encoded>`` for unicode-aware clients.
    """
    ascii_filename = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    encoded_filename = quote(filename, safe="")
    headers = {
        "Content-Disposition": (
            f'{disposition}; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{encoded_filename}"
        )
    }
    if unresolved:
        headers["X-Unresolved-Placeholders"] = ",".join(unresolved)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers=headers,
    )


async def _load_protocol_project(
    db: AsyncSession, protocol: Protocol
) -> Project | None:
    """Load the project that owns a protocol, or None for org-scoped."""
    if not protocol.project_id:
        return None
    result = await db.execute(select(Project).where(Project.id == protocol.project_id))
    return result.scalar_one_or_none()


async def _assert_branch_ok(db: AsyncSession, graph: dict, org_id) -> None:
    """Raise HTTPException(400) if the graph has branch_requires_distinct_roles errors."""
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.organization_id == org_id)
    )
    unit_ops = list(result.scalars().all())
    assert_no_branch_errors(graph or {}, unit_ops)


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
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    await _assert_branch_ok(db, protocol.graph or {}, user.selected_org_id)

    template = await _load_template(db, template_id or protocol.sop_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="SOP template not found")

    template_path = _resolve_template_path(template)
    graph = protocol.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )
    user_signatures = await _build_user_signatures(db, [])
    project = await _load_protocol_project(db, protocol)
    approval_ctx = await _build_approval_context(db, protocol, project)

    context, unresolved = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y") if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        equipment_context=equipment_ctx,
        user_signatures=user_signatures,
    )
    context.update(approval_ctx)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in protocol %s: %s",
            protocol.id,
            unresolved,
        )
    if eq_warnings:
        logger.warning(
            "Equipment warnings in protocol %s: %s", protocol.id, eq_warnings
        )

    disp = disposition or "attachment"
    filename = f"SOP_Preview_{protocol.name}.pdf".replace(" ", "_")
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
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
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    await _assert_branch_ok(db, protocol.graph or {}, user.selected_org_id)

    template = await _load_template(
        db, template_id or protocol.batch_record_template_id
    )
    if not template:
        raise HTTPException(status_code=404, detail="Batch record template not found")

    template_path = _resolve_template_path(template)
    graph = protocol.graph or {}
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )
    user_signatures = await _build_user_signatures(db, [])
    project = await _load_protocol_project(db, protocol)
    approval_ctx = await _build_approval_context(db, protocol, project)

    context, unresolved = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name="Preview",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y") if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        equipment_context=equipment_ctx,
        user_signatures=user_signatures,
    )
    context.update(approval_ctx)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in protocol %s: %s",
            protocol.id,
            unresolved,
        )
    if eq_warnings:
        logger.warning(
            "Equipment warnings in protocol %s: %s", protocol.id, eq_warnings
        )

    disp = disposition or "attachment"
    filename = f"BatchRecord_Preview_{protocol.name}.pdf".replace(" ", "_")
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
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
    _: User = Depends(require_active_subscription()),
):
    """Generate an SOP PDF from a graph payload (unsaved preview)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    await _assert_branch_ok(db, body.graph, user.selected_org_id)

    template = await _load_template(db, template_id or protocol.sop_template_id)
    if not template:
        raise HTTPException(status_code=404, detail="SOP template not found")

    template_path = _resolve_template_path(template)
    graph = body.graph
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )
    user_signatures = await _build_user_signatures(db, [])
    project = await _load_protocol_project(db, protocol)
    approval_ctx = await _build_approval_context(db, protocol, project)

    context, unresolved = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y") if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        equipment_context=equipment_ctx,
        user_signatures=user_signatures,
    )
    context.update(approval_ctx)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in protocol %s: %s",
            protocol.id,
            unresolved,
        )
    if eq_warnings:
        logger.warning(
            "Equipment warnings in protocol %s: %s", protocol.id, eq_warnings
        )

    disp = disposition or "inline"
    filename = f"SOP_Preview_{protocol.name}.pdf".replace(" ", "_")
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
    )


@router.post("/protocols/{protocol_id}/pdf/batch-record")
async def preview_protocol_batch_record_pdf(
    protocol_id: UUID,
    body: GraphPayload,
    disposition: Optional[str] = Query(None),
    template_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Generate a batch record PDF from a graph payload (unsaved preview)."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    await _assert_branch_ok(db, body.graph, user.selected_org_id)

    template = await _load_template(
        db, template_id or protocol.batch_record_template_id
    )
    if not template:
        raise HTTPException(status_code=404, detail="Batch record template not found")

    template_path = _resolve_template_path(template)
    graph = body.graph
    roles_with_steps, flat_steps, is_role_based = _parse_graph_roles_and_steps(graph)

    equipment_ctx, eq_warnings = await build_equipment_context(
        db, user.selected_org_id, graph
    )
    user_signatures = await _build_user_signatures(db, [])
    project = await _load_protocol_project(db, protocol)
    approval_ctx = await _build_approval_context(db, protocol, project)

    context, unresolved = build_context(
        protocol_name=protocol.name,
        protocol_description=protocol.description or "",
        run_name="Preview",
        version_number=protocol.version_number,
        created_at=(
            protocol.updated_at.strftime("%B %d, %Y") if protocol.updated_at else ""
        ),
        roles_with_steps=roles_with_steps,
        flat_steps=flat_steps,
        is_role_based=is_role_based,
        equipment_context=equipment_ctx,
        user_signatures=user_signatures,
    )
    context.update(approval_ctx)
    pdf_bytes = await asyncio.to_thread(render_to_pdf, template_path, context)

    if unresolved:
        logger.warning(
            "Unresolved template variables in protocol %s: %s",
            protocol.id,
            unresolved,
        )
    if eq_warnings:
        logger.warning(
            "Equipment warnings in protocol %s: %s", protocol.id, eq_warnings
        )

    disp = disposition or "inline"
    filename = f"BatchRecord_Preview_{protocol.name}.pdf".replace(" ", "_")
    return _pdf_response(
        pdf_bytes, filename=filename, disposition=disp, unresolved=unresolved
    )
