"""Experiment, Run, and related schemas (TD-0083)."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# Experiment Schemas
class ExperimentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


ALLOWED_EXPERIMENT_NOTE_FLAGS = {"anomaly", "observation"}


class ExperimentNote(BaseModel):
    """A single experiment-level note (stored in Experiment.notes JSONB)."""

    id: UUID
    content: str
    author_id: UUID
    author_name: str = "Unknown"
    created_at: datetime
    flags: list[str] = Field(default_factory=list)


class ExperimentNoteCreate(BaseModel):
    """Request body for adding an experiment-level note."""

    content: str = Field(..., min_length=1, max_length=10000)
    flags: list[str] = Field(default_factory=list)

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, v: list[str]) -> list[str]:
        invalid = set(v) - ALLOWED_EXPERIMENT_NOTE_FLAGS
        if invalid:
            raise ValueError(
                f"Invalid flags: {invalid}. "
                f"Allowed: {ALLOWED_EXPERIMENT_NOTE_FLAGS}"
            )
        return v


class ExperimentNoteListResponse(BaseModel):
    items: list[ExperimentNote] = []


class ExperimentCreate(BaseModel):
    name: str
    project_id: UUID
    description: Optional[str] = None


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    status: Optional[ExperimentStatus] = None


# Run Schemas
class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EDITED = "EDITED"
    ARCHIVED = "ARCHIVED"


# --- Run Notes & Attachments ---

ALLOWED_NOTE_FLAGS = {"anomaly"}


class RunNote(BaseModel):
    """A single run-level note (domain object, stored in Run.notes JSONB)."""

    id: UUID
    content: str
    author_id: UUID
    author_name: str = "Unknown"
    created_at: datetime
    run_status: str
    flags: list[str] = Field(default_factory=list)


class RunNoteCreate(BaseModel):
    """Request body for adding a run-level note."""

    content: str = Field(..., min_length=1, max_length=10000)
    flags: list[str] = Field(default_factory=list)

    @field_validator("flags")
    @classmethod
    def validate_flags(cls, v: list[str]) -> list[str]:
        invalid = set(v) - ALLOWED_NOTE_FLAGS
        if invalid:
            raise ValueError(f"Invalid flags: {invalid}. Allowed: {ALLOWED_NOTE_FLAGS}")
        return v


class RunNoteListResponse(BaseModel):
    items: list[RunNote] = []


class RunAttachment(BaseModel):
    """A single file attachment (domain object, stored in Run.attachments JSONB)."""

    id: UUID
    file_path: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: UUID
    uploaded_at: datetime
    step_id: Optional[str] = None
    run_status: str
    deleted: bool = False


class RunAttachmentListResponse(BaseModel):
    items: list[RunAttachment] = []


# --- Run ---


class RunBase(BaseModel):
    name: str
    status: RunStatus = RunStatus.PLANNED
    graph: Dict[str, Any] = Field(default_factory=dict)
    execution_data: Dict[str, Any] = Field(default_factory=dict)


class RunCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None
    protocol_version_number: Optional[int] = None
    experiment_id: Optional[UUID] = None
    overrides: Optional["RunOverrides"] = None
    # F-0086
    produces_lot: bool = False
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None
    # F-0080: GLP sign-off reviewers
    study_director_id: Optional[UUID] = None
    qau_reviewer_id: Optional[UUID] = None


class RunUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[RunStatus] = None
    graph: Optional[Dict[str, Any]] = None
    execution_data: Optional[Dict[str, Any]] = None
    # F-0086
    produces_lot: Optional[bool] = None
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None


class RunStateUpdate(BaseModel):
    """Body for PATCH /runs/{id}/state (F-0087).

    ``state`` drives a run-level lifecycle transition (PLANNED -> ACTIVE,
    ACTIVE/COMPLETED -> EDITED, etc.). ``edit_reasons`` and
    ``execution_data_delta`` are the GLP audit-trail inputs when entering
    the EDITED state: every modified step must carry a non-blank reason.
    """

    state: Optional[str] = None
    edit_reasons: Optional[Dict[str, str]] = None
    execution_data_delta: Optional[Dict[str, Dict[str, Any]]] = None


class RunStepStateUpdate(BaseModel):
    """Body for PATCH /runs/{id}/steps/{step_id} (F-0087)."""

    status: str


class RunResponse(RunBase):
    id: UUID
    project_id: UUID
    protocol_id: Optional[UUID]
    experiment_id: Optional[UUID] = None
    started_by_id: Optional[UUID] = None
    created_by_id: Optional[UUID] = None
    # F-0080: GLP sign-off reviewers
    study_director_id: Optional[UUID] = None
    qau_reviewer_id: Optional[UUID] = None
    is_strict: bool = False
    notes: list[RunNote] = Field(default_factory=list)
    attachments: list[RunAttachment] = Field(default_factory=list)
    # F-0086
    produces_lot: bool = False
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None
    # F-0087 GLP lifecycle
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    outcome_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Run Overrides (F-0081) ---


class NodeOverrides(BaseModel):
    """Sparse overrides for a single unit-op node in a run snapshot.

    All fields optional. `params` is a sparse dict (only the keys being
    overridden); `equipment`, `paramSchema`, and `description` are full
    replacements. None means "inherit from protocol default".
    """

    params: Optional[Dict[str, Any]] = None
    equipment: Optional[List[Dict[str, Any]]] = None
    paramSchema: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class RunOverrides(BaseModel):
    """Per-run edits to a protocol snapshot, keyed by unit-op node id."""

    nodes: Dict[str, NodeOverrides] = Field(default_factory=dict)


class SuggestLotNumberRequest(BaseModel):
    project_id: UUID


class SuggestLotNumberResponse(BaseModel):
    lot_number: str


class CheckLotNumberResponse(BaseModel):
    exists: bool
    count: int


RunCreate.model_rebuild()


class ExperimentResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)
    status: str = ExperimentStatus.DRAFT
    notes: list[ExperimentNote] = Field(default_factory=list)
    runs: list[RunResponse] = Field(default_factory=list)
    run_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Run Role Assignment Schemas
class RunRoleAssignmentBase(BaseModel):
    lane_node_id: str
    role_name: str
    user_id: UUID


class RunRoleAssignmentCreate(RunRoleAssignmentBase):
    pass


class RunRoleAssignmentResponse(RunRoleAssignmentBase):
    id: UUID
    run_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunRoleAssignmentListResponse(BaseModel):
    items: List[RunRoleAssignmentResponse] = []


RUN_OUTCOMES = ("COMPLETED_NORMAL", "COMPLETED_WITH_DEVIATIONS", "ABORTED")


class RunCompleteRequest(BaseModel):
    outcome: str
    outcome_notes: Optional[str] = None

    @field_validator("outcome")
    @classmethod
    def _check_outcome(cls, v: str) -> str:
        if v not in RUN_OUTCOMES:
            raise ValueError(f"outcome must be one of {RUN_OUTCOMES}")
        return v


class RunReopenRequest(BaseModel):
    reason: str = Field(min_length=1)


class RunReviewersUpdate(BaseModel):
    study_director_id: Optional[UUID] = None
    qau_reviewer_id: Optional[UUID] = None
