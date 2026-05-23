"""TD-0091c: invites to an existing user go through the notification
channel pipeline (in-app + EMAIL via user channel); invites to a new
email address still go through the direct send_invitation_email path."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.iam import User
from app.models.notifications import Notification
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_invite_to_existing_user_creates_in_app_notification(
    authed_admin_client, db_session, test_org,
):
    """Existing-user branch must (a) NOT call direct send_invitation_email
    and (b) create an in-app Notification row for the invitee."""
    existing = User(
        email=f"invitee-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Existing User",
    )
    db_session.add(existing)
    await db_session.flush()
    await db_session.commit()

    with patch(
        "app.services.core.email_service.send_invitation_email"
    ) as mock_direct:
        resp = await authed_admin_client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": existing.email, "role": "MEMBER"},
        )
        assert resp.status_code == 201, resp.text
    mock_direct.assert_not_called()

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == existing.id,
            Notification.event_type == "INVITE_SENT",
        )
    )).scalars().all()
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_invite_to_new_email_uses_direct_send(
    authed_admin_client, db_session, test_org,
):
    """No user for that email → no in-app row; direct send_invitation_email
    is the only path."""
    new_email = f"noaccount-{uuid4().hex[:8]}@example.com"
    with patch(
        "app.services.core.email_service.send_invitation_email"
    ) as mock_direct:
        resp = await authed_admin_client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": new_email, "role": "MEMBER"},
        )
        assert resp.status_code == 201, resp.text
    mock_direct.assert_called_once()
    assert mock_direct.call_args.kwargs["to_email"] == new_email

    notifs = (await db_session.execute(
        select(Notification).where(Notification.event_type == "INVITE_SENT")
    )).scalars().all()
    assert notifs == []


@pytest.mark.asyncio
async def test_resend_existing_user_invite_uses_channel_pipeline(
    authed_admin_client, db_session, test_org,
):
    existing = User(
        email=f"resend-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Resend User",
    )
    db_session.add(existing)
    await db_session.flush()
    await db_session.commit()

    # First create the invitation (mock direct send to silence the new-email branch
    # if the existing-user check fails for any reason).
    with patch("app.services.core.email_service.send_invitation_email"):
        resp = await authed_admin_client.post(
            f"/iam/organizations/{test_org.id}/invitations",
            json={"email": existing.email, "role": "MEMBER"},
        )
        assert resp.status_code == 201, resp.text
        invitation_id = resp.json()["id"]

    # Clear notifications from the create step
    await db_session.execute(
        Notification.__table__.delete().where(
            Notification.event_type == "INVITE_SENT",
        )
    )
    await db_session.commit()

    with patch(
        "app.services.core.email_service.send_invitation_email"
    ) as mock_direct:
        resp = await authed_admin_client.post(
            f"/iam/invitations/{invitation_id}/resend",
        )
        assert resp.status_code == 200, resp.text
    mock_direct.assert_not_called()

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == existing.id,
            Notification.event_type == "INVITE_SENT",
        )
    )).scalars().all()
    assert len(notifs) == 1
