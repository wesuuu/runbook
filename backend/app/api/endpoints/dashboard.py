"""Dashboard endpoint — Action Rail triage surface (F-0092).

Thin orchestration: every counter is derived from the same in-memory lists the
hero and rail render, so a counter cannot drift from what the user sees.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.execution import AuditLog
from app.models.iam import User
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run, RunRoleAssignment
from app.schemas.dashboard import (
    ActivityItem,
    ActivityPage,
    Counters,
    DashboardResponse,
    LabStatus,
    MyWork,
    RunSummary,
    SignoffItem,
)
from app.services.approvals.awaiting import list_awaiting_for_user
from app.services.core.permissions import get_visible_project_ids
from app.services.equipment.calibration import get_calibration_status
from app.services.runs.blockers import list_blocked_runs
from app.services.runs.graph_facts import RunGraphFacts, extract_graph_facts
from app.services.signoffs.queries import list_runs_awaiting_signoff_for_user

router = APIRouter()


def _status(run: Run) -> str:
    return run.status if isinstance(run.status, str) else run.status.value


def _count_steps(graph: dict) -> int:
    """Count unitOp nodes in a graph (tolerant of non-dict node entries)."""
    return sum(
        1
        for n in (graph.get("nodes") or [])
        if isinstance(n, dict) and n.get("type") == "unitOp"
    )


def _count_completed_steps(execution_data: dict) -> int:
    """Count steps with status=completed."""
    return sum(
        1
        for v in execution_data.values()
        if isinstance(v, dict) and v.get("status") == "completed"
    )


def _user_has_incomplete_steps(
    graph: dict, execution_data: dict, user_lane_ids: set[str]
) -> bool:
    """Check if the user's assigned lanes have any incomplete steps."""
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "unitOp":
            continue
        parent_id = node.get("parentId")
        if not user_lane_ids and parent_id is None:
            step_data = execution_data.get(node["id"], {})
            if not isinstance(step_data, dict):
                return True
            if step_data.get("status") != "completed":
                return True
        elif parent_id in user_lane_ids:
            step_data = execution_data.get(node["id"], {})
            if not isinstance(step_data, dict):
                return True
            if step_data.get("status") != "completed":
                return True
    return False


def _build_run_summary(
    run: Run,
    project_name: str,
    protocol_name: str | None,
    role_name: str | None = None,
) -> RunSummary:
    graph = run.graph or {}
    exec_data = run.execution_data or {}
    return RunSummary(
        id=run.id,
        name=run.name,
        project_id=run.project_id,
        project_name=project_name,
        protocol_name=protocol_name,
        status=_status(run),
        role_name=role_name,
        completed_steps=_count_completed_steps(exec_data),
        total_steps=_count_steps(graph),
        updated_at=run.updated_at,
    )


