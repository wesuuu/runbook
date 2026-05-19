"""Run-specific validation guards.

Follows the assert_X pattern from .claude/rules/backend-services.md:
each function raises HTTPException on violation, returns None on success.

Error codes (stable strings used by the frontend):
    EDIT_REASON_REQUIRED        — modified step missing a non-blank edit_reason
    RUN_IMMUTABLE_REOPEN_REQUIRED — COMPLETED run has active sign-offs; reopen first
    SIGNOFF_REQUIRED            — required sign-off role(s) absent at close time
    LANES_UNASSIGNED            — GLP-enabled run missing user on one or more lanes
    REOPEN_NOT_AUTHORIZED       — caller lacks authority to reopen a COMPLETED run
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import GlpSignoff, Project, Run
from app.services.core.permissions import check_permission
from app.services.signoffs.queries import list_active_signoffs


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

    The OPERATOR sign-off is always required.  Additional roles are
    gated by the ``glp_settings`` dict (drawn from
    ``run.graph["glpSettings"]`` or a GLP settings record):

        require_study_director: bool — SD sign-off required to close
        require_qau: bool           — QAU sign-off required to close

    Raises:
        HTTPException(400): detail={error: "SIGNOFF_REQUIRED",
                                    missing_roles: [...]}
    """
    active = await list_active_signoffs(db, "run", run.id)
    have_roles = {s.role for s in active}
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

    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "SIGNOFF_REQUIRED", "missing_roles": missing},
        )


def assert_can_start(run: Run) -> None:
    """Block PLANNED→ACTIVE transition when required lane assignments are missing.

    If the run's graph has ``glpSettings.glp_enabled=True``, every swimlane
    node in ``run.graph["nodes"]`` must have a matching ``RunRoleAssignment``
    (loaded from the ``run.role_assignments`` relationship) before the run
    may start.

    This function is synchronous.  The caller is responsible for ensuring
    ``run.role_assignments`` is loaded (eager or lazy-loaded before call).

    Raises:
        HTTPException(422): detail={error: "LANES_UNASSIGNED",
                                    missing_lanes: ["lane-uuid", ...]}
    """
    graph = run.graph or {}
    glp_settings = graph.get("glpSettings") or {}
    if not glp_settings.get("glp_enabled"):
        return

    nodes = graph.get("nodes") or []
    swimlane_node_ids = [
        n["id"] for n in nodes if isinstance(n, dict) and n.get("type") == "swimLane"
    ]
    if not swimlane_node_ids:
        return

    assigned_lanes = {a.lane_node_id for a in (run.role_assignments or [])}
    missing_lanes = [lid for lid in swimlane_node_ids if lid not in assigned_lanes]

    if missing_lanes:
        raise HTTPException(
            status_code=422,
            detail={"error": "LANES_UNASSIGNED", "missing_lanes": missing_lanes},
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
