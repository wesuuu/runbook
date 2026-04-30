"""Batch record import session tracking model.

Tracks the lifecycle of importing a paper batch record:
EXTRACTING → REVIEW → FINALIZED (or FAILED at any point).
"""

import enum
import uuid
from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class BatchRecordImportStatus(str, enum.Enum):
    EXTRACTING = "EXTRACTING"
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class BatchRecordImport(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "batch_record_imports"
    __table_args__ = (
        Index("ix_bri_org_status", "org_id", "status"),
        Index("ix_bri_project_created", "project_id", "created_at"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=BatchRecordImportStatus.EXTRACTING.value,
    )

    # Source document
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # AI extraction output
    extraction_result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    extraction_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Protocol mapping (user-selected at upload time)
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocols.id"), nullable=False
    )

    # User-reviewed data — accept/edit/reject decisions (audit trail)
    reviewed_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Result
    created_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("runs.id"), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
