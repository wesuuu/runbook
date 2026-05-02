from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.iam import (Organization, OrganizationMember, SubscriptionTier,
                            User)
from app.services.billing import seat_limits


@pytest.mark.asyncio
async def test_get_seat_limit_per_tier():
    assert seat_limits.get_seat_limit(SubscriptionTier.ESSENTIALS) == 5
    assert seat_limits.get_seat_limit(SubscriptionTier.PRO) == 25
    assert seat_limits.get_seat_limit(SubscriptionTier.ENTERPRISE) is None


@pytest.mark.asyncio
async def test_get_seat_count_counts_only_active(db_session, test_org, test_user):
    # test_user fixture adds 1 ADMIN membership to test_org. Add 1 active + 1 archived.
    active_user = User(email="a@x.com", hashed_password="x")
    archived_user = User(email="b@x.com", hashed_password="x")
    db_session.add_all([active_user, archived_user])
    await db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(
                user_id=active_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
                archived=False,
            ),
            OrganizationMember(
                user_id=archived_user.id,
                organization_id=test_org.id,
                roles=["MEMBER"],
                archived=True,
            ),
        ]
    )
    await db_session.flush()
    count = await seat_limits.get_seat_count(db_session, test_org.id)
    assert count == 2  # 1 from test_user fixture + 1 active new; archived excluded


@pytest.mark.asyncio
async def test_check_seat_capacity_allows_when_under_cap(
    db_session, test_org, test_user
):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    await db_session.flush()
    # test_user fixture = 1 member; Essentials cap = 5. Should not raise.
    await seat_limits.check_seat_capacity(db_session, test_org)


@pytest.mark.asyncio
async def test_check_seat_capacity_blocks_when_at_cap(db_session, test_org, test_user):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    await db_session.flush()
    # test_user fixture already added 1 ADMIN. Add 4 more to reach 5 (the cap).
    for i in range(4):
        u = User(email=f"fill{i}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=u.id, organization_id=test_org.id, roles=["MEMBER"], archived=False
            )
        )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await seat_limits.check_seat_capacity(db_session, test_org)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "seat_limit_reached"
    assert exc.value.detail["tier"] == "essentials"
    assert exc.value.detail["limit"] == 5
    assert exc.value.detail["current"] == 5


@pytest.mark.asyncio
async def test_check_seat_capacity_allows_enterprise_at_any_count(
    db_session, test_org, test_user
):
    test_org.subscription_tier = SubscriptionTier.ENTERPRISE
    await db_session.flush()
    for i in range(30):
        u = User(email=f"big{i}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=u.id, organization_id=test_org.id, roles=["MEMBER"], archived=False
            )
        )
    await db_session.flush()
    await seat_limits.check_seat_capacity(db_session, test_org)
