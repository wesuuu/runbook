"""TD-0091c: verified-email gate skips EMAIL dispatch for unverified users on
auto-provisioned (is_default) channels, but still passes for user-managed
channels and for verified accounts (including SSO via oauth_email_verified).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.iam import User
from app.models.notifications import NotificationChannel, NotificationSubscription
from app.services.core.notifications import dispatcher
from app.services.core.notifications.channels.base import FormattedMessage


async def _setup_email_channel(
    db_session, *, email_verified: bool, is_default: bool, oauth_verified: bool = False
):
    user = User(
        email="gate@example.com",
        email_verified=email_verified,
        oauth_email_verified=oauth_verified,
    )
    db_session.add(user)
    await db_session.flush()
    channel = NotificationChannel(
        user_id=user.id,
        name="Email",
        channel_type="EMAIL",
        config={"to": user.email},
        enabled=True,
        is_default=is_default,
    )
    db_session.add(channel)
    await db_session.flush()
    db_session.add(
        NotificationSubscription(
            channel_id=channel.id, event_type="ROLE_ASSIGNED", enabled=True
        )
    )
    await db_session.flush()
    return user, channel


def _messages(event_type="ROLE_ASSIGNED"):
    return (
        FormattedMessage(
            event_type=event_type, title="t", body="b", recipient=""
        ),
        FormattedMessage(
            event_type=event_type, title="t", body="b", recipient="org"
        ),
    )


@pytest.mark.asyncio
async def test_unverified_user_default_channel_is_skipped(db_session, test_org):
    user, _channel = await _setup_email_channel(
        db_session, email_verified=False, is_default=True
    )
    personal, broadcast = _messages()

    fake = AsyncMock(return_value="OK")
    with patch(
        "app.services.core.notifications.dispatcher.get_channel"
    ) as get_channel:
        get_channel.return_value.send = fake
        deliveries = await dispatcher.dispatch_event(
            db_session,
            "ROLE_ASSIGNED",
            test_org.id,
            [user.id],
            personal,
            broadcast,
        )

    assert deliveries == []
    fake.assert_not_called()


@pytest.mark.asyncio
async def test_verified_user_default_channel_is_dispatched(
    db_session, test_org
):
    user, _channel = await _setup_email_channel(
        db_session, email_verified=True, is_default=True
    )
    personal, broadcast = _messages()

    fake = AsyncMock(return_value="OK")
    with patch(
        "app.services.core.notifications.dispatcher.get_channel"
    ) as get_channel:
        get_channel.return_value.send = fake
        deliveries = await dispatcher.dispatch_event(
            db_session,
            "ROLE_ASSIGNED",
            test_org.id,
            [user.id],
            personal,
            broadcast,
        )

    assert len(deliveries) == 1
    fake.assert_called_once()
    # Sent message recipient resolved from User.email (not config.to).
    assert fake.await_args.args[0].recipient == "gate@example.com"


@pytest.mark.asyncio
async def test_oauth_only_verified_user_is_dispatched(db_session, test_org):
    user, _channel = await _setup_email_channel(
        db_session,
        email_verified=False,
        oauth_verified=True,
        is_default=True,
    )
    personal, broadcast = _messages()

    fake = AsyncMock(return_value="OK")
    with patch(
        "app.services.core.notifications.dispatcher.get_channel"
    ) as get_channel:
        get_channel.return_value.send = fake
        deliveries = await dispatcher.dispatch_event(
            db_session,
            "ROLE_ASSIGNED",
            test_org.id,
            [user.id],
            personal,
            broadcast,
        )

    assert len(deliveries) == 1
    fake.assert_called_once()


@pytest.mark.asyncio
async def test_user_managed_channel_skips_gate(db_session, test_org):
    """User-created (is_default=False) channels are best-effort and skip the gate."""
    user, _channel = await _setup_email_channel(
        db_session, email_verified=False, is_default=False
    )
    personal, broadcast = _messages()

    fake = AsyncMock(return_value="OK")
    with patch(
        "app.services.core.notifications.dispatcher.get_channel"
    ) as get_channel:
        get_channel.return_value.send = fake
        deliveries = await dispatcher.dispatch_event(
            db_session,
            "ROLE_ASSIGNED",
            test_org.id,
            [user.id],
            personal,
            broadcast,
        )

    assert len(deliveries) == 1
    fake.assert_called_once()
