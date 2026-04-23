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
        trial_settings={
            "end_behavior": {"missing_payment_method": "cancel"}
        },
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
