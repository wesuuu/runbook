"""Unified sign-off review queue endpoint (F-0080)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User
from app.schemas.signoff_requests import SignoffRequestItem
from app.services.signoffs.queue import list_review_queue_for_user

router = APIRouter()


@router.get("/signoff-requests", response_model=list[SignoffRequestItem])
async def list_signoff_requests(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SignoffRequestItem]:
    """Pending sign-off review items for the current user (run + protocol).

    Always scoped to the caller — there is no caller-supplied assignee param.
    """
    items = await list_review_queue_for_user(db, user.id)
    return [SignoffRequestItem(**item) for item in items]
