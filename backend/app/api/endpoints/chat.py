import logging
import secrets
import traceback
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import (get_current_user, get_or_404,
                           get_org_id_from_request,
                           require_active_subscription)
from app.db.session import get_db
from app.models.chat import (ChatMessage, ChatMessageRole, ChatNotification,
                             ChatSession)
from app.models.iam import (TIER_RANK, Organization, OrganizationMember,
                            OrgRole, SubscriptionTier, User)
from app.schemas.chat import (ChatCompletionResponse, ChatConfigResponse,
                              ChatMessageCreate, ChatSessionCreate,
                              ChatSessionDetailResponse,
                              ChatSessionListResponse, ChatSessionResponse,
                              ChatSessionUpdate, ChatSkillListResponse,
                              ChatSkillResponse, ChatSourceReference,
                              NotifyAdminResponse)
from app.services.ai import (create_session, delete_session, get_session,
                             list_sessions, send_message)
from app.services.ai.ai_config import (get_context_window,
                                       get_model_display_name)
from app.services.core.rate_limit import RateLimitService

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_user_org(
    user: User,
    db: AsyncSession,
    org_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, list[str]]:
    """Return (org_id, roles) for the user's current org (from JWT).

    If org_id is provided (typically from get_org_id_from_request), uses that
    to find the specific membership. Falls back to first membership otherwise.
    """
    stmt = select(OrganizationMember.organization_id, OrganizationMember.roles).where(
        OrganizationMember.user_id == user.id
    )
    if org_id is not None:
        stmt = stmt.where(OrganizationMember.organization_id == org_id)
    stmt = stmt.limit(1)

    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=403,
            detail="User is not a member of any organization",
        )
    return row.organization_id, list(row.roles or [])


# ─── Skills ───


@router.get("/skills", response_model=ChatSkillListResponse)
async def list_skills(
    current_user: User = Depends(get_current_user),
):
    """Return available chat skills by reading the skills directory."""
    skills_path = Path(settings.skills_dir)
    result: list[ChatSkillResponse] = []
    if skills_path.is_dir():
        for skill_dir in sorted(skills_path.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                text = skill_file.read_text()
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1])
                        if meta:
                            result.append(
                                ChatSkillResponse(
                                    name=meta.get("name", skill_dir.name),
                                    description=meta.get("description", ""),
                                    icon=meta.get("icon", "sparkles"),
                                )
                            )
    return ChatSkillListResponse(skills=result)


# ─── Config ───


@router.get("/config", response_model=ChatConfigResponse)
async def get_chat_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_org_id: uuid.UUID | None = Depends(get_org_id_from_request),
):
    """Return chat configuration for the current user's org."""
    org_id, _ = await _get_user_org(current_user, db, org_id=current_org_id)
    context_window = await get_context_window("chat", db, org_id=org_id)
    model_name = await get_model_display_name("chat", db, org_id=org_id)

    return ChatConfigResponse(
        max_message_length=settings.max_message_length,
        model_name=model_name,
        context_window=context_window,
        compaction_threshold=settings.compaction_threshold,
    )


