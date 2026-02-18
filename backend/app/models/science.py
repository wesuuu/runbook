import uuid
from typing import List, Optional, Any

from sqlalchemy import String, Integer, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class ExperimentStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
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

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "app.models.iam.Organization", back_populates="projects"
    )
    experiments: Mapped[List["Experiment"]] = relationship(
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

    # The template graph structure
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="protocols")
    experiments: Mapped[List["Experiment"]] = relationship(
        back_populates="protocol"
    )
    roles: Mapped[List["ProtocolRole"]] = relationship(
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="ProtocolRole.sort_order",
    )


class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("protocols.id"), nullable=True
    )
    status: Mapped[ExperimentStatus] = mapped_column(
        String, default=ExperimentStatus.PLANNED, nullable=False
    )

    # Snapshot of the protocol graph + deviations
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Runtime data (logs, values, timestamps per node)
    execution_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="experiments")
    protocol: Mapped["Protocol"] = relationship(back_populates="experiments")
    role_assignments: Mapped[List["ExperimentRoleAssignment"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentRoleAssignment(Base, UUIDMixin, TimestampMixin):
    """
    Assigns a user to a role (swimlane) within an experiment.

    lane_node_id is the stable identifier from the snapshotted experiment.graph,
    e.g., "lane-{role_uuid}". This allows assignments to remain valid even if
    the source ProtocolRole is later deleted.
    """
    __tablename__ = "experiment_role_assignments"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    lane_node_id: Mapped[str] = mapped_column(String, nullable=False)
    role_name: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    # Relationships
    experiment: Mapped["Experiment"] = relationship(
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


class Equipment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "equipment"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    equipment_type: Mapped[Optional[str]] = mapped_column(String)
    location: Mapped[Optional[str]] = mapped_column(String)
