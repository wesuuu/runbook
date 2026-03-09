"""Schemas for offline field mode endpoints."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Offline session ---

class OfflineSessionRequest(BaseModel):
    run_id: UUID = Field(description="Run to create offline session for")
    password: str = Field(description="User's password for verification")


class OfflineSessionResponse(BaseModel):
    offline_token: str
    expires_at: datetime
    run_id: UUID


# --- Prefetch ---

class RoleAssignmentPrefetch(BaseModel):
    id: UUID
    lane_node_id: str
    role_name: str
    user_id: UUID
    user_name: Optional[str] = None


class RunPrefetchResponse(BaseModel):
    """Everything needed for offline run execution."""
    run_id: UUID
    run_name: str
    run_status: str
    graph: dict[str, Any]
    execution_data: dict[str, Any]
    role_assignments: list[RoleAssignmentPrefetch]
    unit_op_definitions: dict[str, Any] = Field(
        default_factory=dict,
        description="Map of unit_op_id -> {name, category, param_schema}",
    )


# --- Sync queue ---

class SyncAction(BaseModel):
    action_type: str = Field(
        description="Type: 'image_upload', 'parameter_tag', 'manual_values'"
    )
    step_id: Optional[str] = Field(default=None, description="Step node ID")
    image_id: Optional[UUID] = Field(default=None, description="Image ID for tagging")
    image_data: Optional[str] = Field(
        default=None,
        description="Base64-encoded image data for upload",
    )
    image_filename: Optional[str] = Field(default="offline_capture.jpg")
    parameter_tags: Optional[list[str]] = Field(default=None)
    values: Optional[dict[str, Any]] = Field(
        default=None,
        description="Manual field values for a step",
    )


class SyncQueueRequest(BaseModel):
    actions: list[SyncAction] = Field(description="Queued offline actions")


class SyncActionResult(BaseModel):
    index: int
    action_type: str
    success: bool
    error: Optional[str] = None
    image_id: Optional[UUID] = None


class SyncQueueResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[SyncActionResult]


# --- Token revocation ---

class RevokeTokenRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for revocation")


class RevokedTokenResponse(BaseModel):
    jti: str
    user_id: UUID
    run_id: Optional[UUID]
    revoked_by: UUID
    reason: Optional[str]
    created_at: datetime
