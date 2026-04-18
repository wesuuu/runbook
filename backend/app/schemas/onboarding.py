"""Pydantic schemas for the onboarding tour."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

TourSegment = Literal["project", "protocol", "run"]
TourStatus = Literal["completed", "dismissed"]


class TourStateResponse(BaseModel):
    completed: list[TourSegment] = []
    dismissed: list[TourSegment] = []
    model_config = ConfigDict(from_attributes=True)


class TourStateUpdate(BaseModel):
    segment: TourSegment
    status: TourStatus


class TourProjectStartResponse(BaseModel):
    project_id: UUID


class TourProtocolStartResponse(BaseModel):
    project_id: UUID
    protocol_id: UUID


class TourRunStartResponse(BaseModel):
    run_id: UUID
    protocol_id: UUID
    project_id: UUID
