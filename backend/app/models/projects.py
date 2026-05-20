"""Project domain models (TD-0083): Project."""

import uuid
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.iam import Organization
    from app.models.protocols import Protocol
    from app.models.runs import Experiment, Run


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    owner_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    default_sop_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_proj_sop_tpl"),
        nullable=True,
    )
    default_batch_record_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_proj_br_tpl"),
        nullable=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "app.models.iam.Organization", back_populates="projects"
    )
    runs: Mapped[List["Run"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    protocols: Mapped[List["Protocol"]] = relationship(back_populates="project")
    experiments: Mapped[List["Experiment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