async def _resolve_names(
    db: AsyncSession,
    project_ids: set[UUID],
    protocol_ids: set[UUID],
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    """Batch-resolve project and protocol names."""
    project_map: dict[UUID, str] = {}
    if project_ids:
        result = await db.execute(
            select(Project.id, Project.name).where(Project.id.in_(project_ids))
        )
        for pid, name in result.all():
            project_map[pid] = name

    proto_map: dict[UUID, str] = {}
    if protocol_ids:
        result = await db.execute(
            select(Protocol.id, Protocol.name).where(
                Protocol.id.in_(protocol_ids)
            )
        )
        for pid, name in result.all():
            proto_map[pid] = name

    return project_map, proto_map


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    org_id: UUID = Query(..., description="Current organization ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Action Rail dashboard: My Work hero + Lab Status rail + action counters."""
    user_id = user.id

    # ── Step 1: visible projects (early return on none) ──
    visible_project_ids = await get_visible_project_ids(db, user_id, org_id)
    if not visible_project_ids:
        return DashboardResponse(
            my_work=MyWork(),
            lab_status=LabStatus(),
            activity=[],
            counters=Counters(),
        )

    # ── Step 2: load runs in scope (decision 13 — creator / starter /
    #    lane-assignee, plus orphan PLANNED runs via project-visibility) ──
    assigned_run_ids = (
        select(RunRoleAssignment.run_id)
        .where(RunRoleAssignment.user_id == user_id)
        .scalar_subquery()
    )
    runs_with_assignments = (
        select(RunRoleAssignment.run_id).distinct().scalar_subquery()
    )
    scope_filter = or_(
        Run.created_by_id == user_id,                        # A — creator
        Run.started_by_id == user_id,                        # B — starter
        Run.id.in_(assigned_run_ids),                        # C — lane-assignee
        and_(                                                # D — orphan PLANNED
            Run.status == "PLANNED",
            Run.created_by_id.is_(None),
            Run.id.notin_(runs_with_assignments),
        ),
    )
    result = await db.execute(
        select(Run)
        .where(Run.project_id.in_(visible_project_ids), scope_filter)
        .options(defer(Run.notes), defer(Run.attachments))
    )
    in_scope_runs = list(result.scalars().all())

    # ── Step 3: walk each run graph exactly once ──
    graph_facts: dict[UUID, RunGraphFacts] = {
        run.id: extract_graph_facts(run.graph or {}) for run in in_scope_runs
    }

    # ── Step 4: ONE batched load of all role assignments for these runs ──
    run_ids = [r.id for r in in_scope_runs]
    assignments_by_run: dict[UUID, list[RunRoleAssignment]] = {}
    if run_ids:
        result = await db.execute(
            select(RunRoleAssignment).where(
                RunRoleAssignment.run_id.in_(run_ids)
            )
        )
        for a in result.scalars().all():
            assignments_by_run.setdefault(a.run_id, []).append(a)

    project_map, proto_map = await _resolve_names(
        db,
        {r.project_id for r in in_scope_runs},
        {r.protocol_id for r in in_scope_runs if r.protocol_id},
    )

    # ── Step 5: blockers (PLANNED runs only) ──
    planned_runs = [r for r in in_scope_runs if _status(r) == "PLANNED"]
    blocked = await list_blocked_runs(
        db, planned_runs, graph_facts, assignments_by_run, org_id
    )

    # ── Step 6: classify My Work ──
    needs_action_planned: list[RunSummary] = []
    needs_action_active: list[RunSummary] = []
    in_progress: list[RunSummary] = []
    planned_bucket: list[RunSummary] = []

    for run in in_scope_runs:
        status = _status(run)
        proj_name = project_map.get(run.project_id, "")
        proto_name = (
            proto_map.get(run.protocol_id) if run.protocol_id else None
        )
        my_assignments = [
            a for a in assignments_by_run.get(run.id, []) if a.user_id == user_id
        ]
        role_name = my_assignments[0].role_name if my_assignments else None
        summary = _build_run_summary(run, proj_name, proto_name, role_name)

        if status == "PLANNED":
            reasons = blocked.get(run.id)
            if reasons:
                summary.blockers = reasons
                needs_action_planned.append(summary)
            else:
                planned_bucket.append(summary)
        elif status == "ACTIVE":
            involved = bool(my_assignments) or run.started_by_id == user_id
            if not involved:
                continue
            lane_ids = {a.lane_node_id for a in my_assignments}
            if _user_has_incomplete_steps(
                run.graph or {}, run.execution_data or {}, lane_ids
            ):
                needs_action_active.append(summary)
            else:
                in_progress.append(summary)
        # COMPLETED / EDITED runs are not bucketed into My Work.

    needs_action_planned.sort(key=lambda r: r.updated_at, reverse=True)
    needs_action_active.sort(key=lambda r: r.updated_at, reverse=True)
    in_progress.sort(key=lambda r: r.updated_at, reverse=True)
    planned_bucket.sort(key=lambda r: r.updated_at, reverse=True)

    my_work = MyWork(
        needs_action=needs_action_planned + needs_action_active,
        in_progress=in_progress,
        planned=planned_bucket,
    )

    # ── Step 7: Lab Status ──
    calibration = await get_calibration_status(db, org_id)

    proto_awaiting = await list_awaiting_for_user(db, user_id)
    _far_future = datetime.max.replace(tzinfo=timezone.utc)
    signoff_items: list[SignoffItem] = []
    for item in proto_awaiting:
        submitter = item.get("submitted_by")
        detail = (
            f"Submitted by {submitter['name']}" if submitter else None
        )
        signoff_items.append(
            SignoffItem(
                kind="protocol",
                entity_id=item["protocol_id"],
                name=item["name"],
                project_name=item.get("project_name"),
                detail=detail,
                waiting_since=item.get("submitted_at"),
            )
        )
    run_signoff_items = await list_runs_awaiting_signoff_for_user(
        db, user_id, in_scope_runs, graph_facts, assignments_by_run
    )
    # ONE unified queue, oldest-waiting first across BOTH kinds (spec: the rail
    # is a single triage list, not protocol-then-run groups). Items with no
    # timestamp sort last.
    awaiting_signoff = sorted(
        signoff_items + run_signoff_items,
        key=lambda s: s.waiting_since or _far_future,
    )
    lab_status = LabStatus(
        calibration=calibration,
        awaiting_signoff=awaiting_signoff,
    )

    # ── Step 8: activity ──
    activity = await _fetch_activity(db, visible_project_ids, limit=10)

    # ── Step 9: counters (set algebra — see design) ──
    counters = Counters(
        runs_blocked=len(blocked),
        calibrations_due=len(calibration.overdue) + len(calibration.due_soon),
        signoffs_pending=len(lab_status.awaiting_signoff),
        active_runs=len(needs_action_active) + len(in_progress),
    )

    return DashboardResponse(
        my_work=my_work,
        lab_status=lab_status,
        activity=activity,
        counters=counters,
    )


async def _fetch_activity(
    db: AsyncSession,
    project_ids: list[UUID],
    limit: int = 10,
    offset: int = 0,
) -> list[ActivityItem]:
    """Fetch recent audit log entries for the given projects."""
    # Collect child entity IDs
    proto_result = await db.execute(
        select(Protocol.id).where(Protocol.project_id.in_(project_ids))
    )
    protocol_ids = list(proto_result.scalars().all())

    run_result = await db.execute(select(Run.id).where(Run.project_id.in_(project_ids)))
    run_ids = list(run_result.scalars().all())

    # Build OR conditions
    conditions = [
        and_(
            AuditLog.entity_type == "Project",
            AuditLog.entity_id.in_(project_ids),
        )
    ]
    if protocol_ids:
        conditions.append(
            and_(
                AuditLog.entity_type == "Protocol",
                AuditLog.entity_id.in_(protocol_ids),
            )
        )
    if run_ids:
        conditions.append(
            and_(
                AuditLog.entity_type == "Run",
                AuditLog.entity_id.in_(run_ids),
            )
        )
        conditions.append(
            and_(
                AuditLog.entity_type == "RunRoleAssignment",
                AuditLog.entity_id.in_(run_ids),
            )
        )

    query = (
        select(AuditLog)
        .where(or_(*conditions))
        .options(selectinload(AuditLog.actor))
        .order_by(desc(AuditLog.created_at))
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    logs = list(result.scalars().all())

    # Batch-resolve entity names
    entity_names = await _resolve_entity_names(
        db, logs, set(project_ids), set(protocol_ids), set(run_ids)
    )

    items: list[ActivityItem] = []
    for log in logs:
        actor_name = None
        actor_email = None
        if log.actor:
            actor_name = log.actor.full_name or log.actor.email
            actor_email = log.actor.email

        entity_name = entity_names.get(
            (log.entity_type, log.entity_id),
            (log.changes or {}).get("name", ""),
        )

        items.append(
            ActivityItem(
                id=log.id,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                entity_name=entity_name,
                actor_name=actor_name,
                actor_email=actor_email,
                changes=log.changes or {},
                created_at=log.created_at,
            )
        )

    return items


async def _resolve_entity_names(
    db: AsyncSession,
    logs: list,
    project_ids: set[UUID],
    protocol_ids: set[UUID],
    run_ids: set[UUID],
) -> dict[tuple[str, UUID], str]:
    """Resolve entity names from IDs for display."""
    names: dict[tuple[str, UUID], str] = {}

    # Projects
    if project_ids:
        result = await db.execute(
            select(Project.id, Project.name).where(Project.id.in_(project_ids))
        )
        for pid, name in result.all():
            names[("Project", pid)] = name

    # Protocols
    if protocol_ids:
        result = await db.execute(
            select(Protocol.id, Protocol.name).where(Protocol.id.in_(protocol_ids))
        )
        for pid, name in result.all():
            names[("Protocol", pid)] = name

    # Runs
    if run_ids:
        result = await db.execute(select(Run.id, Run.name).where(Run.id.in_(run_ids)))
        for rid, name in result.all():
            names[("Run", rid)] = name
            # RunRoleAssignment entity_id is the run_id
            names[("RunRoleAssignment", rid)] = name

    return names


@router.get("/activity", response_model=ActivityPage)
async def get_dashboard_activity(
    org_id: UUID = Query(..., description="Current organization ID"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated activity feed for the dashboard."""
    visible_project_ids = await get_visible_project_ids(db, user.id, org_id)
    if not visible_project_ids:
        return ActivityPage(items=[], total=0, offset=offset, limit=limit)

    items = await _fetch_activity(db, visible_project_ids, limit=limit, offset=offset)

    # Count total
    proto_result = await db.execute(
        select(Protocol.id).where(Protocol.project_id.in_(visible_project_ids))
    )
    protocol_ids = list(proto_result.scalars().all())
    run_result = await db.execute(
        select(Run.id).where(Run.project_id.in_(visible_project_ids))
    )
    run_ids = list(run_result.scalars().all())

    conditions = [
        and_(
            AuditLog.entity_type == "Project",
            AuditLog.entity_id.in_(visible_project_ids),
        )
    ]
    if protocol_ids:
        conditions.append(
            and_(
                AuditLog.entity_type == "Protocol",
                AuditLog.entity_id.in_(protocol_ids),
            )
        )
    if run_ids:
        conditions.append(
            and_(
                AuditLog.entity_type.in_(["Run", "RunRoleAssignment"]),
                AuditLog.entity_id.in_(run_ids),
            )
        )

    count_result = await db.execute(
        select(func.count(AuditLog.id)).where(or_(*conditions))
    )
    total = count_result.scalar() or 0

    return ActivityPage(items=items, total=total, offset=offset, limit=limit)
