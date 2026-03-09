import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User
from app.models.science import UnitOpDefinition
from app.schemas.science import (
    UnitOpDefinitionCreate,
    UnitOpDefinitionUpdate,
    UnitOpDefinitionResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- UnitOps (auth only, no per-object perms) ---

@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UnitOpDefinition))
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
):
    new_op = UnitOpDefinition(
        name=unit_op.name,
        category=unit_op.category,
        description=unit_op.description,
        param_schema=unit_op.param_schema,
        result_schema=unit_op.result_schema,
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
):
    """Update a global unit op definition.

    Args:
        unit_op_id: The UUID of the unit op to update.
        update_data: Partial update fields.
        user: Authenticated user.
        db: Async DB session.

    Returns:
        Updated UnitOpDefinitionResponse.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = result.scalar_one_or_none()
    if not unit_op:
        raise HTTPException(status_code=404, detail="Unit op not found")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return unit_op
