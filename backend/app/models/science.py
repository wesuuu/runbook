import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EDITED = "EDITED"
    ARCHIVED = "ARCHIVED"


class GlpSignoffRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class GlpRole(str, Enum):
    """21 CFR Part 58 roles used across protocol approval and run sign-off."""

    SPONSOR = "SPONSOR"  # §58.10, §58.120(a)
    STUDY_DIRECTOR = "STUDY_DIRECTOR"  # §58.33
    QAU = "QAU"  # §58.35
    OPERATOR = "OPERATOR"  # §58.29


class GlpSignoffAction(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUESTED_CHANGES = "REQUESTED_CHANGES"


class RunOutcome(str, Enum):
    COMPLETED_NORMAL = "COMPLETED_NORMAL"
    COMPLETED_WITH_DEVIATIONS = "COMPLETED_WITH_DEVIATIONS"
    ABORTED = "ABORTED"


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


class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String, default=ExperimentStatus.DRAFT, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="experiments")
    runs: Mapped[List["Run"]] = relationship(back_populates="experiment")


class Protocol(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocols"

    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND organization_id IS NULL) OR "
            "(project_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_protocol_scope",
        ),
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
    project: Mapped[Optional["Project"]] = relationship(back_populates="protocols")
    organization: Mapped[Optional["Organization"]] = relationship(
        "app.models.iam.Organization", foreign_keys=[organization_id]
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
    created_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[created_by_id]
    )
    approved_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[approved_by_id]
    )
    approval_requests: Mapped[List["GlpSignoffRequest"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="GlpSignoffRequest.created_at.desc()",
    )


class Run(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_outcome", "outcome"),)

    name: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocols.id"), nullable=True
    )
    status: Mapped[RunStatus] = mapped_column(
        String, default=RunStatus.PLANNED, nullable=False
    )

    # Snapshot of the protocol graph + deviations
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Runtime data (logs, values, timestamps per node)
    execution_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Run-level notes (append-only, authored, timestamped)
    notes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # File attachments (run-level or step-level, soft-deletable)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # User who started this run (used for locking role-less runs)
    started_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # User who created this run. Used for permission checks when editing a
    # PLANNED run on a project with permissions_enabled=true: the creator may
    # always edit their own planned run, in addition to project admins.
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Optional experiment grouping
    experiment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("experiments.id"), nullable=True
    )
    is_tour_sample: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    is_strict: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # F-0086: explicit designation that this run produces a manufacturing lot.
    # Drives validation (lot_number required when true) and the runs-list filter.
    produces_lot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )

    # Production metadata (QA-0008): lot/batch identifiers for GxP traceability.
    # Nullable because experiment-style runs may not have a manufacturing lot.
    lot_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    batch_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # GLP run lifecycle timestamps and outcome (21 CFR Part 58)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome: Mapped[Optional[RunOutcome]] = mapped_column(String, nullable=True)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="runs")
    protocol: Mapped["Protocol"] = relationship(back_populates="runs")
    experiment: Mapped[Optional["Experiment"]] = relationship(back_populates="runs")
    started_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[started_by_id]
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[created_by_id]
    )
    role_assignments: Mapped[List["RunRoleAssignment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunRoleAssignment(Base, UUIDMixin, TimestampMixin):
    """
    Assigns a user to a role (swimlane) within a run.

    lane_node_id is the stable identifier from the snapshotted run.graph,
    e.g., "lane-{role_uuid}". This allows assignments to remain valid even if
    the source ProtocolRole is later deleted.
    """

    __tablename__ = "run_role_assignments"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    lane_node_id: Mapped[str] = mapped_column(String, nullable=False)
    role_name: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="role_assignments")
    user: Mapped["app.models.iam.User"] = relationship()


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

    organization: Mapped["app.models.iam.Organization"] = relationship(
        "app.models.iam.Organization",
        foreign_keys=[organization_id],
    )


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
    organization: Mapped[Optional["app.models.iam.Organization"]] = relationship(
        "app.models.iam.Organization", foreign_keys=[organization_id]
    )
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])


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
    created_by: Mapped[Optional["app.models.iam.User"]] = relationship()


