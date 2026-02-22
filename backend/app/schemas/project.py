from uuid import UUID
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    organization_id: UUID


class ProjectCreate(ProjectBase):
    owner_type: Optional[str] = None
    owner_id: Optional[UUID] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class ProjectResponse(ProjectBase):
    id: UUID
    owner_type: Optional[str] = None
    owner_id: Optional[UUID] = None
    settings: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Approver Schemas
class ApproverGrant(BaseModel):
    principal_type: str  # "USER" or "TEAM"
    principal_id: UUID


class ApproverEntry(BaseModel):
    id: UUID
    principal_type: str
    principal_id: UUID
    name: Optional[str] = None
    email: Optional[str] = None


class AuditLogEntry(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    entity_name: Optional[str] = None
    action: str
    changes: dict[str, Any] = {}
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    total: int
    offset: int
    limit: int
