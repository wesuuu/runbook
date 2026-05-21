"""Regression: the PLANNED->ACTIVE start gate behaves identically after the
lane_assignment_gap extraction (F-0092)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.projects import Project
from app.models.runs import Run, RunRoleAssignment


@pytest.fixture
async def planned_run(db_session: AsyncSession, test_project: Project, test_user: User) -> Run:
    run = Run(
        name="Start Gate Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": []},
        execution_data={},
        created_by_id=test_user.id,
    )
    db_session.add(run)
    await db_session.flush()
    return run


async def test_start_blocked_when_no_assignee(
    client: AsyncClient, auth_headers: dict, planned_run: Run
):
    resp = await client.put(
        f"/runs/{planned_run.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "at least one person" in resp.json()["detail"]


async def test_start_blocked_when_swimlane_unassigned(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
):
    run = Run(
        name="Lane Gate Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={
            "nodes": [
                {"id": "lane-a", "type": "swimLane"},
                {"id": "lane-b", "type": "swimLane"},
            ]
        },
        execution_data={},
        created_by_id=test_user.id,
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        RunRoleAssignment(
            run_id=run.id,
            lane_node_id="lane-a",
            role_name="Operator",
            user_id=test_user.id,
        )
    )
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "not all roles" in resp.json()["detail"]


async def test_start_blocked_when_assignment_is_stale(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
):
    # Both swimlanes assigned, PLUS an assignment to a lane no longer in the
    # graph. The live gate's set-equality check rejects this; the refactor
    # must keep rejecting it.
    run = Run(
        name="Stale Lane Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={
            "nodes": [
                {"id": "lane-a", "type": "swimLane"},
                {"id": "lane-b", "type": "swimLane"},
            ]
        },
        execution_data={},
        created_by_id=test_user.id,
    )
    db_session.add(run)
    await db_session.flush()
    for lane in ("lane-a", "lane-b", "lane-deleted"):
        db_session.add(
            RunRoleAssignment(
                run_id=run.id,
                lane_node_id=lane,
                role_name="Operator",
                user_id=test_user.id,
            )
        )
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "not all roles" in resp.json()["detail"]
