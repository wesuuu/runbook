"""Tests for services/runs/blockers.list_blocked_runs (F-0092)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.iam import Organization
from app.models.projects import Project
from app.models.runs import Run, RunRoleAssignment
from app.services.runs.blockers import list_blocked_runs
from app.services.runs.graph_facts import extract_graph_facts


def _run(project_id, *, status="PLANNED", graph=None):
    return Run(
        name="R",
        project_id=project_id,
        status=status,
        graph=graph or {"nodes": []},
        execution_data={},
    )


def _facts(runs):
    return {r.id: extract_graph_facts(r.graph or {}) for r in runs}


async def _assignments_for(db_session, run_id):
    result = await db_session.execute(
        select(RunRoleAssignment).where(RunRoleAssignment.run_id == run_id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_lanes_only_blocker(
    db_session: AsyncSession, test_org: Organization, test_project: Project
):
    run = _run(test_project.id, graph={
        "nodes": [{"id": "lane-a", "type": "swimLane"}]
    })
    db_session.add(run)
    await db_session.flush()

    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), {run.id: []}, test_org.id
    )
    assert run.id in blocked
    codes = {b.code for b in blocked[run.id]}
    assert codes == {"LANES_UNASSIGNED"}
    assert blocked[run.id][0].label == "1 role unassigned"


@pytest.mark.asyncio
async def test_no_one_assigned_label(
    db_session: AsyncSession, test_org: Organization, test_project: Project
):
    run = _run(test_project.id, graph={"nodes": []})
    db_session.add(run)
    await db_session.flush()
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), {run.id: []}, test_org.id
    )
    assert blocked[run.id][0].label == "No one assigned"


@pytest.mark.asyncio
async def test_stale_lane_assignment_blocker(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user,
):
    # All swimlanes assigned, plus a stale assignment to a removed lane —
    # the start gate rejects this, so the dashboard must flag it too.
    run = _run(test_project.id, graph={
        "nodes": [{"id": "lane-a", "type": "swimLane"}]
    })
    db_session.add(run)
    await db_session.flush()
    for lane in ("lane-a", "lane-removed"):
        db_session.add(RunRoleAssignment(
            run_id=run.id, lane_node_id=lane, role_name="Op", user_id=test_user.id
        ))
    await db_session.flush()
    assignments = {run.id: await _assignments_for(db_session, run.id)}
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), assignments, test_org.id
    )
    assert {b.code for b in blocked[run.id]} == {"LANES_UNASSIGNED"}
    assert blocked[run.id][0].label == "Role assignments out of sync"


@pytest.mark.asyncio
async def test_equipment_overdue_blocker(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user,
    default_site_id: str,
):
    eq = Equipment(
        organization_id=test_org.id, site_id=default_site_id,
        name="Old Centrifuge",
        next_calibration_date=date.today() - timedelta(days=10),
    )
    db_session.add(eq)
    await db_session.flush()
    run = _run(test_project.id, graph={
        "nodes": [
            {"id": "op-1", "type": "unitOp",
             "data": {"equipment": [{"equipment_id": str(eq.id)}]}},
        ]
    })
    # assign someone so lanes don't also block
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        RunRoleAssignment(run_id=run.id, lane_node_id="x", role_name="Op", user_id=test_user.id)
    )
    await db_session.flush()
    assignments = {run.id: await _assignments_for(db_session, run.id)}
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), assignments, test_org.id
    )
    assert {b.code for b in blocked[run.id]} == {"EQUIPMENT_CALIBRATION_OVERDUE"}
    assert "Old Centrifuge calibration overdue" == blocked[run.id][0].label


@pytest.mark.asyncio
async def test_future_and_archived_equipment_not_flagged(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user,
    default_site_id: str,
):
    future = Equipment(
        organization_id=test_org.id, site_id=default_site_id, name="Fresh",
        next_calibration_date=date.today() + timedelta(days=100),
    )
    archived = Equipment(
        organization_id=test_org.id, site_id=default_site_id, name="Gone",
        next_calibration_date=date.today() - timedelta(days=10),
        archived_at=datetime.now(timezone.utc),
    )
    db_session.add_all([future, archived])
    await db_session.flush()
    run = _run(test_project.id, graph={
        "nodes": [
            {"id": "op-1", "type": "unitOp", "data": {"equipment": [
                {"equipment_id": str(future.id)},
                {"equipment_id": str(archived.id)},
            ]}},
        ]
    })
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        RunRoleAssignment(run_id=run.id, lane_node_id="x", role_name="Op", user_id=test_user.id)
    )
    await db_session.flush()
    assignments = {run.id: await _assignments_for(db_session, run.id)}
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), assignments, test_org.id
    )
    assert run.id not in blocked


@pytest.mark.asyncio
async def test_active_run_never_blocked(
    db_session: AsyncSession, test_org: Organization, test_project: Project
):
    run = _run(test_project.id, status="ACTIVE", graph={
        "nodes": [{"id": "lane-a", "type": "swimLane"}]
    })
    db_session.add(run)
    await db_session.flush()
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), {run.id: []}, test_org.id
    )
    assert blocked == {}


@pytest.mark.asyncio
async def test_edited_run_never_blocked(
    db_session: AsyncSession, test_org: Organization, test_project: Project
):
    # EDITED is a re-opened COMPLETED run — still modifiable, but it has
    # already started, so the start-gate blockers never apply to it.
    run = _run(test_project.id, status="EDITED", graph={
        "nodes": [{"id": "lane-a", "type": "swimLane"}]
    })
    db_session.add(run)
    await db_session.flush()
    blocked = await list_blocked_runs(
        db_session, [run], _facts([run]), {run.id: []}, test_org.id
    )
    assert blocked == {}
