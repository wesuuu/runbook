from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Site
from app.schemas.sites import SiteCreate, SiteUpdate
from app.services.core.audit import log_audit


async def list_sites(
    db: AsyncSession, org_id: UUID, *, include_archived: bool = False
) -> list[Site]:
    stmt = select(Site).where(Site.organization_id == org_id)
    if not include_archived:
        stmt = stmt.where(Site.archived_at.is_(None))
    stmt = stmt.order_by(Site.name)
    return list((await db.execute(stmt)).scalars().all())


async def get_site(db: AsyncSession, site_id: UUID) -> Site:
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _name_exists(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> bool:
    stmt = select(Site).where(
        Site.organization_id == org_id,
        Site.name == name,
        Site.archived_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Site.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def create_site(
    db: AsyncSession,
    *,
    org_id: UUID,
    payload: SiteCreate,
    actor_id: UUID,
) -> Site:
    if await _name_exists(db, org_id, payload.name):
        raise HTTPException(
            status_code=409,
            detail={"code": "SITE_NAME_CONFLICT", "name": payload.name},
        )
    site = Site(
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        created_by_id=actor_id,
    )
    db.add(site)
    await db.flush()
    await log_audit(
        db,
        actor_id=actor_id,
        action="CREATE",
        entity_type="site",
        entity_id=site.id,
        changes={"name": payload.name},
    )
    await db.commit()
    await db.refresh(site)
    return site


async def update_site(
    db: AsyncSession,
    site: Site,
    *,
    payload: SiteUpdate,
    actor_id: UUID,
) -> Site:
    diff: dict[str, list] = {}
    if payload.name is not None and payload.name != site.name:
        if await _name_exists(
            db, site.organization_id, payload.name, exclude_id=site.id
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "SITE_NAME_CONFLICT", "name": payload.name},
            )
        diff["name"] = [site.name, payload.name]
        site.name = payload.name
    if payload.description is not None and payload.description != site.description:
        diff["description"] = [site.description, payload.description]
        site.description = payload.description
    if diff:
        await log_audit(
            db,
            actor_id=actor_id,
            action="UPDATE",
            entity_type="site",
            entity_id=site.id,
            changes=diff,
        )
    await db.commit()
    await db.refresh(site)
    return site
