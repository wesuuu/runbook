"""Notification API endpoints.

Org-level channels:  POST/GET/PUT/DELETE /notifications/channels
User-level channels: POST/GET/PUT/DELETE /notifications/channels/me
Subscriptions:       POST/DELETE         /notifications/channels/{id}/subscriptions
User notifications:  GET/PUT             /notifications/
Delivery log:        GET                 /notifications/deliveries
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import User, OrganizationMember
from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
    Notification,
    NotificationDelivery,
    ChannelType,
    NotificationEventType,
    DeliveryStatus,
)
from app.schemas.notifications import (
    ChannelCreate,
    ChannelUpdate,
    ChannelResponse,
    ChannelTestResult,
    SubscriptionCreate,
    SubscriptionResponse,
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
    DeliveryResponse,
    DeliveryListResponse,
)
from app.services.notifications.channels import get_channel
from app.services.notifications.channels.base import (
    TransientError, PermanentError,
)

logger = logging.getLogger("notifications.api")

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_user_org_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the user's first org membership. Raises 400 if none."""
    stmt = select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == user_id
    ).limit(1)
    result = await db.execute(stmt)
    org_id = result.scalar_one_or_none()
    if not org_id:
        raise HTTPException(400, "User is not a member of any organization")
    return org_id


async def _require_org_admin(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> None:
    """Verify the user is an org admin. Raises 403 if not."""
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
    )
    result = await db.execute(stmt)
    membership = result.scalar_one_or_none()
    if not membership or membership.role != "ADMIN":
        raise HTTPException(403, "Organization admin access required")


async def _require_org_member(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> None:
    """Verify the user belongs to the org (any role). Raises 403 if not."""
    stmt = select(OrganizationMember.id).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
    )
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        raise HTTPException(403, "Organization membership required")


async def _get_channel_or_404(
    db: AsyncSession, channel_id: UUID
) -> NotificationChannel:
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return channel


def _validate_channel_type(channel_type: str) -> None:
    valid = {e.value for e in ChannelType}
    if channel_type not in valid:
        raise HTTPException(400, f"Invalid channel_type. Must be one of: {valid}")


def _validate_event_type(event_type: str) -> None:
    valid = {e.value for e in NotificationEventType}
    if event_type not in valid:
        raise HTTPException(400, f"Invalid event_type. Must be one of: {valid}")


# ── Org-Level Channel CRUD ───────────────────────────────────────────────

