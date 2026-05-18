from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.science import Site, SiteManagerGrant
from app.services.core.audit import log_audit


async def list_grants_for_site(
    db: AsyncSession, site_id: UUID
) -> list[SiteManagerGrant]:
    stmt = (
        select(SiteManagerGrant)
        .where(SiteManagerGrant.site_id == site_id)
        .options(selectinload(SiteManagerGrant.user))
        .order_by(SiteManagerGrant.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_managed_sites_for_user(
    db: AsyncSession, user_id: UUID, *, include_archived: bool = False
) -> list[SiteManagerGrant]:
    """All grants held by user_id, eager-loading the Site for display."""
    stmt = (
        select(SiteManagerGrant)
        .join(Site, Site.id == SiteManagerGrant.site_id)
        .where(SiteManagerGrant.user_id == user_id)
        .options(selectinload(SiteManagerGrant.site))
    )
    if not include_archived:
        stmt = stmt.where(Site.archived_at.is_(None))
    stmt = stmt.order_by(Site.name)
    return list((await db.execute(stmt)).scalars().all())


async def user_has_grant(db: AsyncSession, site_id: UUID, user_id: UUID) -> bool:
    stmt = select(SiteManagerGrant.id).where(
        SiteManagerGrant.site_id == site_id,
        SiteManagerGrant.user_id == user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def grant_site_manager(
    db: AsyncSession, *, site: Site, user_id: UUID, granted_by_id: UUID
) -> SiteManagerGrant:
    if site.archived_at is not None:
        raise HTTPException(400, detail={"code": "SITE_ARCHIVED"})

    existing = await db.execute(
        select(SiteManagerGrant).where(
            SiteManagerGrant.site_id == site.id,
            SiteManagerGrant.user_id == user_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    grant = SiteManagerGrant(
        organization_id=site.organization_id,
        site_id=site.id,
        user_id=user_id,
        granted_by_id=granted_by_id,
    )
    db.add(grant)
    await db.flush()
    await log_audit(
        db,
        actor_id=granted_by_id,
        action="CREATE",
        entity_type="site_manager_grant",
        entity_id=grant.id,
        changes={"site_id": str(site.id), "user_id": str(user_id)},
    )
    await log_audit(
        db,
        actor_id=granted_by_id,
        action="GRANT_ADDED",
        entity_type="site",
        entity_id=site.id,
        changes={"user_id": str(user_id), "grant_id": str(grant.id)},
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def revoke_site_manager(
    db: AsyncSession, *, site_id: UUID, user_id: UUID, actor_id: UUID
) -> None:
    grant = (
        await db.execute(
            select(SiteManagerGrant).where(
                SiteManagerGrant.site_id == site_id,
                SiteManagerGrant.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise HTTPException(404, detail={"code": "SITE_GRANT_NOT_FOUND"})

    grant_id = grant.id
    await db.delete(grant)
    await log_audit(
        db,
        actor_id=actor_id,
        action="DELETE",
        entity_type="site_manager_grant",
        entity_id=grant_id,
        changes={"site_id": str(site_id), "user_id": str(user_id)},
    )
    await log_audit(
        db,
        actor_id=actor_id,
        action="GRANT_REMOVED",
        entity_type="site",
        entity_id=site_id,
        changes={"user_id": str(user_id), "grant_id": str(grant_id)},
    )
    await db.commit()
