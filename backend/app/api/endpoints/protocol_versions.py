import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    OrganizationMember,
    OrgRole,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.science import (
    Project,
    Protocol,
    ProtocolApprovalEvent,
    ProtocolApprovalRequest,
    ProtocolVersion,
    UnitOpDefinition,
)
from app.schemas.science import (
    ApprovalActorRef,
    ApproveProtocolRequest,
    AwaitingApprovalItem,
    ProtocolApprovalEventResponse,
    ProtocolResponse,
    ProtocolVersionListItem,
    ProtocolVersionRef,
    ProtocolVersionResponse,
    PublishDraftRequest,
    RejectProtocolRequest,
    SubmitForApprovalRequest,
)
from app.services.approvals import fulfill_open_requests, write_event
from app.services.core.audit import log_audit
from app.services.core.notifications import send_notification
from app.services.core.permissions import check_permission
from app.services.protocols.validation import assert_no_branch_errors

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Awaiting My Approval ---
# IMPORTANT: this route is registered BEFORE /protocols/{protocol_id}/... so
# FastAPI doesn't try to parse "awaiting-my-approval" as a UUID.


@router.get(
    "/protocols/awaiting-my-approval",
    response_model=List[AwaitingApprovalItem],
)
async def list_awaiting_my_approval(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List protocols pending approval that the current user can act on."""
    from app.services.approvals.awaiting import list_awaiting_for_user

    items = await list_awaiting_for_user(db, user.id)
    return items


# --- Protocol Version History ---


@router.get(
    "/protocols/{protocol_id}/versions",
    response_model=List[ProtocolVersionListItem],
)
async def list_protocol_versions(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolVersion)
        .options(selectinload(ProtocolVersion.created_by))
        .where(ProtocolVersion.protocol_id == protocol_id)
        .order_by(ProtocolVersion.version_number.desc())
    )
    versions = result.scalars().all()

    return [
        ProtocolVersionListItem(
            id=v.id,
            version_number=v.version_number,
            name=v.name,
            description=v.description,
            change_summary=v.change_summary,
            created_by_name=(
                v.created_by.full_name or v.created_by.email if v.created_by else None
            ),
            created_at=v.created_at,
            is_draft=v.is_draft,
        )
        for v in versions
    ]


@router.get(
    "/protocols/{protocol_id}/versions/{version_number}",
    response_model=ProtocolVersionResponse,
)
async def get_protocol_version(
    protocol_id: UUID,
    version_number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolVersion)
        .options(selectinload(ProtocolVersion.created_by))
        .where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.version_number == version_number,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return ProtocolVersionResponse(
        id=version.id,
        protocol_id=version.protocol_id,
        version_number=version.version_number,
        graph=version.graph,
        name=version.name,
        description=version.description,
        change_summary=version.change_summary,
        created_by_id=version.created_by_id,
        created_by_name=(
            version.created_by.full_name or version.created_by.email
            if version.created_by
            else None
        ),
        created_at=version.created_at,
    )


@router.post(
    "/protocols/{protocol_id}/revert/{version_number}",
    response_model=ProtocolResponse,
)
async def revert_protocol_version(
    protocol_id: UUID,
    version_number: int,
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

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol.status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail="Cannot revert protocol while pending approval",
        )

    result = await db.execute(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.version_number == version_number,
        )
    )
    old_version = result.scalar_one_or_none()
    if not old_version:
        raise HTTPException(status_code=404, detail="Version not found")

    # Create new version with the reverted graph
    protocol.version_number += 1
    protocol.graph = old_version.graph

    new_version = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=protocol.version_number,
        graph=old_version.graph,
        name=protocol.name,
        description=protocol.description,
        created_by_id=user.id,
        change_summary=f"Reverted to v{version_number}",
        sop_template_id=protocol.sop_template_id,
        batch_record_template_id=protocol.batch_record_template_id,
    )
    db.add(new_version)

    if protocol.status == "APPROVED":
        protocol.status = "DRAFT"

    await log_audit(
        db,
        user.id,
        "UPDATE",
        "Protocol",
        protocol.id,
        {
            "reverted_to_version": version_number,
            "version_number": protocol.version_number,
        },
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Protocol Approval ---


@router.post(
    "/protocols/{protocol_id}/submit-for-approval",
    response_model=ProtocolResponse,
)
async def submit_protocol_for_approval(
    protocol_id: UUID,
    body: SubmitForApprovalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Move a DRAFT protocol to PENDING_APPROVAL and request approval from
    the listed users.

    Each requested user must either (a) hold APPROVE on the parent project
    via ObjectPermission, or (b) hold the org PROTOCOL_APPROVER role in the
    same organization as the project.
    """
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if not protocol.requires_approval:
        raise HTTPException(
            status_code=400,
            detail="Protocol does not require approval. Designate it first.",
        )

    if protocol.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit: protocol status is {protocol.status}.",
        )

    if not body.requested_user_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one approver must be requested.",
        )

    # Resolve org context — supports project-scoped protocols (the typical case
    # for approval). Org-scoped protocols still need an org for the role lookup.
    org_id: Optional[UUID] = None
    if protocol.project_id is not None:
        proj_row = await db.execute(
            select(Project).where(Project.id == protocol.project_id)
        )
        project_obj = proj_row.scalar_one_or_none()
        if project_obj is None:
            raise HTTPException(status_code=404, detail="Project not found")
        org_id = project_obj.organization_id
    else:
        org_id = protocol.organization_id

    # Build eligibility set
    eligible: set[UUID] = set()
    if protocol.project_id is not None:
        proj_perm_rows = await db.execute(
            select(ObjectPermission.principal_id).where(
                ObjectPermission.object_type == ObjectType.PROJECT.value,
                ObjectPermission.object_id == protocol.project_id,
                ObjectPermission.principal_type == PrincipalType.USER.value,
                ObjectPermission.permission_level == PermissionLevel.APPROVE.value,
            )
        )
        eligible.update(proj_perm_rows.scalars().all())

    if org_id is not None:
        org_approver_rows = await db.execute(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.roles.contains([OrgRole.PROTOCOL_APPROVER.value]),
            )
        )
        eligible.update(org_approver_rows.scalars().all())

    requested = set(body.requested_user_ids)
    ineligible = requested - eligible
    if ineligible:
        raise HTTPException(
            status_code=400,
            detail=(
                "One or more requested users are not eligible approvers: "
                + ", ".join(str(u) for u in ineligible)
            ),
        )

    # State transitions
    protocol.status = "PENDING_APPROVAL"

    for uid in requested:
        db.add(
            ProtocolApprovalRequest(
                protocol_id=protocol.id,
                requested_user_id=uid,
                requested_by_id=user.id,
                status="OPEN",
            )
        )

    await write_event(
        db,
        protocol=protocol,
        actor_id=user.id,
        action="SUBMITTED",
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


@router.post(
    "/protocols/{protocol_id}/approve",
    response_model=ProtocolResponse,
)
async def approve_protocol(
    protocol_id: UUID,
    body: ApproveProtocolRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Approve a PENDING_APPROVAL protocol.

    Requires APPROVE on the protocol (granted via project APPROVE
    permission or via the org PROTOCOL_APPROVER role).
    """
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required to approve this protocol.",
        )

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve: protocol is {protocol_obj.status}.",
        )

    protocol_obj.status = "APPROVED"
    protocol_obj.approved_by_id = user.id
    protocol_obj.approved_at = datetime.now(timezone.utc)

    await write_event(
        db,
        protocol=protocol_obj,
        actor_id=user.id,
        action="APPROVED",
        comment=body.comment,
        signature_statement=body.signature_statement,
    )
    await fulfill_open_requests(
        db,
        protocol_id=protocol_obj.id,
        final_status="APPROVED",
        actor_id=user.id,
    )

    await db.commit()

    # Notify protocol author of approval (best-effort, project-scoped only)
    if protocol_obj.project_id is not None:
        proj = await db.execute(
            select(Project).where(Project.id == protocol_obj.project_id)
        )
        project = proj.scalar_one_or_none()
        if project is not None:
            ver_result = await db.execute(
                select(ProtocolVersion.created_by_id)
                .where(ProtocolVersion.protocol_id == protocol_id)
                .order_by(ProtocolVersion.version_number.desc())
                .limit(1)
            )
            author_id = ver_result.scalar_one_or_none()
            if author_id and author_id != user.id:
                background_tasks.add_task(
                    send_notification,
                    db=db,
                    event_type="PROTOCOL_APPROVED",
                    org_id=project.organization_id,
                    entity_type="protocol",
                    entity_id=protocol_obj.id,
                    recipients=[author_id],
                    context={
                        "protocol_name": protocol_obj.name,
                        "approved_by": user.full_name or user.email,
                    },
                )

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_obj.id)
    )
    return result.scalar_one()


@router.post(
    "/protocols/{protocol_id}/reject",
    response_model=ProtocolResponse,
)
async def reject_protocol(
    protocol_id: UUID,
    body: RejectProtocolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Reject a PENDING_APPROVAL protocol, returning it to DRAFT.

    Requires APPROVE on the protocol. A non-empty `comment` is required
    so the author understands why the protocol was sent back.
    """
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required to reject this protocol.",
        )

    result = await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject: protocol is {protocol_obj.status}.",
        )

    protocol_obj.status = "DRAFT"

    await write_event(
        db,
        protocol=protocol_obj,
        actor_id=user.id,
        action="REJECTED",
        comment=body.comment,
        signature_statement=body.signature_statement,
    )
    await fulfill_open_requests(
        db,
        protocol_id=protocol_obj.id,
        final_status="REJECTED",
        actor_id=user.id,
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_obj.id)
    )
    return result.scalar_one()


