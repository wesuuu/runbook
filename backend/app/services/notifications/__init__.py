"""Notification service — public API.

Usage in endpoints:
    from app.services.notifications import send_notification

    background_tasks.add_task(
        send_notification, db, event_type, org_id, entity_type,
        entity_id, recipients, context,
    )
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification
from app.services.notifications.channels.base import FormattedMessage
from app.services.notifications.dispatcher import dispatch_event
from app.services.notifications.templates import TEMPLATES

logger = logging.getLogger("notifications")


async def send_notification(
    db: AsyncSession,
    event_type: str,
    org_id: UUID,
    entity_type: str,
    entity_id: UUID,
    recipients: list[UUID],
    context: dict,
) -> None:
    """Main entry point: create in-app notifications and dispatch to channels.

    Args:
        db: Async database session.
        event_type: NotificationEventType value (e.g. "ROLE_ASSIGNED").
        org_id: Organization ID for org-level channel lookup.
        entity_type: Entity type for deep linking (e.g. "run", "protocol").
        entity_id: Entity UUID for deep linking.
        recipients: List of user IDs to notify.
        context: Template variables (run_name, role_name, etc.).
    """
    template_fn = TEMPLATES.get(event_type)
    if not template_fn:
        logger.warning("No template for event type: %s", event_type)
        return

    # Generate both message perspectives
    title_personal, body_personal = template_fn(context, personal=True)
    title_broadcast, body_broadcast = template_fn(context, personal=False)

    # 1. Create in-app notification records
    for user_id in recipients:
        notif = Notification(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title_personal,
            message=body_personal,
        )
        db.add(notif)

    await db.flush()

    # 2. Dispatch to external channels (org-level + user-level)
    msg_personal = FormattedMessage(
        event_type=event_type,
        title=title_personal,
        body=body_personal,
        recipient="",  # filled per-channel
    )
    msg_broadcast = FormattedMessage(
        event_type=event_type,
        title=title_broadcast,
        body=body_broadcast,
        recipient="broadcast",
    )

    try:
        await dispatch_event(
            db=db,
            event_type=event_type,
            org_id=org_id,
            recipients=recipients,
            message_personal=msg_personal,
            message_broadcast=msg_broadcast,
        )
    except Exception:
        logger.exception("Failed to dispatch notifications for %s", event_type)

    await db.commit()
