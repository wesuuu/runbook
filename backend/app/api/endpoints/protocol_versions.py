import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User, ObjectType, PermissionLevel
from app.models.science import Protocol, ProtocolVersion, Project
from app.schemas.science import (
    ProtocolResponse,
    ProtocolApprovalAction,
    ProtocolVersionListItem,
    ProtocolVersionResponse,
)
from app.services.audit import log_audit
from app.services.notifications import send_notification
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


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
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
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
            change_summary=v.change_summary,
            created_by_name=(
                v.created_by.full_name or v.created_by.email
                if v.created_by else None
            ),
            created_at=v.created_at,
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
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
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
            if version.created_by else None
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
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
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
    )
    db.add(new_version)

    if protocol.status == "APPROVED":
        protocol.status = "DRAFT"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id,
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
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

    if protocol.status != "DRAFT":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit: protocol is {protocol.status}",
        )

    protocol.status = "PENDING_APPROVAL"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id,
        {"status": "PENDING_APPROVAL"},
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
    action: ProtocolApprovalAction,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Require APPROVE permission on the parent project
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol_obj.project_id, PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required on project",
        )

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: protocol is {protocol_obj.status}",
        )

    protocol_obj.status = "APPROVED"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol_obj.id,
        {"status": "APPROVED", "comment": action.comment},
    )

    await db.commit()

    # Notify protocol author of approval
    proj = await db.execute(
        select(Project).where(Project.id == protocol_obj.project_id)
    )
    project = proj.scalar_one()

    # Find the protocol author (latest version's created_by_id)
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
    action: ProtocolApprovalAction,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Require APPROVE permission on the parent project
    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    protocol_obj = result.scalar_one_or_none()
    if not protocol_obj:
        raise HTTPException(status_code=404, detail="Protocol not found")

    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol_obj.project_id, PermissionLevel.APPROVE,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="APPROVE permission required on project",
        )

    if protocol_obj.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: protocol is {protocol_obj.status}",
        )

    protocol_obj.status = "DRAFT"

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol_obj.id,
        {"status": "DRAFT", "action": "rejected", "comment": action.comment},
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish a draft version: set is_draft=False and update main protocol."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
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
        select(ProtocolVersion)
        .where(
            (ProtocolVersion.protocol_id == protocol_id)
            & (ProtocolVersion.version_number == version_number)
            & (ProtocolVersion.is_draft == True)
        )
    )
    draft = version_result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft version not found")

    # Mark as published (not a draft) and update main protocol
    draft.is_draft = False
    protocol.graph = draft.graph
    protocol.version_number = version_number

    await log_audit(
        db, user.id, "UPDATE", "Protocol", protocol.id,
        {"action": "published_draft", "version_number": version_number},
    )

    await db.commit()

    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol.id)
    )
    return result.scalar_one()
