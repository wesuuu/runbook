import uuid
from typing import Optional, Any
from sqlalchemy import String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin

# RunSheet model removed in favor of Run.execution_data

class AuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False) # CREATE, UPDATE, DELETE
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    actor: Mapped["User"] = relationship("app.models.iam.User")
