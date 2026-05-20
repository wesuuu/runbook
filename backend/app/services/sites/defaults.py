from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sites import Site
from app.services.core.audit import log_audit

DEFAULT_SITE_NAME = "Default Site"


async def ensure_default_site(
    db: AsyncSession, org_id: UUID, *, actor_id: UUID | None
) -> Site:
    """Return the org's default site, creating it if missing.

    Identity is the `is_default` column — NOT the name. The migration
    eager-creates one row per org with is_default=true; this helper is
    the runtime equivalent for new orgs created post-migration.
    """
    stmt = select(Site).where(
        Site.organization_id == org_id,
        Site.is_default.is_(True),
        Site.archived_at.is_(None),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    site = Site(
        organization_id=org_id,
        name=DEFAULT_SITE_NAME,
        description="Auto-created default site for this organization.",
        is_default=True,
        created_by_id=actor_id,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


def is_default_site(site: Site) -> bool:
    """Default identity is the column, not the name. A SITE_MANAGER may
    rename the row to "HQ"; it is still the default until the column flips.
    """
    return bool(site.is_default)


async def set_default_site(db: AsyncSession, *, site: Site, actor_id: UUID) -> Site:
    """Promote `site` to be the org's default. Atomically unsets the
    previous default. No-op if `site` is already default."""
    if site.archived_at is not None:
        raise HTTPException(400, detail={"code": "SITE_ARCHIVED"})
    if site.is_default:
        return site

    prev_stmt = select(Site).where(
        Site.organization_id == site.organization_id,
        Site.is_default.is_(True),
    )
    previous = (await db.execute(prev_stmt)).scalar_one_or_none()

    # Two-step swap to respect the partial unique index
    # (uq_sites_org_is_default) which allows only one row per org with
    # is_default=true. Clear the old default first, then set the new one.
    if previous is not None and previous.id != site.id:
        await db.execute(
            update(Site).where(Site.id == previous.id).values(is_default=False)
        )
    await db.execute(update(Site).where(Site.id == site.id).values(is_default=True))

    await log_audit(
        db,
        actor_id=actor_id,
        action="SET_DEFAULT",
        entity_type="site",
        entity_id=site.id,
        changes={
            "previous_default_id": (str(previous.id) if previous is not None else None),
            "new_default_id": str(site.id),
        },
    )
    await db.commit()
    await db.refresh(site)
    return site
