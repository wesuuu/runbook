from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BlockerReason(BaseModel):
    code: str    # "LANES_UNASSIGNED" | "EQUIPMENT_CALIBRATION_OVERDUE"
    label: str   # human "why" tag, plain text (HTML-escaped on render)


class RunSummary(BaseModel):
    id: UUID
    name: str
    project_id: UUID
    project_name: str
    protocol_name: Optional[str] = None
    status: str
    role_name: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    updated_at: datetime
    blockers: list[BlockerReason] = []


class ActivityItem(BaseModel):
    id: UUID
    action: str
    entity_type: str
    entity_id: UUID
    entity_name: Optional[str] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    changes: dict[str, Any] = {}
    created_at: datetime


class Counters(BaseModel):
    runs_blocked: int = 0       # user's blocked PLANNED runs
    calibrations_due: int = 0   # org overdue + due-soon equipment
    signoffs_pending: int = 0   # protocol approvals + involved-run sign-offs
    active_runs: int = 0        # user's ACTIVE runs


class MyWork(BaseModel):
    needs_action: list[RunSummary] = []
    in_progress: list[RunSummary] = []
    planned: list[RunSummary] = []


class CalibrationItem(BaseModel):
    equipment_id: UUID
    name: str
    site_name: Optional[str] = None
    next_calibration_date: Optional[date] = None
    state: str   # "overdue" | "due_soon"


class CalibrationStatus(BaseModel):
    overdue: list[CalibrationItem] = []
    due_soon: list[CalibrationItem] = []


class SignoffItem(BaseModel):
    kind: str              # "protocol" | "run"
    entity_id: UUID
    name: str
    project_name: Optional[str] = None
    detail: Optional[str] = None
    waiting_since: Optional[datetime] = None  # sort key — oldest-waiting first


class LabStatus(BaseModel):
    calibration: CalibrationStatus = Field(default_factory=CalibrationStatus)
    awaiting_signoff: list[SignoffItem] = []


class DashboardResponse(BaseModel):
    my_work: MyWork
    lab_status: LabStatus
    activity: list[ActivityItem] = []
    counters: Counters


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    total: int
    offset: int
    limit: int


# Deprecated stubs for backward compatibility with dashboard.py endpoint
# These are imported by the old endpoint but will be removed in Task 9
class CompletionTrendItem(BaseModel):
    date: str
    count: int


class PendingAnalyses(BaseModel):
    total_images: int = 0
    total_runs: int = 0
