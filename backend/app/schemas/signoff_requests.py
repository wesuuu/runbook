"""Schemas for the unified sign-off review queue (F-0080)."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class QueueActorRef(BaseModel):
    id: str
    name: str
    email: str


class SignoffRequestItem(BaseModel):
    type: Literal["run", "protocol"]
    request_id: Optional[UUID] = None
    target_id: UUID
    target_name: str
    role: Optional[str] = None
    project_id: Optional[UUID] = None
    assigned: bool
    requested_by: Optional[QueueActorRef] = None
    created_at: Optional[datetime] = None
