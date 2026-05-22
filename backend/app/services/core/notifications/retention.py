"""Retention sweep for in-app notifications.

Read notifications older than the retention window are hard-deleted to
bound the ``notifications`` table's growth. Unread notifications are kept
regardless of age.

This sweep touches only the ``notifications`` (inbox) table. External
``notification_deliveries`` rows are a separate audit trail — the
dispatcher records them with ``notification_id`` left NULL, so they are
not children of inbox rows and a purge cannot affect them. (The FK is
``ON DELETE SET NULL`` purely as a defensive contract should the two
ever be linked; see ``test_delivery_survives_purge_with_null_fk``.)
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification

logger = logging.getLogger("notifications.retention")

# Rows deleted per statement. Bounds lock duration and WAL volume on the
# first sweep against a large unpurged table.
PURGE_CHUNK_SIZE = 500


async def purge_read_notifications(
    db: AsyncSession, *, older_than_days: int
) -> int:
    """Hard-delete read notifications older than ``older_than_days``.

    Deletes in ``PURGE_CHUNK_SIZE`` chunks, committing after each chunk,
    until a chunk deletes fewer than a full batch. Unread rows are never
    deleted. ``older_than_days <= 0`` is a no-op returning 0.

    Args:
        db: Database session.
        older_than_days: Age threshold; read notifications whose
            ``read_at`` is older than this many days are eligible.

    Returns:
        Total number of rows deleted.
    """
    if older_than_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    eligible = (
        select(Notification.id)
        .where(Notification.read_at.is_not(None))
        .where(Notification.read_at < cutoff)
        # Deterministic chunk membership: ix_notif_read_at is already
        # ordered on read_at, so the ORDER BY is free and makes the
        # `deleted < PURGE_CHUNK_SIZE` termination reliable.
        .order_by(Notification.read_at)
        .limit(PURGE_CHUNK_SIZE)
    )
    stmt = delete(Notification).where(Notification.id.in_(eligible))

    total = 0
    try:
        while True:
            result = await db.execute(stmt)
            deleted = result.rowcount or 0
            await db.commit()
            total += deleted
            if deleted < PURGE_CHUNK_SIZE:
                break
    except Exception:
        # Chunks already committed are irreversible — surface how far the
        # sweep got before the failure rather than losing the count.
        logger.exception(
            "Retention sweep interrupted after deleting %d read "
            "notifications",
            total,
        )
        raise

    logger.debug(
        "Retention sweep deleted %d read notifications older than %d days",
        total,
        older_than_days,
    )
    return total
