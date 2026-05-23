"""Notification service — public API.

Usage in endpoints:
    from app.services.core.notifications import send_notification

    background_tasks.add_task(
        send_notification, event_type, org_id, entity_type,
        entity_id, recipients, context,
    )

TD-0091c amendment A: send_notification opens its own AsyncSessionLocal
session so it stays valid after the request session is closed by FastAPI's
BackgroundTasks teardown.
"""

import logging
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.models.notifications import Notification
from app.services.core.notifications.channels.base import FormattedMessage
from app.services.core.notifications.dispatcher import dispatch_event
from app.services.core.notifications.templates import TEMPLATES, TemplateResult


def _unpack_template(result) -> tuple[str, str, str | None]:
    """Accept either a TemplateResult or a legacy (title, body) tuple."""
    if isinstance(result, TemplateResult):
        return result.title, result.body, result.html_body
    title, body = result
    return title, body, None

logger = logging.getLogger("notifications")


async def send_notification(
    event_type: str,
    org_id: UUID,
    entity_type: str,
    entity_id: UUID,
    recipients: list[UUID],
    context: dict,
    payload: dict | None = None,
) -> None:
    """Main entry point: create in-app notifications and dispatch to channels.

    Opens its own AsyncSessionLocal session — safe to call from
    BackgroundTasks after the request session is closed.

    Args:
        event_type: NotificationEventType value (e.g. "ROLE_ASSIGNED").
        org_id: Organization ID for org-level channel lookup.
        entity_type: Entity type for deep linking (e.g. "run", "protocol").
        entity_id: Entity UUID for deep linking.
        recipients: List of user IDs to notify.
        context: Template variables (run_name, role_name, etc.).
        payload: Optional schemaless dict persisted on each Notification.
            TD-0091d: pass {"step_id": "<id>"} (matching
            ^[A-Za-z0-9_-]{1,64}$) for step-scoped events on a run; the
            resolver will append #step-<id> to the deep link.
    """
    template_fn = TEMPLATES.get(event_type)
    if not template_fn:
        logger.warning("No template for event type: %s", event_type)
        return

    title_personal, body_personal, html_body_personal = _unpack_template(
        template_fn(context, personal=True)
    )
    title_broadcast, body_broadcast, html_body_broadcast = _unpack_template(
        template_fn(context, personal=False)
    )

    notif_payload = payload if payload is not None else {}
    async with AsyncSessionLocal() as db:
        try:
            for user_id in recipients:
                db.add(
                    Notification(
                        user_id=user_id,
                        event_type=event_type,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        title=title_personal,
                        message=body_personal,
                        # Per-row dict copy so SQLAlchemy doesn't hand the
                        # same mutable dict to N ORM instances.
                        payload=dict(notif_payload),
                    )
                )
            await db.flush()

            msg_personal = FormattedMessage(
                event_type=event_type,
                title=title_personal,
                body=body_personal,
                recipient="",
                html_body=html_body_personal,
            )
            msg_broadcast = FormattedMessage(
                event_type=event_type,
                title=title_broadcast,
                body=body_broadcast,
                recipient="broadcast",
                html_body=html_body_broadcast,
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
                logger.exception(
                    "Failed to dispatch notifications for %s", event_type
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise
