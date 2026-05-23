"""Unit tests for the send_notification wrapper."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.notifications import Notification
from app.services.core.notifications import send_notification


pytestmark = pytest.mark.asyncio


async def test_send_notification_persists_payload(
    db_session, test_user, test_org
):
    """Explicit payload survives the wrapper end-to-end."""
    await send_notification(
        event_type="ROLE_ASSIGNED",
        org_id=test_org.id,
        entity_type="run",
        entity_id=uuid4(),
        recipients=[test_user.id],
        context={
            "role_name": "Operator",
            "run_name": "CHO 42",
            "assigned_by": "Alice",
            "assignee_name": "Bob",
        },
        payload={"step_id": "abc-123"},
    )

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == test_user.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].payload == {"step_id": "abc-123"}


async def test_send_notification_defaults_payload_to_empty_dict(
    db_session, test_user, test_org
):
    """Omitting payload persists `{}` (the column default)."""
    await send_notification(
        event_type="ROLE_ASSIGNED",
        org_id=test_org.id,
        entity_type="run",
        entity_id=uuid4(),
        recipients=[test_user.id],
        context={
            "role_name": "Operator",
            "run_name": "CHO 42",
            "assigned_by": "Alice",
            "assignee_name": "Bob",
        },
    )

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == test_user.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].payload == {}


async def test_send_notification_preserves_explicit_empty_payload(
    db_session, test_user, test_org
):
    """Caller passing {} verbatim is not coerced (rules out `payload or {}`)."""
    await send_notification(
        event_type="ROLE_ASSIGNED",
        org_id=test_org.id,
        entity_type="run",
        entity_id=uuid4(),
        recipients=[test_user.id],
        context={
            "role_name": "Operator",
            "run_name": "CHO 42",
            "assigned_by": "Alice",
            "assignee_name": "Bob",
        },
        payload={},
    )

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == test_user.id)
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].payload == {}
