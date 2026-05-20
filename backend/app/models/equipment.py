"""Equipment domain models (TD-0083): EquipmentStatus, Equipment, EquipmentAttachment."""

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import ARRAY, Date, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


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
