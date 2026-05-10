"""Integration tests for GET /science/protocols/{id}/approval-history."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.iam import Organization, OrganizationMember, User
from app.models.science import Project, Protocol


async def _make_org_approver(db: AsyncSession, org: Organization) -> tuple[User, dict]:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Org Approver",
        selected_org_id=org.id,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=["MEMBER", "PROTOCOL_APPROVER"],
        )
    )
    await db.flush()
    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=True,
    )
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_approval_history_after_submit_approve(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Submit then approve → 2 events ordered DESC, actor populated."""
    proto = Protocol(
        name="History Test",
        project_id=test_project.id,
        status="DRAFT",
        created_by_id=test_user.id,
        requires_approval=True,
    )
    db_session.add(proto)
    await db_session.flush()

    approver, approver_headers = await _make_org_approver(db_session, test_org)

    # Submit
    submit_resp = await client.post(
        f"/science/protocols/{proto.id}/submit-for-approval",
        json={"requested_user_ids": [str(approver.id)]},
        headers=auth_headers,
    )
    assert submit_resp.status_code == 200, submit_resp.text

    # Approve
    approve_resp = await client.post(
        f"/science/protocols/{proto.id}/approve",
        json={"comment": "all good"},
        headers=approver_headers,
    )
    assert approve_resp.status_code == 200, approve_resp.text

    # History
    hist_resp = await client.get(
        f"/science/protocols/{proto.id}/approval-history",
        headers=auth_headers,
    )
    assert hist_resp.status_code == 200, hist_resp.text
    events = hist_resp.json()
    assert len(events) == 2
    # Newest first → APPROVED, then SUBMITTED
    assert events[0]["action"] == "APPROVED"
    assert events[1]["action"] == "SUBMITTED"
    assert events[0]["actor"]["id"] == str(approver.id)
    assert events[0]["actor"]["email"] == approver.email
    assert events[1]["actor"]["id"] == str(test_user.id)
