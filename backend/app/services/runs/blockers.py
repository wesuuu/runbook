"""Dashboard run-blocker detection (F-0092).

A PLANNED run is "blocked" when it cannot start cleanly. Two scopes:
  - LANES_UNASSIGNED              — the lane-assignment start gate would reject it
  - EQUIPMENT_CALIBRATION_OVERDUE — it references overdue-calibration equipment

ACTIVE / EDITED runs are never blocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.runs import Run, RunRoleAssignment
from app.schemas.dashboard import BlockerReason
from app.services.runs.graph_facts import RunGraphFacts
from app.services.runs.validation import lane_assignment_gap

_NAME_CAP = 40


def _cap(name: str) -> str:
    """Cap an embedded equipment name so a pathological name can't blow out
    the tag layout (ellipsis-truncated)."""
    if len(name) <= _NAME_CAP:
        return name
    return name[: _NAME_CAP - 1] + "…"


def _status(run: Run) -> str:
    return run.status if isinstance(run.status, str) else run.status.value


async def list_blocked_runs(
    db: AsyncSession,
    runs: list[Run],
    graph_facts: dict[UUID, RunGraphFacts],
    assignments_by_run: dict[UUID, list[RunRoleAssignment]],
    org_id: UUID,
) -> dict[UUID, list[BlockerReason]]:
    """Map each blocked PLANNED run id to its non-empty list of BlockerReasons."""
    today = datetime.now(timezone.utc).date()
    planned = [r for r in runs if _status(r) == "PLANNED"]

    # Batched: every overdue, non-archived, in-org equipment referenced by any
    # planned run. Equipment ids come from the pre-walked graph_facts.
    all_equipment_ids: set[UUID] = set()
    for run in planned:
        facts = graph_facts.get(run.id)
        if facts:
            all_equipment_ids.update(facts.equipment_ids)

    overdue_names: dict[UUID, str] = {}
    if all_equipment_ids:
        result = await db.execute(
            select(Equipment).where(
                Equipment.id.in_(all_equipment_ids),
                Equipment.organization_id == org_id,
                Equipment.archived_at.is_(None),
                Equipment.next_calibration_date.is_not(None),
                Equipment.next_calibration_date < today,
            )
        )
        for eq in result.scalars().all():
            overdue_names[eq.id] = eq.name

    blocked: dict[UUID, list[BlockerReason]] = {}
    for run in planned:
        reasons: list[BlockerReason] = []

        gap = lane_assignment_gap(
            run.graph or {}, assignments_by_run.get(run.id, [])
        )
        if gap.is_blocking:
            if gap.unassigned_lane_ids:
                n = len(gap.unassigned_lane_ids)
                label = f"{n} lane{'' if n == 1 else 's'} unassigned"
            elif not gap.has_assignee:
                label = "No one assigned"
            else:
                # Lanes all assigned + someone assigned, but an assignment
                # points at a lane removed from the graph — the start gate
                # rejects this via its set-equality check.
                label = "Role assignments out of sync"
            reasons.append(BlockerReason(code="LANES_UNASSIGNED", label=label))

        facts = graph_facts.get(run.id)
        run_overdue = [
            overdue_names[eid]
            for eid in (facts.equipment_ids if facts else [])
            if eid in overdue_names
        ]
        run_overdue = list(dict.fromkeys(run_overdue))  # de-dup, keep order
        if run_overdue:
            label = f"{_cap(run_overdue[0])} calibration overdue"
            if len(run_overdue) > 1:
                label += f" (+{len(run_overdue) - 1} more)"
            reasons.append(
                BlockerReason(code="EQUIPMENT_CALIBRATION_OVERDUE", label=label)
            )

        if reasons:
            blocked[run.id] = reasons

    return blocked
