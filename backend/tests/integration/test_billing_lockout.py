from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.iam import (Organization, OrganizationMember, OrgRole,
                            SubscriptionTier, User)
from app.models.science import Project


async def _setup_locked_out_org(db_session, status: str = "canceled"):
    org = Organization(
        name="Locked Out",
        subscription_tier="essentials",
        subscription_status=status,
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email=f"locked{uuid4().hex[:6]}@test.co",
        hashed_password=hash_password("x"),
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=user.id, organization_id=org.id, roles=["MEMBER", OrgRole.ADMIN.value]
        )
    )
    await db_session.flush()
    return user, org


def _headers(user):
    token = create_access_token(
        user_id=user.id,
        org_id=user.selected_org_id,
        subscription_tier=SubscriptionTier.ESSENTIALS.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_write_endpoint_402s_when_subscription_canceled(
    client: AsyncClient, db_session
):
    user, _ = await _setup_locked_out_org(db_session, status="canceled")
    headers = _headers(user)

    resp = await client.post(
        "/projects/",
        json={"name": "should fail"},
        headers=headers,
    )

    assert resp.status_code == 402
    body = resp.json()
    assert body["detail"]["code"] == "subscription_required"
    assert body["detail"]["status"] == "canceled"


@pytest.mark.asyncio
async def test_write_endpoint_402s_when_past_due(client: AsyncClient, db_session):
    user, _ = await _setup_locked_out_org(db_session, status="past_due")
    resp = await client.post(
        "/projects/",
        json={"name": "should fail"},
        headers=_headers(user),
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_read_endpoint_succeeds_when_locked_out(client: AsyncClient, db_session):
    user, org = await _setup_locked_out_org(db_session, status="canceled")
    db_session.add(Project(name="p1", organization_id=org.id))
    await db_session.flush()

    resp = await client.get(
        "/projects/",
        params={"organization_id": str(org.id)},
        headers=_headers(user),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_billing_portal_session_accessible_when_locked_out(
    client: AsyncClient, db_session, monkeypatch
):
    from unittest.mock import MagicMock

    from app.services.billing import stripe_client

    fake = MagicMock()
    fake.billing_portal.Session.create.return_value = MagicMock(
        url="https://billing.stripe.com/session/abc"
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", "x")

    user, org = await _setup_locked_out_org(db_session)
    org.stripe_customer_id = "cus_test_lockout"
    await db_session.flush()

    resp = await client.post("/billing/portal-session", json={}, headers=_headers(user))
    assert resp.status_code == 200
    stripe_client._reset_cache()


@pytest.mark.asyncio
async def test_trialing_user_can_write(client: AsyncClient, db_session):
    user, org = await _setup_locked_out_org(db_session, status="trialing")
    resp = await client.post(
        "/projects/",
        json={"name": "ok", "organization_id": str(org.id)},
        headers=_headers(user),
    )
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_null_status_user_can_write(client: AsyncClient, db_session):
    """Pre-billing org (no Stripe provisioning) behaves as 'not locked out'."""
    user, org = await _setup_locked_out_org(db_session, status="trialing")
    org.subscription_status = None
    await db_session.flush()

    resp = await client.post(
        "/projects/",
        json={"name": "ok", "organization_id": str(org.id)},
        headers=_headers(user),
    )
    assert resp.status_code in (200, 201)
