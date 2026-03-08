"""Core dispatch engine: routes notification events to channels and tracks delivery."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notifications import (
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
    DeliveryStatus,
)
from app.services.notifications.channels import get_channel
from app.services.notifications.channels.base import (
    FormattedMessage, TransientError, PermanentError,
)

logger = logging.getLogger("notifications.dispatcher")

MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 600]  # seconds


async def dispatch_event(
    db: AsyncSession,
    event_type: str,
    org_id: UUID,
    recipients: list[UUID],
    message_personal: FormattedMessage,
    message_broadcast: FormattedMessage,
) -> list[NotificationDelivery]:
    """Fan out an event to all subscribed channels (org + per-user).

    Args:
        db: Database session.
        event_type: The NotificationEventType value.
        org_id: Organization for org-level channel lookup.
        recipients: User IDs who should receive user-level deliveries.
        message_personal: Message formatted from the recipient's perspective.
        message_broadcast: Message formatted for broadcast channels.

    Returns:
        List of created NotificationDelivery records.
    """
    deliveries: list[NotificationDelivery] = []

    # 1. Org-level channels subscribed to this event
    org_channels = await _get_subscribed_channels(
        db, event_type, org_id=org_id
    )
    for channel_model in org_channels:
        delivery = await _dispatch_to_channel(
            db, channel_model, message_broadcast, event_type
        )
        deliveries.append(delivery)

    # 2. User-level channels for each recipient
    for user_id in recipients:
        user_channels = await _get_subscribed_channels(
            db, event_type, user_id=user_id
        )
        for channel_model in user_channels:
            msg = FormattedMessage(
                event_type=message_personal.event_type,
                title=message_personal.title,
                body=message_personal.body,
                recipient=message_personal.recipient,
                url=message_personal.url,
            )
            delivery = await _dispatch_to_channel(
                db, channel_model, msg, event_type
            )
            deliveries.append(delivery)

    return deliveries


async def retry_pending(db: AsyncSession) -> int:
    """Retry deliveries that are due. Returns count of retried deliveries."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.status == DeliveryStatus.RETRYING)
        .where(NotificationDelivery.next_retry_at <= now)
        .limit(50)
    )
    result = await db.execute(stmt)
    pending = result.scalars().all()

    count = 0
    for delivery in pending:
        channel_model = await db.get(NotificationChannel, delivery.channel_id)
        if not channel_model or not channel_model.enabled:
            delivery.status = DeliveryStatus.FAILED
            delivery.status_detail = "Channel disabled or deleted"
            continue

        channel = get_channel(channel_model.channel_type, channel_model.config)
        msg = FormattedMessage(
            event_type=delivery.event_type,
            title="(retry)",
            body="",
            recipient=delivery.recipient_info.get("recipient", "unknown"),
        )

        await _execute_send(db, delivery, channel, msg)
        count += 1

    await db.flush()
    return count


async def _get_subscribed_channels(
    db: AsyncSession,
    event_type: str,
    org_id: UUID | None = None,
    user_id: UUID | None = None,
) -> list[NotificationChannel]:
    """Find enabled channels with an active subscription for this event."""
    stmt = (
        select(NotificationChannel)
        .join(NotificationSubscription)
        .where(NotificationChannel.enabled == True)
        .where(NotificationSubscription.event_type == event_type)
        .where(NotificationSubscription.enabled == True)
    )
    if org_id is not None:
        stmt = stmt.where(NotificationChannel.org_id == org_id)
    if user_id is not None:
        stmt = stmt.where(NotificationChannel.user_id == user_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _dispatch_to_channel(
    db: AsyncSession,
    channel_model: NotificationChannel,
    message: FormattedMessage,
    event_type: str,
) -> NotificationDelivery:
    """Create a delivery record and attempt to send."""
    delivery = NotificationDelivery(
        channel_id=channel_model.id,
        event_type=event_type,
        recipient_info={
            "channel_name": channel_model.name,
            "channel_type": channel_model.channel_type,
            "recipient": message.recipient,
        },
        status=DeliveryStatus.PENDING,
        attempts=0,
    )
    db.add(delivery)
    await db.flush()

    channel = get_channel(channel_model.channel_type, channel_model.config)
    await _execute_send(db, delivery, channel, message)

    return delivery


async def _execute_send(
    db: AsyncSession,
    delivery: NotificationDelivery,
    channel,
    message: FormattedMessage,
) -> None:
    """Attempt send and update delivery status accordingly."""
    delivery.attempts += 1
    try:
        result = await channel.send(message)
        delivery.status = DeliveryStatus.SENT
        delivery.status_detail = result
    except TransientError as e:
        logger.warning(
            "Transient error on delivery %s (attempt %d): %s",
            delivery.id, delivery.attempts, e,
        )
        if delivery.attempts < MAX_RETRIES:
            backoff = RETRY_BACKOFF[delivery.attempts - 1]
            delivery.status = DeliveryStatus.RETRYING
            delivery.status_detail = str(e)
            delivery.next_retry_at = (
                datetime.now(timezone.utc) + timedelta(seconds=backoff)
            )
        else:
            delivery.status = DeliveryStatus.FAILED
            delivery.status_detail = f"Max retries exceeded: {e}"
    except PermanentError as e:
        logger.error(
            "Permanent error on delivery %s: %s", delivery.id, e,
        )
        delivery.status = DeliveryStatus.FAILED
        delivery.status_detail = str(e)
    except Exception as e:
        logger.exception(
            "Unexpected error on delivery %s: %s", delivery.id, e,
        )
        delivery.status = DeliveryStatus.FAILED
        delivery.status_detail = f"Unexpected: {e}"

    await db.flush()
