"""GLP Signoff schemas (TD-0083)."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

# ── GLP Signoff Schemas ─────────────────────────────────────────────

GLP_ROLES = ("SPONSOR", "STUDY_DIRECTOR", "QAU", "OPERATOR")
GLP_ACTIONS = ("APPROVED", "REJECTED", "REQUESTED_CHANGES")


class GlpSignoffCreate(BaseModel):
    role: str
    action: str
    attestation: Optional[str] = None
    signature_image_path: Optional[str] = None
    signoff_request_id: Optional[UUID] = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in GLP_ROLES:
            raise ValueError(f"role must be one of {GLP_ROLES}")
        return v

    @field_validator("action")
    @classmethod
    def _check_action(cls, v: str) -> str:
        if v not in GLP_ACTIONS:
            raise ValueError(f"action must be one of {GLP_ACTIONS}")
        return v


class GlpSignoffResponse(BaseModel):
    id: UUID
    protocol_id: Optional[UUID]
    run_id: Optional[UUID]
    role: str
    action: str
    signer_id: UUID
    attestation: Optional[str]
    signed_at: datetime
    signature_image_path: Optional[str]
    signoff_request_id: Optional[UUID]
    invalidated_at: Optional[datetime]
    invalidated_reason: Optional[str]
    invalidated_by_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def signature_image_url(self) -> Optional[str]:
        if not self.signature_image_path:
            return None
        return f"/signoffs/{self.id}/signature"
