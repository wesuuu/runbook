"""Dashboard endpoint — My Work, Team Activity, Operational Counters."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.execution import AuditLog
from app.models.iam import (
    OrganizationMember,
    User,
)
from app.models.science import (
    Project,
    Protocol,
    Run,
    RunRoleAssignment,
)
from app.schemas.dashboard import (
    ActivityItem,
    ActivityPage,
    CompletionTrendItem,
    Counters,
    DashboardResponse,
    MyWork,
    RunSummary,
)
from app.services.permissions import get_visible_project_ids

router = APIRouter()


def _count_steps(graph: dict) -> int:
    """Count unitOp nodes in a graph."""
    return sum(
        1 for n in graph.get("nodes", []) if n.get("type") == "unitOp"
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
    for node in graph.get("nodes", []):
        if node.get("type") != "unitOp":
            continue
        parent_id = node.get("parentId")
        # If no swimlanes at all, all steps belong to the user
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
    status_str = run.status if isinstance(run.status, str) else run.status.value
    return RunSummary(
        id=run.id,
        name=run.name,
        project_id=run.project_id,
        project_name=project_name,
        protocol_name=protocol_name,
        status=status_str,
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


def _compute_completion_trend(
    runs: list, days: int = 7
) -> list[CompletionTrendItem]:
    """Build a per-day completion count for the last N days."""
    now = datetime.now(timezone.utc)
    # Build date buckets (oldest first)
    buckets: dict[str, int] = {}
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        buckets[d] = 0

    for run in runs:
        status = run.status if isinstance(run.status, str) else run.status.value
        if status not in ("COMPLETED", "EDITED"):
            continue
        if not run.updated_at:
            continue
        day_key = run.updated_at.strftime("%Y-%m-%d")
        if day_key in buckets:
            buckets[day_key] += 1

    return [
        CompletionTrendItem(date=d, count=c) for d, c in buckets.items()
    ]


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    org_id: UUID = Query(..., description="Current organization ID"),
    trend_days: int = Query(7, ge=7, le=14, description="Days for completion trend (7 or 14)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Main dashboard: My Work + recent activity + counters."""
    user_id = user.id

    # Determine admin status
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    is_admin = (membership.role == "ADMIN") if membership else False

    # Get visible project IDs for this user
    visible_project_ids = await get_visible_project_ids(db, user_id, org_id)
    if not visible_project_ids:
        return DashboardResponse(
            my_work=MyWork(),
            activity=[],
            counters=Counters(),
            is_admin=is_admin,
        )

    # ── Load all runs in visible projects ──
    result = await db.execute(
        select(Run).where(Run.project_id.in_(visible_project_ids))
    )
    all_runs = list(result.scalars().all())

    # ── Load user's role assignments ──
    run_ids = [r.id for r in all_runs]
    user_assignments: dict[UUID, list[RunRoleAssignment]] = {}
    if run_ids:
        result = await db.execute(
            select(RunRoleAssignment).where(
                RunRoleAssignment.run_id.in_(run_ids),
                RunRoleAssignment.user_id == user_id,
            )
        )
        for assignment in result.scalars().all():
            user_assignments.setdefault(assignment.run_id, []).append(
                assignment
            )

    # Batch-resolve project/protocol names
    project_ids_set = {r.project_id for r in all_runs}
    protocol_ids_set = {r.protocol_id for r in all_runs if r.protocol_id}
    project_map, proto_map = await _resolve_names(
        db, project_ids_set, protocol_ids_set
    )

    # ── Classify runs into My Work buckets ──
    needs_action: list[RunSummary] = []
    active_runs: list[RunSummary] = []
    recently_completed: list[RunSummary] = []
    planned_runs: list[RunSummary] = []

    two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

    for run in all_runs:
        status = run.status if isinstance(run.status, str) else run.status.value
        proj_name = project_map.get(run.project_id, "")
        proto_name = proto_map.get(run.protocol_id, "") if run.protocol_id else None
        assignments = user_assignments.get(run.id, [])
        role_name = assignments[0].role_name if assignments else None

        # Is this user involved? (assigned a role OR started the run)
        user_involved = bool(assignments) or run.started_by_id == user_id

        if status == "ACTIVE":
            if user_involved:
                summary = _build_run_summary(
                    run, proj_name, proto_name, role_name
                )
                # Check if user's lanes have incomplete steps
                lane_ids = {a.lane_node_id for a in assignments}
                graph = run.graph or {}
                exec_data = run.execution_data or {}
                if _user_has_incomplete_steps(graph, exec_data, lane_ids):
                    needs_action.append(summary)
                else:
                    active_runs.append(summary)

        elif status in ("COMPLETED", "EDITED"):
            if user_involved and run.updated_at and run.updated_at >= two_weeks_ago:
                recently_completed.append(
                    _build_run_summary(run, proj_name, proto_name, role_name)
                )

        elif status == "PLANNED":
            planned_runs.append(
                _build_run_summary(run, proj_name, proto_name, role_name)
            )

    # Sort buckets
    needs_action.sort(key=lambda r: r.updated_at)
    active_runs.sort(key=lambda r: r.updated_at, reverse=True)
    recently_completed.sort(key=lambda r: r.updated_at, reverse=True)
    planned_runs.sort(key=lambda r: r.updated_at, reverse=True)

    my_work = MyWork(
        needs_action=needs_action,
        active_runs=active_runs,
        recently_completed=recently_completed[:10],
        planned_runs=planned_runs,
    )

    # ── Activity feed (last 10) ──
    activity = await _fetch_activity(db, visible_project_ids, limit=10)

    # ── Counters ──
    now = datetime.now(timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

    active_count = sum(
        1 for r in all_runs
        if (r.status if isinstance(r.status, str) else r.status.value) == "ACTIVE"
    )
    completed_this_week = sum(
        1 for r in all_runs
        if (r.status if isinstance(r.status, str) else r.status.value) in ("COMPLETED", "EDITED")
        and r.updated_at and r.updated_at >= start_of_week
    )
    planned_count = sum(
        1 for r in all_runs
        if (r.status if isinstance(r.status, str) else r.status.value) == "PLANNED"
    )

    counters = Counters(
        active_runs=active_count,
        completed_this_week=completed_this_week,
        planned_runs=planned_count,
    )

    # Admin-only counters
    if is_admin:
        result = await db.execute(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == org_id,
            )
        )
        counters.team_members = result.scalar() or 0

        counters.active_projects = len(visible_project_ids)

        result = await db.execute(
            select(func.count(Protocol.id)).where(
                Protocol.project_id.in_(visible_project_ids)
            )
        )
        counters.total_protocols = result.scalar() or 0

    # ── Completion trend ──
    completion_trend = _compute_completion_trend(all_runs, days=trend_days)

    return DashboardResponse(
        my_work=my_work,
        activity=activity,
        counters=counters,
        completion_trend=completion_trend,
        is_admin=is_admin,
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

    run_result = await db.execute(
        select(Run.id).where(Run.project_id.in_(project_ids))
    )
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
            log.changes.get("name", ""),
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
            select(Project.id, Project.name).where(
                Project.id.in_(project_ids)
            )
        )
        for pid, name in result.all():
            names[("Project", pid)] = name

    # Protocols
    if protocol_ids:
        result = await db.execute(
            select(Protocol.id, Protocol.name).where(
                Protocol.id.in_(protocol_ids)
            )
        )
        for pid, name in result.all():
            names[("Protocol", pid)] = name

    # Runs
    if run_ids:
        result = await db.execute(
            select(Run.id, Run.name).where(Run.id.in_(run_ids))
        )
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
    visible_project_ids = await get_visible_project_ids(
        db, user.id, org_id
    )
    if not visible_project_ids:
        return ActivityPage(items=[], total=0, offset=offset, limit=limit)

    items = await _fetch_activity(
        db, visible_project_ids, limit=limit, offset=offset
    )

    # Count total
    proto_result = await db.execute(
        select(Protocol.id).where(
            Protocol.project_id.in_(visible_project_ids)
        )
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

    return ActivityPage(
        items=items, total=total, offset=offset, limit=limit
    )
