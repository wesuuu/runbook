from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization, User
from app.services.billing import stripe_client


@pytest.fixture(autouse=True)
def reset_stripe_cache():
    yield
    stripe_client._reset_cache()


@pytest.fixture
def configured_fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.Customer.create.return_value = MagicMock(id="cus_reg_111")
    fake.Subscription.create.return_value = MagicMock(
        id="sub_reg_222",
        status="trialing",
        trial_end=1716000000,
        current_period_end=1718000000,
        cancel_at_period_end=False,
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


@pytest.mark.asyncio
async def test_register_creates_trial_subscription_when_stripe_configured(
    client: AsyncClient, db_session, configured_fake_stripe
):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "password123",
            "full_name": "New User",
        },
    )
    assert resp.status_code == 200

    user = (await db_session.execute(
        select(User).where(User.email == "newuser@example.com")
    )).scalar_one()
    org = (await db_session.execute(
        select(Organization).where(Organization.id == user.selected_org_id)
    )).scalar_one()

    assert org.stripe_customer_id == "cus_reg_111"
    assert org.stripe_subscription_id == "sub_reg_222"
    assert org.subscription_status == "trialing"


@pytest.mark.asyncio
async def test_register_succeeds_without_stripe_configured(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    resp = await client.post(
        "/auth/register",
        json={
            "email": "unconfigured@example.com",
            "password": "password123",
            "full_name": "NC User",
        },
    )
    assert resp.status_code == 200

    user = (await db_session.execute(
        select(User).where(User.email == "unconfigured@example.com")
    )).scalar_one()
    org = (await db_session.execute(
        select(Organization).where(Organization.id == user.selected_org_id)
    )).scalar_one()

    assert org.stripe_customer_id is None
    assert org.stripe_subscription_id is None
