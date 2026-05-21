"""Read/write helpers for GlpSignoff. Single source of truth for the
'active sign-off' definition (action=APPROVED AND invalidated_at IS NULL).

Caller manages the transaction (flush/commit); this module never calls
db.commit() so it integrates cleanly with SAVEPOINT-based test sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.protocols import Protocol
from app.models.runs import Run, RunRoleAssignment
from app.models.signoffs import GlpSignoff
from app.schemas.dashboard import SignoffItem
from app.services.runs.graph_facts import RunGraphFacts


def missing_signoff_roles(
    have_roles: set[str], glp_settings: dict[str, Any]
) -> list[str]:
    """Which required run sign-off roles are not yet present.

    OPERATOR is always required. STUDY_DIRECTOR / QAU are gated by the
    ``glp_settings`` flags. Used by the dashboard's awaiting-sign-off
    query to surface runs with outstanding sign-off roles.

    Note: run *closure* is gated only on OPERATOR (see
    ``assert_run_can_close``) — SD/QAU are async post-completion reviews
    (F-0080 decision C1), so this helper is not the closure gate.
    """
    missing: list[str] = []
    if "OPERATOR" not in have_roles:
        missing.append("OPERATOR")
    if (
        glp_settings.get("require_study_director")
        and "STUDY_DIRECTOR" not in have_roles
    ):
        missing.append("STUDY_DIRECTOR")
    if glp_settings.get("require_qau") and "QAU" not in have_roles:
        missing.append("QAU")
    return missing


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


async def list_runs_awaiting_signoff_for_user(
    db: AsyncSession,
    user_id: UUID,
    runs: list[Run],
    graph_facts: dict[UUID, RunGraphFacts],
    assignments_by_run: dict[UUID, list[RunRoleAssignment]],
    project_slug_map: dict[UUID, str] | None = None,
) -> list[SignoffItem]:
    """Runs the user is involved in that are ready to close but missing a sign-off.

    A run qualifies when ALL hold:
      - status ACTIVE or EDITED
      - the *protocol* graph has glpSettings.glp_enabled true
      - every unit-op step is completed
      - a required sign-off role is missing
      - the user is involved (a RunRoleAssignment row OR started_by_id)

    ``project_slug_map`` (run project_id → slug) is used to populate each
    item's ``project_slug`` so the dashboard can build the run's nested URL.

    Returned oldest-waiting first (run.updated_at ascending).
    """
    slug_map = project_slug_map or {}
    candidates = [
        r
        for r in runs
        if (r.status if isinstance(r.status, str) else r.status.value)
        in ("ACTIVE", "EDITED")
    ]

    involved: list[Run] = []
    for run in candidates:
        mine = [
            a for a in assignments_by_run.get(run.id, []) if a.user_id == user_id
        ]
        if mine or run.started_by_id == user_id:
            involved.append(run)
    if not involved:
        return []

    # Live GLP settings come from the protocol graph (what complete_run reads).
    proto_ids = {r.protocol_id for r in involved if r.protocol_id}
    protocols: dict[UUID, Protocol] = {}
    if proto_ids:
        result = await db.execute(
            select(Protocol).where(Protocol.id.in_(proto_ids))
        )
        protocols = {p.id: p for p in result.scalars().all()}

    # One batched query — active run sign-offs across all candidate run ids.
    run_ids = [r.id for r in involved]
    have_by_run: dict[UUID, set[str]] = {}
    result = await db.execute(
        select(GlpSignoff).where(
            GlpSignoff.run_id.in_(run_ids),
            GlpSignoff.action == "APPROVED",
            GlpSignoff.invalidated_at.is_(None),
        )
    )
    for s in result.scalars().all():
        have_by_run.setdefault(s.run_id, set()).add(s.role)

    qualifying: list[tuple[datetime, SignoffItem]] = []
    for run in involved:
        proto = protocols.get(run.protocol_id) if run.protocol_id else None
        glp = ((proto.graph or {}).get("glpSettings") if proto else None) or {}
        if not glp.get("glp_enabled"):
            continue

        facts = graph_facts.get(run.id)
        unit_op_ids = facts.unit_op_node_ids if facts else []
        if not unit_op_ids:
            continue

        exec_data = run.execution_data or {}
        all_complete = all(
            isinstance(exec_data.get(sid), dict)
            and exec_data[sid].get("status") == "completed"
            for sid in unit_op_ids
        )
        if not all_complete:
            continue

        missing = missing_signoff_roles(have_by_run.get(run.id, set()), glp)
        if not missing:
            continue

        qualifying.append(
            (
                run.updated_at,
                SignoffItem(
                    kind="run",
                    entity_id=run.id,
                    entity_slug=run.slug,
                    name=run.name,
                    # Intentionally None — the rail shows run name + detail;
                    # SignoffItem carries no project *name* for runs (F-0092).
                    project_name=None,
                    project_slug=slug_map.get(run.project_id),
                    detail=f"Missing {', '.join(missing)}",
                    waiting_since=run.updated_at,
                ),
            )
        )

    qualifying.sort(key=lambda pair: pair[0])  # oldest-waiting first
    return [item for _, item in qualifying]
