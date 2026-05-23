"""Auto-provisioning of the default per-user EMAIL notification channel.

Called from two places:

1. A SQLAlchemy after_insert event on User, drained by the request-end
   hook in app.db.session.get_db. Covers every user-creation path.
2. The backfill migration (td0091c_c) -- for any users that exist
   before this feature lands.

Idempotent. Safe to call repeatedly.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.iam import User
from app.models.notifications import NotificationChannel, NotificationSubscription
from app.services.core.notifications.policy import DEFAULT_POLICY

logger = logging.getLogger("notifications.provisioning")


async def ensure_default_user_channel(
    db: AsyncSession, user_id: UUID
) -> NotificationChannel:
    """Idempotently create the user's default EMAIL channel + default subs.

    Uses SAVEPOINT (begin_nested) so a unique-index race rolls back only
    the failed INSERT, not the caller's outer transaction.
    """
    existing = (
        await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.channel_type == "EMAIL",
                NotificationChannel.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        channel = existing
    else:
        user = await db.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        channel = NotificationChannel(
            user_id=user_id,
            org_id=None,
            name="Email",
            channel_type="EMAIL",
            config={"to": user.email},
            enabled=True,
            is_default=True,
        )
        try:
            async with db.begin_nested():
                db.add(channel)
                await db.flush()
        except IntegrityError:
            logger.warning(
                "Default channel race for user %s; re-fetching", user_id
            )
            channel = (
                await db.execute(
                    select(NotificationChannel).where(
                        NotificationChannel.user_id == user_id,
                        NotificationChannel.channel_type == "EMAIL",
                        NotificationChannel.is_default.is_(True),
                    )
                )
            ).scalar_one()

    existing_event_types = {
        row[0]
        for row in (
            await db.execute(
                select(NotificationSubscription.event_type).where(
                    NotificationSubscription.channel_id == channel.id
                )
            )
        ).all()
    }
    for event_type, policy in DEFAULT_POLICY.items():
        if not policy.email or event_type in existing_event_types:
            continue
        try:
            async with db.begin_nested():
                db.add(
                    NotificationSubscription(
                        channel_id=channel.id,
                        event_type=event_type,
                        enabled=True,
                    )
                )
                await db.flush()
        except IntegrityError:
            pass
    return channel


async def provision_default_channel_for_user(user_id: UUID) -> None:
    """Open an isolated session and provision the channel for `user_id`.

    Called from a fire-and-forget queue drained at request end, so it
    must not depend on the caller's session.
    """
    async with AsyncSessionLocal() as session:
        try:
            await ensure_default_user_channel(session, user_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed to provision default channel for user %s", user_id
            )
