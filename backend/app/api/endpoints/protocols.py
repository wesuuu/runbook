import logging
import tempfile
from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, Query, UploadFile)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import (get_current_user, get_or_404,
                           require_active_subscription, require_permission)
from app.db.session import get_db
from app.models.iam import (ObjectType, OrganizationMember, OrgRole,
                            PermissionLevel, User)
from app.models.science import (Project, Protocol, ProtocolRole,
                                ProtocolVersion, Run)
from app.schemas.science import (DesignateApprovalRequest, ProtocolCreate,
                                 ProtocolImportFinalizeRequest,
                                 ProtocolImportProposalResponse,
                                 ProtocolRefineRequest, ProtocolResponse,
                                 ProtocolRoleCreate, ProtocolRoleResponse,
                                 ProtocolRoleUpdate, ProtocolUpdate)
from app.services.approvals import write_event
from app.services.core.audit import log_audit
from app.services.core.notifications import send_notification
from app.services.core.permissions import check_permission
from app.services.protocols.lookup import get_protocol_full, list_protocols
from app.services.protocols.roles import (add_role, list_roles, remove_role,
                                          update_role)

logger = logging.getLogger(__name__)

router = APIRouter()

# F-0066 Task 14: fields whose mutation while APPROVED triggers an
# auto-revert to DRAFT, and whose mutation while PENDING_APPROVAL is
# outright rejected. Anything outside this set is allowed to flow
# through unchanged.
APPROVED_EDIT_FIELDS = {"name", "description", "graph"}


# --- Protocols ---


