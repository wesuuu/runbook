"""TD-0091c: _resolve_personal_recipient prefers User.email for is_default channels."""

import pytest

from app.models.iam import User
from app.models.notifications import NotificationChannel
from app.services.core.notifications.dispatcher import _resolve_personal_recipient


@pytest.mark.asyncio
async def test_is_default_channel_resolves_from_user_email(db_session):
    user = User(email="alice@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()
    channel = NotificationChannel(
        user_id=user.id,
        channel_type="EMAIL",
        name="Email",
        # config.to is tampered; is_default channels MUST ignore it.
        config={"to": "attacker@evil.com"},
        enabled=True,
        is_default=True,
    )
    db_session.add(channel)
    await db_session.flush()

    cache: dict = {}
    recipient, resolved_user = await _resolve_personal_recipient(
        db_session, channel, cache
    )
    assert recipient == "alice@example.com"
    assert resolved_user is not None and resolved_user.id == user.id


@pytest.mark.asyncio
async def test_user_managed_channel_uses_config_to(db_session):
    user = User(email="bob@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()
    channel = NotificationChannel(
        user_id=user.id,
        channel_type="EMAIL",
        name="Personal alias",
        config={"to": "bob+alias@example.com"},
        enabled=True,
        is_default=False,
    )
    db_session.add(channel)
    await db_session.flush()

    cache: dict = {}
    recipient, resolved_user = await _resolve_personal_recipient(
        db_session, channel, cache
    )
    assert recipient == "bob+alias@example.com"
    assert resolved_user is not None and resolved_user.id == user.id


@pytest.mark.asyncio
async def test_slack_channel_returns_empty_recipient(db_session):
    user = User(email="carol@example.com", email_verified=True)
    db_session.add(user)
    await db_session.flush()
    channel = NotificationChannel(
        user_id=user.id,
        channel_type="SLACK",
        name="My Slack",
        config={"webhook_url": "https://hooks.slack.com/x"},
        enabled=True,
        is_default=False,
    )
    db_session.add(channel)
    await db_session.flush()

    cache: dict = {}
    recipient, resolved_user = await _resolve_personal_recipient(
        db_session, channel, cache
    )
    assert recipient == ""


@pytest.mark.asyncio
async def test_org_scoped_channel_uses_config_to(db_session):
    """Org-scoped (user_id IS NULL) channels carry their recipient in config."""
    from app.models.iam import Organization

    org = Organization(name="Test Org")
    db_session.add(org)
    await db_session.flush()

    channel = NotificationChannel(
        user_id=None,
        org_id=org.id,
        channel_type="EMAIL",
        name="Team alias",
        config={"to": "team@example.com"},
        enabled=True,
        is_default=False,
    )
    db_session.add(channel)
    await db_session.flush()

    cache: dict = {}
    recipient, resolved_user = await _resolve_personal_recipient(
        db_session, channel, cache
    )
    assert recipient == "team@example.com"
    assert resolved_user is None
