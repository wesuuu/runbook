"""Per-event default delivery policy.

Single source of truth for which channels Batchrite uses for each event
out of the box. Drives the seed set of NotificationSubscription rows that
are created when a user is provisioned (see provisioning.py). Not
consulted at dispatch time -- once subscriptions exist, the subscription
table is authoritative, so a user opting out stays opted out.
"""

from dataclasses import dataclass

from app.models.notifications import NotificationEventType


@dataclass(frozen=True)
class DeliveryPolicy:
    in_app: bool = True
    email: bool = False


DEFAULT_POLICY: dict[str, DeliveryPolicy] = {
    NotificationEventType.RUN_STARTED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_ASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_REASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.ROLE_UNASSIGNED.value: DeliveryPolicy(True, True),
    NotificationEventType.INVITE_SENT.value: DeliveryPolicy(True, True),
    NotificationEventType.INVITE_ACCEPTED.value: DeliveryPolicy(True, False),
    NotificationEventType.PROTOCOL_APPROVAL_REQUESTED.value: DeliveryPolicy(
        True, True
    ),
    NotificationEventType.PROTOCOL_APPROVED.value: DeliveryPolicy(True, True),
    NotificationEventType.PROTOCOL_REVERTED.value: DeliveryPolicy(True, False),
    NotificationEventType.RUN_SIGNOFF_REQUESTED.value: DeliveryPolicy(True, True),
    NotificationEventType.RUN_SIGNOFF_CANCELLED.value: DeliveryPolicy(True, False),
    NotificationEventType.RUN_COMPLETED.value: DeliveryPolicy(True, False),
    NotificationEventType.STEP_DEVIATION.value: DeliveryPolicy(True, False),
    NotificationEventType.PENDING_IMAGE_ANALYSIS.value: DeliveryPolicy(True, False),
    NotificationEventType.OFFLINE_SYNC_PENDING.value: DeliveryPolicy(True, False),
}


def policy_for(event_type: str) -> DeliveryPolicy:
    """Look up the delivery policy for an event type. Unknown -> safe default."""
    return DEFAULT_POLICY.get(event_type, DeliveryPolicy())
