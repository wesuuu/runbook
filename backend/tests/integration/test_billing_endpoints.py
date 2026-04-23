from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization, OrganizationMember, OrgRole
from app.services.billing import stripe_client


@pytest.fixture
def configured_fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.billing_portal.Session.create.return_value = MagicMock(
        url="https://billing.stripe.com/session/xyz"
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )
    return fake


async def _make_billing_user(db_session, role: str = OrgRole.ADMIN.value):
    from app.core.security import hash_password
    from app.models.iam import User
    org = Organization(
        name="Billing Test",
        subscription_tier="essentials",
        subscription_status="trialing",
        stripe_customer_id="cus_test_billing",
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email=f"billing{uuid4().hex[:6]}@test.co",
        hashed_password=hash_password("x"),
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=org.id, role=role
    ))
    await db_session.flush()
    return user, org


async def _auth_headers_for(user):
    from app.core.security import create_access_token
    from app.models.iam import SubscriptionTier
    token = create_access_token(
        user_id=user.id,
        org_id=user.selected_org_id,
        subscription_tier=SubscriptionTier.ESSENTIALS.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_subscription_returns_state(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, org = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "essentials"
    assert data["status"] == "trialing"
    assert "days_remaining_in_trial" in data
    assert data["is_locked_out"] is False


@pytest.mark.asyncio
async def test_get_subscription_rejects_non_billing_member(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(
        db_session, role=OrgRole.MEMBER.value
    )
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_portal_session_returns_url(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.post(
        "/billing/portal-session", json={}, headers=headers
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["url"].startswith("https://billing.stripe.com/")


@pytest.mark.asyncio
async def test_create_portal_session_uses_custom_return_url(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.post(
        "/billing/portal-session",
        json={"return_url": "https://myapp/custom"},
        headers=headers,
    )

    assert resp.status_code == 200
    configured_fake_stripe.billing_portal.Session.create.assert_called_with(
        customer="cus_test_billing",
        return_url="https://myapp/custom",
    )


@pytest.mark.asyncio
async def test_endpoints_return_503_when_unconfigured(
    client: AsyncClient, db_session
):
    # Relies on the conftest autouse _disable_stripe_globally fixture to
    # ensure Stripe config is blanked — don't re-apply configured_fake_stripe.
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 503
    assert "Billing" in resp.json()["detail"]

    resp = await client.post(
        "/billing/portal-session", json={}, headers=headers
    )
    assert resp.status_code == 503
