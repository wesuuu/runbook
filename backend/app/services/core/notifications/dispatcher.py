"""Core dispatch engine: routes notification events to channels and tracks delivery."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.iam import User
from app.models.notifications import (
    DeliveryStatus,
    NotificationChannel,
    NotificationDelivery,
    NotificationSubscription,
)
from app.services.core.notifications.channels import get_channel
from app.services.core.notifications.channels.base import (
    FormattedMessage,
    PermanentError,
    TransientError,
)

logger = logging.getLogger("notifications.dispatcher")

MAX_RETRIES = 3
RETRY_BACKOFF = [30, 120, 600]  # seconds
# NOTE: _execute_send increments `attempts` before the
# `attempts < MAX_RETRIES` check, so a delivery is sent at most 3 times
# and only 2 retries occur — RETRY_BACKOFF[2] (600s) is never used. This
# off-by-one is pre-existing and tracked in a separate TECH_DEBT task; it
# is intentionally NOT changed here (this change is test-coverage only).


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
    org_channels = await _get_subscribed_channels(db, event_type, org_id=org_id)
    for channel_model in org_channels:
        delivery = await _dispatch_to_channel(
            db, channel_model, message_broadcast, event_type
        )
        deliveries.append(delivery)

    # 2. User-level channels — single IN query for all recipients, grouped.
    all_user_channels = await _get_subscribed_channels(
        db, event_type, user_ids=recipients
    )
    channels_by_user: dict[UUID, list[NotificationChannel]] = {}
    for ch in all_user_channels:
        if ch.user_id is not None:
            channels_by_user.setdefault(ch.user_id, []).append(ch)

    user_cache: dict[UUID, User | None] = {}
    for user_id in recipients:
        for channel_model in channels_by_user.get(user_id, []):
            recipient = message_personal.recipient
            if channel_model.channel_type == "EMAIL":
                resolved_recipient, user = await _resolve_personal_recipient(
                    db, channel_model, user_cache
                )
                # Verified-email gate (TD-0091c): only auto-provisioned
                # is_default channels are gated. User-managed channels are
                # best-effort and skip the gate so deliberate aliases work.
                if channel_model.is_default and (
                    user is None
                    or not (
                        user.email_verified
                        or getattr(user, "oauth_email_verified", False)
                    )
                ):
                    logger.info(
                        "Skipping email for unverified user %s on event %s",
                        channel_model.user_id,
                        event_type,
                    )
                    continue
                recipient = resolved_recipient

            msg = FormattedMessage(
                event_type=message_personal.event_type,
                title=message_personal.title,
                body=message_personal.body,
                recipient=recipient,
                url=message_personal.url,
                html_body=message_personal.html_body,
            )
            delivery = await _dispatch_to_channel(db, channel_model, msg, event_type)
            deliveries.append(delivery)

    return deliveries


async def _get_user_cached(
    db: AsyncSession,
    user_id: UUID,
    cache: dict[UUID, User | None],
) -> User | None:
    if user_id in cache:
        return cache[user_id]
    user = await db.get(User, user_id)
    cache[user_id] = user
    return user


async def _resolve_personal_recipient(
    db: AsyncSession,
    channel: NotificationChannel,
    user_cache: dict[UUID, User | None],
) -> tuple[str, User | None]:
    """Per-channel recipient + resolved user for a user-level dispatch.

    For is_default=True EMAIL channels we ignore config['to'] (tamper-proof)
    and resolve from User.email. For user-managed EMAIL channels we honor
    config['to']. Non-EMAIL channels (Slack/Teams/etc.) route via their own
    config (webhook URL etc.) and return an empty recipient.
    """
    if channel.channel_type != "EMAIL":
        # Still resolve the user (for context like the verified-email gate),
        # but the recipient field is unused by these channels.
        user = None
        if channel.user_id is not None:
            user = await _get_user_cached(db, channel.user_id, user_cache)
        return "", user

    user: User | None = None
    if channel.user_id is not None:
        user = await _get_user_cached(db, channel.user_id, user_cache)

    if channel.is_default and user is not None:
        return user.email or "", user
    config_to = (channel.config or {}).get("to", "")
    return config_to, user


async def retry_pending(db: AsyncSession) -> int:
    """Retry deliveries that are due. Returns count of retried deliveries.

    Each delivery is processed inside its own SAVEPOINT (``begin_nested``),
    so a failure on one row — including a DB-level error that would poison
    the session — is rolled back to the savepoint and the row marked FAILED
    on the still-healthy outer transaction. The batch is never aborted, so
    the caller's single commit is always reached. Most-overdue deliveries
    drain first.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.status == DeliveryStatus.RETRYING)
        .where(NotificationDelivery.next_retry_at <= now)
        .order_by(NotificationDelivery.next_retry_at, NotificationDelivery.id)
        .limit(50)
        .options(selectinload(NotificationDelivery.channel))
    )
    result = await db.execute(stmt)
    pending = result.scalars().all()

    count = 0
    for delivery in pending:
        try:
            async with db.begin_nested():
                channel_model = delivery.channel
                if not channel_model or not channel_model.enabled:
                    delivery.status = DeliveryStatus.FAILED
                    delivery.status_detail = "Channel disabled or deleted"
                else:
                    channel = get_channel(
                        channel_model.channel_type, channel_model.config
                    )
                    msg = FormattedMessage(
                        event_type=delivery.event_type,
                        title="(retry)",
                        body="",
                        recipient=delivery.recipient_info.get(
                            "recipient", "unknown"
                        ),
                    )
                    await _execute_send(db, delivery, channel, msg)
                    count += 1
        except Exception as e:  # noqa: BLE001 — per-row batch isolation
            logger.exception(
                "Retry sweep: unexpected error on delivery %s", delivery.id
            )
            delivery.status = DeliveryStatus.FAILED
            delivery.status_detail = f"Retry aborted: {e}"

    await db.flush()
    return count


async def _get_subscribed_channels(
    db: AsyncSession,
    event_type: str,
    org_id: UUID | None = None,
    user_id: UUID | None = None,
    user_ids: list[UUID] | None = None,
) -> list[NotificationChannel]:
    """Find enabled channels with an active subscription for this event.

    `user_id` and `user_ids` are mutually exclusive overloads — pass either.
    `user_ids` issues a single IN query, used by the dispatcher's per-event
    user-channel fan-out so STEP_DEVIATION on a 10-assignee run isn't N+1.
    """
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
    elif user_ids is not None:
        if not user_ids:
            return []
        stmt = stmt.where(NotificationChannel.user_id.in_(user_ids))

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
            delivery.id,
            delivery.attempts,
            e,
        )
        if delivery.attempts < MAX_RETRIES:
            backoff = RETRY_BACKOFF[delivery.attempts - 1]
            delivery.status = DeliveryStatus.RETRYING
            delivery.status_detail = str(e)
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=backoff
            )
        else:
            delivery.status = DeliveryStatus.FAILED
            delivery.status_detail = f"Max retries exceeded: {e}"
    except PermanentError as e:
        logger.error(
            "Permanent error on delivery %s: %s",
            delivery.id,
            e,
        )
        delivery.status = DeliveryStatus.FAILED
        delivery.status_detail = str(e)
    except Exception as e:
        logger.exception(
            "Unexpected error on delivery %s: %s",
            delivery.id,
            e,
        )
        delivery.status = DeliveryStatus.FAILED
        delivery.status_detail = f"Unexpected: {e}"

    await db.flush()
