"""Billing endpoints (F-0019a).

All endpoints (except /webhook) require the BILLING role on the user's
selected org. Webhook handler uses signature verification instead.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_org_role
from app.db.session import get_db
from app.models.iam import Organization, OrgRole, User
from app.schemas.billing import (
    PortalSessionRequest,
    PortalSessionResponse,
    SubscriptionStateResponse,
)
from app.services.billing import (
    seat_limits,
    stripe_client,
    subscription_service,
    webhook_handler,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_configured() -> None:
    if not stripe_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Billing is not configured in this environment. "
                "Contact an administrator."
            ),
        )


@router.get("/subscription", response_model=SubscriptionStateResponse)
async def get_subscription(
    user: User = Depends(require_org_role(OrgRole.BILLING)),
    db: AsyncSession = Depends(get_db),
):
    _require_configured()
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    state = subscription_service.get_subscription_state(org)
    seat_count = await seat_limits.get_seat_count(db, org.id)
    seat_limit = seat_limits.get_seat_limit(org.subscription_tier)
    state["seat_count"] = seat_count
    state["seat_limit"] = seat_limit
    state["seat_limit_exceeded"] = seat_limit is not None and seat_count > seat_limit
    return SubscriptionStateResponse(**state)


@router.post("/portal-session", response_model=PortalSessionResponse)
async def create_portal_session(
    body: PortalSessionRequest,
    user: User = Depends(require_org_role(OrgRole.BILLING)),
    db: AsyncSession = Depends(get_db),
):
    _require_configured()
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    # Lazy-provision for orgs that predate F-0019a (seeded orgs or orgs
    # whose registration ran before Stripe was configured). Idempotent —
    # returns the org unchanged if a subscription_id is already set.
    if not org.stripe_customer_id:
        await subscription_service.create_trial_subscription(db, org, user)
        await db.commit()
        await db.refresh(org)
    return_url = body.return_url or settings.stripe_portal_return_url
    try:
        url = await subscription_service.create_portal_session(org, return_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PortalSessionResponse(url=url)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    _require_configured()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe = stripe_client.get_stripe()
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except Exception as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    if hasattr(event, "to_dict_recursive"):
        event_dict = event.to_dict_recursive()
    else:
        event_dict = dict(event)

    try:
        await webhook_handler.handle_event(db, event_dict)
        await db.commit()
    except Exception:
        event_id = event.get("id") if isinstance(event, dict) else event.id
        logger.exception("Stripe webhook handling failed for event %s", event_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Webhook handling failed")

    return {"received": True}
