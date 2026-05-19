from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment, Site
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate
from app.services.core.audit import log_audit
from app.services.equipment.tags import normalize_tags

RESTRICTED_EQUIPMENT_FIELDS = frozenset(
    {
        "manufacturer",
        "model",
        "serial_number",
        "status",
        "install_date",
        "last_calibration_date",
        "next_calibration_due",
    }
)


async def _validate_site(db: AsyncSession, org_id: UUID, site_id: UUID) -> Site:
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_REQUIRED"})
    if site.organization_id != org_id:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_CROSS_ORG"})
    if site.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_ARCHIVED"})
    return site


async def list_equipment(
    db: AsyncSession,
    org_id: UUID,
    *,
    site_id: UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    include_archived: bool = False,
) -> list[Equipment]:
    stmt = select(Equipment).where(Equipment.organization_id == org_id)
    if not include_archived:
        stmt = stmt.where(Equipment.archived_at.is_(None))
    if site_id is not None:
        stmt = stmt.where(Equipment.site_id == site_id)
    if status is not None:
        stmt = stmt.where(Equipment.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                Equipment.name.ilike(like),
                Equipment.serial_number.ilike(like),
                Equipment.equipment_type.ilike(like),
            )
        )
    if tag:
        stmt = stmt.where(Equipment.tags.any(tag))
    stmt = stmt.order_by(Equipment.name)
    return list((await db.execute(stmt)).scalars().all())


async def get_equipment(db: AsyncSession, equipment_id: UUID) -> Equipment:
    eq = await db.get(Equipment, equipment_id)
    if eq is None:
        raise HTTPException(404, detail="Equipment not found")
    return eq


async def create_equipment(
    db: AsyncSession,
    *,
    org_id: UUID,
    payload: EquipmentCreate,
    actor_id: UUID,
    can_set_restricted: bool,
) -> Equipment:
    await _validate_site(db, org_id, payload.site_id)
    data = payload.model_dump()
    data["tags"] = normalize_tags(data.get("tags") or [])
    data["status"] = (
        data["status"].value
        if hasattr(data.get("status"), "value")
        else data.get("status")
    )

    if not can_set_restricted:
        dropped: dict[str, str] = {}
        for field in RESTRICTED_EQUIPMENT_FIELDS:
            if field == "status":
                if data.get("status") and data["status"] != "ACTIVE":
                    dropped["status"] = data["status"]
                    data["status"] = "ACTIVE"
                continue
            if data.get(field) is not None:
                dropped[field] = str(data[field])
                data[field] = None
    else:
        dropped = {}

    eq = Equipment(organization_id=org_id, created_by_id=actor_id, **data)
    db.add(eq)
    await db.flush()
    changes: dict = {"name": eq.name, "site_id": str(eq.site_id)}
    if dropped:
        changes["_dropped_restricted_fields"] = dropped
    await log_audit(
        db,
        actor_id=actor_id,
        action="CREATE",
        entity_type="equipment",
        entity_id=eq.id,
        changes=changes,
    )
    await db.commit()
    await db.refresh(eq)
    return eq


async def update_equipment(
    db: AsyncSession,
    eq: Equipment,
    *,
    payload: EquipmentUpdate,
    actor_id: UUID,
) -> Equipment:
    touched = payload.model_dump(exclude_unset=True)
    diff: dict[str, list] = {}

    if "site_id" in touched and touched["site_id"] != eq.site_id:
        await _validate_site(db, eq.organization_id, touched["site_id"])

    if "tags" in touched and touched["tags"] is not None:
        touched["tags"] = normalize_tags(touched["tags"])

    if "status" in touched and hasattr(touched["status"], "value"):
        touched["status"] = touched["status"].value

    for field, new_val in touched.items():
        old_val = getattr(eq, field)
        if old_val != new_val:
            diff[field] = [
                str(old_val) if old_val is not None else None,
                str(new_val) if new_val is not None else None,
            ]
            setattr(eq, field, new_val)

    if diff:
        await log_audit(
            db,
            actor_id=actor_id,
            action="UPDATE",
            entity_type="equipment",
            entity_id=eq.id,
            changes=diff,
        )
    await db.commit()
    await db.refresh(eq)
    return eq


async def archive_equipment(
    db: AsyncSession, eq: Equipment, *, actor_id: UUID
) -> Equipment:
    eq.archived_at = datetime.now(timezone.utc)
    eq.archived_by_id = actor_id
    await log_audit(
        db,
        actor_id=actor_id,
        action="ARCHIVE",
        entity_type="equipment",
        entity_id=eq.id,
        changes={},
    )
    await db.commit()
    await db.refresh(eq)
    return eq
