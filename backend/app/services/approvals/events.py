"""Helpers for writing approval events + audit log atomically."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import (Protocol, ProtocolApprovalEvent,
                                ProtocolApprovalRequest)
from app.services.core.audit import log_audit

VALID_ACTIONS = ("SUBMITTED", "APPROVED", "REJECTED", "REVERTED")
VALID_FULFILL_STATES = ("APPROVED", "REJECTED", "WITHDRAWN")


async def write_event(
    db: AsyncSession,
    *,
    protocol: Protocol,
    actor_id: Optional[uuid.UUID],
    action: str,
    comment: Optional[str] = None,
    signature_statement: Optional[str] = None,
    protocol_version_id: Optional[uuid.UUID] = None,
) -> ProtocolApprovalEvent:
    """Add a ProtocolApprovalEvent + audit log row to the session.

    Caller is responsible for committing the transaction.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid approval action {action!r}")
    event = ProtocolApprovalEvent(
        protocol_id=protocol.id,
        protocol_version_id=protocol_version_id,
        actor_id=actor_id,
        action=action,
        comment=comment,
        signature_statement=signature_statement,
    )
    db.add(event)

    if actor_id is not None:
        try:
            await log_audit(
                db,
                actor_id,
                f"PROTOCOL_APPROVAL_{action}",
                "Protocol",
                protocol.id,
                {
                    "comment": comment,
                    "has_signature_statement": bool(signature_statement),
                },
            )
        except Exception:
            # Audit logging is best-effort; event row is canonical.
            pass

    return event


async def fulfill_open_requests(
    db: AsyncSession,
    *,
    protocol_id: uuid.UUID,
    final_status: str,
    actor_id: Optional[uuid.UUID],
) -> int:
    """Mark all OPEN approval requests for a protocol as fulfilled."""
    if final_status not in VALID_FULFILL_STATES:
        raise ValueError(f"invalid final_status {final_status!r}")
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ProtocolApprovalRequest)
        .where(
            ProtocolApprovalRequest.protocol_id == protocol_id,
            ProtocolApprovalRequest.status == "OPEN",
        )
        .values(status=final_status, fulfilled_at=now, fulfilled_by_id=actor_id)
    )
    return result.rowcount or 0
