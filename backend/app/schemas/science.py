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

class UnitOpDefinitionResponse(UnitOpDefinitionBase):
    id: UUID
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
