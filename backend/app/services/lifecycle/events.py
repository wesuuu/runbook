"""High-level lifecycle events emitted to Loops.

Each function takes domain objects (User, Organization) and translates them
into Loops REST calls. This is the ONLY place the rest of the app interacts
with Loops -- call sites should never import loops_client directly.

Event names documented in docs/loops-campaigns.md; change them only in
coordination with the Loops dashboard workflow triggers.

Synced contact properties (see docs/loops-campaigns.md for the privacy note):
  email, firstName (if known), org_id, org_name, plan, status,
  trial_end (ISO date), days_in_trial (int at signup).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.iam import Organization, User
from app.services.lifecycle import loops_client

logger = logging.getLogger(__name__)


def emit_signup(user: User, org: Organization) -> None:
    """New user finished registration. Creates the Loops contact + fires event."""
    try:
        props = _contact_properties(user, org)
        props["days_in_trial"] = _days_in_trial(org)
        loops_client.contacts_create(email=user.email, properties=props)
        loops_client.events_send(
            email=user.email,
            event_name="signed_up",
            event_properties={},
            contact_properties=props,
        )
    except Exception:
        logger.exception("emit_signup failed for user %s", user.email)


def emit_trial_started(user: User, org: Organization) -> None:
    """Trial subscription was created for the org. Keeps trial_end fresh."""
    try:
        props = _contact_properties(user, org)
        loops_client.events_send(
            email=user.email,
            event_name="trial_started",
            event_properties={},
            contact_properties=props,
        )
    except Exception:
        logger.exception("emit_trial_started failed for user %s", user.email)


def emit_subscription_changed(
    user: User,
    org: Organization,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    """Org tier or status changed (from Stripe webhook).

    `before` and `after` are each {"tier": str, "status": str} snapshots.
    Event properties expose both so Loops workflows can branch on the
    direction of change (e.g., upgrade vs downgrade).
    """
    try:
        loops_client.events_send(
            email=user.email,
            event_name="subscription_changed",
            event_properties={
                "previous_plan": before.get("tier"),
                "new_plan": after.get("tier"),
                "previous_status": before.get("status"),
                "new_status": after.get("status"),
            },
            contact_properties=_contact_properties(user, org),
        )
    except Exception:
        logger.exception("emit_subscription_changed failed for user %s", user.email)


def emit_trial_expired(user: User, org: Organization) -> None:
    """Trial subscription was deleted without payment method."""
    try:
        loops_client.events_send(
            email=user.email,
            event_name="trial_expired",
            event_properties={},
            contact_properties=_contact_properties(user, org),
        )
    except Exception:
        logger.exception("emit_trial_expired failed for user %s", user.email)


def _contact_properties(user: User, org: Organization) -> dict[str, Any]:
    props: dict[str, Any] = {
        "org_id": str(org.id) if org.id is not None else None,
        "org_name": org.name,
        "plan": org.subscription_tier,
        "status": org.subscription_status,
        "trial_end": _iso_date(org.trial_end),
    }
    first_name = _first_name(user.full_name)
    if first_name:
        props["firstName"] = first_name
    # Drop None values so we never overwrite Loops properties with null.
    return {k: v for k, v in props.items() if v is not None}


def _first_name(full_name: Optional[str]) -> Optional[str]:
    if not full_name:
        return None
    parts = full_name.strip().split()
    return parts[0] if parts else None


def _iso_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.date().isoformat()


def _days_in_trial(org: Organization) -> int:
    """Calendar days between now and trial_end; 0 when trial_end is absent."""
    if org.trial_end is None:
        return 0
    delta = org.trial_end - datetime.now(timezone.utc)
    return max(0, delta.days + (1 if delta.seconds > 0 else 0))
