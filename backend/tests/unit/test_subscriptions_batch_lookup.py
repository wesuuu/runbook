"""TD-0091c: _get_subscribed_channels accepts user_ids for batch lookup."""

import pytest
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import (
    NotificationChannel,
    NotificationSubscription,
)
from app.services.core.notifications.dispatcher import _get_subscribed_channels


@pytest.mark.asyncio
async def test_batch_lookup_returns_channels_for_multiple_users(db_session):
    users = []
    for i in range(3):
        u = User(email=f"batch{i}@example.com", email_verified=True)
        db_session.add(u)
        await db_session.flush()
        c = NotificationChannel(
            user_id=u.id,
            name="Email",
            channel_type="EMAIL",
            config={"to": u.email},
            enabled=True,
            is_default=True,
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(
            NotificationSubscription(
                channel_id=c.id,
                event_type="STEP_DEVIATION",
                enabled=True,
            )
        )
        users.append(u)
    await db_session.flush()

    channels = await _get_subscribed_channels(
        db_session,
        "STEP_DEVIATION",
        user_ids=[u.id for u in users],
    )
    assert {c.user_id for c in channels} == {u.id for u in users}


@pytest.mark.asyncio
async def test_batch_lookup_emits_one_query(db_session):
    """One IN query, not N. Count statements that touch notification_channels."""
    users = []
    for i in range(3):
        u = User(email=f"qcount{i}@example.com", email_verified=True)
        db_session.add(u)
        await db_session.flush()
        c = NotificationChannel(
            user_id=u.id,
            name="Email",
            channel_type="EMAIL",
            config={"to": u.email},
            enabled=True,
            is_default=True,
        )
        db_session.add(c)
        await db_session.flush()
        db_session.add(
            NotificationSubscription(
                channel_id=c.id,
                event_type="STEP_DEVIATION",
                enabled=True,
            )
        )
        users.append(u)
    await db_session.flush()

    from sqlalchemy import event as sa_event

    bind = db_session.bind
    counter = {"n": 0}

    def _counter(conn, cursor, statement, parameters, context, executemany):
        if "notification_channels" in statement.lower() and "select" in statement.lower():
            counter["n"] += 1

    sync_engine = bind.sync_engine
    sa_event.listen(sync_engine, "before_cursor_execute", _counter)
    try:
        await _get_subscribed_channels(
            db_session,
            "STEP_DEVIATION",
            user_ids=[u.id for u in users],
        )
    finally:
        sa_event.remove(sync_engine, "before_cursor_execute", _counter)

    assert counter["n"] == 1
