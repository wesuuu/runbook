from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class DocumentResponse(BaseModel):
    id: UUID
    org_id: UUID
    project_id: Optional[UUID] = None
    uploaded_by_id: UUID
    title: str
    slug: str
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
    chunk_count: int = 0
    embedded_count: int = 0
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


class ProcessingJobAudit(BaseModel):
    id: UUID
    job_type: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    attempts: int = 0
    error_message: Optional[str] = None
    stage: Optional[str] = None
    stage_label: Optional[str] = None
    current: Optional[int] = None
    total: Optional[int] = None
    percent: Optional[int] = None


class ProcessingAuditResponse(BaseModel):
    document_id: UUID
    document_status: str
    chunk_count: int = 0
    embedded_count: int = 0
    jobs: List[ProcessingJobAudit] = []


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
    document_slug: str
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


class RefineCompleteRequest(BaseModel):
    reopen: bool = False
