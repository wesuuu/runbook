from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.execution import AuditLog
from app.models.iam import (
    User,
    Team,
    OrganizationMember,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project, Protocol, Run
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    AuditLogEntry,
    AuditLogPage,
    ApproverGrant,
    ApproverEntry,
)
from app.services.audit import log_audit
from app.services.permissions import check_permission, get_visible_project_ids

router = APIRouter()


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    project: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify user is org member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == project.organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail="Must be an organization member to create projects",
        )

    # Default ownership to the creating user
    owner_type = project.owner_type or "USER"
    owner_id = project.owner_id or user.id

    db_project = Project(
        name=project.name,
        description=project.description,
        organization_id=project.organization_id,
        owner_type=owner_type,
        owner_id=owner_id,
    )
    db.add(db_project)
    await db.flush()

    # Auto-grant ADMIN permission to the creator
    perm = ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=db_project.id,
        permission_level=PermissionLevel.ADMIN.value,
    )
    db.add(perm)

    await log_audit(
        db,
        actor_id=user.id,
        action="CREATE",
        entity_type="Project",
        entity_id=db_project.id,
        changes=project.model_dump(),
    )

    await db.commit()
    await db.refresh(db_project)
    return db_project


@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    organization_id: UUID = Query(...),
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    visible_ids = await get_visible_project_ids(
        db, user.id, organization_id
    )
    if not visible_ids:
        return []

    result = await db.execute(
        select(Project)
        .where(Project.id.in_(visible_ids))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.EDIT
            )
        )
    ],
)
async def update_project(
    project_id: UUID,
    update_data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    changes = update_data.model_dump(exclude_unset=True)
    if not changes:
        return project

    # Require ADMIN for settings changes
    if "settings" in changes:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT,
            project_id, PermissionLevel.ADMIN,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="ADMIN permission required to update settings",
            )

    for key, value in changes.items():
        setattr(project, key, value)

    await log_audit(
        db,
        actor_id=user.id,
        action="UPDATE",
        entity_type="Project",
        entity_id=project.id,
        changes=changes,
    )

    await db.commit()
    await db.refresh(project)
    return project


@router.delete(
    "/{project_id}",
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.ADMIN
            )
        )
    ],
)
async def delete_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await log_audit(
        db,
        actor_id=user.id,
        action="DELETE",
        entity_type="Project",
        entity_id=project.id,
        changes={"name": project.name},
    )

    # Clean up permissions for this project
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.object_type == ObjectType.PROJECT.value,
            ObjectPermission.object_id == project_id,
        )
    )
    for perm in result.scalars().all():
        await db.delete(perm)

    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get(
    "/{project_id}/activity",
    response_model=AuditLogPage,
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def get_project_activity(
    project_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Verify project exists
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Collect child entity IDs
    proto_result = await db.execute(
        select(Protocol.id).where(Protocol.project_id == project_id)
    )
    protocol_ids = list(proto_result.scalars().all())

    run_result = await db.execute(
        select(Run.id).where(Run.project_id == project_id)
    )
    run_ids = list(run_result.scalars().all())

    # Build filter conditions for all related entities
    conditions = [
        (AuditLog.entity_type == "Project")
        & (AuditLog.entity_id == project_id),
    ]
    if protocol_ids:
        conditions.append(
            (AuditLog.entity_type == "Protocol")
            & (AuditLog.entity_id.in_(protocol_ids))
        )
    if run_ids:
        conditions.append(
            (AuditLog.entity_type == "Run")
            & (AuditLog.entity_id.in_(run_ids))
        )

    base_filter = or_(*conditions)

    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(base_filter)
    )
    total = count_result.scalar_one()

    # Fetch page of audit logs with actor eager-loaded
    logs_result = await db.execute(
        select(AuditLog)
        .options(selectinload(AuditLog.actor))
        .where(base_filter)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    logs = list(logs_result.scalars().all())

    # Batch-resolve entity names
    entity_name_map: dict[str, str] = {}

    # Protocols
    proto_ids_in_logs = {
        l.entity_id for l in logs if l.entity_type == "Protocol"
    }
    if proto_ids_in_logs:
        name_result = await db.execute(
            select(Protocol.id, Protocol.name).where(
                Protocol.id.in_(proto_ids_in_logs)
            )
        )
        for row in name_result.all():
            entity_name_map[f"Protocol:{row[0]}"] = row[1]

    # Runs
    run_ids_in_logs = {
        l.entity_id for l in logs if l.entity_type == "Run"
    }
    if run_ids_in_logs:
        name_result = await db.execute(
            select(Run.id, Run.name).where(Run.id.in_(run_ids_in_logs))
        )
        for row in name_result.all():
            entity_name_map[f"Run:{row[0]}"] = row[1]

    # Project name
    proj_result = await db.execute(
        select(Project.name).where(Project.id == project_id)
    )
    proj_name = proj_result.scalar_one_or_none()
    entity_name_map[f"Project:{project_id}"] = proj_name or ""

    # Build response
    items = []
    for log in logs:
        key = f"{log.entity_type}:{log.entity_id}"
        entity_name = entity_name_map.get(key)
        # Fallback to changes["name"] for deleted entities
        if entity_name is None and log.changes:
            entity_name = log.changes.get("name")

        items.append(
            AuditLogEntry(
                id=log.id,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                entity_name=entity_name,
                action=log.action,
                changes=log.changes or {},
                actor_name=log.actor.full_name if log.actor else None,
                actor_email=log.actor.email if log.actor else None,
                created_at=log.created_at,
            )
        )

    return AuditLogPage(
        items=items, total=total, offset=offset, limit=limit
    )


# --- Approver Management ---

@router.get(
    "/{project_id}/approvers",
    response_model=List[ApproverEntry],
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.VIEW
            )
        )
    ],
)
async def list_approvers(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.object_type == ObjectType.PROJECT.value,
            ObjectPermission.object_id == project_id,
            ObjectPermission.permission_level == PermissionLevel.APPROVE.value,
        )
    )
    perms = result.scalars().all()

    entries: list[ApproverEntry] = []
    for perm in perms:
        name = None
        email = None
        if perm.principal_type == PrincipalType.USER.value:
            u_result = await db.execute(
                select(User).where(User.id == perm.principal_id)
            )
            u = u_result.scalar_one_or_none()
            if u:
                name = u.full_name or u.email
                email = u.email
        elif perm.principal_type == PrincipalType.TEAM.value:
            t_result = await db.execute(
                select(Team).where(Team.id == perm.principal_id)
            )
            t = t_result.scalar_one_or_none()
            if t:
                name = t.name
        entries.append(ApproverEntry(
            id=perm.id,
            principal_type=perm.principal_type,
            principal_id=perm.principal_id,
            name=name,
            email=email,
        ))
    return entries


