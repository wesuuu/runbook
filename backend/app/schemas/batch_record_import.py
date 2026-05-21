"""Request/response schemas for batch record import API."""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.jobs import ProcessingProgress

# ── Extraction response (read-only, from AI) ────────────────────────


class ExtractedParameterValueResponse(BaseModel):
    field_label: str
    value: Any
    unit: Optional[str] = None
    confidence: float
    source_page: Optional[int] = None


class ExtractedTimestampResponse(BaseModel):
    value: str
    label: str
    confidence: float


class ExtractedSignatureResponse(BaseModel):
    initials_or_name: str
    role: Optional[str] = None
    confidence: float


class ExtractedDeviationResponse(BaseModel):
    description: str
    severity: Optional[str] = None
    step_reference: Optional[str] = None
    confidence: float


class ExtractedStepResponse(BaseModel):
    step_name: str
    step_number: Optional[int] = None
    description: str = ""
    parameters: List[ExtractedParameterValueResponse] = []
    timestamps: List[ExtractedTimestampResponse] = []
    signatures: List[ExtractedSignatureResponse] = []
    deviations: List[ExtractedDeviationResponse] = []
    notes: str = ""
    confidence: float
    source_page: Optional[int] = None


class ExtractionResponse(BaseModel):
    document_title: str = ""
    batch_id: Optional[str] = None
    product_name: Optional[str] = None
    date: Optional[str] = None
    steps: List[ExtractedStepResponse] = []
    general_notes: List[str] = []
    overall_confidence: float


# ── Step mapping response (from LLM matching) ───────────────────────


class ParamMappingResponse(BaseModel):
    extracted_param_index: int
    extracted_label: str
    extracted_value: Any = None
    extracted_unit: Optional[str] = None
    schema_field_key: str
    schema_field_label: str
    confidence: float


class StepMappingResponse(BaseModel):
    extracted_step_index: int
    extracted_step_name: str
    protocol_step_id: str
    protocol_step_name: str
    score: float
    param_mappings: List[ParamMappingResponse] = []


# ── Import session response ──────────────────────────────────────────


class BatchRecordImportResponse(BaseModel):
    import_id: UUID
    status: str
    extraction: Optional[ExtractionResponse] = None
    step_mappings: List[StepMappingResponse] = []
    progress: Optional[ProcessingProgress] = None
    created_run_id: Optional[UUID] = None
    error_message: Optional[str] = None
    page_count: Optional[int] = None
    original_filename: str = ""
    protocol_id: UUID
    created_at: datetime


# ── Finalize request ─────────────────────────────────────────────────


class FinalizedValue(BaseModel):
    schema_field_key: str
    value: Any
    accepted: bool
    edited: bool = False
    original_value: Any = None
    original_confidence: float = 0.0


class FinalizedStepMapping(BaseModel):
    protocol_step_id: str
    values: List[FinalizedValue] = []
    notes: str = ""
    na: bool = False
    na_reason: str = ""
    timestamps: List[ExtractedTimestampResponse] = []
    signatures: List[ExtractedSignatureResponse] = []
    deviations: List[ExtractedDeviationResponse] = []


class BatchRecordFinalizeRequest(BaseModel):
    protocol_id: UUID
    run_name: str = Field(min_length=1, max_length=200)
    step_mappings: List[FinalizedStepMapping]


class BatchRecordFinalizeResponse(BaseModel):
    run_id: UUID
    run_slug: str
    run_name: str
    project_slug: str
    import_id: UUID
    status: str = "FINALIZED"
