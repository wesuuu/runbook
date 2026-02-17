from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.iam import (
    User,
    OrganizationMember,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.audit import log_audit
from app.services.permissions import get_visible_project_ids

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
