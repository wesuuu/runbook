"""Helpers for writing approval events + audit log atomically.

TODO(F-0087 Task 27): The ``write_event`` function below still writes to
``protocol_approval_events`` instead of ``glp_signoffs``. It cannot be
swapped to ``services/signoffs/service.create_signoff`` until the legacy
F-0066 endpoints that call it (``/protocols/{id}/submit-for-approval``,
``/approve``, ``/reject``, plus the ``REVERTED`` write inside
``protocols.py``) are deleted in Task 27.

Three concrete reasons the rewrite must wait:

1. ``write_event`` is called with actions ``SUBMITTED`` and ``REVERTED``,
   which are workflow markers, not GLP sign-off actions. ``GlpSignoff.action``
   only accepts ``APPROVED``, ``REJECTED``, ``REQUESTED_CHANGES`` (CHECK
   ``ck_glp_signoff_action``). There is no defensible mapping for the
   workflow actions — they belong on ``GlpSignoffRequest`` instead.
2. ``create_signoff`` requires a record-scoped signature image
   (``signer.signature_full_path`` is copied at sign time, and
   ``ck_approved_requires_attestation`` rejects APPROVED rows without
   ``signature_image_path``). The legacy F-0066 endpoints do not collect a
   signature image; the existing F-0066 tests do not populate one either.
3. ``create_signoff`` runs QAU-independence and role-assignability
   validators that the F-0066 endpoints have no concept of. Routing F-0066
   approvals through them would change observable error behaviour before
   the endpoints are removed.

The reader path that *can* move to ``glp_signoffs`` today is the
"awaiting my approval" service — see ``awaiting.py``, which was rewritten
in Task 26 to derive ``submitted_at`` / ``submitted_by`` from
``GlpSignoffRequest`` rather than the legacy SUBMITTED event row.

Once Task 27 lands and the legacy endpoints are gone, this whole module
should be deleted along with the ``ProtocolApprovalEvent`` model.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import (GlpSignoffRequest, Protocol,
                                ProtocolApprovalEvent)
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

    TODO(F-0087 Task 27): retire alongside the legacy F-0066 endpoints
    (see module docstring). Until then this remains the source of writes
    to ``protocol_approval_events``; ``glp_signoffs`` is populated only
    via the new ``POST /signoffs`` endpoint (Task 13) and the create_signoff
    service.

    Caller is responsible for committing the transaction.
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid approval action {action!r}")
    # Stamp created_at explicitly. Postgres `now()` returns transaction time,
    # so consecutive events written inside one transaction (or one test
    # SAVEPOINT) would otherwise share a timestamp and break DESC ordering.
    now = datetime.now(timezone.utc)
    event = ProtocolApprovalEvent(
        protocol_id=protocol.id,
        protocol_version_id=protocol_version_id,
        actor_id=actor_id,
        action=action,
        comment=comment,
        signature_statement=signature_statement,
        created_at=now,
        updated_at=now,
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
    """Mark all OPEN approval requests for a protocol as fulfilled.

    Operates on ``glp_signoff_requests`` (Task 7 rename); this function
    survives the Task 27 cutover and the GlpSignoffRequest queue continues
    to track per-user OPEN/APPROVED/REJECTED/WITHDRAWN state.
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
