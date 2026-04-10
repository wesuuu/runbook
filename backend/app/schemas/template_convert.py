"""Schemas for the template conversion endpoints."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ConvertWarning(BaseModel):
    type: str
    variable: str
    description: str


class ConvertStartResponse(BaseModel):
    conversion_id: str
    status: str  # "processing"


class ConvertResponse(BaseModel):
    conversion_id: str
    preview_url: str
    template_download_url: str
    warnings: list[ConvertWarning] = []
    variables_detected: list[str] = []


class RefineRequest(BaseModel):
    instruction: str


class SaveRequest(BaseModel):
    name: str
    template_type: str
    description: Optional[str] = None
    project_id: Optional[UUID] = None
    set_as_default: bool = False


# ── SSE Event Schemas ──


class ToolCallEvent(BaseModel):
    """SSE data for 'tool_call' event — a tool invocation starts."""

    tool: str
    status: str  # "running"
    sequence: int


class ToolResultEvent(BaseModel):
    """SSE data for 'tool_result' event — a tool invocation completes."""

    tool: str
    status: str  # "success" | "error"
    sequence: int
    summary: str


class ConversionCompleteEvent(BaseModel):
    """SSE data for 'complete' event."""

    template_url: str
    preview_url: Optional[str] = None
    variables: list[str] = []
    warnings: list[ConvertWarning] = []


class ConversionErrorEvent(BaseModel):
    """SSE data for 'error' event."""

    message: str
