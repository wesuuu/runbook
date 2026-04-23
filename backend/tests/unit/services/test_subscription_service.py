from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.iam import Organization, User
from app.services.billing import stripe_client, subscription_service


@pytest.fixture(autouse=True)
def reset_stripe_cache():
    yield
    stripe_client._reset_cache()


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.Customer.create.return_value = MagicMock(id="cus_test_123")
    trial_end_ts = int(
        datetime(2026, 5, 23, tzinfo=timezone.utc).timestamp()
    )
    period_end_ts = int(
        datetime(2026, 6, 23, tzinfo=timezone.utc).timestamp()
    )
    fake.Subscription.create.return_value = MagicMock(
        id="sub_test_456",
        status="trialing",
        trial_end=trial_end_ts,
        current_period_end=period_end_ts,
        cancel_at_period_end=False,
    )
    stripe_client.set_fake_client(fake)
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key",
        "sk_test_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_webhook_secret",
        "whsec_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_essentials_price_id",
        "price_ess",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_pro_price_id",
        "price_pro",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.essentials_trial_days",
        30,
    )
    return fake


@pytest.mark.asyncio
async def test_create_trial_subscription_creates_customer_and_subscription(
    db_session, fake_stripe
):
    org = Organization(name="Test Co")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    result = await subscription_service.create_trial_subscription(
        db_session, org, user
    )

    assert result.stripe_customer_id == "cus_test_123"
    assert result.stripe_subscription_id == "sub_test_456"
    assert result.subscription_status == "trialing"
    assert result.trial_end is not None
    assert result.current_period_end is not None

    fake_stripe.Customer.create.assert_called_once()
    kwargs = fake_stripe.Customer.create.call_args.kwargs
    assert kwargs["email"] == "owner@test.co"
    assert kwargs["name"] == "Test Co"
    assert kwargs["metadata"]["org_id"] == str(org.id)

    fake_stripe.Subscription.create.assert_called_once()
    sub_kwargs = fake_stripe.Subscription.create.call_args.kwargs
    assert sub_kwargs["customer"] == "cus_test_123"
    assert sub_kwargs["items"] == [{"price": "price_ess"}]
    assert sub_kwargs["trial_period_days"] == 30
    assert (
        sub_kwargs["trial_settings"]["end_behavior"][
            "missing_payment_method"
        ]
        == "cancel"
    )


@pytest.mark.asyncio
async def test_create_trial_subscription_is_idempotent(
    db_session, fake_stripe
):
    org = Organization(
        name="Test Co", stripe_subscription_id="sub_existing_789"
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    result = await subscription_service.create_trial_subscription(
        db_session, org, user
    )

    assert result.stripe_subscription_id == "sub_existing_789"
    fake_stripe.Customer.create.assert_not_called()
    fake_stripe.Subscription.create.assert_not_called()


@pytest.mark.asyncio
async def test_create_trial_subscription_noop_when_unconfigured(
    db_session, monkeypatch, caplog
):
    # No fake_stripe fixture here; Stripe is genuinely unconfigured
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    org = Organization(name="Test Co")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    with caplog.at_level("WARNING"):
        result = await subscription_service.create_trial_subscription(
            db_session, org, user
        )

    assert result.stripe_customer_id is None
    assert result.stripe_subscription_id is None
    assert any("Stripe not configured" in r.message for r in caplog.records)
