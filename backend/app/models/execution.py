import uuid
from typing import Optional, Any
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin

# RunSheet model removed in favor of Experiment.execution_data
# class RunSheet(Base, UUIDMixin, TimestampMixin):
#     __tablename__ = "run_sheets"
# 
#     experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiments.id"), nullable=False)
#     protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("protocols.id"), nullable=True)
#     graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
#     status: Mapped[str] = mapped_column(String, default="DRAFT")
# 
#     # Relationships
#     experiment: Mapped["Experiment"] = relationship("app.models.science.Experiment", back_populates="run_sheets")
#     protocol: Mapped[Optional["Protocol"]] = relationship("app.models.science.Protocol")

class AuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False) # CREATE, UPDATE, DELETE
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    actor: Mapped["User"] = relationship("app.models.iam.User")