@router.post(
    "/protocols",
    response_model=ProtocolResponse,
    status_code=201,
)
async def create_protocol(
    protocol: ProtocolCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    # Validate scope: exactly one of project_id or organization_id
    if protocol.project_id and protocol.organization_id:
        raise HTTPException(400, "Set project_id or organization_id, not both")
    if not protocol.project_id and not protocol.organization_id:
        # Default to project-scoped (backward compat)
        raise HTTPException(400, "project_id or organization_id required")

    if protocol.project_id:
        allowed = await check_permission(
            db,
            user.id,
            ObjectType.PROJECT,
            protocol.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(403, "EDIT permission required on project")
        result = await db.execute(
            select(Project).where(Project.id == protocol.project_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(404, "Project not found")

    if protocol.organization_id:
        # Org-scoped: require org admin
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == protocol.organization_id,
                OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(403, "Org admin required for organization protocols")

    # Resolve default template IDs: project > org > system
    from app.services.protocols.template_engine import \
        resolve_default_template_id

    org_id = protocol.organization_id
    if not org_id and protocol.project_id:
        proj_result = await db.execute(
            select(Project).where(Project.id == protocol.project_id)
        )
        proj = proj_result.scalar_one_or_none()
        if proj:
            org_id = proj.organization_id

    sop_tpl_id = None
    br_tpl_id = None
    if org_id:
        sop_tpl_id = await resolve_default_template_id(
            db, protocol.project_id or UUID(int=0), org_id, "SOP"
        )
        br_tpl_id = await resolve_default_template_id(
            db, protocol.project_id or UUID(int=0), org_id, "BATCH_RECORD"
        )

    new_protocol = Protocol(
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        organization_id=protocol.organization_id,
        graph=protocol.graph,
        sop_template_id=sop_tpl_id,
        batch_record_template_id=br_tpl_id,
    )
    db.add(new_protocol)
    await db.flush()

    await log_audit(
        db,
        user.id,
        "CREATE",
        "Protocol",
        new_protocol.id,
        {"name": protocol.name, "version_number": new_protocol.version_number},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == new_protocol.id)
    )
    return result.scalar_one()


# --- Protocol Import ---


@router.post(
    "/protocols/import",
    response_model=ProtocolImportProposalResponse,
)
async def import_protocol(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Upload a protocol document and get an AI-generated import proposal."""
    from app.models.science import UnitOpDefinition
    from app.services.protocols.protocol_importer import (build_proposal,
                                                          extract_text,
                                                          parse_protocol_text)

    # Validate file type
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
        "image/tiff",
    }
    if file.content_type not in allowed_types:
        raise HTTPException(
            422,
            f"Unsupported file type: {file.content_type}. "
            f"Accepted: PDF, DOCX, JPEG, PNG, TIFF",
        )

    org_id = user.selected_org_id

    # Save to temp file
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=Path(file.filename or "doc").suffix
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Extract text
        text = await extract_text(tmp_path, file.content_type, db, org_id)
        if not text or not text.strip():
            raise HTTPException(422, "Could not extract text from document")

        # Fetch unit op catalog
        result = await db.execute(select(UnitOpDefinition))
        unit_ops = list(result.scalars().all())

        # Parse with LLM
        try:
            parsed = await parse_protocol_text(text, unit_ops, db, org_id)
        except Exception as e:
            logger.exception("LLM analysis failed for protocol import")
            raise HTTPException(502, f"AI analysis failed: {str(e)}")

        # Build proposal
        proposal = build_proposal(
            parsed,
            unit_ops,
            file.filename or "uploaded_document",
            source_text=text,
        )
        return proposal
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/protocols/refine")
async def refine_protocol_endpoint(
    request: ProtocolRefineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Refine a protocol graph based on a natural language instruction.

    General-purpose: works for imported protocols and existing ones.
    """
    from app.models.science import UnitOpDefinition
    from app.services.protocols.protocol_importer import refine_protocol

    org_id = user.selected_org_id

    result = await db.execute(select(UnitOpDefinition))
    unit_ops = list(result.scalars().all())

    try:
        updated_graph = await refine_protocol(
            request.graph,
            request.instruction,
            unit_ops,
            db,
            org_id,
        )
    except Exception as e:
        logger.exception("Protocol refinement failed")
        raise HTTPException(502, f"AI refinement failed: {str(e)}")

    return updated_graph


@router.post(
    "/protocols/finalize-import",
    response_model=ProtocolResponse,
    status_code=201,
)
async def finalize_protocol_import(
    request: ProtocolImportFinalizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Finalize a protocol import: create unit ops, roles, and protocol."""
    from app.services.protocols.protocol_importer import (StepProposal,
                                                          finalize_import)

    # Validate scope
    if request.project_id and request.organization_id:
        raise HTTPException(400, "Set project_id or organization_id, not both")
    if not request.project_id and not request.organization_id:
        raise HTTPException(400, "project_id or organization_id required")

    if request.project_id:
        allowed = await check_permission(
            db,
            user.id,
            ObjectType.PROJECT,
            request.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(403, "EDIT permission required on project")

    if request.organization_id:
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == request.organization_id,
                OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(403, "Org admin required for organization protocols")

    # Convert schema steps to service StepProposals
    steps = [
        StepProposal(
            name=s.name,
            description=s.description,
            category=s.category,
            duration_min=s.duration_min,
            params=s.params,
            param_schema=s.param_schema,
            role=s.role,
            matched_unit_op_id=s.matched_unit_op_id,
            matched_unit_op_name=s.matched_unit_op_name,
            is_new=s.is_new,
        )
        for s in request.steps
    ]

    protocol = await finalize_import(
        steps=steps,
        protocol_name=request.protocol_name,
        protocol_description=request.protocol_description,
        project_id=request.project_id,
        organization_id=request.organization_id,
        user_id=user.id,
        source_filename=request.source_filename,
        db=db,
    )

    await log_audit(
        db,
        user.id,
        "CREATE",
        "Protocol",
        protocol.id,
        {"name": protocol.name, "source": "protocol_import"},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_protocol_full(db, user_id=user.id, protocol_id=protocol_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    # Re-load the ORM object so the existing ProtocolResponse serializer works
    # unchanged (it expects ORM attrs, not the dataclass).
    protocol = await get_or_404(
        db,
        Protocol,
        protocol_id,
        options=[selectinload(Protocol.roles)],
    )

    # F-0066: derive latest_signature_statement / latest_approval_comment
    # from the most recent APPROVED ProtocolApprovalEvent.
    from app.models.science import ProtocolApprovalEvent

    latest = await db.execute(
        select(ProtocolApprovalEvent)
        .where(
            ProtocolApprovalEvent.protocol_id == protocol_id,
            ProtocolApprovalEvent.action == "APPROVED",
        )
        .order_by(ProtocolApprovalEvent.created_at.desc())
        .limit(1)
    )
    latest_ev = latest.scalar_one_or_none()
    # Stash on the ORM instance for `from_attributes` serialization.
    protocol.latest_signature_statement = (  # type: ignore[attr-defined]
        latest_ev.signature_statement if latest_ev else None
    )
    protocol.latest_approval_comment = (  # type: ignore[attr-defined]
        latest_ev.comment if latest_ev else None
    )

    # Surface unpublished drafts so the editor's version toggle can jump to
    # them. Mirrors the same logic in list_project_protocols.
    draft_row = await db.execute(
        select(func.max(ProtocolVersion.version_number)).where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.is_draft.is_(True),
        )
    )
    draft_v = draft_row.scalar_one_or_none()
    if draft_v is not None and draft_v > (protocol.version_number or 0):
        protocol.latest_draft_version_number = draft_v  # type: ignore[attr-defined]

    return protocol


@router.get(
    "/projects/{project_id}/protocols",
    response_model=List[ProtocolResponse],
)
async def list_project_protocols(
    project_id: UUID,
    include_archived: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await list_protocols(
        db,
        user_id=user.id,
        org_id=user.selected_org_id,
        project_id=project_id,
    )
    if not include_archived:
        items = [it for it in items if it.status != "ARCHIVED"]
    ids = [it.id for it in items]
    if not ids:
        return []
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id.in_(ids))
    )
    protos = list(result.scalars().all())
    # Surface unpublished drafts so the project table can badge them. A
    # protocol "has a draft" iff there's a ProtocolVersion row with
    # is_draft=true and version_number greater than the protocol's
    # currently published version_number.
    draft_rows = await db.execute(
        select(
            ProtocolVersion.protocol_id,
            func.max(ProtocolVersion.version_number),
        )
        .where(
            ProtocolVersion.protocol_id.in_(ids),
            ProtocolVersion.is_draft.is_(True),
        )
        .group_by(ProtocolVersion.protocol_id)
    )
    latest_draft_by_protocol = {pid: v for pid, v in draft_rows.all()}
    responses: list[ProtocolResponse] = []
    for p in protos:
        resp = ProtocolResponse.model_validate(p)
        draft_v = latest_draft_by_protocol.get(p.id)
        if draft_v is not None and draft_v > (p.version_number or 0):
            resp.latest_draft_version_number = draft_v
        responses.append(resp)
    return responses


@router.delete("/protocols/{protocol_id}", status_code=200)
async def delete_or_archive_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Delete or archive a protocol.

    - PENDING_APPROVAL → blocked (must reject first)
    - DRAFT + empty graph + no runs → hard delete
    - Otherwise → archive (set status=ARCHIVED)
    """
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="EDIT permission required")

    protocol = await get_or_404(
        db,
        Protocol,
        protocol_id,
        options=[selectinload(Protocol.roles)],
    )

    # Sample/tour protocols always hard-delete, bypassing status guards.
    if protocol.is_tour_sample:
        await log_audit(
            db,
            user.id,
            "DELETE",
            "Protocol",
            protocol.id,
            {"name": protocol.name, "action": "hard_delete_sample"},
        )
        await db.delete(protocol)
        await db.commit()
        return {"action": "deleted", "protocol_id": str(protocol_id)}

    if protocol.status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a protocol pending approval. Reject it first.",
        )

    if protocol.status == "ARCHIVED":
        raise HTTPException(
            status_code=400,
            detail="Protocol is already archived",
        )

    # Check if runs exist for this protocol
    run_count_result = await db.execute(
        select(func.count()).where(Run.protocol_id == protocol_id)
    )
    run_count = run_count_result.scalar() or 0

    # Determine if graph is empty (no nodes)
    graph = protocol.graph or {}
    nodes = graph.get("nodes", [])
    graph_is_empty = len(nodes) == 0

    if protocol.status == "DRAFT" and graph_is_empty and run_count == 0:
        # Hard delete
        await log_audit(
            db,
            user.id,
            "DELETE",
            "Protocol",
            protocol.id,
            {"name": protocol.name, "action": "hard_delete"},
        )
        await db.delete(protocol)
        await db.commit()
        return {"action": "deleted", "protocol_id": str(protocol_id)}
    else:
        # Archive
        old_status = protocol.status
        protocol.status = "ARCHIVED"
        await log_audit(
            db,
            user.id,
            "ARCHIVE",
            "Protocol",
            protocol.id,
            {
                "name": protocol.name,
                "previous_status": old_status,
                "run_count": run_count,
                "had_graph": not graph_is_empty,
            },
        )
        await db.commit()
        return {"action": "archived", "protocol_id": str(protocol_id)}


@router.put("/protocols/{protocol_id}/unarchive", response_model=ProtocolResponse)
async def unarchive_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Unarchive a protocol back to DRAFT. Requires ADMIN on project."""
    protocol = await get_or_404(
        db,
        Protocol,
        protocol_id,
        options=[selectinload(Protocol.roles)],
    )

    if protocol.status != "ARCHIVED":
        raise HTTPException(
            status_code=400,
            detail="Protocol is not archived",
        )

    # Require ADMIN on the parent project (or org admin)
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        protocol.project_id,
        PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Project ADMIN permission required to unarchive",
        )

    protocol.status = "DRAFT"
    await log_audit(
        db,
        user.id,
        "UNARCHIVE",
        "Protocol",
        protocol.id,
        {"name": protocol.name, "restored_to": "DRAFT"},
    )
    await db.commit()
    await db.refresh(protocol)
    return protocol


@router.post(
    "/protocols/{protocol_id}/designate-approval",
    response_model=ProtocolResponse,
)
async def designate_approval(
    protocol_id: UUID,
    body: DesignateApprovalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Toggle Protocol.requires_approval. Only the creator or a project admin
    may change it, and only while the protocol is in DRAFT status.

    Turning it on requires the parent project's
    `settings.require_protocol_approval` flag to be enabled first.
    """
    protocol = await get_or_404(
        db,
        Protocol,
        protocol_id,
        options=[selectinload(Protocol.roles)],
    )

    if protocol.project_id is None:
        raise HTTPException(
            status_code=400,
            detail="requires_approval is only supported for project-scoped protocols.",
        )

    project = await get_or_404(db, Project, protocol.project_id)

    is_creator = protocol.created_by_id == user.id
    is_admin = await check_permission(
        db,
        user.id,
        ObjectType.PROJECT,
        project.id,
        PermissionLevel.ADMIN,
    )
    if not (is_creator or is_admin):
        raise HTTPException(
            status_code=403,
            detail=(
                "Only the protocol creator or a project admin can change "
                "requires_approval."
            ),
        )

    if protocol.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail="requires_approval can only be changed while status is DRAFT.",
        )

    if body.requires_approval and not (project.settings or {}).get(
        "require_protocol_approval"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Project setting `require_protocol_approval` must be enabled "
                "before designating a protocol as requiring approval."
            ),
        )

    protocol.requires_approval = body.requires_approval

    await log_audit(
        db,
        user.id,
        "UPDATE",
        "Protocol",
        protocol.id,
        {"requires_approval": body.requires_approval},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(
    protocol_id: UUID,
    update_data: ProtocolUpdate,
    background_tasks: BackgroundTasks,
    save_as_draft: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    protocol = await get_or_404(
        db,
        Protocol,
        protocol_id,
        options=[selectinload(Protocol.roles)],
    )

    changes = update_data.model_dump(exclude_unset=True)

    changed_fields = set(changes.keys()) & APPROVED_EDIT_FIELDS

    # Block edits while pending approval
    if protocol.status == "PENDING_APPROVAL" and changed_fields:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit protocol while pending approval",
        )

    # F-0066 Task 14: APPROVED protocols can be edited only by the creator,
    # a project admin, or an approver, and any such edit auto-reverts the
    # protocol to DRAFT and emits a single REVERTED event. Doing this
    # *before* the metadata-only fast-path means a rename-while-APPROVED
    # still triggers the revert + audit trail (the fast-path otherwise
    # 409s on any non-DRAFT protocol).
    auto_revert_emitted = False
    if protocol.status == "APPROVED" and changed_fields:
        is_creator = protocol.created_by_id == user.id
        is_admin = False
        is_approver = False
        if protocol.project_id is not None:
            is_admin = await check_permission(
                db,
                user.id,
                ObjectType.PROJECT,
                protocol.project_id,
                PermissionLevel.ADMIN,
            )
        is_approver = await check_permission(
            db,
            user.id,
            ObjectType.PROTOCOL,
            protocol.id,
            PermissionLevel.APPROVE,
        )
        if not (is_creator or is_admin or is_approver):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only the creator, project admin, or an approver can "
                    "edit an APPROVED protocol."
                ),
            )

        protocol.status = "DRAFT"
        protocol.approved_by_id = None
        protocol.approved_at = None

        await write_event(
            db,
            protocol=protocol,
            actor_id=user.id,
            action="REVERTED",
        )
        # Flush so the metadata-only fast path below (which re-SELECTs
        # the protocol inside update_protocol_metadata) sees the new
        # DRAFT status and doesn't 409 on its "published" guard.
        await db.flush()
        auto_revert_emitted = True

    # Metadata-only patch fast path (no graph change, no draft request) —
    # delegate to the canonical service so chat tools and HTTP share logic.
    if (
        "graph" not in changes
        and not save_as_draft
        and any(k in changes for k in ("name", "description"))
    ):
        from app.services.protocols.creation import update_protocol_metadata

        try:
            await update_protocol_metadata(
                db,
                user_id=user.id,
                protocol_id=protocol_id,
                name=changes.get("name"),
                description=changes.get("description"),
            )
        except ValueError as e:
            msg = str(e)
            if "published" in msg:
                raise HTTPException(status_code=409, detail=msg)
            raise HTTPException(status_code=403, detail=msg)
        for k in ("name", "description"):
            changes.pop(k, None)

    # If graph is being updated and save_as_draft is True
    if "graph" in changes and save_as_draft:
        new_graph = changes["graph"]
        # Always create/update the draft when save_as_draft is requested.
        # The user's intent to save a draft means we should always have a
        # draft version to publish, even if the graph is semantically unchanged.
        draft_version_number = protocol.version_number + 1

        # Check if draft already exists
        existing_draft = await db.execute(
            select(ProtocolVersion).where(
                (ProtocolVersion.protocol_id == protocol_id)
                & (ProtocolVersion.version_number == draft_version_number)
                & (ProtocolVersion.is_draft == True)
            )
        )
        draft = existing_draft.scalar_one_or_none()

        if draft:
            # Update existing draft
            draft.graph = new_graph
        else:
            # Create new draft version
            draft = ProtocolVersion(
                protocol_id=protocol.id,
                version_number=draft_version_number,
                graph=new_graph,
                name=changes.get("name", protocol.name),
                description=changes.get("description", protocol.description),
                created_by_id=user.id,
                is_draft=True,
                sop_template_id=protocol.sop_template_id,
                batch_record_template_id=protocol.batch_record_template_id,
            )
            db.add(draft)

        # For unpublished protocols (still DRAFT), the live graph IS the
        # working draft — keep it in sync so role/lane mutations from
        # other paths (sidebar, chat tools) and the editor's saved state
        # don't drift apart. Published protocols stay frozen until the
        # draft is explicitly published.
        if protocol.status == "DRAFT":
            protocol.graph = new_graph

        audit_changes = {"action": "saved_draft", "draft_version": draft_version_number}
    else:
        # Normal save: update protocol graph and create version
        if "graph" in changes:
            protocol.version_number += 1
            version = ProtocolVersion(
                protocol_id=protocol.id,
                version_number=protocol.version_number,
                graph=changes["graph"],
                name=changes.get("name", protocol.name),
                description=changes.get("description", protocol.description),
                created_by_id=user.id,
                is_draft=False,
                sop_template_id=protocol.sop_template_id,
                batch_record_template_id=protocol.batch_record_template_id,
            )
            db.add(version)

            # F-0066 Task 14: status flip + REVERTED event are emitted at the
            # top of this handler (auto_revert_emitted). Here we just keep
            # the legacy notification side-effect when a graph edit was the
            # trigger, so project admins still hear about it.
            if auto_revert_emitted and "graph" in changes:
                # Notify project admins of reversion
                proj_result = await db.execute(
                    select(Project).where(Project.id == protocol.project_id)
                )
                proj = proj_result.scalar_one()
                admin_result = await db.execute(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == proj.organization_id,
                        OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
                    )
                )
                admin_ids = [row[0] for row in admin_result.all() if row[0] != user.id]
                if admin_ids:
                    background_tasks.add_task(
                        send_notification,
                        db=db,
                        event_type="PROTOCOL_REVERTED",
                        org_id=proj.organization_id,
                        entity_type="protocol",
                        entity_id=protocol.id,
                        recipients=admin_ids,
                        context={
                            "protocol_name": protocol.name,
                            "edited_by": user.full_name or user.email,
                        },
                    )

        # Update protocol fields (name, description, etc.)
        for key, value in changes.items():
            setattr(protocol, key, value)

        audit_changes = dict(changes)
        if "graph" in changes:
            audit_changes["version_number"] = protocol.version_number

    await log_audit(
        db,
        user.id,
        "UPDATE",
        "Protocol",
        protocol.id,
        audit_changes,
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Protocol Roles (inherit project perms) ---


@router.get(
    "/protocols/{protocol_id}/roles",
    response_model=List[ProtocolRoleResponse],
)
async def list_protocol_roles(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await list_roles(db, user_id=user.id, protocol_id=protocol_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=403, detail=msg)


@router.post(
    "/protocols/{protocol_id}/roles",
    response_model=ProtocolRoleResponse,
    status_code=201,
)
async def create_protocol_role(
    protocol_id: UUID,
    role: ProtocolRoleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    try:
        new_role = await add_role(
            db,
            user_id=user.id,
            protocol_id=protocol_id,
            name=role.name,
            color=role.color,
            sort_order=role.sort_order,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    await db.refresh(new_role)
    return new_role


@router.put(
    "/protocols/{protocol_id}/roles/{role_id}",
    response_model=ProtocolRoleResponse,
)
async def update_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    update_data: ProtocolRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    changes = update_data.model_dump(exclude_unset=True)
    try:
        updated = await update_role(db, user_id=user.id, role_id=role_id, **changes)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    await db.refresh(updated)
    return updated


@router.delete("/protocols/{protocol_id}/roles/{role_id}")
async def delete_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    try:
        await remove_role(db, user_id=user.id, role_id=role_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    await db.commit()
    return {"ok": True}
