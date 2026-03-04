from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    ObjectPermission,
    OrganizationMember,
    TeamMember,
    PrincipalType,
    ObjectType,
    PermissionLevel,
    PERMISSION_RANK,
)
from app.core.config import settings
from app.models.science import Project, Protocol, Run


def _meets_level(
    actual: str, required: PermissionLevel
) -> bool:
    return PERMISSION_RANK.get(
        PermissionLevel(actual), 0
    ) >= PERMISSION_RANK[required]


async def _get_org_id_for_object(
    db: AsyncSession,
    object_type: ObjectType,
    object_id: UUID,
) -> UUID | None:
    """Resolve the organization_id for any object."""
    if object_type == ObjectType.PROJECT:
        result = await db.execute(
            select(Project.organization_id).where(
                Project.id == object_id
            )
        )
        return result.scalar_one_or_none()

    if object_type == ObjectType.PROTOCOL:
        result = await db.execute(
            select(Project.organization_id)
            .join(Protocol, Protocol.project_id == Project.id)
            .where(Protocol.id == object_id)
        )
        return result.scalar_one_or_none()

    if object_type == ObjectType.RUN:
        result = await db.execute(
            select(Project.organization_id)
            .join(Run, Run.project_id == Project.id)
            .where(Run.id == object_id)
        )
        return result.scalar_one_or_none()

    return None


async def _get_parent_project_id(
    db: AsyncSession,
    object_type: ObjectType,
    object_id: UUID,
) -> UUID | None:
    """Get the parent project_id for a protocol or run."""
    if object_type == ObjectType.PROTOCOL:
        result = await db.execute(
            select(Protocol.project_id).where(
                Protocol.id == object_id
            )
        )
        return result.scalar_one_or_none()

    if object_type == ObjectType.RUN:
        result = await db.execute(
            select(Run.project_id).where(
                Run.id == object_id
            )
        )
        return result.scalar_one_or_none()

    return None


async def _get_user_team_ids(
    db: AsyncSession, user_id: UUID
) -> list[UUID]:
    result = await db.execute(
        select(TeamMember.team_id).where(
            TeamMember.user_id == user_id
        )
    )
    return list(result.scalars().all())


async def check_permission(
    db: AsyncSession,
    user_id: UUID,
    object_type: ObjectType,
    object_id: UUID,
    required_level: PermissionLevel,
) -> bool:
    """Check if user has at least required_level on the object.

    Resolution order:
    1. Auth disabled → always allow
    2. Org admin → full access to everything in that org
    3. Individual permission on object → use it (overrides team)
    4. Team permissions on object → use highest across user's teams
    5. Protocol/Run → inherit from parent Project
    6. No match → deny
    """
    if not settings.auth_enabled:
        return True

    # 1. Check org admin
    org_id = await _get_org_id_for_object(db, object_type, object_id)
    if org_id is None:
        return False

    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return False  # Not even in the org
    if membership.is_admin:
        return True

    # 2. Individual permission on this object
    result = await db.execute(
        select(ObjectPermission).where(
            ObjectPermission.principal_type == PrincipalType.USER,
            ObjectPermission.principal_id == user_id,
            ObjectPermission.object_type == object_type.value,
            ObjectPermission.object_id == object_id,
        )
    )
    individual = result.scalar_one_or_none()
    if individual is not None:
        return _meets_level(individual.permission_level, required_level)

    # 3. Team permissions on this object
    team_ids = await _get_user_team_ids(db, user_id)
    if team_ids:
        result = await db.execute(
            select(ObjectPermission).where(
                ObjectPermission.principal_type == PrincipalType.TEAM,
                ObjectPermission.principal_id.in_(team_ids),
                ObjectPermission.object_type == object_type.value,
                ObjectPermission.object_id == object_id,
            )
        )
        team_perms = result.scalars().all()
        if team_perms:
            highest = max(
                PERMISSION_RANK.get(PermissionLevel(p.permission_level), 0)
                for p in team_perms
            )
            return highest >= PERMISSION_RANK[required_level]

    # 4. Inherit from parent project for protocols/runs
    if object_type in (ObjectType.PROTOCOL, ObjectType.RUN):
        project_id = await _get_parent_project_id(
            db, object_type, object_id
        )
        if project_id:
            return await check_permission(
                db, user_id, ObjectType.PROJECT,
                project_id, required_level,
            )

    # 5. Deny
    return False


async def get_visible_project_ids(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> list[UUID]:
    """Get project IDs the user can see in an org.

    Org admins see all. Others see projects they have direct
    or team-level permissions on.
    """
    # Check org admin
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        return []
    if membership.is_admin:
        result = await db.execute(
            select(Project.id).where(
                Project.organization_id == org_id
            )
        )
        return list(result.scalars().all())

    # Collect from individual perms
    result = await db.execute(
        select(ObjectPermission.object_id).where(
            ObjectPermission.principal_type == PrincipalType.USER,
            ObjectPermission.principal_id == user_id,
            ObjectPermission.object_type == ObjectType.PROJECT.value,
        )
    )
    project_ids = set(result.scalars().all())

    # Collect from team perms
    team_ids = await _get_user_team_ids(db, user_id)
    if team_ids:
        result = await db.execute(
            select(ObjectPermission.object_id).where(
                ObjectPermission.principal_type == PrincipalType.TEAM,
                ObjectPermission.principal_id.in_(team_ids),
                ObjectPermission.object_type == ObjectType.PROJECT.value,
            )
        )
        project_ids.update(result.scalars().all())

    # Filter to only projects in this org
    if not project_ids:
        return []
    result = await db.execute(
        select(Project.id).where(
            Project.id.in_(project_ids),
            Project.organization_id == org_id,
        )
    )
    return list(result.scalars().all())
