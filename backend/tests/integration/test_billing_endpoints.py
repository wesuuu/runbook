import hashlib
import hmac
import json
import time
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
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", "x")
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
    db_session.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=sorted({"MEMBER", role}),
        )
    )
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
    user, _ = await _make_billing_user(db_session, role=OrgRole.MEMBER.value)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_portal_session_returns_url(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.post("/billing/portal-session", json={}, headers=headers)

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
async def test_endpoints_return_503_when_unconfigured(client: AsyncClient, db_session):
    # Relies on the conftest autouse _disable_stripe_globally fixture to
    # ensure Stripe config is blanked — don't re-apply configured_fake_stripe.
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 503
    assert "Billing" in resp.json()["detail"]

    resp = await client.post("/billing/portal-session", json={}, headers=headers)
    assert resp.status_code == 503


def _sign_stripe_event(payload: bytes, secret: str, ts: int = None) -> str:
    """Construct a Stripe-style signature header for a test payload."""
    ts = ts or int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature(
    client: AsyncClient, db_session, monkeypatch
):
    secret = "whsec_test_signing_secret"
    for key, val in [
        ("stripe_secret_key", "sk_test_x"),
        ("stripe_webhook_secret", secret),
        ("stripe_essentials_price_id", "price_ess"),
        ("stripe_pro_price_id", "price_pro"),
    ]:
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", val)
        monkeypatch.setattr(f"app.api.endpoints.billing.settings.{key}", val)
    stripe_client._reset_cache()

    # Pre-create the org so the event has a matching customer
    org = Organization(
        name="WebhookTest",
        stripe_customer_id="cus_test_123",
        stripe_subscription_id="sub_test_456",
        subscription_tier="essentials",
        subscription_status="trialing",
    )
    db_session.add(org)
    await db_session.flush()

    # Prime the real stripe module (not the injected fake) for construct_event
    stripe_client._reset_cache()
    from app.services.billing.stripe_client import get_stripe

    _ = get_stripe()

    payload = json.dumps(
        {
            "id": "evt_sig_test_001",
            "object": "event",
            "type": "customer.subscription.updated",
            "created": 1714000000,
            "data": {
                "object": {
                    "id": "sub_test_456",
                    "object": "subscription",
                    "customer": "cus_test_123",
                    "status": "active",
                    "trial_end": None,
                    "current_period_end": 1716678400,
                    "cancel_at_period_end": False,
                    "items": {"data": [{"price": {"id": "price_pro"}}]},
                }
            },
        }
    ).encode()
    sig = _sign_stripe_event(payload, secret)

    resp = await client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": sig, "content-type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: AsyncClient, monkeypatch):
    for key, val in [
        ("stripe_secret_key", "sk_test_x"),
        ("stripe_webhook_secret", "whsec_signing"),
        ("stripe_essentials_price_id", "price_ess"),
        ("stripe_pro_price_id", "price_pro"),
    ]:
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", val)
    stripe_client._reset_cache()

    resp = await client.post(
        "/billing/webhook",
        content=b'{"id": "evt_bogus"}',
        headers={
            "stripe-signature": "t=1,v1=badsig",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 400
