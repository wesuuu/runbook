"""Read/write helpers for GlpSignoff. Single source of truth for the
'active sign-off' definition (action=APPROVED AND invalidated_at IS NULL).

Caller manages the transaction (flush/commit); this module never calls
db.commit() so it integrates cleanly with SAVEPOINT-based test sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.science import GlpSignoff


async def list_active_signoffs(
    db: AsyncSession,
    entity_type: Literal["protocol", "run"],
    entity_id: UUID,
) -> Sequence[GlpSignoff]:
    """Return all non-invalidated APPROVED sign-offs for the given entity.

    Results are ordered by signed_at ascending (oldest first). The signer
    relationship is eagerly loaded.
    """
    fk = GlpSignoff.protocol_id if entity_type == "protocol" else GlpSignoff.run_id
    result = await db.execute(
        select(GlpSignoff)
        .where(
            fk == entity_id,
            GlpSignoff.action == "APPROVED",
            GlpSignoff.invalidated_at.is_(None),
        )
        .options(selectinload(GlpSignoff.signer))
        .order_by(GlpSignoff.signed_at)
    )
    return result.scalars().all()


async def get_signoff_by_role(
    db: AsyncSession,
    entity_type: Literal["protocol", "run"],
    entity_id: UUID,
    role: str,
) -> GlpSignoff | None:
    """Return the single active APPROVED sign-off for a specific role, or None."""
    fk = GlpSignoff.protocol_id if entity_type == "protocol" else GlpSignoff.run_id
    result = await db.execute(
        select(GlpSignoff).where(
            fk == entity_id,
            GlpSignoff.role == role,
            GlpSignoff.action == "APPROVED",
            GlpSignoff.invalidated_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def invalidate_active_signoffs(
    db: AsyncSession,
    run_id: UUID,
    *,
    reason: str,
    user_id: UUID,
    superseded_by_reopen_audit_event_id: Optional[UUID] = None,
) -> int:
    """Mark all active sign-offs on a run invalidated. Returns row count.

    When called from the reopen endpoint, pass superseded_by_reopen_audit_event_id
    to distinguish reopen-supersession from edit-invalidation (grilling decision #15).
    When None (e.g. RUN_EDITED), the column is left NULL.

    Caller manages transaction (flush/commit).
    """
    values_dict: dict = {
        "invalidated_at": datetime.now(timezone.utc),
        "invalidated_reason": reason,
        "invalidated_by_id": user_id,
    }
    if superseded_by_reopen_audit_event_id is not None:
        values_dict["superseded_by_reopen_audit_event_id"] = (
            superseded_by_reopen_audit_event_id
        )

    result = await db.execute(
        update(GlpSignoff)
        .where(
            GlpSignoff.run_id == run_id,
            GlpSignoff.action == "APPROVED",
            GlpSignoff.invalidated_at.is_(None),
        )
        .values(**values_dict)
    )
    await db.flush()
    return result.rowcount or 0
