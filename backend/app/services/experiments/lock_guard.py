"""Helpers for enforcing experiment-conclusion locks across endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Experiment


def locked_409(message: str) -> HTTPException:
    """Standard 409 for any write attempt on a locked experiment."""
    return HTTPException(
        status_code=409,
        detail={"code": "EXPERIMENT_LOCKED", "message": message},
    )


async def assert_experiment_unlocked(
    db: AsyncSession,
    experiment_id: Optional[UUID],
    message: str,
) -> None:
    """Raise 409 if the experiment is locked. No-op when id is None."""
    if experiment_id is None:
        return
    locked_at = await db.scalar(
        select(Experiment.conclusion_locked_at).where(
            Experiment.id == experiment_id
        )
    )
    if locked_at is not None:
        raise locked_409(message)
