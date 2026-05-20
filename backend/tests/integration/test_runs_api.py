import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.projects import Project
from app.models.runs import Run


@pytest.mark.asyncio
async def test_create_run(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/runs",
        json={
            "name": "New Run",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Run"


@pytest.mark.asyncio
async def test_create_run_no_project_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    resp = await client.post(
        "/runs",
        json={
            "name": "Should Fail",
            "project_id": str(test_project.id),
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_run_with_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    run_obj = Run(
        name="Readable Run",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.get(
        f"/runs/{run_obj.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Readable Run"


@pytest.mark.asyncio
async def test_get_run_without_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    second_user: User,
):
    run_obj = Run(
        name="Secret Run",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.get(
        f"/runs/{run_obj.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_run_with_edit_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    run_obj = Run(
        name="Editable Run",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"name": "Updated Run"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Run"


@pytest.mark.asyncio
async def test_list_runs_for_project(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    run_obj = Run(
        name="Listed Run",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.get(
        f"/projects/{test_project.id}/runs",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_start_run_without_assignments_fails(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that starting a run without any assignments fails."""
    run_obj = Run(
        name="Unassigned Run",
        project_id=test_project.id,
        graph={"nodes": [], "edges": []},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "at least one person" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_start_run_with_swimlanes_requires_all_assigned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that starting a run with swimlanes requires all to be assigned."""
    run_obj = Run(
        name="Partial Assignment Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                },
                {
                    "id": "lane-role-2",
                    "type": "swimLane",
                    "data": {"label": "Technician"},
                },
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    # Assign only one role
    from app.models.runs import RunRoleAssignment

    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-1",
        role_name="Scientist",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    # Try to start - should fail because second role is not assigned
    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "not all roles have assigned users" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_start_run_succeeds_with_one_assignment_no_swimlanes(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that starting a run succeeds with one assignment even without swimlanes."""
    run_obj = Run(
        name="Simple Run",
        project_id=test_project.id,
        graph={"nodes": [], "edges": []},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    from app.models.runs import RunRoleAssignment

    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="general",
        role_name="Executor",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_start_run_succeeds_with_all_swimlanes_assigned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    second_user: User,
    db_session: AsyncSession,
):
    """Test that starting a run succeeds when all swimlanes are assigned."""
    run_obj = Run(
        name="Full Assignment Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                },
                {
                    "id": "lane-role-2",
                    "type": "swimLane",
                    "data": {"label": "Technician"},
                },
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    from app.models.runs import RunRoleAssignment

    assignment1 = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-1",
        role_name="Scientist",
        user_id=test_user.id,
    )
    assignment2 = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-2",
        role_name="Technician",
        user_id=second_user.id,
    )
    db_session.add(assignment1)
    db_session.add(assignment2)
    await db_session.flush()

    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_started_by_id_set_on_active_transition(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that started_by_id is set when run transitions to ACTIVE."""
    run_obj = Run(
        name="Test Started By Run",
        project_id=test_project.id,
        graph={"nodes": []},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    from app.models.runs import RunRoleAssignment

    # Assign at least one person
    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="general",
        role_name="General",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.commit()

    # Transition to ACTIVE
    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"

    # Verify started_by_id is set
    await db_session.refresh(run_obj)
    assert run_obj.started_by_id == test_user.id
