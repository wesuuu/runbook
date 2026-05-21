"""Integration tests for the F-0092 Action Rail dashboard endpoint."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.equipment import Equipment
from app.models.iam import Organization, User
from app.models.projects import Project
from app.models.runs import Run, RunRoleAssignment
from app.services.runs import graph_facts as graph_facts_mod


async def _planned_run(db, project, *, created_by=None, graph=None):
    run = Run(
        name="Planned Run",
        project_id=project.id,
        status="PLANNED",
        graph=graph or {"nodes": []},
        execution_data={},
        created_by_id=created_by,
    )
    db.add(run)
    await db.flush()
    return run


async def test_dashboard_response_shape(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_project: Project,
):
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"my_work", "lab_status", "activity", "counters"}
    assert set(body["my_work"]) == {"needs_action", "in_progress", "planned"}
    assert set(body["counters"]) == {
        "runs_blocked", "calibrations_due", "signoffs_pending", "active_runs",
    }
    assert "completion_trend" not in body
    assert "pending_analyses" not in body


async def test_blocked_planned_run_promoted_to_needs_action(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
):
    # a PLANNED run the user created, with an unassigned swimlane → blocked
    run = await _planned_run(
        db_session, test_project, created_by=test_user.id,
        graph={"nodes": [{"id": "lane-a", "type": "swimLane"}]},
    )
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    body = resp.json()
    needs_action_ids = {r["id"] for r in body["my_work"]["needs_action"]}
    planned_ids = {r["id"] for r in body["my_work"]["planned"]}
    assert str(run.id) in needs_action_ids
    assert str(run.id) not in planned_ids
    assert body["counters"]["runs_blocked"] == 1
    blocked_card = next(
        r for r in body["my_work"]["needs_action"] if r["id"] == str(run.id)
    )
    assert blocked_card["blockers"][0]["code"] == "LANES_UNASSIGNED"


async def test_counters_match_list_lengths(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    default_site_id: str,
):
    db_session.add(Equipment(
        organization_id=test_org.id, site_id=default_site_id,
        name="Overdue Eq",
        next_calibration_date=date.today() - timedelta(days=5),
    ))
    await db_session.flush()
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    body = resp.json()
    cal = body["lab_status"]["calibration"]
    assert body["counters"]["calibrations_due"] == (
        len(cal["overdue"]) + len(cal["due_soon"])
    )
    assert body["counters"]["signoffs_pending"] == len(
        body["lab_status"]["awaiting_signoff"]
    )


async def test_non_creator_lane_assignee_sees_planned_run(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
):
    other = User(
        email="other@example.com",
        hashed_password=hash_password("x"),
        full_name="Other",
        email_verified=True,
    )
    db_session.add(other)
    await db_session.flush()
    run = await _planned_run(db_session, test_project, created_by=other.id)
    db_session.add(RunRoleAssignment(
        run_id=run.id, lane_node_id="lane-a", role_name="Op",
        user_id=test_user.id,
    ))
    await db_session.flush()
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    all_ids = {
        r["id"]
        for bucket in resp.json()["my_work"].values()
        for r in bucket
    }
    assert str(run.id) in all_ids


async def test_orphan_planned_run_visible_to_project_member(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
):
    # no creator, no assignments → orphan; test_user sees test_project
    run = await _planned_run(db_session, test_project, created_by=None)
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    all_ids = {
        r["id"]
        for bucket in resp.json()["my_work"].values()
        for r in bucket
    }
    assert str(run.id) in all_ids


async def test_unrelated_run_not_shown(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
):
    other = User(
        email="stranger@example.com",
        hashed_password=hash_password("x"),
        full_name="Stranger",
        email_verified=True,
    )
    db_session.add(other)
    await db_session.flush()
    run = await _planned_run(db_session, test_project, created_by=other.id)
    db_session.add(RunRoleAssignment(
        run_id=run.id, lane_node_id="lane-a", role_name="Op",
        user_id=other.id,
    ))
    await db_session.flush()
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    all_ids = {
        r["id"]
        for bucket in resp.json()["my_work"].values()
        for r in bucket
    }
    assert str(run.id) not in all_ids


async def test_orphan_with_foreign_assignment_and_null_creator_hidden(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
):
    """A PLANNED run with a null creator is NOT an orphan once it has any
    RunRoleAssignment — even one belonging to another user — so scope D must
    not match it and it must not appear for me."""
    other = User(
        email="lab-tech@example.com",
        hashed_password=hash_password("x"),
        full_name="Lab Tech",
        email_verified=True,
    )
    db_session.add(other)
    await db_session.flush()
    run = await _planned_run(db_session, test_project, created_by=None)
    db_session.add(RunRoleAssignment(
        run_id=run.id, lane_node_id="lane-a", role_name="Op",
        user_id=other.id,
    ))
    await db_session.flush()
    resp = await client.get(
        f"/dashboard?org_id={test_org.id}", headers=auth_headers
    )
    all_ids = {
        r["id"]
        for bucket in resp.json()["my_work"].values()
        for r in bucket
    }
    assert str(run.id) not in all_ids


async def test_no_n_plus_one_as_run_count_grows(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
    default_site_id: str,
):
    """Query + graph-walk count stay bounded as runs AND equipment grow."""
    async def _measure(n: int) -> tuple[int, int]:
        # Scale BOTH runs and equipment so the guard catches a per-run OR a
        # per-equipment query regression.
        for _ in range(n):
            await _planned_run(
                db_session, test_project, created_by=test_user.id
            )
            db_session.add(Equipment(
                organization_id=test_org.id, site_id=default_site_id,
                name="Cal Eq",
                next_calibration_date=date.today() - timedelta(days=3),
            ))
        await db_session.flush()
        queries: list[str] = []

        def _count(conn, cursor, statement, *a):
            queries.append(statement)

        engine = db_session.bind
        event.listen(engine.sync_engine, "before_cursor_execute", _count)
        try:
            with patch(
                "app.api.endpoints.dashboard.extract_graph_facts",
                wraps=graph_facts_mod.extract_graph_facts,
            ) as spy:
                resp = await client.get(
                    f"/dashboard?org_id={test_org.id}", headers=auth_headers
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count)
        assert resp.status_code == 200
        # one extract_graph_facts call per in-scope run, never more
        n_in_scope = len({
            r["id"]
            for bucket in resp.json()["my_work"].values()
            for r in bucket
        })
        assert spy.call_count == n_in_scope
        return len(queries), n_in_scope

    q_small, _ = await _measure(2)
    q_large, _ = await _measure(6)
    # SQL round-trips must not scale with the number of runs
    assert q_large <= q_small + 2
