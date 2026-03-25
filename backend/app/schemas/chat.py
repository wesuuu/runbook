from typing import Any, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Request schemas ---


class ChatSessionCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    context_document_ids: Optional[list[UUID]] = None


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class ChatSessionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


# --- Response schemas ---


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    metadata_: Optional[dict[str, Any]] = Field(None, alias="metadata_")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    org_id: UUID
    title: str
    status: str
    context_document_ids: Optional[list[Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[ChatMessageResponse] = []


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]
    total: int


class ChatSourceReference(BaseModel):
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    page_number: Optional[int] = None
    score: float
    snippet: str


class ChatCompletionResponse(BaseModel):
    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
    sources: list[ChatSourceReference] = []


class GenerateProtocolRequest(BaseModel):
    project_id: UUID
    protocol_name: Optional[str] = Field(None, max_length=255)


class GenerateProtocolResponse(BaseModel):
    protocol_id: UUID
    protocol_name: str
    project_id: UUID
