import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import (
    User,
    ObjectType,
    PermissionLevel,
    ObjectPermission,
    OrganizationMember,
    TeamMember,
)
from app.models.science import Project
from app.schemas.iam import UserSearchResponse
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Project Members ---

@router.get(
    "/projects/{project_id}/members",
    response_model=List[UserSearchResponse],
)
async def get_project_members(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all users who have access to a project.

    This includes:
    - Users with direct ObjectPermission rows on the project
    - Users who belong to teams with ObjectPermission on the project
    - Organization admins
    """
    # Check VIEW permission on project
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT,
        project_id, PermissionLevel.VIEW,
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Get the project to find its org
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    user_ids = set()

    # 1. Direct USER permissions on project
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "USER",
        ))
    )
    for perm in result.scalars().all():
        user_ids.add(perm.principal_id)

    # 2. TEAM permissions on project → expand to team members
    result = await db.execute(
        select(ObjectPermission)
        .where(and_(
            ObjectPermission.object_type == ObjectType.PROJECT,
            ObjectPermission.object_id == project_id,
            ObjectPermission.principal_type == "TEAM",
        ))
    )
    team_perms = result.scalars().all()
    if team_perms:
        team_ids = [p.principal_id for p in team_perms]
        result = await db.execute(
            select(TeamMember)
            .where(TeamMember.team_id.in_(team_ids))
        )
        for tm in result.scalars().all():
            user_ids.add(tm.user_id)

    # 3. Organization admins
    result = await db.execute(
        select(OrganizationMember)
        .where(and_(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.role == "ADMIN",
        ))
    )
    for om in result.scalars().all():
        user_ids.add(om.user_id)

    # Fetch all users
    if not user_ids:
        return []

    result = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users = result.scalars().all()
    return users
