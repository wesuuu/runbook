"""Protocol domain models (TD-0083): Protocol, ProtocolRole, ProtocolVersion, UnitOpDefinition, UnitOpLibrarySubscription."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.iam import Organization, User
    from app.models.projects import Project
    from app.models.runs import Run
    from app.models.signoffs import GlpSignoffRequest


class Protocol(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocols"

    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND organization_id IS NULL) OR "
            "(project_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_protocol_scope",
        ),
        UniqueConstraint("owner_org_id", "slug", name="uq_protocols_owner_org_slug"),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    supersedes_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definitions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    owner_org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String, default="DRAFT", server_default="DRAFT", nullable=False
    )
    version_number: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    is_tour_sample: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The template graph structure
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Document template bindings
    sop_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_proto_sop_tpl"),
        nullable=True,
    )
    batch_record_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_proto_br_tpl"),
        nullable=True,
    )

    # Relationships
    project: Mapped[Optional["Project"]] = relationship(
        back_populates="protocols", lazy="selectin"
    )
    organization: Mapped[Optional["Organization"]] = relationship(
        "app.models.iam.Organization",
        foreign_keys=[organization_id],
    )
    runs: Mapped[List["Run"]] = relationship(back_populates="protocol")
    roles: Mapped[List["ProtocolRole"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="ProtocolRole.sort_order",
    )
    versions: Mapped[List["ProtocolVersion"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="ProtocolVersion.version_number.desc()",
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[created_by_id]
    )
    approved_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[approved_by_id]
    )
    approval_requests: Mapped[List["GlpSignoffRequest"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="GlpSignoffRequest.created_at.desc()",
    )

    @property
    def project_slug(self) -> Optional[str]:
        """Slug of the owning project — for building project back-links.

        ``None`` for org-scoped (library) protocols, which have no project.
        """
        return self.project.slug if self.project else None


class ProtocolRole(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocol_roles"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False, default="#94a3b8")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    protocol: Mapped["Protocol"] = relationship(back_populates="roles")


class ProtocolVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocol_versions"
    __table_args__ = (
        Index(
            "ix_proto_ver_lookup",
            "protocol_id",
            "version_number",
            unique=True,
        ),
    )

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    doc_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    supersedes_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definitions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    change_summary: Mapped[Optional[str]] = mapped_column(String)
    is_draft: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    # Document template bindings (snapshotted from Protocol)
    sop_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_pv_sop_tpl"),
        nullable=True,
    )
    batch_record_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("document_templates.id", use_alter=True, name="fk_pv_br_tpl"),
        nullable=True,
    )

    # Relationships
    protocol: Mapped["Protocol"] = relationship(back_populates="versions")
    created_by: Mapped[Optional["User"]] = relationship()


class UnitOpDefinition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_definitions"
    __table_args__ = (
        CheckConstraint(
            "project_id IS NULL OR organization_id IS NOT NULL",
            name="ck_unit_op_scope_valid",
        ),
        CheckConstraint(
            "(source_library_slug IS NULL AND source_op_slug IS NULL) OR "
            "(source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)",
            name="ck_unit_op_source_both_or_neither",
        ),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, default="General")
    description: Mapped[Optional[str]] = mapped_column(String)

    # Configuration schema (JSONSchema) for this operation
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Result schema (JSONSchema) — what the scientist records during execution
    result_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    # Scoping: NULL/NULL = global, org set = org-scoped, both set = project-scoped
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )

    # Library override pointers (F-0075). Set when this row overrides a
    # JSON op; the row's id equals synthetic_uuid(slug, op_slug).
    source_library_slug: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )
    source_op_slug: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "app.models.iam.Organization", foreign_keys=[organization_id]
    )
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])


class UnitOpLibrarySubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_library_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "library_slug",
            name="uq_unit_op_lib_sub",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    library_slug: Mapped[str] = mapped_column(String, nullable=False)
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship(
        "app.models.iam.Organization",
        foreign_keys=[organization_id],
    )
