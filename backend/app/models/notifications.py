import uuid
from enum import Enum
from typing import Optional, Any

from sqlalchemy import (
    String, Integer, ForeignKey, Boolean, CheckConstraint, Index, Text,
    DateTime,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base
from app.models.mixins import UUIDMixin, TimestampMixin


class ChannelType(str, Enum):
    EMAIL = "EMAIL"
    SLACK = "SLACK"
    TEAMS = "TEAMS"
    DISCORD = "DISCORD"
    WEBHOOK = "WEBHOOK"
    CONSOLE = "CONSOLE"


class NotificationEventType(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    RUN_COMPLETED = "RUN_COMPLETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    ROLE_UNASSIGNED = "ROLE_UNASSIGNED"
    ROLE_REASSIGNED = "ROLE_REASSIGNED"
    INVITE_SENT = "INVITE_SENT"
    INVITE_ACCEPTED = "INVITE_ACCEPTED"
    PROTOCOL_APPROVED = "PROTOCOL_APPROVED"
    PROTOCOL_REVERTED = "PROTOCOL_REVERTED"
    STEP_DEVIATION = "STEP_DEVIATION"
    PENDING_IMAGE_ANALYSIS = "PENDING_IMAGE_ANALYSIS"
    OFFLINE_SYNC_PENDING = "OFFLINE_SYNC_PENDING"
    OFFLINE_VALUE_DISCREPANCY = "OFFLINE_VALUE_DISCREPANCY"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


class NotificationChannel(Base, UUIDMixin, TimestampMixin):
    """A configured delivery channel, owned by either an org or a user."""
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint(
            "(org_id IS NOT NULL AND user_id IS NULL) OR "
            "(org_id IS NULL AND user_id IS NOT NULL)",
            name="ck_channel_scope",
        ),
        Index("ix_notif_channels_org", "org_id"),
        Index("ix_notif_channels_user", "user_id"),
    )

    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    channel_type: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "app.models.iam.Organization"
    )
    user: Mapped[Optional["User"]] = relationship(
        "app.models.iam.User"
    )
    subscriptions: Mapped[list["NotificationSubscription"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class NotificationSubscription(Base, UUIDMixin, TimestampMixin):
    """Maps an event type to a channel — 'send RUN_STARTED to this Slack channel'."""
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        Index(
            "ix_notif_sub_lookup", "channel_id", "event_type", unique=True
        ),
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Relationships
    channel: Mapped["NotificationChannel"] = relationship(
        back_populates="subscriptions"
    )


class Notification(Base, UUIDMixin, TimestampMixin):
    """In-app notification record for a specific user."""
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_user_created", "user_id", "created_at"),
        Index("ix_notif_user_unread", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[Optional[Any]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("app.models.iam.User")


class NotificationDelivery(Base, UUIDMixin, TimestampMixin):
    """Tracks every external dispatch attempt for observability and retries."""
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notif_del_status", "status", "next_retry_at"),
        Index("ix_notif_del_channel", "channel_id", "created_at"),
    )

    notification_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    recipient_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, default=DeliveryStatus.PENDING, server_default="PENDING",
        nullable=False,
    )
    status_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    next_retry_at: Mapped[Optional[Any]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    notification: Mapped[Optional["Notification"]] = relationship()
    channel: Mapped["NotificationChannel"] = relationship()
