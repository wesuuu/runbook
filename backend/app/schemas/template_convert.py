"""Schemas for the template conversion endpoints."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ConvertWarning(BaseModel):
    type: str
    variable: str
    description: str


class ConvertResponse(BaseModel):
    conversion_id: str
    preview_url: str
    template_download_url: str
    warnings: list[ConvertWarning] = []
    variables_detected: list[str] = []
    verification_rounds: int
    verification_passed: bool


class RefineRequest(BaseModel):
    instruction: str


class SaveRequest(BaseModel):
    name: str
    template_type: str
    description: Optional[str] = None
    project_id: Optional[UUID] = None
    set_as_default: bool = False
