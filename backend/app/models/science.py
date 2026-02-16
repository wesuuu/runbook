import uuid
from typing import List, Optional, Any
from sqlalchemy import String, ForeignKey, Enum
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
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship("app.models.iam.Organization", back_populates="projects")
    experiments: Mapped[List["Experiment"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    protocols: Mapped[List["Protocol"]] = relationship(back_populates="project", cascade="all, delete-orphan")

class Protocol(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "protocols"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    
    # The template graph structure (nodes, edges, viewport)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="protocols")
    experiments: Mapped[List["Experiment"]] = relationship(back_populates="protocol")

class Experiment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    protocol_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("protocols.id"), nullable=True)
    status: Mapped[ExperimentStatus] = mapped_column(String, default=ExperimentStatus.PLANNED, nullable=False)
    
    # Snapshot of the protocol graph + deviations
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    
    # Runtime data (logs, values, timestamps per node)
    execution_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="experiments")
    protocol: Mapped["Protocol"] = relationship(back_populates="experiments")

class UnitOpDefinition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_definitions"

    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, default="General")
    description: Mapped[Optional[str]] = mapped_column(String)
    
    # Configuration schema (JSONSchema) for this operation
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
