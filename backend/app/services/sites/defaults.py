from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Site

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
