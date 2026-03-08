from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, ConfigDict, Field


# --- Channel Schemas ---

class ChannelCreate(BaseModel):
    name: str
    channel_type: str  # EMAIL, SLACK, TEAMS, DISCORD, WEBHOOK, CONSOLE
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class ChannelResponse(BaseModel):
    id: UUID
    org_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    name: str
    channel_type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChannelTestResult(BaseModel):
    status: str  # SENT or FAILED
    detail: str


# --- Subscription Schemas ---

class SubscriptionCreate(BaseModel):
    event_type: str
    enabled: bool = True


class SubscriptionResponse(BaseModel):
    id: UUID
    channel_id: UUID
    event_type: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- In-App Notification Schemas ---

class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    title: str
    message: str
    read_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse] = []
    total: int = 0


class UnreadCountResponse(BaseModel):
    count: int


# --- Delivery Schemas ---

class DeliveryResponse(BaseModel):
    id: UUID
    notification_id: Optional[UUID] = None
    channel_id: UUID
    event_type: str
    recipient_info: Dict[str, Any] = Field(default_factory=dict)
    status: str
    status_detail: Optional[str] = None
    attempts: int
    next_retry_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryListResponse(BaseModel):
    items: List[DeliveryResponse] = []
    total: int = 0


# --- User Notification Preferences ---

class NotificationPreferences(BaseModel):
    in_app: bool = True
    email: bool = True
    mute_until: Optional[datetime] = None
