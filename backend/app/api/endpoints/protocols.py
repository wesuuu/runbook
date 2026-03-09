import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.iam import (
    User,
    ObjectType,
    PermissionLevel,
    OrganizationMember,
)
from app.models.science import (
    Protocol,
    ProtocolVersion,
    ProtocolRole,
    Run,
    Project,
)
from app.schemas.science import (
    ProtocolCreate,
    ProtocolUpdate,
    ProtocolResponse,
    ProtocolRoleCreate,
    ProtocolRoleUpdate,
    ProtocolRoleResponse,
)
from app.services.audit import log_audit
from app.services.notifications import send_notification
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Protocols ---

@router.post(
    "/protocols", response_model=ProtocolResponse, status_code=201,
)
async def create_protocol(
    protocol: ProtocolCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check user has EDIT on the parent project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    result = await db.execute(
        select(Project).where(Project.id == protocol.project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    new_protocol = Protocol(
        name=protocol.name,
        description=protocol.description,
        project_id=protocol.project_id,
        graph=protocol.graph,
    )
    db.add(new_protocol)
    await db.flush()

    await log_audit(
        db, user.id, "CREATE", "Protocol",
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


@router.get("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(
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
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.get(
    "/projects/{project_id}/protocols",
    response_model=List[ProtocolResponse],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_project_protocols(
    project_id: UUID,
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.project_id == project_id)
    )
    if not include_archived:
        stmt = stmt.where(Protocol.status != "ARCHIVED")
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/protocols/{protocol_id}", status_code=200)
async def delete_or_archive_protocol(
    protocol_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete or archive a protocol.

    - PENDING_APPROVAL → blocked (must reject first)
    - DRAFT + empty graph + no runs → hard delete
    - Otherwise → archive (set status=ARCHIVED)
    """
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="EDIT permission required")

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
            status_code=400,
            detail="Cannot delete a protocol pending approval. Reject it first.",
        )

    if protocol.status == "ARCHIVED":
        raise HTTPException(
            status_code=400, detail="Protocol is already archived",
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
            db, user.id, "DELETE", "Protocol",
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
            db, user.id, "ARCHIVE", "Protocol",
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
):
    """Unarchive a protocol back to DRAFT. Requires ADMIN on project."""
    result = await db.execute(
        select(Protocol)
        .options(selectinload(Protocol.roles))
        .where(Protocol.id == protocol_id)
    )
    protocol = result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")

    if protocol.status != "ARCHIVED":
        raise HTTPException(
            status_code=400, detail="Protocol is not archived",
        )

    # Require ADMIN on the parent project (or org admin)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        protocol.project_id, PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Project ADMIN permission required to unarchive",
        )

    protocol.status = "DRAFT"
    await log_audit(
        db, user.id, "UNARCHIVE", "Protocol",
        protocol.id,
        {"name": protocol.name, "restored_to": "DRAFT"},
    )
    await db.commit()
    await db.refresh(protocol)
    return protocol


@router.put("/protocols/{protocol_id}", response_model=ProtocolResponse)
async def update_protocol(
    protocol_id: UUID,
    update_data: ProtocolUpdate,
    background_tasks: BackgroundTasks,
    save_as_draft: bool = Query(False),
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

    changes = update_data.model_dump(exclude_unset=True)

    # Block edits while pending approval
    if protocol.status == "PENDING_APPROVAL" and "graph" in changes:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit protocol while pending approval",
        )

    # If graph is being updated and save_as_draft is True
    if "graph" in changes and save_as_draft:
        new_graph = changes["graph"]
        # Check if graph actually changed compared to current protocol
        if new_graph != protocol.graph:
            # Create/update draft version without modifying main protocol
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
                )
                db.add(draft)

            audit_changes = {"action": "saved_draft", "draft_version": draft_version_number}
        else:
            # No meaningful changes to graph
            audit_changes = {"action": "save_draft_attempt", "result": "no_changes"}
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
            )
            db.add(version)

            # Revert approved protocol to draft on edit
            if protocol.status == "APPROVED":
                protocol.status = "DRAFT"

                # Notify project admins of reversion
                proj_result = await db.execute(
                    select(Project).where(Project.id == protocol.project_id)
                )
                proj = proj_result.scalar_one()
                admin_result = await db.execute(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == proj.organization_id,
                        OrganizationMember.role == "ADMIN",
                    )
                )
                admin_ids = [
                    row[0] for row in admin_result.all()
                    if row[0] != user.id
                ]
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
        db, user.id, "UPDATE", "Protocol", protocol.id, audit_changes,
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
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole)
        .where(ProtocolRole.protocol_id == protocol_id)
        .order_by(ProtocolRole.sort_order)
    )
    return result.scalars().all()


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
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(Protocol).where(Protocol.id == protocol_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Protocol not found")

    new_role = ProtocolRole(
        protocol_id=protocol_id,
        name=role.name,
        color=role.color,
        sort_order=role.sort_order,
    )
    db.add(new_role)
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
):
    allowed = await check_permission(
        db, user.id, ObjectType.PROTOCOL,
        protocol_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(role, key, value)

    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/protocols/{protocol_id}/roles/{role_id}")
async def delete_protocol_role(
    protocol_id: UUID,
    role_id: UUID,
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
        select(ProtocolRole).where(
            ProtocolRole.id == role_id,
            ProtocolRole.protocol_id == protocol_id,
        )
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    await db.delete(role)
    await db.commit()
    return {"ok": True}
