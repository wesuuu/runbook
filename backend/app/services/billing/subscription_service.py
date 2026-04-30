"""Organization-facing billing operations: trial subscription, portal session, state.

All functions are async, take a db session, and commit caller-side so they
integrate cleanly into endpoint transactions. Stripe-unconfigured calls
log a warning and no-op (tests assert this) so the app boots without keys.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iam import Organization, User
from app.services.billing import stripe_client

logger = logging.getLogger(__name__)


async def create_trial_subscription(
    db: AsyncSession, org: Organization, user: User
) -> Organization:
    """Create a Stripe customer + trialing Essentials subscription for a new org.

    Idempotent: if `org.stripe_subscription_id` is already set, return the org
    unchanged. No-op with a warning when Stripe is unconfigured (registration
    must not fail just because billing isn't set up locally).

    Does not commit; the caller owns transaction scope.
    """
    if org.stripe_subscription_id:
        return org

    if not stripe_client.is_configured():
        logger.warning(
            "Stripe not configured; skipping trial subscription for org %s",
            org.id,
        )
        return org

    stripe = stripe_client.get_stripe()

    customer = stripe.Customer.create(
        email=user.email,
        name=org.name,
        metadata={
            "org_id": str(org.id),
            "user_id": str(user.id),
        },
    )

    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": settings.stripe_essentials_price_id}],
        trial_period_days=settings.essentials_trial_days,
        trial_settings={"end_behavior": {"missing_payment_method": "cancel"}},
        metadata={"org_id": str(org.id)},
    )

    org.stripe_customer_id = customer.id
    org.stripe_subscription_id = subscription.id
    org.subscription_status = subscription.status
    org.trial_end = _ts_to_dt(getattr(subscription, "trial_end", None))
    org.current_period_end = _ts_to_dt(
        getattr(subscription, "current_period_end", None)
    )
    org.cancel_at_period_end = bool(
        getattr(subscription, "cancel_at_period_end", False)
    )
    return org


def _ts_to_dt(ts: Optional[int]) -> Optional[datetime]:
    """Stripe returns Unix timestamps; convert to timezone-aware datetime."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


async def create_portal_session(org: Organization, return_url: str) -> str:
    """Create a Stripe Customer Portal session URL for this org's customer."""
    if not org.stripe_customer_id:
        raise ValueError(
            f"Organization {org.id} has no Stripe customer; "
            "cannot open a billing portal session."
        )

    stripe = stripe_client.get_stripe()
    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=return_url,
    )
    return session.url


_LOCKED_OUT_STATUSES = {"canceled", "past_due", "unpaid"}


def get_subscription_state(org: Organization) -> dict:
    """Read-only projection of the org's current billing state.

    Reads columns populated by the registration flow and webhook handler;
    does not hit Stripe. Adds two derived fields:
      - days_remaining_in_trial: int when status=trialing, else None
      - is_locked_out: True when status in LOCKED_OUT_STATUSES
    """
    days_remaining: Optional[int] = None
    if org.subscription_status == "trialing" and org.trial_end is not None:
        now = datetime.now(timezone.utc)
        delta = org.trial_end - now
        days_remaining = max(0, (delta.days + (1 if delta.seconds > 0 else 0)))

    return {
        "tier": org.subscription_tier,
        "status": org.subscription_status,
        "trial_end": org.trial_end,
        "days_remaining_in_trial": days_remaining,
        "current_period_end": org.current_period_end,
        "cancel_at_period_end": org.cancel_at_period_end,
        "has_payment_method": org.has_payment_method,
        "is_locked_out": org.subscription_status in _LOCKED_OUT_STATUSES,
    }
