import uuid
from typing import List, Optional, Any

from sqlalchemy import String, Integer, ForeignKey, Enum, Index, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EDITED = "EDITED"
    ARCHIVED = "ARCHIVED"


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

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "app.models.iam.Organization", back_populates="projects"
    )
    runs: Mapped[List["Run"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    protocols: Mapped[List["Protocol"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Protocol(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocols"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, default="DRAFT", server_default="DRAFT", nullable=False
    )
    version_number: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # The template graph structure
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="protocols")
    runs: Mapped[List["Run"]] = relationship(
        back_populates="protocol"
    )
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


class Run(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runs"

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
    execution_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict
    )

    # User who started this run (used for locking role-less runs)
    started_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="runs")
    protocol: Mapped["Protocol"] = relationship(back_populates="runs")
    started_by: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User", foreign_keys=[started_by_id]
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
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # Relationships
    run: Mapped["Run"] = relationship(
        back_populates="role_assignments"
    )
    user: Mapped["app.models.iam.User"] = relationship()


class UnitOpDefinition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_definitions"

    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(
        String, nullable=False, default="General"
    )
    description: Mapped[Optional[str]] = mapped_column(String)

    # Configuration schema (JSONSchema) for this operation
    param_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict
    )

    # Result schema (JSONSchema) — what the scientist records during execution
    result_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )


class ProtocolRole(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocol_roles"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(
        String, nullable=False, default="#94a3b8"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

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
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    change_summary: Mapped[Optional[str]] = mapped_column(String)
    is_draft: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    # Relationships
    protocol: Mapped["Protocol"] = relationship(back_populates="versions")
    created_by: Mapped[Optional["app.models.iam.User"]] = relationship()


class Equipment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "equipment"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    equipment_type: Mapped[Optional[str]] = mapped_column(String)
    location: Mapped[Optional[str]] = mapped_column(String)
