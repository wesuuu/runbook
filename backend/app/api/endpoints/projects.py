from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlalchemy
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
    entity_type: str | None = Query(None, description="Filter by entity type (comma-separated: Project,Protocol,Run)"),
    action: str | None = Query(None, description="Filter by action (comma-separated: CREATE,UPDATE,DELETE,STEP_EDIT,STEP_COMPLETE,STEP_UNCOMPLETE)"),
    search: str | None = Query(None, description="Search entity names and change details"),
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
    # When entity_type filter is set, only include matching types
    entity_types_filter = (
        [t.strip() for t in entity_type.split(",") if t.strip()]
        if entity_type
        else None
    )

    conditions = []
    if not entity_types_filter or "Project" in entity_types_filter:
        conditions.append(
            (AuditLog.entity_type == "Project")
            & (AuditLog.entity_id == project_id),
        )
    if not entity_types_filter or "Protocol" in entity_types_filter:
        if protocol_ids:
            conditions.append(
                (AuditLog.entity_type == "Protocol")
                & (AuditLog.entity_id.in_(protocol_ids))
            )
    if not entity_types_filter or "Run" in entity_types_filter:
        if run_ids:
            conditions.append(
                (AuditLog.entity_type == "Run")
                & (AuditLog.entity_id.in_(run_ids))
            )

    if not conditions:
        return AuditLogPage(items=[], total=0, offset=offset, limit=limit)

    base_filter = or_(*conditions)

    # Apply action filter
    if action:
        actions = [a.strip() for a in action.split(",") if a.strip()]
        if actions:
            base_filter = base_filter & AuditLog.action.in_(actions)

    # Apply text search (entity names + changes JSONB)
    if search and search.strip():
        search_term = f"%{search.strip().lower()}%"
        # Find entity IDs whose names match the search
        name_match_conditions = []
        if not entity_types_filter or "Protocol" in entity_types_filter:
            if protocol_ids:
                matching_protos = await db.execute(
                    select(Protocol.id).where(
                        Protocol.id.in_(protocol_ids),
                        func.lower(Protocol.name).like(search_term),
                    )
                )
                matched_proto_ids = list(matching_protos.scalars().all())
                if matched_proto_ids:
                    name_match_conditions.append(
                        (AuditLog.entity_type == "Protocol")
                        & AuditLog.entity_id.in_(matched_proto_ids)
                    )
        if not entity_types_filter or "Run" in entity_types_filter:
            if run_ids:
                matching_runs = await db.execute(
                    select(Run.id).where(
                        Run.id.in_(run_ids),
                        func.lower(Run.name).like(search_term),
                    )
                )
                matched_run_ids = list(matching_runs.scalars().all())
                if matched_run_ids:
                    name_match_conditions.append(
                        (AuditLog.entity_type == "Run")
                        & AuditLog.entity_id.in_(matched_run_ids)
                    )
        if not entity_types_filter or "Project" in entity_types_filter:
            proj_name_result = await db.execute(
                select(Project.name).where(
                    Project.id == project_id,
                    func.lower(Project.name).like(search_term),
                )
            )
            if proj_name_result.scalar_one_or_none():
                name_match_conditions.append(
                    (AuditLog.entity_type == "Project")
                    & (AuditLog.entity_id == project_id)
                )

        # Also match against changes JSONB text
        changes_match = func.lower(
            func.cast(AuditLog.changes, sqlalchemy.Text)
        ).like(search_term)
        name_match_conditions.append(changes_match)

        base_filter = base_filter & or_(*name_match_conditions)

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


# --- Permission Management ---

@router.get("/{project_id}/permissions", response_model=list[dict])
async def list_project_permissions(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all permission grants on a project. Requires ADMIN on project."""
    has_perm = await check_permission(
        db, current_user.id, ObjectType.PROJECT,
        project_id, PermissionLevel.ADMIN,
    )
    if not has_perm:
        raise HTTPException(403, "Admin access required")

    stmt = select(ObjectPermission).where(
        ObjectPermission.object_type == ObjectType.PROJECT.value,
        ObjectPermission.object_id == project_id,
    )
    result = await db.execute(stmt)
    perms = result.scalars().all()

    # Enrich with names
    items = []
    for p in perms:
        item = {
            "id": str(p.id),
            "principal_type": p.principal_type,
            "principal_id": str(p.principal_id),
            "permission_level": p.permission_level,
            "name": None,
            "email": None,
        }
        if p.principal_type == PrincipalType.USER.value:
            user = await db.get(User, p.principal_id)
            if user:
                item["name"] = user.full_name
                item["email"] = user.email
        elif p.principal_type == PrincipalType.TEAM.value:
            team = await db.get(Team, p.principal_id)
            if team:
                item["name"] = team.name
        items.append(item)

    return items


@router.put("/{project_id}/permissions/{permission_id}")
async def update_project_permission(
    project_id: UUID,
    permission_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update permission level on a grant. Requires ADMIN."""
    has_perm = await check_permission(
        db, current_user.id, ObjectType.PROJECT,
        project_id, PermissionLevel.ADMIN,
    )
    if not has_perm:
        raise HTTPException(403, "Admin access required")

    perm = await db.get(ObjectPermission, permission_id)
    if not perm or str(perm.object_id) != str(project_id):
        raise HTTPException(404, "Permission not found")

    level = body.get("permission_level")
    valid_levels = {e.value for e in PermissionLevel}
    if level not in valid_levels:
        raise HTTPException(
            400,
            f"Invalid permission_level. Must be one of: {valid_levels}",
        )

    perm.permission_level = level
    await db.commit()
    await db.refresh(perm)
    return {"id": str(perm.id), "permission_level": perm.permission_level}