# ─── Sessions ───


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
    current_org_id: uuid.UUID | None = Depends(get_org_id_from_request),
):
    org_id, _ = await _get_user_org(current_user, db, org_id=current_org_id)
    session = await create_session(
        db,
        user_id=current_user.id,
        org_id=org_id,
        title=body.title,
        context_document_ids=body.context_document_ids,
    )
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_org_id: uuid.UUID | None = Depends(get_org_id_from_request),
):
    org_id, _ = await _get_user_org(current_user, db, org_id=current_org_id)
    sessions, total = await list_sessions(
        db, user_id=current_user.id, org_id=org_id, limit=limit, offset=offset
    )
    return ChatSessionListResponse(items=sessions, total=total)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")
    return session


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionResponse,
)
async def update_chat_session(
    session_id: uuid.UUID,
    body: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    session = await get_or_404(db, ChatSession, session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")
    if body.title is not None:
        session.title = body.title
    await db.commit()
    await db.refresh(session)
    return session


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    session = await get_or_404(db, ChatSession, session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")
    await delete_session(db, session)
    await db.commit()


# ─── Messages ───


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_chat_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(require_active_subscription()),
):
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")

    # Resolve org role for is_org_admin
    _, org_roles = await _get_user_org(current_user, db)
    is_org_admin = OrgRole.ADMIN.value in org_roles

    # Wrap send_message in a SAVEPOINT so a failed agent run rolls back only
    # its own partial state — the chat session row and any other prior
    # committed state stay intact for the forensic write below.
    try:
        async with db.begin_nested():
            user_msg, assistant_msg, sources = await send_message(
                db,
                session,
                body.content,
                user_id=current_user.id,
                is_org_admin=is_org_admin,
            )
        await db.commit()
        await db.refresh(user_msg)
        await db.refresh(assistant_msg)
        return ChatCompletionResponse(
            user_message=user_msg,
            assistant_message=assistant_msg,
            sources=[
                ChatSourceReference(
                    document_id=s.document_id,
                    document_title=s.document_title,
                    chunk_id=s.chunk_id,
                    chunk_index=s.chunk_index,
                    page_number=s.page_number,
                    score=s.score,
                    snippet=s.content[:200],
                )
                for s in sources
            ],
        )
    except Exception as exc:
        # Persist a forensic ERROR row so the failure isn't silent. The user
        # gets a generic toast (plus this short code to reference) while the
        # full traceback lives in postgres + the backend log.
        error_code = secrets.token_hex(4)
        logger.exception(
            "Chat completion failed [error_code=%s] for session %s",
            error_code,
            session_id,
        )
        try:
            db.add(
                ChatMessage(
                    session_id=session_id,
                    role=ChatMessageRole.USER,
                    content=body.content,
                )
            )
            db.add(
                ChatMessage(
                    session_id=session_id,
                    role=ChatMessageRole.ERROR,
                    content=str(exc),
                    metadata_={
                        "error_code": error_code,
                        "error_type": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )
            )
            await db.commit()
        except Exception:
            # Forensic write is best-effort — if even that fails, we still
            # want to return the original error to the user.
            logger.exception(
                "Failed to persist ERROR row [error_code=%s] for session %s",
                error_code,
                session_id,
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate AI response (error_code={error_code})",
        )


# ─── Admin Notifications ───


async def _get_org_admin_emails(org_id: uuid.UUID, db: AsyncSession) -> list[str]:
    """Get all admin emails for an org."""
    result = await db.execute(
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
        )
    )
    return result.scalars().all()


@router.post("/notify-admin", response_model=NotifyAdminResponse)
async def notify_admin(
    current_user: User = Depends(get_current_user),
    current_org_id: uuid.UUID | None = Depends(get_org_id_from_request),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    """Notify org admins that a non-Pro user needs AI configured.

    Rate limits:
    - 1 per user per 24h
    - 3 per org per 24h
    """
    from datetime import datetime

    # Get user's current org (from JWT token)
    org_id, _ = await _get_user_org(current_user, db, org_id=current_org_id)

    # Check if org is Pro (if so, they don't need to notify)
    result = await db.execute(
        select(Organization.subscription_tier).where(Organization.id == org_id)
    )
    tier = result.scalar_one_or_none()
    if (
        tier
        and TIER_RANK.get(SubscriptionTier(tier), 0) >= TIER_RANK[SubscriptionTier.PRO]
    ):
        raise HTTPException(
            status_code=403,
            detail="Your organization has Pro subscription. AI is available by default.",
        )

    # Check per-user rate limit (1 per 24h)
    user_rate_limit = RateLimitService(max_attempts=1, window_seconds=86400)
    user_key = f"notify-admin:user:{current_user.id}"
    if not await user_rate_limit.is_allowed(user_key, db):
        raise HTTPException(
            status_code=429,
            detail="You've already notified admins recently. They'll get back to you soon.",
        )

    # Check per-org rate limit (3 per 24h)
    org_rate_limit = RateLimitService(max_attempts=3, window_seconds=86400)
    org_key = f"notify-admin:org:{org_id}"
    if not await org_rate_limit.is_allowed(org_key, db):
        raise HTTPException(
            status_code=429,
            detail="Your organization has reached its notification limit. Please try again later.",
        )

    # Record rate limit attempts (both per-user and per-org)
    await user_rate_limit.record_attempt(user_key, db)
    await org_rate_limit.record_attempt(org_key, db)

    # Record notification
    notification = ChatNotification(
        user_id=current_user.id,
        org_id=org_id,
    )
    db.add(notification)
    await db.commit()

    # Log the notification (non-critical, don't fail if logging fails)
    try:
        logger.info(
            "Chat AI notification sent from user %s in org %s",
            current_user.id,
            org_id,
        )
    except Exception as e:
        logger.error("Failed to log chat notification: %s", e)

    return NotifyAdminResponse(
        message="Admin notified! They'll get back to you soon.",
        user_notified_at=datetime.utcnow(),
    )
