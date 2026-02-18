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
    roles: List[ProtocolRoleResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Experiment Schemas
class ExperimentStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"

class ExperimentBase(BaseModel):
    name: str
    status: ExperimentStatus = ExperimentStatus.PLANNED
    graph: Dict[str, Any] = Field(default_factory=dict)
    execution_data: Dict[str, Any] = Field(default_factory=dict)

class ExperimentCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None

class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[ExperimentStatus] = None
    graph: Optional[Dict[str, Any]] = None
    execution_data: Optional[Dict[str, Any]] = None

class ExperimentResponse(ExperimentBase):
    id: UUID
    project_id: UUID
    protocol_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Experiment Role Assignment Schemas
class ExperimentRoleAssignmentBase(BaseModel):
    lane_node_id: str
    role_name: str
    user_id: UUID

class ExperimentRoleAssignmentCreate(ExperimentRoleAssignmentBase):
    pass

class ExperimentRoleAssignmentResponse(ExperimentRoleAssignmentBase):
    id: UUID
    experiment_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ExperimentRoleAssignmentListResponse(BaseModel):
    items: List[ExperimentRoleAssignmentResponse] = []

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
