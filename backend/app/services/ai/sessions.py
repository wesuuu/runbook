"""ChatSession CRUD — pure DB operations, no LLM."""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatSession, ChatSessionStatus


async def create_session(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    title: Optional[str] = None,
    context_document_ids: Optional[list[UUID]] = None,
) -> ChatSession:
    session = ChatSession(
        user_id=user_id,
        org_id=org_id,
        title=title or "New Chat",
        context_document_ids=(
            [str(did) for did in context_document_ids] if context_document_ids else None
        ),
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: UUID) -> Optional[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(selectinload(ChatSession.messages))
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    user_id: UUID,
    org_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatSession], int]:
    base_query = select(ChatSession).where(
        ChatSession.user_id == user_id,
        ChatSession.org_id == org_id,
        ChatSession.status == ChatSessionStatus.ACTIVE,
    )

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(
        base_query.order_by(ChatSession.updated_at.desc()).offset(offset).limit(limit)
    )
    sessions = list(result.scalars().all())
    return sessions, total


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    await db.delete(session)
    await db.flush()
