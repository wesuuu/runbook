import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.billing import StripeEvent
from app.models.execution import AuditLog
from app.models.iam import Organization
from app.services.billing import webhook_handler

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "stripe"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
async def org_with_pro_trial(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.billing.webhook_handler.settings.stripe_essentials_price_id",
        "price_ess",
    )
    monkeypatch.setattr(
        "app.services.billing.webhook_handler.settings.stripe_pro_price_id",
        "price_pro",
    )
    org = Organization(
        name="Test",
        stripe_customer_id="cus_test_123",
        stripe_subscription_id="sub_test_456",
        subscription_tier="essentials",
        subscription_status="trialing",
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest.mark.asyncio
async def test_subscription_updated_upgrade_flips_tier_and_writes_audit(
    db_session, org_with_pro_trial
):
    event = _load("customer_subscription_updated_upgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_tier == "pro"
    assert org_with_pro_trial.subscription_status == "active"
    assert org_with_pro_trial.cancel_at_period_end is False

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.entity_id == org_with_pro_trial.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(
        row.action == "UPDATE"
        and "subscription_tier" in (row.changes or {})
        and row.changes["subscription_tier"] == ["essentials", "pro"]
        for row in audit_rows
    )


@pytest.mark.asyncio
async def test_subscription_updated_downgrade_sets_cancel_flag_no_tier_change(
    db_session, org_with_pro_trial
):
    org_with_pro_trial.subscription_tier = "pro"
    org_with_pro_trial.subscription_status = "active"
    await db_session.flush()

    event = _load("customer_subscription_updated_downgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_tier == "pro"
    assert org_with_pro_trial.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_subscription_deleted_sets_canceled_and_writes_audit(
    db_session, org_with_pro_trial
):
    event = _load("customer_subscription_deleted")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_status == "canceled"

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.entity_id == org_with_pro_trial.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(
        row.action == "UPDATE"
        and row.changes
        and row.changes.get("subscription_status") == ["trialing", "canceled"]
        for row in audit_rows
    )


@pytest.mark.asyncio
async def test_invoice_payment_failed_sets_past_due(db_session, org_with_pro_trial):
    org_with_pro_trial.subscription_status = "active"
    await db_session.flush()

    event = _load("invoice_payment_failed")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_status == "past_due"


@pytest.mark.asyncio
async def test_handle_event_is_idempotent(db_session, org_with_pro_trial):
    event = _load("customer_subscription_updated_upgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.entity_id == org_with_pro_trial.id)
            )
        )
        .scalars()
        .all()
    )
    tier_change_rows = [
        r for r in audit_rows if r.changes and "subscription_tier" in r.changes
    ]
    assert len(tier_change_rows) == 1  # second apply was a no-op

    events_seen = (
        (
            await db_session.execute(
                select(StripeEvent).where(StripeEvent.stripe_event_id == event["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(events_seen) == 1


@pytest.mark.asyncio
async def test_handle_event_unknown_customer_logs_and_returns(db_session, caplog):
    event = _load("customer_subscription_updated_upgrade")
    with caplog.at_level("WARNING"):
        await webhook_handler.handle_event(db_session, event)
        await db_session.flush()

    events_seen = (
        (
            await db_session.execute(
                select(StripeEvent).where(StripeEvent.stripe_event_id == event["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(events_seen) == 1
    assert any("no matching org" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_subscription_updated_caches_has_payment_method(
    db_session, org_with_pro_trial, monkeypatch
):
    from unittest.mock import MagicMock

    from app.services.billing import stripe_client

    fake = MagicMock()
    fake.Customer.retrieve.return_value = MagicMock(
        invoice_settings=MagicMock(default_payment_method="pm_test_card")
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", "x")

    event = _load("customer_subscription_updated_upgrade")
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await db_session.refresh(org_with_pro_trial)

    assert org_with_pro_trial.has_payment_method is True
    fake.Customer.retrieve.assert_called_with("cus_test_123")
    stripe_client._reset_cache()


@pytest.mark.asyncio
async def test_subscription_updated_reflects_no_payment_method(
    db_session, org_with_pro_trial, monkeypatch
):
    from unittest.mock import MagicMock

    from app.services.billing import stripe_client

    fake = MagicMock()
    fake.Customer.retrieve.return_value = MagicMock(
        invoice_settings=MagicMock(default_payment_method=None)
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(f"app.services.billing.stripe_client.settings.{key}", "x")

    org_with_pro_trial.has_payment_method = True
    await db_session.flush()

    event = _load("customer_subscription_updated_upgrade")
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await db_session.refresh(org_with_pro_trial)

    assert org_with_pro_trial.has_payment_method is False
    stripe_client._reset_cache()
