import pytest

from app.services.billing import stripe_client


def test_get_stripe_returns_stripe_module_when_configured(monkeypatch):
    """get_stripe() returns the real stripe module when secret key is set."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key",
        "sk_test_fake",
    )
    # Reset the cached client so the monkeypatch takes effect
    stripe_client._reset_cache()

    client = stripe_client.get_stripe()

    import stripe as real_stripe

    assert client is real_stripe
    assert real_stripe.api_key == "sk_test_fake"


def test_get_stripe_raises_when_unconfigured(monkeypatch):
    """get_stripe() raises BillingUnconfiguredError when no secret key."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    with pytest.raises(stripe_client.BillingUnconfiguredError):
        stripe_client.get_stripe()


def test_is_configured_true_when_all_keys_set(monkeypatch):
    """is_configured() returns True iff all required keys are set."""
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

    assert stripe_client.is_configured() is True


def test_is_configured_false_when_any_key_missing(monkeypatch):
    """is_configured() returns False when any required key is empty."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    assert stripe_client.is_configured() is False


def test_set_fake_client_injects_for_tests(monkeypatch):
    """set_fake_client replaces the stripe module for tests; cleared via _reset_cache."""
    fake = object()
    stripe_client.set_fake_client(fake)
    assert stripe_client.get_stripe() is fake

    stripe_client._reset_cache()
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    with pytest.raises(stripe_client.BillingUnconfiguredError):
        stripe_client.get_stripe()
