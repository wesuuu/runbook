from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentTemplateResponse(BaseModel):
    id: UUID
    org_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    uploaded_by_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    template_type: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    variables: dict[str, Any] = {}
    is_system: bool = False
    is_default: bool = False
    is_current_default: bool = False
    status: str = "ACTIVE"
    archived_at: Optional[datetime] = None
    archived_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    set_as_default: Optional[bool] = None
