"""Dispatch Stripe webhook events and reconcile org billing state.

Contract:
  - Called with a parsed event dict (already signature-verified by the endpoint).
  - Idempotent: writes a StripeEvent row keyed by event ID; duplicate deliveries
    short-circuit before mutating org state.
  - Writes audit log entries on subscription_tier or subscription_status changes
    with before/after values.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import StripeEvent
from app.models.iam import Organization, OrganizationMember, OrgRole, User
from app.services.billing import stripe_client
from app.services.core.audit import SYSTEM_ACTOR_ID, log_audit
from app.services.lifecycle import events as lifecycle_events

logger = logging.getLogger(__name__)


async def handle_event(db: AsyncSession, event: dict[str, Any]) -> None:
    """Dispatch a Stripe webhook event.

    Called from POST /billing/webhook after signature verification. Does not
    commit; the caller owns transaction scope.
    """
    event_id = event["id"]
    event_type = event["type"]

    # Idempotency: has this event ID been processed before?
    existing = await db.execute(
        select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(
            "Stripe event %s (%s) already processed; skipping.",
            event_id,
            event_type,
        )
        return

    # Mark the event as seen BEFORE mutating state so a crash between mutation
    # and commit still leaves us idempotent on retry (caller's transaction
    # rolls back the StripeEvent row too, which is fine — Stripe retries).
    db.add(StripeEvent(stripe_event_id=event_id, event_type=event_type))

    handlers = {
        "customer.subscription.created": _apply_subscription_state,
        "customer.subscription.updated": _apply_subscription_state,
        "customer.subscription.deleted": _apply_subscription_deleted,
        "invoice.payment_failed": _apply_invoice_payment_failed,
        "checkout.session.completed": _apply_checkout_completed,
    }
    handler = handlers.get(event_type)
    if handler is None:
        logger.info("Ignoring unhandled Stripe event type: %s", event_type)
        return

    await handler(db, event["data"]["object"])


async def _apply_subscription_state(
    db: AsyncSession, subscription: dict[str, Any]
) -> None:
    """Reconcile org state from a subscription.created or subscription.updated payload."""
    customer_id = subscription["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe subscription event for customer %s has no matching org",
            customer_id,
        )
        return

    new_tier = _tier_from_price_id(_price_id(subscription))
    new_status = subscription["status"]
    changes: dict[str, list[Any]] = {}
    if new_tier is not None and org.subscription_tier != new_tier:
        changes["subscription_tier"] = [org.subscription_tier, new_tier]
        org.subscription_tier = new_tier
    if org.subscription_status != new_status:
        changes["subscription_status"] = [org.subscription_status, new_status]
        org.subscription_status = new_status

    org.stripe_subscription_id = subscription["id"]
    org.trial_end = _ts_to_dt(subscription.get("trial_end"))
    org.current_period_end = _ts_to_dt(subscription.get("current_period_end"))
    org.cancel_at_period_end = bool(subscription.get("cancel_at_period_end", False))

    # Refresh has_payment_method by checking the customer's default PM.
    # If Stripe is unreachable here, log and keep the existing value
    # rather than failing the webhook (avoids blocking status updates).
    try:
        stripe = stripe_client.get_stripe()
        customer = stripe.Customer.retrieve(customer_id)
        pm = getattr(
            getattr(customer, "invoice_settings", None),
            "default_payment_method",
            None,
        )
        org.has_payment_method = pm is not None
    except Exception:
        logger.exception(
            "Failed to refresh has_payment_method for customer %s",
            customer_id,
        )

    if changes:
        await log_audit(
            db,
            actor_id=SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes=changes,
        )
        # Notify Loops on tier or status change (F-0019c).
        user = await _primary_user(db, org)
        if user is not None:
            before = {
                "tier": changes.get("subscription_tier", [org.subscription_tier])[0],
                "status": changes.get("subscription_status", [org.subscription_status])[
                    0
                ],
            }
            after = {
                "tier": org.subscription_tier,
                "status": org.subscription_status,
            }
            lifecycle_events.emit_subscription_changed(
                user, org, before=before, after=after
            )


async def _apply_subscription_deleted(
    db: AsyncSession, subscription: dict[str, Any]
) -> None:
    customer_id = subscription["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe subscription.deleted for customer %s has no matching org",
            customer_id,
        )
        return

    changes: dict[str, list[Any]] = {}
    if org.subscription_status != "canceled":
        changes["subscription_status"] = [org.subscription_status, "canceled"]
        org.subscription_status = "canceled"
    # Defensive: revert tier to essentials if somehow left on pro
    if org.subscription_tier == "pro":
        changes["subscription_tier"] = ["pro", "essentials"]
        org.subscription_tier = "essentials"

    org.cancel_at_period_end = False

    if changes:
        await log_audit(
            db,
            actor_id=SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes=changes,
        )

    # Fire trial_expired for the org's primary user regardless of whether
    # the status flip was net-new (Stripe may retry with no changes).
    user = await _primary_user(db, org)
    if user is not None:
        lifecycle_events.emit_trial_expired(user, org)


async def _apply_invoice_payment_failed(
    db: AsyncSession, invoice: dict[str, Any]
) -> None:
    customer_id = invoice["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe invoice.payment_failed for customer %s has no matching org",
            customer_id,
        )
        return

    if org.subscription_status != "past_due":
        await log_audit(
            db,
            actor_id=SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes={"subscription_status": [org.subscription_status, "past_due"]},
        )
        org.subscription_status = "past_due"


async def _apply_checkout_completed(
    db: AsyncSession, session_obj: dict[str, Any]
) -> None:
    # We don't use Checkout directly (Portal handles upgrades), but handle
    # defensively in case Stripe fires this during Portal-driven flows.
    # Reconciliation happens via the subsequent subscription.updated event.
    logger.info(
        "Received checkout.session.completed for customer %s; "
        "awaiting subscription.updated for state reconciliation.",
        session_obj.get("customer"),
    )


async def _org_by_customer(
    db: AsyncSession, customer_id: str
) -> Optional[Organization]:
    result = await db.execute(
        select(Organization).where(Organization.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _primary_user(db: AsyncSession, org: Organization) -> Optional[User]:
    """Resolve the org's billing contact for lifecycle events.

    Uses the earliest-joined ADMIN (the registrant who created the org
    in the standard flow); falls back to the earliest active member.
    Returns None when the org has no resolvable users -- lifecycle emit
    is skipped in that case (no-op, logged upstream in loops_client).
    """
    stmt = (
        select(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.archived == False,  # noqa: E712
            OrganizationMember.roles.contains([OrgRole.ADMIN.value]),
        )
        .order_by(OrganizationMember.created_at.asc())
        .limit(1)
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is not None:
        return user

    fallback = (
        select(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.archived == False,  # noqa: E712
        )
        .order_by(OrganizationMember.created_at.asc())
        .limit(1)
    )
    return (await db.execute(fallback)).scalar_one_or_none()


def _price_id(subscription: dict[str, Any]) -> Optional[str]:
    items = subscription.get("items", {}).get("data", [])
    if not items:
        return None
    return items[0].get("price", {}).get("id")


def _tier_from_price_id(price_id: Optional[str]) -> Optional[str]:
    if price_id is None:
        return None
    if price_id == settings.stripe_essentials_price_id:
        return "essentials"
    if price_id == settings.stripe_pro_price_id:
        return "pro"
    return None


def _ts_to_dt(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)
