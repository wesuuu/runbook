"""Stripe Python SDK adapter.

Single point where we configure stripe.api_key from settings. Provides a
get_stripe() accessor that callers use instead of importing `stripe`
directly; this makes it possible to inject a fake during tests via
set_fake_client().
"""

from typing import Any

from app.core.config import settings


class BillingUnconfiguredError(RuntimeError):
    """Raised when billing code is invoked but Stripe config is missing."""


_cached_client: Any = None
_fake_client: Any = None


def _reset_cache() -> None:
    """Clear cached client. Test-only; not part of public API."""
    global _cached_client, _fake_client
    _cached_client = None
    _fake_client = None


def set_fake_client(fake: Any) -> None:
    """Inject a fake stripe-like object for tests.

    Once called, get_stripe() returns this object instead of the real
    stripe module until _reset_cache() is called.
    """
    global _fake_client
    _fake_client = fake


def is_configured() -> bool:
    """True iff all required Stripe settings are populated."""
    return bool(
        settings.stripe_secret_key
        and settings.stripe_webhook_secret
        and settings.stripe_essentials_price_id
        and settings.stripe_pro_price_id
    )


def get_stripe() -> Any:
    """Return the configured stripe module (or injected fake).

    Raises BillingUnconfiguredError if no secret key is set and no fake
    has been injected.
    """
    global _cached_client
    if _fake_client is not None:
        return _fake_client
    if _cached_client is not None:
        return _cached_client

    if not settings.stripe_secret_key:
        raise BillingUnconfiguredError(
            "Stripe is not configured (BATCHRITE_STRIPE_SECRET_KEY unset)."
        )

    import stripe

    stripe.api_key = settings.stripe_secret_key
    _cached_client = stripe
    return stripe
