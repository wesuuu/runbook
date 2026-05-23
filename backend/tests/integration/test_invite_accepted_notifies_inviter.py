"""TD-0091c: GET /auth/accept-invite emits an INVITE_ACCEPTED notification
to the inviter so they can see the invitee joined."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import generate_verification_token, hash_password
from app.models.iam import Invitation, InvitationStatus, User
from app.models.notifications import Notification


@pytest.mark.asyncio
async def test_accept_invite_notifies_inviter(
    client, db_session, test_org, test_user,
):
    """test_user is the inviter; we create a fresh invitee + pending invitation
    and verify the accept route creates an INVITE_ACCEPTED Notification
    targeting the inviter."""
    invitee = User(
        email=f"accepter-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        email_verified=True,
        full_name="Accepter",
    )
    db_session.add(invitee)
    await db_session.flush()

    token = generate_verification_token()
    invitation = Invitation(
        organization_id=test_org.id,
        invited_email=invitee.email,
        invited_user_id=invitee.id,
        role="MEMBER",
        invited_by=test_user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invitation)
    await db_session.commit()

    resp = await client.get(f"/auth/accept-invite?token={token}")
    assert resp.status_code in (200, 302), resp.text

    notifs = (await db_session.execute(
        select(Notification).where(
            Notification.user_id == test_user.id,
            Notification.event_type == "INVITE_ACCEPTED",
        )
    )).scalars().all()
    assert len(notifs) == 1