@router.post("/channels", response_model=ChannelResponse, status_code=201)
async def create_org_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an org-level notification channel (admin only)."""
    _validate_channel_type(body.channel_type)
    org_id = await _get_user_org_id(db, current_user.id)
    await _require_org_admin(db, current_user.id, org_id)

    channel = NotificationChannel(
        org_id=org_id,
        name=body.name,
        channel_type=body.channel_type,
        config=body.config,
        enabled=body.enabled,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/channels", response_model=list[ChannelResponse])
async def list_org_channels(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List org-level channels."""
    org_id = await _get_user_org_id(db, current_user.id)
    stmt = (
        select(NotificationChannel)
        .where(NotificationChannel.org_id == org_id)
        .order_by(NotificationChannel.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.put("/channels/{channel_id}", response_model=ChannelResponse)
async def update_org_channel(
    channel_id: UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an org-level channel (admin only)."""
    channel = await _get_channel_or_404(db, channel_id)
    if channel.org_id is None:
        raise HTTPException(400, "This is not an org-level channel")
    await _require_org_admin(db, current_user.id, channel.org_id)

    if body.name is not None:
        channel.name = body.name
    if body.config is not None:
        channel.config = body.config
    if body.enabled is not None:
        channel.enabled = body.enabled

    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_org_channel(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an org-level channel (admin only)."""
    channel = await _get_channel_or_404(db, channel_id)
    if channel.org_id is None:
        raise HTTPException(400, "This is not an org-level channel")
    await _require_org_admin(db, current_user.id, channel.org_id)

    await db.delete(channel)
    await db.commit()


# ── User-Level Channel CRUD ─────────────────────────────────────────────

@router.post("/channels/me", response_model=ChannelResponse, status_code=201)
async def create_user_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a personal notification channel."""
    _validate_channel_type(body.channel_type)

    channel = NotificationChannel(
        user_id=current_user.id,
        name=body.name,
        channel_type=body.channel_type,
        config=body.config,
        enabled=body.enabled,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/channels/me", response_model=list[ChannelResponse])
async def list_user_channels(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's personal channels."""
    stmt = (
        select(NotificationChannel)
        .where(NotificationChannel.user_id == current_user.id)
        .order_by(NotificationChannel.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.put("/channels/me/{channel_id}", response_model=ChannelResponse)
async def update_user_channel(
    channel_id: UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a personal channel."""
    channel = await _get_channel_or_404(db, channel_id)
    if channel.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    if body.name is not None:
        channel.name = body.name
    if body.config is not None:
        channel.config = body.config
    if body.enabled is not None:
        channel.enabled = body.enabled

    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/channels/me/{channel_id}", status_code=204)
async def delete_user_channel(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a personal channel."""
    channel = await _get_channel_or_404(db, channel_id)
    if channel.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    await db.delete(channel)
    await db.commit()


# ── Channel Test ─────────────────────────────────────────────────────────

@router.post(
    "/channels/{channel_id}/test", response_model=ChannelTestResult
)
async def test_channel(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a test notification through a channel."""
    channel_model = await _get_channel_or_404(db, channel_id)

    # Verify ownership
    is_org = channel_model.org_id is not None
    if is_org:
        await _require_org_admin(db, current_user.id, channel_model.org_id)
    elif channel_model.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    adapter = get_channel(channel_model.channel_type, channel_model.config)
    try:
        result = await adapter.test()
        return ChannelTestResult(status="SENT", detail=result)
    except (TransientError, PermanentError) as e:
        return ChannelTestResult(status="FAILED", detail=str(e))


# ── Subscriptions ────────────────────────────────────────────────────────

@router.post(
    "/channels/{channel_id}/subscriptions",
    response_model=SubscriptionResponse,
    status_code=201,
)
async def create_subscription(
    channel_id: UUID,
    body: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Subscribe a channel to an event type."""
    _validate_event_type(body.event_type)
    channel = await _get_channel_or_404(db, channel_id)

    # Ownership check
    if channel.org_id:
        await _require_org_admin(db, current_user.id, channel.org_id)
    elif channel.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    # Check for duplicate
    stmt = select(NotificationSubscription).where(
        NotificationSubscription.channel_id == channel_id,
        NotificationSubscription.event_type == body.event_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.enabled = body.enabled
        await db.commit()
        await db.refresh(existing)
        return existing

    sub = NotificationSubscription(
        channel_id=channel_id,
        event_type=body.event_type,
        enabled=body.enabled,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@router.get(
    "/channels/{channel_id}/subscriptions",
    response_model=list[SubscriptionResponse],
)
async def list_subscriptions(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List subscriptions for a channel."""
    channel = await _get_channel_or_404(db, channel_id)

    if channel.org_id:
        await _require_org_member(db, current_user.id, channel.org_id)
    elif channel.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    stmt = (
        select(NotificationSubscription)
        .where(NotificationSubscription.channel_id == channel_id)
        .order_by(NotificationSubscription.event_type)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/channels/{channel_id}/subscriptions/{subscription_id}",
    status_code=204,
)
async def delete_subscription(
    channel_id: UUID,
    subscription_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a subscription."""
    channel = await _get_channel_or_404(db, channel_id)
    if channel.org_id:
        await _require_org_admin(db, current_user.id, channel.org_id)
    elif channel.user_id != current_user.id:
        raise HTTPException(403, "Not your channel")

    sub = await db.get(NotificationSubscription, subscription_id)
    if not sub or sub.channel_id != channel_id:
        raise HTTPException(404, "Subscription not found")

    await db.delete(sub)
    await db.commit()


# ── User In-App Notifications ───────────────────────────────────────────

@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's in-app notifications."""
    base = select(Notification).where(
        Notification.user_id == current_user.id
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        base
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return NotificationListResponse(items=items, total=total)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get count of unread notifications."""
    stmt = select(func.count()).where(
        Notification.user_id == current_user.id,
        Notification.read_at.is_(None),
    )
    count = (await db.execute(stmt)).scalar() or 0
    return UnreadCountResponse(count=count)


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a notification as read."""
    notif = await db.get(Notification, notification_id)
    if not notif or notif.user_id != current_user.id:
        raise HTTPException(404, "Notification not found")

    notif.read_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(notif)
    return notif


@router.put("/read-all", status_code=204)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all notifications as read."""
    from sqlalchemy import update
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.execute(stmt)
    await db.commit()


# ── Delivery Log (Admin) ────────────────────────────────────────────────

@router.get("/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List delivery log entries (admin only)."""
    org_id = await _get_user_org_id(db, current_user.id)
    await _require_org_admin(db, current_user.id, org_id)

    base = (
        select(NotificationDelivery)
        .join(NotificationChannel)
        .where(NotificationChannel.org_id == org_id)
    )
    if status:
        base = base.where(NotificationDelivery.status == status)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        base
        .order_by(NotificationDelivery.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return DeliveryListResponse(items=items, total=total)
