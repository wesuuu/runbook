"""Integration tests for per-tier seat caps on POST /iam/organizations/{org_id}/members."""
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.iam import (
    Organization,
    OrganizationMember,
    SubscriptionTier,
    User,
)


async def _fill_org_to(db_session, org_id, target_count, start_count=1):
    """Add (target_count - start_count) active members to org."""
    for i in range(target_count - start_count):
        u = User(email=f"fill_{uuid4().hex[:6]}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=u.id, organization_id=org_id, role="MEMBER", archived=False,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_add_member_blocked_when_essentials_cap_reached(
    client: AsyncClient, db_session, test_org, test_user, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=5)

    new_user = User(email="overflow@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    body = resp.json()["detail"]
    assert body["code"] == "seat_limit_reached"
    assert body["tier"] == "essentials"
    assert body["limit"] == 5
    assert body["current"] == 5


@pytest.mark.asyncio
async def test_add_member_succeeds_at_cap_minus_one(
    client: AsyncClient, db_session, test_org, test_user, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=4)

    new_user = User(email="ok@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reactivate_archived_member_bypasses_cap(
    client: AsyncClient, db_session, test_org, test_user, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=5)

    archived_user = User(email="comeback@x.com", hashed_password="x")
    db_session.add(archived_user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=archived_user.id,
            organization_id=test_org.id,
            role="MEMBER",
            archived=True,
        )
    )
    await db_session.commit()
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(archived_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enterprise_has_no_cap(
    client: AsyncClient, db_session, test_org, test_user, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ENTERPRISE
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=30)

    new_user = User(email="yetanother@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
