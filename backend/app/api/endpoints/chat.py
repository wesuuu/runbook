import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_or_404
from app.db.session import get_db
from app.models.chat import ChatSession
from app.models.iam import OrganizationMember, User, ObjectType, PermissionLevel
from app.models.science import Project
from app.schemas.chat import (
    ChatCompletionResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatSourceReference,
    GenerateProtocolRequest,
    GenerateProtocolResponse,
)
from app.services import chat_service
from app.services.audit import log_audit
from app.services.permissions import check_permission

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_user_org_id(user: User, db: AsyncSession) -> uuid.UUID:
    result = await db.execute(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .limit(1)
    )
    org_id = result.scalar_one_or_none()
    if org_id is None:
        raise HTTPException(
            status_code=403,
            detail="User is not a member of any organization",
        )
    return org_id


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_user_org_id(current_user, db)
    session = await chat_service.create_session(
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
):
    org_id = await _get_user_org_id(current_user, db)
    sessions, total = await chat_service.list_sessions(
        db, user_id=current_user.id, org_id=org_id, limit=limit, offset=offset
    )
    return ChatSessionListResponse(items=sessions, total=total)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await chat_service.get_session(db, session_id)
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
):
    session = await get_or_404(db, ChatSession, session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")
    await chat_service.delete_session(db, session)
    await db.commit()


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
):
    session = await chat_service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")

    try:
        user_msg, assistant_msg, sources = await chat_service.send_message(
            db, session, body.content
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
    except Exception:
        logger.exception("Chat completion failed for session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate AI response",
        )


@router.post(
    "/sessions/{session_id}/generate-protocol",
    response_model=GenerateProtocolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_protocol_from_chat(
    session_id: uuid.UUID,
    body: GenerateProtocolRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a DRAFT protocol from a chat conversation."""
    from app.services.protocol_generator import generate_protocol_from_chat

    # Validate session exists and belongs to user
    session = await chat_service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your chat session")

    # Validate project exists
    result = await db.execute(
        select(Project).where(Project.id == body.project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check EDIT permission on project
    allowed = await check_permission(
        db, current_user.id, ObjectType.PROJECT,
        body.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="EDIT permission required on project",
        )

    try:
        protocol = await generate_protocol_from_chat(
            db,
            session,
            body.project_id,
            current_user.id,
            body.protocol_name,
        )

        # Audit log
        await log_audit(
            db,
            actor_id=current_user.id,
            action="CREATE",
            entity_type="Protocol",
            entity_id=protocol.id,
            changes={
                "name": protocol.name,
                "source": "ai_generated",
                "chat_session_id": session_id,
                "generated_by": current_user.id,
            },
        )

        await db.commit()
        await db.refresh(protocol)

        return GenerateProtocolResponse(
            protocol_id=protocol.id,
            protocol_name=protocol.name,
            project_id=protocol.project_id,
        )
    except Exception:
        logger.exception(
            "Protocol generation failed for session %s", session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to generate protocol",
        )
