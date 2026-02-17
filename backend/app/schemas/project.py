from uuid import UUID
from datetime import datetime
from typing import Optional

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


class ProjectResponse(ProjectBase):
    id: UUID
    owner_type: Optional[str] = None
    owner_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
