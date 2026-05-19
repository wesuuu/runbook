from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: UUID
    description: str | None = None
    equipment_type: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    room: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    status: EquipmentStatus = EquipmentStatus.ACTIVE
    install_date: date | None = None
    last_calibration_date: date | None = None
    next_calibration_date: date | None = None


class EquipmentUpdate(BaseModel):
    """All fields optional — endpoint diffs which are touched against
    `RESTRICTED_EQUIPMENT_FIELDS` to enforce role gate."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: UUID | None = None
    description: str | None = None
    equipment_type: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    room: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    status: EquipmentStatus | None = None
    install_date: date | None = None
    last_calibration_date: date | None = None
    next_calibration_date: date | None = None


class EquipmentAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    equipment_id: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_by_id: UUID
    created_at: datetime


class EquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    site_id: UUID
    name: str
    description: str | None
    equipment_type: str | None
    location: str | None
    room: str | None
    tags: list[str]
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    status: EquipmentStatus
    install_date: date | None
    last_calibration_date: date | None
    next_calibration_date: date | None
    archived_at: datetime | None
    archived_by_id: UUID | None
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
