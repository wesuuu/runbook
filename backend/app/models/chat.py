import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class ChatSessionStatus(str):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ChatMessageRole(str):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    SUMMARY = "summary"


class ChatSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), default="New Chat", nullable=False)
    status: Mapped[str] = mapped_column(
        String, default=ChatSessionStatus.ACTIVE, nullable=False
    )
    context_document_ids: Mapped[Optional[list[Any]]] = mapped_column(
        JSONB, nullable=True, default=None
    )
    ai_message_history: Mapped[Optional[list[Any]]] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Relationships
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True, default=None
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class ChatRateLimitAttempt(Base):
    __tablename__ = "chat_rate_limit_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (Index("idx_key_attempted_at", "key", "attempted_at"),)


class ChatNotification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "chat_notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("idx_org_created_at", "org_id", "created_at"),
        Index("idx_user_created_at", "user_id", "created_at"),
    )
