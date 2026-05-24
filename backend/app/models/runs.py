"""Run domain models (TD-0083): RunStatus, RunOutcome, ExperimentStatus, Run, RunRoleAssignment, Experiment."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, Numeric, String,
                        Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.iam import User
    from app.models.projects import Project
    from app.models.protocols import Protocol


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EDITED = "EDITED"
    ARCHIVED = "ARCHIVED"


class RunOutcome(str, Enum):
    COMPLETED_NORMAL = "COMPLETED_NORMAL"
    COMPLETED_WITH_DEVIATIONS = "COMPLETED_WITH_DEVIATIONS"
    ABORTED = "ABORTED"


class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class Run(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_outcome", "outcome"),
        UniqueConstraint("project_id", "slug", name="uq_runs_project_slug"),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
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

    # F-0080: GLP sign-off reviewers, designated up front (nullable = no
    # specific reviewer; a null QAU resolves to the org QAU pool).
    study_director_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    qau_reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
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

    # F-0043: structured key result for the experiment Results table + chart
    key_result_label: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    key_result_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    key_result_unit: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )

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
    project: Mapped["Project"] = relationship(back_populates="runs", lazy="selectin")
    protocol: Mapped["Protocol"] = relationship(back_populates="runs")
    experiment: Mapped[Optional["Experiment"]] = relationship(back_populates="runs")
    started_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[started_by_id]
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[created_by_id]
    )
    study_director: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[study_director_id]
    )
    qau_reviewer: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[qau_reviewer_id]
    )
    role_assignments: Mapped[List["RunRoleAssignment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    @property
    def project_slug(self) -> str:
        """Slug of the owning project — for building nested run URLs."""
        return self.project.slug


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
    user: Mapped["User"] = relationship()


class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_experiments_project_slug"),
    )

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
    slug: Mapped[str] = mapped_column(String(64), nullable=False)

    # F-0093: investigation objective + success criteria.
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # F-0043: conclusion + lock
    conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conclusion_locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conclusion_locked_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    conclusion_locked_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    conclusion_locked_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[conclusion_locked_by_id]
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        back_populates="experiments", lazy="selectin"
    )
    runs: Mapped[List["Run"]] = relationship(back_populates="experiment")
    created_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by_id]
    )

    @property
    def project_slug(self) -> str:
        """Slug of the owning project — for building nested experiment URLs."""
        return self.project.slug
