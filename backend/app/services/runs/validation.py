"""Run-specific validation guards.

Follows the assert_X pattern from .claude/rules/backend-services.md:
each function raises HTTPException on violation, returns None on success.

Error codes (stable strings used by the frontend):
    EDIT_REASON_REQUIRED        — modified step missing a non-blank edit_reason
    RUN_IMMUTABLE_REOPEN_REQUIRED — COMPLETED run has active sign-offs; reopen first
    SIGNOFF_REQUIRED            — required sign-off role(s) absent at close time
    REOPEN_NOT_AUTHORIZED       — caller lacks authority to reopen a COMPLETED run
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.projects import Project
from app.models.runs import Run, RunRoleAssignment
from app.models.signoffs import GlpSignoff
from app.services.core.permissions import check_permission
from app.services.signoffs.queries import (
    list_active_signoffs,
    missing_signoff_roles,
)


def assert_no_unjustified_edit_errors(
    execution_data_delta: dict[str, dict[str, Any]],
) -> None:
    """Raise 400 if any modified step is missing a non-blank edit_reason.

    Args:
        execution_data_delta: Mapping of step_id → dict of changed fields.
            Each entry must contain ``edit_reason`` (non-empty string).

    Raises:
        HTTPException(400): detail={error: "EDIT_REASON_REQUIRED",
                                    issues: [{step_id: "..."}]}
    """
    issues = []
    for step_id, fields in execution_data_delta.items():
        reason = fields.get("edit_reason")
        if not isinstance(reason, str) or not reason.strip():
            issues.append({"step_id": step_id})
    if issues:
        raise HTTPException(
            status_code=400,
            detail={"error": "EDIT_REASON_REQUIRED", "issues": issues},
        )


async def assert_can_edit_completed_run(
    db: AsyncSession,
    run: Run,
) -> None:
    """Block edits on a COMPLETED run that still carries active sign-offs.

    A run that has been signed off is "of record".  The client must POST
    /runs/{id}/reopen first, which invalidates existing sign-offs and
    transitions the run to EDITED, before further edits are permitted.

    Raises:
        HTTPException(400): detail={error: "RUN_IMMUTABLE_REOPEN_REQUIRED",
                                    active_roles: [...]}
    """
    if run.status != "COMPLETED":
        return
    active = await list_active_signoffs(db, "run", run.id)
    if active:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "RUN_IMMUTABLE_REOPEN_REQUIRED",
                "active_roles": [s.role for s in active],
            },
        )


async def assert_run_can_close(
    db: AsyncSession,
    run: Run,
    glp_settings: dict[str, Any],
) -> None:
    """Verify required sign-offs exist before a run is closed.

    Sign-offs are a GLP feature.  A run counts as GLP iff its protocol's
    ``glpSettings`` enable at least one reviewer role —
    ``require_study_director`` or ``require_qau``.  That is the same
    signal the protocol editor uses to derive ``protocol.requires_approval``
    (see :mod:`app.api.endpoints.protocols`).  A "basic" (non-GLP)
    protocol enables neither, so its runs close with no sign-off gate at
    all — not even OPERATOR (#18).

    For a GLP run the OPERATOR sign-off is always required.  The
    STUDY_DIRECTOR and QAU sign-offs are each required only when their
    flag in ``glp_settings`` is set (drawn from ``run.graph["glpSettings"]``
    or a GLP settings record):

        require_study_director: bool — SD sign-off required to close
        require_qau: bool           — QAU sign-off required to close

    Raises:
        HTTPException(400): detail={error: "SIGNOFF_REQUIRED",
                                    missing_roles: [...]}
    """
    require_sd = bool(glp_settings.get("require_study_director"))
    require_qau = bool(glp_settings.get("require_qau"))

    # Basic (non-GLP) run: no reviewer role enabled, no sign-off gate (#18).
    if not (require_sd or require_qau):
        return

    active = await list_active_signoffs(db, "run", run.id)
    have_roles = {s.role for s in active}
    missing = missing_signoff_roles(have_roles, glp_settings)

    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "SIGNOFF_REQUIRED", "missing_roles": missing},
        )


async def assert_can_reopen(
    db: AsyncSession,
    run: Run,
    user: Any,
) -> None:
    """Tiered authorization for reopening a COMPLETED run.

    Authorization tiers (first match wins):
        1. Study Director — user is the active STUDY_DIRECTOR signer on the
           run's protocol (pre-execution approval).  Always allowed.
        2. Org Admin — user has the 'ADMIN' role in the run's org.
        3. Project Lead (proxy) — user has ADMIN-level object permission on
           the run's project.  Allowed unless the run outcome was ABORTED.
           NOTE: the codebase has no distinct "project lead" concept yet.
           ADMIN permission on the project is the closest semantic match.
           TODO: replace with a dedicated PROJECT_LEAD role when introduced.

    Raises:
        HTTPException(403): detail={error: "REOPEN_NOT_AUTHORIZED"}
    """
    project_id = run.project_id

    # Resolve org_id for the project.
    proj_result = await db.execute(
        select(Project.organization_id).where(Project.id == project_id)
    )
    org_id: UUID | None = proj_result.scalar_one_or_none()

    if org_id is None:
        raise HTTPException(
            status_code=403,
            detail={"error": "REOPEN_NOT_AUTHORIZED"},
        )

    # Check org membership (needed for both tier 2 and tier 1).
    from app.models.iam import OrganizationMember

    member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = member_result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail={"error": "REOPEN_NOT_AUTHORIZED"},
        )

    # Tier 2: Org Admin.
    if "ADMIN" in (membership.roles or []):
        return

    # Tier 1: Study Director — active STUDY_DIRECTOR sign-off on the protocol.
    if run.protocol_id is not None:
        sd_result = await db.execute(
            select(GlpSignoff).where(
                GlpSignoff.protocol_id == run.protocol_id,
                GlpSignoff.role == "STUDY_DIRECTOR",
                GlpSignoff.action == "APPROVED",
                GlpSignoff.invalidated_at.is_(None),
            )
        )
        sd_row = sd_result.scalar_one_or_none()
        if sd_row is not None and sd_row.signer_id == user.id:
            return

    # Tier 3: Project Lead (ADMIN permission on the project).
    # NOTE: outcome==ABORTED runs are treated the same as any other
    # completed run for now.  Decision #9 specified 'INVALIDATED' as a
    # block condition, but RunOutcome has no INVALIDATED value — only
    # COMPLETED_NORMAL, COMPLETED_WITH_DEVIATIONS, and ABORTED.
    # We do not gate project-lead reopen on ABORTED here; leave a
    # TODO for when a dedicated INVALIDATED/LOCKED outcome is introduced.
    # TODO(F-0087): revisit if INVALIDATED outcome is added to RunOutcome.
    has_project_admin = await check_permission(
        db=db,
        user_id=user.id,
        object_type=ObjectType.PROJECT,
        object_id=project_id,
        required_level=PermissionLevel.ADMIN,
    )
    if has_project_admin:
        return

    raise HTTPException(
        status_code=403,
        detail={"error": "REOPEN_NOT_AUTHORIZED"},
    )


@dataclass
class LaneGap:
    """Why a PLANNED run can't start. ``is_blocking`` False == ready to start.

    ``stale_lane_ids`` captures assignments whose ``lane_node_id`` is not a
    swimlane in the run's current graph. The inlined ``update_run`` gate
    rejects these via a *set-equality* check (``assigned != required``), so the
    predicate must surface them — otherwise the dashboard would call a run
    "ready" that the live gate still rejects.
    """

    has_assignee: bool
    unassigned_lane_ids: list[str]
    stale_lane_ids: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        return (
            (not self.has_assignee)
            or bool(self.unassigned_lane_ids)
            or bool(self.stale_lane_ids)
        )


def lane_assignment_gap(
    graph: Optional[dict], role_assignments: Iterable[RunRoleAssignment]
) -> LaneGap:
    """Compute the lane-assignment gap for a run's PLANNED->ACTIVE start gate.

    Mirrors the inlined gate in ``update_run`` exactly:
      (a) at least one RunRoleAssignment must exist;
      (b) if the graph has swimlane nodes, the set of assigned lane ids must
          *equal* the set of swimlane node ids — i.e. every swimlane is
          assigned AND no assignment points at a lane absent from the graph.

    When the graph has no swimlane nodes, only (a) applies — the live gate
    does not inspect lane ids at all in that case.

    Pure and synchronous — the caller supplies the already-loaded assignments.
    """
    assignments = list(role_assignments)
    has_assignee = len(assignments) > 0

    nodes = (graph or {}).get("nodes") or []
    swimlane_ids = [
        n["id"]
        for n in nodes
        if isinstance(n, dict) and n.get("type") == "swimLane" and n.get("id")
    ]
    assigned = {a.lane_node_id for a in assignments}
    if swimlane_ids:
        swimlane_set = set(swimlane_ids)
        unassigned = [lid for lid in swimlane_ids if lid not in assigned]
        stale = sorted(lid for lid in assigned if lid not in swimlane_set)
    else:
        unassigned = []
        stale = []
    return LaneGap(
        has_assignee=has_assignee,
        unassigned_lane_ids=unassigned,
        stale_lane_ids=stale,
    )