class Equipment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "equipment"
    __table_args__ = (
        Index("ix_equipment_site", "site_id"),
        Index("ix_equipment_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    equipment_type: Mapped[Optional[str]] = mapped_column(String)
    location: Mapped[Optional[str]] = mapped_column(String)
    site_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EquipmentStatus.ACTIVE,
        server_default="ACTIVE",
    )
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_calibration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_calibration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    calibration_certificate_path: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    room: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::varchar[]"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    site = relationship("Site", back_populates="equipment", lazy="joined")
    attachments = relationship(
        "EquipmentAttachment",
        back_populates="equipment",
        lazy="select",
        cascade="all, delete-orphan",
    )


class EquipmentAttachment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "equipment_attachments"

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    equipment = relationship("Equipment", back_populates="attachments", lazy="joined")


class SiteManagerGrant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "site_manager_grants"
    __table_args__ = (
        Index("ix_site_manager_grants_site", "site_id"),
        Index("ix_site_manager_grants_user", "user_id"),
        Index("ix_site_manager_grants_org", "organization_id"),
        Index(
            "uq_site_manager_grants_site_user",
            "site_id",
            "user_id",
            unique=True,
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    site = relationship("Site", lazy="joined")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    granted_by = relationship("User", foreign_keys=[granted_by_id], lazy="select")


class Site(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = (
        Index("ix_sites_org", "organization_id"),
        Index(
            "uq_sites_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "uq_sites_org_is_default",
            "organization_id",
            unique=True,
            postgresql_where=text("is_default = true AND archived_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    equipment = relationship("Equipment", back_populates="site", lazy="select")


class GlpSignoffRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "glp_signoff_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','APPROVED','REJECTED','WITHDRAWN')",
            name="ck_proto_appr_req_status",
        ),
        Index(
            "ix_proto_appr_req_open_unique",
            "protocol_id",
            "requested_user_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    requested_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="OPEN", server_default="OPEN", nullable=False
    )
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    protocol: Mapped["Protocol"] = relationship(back_populates="approval_requests")
    requested_user: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_user_id]
    )
    requested_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[requested_by_id]
    )
    fulfilled_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[fulfilled_by_id]
    )


class GlpSignoff(Base, UUIDMixin, TimestampMixin):
    """Unified GLP signature event for both protocol approvals
    (pre-execution) and run sign-offs (during/post-execution).
    Partition by FK: exactly one of protocol_id/run_id is set.

    This model is the single source of truth for signature events after
    F-0087 Task 27 retired the legacy protocol-approval events table.
    """

    __tablename__ = "glp_signoffs"
    __table_args__ = (
        CheckConstraint(
            "(protocol_id IS NOT NULL AND run_id IS NULL) OR "
            "(protocol_id IS NULL AND run_id IS NOT NULL)",
            name="ck_glp_signoff_scope",
        ),
        CheckConstraint(
            "role IN ('SPONSOR','STUDY_DIRECTOR','QAU','OPERATOR')",
            name="ck_glp_signoff_role",
        ),
        CheckConstraint(
            "action IN ('APPROVED','REJECTED','REQUESTED_CHANGES')",
            name="ck_glp_signoff_action",
        ),
        CheckConstraint(
            "(protocol_id IS NULL) OR " "(role IN ('SPONSOR','STUDY_DIRECTOR','QAU'))",
            name="ck_protocol_signoff_roles",
        ),
        CheckConstraint(
            "(run_id IS NULL) OR " "(role IN ('OPERATOR','STUDY_DIRECTOR','QAU'))",
            name="ck_run_signoff_roles",
        ),
        CheckConstraint(
            "(action != 'APPROVED') OR "
            "(attestation IS NOT NULL AND signature_image_path IS NOT NULL)",
            name="ck_approved_requires_attestation",
        ),
        Index(
            "ux_glp_signoff_active_protocol",
            "protocol_id",
            "role",
            unique=True,
            postgresql_where=text(
                "protocol_id IS NOT NULL AND action='APPROVED' "
                "AND invalidated_at IS NULL"
            ),
        ),
        Index(
            "ux_glp_signoff_active_run",
            "run_id",
            "role",
            unique=True,
            postgresql_where=text(
                "run_id IS NOT NULL AND action='APPROVED' " "AND invalidated_at IS NULL"
            ),
        ),
    )

    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )

    role: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)

    signer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    attestation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    signoff_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "glp_signoff_requests.id",
            use_alter=True,
            name="fk_glp_signoff_request",
        ),
        nullable=True,
    )

    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    invalidated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Grilling decision #15: distinguish edit-invalidation vs reopen-supersession.
    # Both set invalidated_at; only reopen sets this FK to the audit event row.
    superseded_by_reopen_audit_event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "audit_logs.id",
            use_alter=True,
            name="fk_glp_signoff_superseded_by",
        ),
        nullable=True,
    )

    protocol: Mapped[Optional["Protocol"]] = relationship(
        "Protocol", foreign_keys=[protocol_id]
    )
    run: Mapped[Optional["Run"]] = relationship("Run", foreign_keys=[run_id])
    signer: Mapped["app.models.iam.User"] = relationship(
        "app.models.iam.User", foreign_keys=[signer_id]
    )
    invalidated_by: Mapped[Optional["app.models.iam.User"]] = relationship(
        "app.models.iam.User", foreign_keys=[invalidated_by_id]
    )
