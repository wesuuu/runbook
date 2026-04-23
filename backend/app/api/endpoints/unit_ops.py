import logging
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
    org_id = user.selected_org_id

    # Always include global ops
    conditions = [
        and_(
            UnitOpDefinition.organization_id.is_(None),
            UnitOpDefinition.project_id.is_(None),
        ),
    ]

    # Include org-scoped ops for user's selected org
    if org_id is not None:
        conditions.append(
            and_(
                UnitOpDefinition.organization_id == org_id,
                UnitOpDefinition.project_id.is_(None),
            )
        )

    # Include project-scoped ops if project_id provided
    if project_id is not None:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, project_id, PermissionLevel.VIEW,
        )
        if allowed:
            conditions.append(UnitOpDefinition.project_id == project_id)

    stmt = select(UnitOpDefinition).where(or_(*conditions))
    result = await db.execute(stmt)
    return result.scalars().all()


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
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = result.scalar_one_or_none()
    if not unit_op:
        raise HTTPException(status_code=404, detail="Unit op not found")

    # Permission check based on scope
    if unit_op.organization_id is None and unit_op.project_id is None:
        # Global — read-only via API
        raise HTTPException(
            status_code=403,
            detail="Global unit operations are read-only",
        )
    elif unit_op.project_id is not None:
        # Project-scoped — require EDIT on the project
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, unit_op.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(
                status_code=403, detail="Insufficient permissions",
            )
    else:
        # Org-scoped — require org admin
        await _require_org_admin(db, user.id, unit_op.organization_id)

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return unit_op
