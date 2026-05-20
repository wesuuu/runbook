from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

# --- Request schemas ---


class ChatSessionCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    context_document_ids: Optional[list[UUID]] = None


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    skill_id: Optional[str] = None
    current_route: Optional[str] = Field(default=None, max_length=512)


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
    active_turn_heartbeat_at: Optional[datetime] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def turn_in_progress(self) -> bool:
        """True while a chat turn is actively running for this session (BUG-005)."""
        # Imported lazily inside the property: a module-level import would
        # cycle (app.services.ai/__init__ eagerly imports send_message, which
        # imports this schema module).
        from app.services.ai.turn_status import is_turn_in_progress

        return is_turn_in_progress(self.active_turn_heartbeat_at)


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


class ChatSkillResponse(BaseModel):
    name: str
    description: str
    icon: str


class ChatSkillListResponse(BaseModel):
    skills: list[ChatSkillResponse]


class ChatConfigResponse(BaseModel):
    max_message_length: int
    model_name: str
    context_window: int
    compaction_threshold: float


class NotifyAdminResponse(BaseModel):
    message: str
    user_notified_at: datetime


# --- External protocol approval (F-0084) ---


class ExternalProtocolStepPreview(BaseModel):
    """Single procedure step shown on the approval card's expandable list.

    Slimmer than ``ExternalProtocolStep`` — only the fields the card needs.
    """

    text: str
    duration_min: Optional[int] = None


class ExternalProtocolPayloadPreview(BaseModel):
    """Compact preview of an ExternalProtocolPayload for the approval card."""

    title: str
    source_url: str
    project_name: Optional[str] = None
    step_count: int
    duration_min_total: Optional[int] = None
    license: str = "CC BY-SA 3.0"
    deviations: list[str] = []
    steps: list[ExternalProtocolStepPreview] = []


class ApprovalRequiredEvent(BaseModel):
    """SSE event yielded when agent.run terminates on a deferred tool call."""

    type: Literal["approval_required"]
    tool_call_id: str
    tool_name: str
    title: str
    source_url: str
    payload_preview: ExternalProtocolPayloadPreview
    assistant_message_id: UUID


class ApprovalRequest(BaseModel):
    """Body for ``POST /sessions/{id}/messages/approve``.

    The user can edit the procedure inline on the approval card before
    approving. ``edited_steps`` is the final step list they intend to draft
    from (replaces the original cached payload's ``steps``). ``deviations``
    is a human-readable audit/display list derived from a diff of the
    original vs. edited steps (e.g. ``"Added step: ..."``, ``"Removed step:
    ..."``, ``"Edited step: ~~old~~ new"``). Both ignored on rejection.
    """

    tool_call_id: str
    approved: bool
    edited_steps: list[ExternalProtocolStepPreview] | None = None
    deviations: list[str] | None = None
