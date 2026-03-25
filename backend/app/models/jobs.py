"""Background job tracking model.

Provides a generic job registry so async work can be tracked, claimed
by workers, and reported on.  Designed for future extensibility to
external backends (Kubernetes Jobs, Celery, external APIs) via the
SKIP LOCKED claim pattern.
"""

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BackgroundJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_bgj_status_job_type", "status", "job_type"),
        Index("ix_bgj_entity", "entity_type", "entity_id"),
    )

    job_type: Mapped[str] = mapped_column(
        String, nullable=False, doc="e.g. document_process, document_enrich"
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=JobStatus.PENDING.value,
        server_default=JobStatus.PENDING.value,
    )

    # Link back to the domain entity this job operates on
    entity_type: Mapped[str] = mapped_column(
        String, nullable=False, doc="e.g. document, run"
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
    )

    # Serialised arguments the worker needs to execute
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Results written back by the worker on completion
    output_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, doc="Hostname / pod name of claiming worker"
    )

    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        doc="Updated every ~15s by the owning worker; stale = worker died",
    )

    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
