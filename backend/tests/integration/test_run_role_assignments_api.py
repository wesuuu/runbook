import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.projects import Project
from app.models.runs import Run


@pytest.mark.asyncio
async def test_create_role_assignment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test creating a role assignment."""
    run_obj = Run(
        name="Assignment Test Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                }
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    resp = await client.post(
        f"/runs/{run_obj.id}/role-assignments",
        json={
            "lane_node_id": "lane-role-1",
            "role_name": "Scientist",
            "user_id": str(test_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["lane_node_id"] == "lane-role-1"
    assert data["role_name"] == "Scientist"
    assert data["user_id"] == str(test_user.id)


@pytest.mark.asyncio
async def test_get_role_assignments(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test listing role assignments."""
    from app.models.runs import RunRoleAssignment

    run_obj = Run(
        name="List Assignment Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                }
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-1",
        role_name="Scientist",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    resp = await client.get(
        f"/runs/{run_obj.id}/role-assignments",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["lane_node_id"] == "lane-role-1"


@pytest.mark.asyncio
async def test_update_role_assignment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    second_user: User,
    db_session: AsyncSession,
):
    """Test updating a role assignment by reassigning to a different user."""
    run_obj = Run(
        name="Update Assignment Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                }
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    # Create initial assignment
    resp = await client.post(
        f"/runs/{run_obj.id}/role-assignments",
        json={
            "lane_node_id": "lane-role-1",
            "role_name": "Scientist",
            "user_id": str(test_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Update to assign to second_user
    resp = await client.post(
        f"/runs/{run_obj.id}/role-assignments",
        json={
            "lane_node_id": "lane-role-1",
            "role_name": "Scientist",
            "user_id": str(second_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == str(second_user.id)


@pytest.mark.asyncio
async def test_delete_role_assignment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test deleting a role assignment."""
    from app.models.runs import RunRoleAssignment

    run_obj = Run(
        name="Delete Assignment Run",
        project_id=test_project.id,
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                }
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-1",
        role_name="Scientist",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    resp = await client.delete(
        f"/runs/{run_obj.id}/role-assignments/{assignment.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_transition_to_active_with_all_roles_assigned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that run can transition to ACTIVE when all roles are assigned."""
    from app.models.runs import RunRoleAssignment

    run_obj = Run(
        name="Ready to Start",
        project_id=test_project.id,
        status="PLANNED",
        graph={
            "nodes": [
                {
                    "id": "lane-role-1",
                    "type": "swimLane",
                    "data": {"label": "Scientist"},
                }
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    # Assign the role
    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="lane-role-1",
        role_name="Scientist",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    # Transition to ACTIVE
    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_transition_to_active_without_all_roles_assigned(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that run cannot transition to ACTIVE if not all roles are assigned."""
    run_obj = Run(
        name="Not Ready to Start",
        project_id=test_project.id,
        status="PLANNED",
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
                    "data": {"label": "QC"},
                },
            ]
        },
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    # Don't assign any roles

    # Try to transition to ACTIVE - should fail
    resp = await client.put(
        f"/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # Should fail because no one is assigned at all
    assert "at least one person" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_assignment_operations_audit_logged(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that assignment CREATE, UPDATE, and DELETE operations are audited."""
    from uuid import UUID

    from app.models.execution import AuditLog

    run_obj = Run(
        name="Test Audit Run",
        project_id=test_project.id,
        graph={"nodes": []},
        execution_data={},
    )
    db_session.add(run_obj)
    await db_session.flush()

    # Create assignment
    resp = await client.post(
        f"/runs/{run_obj.id}/role-assignments",
        json={
            "lane_node_id": "general",
            "role_name": "General",
            "user_id": str(test_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assignment_id = UUID(resp.json()["id"])

    # Verify CREATE audit log
    result = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "RunRoleAssignment")
            & (AuditLog.entity_id == assignment_id)
            & (AuditLog.action == "CREATE")
        )
    )
    create_log = result.scalar_one_or_none()
    assert create_log is not None
    assert create_log.actor_id == test_user.id
    assert "lane_node_id" in create_log.changes
    assert "user_id" in create_log.changes

    # Update assignment (same endpoint, replaces existing assignment)
    resp = await client.post(
        f"/runs/{run_obj.id}/role-assignments",
        json={
            "lane_node_id": "general",
            "role_name": "General",
            "user_id": str(test_user.id),  # Same user, just updating
        },
        headers=auth_headers,
    )
    # Endpoint returns 201 for both create and update
    assert resp.status_code in [200, 201]

    # Verify UPDATE audit log
    result = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "RunRoleAssignment")
            & (AuditLog.entity_id == assignment_id)
            & (AuditLog.action == "UPDATE")
        )
    )
    update_log = result.scalar_one_or_none()
    assert update_log is not None
    assert update_log.actor_id == test_user.id

    # Delete assignment
    resp = await client.delete(
        f"/runs/{run_obj.id}/role-assignments/{assignment_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify DELETE audit log
    result = await db_session.execute(
        select(AuditLog).where(
            (AuditLog.entity_type == "RunRoleAssignment")
            & (AuditLog.entity_id == assignment_id)
            & (AuditLog.action == "DELETE")
        )
    )
    delete_log = result.scalar_one_or_none()
    assert delete_log is not None
    assert delete_log.actor_id == test_user.id
    assert "lane_node_id" in delete_log.changes
