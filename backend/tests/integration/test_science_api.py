import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    Organization,
    OrganizationMember,
    User,
    ObjectPermission,
    PrincipalType,
    ObjectType,
    PermissionLevel,
)
from app.models.science import Project, Protocol, Run


# --- Unit Ops ---

@pytest.mark.asyncio
async def test_list_unit_ops_authenticated(
    client: AsyncClient, auth_headers: dict,
):
    resp = await client.get("/science/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_unit_ops_unauthenticated(client: AsyncClient):
    resp = await client.get("/science/unit-ops")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_unit_op(
    client: AsyncClient, auth_headers: dict,
):
    resp = await client.post(
        "/science/unit-ops",
        json={
            "name": "Test Op",
            "category": "General",
            "description": "A test op",
            "param_schema": {},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test Op"


# --- Protocols ---

@pytest.mark.asyncio
async def test_create_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/science/protocols",
        json={
            "name": "New Protocol",
            "project_id": str(test_project.id),
            "graph": {},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Protocol"


@pytest.mark.asyncio
async def test_create_protocol_no_project_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    resp = await client.post(
        "/science/protocols",
        json={
            "name": "Should Fail",
            "project_id": str(test_project.id),
            "graph": {},
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_protocol_with_project_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Readable Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Readable Protocol"


@pytest.mark.asyncio
async def test_get_protocol_without_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    second_user: User,
):
    protocol = Protocol(
        name="Secret Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_protocol_with_edit_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Editable Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}",
        json={"name": "Updated Protocol"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Protocol"


@pytest.mark.asyncio
async def test_update_protocol_view_only_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    # Give second_user VIEW only on the project
    db_session.add(OrganizationMember(
        user_id=second_user.id,
        organization_id=test_org.id,
        role="MEMBER",
    ))
    db_session.add(ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=second_user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=test_project.id,
        permission_level=PermissionLevel.VIEW.value,
    ))
    await db_session.flush()

    protocol = Protocol(
        name="View Only Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}",
        json={"name": "Should Fail"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_protocols_for_project(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Listed Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/science/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


# --- Protocol Roles ---

@pytest.mark.asyncio
async def test_list_protocol_roles(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Role Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}/roles",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_protocol_role(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    protocol = Protocol(
        name="Role Creation Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.post(
        f"/science/protocols/{protocol.id}/roles",
        json={"name": "Operator", "color": "#ff0000", "sort_order": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Operator"


@pytest.mark.asyncio
async def test_update_protocol_role(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    from app.models.science import ProtocolRole

    protocol = Protocol(
        name="Role Update Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    role = ProtocolRole(
        protocol_id=protocol.id,
        name="OldName",
        color="#aaa",
        sort_order=0,
    )
    db_session.add(role)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}/roles/{role.id}",
        json={"name": "NewName"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "NewName"


@pytest.mark.asyncio
async def test_delete_protocol_role(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    from app.models.science import ProtocolRole

    protocol = Protocol(
        name="Role Delete Protocol",
        project_id=test_project.id,
        graph={},
    )
    db_session.add(protocol)
    await db_session.flush()

    role = ProtocolRole(
        protocol_id=protocol.id,
        name="Deletable",
        color="#bbb",
        sort_order=0,
    )
    db_session.add(role)
    await db_session.flush()

    resp = await client.delete(
        f"/science/protocols/{protocol.id}/roles/{role.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


# --- Runs ---

@pytest.mark.asyncio
async def test_create_run(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/science/runs",
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
        "/science/runs",
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
        f"/science/runs/{run_obj.id}",
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
        f"/science/runs/{run_obj.id}",
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
        f"/science/runs/{run_obj.id}",
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
        f"/science/projects/{test_project.id}/runs",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# --- Project Members ---

@pytest.mark.asyncio
async def test_get_project_members(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    test_user: User,
    db_session: AsyncSession,
):
    """Test getting members of a project."""
    resp = await client.get(
        f"/science/projects/{test_project.id}/members",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    members = resp.json()
    assert isinstance(members, list)
    # test_user is the owner of test_project and should be in the list
    member_ids = [m["id"] for m in members]
    assert str(test_user.id) in member_ids


@pytest.mark.asyncio
async def test_get_project_members_no_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
):
    """Test that user without VIEW perm cannot get members."""
    resp = await client.get(
        f"/science/projects/{test_project.id}/members",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


# --- Run Role Assignments ---

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
        f"/science/runs/{run_obj.id}/role-assignments",
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
    from app.models.science import RunRoleAssignment

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
        f"/science/runs/{run_obj.id}/role-assignments",
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
        f"/science/runs/{run_obj.id}/role-assignments",
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
        f"/science/runs/{run_obj.id}/role-assignments",
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
    from app.models.science import RunRoleAssignment

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
        f"/science/runs/{run_obj.id}/role-assignments/{assignment.id}",
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
    from app.models.science import RunRoleAssignment

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
        f"/science/runs/{run_obj.id}",
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
        f"/science/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # Should fail because no one is assigned at all
    assert "at least one person" in resp.json()["detail"]


# --- Protocol Publishing ---


@pytest.mark.asyncio
async def test_publish_protocol_success(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that publishing a draft version updates the main protocol."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save as draft (creates draft version v1)
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "test"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Publish the draft
    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["version_number"] == 1
    assert len(result["graph"]["nodes"]) == 1


@pytest.mark.asyncio
async def test_save_as_draft_creates_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that save_as_draft creates a draft version without modifying main protocol."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()
    original_version = protocol.version_number

    # Save as draft
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "draft"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Check that main protocol version_number didn't change
    result = resp.json()
    assert result["version_number"] == original_version

    # Check versions list includes the draft
    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    draft_found = any(v.get("version_number") == 1 for v in versions)
    assert draft_found


@pytest.mark.asyncio
async def test_publish_draft_not_found(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test publishing non-existent draft version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=999",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_save_draft_no_changes(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Test that saving identical graph doesn't create new version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [{"id": "1"}], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Try to save the exact same graph
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Check that no new version was created
    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    versions = resp.json()
    # Should not have v1 since no changes
    assert all(v["version_number"] != 1 for v in versions)


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
        f"/science/runs/{run_obj.id}",
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
    from app.models.science import RunRoleAssignment
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
        f"/science/runs/{run_obj.id}",
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

    from app.models.science import RunRoleAssignment
    assignment = RunRoleAssignment(
        run_id=run_obj.id,
        lane_node_id="general",
        role_name="Executor",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    resp = await client.put(
        f"/science/runs/{run_obj.id}",
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

    from app.models.science import RunRoleAssignment
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
        f"/science/runs/{run_obj.id}",
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

    from app.models.science import RunRoleAssignment
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
        f"/science/runs/{run_obj.id}",
        json={"status": "ACTIVE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"

    # Verify started_by_id is set
    await db_session.refresh(run_obj)
    assert run_obj.started_by_id == test_user.id


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
        f"/science/runs/{run_obj.id}/role-assignments",
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
        select(AuditLog)
        .where(
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
        f"/science/runs/{run_obj.id}/role-assignments",
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
        select(AuditLog)
        .where(
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
        f"/science/runs/{run_obj.id}/role-assignments/{assignment_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify DELETE audit log
    result = await db_session.execute(
        select(AuditLog)
        .where(
            (AuditLog.entity_type == "RunRoleAssignment")
            & (AuditLog.entity_id == assignment_id)
            & (AuditLog.action == "DELETE")
        )
    )
    delete_log = result.scalar_one_or_none()
    assert delete_log is not None
    assert delete_log.actor_id == test_user.id
    assert "lane_node_id" in delete_log.changes
