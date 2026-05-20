"""Protocol, ProtocolRole, and UnitOpDefinition schemas (TD-0083)."""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, computed_field


# UnitOpDefinition Schemas
class UnitOpDefinitionBase(BaseModel):
    name: str
    category: str = "General"
    description: Optional[str] = None
    param_schema: Dict[str, Any] = Field(default_factory=dict)
    result_schema: Dict[str, Any] = Field(default_factory=dict)


class UnitOpDefinitionCreate(UnitOpDefinitionBase):
    project_id: Optional[UUID] = None


class UnitOpDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    param_schema: Optional[Dict[str, Any]] = None
    result_schema: Optional[Dict[str, Any]] = None


class UnitOpDefinitionResponse(UnitOpDefinitionBase):
    id: UUID
    organization_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    library_slug: Optional[str] = None  # F-0075: identifies JSON library origin
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope(self) -> Literal["global", "organization", "project"]:
        if self.project_id is not None:
            return "project"
        elif self.organization_id is not None:
            return "organization"
        return "global"

    class Config:
        from_attributes = True


# ProtocolRole Schemas
class ProtocolRoleBase(BaseModel):
    name: str
    color: str = "#94a3b8"
    sort_order: int = 0


class ProtocolRoleCreate(ProtocolRoleBase):
    pass


class ProtocolRoleUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class ProtocolRoleResponse(ProtocolRoleBase):
    id: UUID
    protocol_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Protocol Schemas
class ProtocolBase(BaseModel):
    name: str
    description: Optional[str] = None
    graph: Dict[str, Any] = Field(default_factory=dict)


class ProtocolCreate(ProtocolBase):
    project_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    # QA-0008: GxP metadata
    doc_number: Optional[str] = None
    effective_date: Optional[date] = None
    supersedes_date: Optional[date] = None
    purpose: Optional[str] = None
    scope: Optional[str] = None
    references: Optional[str] = None
    definitions: Optional[str] = None

    class Config:
        from_attributes = True


class ProtocolUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    graph: Optional[Dict[str, Any]] = None
    # QA-0008: GxP metadata
    doc_number: Optional[str] = None
    effective_date: Optional[date] = None
    supersedes_date: Optional[date] = None
    purpose: Optional[str] = None
    scope: Optional[str] = None
    references: Optional[str] = None
    definitions: Optional[str] = None


class ProtocolResponse(ProtocolBase):
    id: UUID
    project_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    status: str = "DRAFT"
    version_number: int = 0
    # Highest is_draft version_number above version_number, when an
    # unpublished draft exists. None if the only versions are published.
    latest_draft_version_number: Optional[int] = None
    is_tour_sample: bool = False
    requires_approval: bool = False
    created_by_id: Optional[UUID] = None
    approved_by_id: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    latest_signature_statement: Optional[str] = None
    latest_approval_comment: Optional[str] = None
    roles: List[ProtocolRoleResponse] = []
    # QA-0008: GxP metadata
    doc_number: Optional[str] = None
    effective_date: Optional[date] = None
    supersedes_date: Optional[date] = None
    purpose: Optional[str] = None
    scope: Optional[str] = None
    references: Optional[str] = None
    definitions: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Protocol Version Schemas
class ProtocolVersionListItem(BaseModel):
    id: UUID
    version_number: int
    name: str
    description: Optional[str] = None
    change_summary: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    is_draft: bool = False

    class Config:
        from_attributes = True


class ProtocolVersionResponse(ProtocolVersionListItem):
    protocol_id: UUID
    graph: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    created_by_id: Optional[UUID] = None

    class Config:
        from_attributes = True


class PublishDraftRequest(BaseModel):
    """Optional metadata captured when promoting a draft version to published."""

    description: Optional[str] = None
    change_summary: Optional[str] = None


# Protocol Approval Schemas


class DesignateApprovalRequest(BaseModel):
    """Request body for POST /protocols/{id}/designate-approval."""

    requires_approval: bool


class SubmitForApprovalRequest(BaseModel):
    """Request body for POST /protocols/{id}/submit-for-approval."""

    requested_user_ids: List[UUID]


class ApproveProtocolRequest(BaseModel):
    """Request body for POST /protocols/{id}/approve."""

    comment: Optional[str] = None
    signature_statement: Optional[str] = None


class RejectProtocolRequest(BaseModel):
    """Request body for POST /protocols/{id}/reject."""

    comment: str = Field(..., min_length=1)
    signature_statement: Optional[str] = None


class ApprovalActorRef(BaseModel):
    """Minimal reference to the user who acted on a protocol approval.

    Kept as a shared type so the awaiting-approval list endpoint can
    surface submitter identity without leaking the full User schema.
    """

    id: UUID
    name: str
    email: str


class AwaitingApprovalItem(BaseModel):
    """Single entry in GET /protocols/awaiting-my-approval response."""

    protocol_id: UUID
    name: str
    project_id: Optional[UUID] = None
    project_name: Optional[str] = None
    organization_id: UUID
    submitted_at: Optional[datetime] = None
    submitted_by: Optional[ApprovalActorRef] = None


class GraphPayload(BaseModel):
    graph: Dict[str, Any] = Field(default_factory=dict)


# ── Protocol Import Schemas ─────────────────────────────────────────


class StepProposalSchema(BaseModel):
    name: str
    description: str = ""
    category: str = "General"
    duration_min: int = 30
    params: Dict[str, Any] = Field(default_factory=dict)
    param_schema: Dict[str, Any] = Field(default_factory=dict)
    role: Optional[str] = None
    matched_unit_op_id: Optional[str] = None
    matched_unit_op_name: Optional[str] = None
    is_new: bool = False


class ProtocolImportProposalResponse(BaseModel):
    protocol_name: str
    protocol_description: str = ""
    steps: List[StepProposalSchema]
    matched_count: int
    unmatched_count: int
    source_filename: str
    source_text_preview: str = ""


class ProtocolRefineRequest(BaseModel):
    graph: Dict[str, Any]
    instruction: str


class ProtocolImportFinalizeRequest(BaseModel):
    protocol_name: str
    protocol_description: str = ""
    steps: List[StepProposalSchema]
    project_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    source_filename: str = ""
