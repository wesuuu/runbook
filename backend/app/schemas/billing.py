from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SubscriptionStateResponse(BaseModel):
    tier: str
    status: Optional[str]
    trial_end: Optional[datetime]
    days_remaining_in_trial: Optional[int]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    has_payment_method: bool
    is_locked_out: bool
    seat_count: int
    seat_limit: Optional[int]
    seat_limit_exceeded: bool

    model_config = ConfigDict(from_attributes=True)


class PortalSessionRequest(BaseModel):
    return_url: Optional[str] = None


class PortalSessionResponse(BaseModel):
    url: str
