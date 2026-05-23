"""TD-0091c Phase 11: read-side notification endpoints must remain accessible
to lapsed subscribers; write-side endpoints continue to 402."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.notifications import (
    Notification,
    NotificationChannel,
    NotificationEventType,
)


async def _lapse_org(db_session, test_org):
    test_org.subscription_status = "past_due"
    db_session.add(test_org)
    await db_session.commit()
    await db_session.refresh(test_org)


async def _seed_notification(db_session, user_id):
    n = Notification(
        user_id=user_id,
        event_type=NotificationEventType.ROLE_ASSIGNED.value,
        title="Test",
        message="You were assigned",
        entity_type="run",
        entity_id=uuid4(),
    )
    db_session.add(n)
    await db_session.commit()
    await db_session.refresh(n)
    return n


@pytest.mark.asyncio
async def test_lapsed_user_can_read_and_dismiss(
    authed_admin_client, db_session, test_org, test_user,
):
    await _lapse_org(db_session, test_org)
    notif = await _seed_notification(db_session, test_user.id)

    resp = await authed_admin_client.get("/notifications/")
    assert resp.status_code == 200, resp.text

    resp = await authed_admin_client.get("/notifications/unread-count")
    assert resp.status_code == 200, resp.text

    resp = await authed_admin_client.put(
        f"/notifications/{notif.id}/read",
    )
    assert resp.status_code == 200, resp.text

    resp = await authed_admin_client.put("/notifications/read-all")
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_lapsed_user_cannot_create_channel(
    authed_admin_client, db_session, test_org,
):
    await _lapse_org(db_session, test_org)
    resp = await authed_admin_client.post(
        "/notifications/channels/me",
        json={
            "name": "My Slack",
            "channel_type": "SLACK",
            "config": {"webhook_url": "https://hooks.slack.com/x/y/z"},
        },
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_lapsed_user_cannot_create_subscription(
    authed_admin_client, db_session, test_org, test_user,
):
    # Seed a channel BEFORE lapsing so we don't hit the create-channel gate.
    channel = NotificationChannel(
        user_id=test_user.id,
        name="Default",
        channel_type="SLACK",
        config={"webhook_url": "https://hooks.slack.com/a/b/c"},
        is_default=False,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)

    await _lapse_org(db_session, test_org)

    resp = await authed_admin_client.post(
        f"/notifications/channels/{channel.id}/subscriptions",
        json={"event_type": "ROLE_ASSIGNED", "enabled": True},
    )
    assert resp.status_code == 402, resp.text
