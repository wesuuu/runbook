"""Run sign-off request lifecycle: generation, cancellation, fulfillment (F-0080).

All functions are transaction-neutral — the caller manages flush/commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Run
from app.models.signoffs import GlpRole, GlpSignoffRequest
from app.services.core.audit import log_audit
from app.services.signoffs.validation import assert_qau_independent


def _glp_settings(run: Run) -> dict:
    """Read glpSettings from the run's graph snapshot (GLP source of truth)."""
    graph = run.graph if isinstance(run.graph, dict) else {}
    settings = graph.get("glpSettings")
    return settings if isinstance(settings, dict) else {}


def _required_roles(glp_settings: dict) -> list[str]:
    """Roles requiring a sign-off request, per glpSettings."""
    roles: list[str] = []
    if glp_settings.get("require_study_director"):
        roles.append(GlpRole.STUDY_DIRECTOR.value)
    if glp_settings.get("require_qau"):
        roles.append(GlpRole.QAU.value)
    return roles


async def assert_run_completable(db: AsyncSession, run: Run) -> None:
    """Reject completion when a required SD review request would be unrouted.

    An unassigned QAU request is fine — it falls to the org QAU pool — but an
    unassigned SD request surfaces to no one (§58.33), so block completion.
    """
    if GlpRole.STUDY_DIRECTOR.value in _required_roles(_glp_settings(run)):
        if run.study_director_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "RUN_SD_UNASSIGNED",
                    "message": (
                        "Assign a Study Director before completing this run."
                    ),
                },
            )


async def _resolve_assignee(
    db: AsyncSession, run: Run, role: str
) -> Optional[uuid.UUID]:
    """Resolve the request assignee from the Run reviewer columns.

    QAU is re-validated for §58.35 independence; a now-conflicted QAU is
    demoted to the org pool (returns None) and the demotion is audit-logged.
    """
    if role == GlpRole.STUDY_DIRECTOR.value:
        return run.study_director_id
    if role == GlpRole.QAU.value:
        candidate = run.qau_reviewer_id
        if candidate is None:
            return None
        try:
            await assert_qau_independent(db, "run", run.id, candidate, "QAU")
        except HTTPException:
            await log_audit(
                db, candidate, "signoff_request.qau_demoted", "run", run.id,
                {"reason": "QAU_NOT_INDEPENDENT"},
            )
            return None
        return candidate
    return None


async def generate_signoff_requests(db: AsyncSession, run: Run) -> int:
    """Create one OPEN GlpSignoffRequest per role required by the run's glpSettings.

    Idempotent two ways:

    1. Roles that already have an OPEN request are skipped *before*
       ``_resolve_assignee`` runs. This matters: ``_resolve_assignee`` re-checks
       QAU independence and audit-logs a ``qau_demoted`` row on conflict — so
       running it on a role that is already requested would emit a spurious
       audit entry on every idempotent re-call (e.g. a double completion
       transition). Skipping first keeps the audit trail clean.
    2. The INSERT itself is ``ON CONFLICT DO NOTHING`` against
       ``ux_signoff_request_active_run`` — a concurrency belt-and-suspenders so
       two racing completion transitions cannot raise ``IntegrityError``.

    Returns the number of rows actually inserted.
    """
    required = _required_roles(_glp_settings(run))
    if not required:
        return 0

    existing_rows = await db.execute(
        select(GlpSignoffRequest.role).where(
            GlpSignoffRequest.run_id == run.id,
            GlpSignoffRequest.status == "OPEN",
        )
    )
    already_open: set[str] = set(existing_rows.scalars().all())

    created = 0
    for role in required:
        if role in already_open:
            continue
        assignee = await _resolve_assignee(db, run, role)
        stmt = (
            pg_insert(GlpSignoffRequest)
            .values(
                id=uuid.uuid4(),
                protocol_id=None,
                run_id=run.id,
                role=role,
                requested_user_id=assignee,
                requested_by_id=run.started_by_id,
                status="OPEN",
            )
            .on_conflict_do_nothing(
                index_elements=["run_id", "role"],
                index_where=text("status = 'OPEN'"),
            )
        )
        result = await db.execute(stmt)
        created += result.rowcount or 0
    return created


async def cancel_signoff_requests(db: AsyncSession, run: Run) -> int:
    """Flip every OPEN run-scoped request for the run to CANCELLED.

    Leaves APPROVED/REJECTED rows as historical record — request status is not
    the source of truth for "reviewed" (that is the GlpSignoff row).
    """
    result = await db.execute(
        update(GlpSignoffRequest)
        .where(
            GlpSignoffRequest.run_id == run.id,
            GlpSignoffRequest.status == "OPEN",
        )
        .values(status="CANCELLED")
    )
    return result.rowcount or 0


async def fulfill_signoff_request(
    db: AsyncSession, *, run_id: uuid.UUID, role: str, status: str
) -> int:
    """Flip the matching OPEN run request to a terminal status. No-op if none."""
    result = await db.execute(
        update(GlpSignoffRequest)
        .where(
            GlpSignoffRequest.run_id == run_id,
            GlpSignoffRequest.role == role,
            GlpSignoffRequest.status == "OPEN",
        )
        .values(status=status, fulfilled_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0
