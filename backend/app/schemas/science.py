from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

# UnitOpDefinition Schemas
class UnitOpDefinitionBase(BaseModel):
    name: str
    category: str = "General"
    description: Optional[str] = None
    param_schema: Dict[str, Any] = Field(default_factory=dict)

class UnitOpDefinitionCreate(UnitOpDefinitionBase):
    pass

class UnitOpDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    param_schema: Optional[Dict[str, Any]] = None

class UnitOpDefinitionResponse(UnitOpDefinitionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ProtocolRole Schemas
class ProtocolRoleBase(BaseModel):
    name: str
    color: str = "#94a3b8"
    sort_order: int = 0

class ProtocolRoleCreate(ProtocolRoleBase):
    pass

class ProtocolRoleUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None

class ProtocolRoleResponse(ProtocolRoleBase):
    id: UUID
    protocol_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Protocol Schemas
class ProtocolBase(BaseModel):
    name: str
    description: Optional[str] = None
    graph: Dict[str, Any] = Field(default_factory=dict)

class ProtocolCreate(ProtocolBase):
    project_id: UUID

    class Config:
        from_attributes = True

class ProtocolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    graph: Optional[Dict[str, Any]] = None

class ProtocolResponse(ProtocolBase):
    id: UUID
    project_id: UUID
    status: str = "DRAFT"
    version_number: int = 0
    roles: List[ProtocolRoleResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Protocol Version Schemas
class ProtocolVersionListItem(BaseModel):
    id: UUID
    version_number: int
    name: str
    change_summary: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    is_draft: bool = False

    class Config:
        from_attributes = True


class ProtocolVersionResponse(ProtocolVersionListItem):
    protocol_id: UUID
    graph: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    created_by_id: Optional[UUID] = None

    class Config:
        from_attributes = True


# Protocol Approval Schemas
class ProtocolApprovalAction(BaseModel):
    comment: Optional[str] = None

# Run Schemas
class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"

class RunBase(BaseModel):
    name: str
    status: RunStatus = RunStatus.PLANNED
    graph: Dict[str, Any] = Field(default_factory=dict)
    execution_data: Dict[str, Any] = Field(default_factory=dict)

class RunCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None

class RunUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[RunStatus] = None
    graph: Optional[Dict[str, Any]] = None
    execution_data: Optional[Dict[str, Any]] = None

class RunResponse(RunBase):
    id: UUID
    project_id: UUID
    protocol_id: Optional[UUID]
    started_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Run Role Assignment Schemas
class RunRoleAssignmentBase(BaseModel):
    lane_node_id: str
    role_name: str
    user_id: UUID

class RunRoleAssignmentCreate(RunRoleAssignmentBase):
    pass

class RunRoleAssignmentResponse(RunRoleAssignmentBase):
    id: UUID
    run_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RunRoleAssignmentListResponse(BaseModel):
    items: List[RunRoleAssignmentResponse] = []

# Equipment Schemas
class EquipmentBase(BaseModel):
    name: str
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    location: Optional[str] = None

class EquipmentCreate(EquipmentBase):
    pass

class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    equipment_type: Optional[str] = None
    location: Optional[str] = None

class EquipmentResponse(EquipmentBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
