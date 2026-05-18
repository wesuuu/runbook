from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import OrganizationMember
from app.models.science import SiteManagerGrant


async def _is_admin(db: AsyncSession, *, user_id: UUID, org_id: UUID) -> bool:
    stmt = select(OrganizationMember.roles).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
        OrganizationMember.archived == False,  # noqa: E712
    )
    roles = (await db.execute(stmt)).scalar_one_or_none()
    return roles is not None and "ADMIN" in (roles or [])


async def _has_site_manager_role(
    db: AsyncSession, *, user_id: UUID, org_id: UUID
) -> bool:
    stmt = select(OrganizationMember.roles).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
        OrganizationMember.archived == False,  # noqa: E712
    )
    roles = (await db.execute(stmt)).scalar_one_or_none()
    return roles is not None and "SITE_MANAGER" in (roles or [])


async def _has_grant(db: AsyncSession, *, user_id: UUID, site_id: UUID) -> bool:
    stmt = select(SiteManagerGrant.id).where(
        SiteManagerGrant.user_id == user_id,
        SiteManagerGrant.site_id == site_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def user_can_edit_restricted_equipment(
    db: AsyncSession, *, user_id: UUID, org_id: UUID, site_id: UUID
) -> bool:
    """ADMIN always; otherwise needs SITE_MANAGER role AND a grant on
    the equipment's site."""
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False
    return await _has_grant(db, user_id=user_id, site_id=site_id)


async def user_can_move_equipment(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_id: UUID,
    from_site_id: UUID,
    to_site_id: UUID,
) -> tuple[bool, list[UUID]]:
    """Return (ok, missing_grants). Needs grants on BOTH source and dest."""
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True, []
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False, [from_site_id, to_site_id]
    missing: list[UUID] = []
    if not await _has_grant(db, user_id=user_id, site_id=from_site_id):
        missing.append(from_site_id)
    if not await _has_grant(db, user_id=user_id, site_id=to_site_id):
        missing.append(to_site_id)
    return (not missing), missing


async def user_can_rename_site(
    db: AsyncSession, *, user_id: UUID, org_id: UUID, site_id: UUID
) -> bool:
    """SITE_MANAGER with grant can rename. CREATE/ARCHIVE remain ADMIN-only."""
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False
    return await _has_grant(db, user_id=user_id, site_id=site_id)
