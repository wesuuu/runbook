"""Helpers for fulfilling open GLP signoff requests.

This module replaces the legacy events writer that targeted the
retired F-0066 protocol-approval table. After F-0087 Task 27, all
signature events flow through ``glp_signoffs`` (via
``services.signoffs.service.create_signoff``); the only thing that
remains here is the per-user request queue, which lives in
``glp_signoff_requests`` and is updated when the protocol's overall
status flips from PENDING_APPROVAL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import GlpSignoffRequest

VALID_FULFILL_STATES = ("APPROVED", "REJECTED", "WITHDRAWN")


async def fulfill_open_requests(
    db: AsyncSession,
    *,
    protocol_id: uuid.UUID,
    final_status: str,
    actor_id: Optional[uuid.UUID],
) -> int:
    """Mark all OPEN approval requests for a protocol as fulfilled.

    Operates on ``glp_signoff_requests`` (Task 7 rename); this function
    survived the Task 27 cutover and the GlpSignoffRequest queue
    continues to track per-user OPEN/APPROVED/REJECTED/WITHDRAWN state.

    Caller manages the transaction (flush/commit).
    """
    if final_status not in VALID_FULFILL_STATES:
        raise ValueError(f"invalid final_status {final_status!r}")
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(GlpSignoffRequest)
        .where(
            GlpSignoffRequest.protocol_id == protocol_id,
            GlpSignoffRequest.status == "OPEN",
        )
        .values(status=final_status, fulfilled_at=now, fulfilled_by_id=actor_id)
    )
    return result.rowcount or 0
