from typing import Any, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.ai import SUPPORTED_PROVIDERS, SUPPORTED_CAPABILITIES


# --- AI Provider Settings ---


class AiProviderConfigUpdate(BaseModel):
    provider: str
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_enabled: bool = True


class AiProviderConfigResponse(BaseModel):
    id: UUID
    capability: str
    provider: str
    model_name: str
    api_key_set: bool = Field(
        description="Whether an API key is configured (never returns the actual key)"
    )
    api_key_hint: Optional[str] = Field(
        default=None,
        description="Masked API key hint, e.g. 'sk-ant-...a1b2'",
    )
    base_url: Optional[str] = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AiSettingsListResponse(BaseModel):
    items: list[AiProviderConfigResponse]


class AiTestConnectionResponse(BaseModel):
    success: bool
    message: str


# --- Image Upload & Conversation ---


class RunImageResponse(BaseModel):
    id: UUID
    run_id: UUID
    step_id: str
    file_path: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    uploaded_by_id: Optional[UUID] = None
    parameter_tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunImageListResponse(BaseModel):
    items: list[RunImageResponse]


class ImageConversationResponse(BaseModel):
    id: UUID
    image_id: UUID
    messages: list[dict[str, Any]]
    extracted_values: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunImageDetailResponse(RunImageResponse):
    conversation: Optional[ImageConversationResponse] = None


# --- Analyze / Converse / Confirm ---


class ConverseRequest(BaseModel):
    message: str = Field(description="User's reply to the AI")


class ExtractedValueSchema(BaseModel):
    field_key: str
    field_label: str
    value: float | int | str
    unit: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class AnalysisResponse(BaseModel):
    conversation: ImageConversationResponse
    message: str
    extracted_values: list[ExtractedValueSchema]
    needs_clarification: bool


class ConfirmRequest(BaseModel):
    values: dict[str, Any] = Field(
        description="Map of field_key -> confirmed value to write to execution_data"
    )


class ConfirmResponse(BaseModel):
    conversation: ImageConversationResponse
    execution_data_updated: bool


# --- Tag & Batch Analyze ---


class TagImageRequest(BaseModel):
    parameter_tags: list[str] = Field(
        description="List of param_schema field keys this image relates to"
    )


class BatchAnalyzeResponse(BaseModel):
    total: int = Field(description="Number of unanalyzed images found")
    succeeded: int = Field(description="Number successfully analyzed")
    failed: int = Field(description="Number that failed analysis")
