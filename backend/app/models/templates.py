import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class TemplateType(str, enum.Enum):
    SOP = "SOP"
    BATCH_RECORD = "BATCH_RECORD"


class TemplateStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class DocumentTemplate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "document_templates"

    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", use_alter=True, name="fk_dt_org_id"),
        nullable=True,
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id", use_alter=True, name="fk_dt_project_id"),
        nullable=True,
    )
    uploaded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_dt_uploaded_by_id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    template_type: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String, default=TemplateStatus.ACTIVE, server_default="ACTIVE"
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_dt_archived_by_id"),
        nullable=True,
    )

    # Relationships
    organization: Mapped[Optional["app.models.iam.Organization"]] = relationship(
        foreign_keys=[org_id]
    )
    project: Mapped[Optional["app.models.projects.Project"]] = relationship(
        foreign_keys=[project_id]
    )
    uploaded_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        foreign_keys=[uploaded_by_id]
    )
    archived_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        foreign_keys=[archived_by_id]
    )