@router.post(
    "/protocols/{protocol_id}/publish-draft",
    response_model=ProtocolResponse,
)
async def publish_draft_version(
    protocol_id: UUID,
    version_number: int = Query(...),
    body: Optional[PublishDraftRequest] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Publish a draft version: set is_draft=False and update main protocol."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    # Find the draft version
    version_result = await db.execute(
        select(ProtocolVersion).where(
            (ProtocolVersion.protocol_id == protocol_id)
            & (ProtocolVersion.version_number == version_number)
            & (ProtocolVersion.is_draft == True)
        )
    )
    draft = version_result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft version not found")

    # Defense-in-depth: reject publish if branch role rule fires.
    org_id = user.selected_org_id
    unit_ops_result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.organization_id == org_id)
    )
    unit_ops = list(unit_ops_result.scalars().all())
    assert_no_branch_errors(draft.graph or {}, unit_ops)

    # Mark as published (not a draft) and update main protocol
    draft.is_draft = False
    if body is not None:
        if body.description is not None:
            draft.description = body.description
        if body.change_summary is not None:
            draft.change_summary = body.change_summary
    protocol.graph = draft.graph
    protocol.version_number = version_number

    await log_audit(
        db,
        user.id,
        "UPDATE",
        "Protocol",
        protocol.id,
        {"action": "published_draft", "version_number": version_number},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()


# --- Approval History ---


@router.get(
    "/protocols/{protocol_id}/approval-history",
    response_model=List[ProtocolApprovalEventResponse],
)
async def list_approval_history(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the protocol's approval events, newest first."""
    allowed = await check_permission(
        db,
        user.id,
        ObjectType.PROTOCOL,
        protocol_id,
        PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolApprovalEvent)
        .options(
            selectinload(ProtocolApprovalEvent.actor),
            selectinload(ProtocolApprovalEvent.protocol_version),
        )
        .where(ProtocolApprovalEvent.protocol_id == protocol_id)
        .order_by(ProtocolApprovalEvent.created_at.desc())
    )
    events = result.scalars().all()

    response: list[ProtocolApprovalEventResponse] = []
    for ev in events:
        actor_ref = None
        if ev.actor is not None:
            actor_ref = ApprovalActorRef(
                id=ev.actor.id,
                name=ev.actor.full_name or ev.actor.email,
                email=ev.actor.email,
            )
        version_ref = None
        if ev.protocol_version is not None:
            version_ref = ProtocolVersionRef(
                id=ev.protocol_version.id,
                version_number=ev.protocol_version.version_number,
            )
        response.append(
            ProtocolApprovalEventResponse(
                id=ev.id,
                action=ev.action,
                comment=ev.comment,
                signature_statement=ev.signature_statement,
                actor=actor_ref,
                protocol_version=version_ref,
                created_at=ev.created_at,
            )
        )
    return response
