"""Tests for the default-channel provisioning module (TD-0091c Phase 4)."""

import pytest
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
)
from app.services.core.notifications.policy import DEFAULT_POLICY
from app.services.core.notifications.provisioning import (
    ensure_default_user_channel,
)


@pytest.mark.asyncio
async def test_new_user_gets_channel_and_subscriptions(db_session):
    user = User(email="newbie@example.com", email_verified=True, full_name="Newbie")
    db_session.add(user)
    await db_session.flush()

    channel = await ensure_default_user_channel(db_session, user.id)
    await db_session.flush()

    assert channel.user_id == user.id
    assert channel.channel_type == "EMAIL"
    assert channel.config == {"to": "newbie@example.com"}
    assert channel.is_default is True

    subs = (
        await db_session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.channel_id == channel.id
            )
        )
    ).scalars().all()
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    assert {s.event_type for s in subs} == expected


@pytest.mark.asyncio
async def test_re_call_is_no_op(db_session):
    user = User(email="repeat@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()

    await ensure_default_user_channel(db_session, user.id)
    await db_session.flush()
    await ensure_default_user_channel(db_session, user.id)
    await db_session.flush()

    channels = (
        await db_session.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user.id,
                NotificationChannel.channel_type == "EMAIL",
                NotificationChannel.is_default.is_(True),
            )
        )
    ).scalars().all()
    assert len(channels) == 1

    subs = (
        await db_session.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.channel_id == channels[0].id
            )
        )
    ).scalars().all()
    expected = {ev for ev, p in DEFAULT_POLICY.items() if p.email}
    assert {s.event_type for s in subs} == expected


@pytest.mark.asyncio
async def test_pre_existing_default_channel_is_returned(db_session):
    """If the row already exists, ensure_default_user_channel returns it."""
    user = User(email="race@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()

    pre = NotificationChannel(
        user_id=user.id,
        name="Email",
        channel_type="EMAIL",
        config={"to": user.email},
        enabled=True,
        is_default=True,
    )
    db_session.add(pre)
    await db_session.flush()

    channel = await ensure_default_user_channel(db_session, user.id)
    assert channel.id == pre.id
