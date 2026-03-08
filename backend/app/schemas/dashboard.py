from typing import Any, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


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
    active_runs: int = 0
    completed_this_week: int = 0
    planned_runs: int = 0
    # Org admin only
    team_members: Optional[int] = None
    active_projects: Optional[int] = None
    total_protocols: Optional[int] = None


class MyWork(BaseModel):
    needs_action: list[RunSummary] = []
    active_runs: list[RunSummary] = []
    recently_completed: list[RunSummary] = []
    planned_runs: list[RunSummary] = []


class DashboardResponse(BaseModel):
    my_work: MyWork
    activity: list[ActivityItem] = []
    counters: Counters
    is_admin: bool = False


class ActivityPage(BaseModel):
    items: list[ActivityItem]
    total: int
    offset: int
    limit: int