@router.post(
    "/{project_id}/approvers",
    response_model=ApproverEntry,
    status_code=201,
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.ADMIN
            )
        )
    ],
)
async def add_approver(
    project_id: UUID,
    grant: ApproverGrant,
    db: AsyncSession = Depends(get_db),
):
    # Check if permission already exists
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.principal_type == grant.principal_type,
            ObjectPermission.principal_id == grant.principal_id,
            ObjectPermission.object_type == ObjectType.PROJECT.value,
            ObjectPermission.object_id == project_id,
            ObjectPermission.permission_level == PermissionLevel.APPROVE.value,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409, detail="Approver already exists"
        )

    perm = ObjectPermission(
        principal_type=grant.principal_type,
        principal_id=grant.principal_id,
        object_type=ObjectType.PROJECT.value,
        object_id=project_id,
        permission_level=PermissionLevel.APPROVE.value,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)

    # Resolve name
    name = None
    email = None
    if grant.principal_type == PrincipalType.USER.value:
        u_result = await db.execute(
            select(User).where(User.id == grant.principal_id)
        )
        u = u_result.scalar_one_or_none()
        if u:
            name = u.full_name or u.email
            email = u.email
    elif grant.principal_type == PrincipalType.TEAM.value:
        t_result = await db.execute(
            select(Team).where(Team.id == grant.principal_id)
        )
        t = t_result.scalar_one_or_none()
        if t:
            name = t.name

    return ApproverEntry(
        id=perm.id,
        principal_type=perm.principal_type,
        principal_id=perm.principal_id,
        name=name,
        email=email,
    )


@router.delete(
    "/{project_id}/approvers/{permission_id}",
    dependencies=[
        Depends(
            require_permission(
                ObjectType.PROJECT, "project_id", PermissionLevel.ADMIN
            )
        )
    ],
)
async def remove_approver(
    project_id: UUID,
    permission_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.id == permission_id,
            ObjectPermission.object_type == ObjectType.PROJECT.value,
            ObjectPermission.object_id == project_id,
            ObjectPermission.permission_level == PermissionLevel.APPROVE.value,
        )
    )
    perm = result.scalar_one_or_none()
    if not perm:
        raise HTTPException(status_code=404, detail="Approver not found")

    await db.delete(perm)
    await db.commit()
    return {"ok": True}
