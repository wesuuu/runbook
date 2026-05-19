"""Equipment registry endpoints.

Permission matrix:
  GET  /equipment                       any MEMBER
  GET  /equipment/tags                  any MEMBER
  GET  /equipment/{id}                  any MEMBER
  POST /equipment                       any MEMBER; restricted fields silently
                                        dropped unless SITE_MANAGER+grant or ADMIN
  PATCH /equipment/{id}                 any MEMBER for unrestricted fields;
                                        SITE_MANAGER+grant or ADMIN for restricted;
                                        site_id change requires grants on BOTH sites
  DELETE /equipment/{id}                SITE_MANAGER (additive) OR ADMIN
  GET  /equipment/{id}/attachments      any MEMBER
  POST /equipment/{id}/attachments      SITE_MANAGER (additive) OR ADMIN
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_any_org_role
from app.models.iam import OrgRole, User
from app.models.science import EquipmentAttachment
from app.schemas.equipment import (EquipmentAttachmentResponse,
                                   EquipmentCreate, EquipmentResponse,
                                   EquipmentUpdate)
from app.services.equipment import attachments as att_svc
from app.services.equipment import registry as eq_svc
from app.services.equipment.registry import RESTRICTED_EQUIPMENT_FIELDS
from app.services.equipment.tags import list_distinct_tags
from app.services.permissions.equipment import (
    user_can_edit_restricted_equipment, user_can_move_equipment)

router = APIRouter(prefix="/equipment", tags=["equipment"])

# Additive role dependency: SITE_MANAGER OR ADMIN (Decision 5c-ii).
_require_site_manager_or_admin = require_any_org_role(
    [OrgRole.SITE_MANAGER, OrgRole.ADMIN]
)


# ── tag listing (must be registered before /{equipment_id} to avoid shadowing) ──


@router.get("/tags", response_model=list[str])
async def list_tags_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all distinct tags in use by non-archived equipment in the org."""
    return await list_distinct_tags(db, user.selected_org_id)


# ── attachment delete (registered before /{equipment_id} to avoid shadowing) ──


@router.delete("/attachments/{attachment_id}")
async def delete_attachment_endpoint(
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_site_manager_or_admin),
):
    att = await db.get(EquipmentAttachment, attachment_id)
    if att is None:
        raise HTTPException(404)
    eq = await eq_svc.get_equipment(db, att.equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    await att_svc.remove_attachment(db, att, actor_id=user.id)
    return {"deleted": True}


# ── list / detail ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[EquipmentResponse])
async def list_equipment_endpoint(
    site_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await eq_svc.list_equipment(
        db,
        user.selected_org_id,
        site_id=site_id,
        status=status,
        q=q,
        tag=tag,
        include_archived=include_archived,
    )


@router.get("/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await eq_svc.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return eq


# ── create ─────────────────────────────────────────────────────────────────────


@router.post("", response_model=EquipmentResponse, status_code=201)
async def create_equipment_endpoint(
    payload: EquipmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    can_set_restricted = await user_can_edit_restricted_equipment(
        db,
        user_id=user.id,
        org_id=user.selected_org_id,
        site_id=payload.site_id,
    )
    return await eq_svc.create_equipment(
        db,
        org_id=user.selected_org_id,
        payload=payload,
        actor_id=user.id,
        can_set_restricted=can_set_restricted,
    )


# ── patch ──────────────────────────────────────────────────────────────────────


@router.patch("/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment_endpoint(
    equipment_id: UUID,
    payload: EquipmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await eq_svc.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)

    if eq.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_ARCHIVED"})

    touched = payload.model_dump(exclude_unset=True)

    # ── site_id move guard ───────────────────────────────────────────────────
    new_site_id = touched.get("site_id")
    if new_site_id is not None and new_site_id != eq.site_id:
        ok, missing = await user_can_move_equipment(
            db,
            user_id=user.id,
            org_id=user.selected_org_id,
            from_site_id=eq.site_id,
            to_site_id=new_site_id,
        )
        if not ok:
            raise HTTPException(
                403,
                detail={
                    "code": "SITE_MOVE_FORBIDDEN",
                    "missing_grants": [str(sid) for sid in missing],
                },
            )

    # ── restricted field gate ────────────────────────────────────────────────
    # Value-compare: round-tripping a restricted field with its unchanged
    # value is a no-op and must NOT 403.
    restricted_changing: list[str] = []
    for field in RESTRICTED_EQUIPMENT_FIELDS:
        if field not in touched:
            continue
        new_val = touched[field]
        old_val = getattr(eq, field)
        # Normalize enum → string for comparison
        if hasattr(new_val, "value"):
            new_val = new_val.value
        if hasattr(old_val, "value"):
            old_val = old_val.value
        if new_val != old_val:
            restricted_changing.append(field)

    if restricted_changing:
        can_edit = await user_can_edit_restricted_equipment(
            db,
            user_id=user.id,
            org_id=user.selected_org_id,
            site_id=eq.site_id,
        )
        if not can_edit:
            raise HTTPException(
                403,
                detail={
                    "code": "EQUIPMENT_FIELD_RESTRICTED",
                    "fields": restricted_changing,
                },
            )

    return await eq_svc.update_equipment(db, eq, payload=payload, actor_id=user.id)


# ── delete (archive) ───────────────────────────────────────────────────────────


@router.delete("/{equipment_id}", response_model=EquipmentResponse)
async def archive_equipment_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_site_manager_or_admin),
):
    eq = await eq_svc.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await eq_svc.archive_equipment(db, eq, actor_id=user.id)


# ── attachments ────────────────────────────────────────────────────────────────


@router.get(
    "/{equipment_id}/attachments",
    response_model=list[EquipmentAttachmentResponse],
)
async def list_attachments_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await eq_svc.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    result = await db.execute(
        select(EquipmentAttachment)
        .where(EquipmentAttachment.equipment_id == equipment_id)
        .order_by(EquipmentAttachment.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{equipment_id}/attachments",
    response_model=EquipmentAttachmentResponse,
    status_code=201,
)
async def upload_attachment_endpoint(
    equipment_id: UUID,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_require_site_manager_or_admin),
):
    eq = await eq_svc.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await att_svc.add_attachment(db, eq, file, actor_id=user.id)
