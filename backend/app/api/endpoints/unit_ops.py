import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import (ObjectType, OrganizationMember, OrgRole,
                            PermissionLevel, User)
from app.models.science import Project, UnitOpDefinition
from app.schemas.science import (UnitOpDefinitionCreate,
                                 UnitOpDefinitionResponse,
                                 UnitOpDefinitionUpdate)
from app.services.core.permissions import check_permission

# Synthetic timestamp for JSON-only ops. They have no real created_at;
# pin to epoch so the response shape is consistent.
_LIB_TIMESTAMP = datetime(1970, 1, 1, tzinfo=timezone.utc)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_org_admin(
    db: AsyncSession, user_id: UUID, org_id: UUID,
) -> None:
    """Raise 403 if user is not ADMIN in the given org."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgRole.ADMIN,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail="Org admin role required for org-scoped unit ops",
        )


@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(
    project_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.science import UnitOpLibrarySubscription
    from app.services.science import library_registry

    org_id = user.selected_org_id
    if org_id is None:
        return []

    # 1. JSON ops from subscribed libraries
    sub_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    subscribed_slugs = {row[0] for row in sub_q.all()}

    by_id: dict[UUID, dict] = {}
    for slug in subscribed_slugs:
        lib = library_registry.get_library(slug)
        if lib is None:
            continue
        for op in lib.unit_ops:
            synth_id = library_registry.synthetic_uuid(slug, op.slug)
            by_id[synth_id] = {
                "id": synth_id,
                "name": op.name,
                "category": op.category,
                "description": op.description,
                "param_schema": op.param_schema,
                "result_schema": op.result_schema,
                "organization_id": None,
                "project_id": None,
                "library_slug": slug,
                "created_at": _LIB_TIMESTAMP,
                "updated_at": _LIB_TIMESTAMP,
            }

    # 2. DB rows for this org (overrides + custom org ops)
    db_q = await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.organization_id == org_id,
            UnitOpDefinition.project_id.is_(None),
        )
    )
    for row in db_q.scalars():
        by_id[row.id] = _row_to_response_dict(row)

    # 3. Project-scoped ops if requested
    if project_id is not None:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, project_id, PermissionLevel.VIEW,
        )
        if allowed:
            proj_q = await db.execute(
                select(UnitOpDefinition).where(
                    UnitOpDefinition.project_id == project_id,
                )
            )
            for row in proj_q.scalars():
                by_id[row.id] = _row_to_response_dict(row)

    return list(by_id.values())


def _row_to_response_dict(row: UnitOpDefinition) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "param_schema": row.param_schema,
        "result_schema": row.result_schema,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "library_slug": row.source_library_slug,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post(
    "/unit-ops",
    response_model=UnitOpDefinitionResponse,
    status_code=201,
)
async def create_unit_op(
    unit_op: UnitOpDefinitionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(
            status_code=400, detail="No organization selected",
        )

    if unit_op.project_id is not None:
        # Project-scoped: validate project belongs to user's org
        result = await db.execute(
            select(Project).where(
                Project.id == unit_op.project_id,
                Project.organization_id == org_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found in your organization",
            )

        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, unit_op.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail="Project edit permission required",
            )
    else:
        # Org-scoped: require org admin
        await _require_org_admin(db, user.id, org_id)

    new_op = UnitOpDefinition(
        name=unit_op.name,
        category=unit_op.category,
        description=unit_op.description,
        param_schema=unit_op.param_schema,
        result_schema=unit_op.result_schema,
        organization_id=org_id,
        project_id=unit_op.project_id,
    )
    db.add(new_op)
    await db.commit()
    await db.refresh(new_op)
    return new_op


@router.put(
    "/unit-ops/{unit_op_id}",
    response_model=UnitOpDefinitionResponse,
)
async def update_unit_op(
    unit_op_id: UUID,
    update_data: UnitOpDefinitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(400, "No organization selected")

    # 1. Try the DB
    row = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = row.scalar_one_or_none()

    if unit_op is None:
        # 2. Maybe it's a JSON op — find the (library, op) producing this UUID
        op_match = await _find_subscribed_json_op(db, org_id, unit_op_id)
        if op_match is None:
            raise HTTPException(404, "Unit op not found")
        # Copy-on-write: org admin only.
        await _require_org_admin(db, user.id, org_id)
        lib_slug, op = op_match
        unit_op = UnitOpDefinition(
            id=unit_op_id,
            name=op.name,
            category=op.category,
            description=op.description,
            param_schema=op.param_schema,
            result_schema=op.result_schema,
            organization_id=org_id,
            project_id=None,
            source_library_slug=lib_slug,
            source_op_slug=op.slug,
        )
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(unit_op, key, value)
        db.add(unit_op)
        await db.commit()
        await db.refresh(unit_op)
        return _row_to_response_dict(unit_op)

    # 3. Existing DB row — permission depends on scope
    if unit_op.project_id is not None:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, unit_op.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(403, "Insufficient permissions")
    elif unit_op.organization_id is not None:
        await _require_org_admin(db, user.id, unit_op.organization_id)
    else:
        # No NULL/NULL rows should exist post-migration; defensive 403
        raise HTTPException(403, "Read-only unit op")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return _row_to_response_dict(unit_op)


async def _find_subscribed_json_op(
    db: AsyncSession, org_id: UUID, target_id: UUID,
):
    """Walk every subscribed library; return (slug, op) if its synthetic
    UUID equals target_id, else None."""
    from app.models.science import UnitOpLibrarySubscription
    from app.services.science import library_registry

    sub_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    for (slug,) in sub_q.all():
        lib = library_registry.get_library(slug)
        if lib is None:
            continue
        for op in lib.unit_ops:
            if library_registry.synthetic_uuid(slug, op.slug) == target_id:
                return (slug, op)
    return None
