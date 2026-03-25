from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


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


class ProcessingProgress(BaseModel):
    stage: str = ""  # extracting, chunking, embedding, enriching, classifying
    stage_label: str = ""  # human-readable label
    current: int = 0
    total: int = 0
    percent: int = 0


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
    has_page_images: bool = False


class ImportUrlRequest(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
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
