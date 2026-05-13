from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class DocumentResponse(BaseModel):
    id: UUID
    org_id: UUID
    project_id: Optional[UUID] = None
    uploaded_by_id: UUID
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_path: str
    status: str
    page_count: Optional[int] = None
    tags: List[Any] = []
    doc_metadata: dict[str, Any] = {}
    error_message: Optional[str] = None
    source_url: Optional[str] = None
    processing_started_at: Optional[datetime] = None
    structure_metadata: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    can_delete: bool = False
    source_format: Optional[str] = None
    refinement_status: Optional[str] = None
    refinement_flags: Optional[List[Any]] = None
    refined_by_id: Optional[UUID] = None
    refined_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int


class DocumentChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    token_count: int
    page_number: Optional[int] = None
    chunk_metadata: dict[str, Any] = {}
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


from app.schemas.jobs import ProcessingProgress  # noqa: E402 — re-exported


class TOCEntry(BaseModel):
    level: int
    text: str
    page_number: Optional[int] = None
    chunk_index: Optional[int] = None


class DocumentDetailResponse(DocumentResponse):
    chunk_count: int = 0
    chunks_preview: List[DocumentChunkResponse] = []
    processing_progress: Optional[ProcessingProgress] = None
    table_of_contents: List[TOCEntry] = []


class ImportUrlRequest(BaseModel):
    url: HttpUrl
    title: Optional[str] = Field(None, max_length=150)
    project_id: Optional[UUID] = None


class SearchResultItem(BaseModel):
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    content: str
    highlighted_content: Optional[str] = None
    page_number: Optional[int] = None
    score: float


class SearchResultGroup(BaseModel):
    document_id: UUID
    document_title: str
    match_count: int
    best_score: float
    best_chunk: SearchResultItem


class SearchResponse(BaseModel):
    query: str
    items: List[SearchResultGroup]
    total: int
    search_mode: str  # "hybrid", "semantic", "keyword"


class MarkdownPayload(BaseModel):
    markdown: str


class RefineAiRequest(BaseModel):
    scope: str = Field(..., pattern="^(selection|block|document)$")
    selection_markdown: str
    instruction: str
    surrounding_context_markdown: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None

    @field_validator("bbox")
    @classmethod
    def _bbox_len(cls, v):
        if v is None:
            return v
        if len(v) != 4:
            raise ValueError("bbox must be [x0,y0,x1,y1]")
        return v


class RefineAiResponse(BaseModel):
    suggested_markdown: str
    model_used: str


class RefineCompleteRequest(BaseModel):
    reopen: bool = False
