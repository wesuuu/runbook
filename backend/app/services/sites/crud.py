from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment, Site
from app.schemas.sites import SiteCreate, SiteUpdate
from app.services.core.audit import log_audit
from app.services.sites.defaults import is_default_site


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


async def archive_site(
    db: AsyncSession,
    site: Site,
    *,
    default_move_to: UUID,
    overrides: dict[UUID, UUID] | None,
    reason: str,
    actor_id: UUID,
) -> Site:
    overrides = overrides or {}

    if is_default_site(site):
        raise HTTPException(
            status_code=400,
            detail={"code": "SITE_ARCHIVE_DEFAULT_FORBIDDEN", "site_id": str(site.id)},
        )

    if default_move_to == site.id or any(v == site.id for v in overrides.values()):
        raise HTTPException(
            status_code=400,
            detail={"code": "SITE_ARCHIVE_SELF_DESTINATION"},
        )

    destinations = {default_move_to, *overrides.values()}
    dest_rows = (
        (await db.execute(select(Site).where(Site.id.in_(destinations))))
        .scalars()
        .all()
    )
    found = {d.id: d for d in dest_rows}
    for dest_id in destinations:
        dest = found.get(dest_id)
        if (
            dest is None
            or dest.organization_id != site.organization_id
            or dest.archived_at is not None
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SITE_ARCHIVE_BAD_DESTINATION",
                    "site_id": str(dest_id),
                },
            )

    if overrides:
        eq_rows = (
            (
                await db.execute(
                    select(Equipment).where(Equipment.id.in_(list(overrides.keys())))
                )
            )
            .scalars()
            .all()
        )
        eq_by_id = {e.id: e for e in eq_rows}
        for eq_id in overrides.keys():
            e = eq_by_id.get(eq_id)
            if e is None or e.site_id != site.id:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "SITE_ARCHIVE_OVERRIDE_NOT_FOUND",
                        "equipment_id": str(eq_id),
                    },
                )

    all_eq = (
        (
            await db.execute(
                select(Equipment).where(
                    Equipment.site_id == site.id, Equipment.archived_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )

    counts_per_dest: dict[UUID, int] = {}
    for e in all_eq:
        target = overrides.get(e.id, default_move_to)
        old = e.site_id
        e.site_id = target
        counts_per_dest[target] = counts_per_dest.get(target, 0) + 1
        await log_audit(
            db,
            actor_id=actor_id,
            action="UPDATE",
            entity_type="equipment",
            entity_id=e.id,
            changes={
                "site_id": [str(old), str(target)],
                "reason": reason,
            },
        )

    site.archived_at = datetime.now(timezone.utc)
    site.archived_by_id = actor_id
    site.archive_reason = reason

    await log_audit(
        db,
        actor_id=actor_id,
        action="ARCHIVE",
        entity_type="site",
        entity_id=site.id,
        changes={
            "reason": reason,
            "moves": {str(k): v for k, v in counts_per_dest.items()},
        },
    )

    await db.commit()
    await db.refresh(site)
    return site
