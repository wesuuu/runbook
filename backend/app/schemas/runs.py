"""Experiment, Run, and related schemas (TD-0083)."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ExperimentRunSummary(BaseModel):
    """A child run reduced to what the index needs (F-0093)."""

    status: str
    outcome: Optional[str] = None


class ExperimentOwner(BaseModel):
    """The experiment's creator, for the index owner avatar (F-0093)."""

    id: UUID
    name: str
    initials: str


class ExperimentSummary(BaseModel):
    """Lightweight per-experiment row for the org-wide index (F-0093)."""

    id: UUID
    slug: str
    name: str
    objective: Optional[str] = None
    project_id: UUID
    project_slug: str
    project_name: str
    lifecycle_status: str
    run_count: int
    run_summaries: List[ExperimentRunSummary] = Field(default_factory=list)
    owner: Optional[ExperimentOwner] = None
    created_at: datetime
    updated_at: datetime


EXPERIMENT_NAME_MAX = 200
EXPERIMENT_DESCRIPTION_MAX = 5000


def _validated_name(value: str) -> str:
    """Reject blank/whitespace-only names; both schemas enforce this."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("Name must not be blank")
    return stripped


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=EXPERIMENT_NAME_MAX)
    project_id: UUID
    description: Optional[str] = Field(
        default=None, max_length=EXPERIMENT_DESCRIPTION_MAX
    )
    objective: Optional[str] = None
    success_criteria: List[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _validated_name(v)


class ExperimentUpdate(BaseModel):
    # `status` is intentionally absent — lifecycle status is derived, not set
    # (F-0093 §3.3). `extra="forbid"` turns a stale `{"status": ...}` write
    # into an explicit 422 instead of silently dropping it.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None, min_length=1, max_length=EXPERIMENT_NAME_MAX
    )
    description: Optional[str] = Field(
        default=None, max_length=EXPERIMENT_DESCRIPTION_MAX
    )
    content: Optional[Dict[str, Any]] = None
    objective: Optional[str] = None
    success_criteria: Optional[List[str]] = None
    conclusion: Optional[str] = Field(default=None, max_length=65536)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _validated_name(v)


class ConclusionUnlockRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)


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
    key_result_label: Optional[str] = Field(default=None, max_length=120)
    key_result_value: Optional[float] = None
    key_result_unit: Optional[str] = Field(default=None, max_length=32)

    @field_validator("key_result_value")
    @classmethod
    def _bound_key_result(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        # Reject NaN / Inf and bound magnitude to Numeric(14,6) integer digits.
        if not (v == v):  # NaN
            raise ValueError("key_result_value cannot be NaN")
        if v in (float("inf"), float("-inf")):
            raise ValueError("key_result_value cannot be infinite")
        if abs(v) >= 10**14:
            raise ValueError("key_result_value magnitude exceeds 14 integer digits")
        return v

    @model_validator(mode="after")
    def _key_result_pairing(self) -> "RunUpdate":
        label_present = self.key_result_label is not None
        value_present = self.key_result_value is not None
        if label_present != value_present:
            raise ValueError(
                "key_result_label and key_result_value must be set together"
            )
        return self


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
    slug: str
    project_slug: str
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
    key_result_label: Optional[str] = None
    key_result_value: Optional[float] = None
    key_result_unit: Optional[str] = None
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
    slug: str
    project_slug: str
    name: str
    description: Optional[str] = None
    objective: Optional[str] = None
    success_criteria: List[str] = Field(default_factory=list)
    created_by_id: Optional[UUID] = None
    conclusion: Optional[str] = None
    conclusion_locked_at: Optional[datetime] = None
    conclusion_locked_by_id: Optional[UUID] = None
    conclusion_locked_by_name: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)
    # `status` is the stored archived/not-archived flag (it keeps a default for
    # back-compat with callers that build the response by hand). `lifecycle_status`
    # is *derived* from child runs at read time — every handler must supply it,
    # so it is intentionally required (no default) to fail loudly if one forgets.
    status: str = ExperimentStatus.DRAFT
    lifecycle_status: str
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
