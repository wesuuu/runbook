import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            OrganizationMember, PermissionLevel, PrincipalType,
                            User)
from app.models.science import Project, Protocol, Run

# --- Unit Ops ---


@pytest.mark.asyncio
async def test_list_unit_ops_authenticated(
    client: AsyncClient,
    auth_headers: dict,
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
    client: AsyncClient,
    auth_headers: dict,
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
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=second_user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.VIEW.value,
        )
    )
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


@pytest.mark.asyncio
async def test_list_protocols_filters_archived_by_default(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Archived protocols are hidden by default and shown with include_archived=true."""
    active = Protocol(
        name="Active Protocol",
        project_id=test_project.id,
        graph={},
        status="DRAFT",
    )
    archived = Protocol(
        name="Archived Protocol",
        project_id=test_project.id,
        graph={},
        status="ARCHIVED",
    )
    db_session.add_all([active, archived])
    await db_session.flush()

    # Default: archived hidden
    resp = await client.get(
        f"/science/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Active Protocol" in names
    assert "Archived Protocol" not in names

    # include_archived=true: archived included
    resp = await client.get(
        f"/science/projects/{test_project.id}/protocols",
        params={"include_archived": "true"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "Active Protocol" in names
    assert "Archived Protocol" in names


@pytest.mark.asyncio
async def test_list_protocols_surfaces_latest_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Approved protocols with an unpublished draft should expose
    latest_draft_version_number so the project table can badge them."""
    from app.models.science import ProtocolVersion

    with_draft = Protocol(
        name="Has Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=4,
    )
    no_draft = Protocol(
        name="No Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=2,
    )
    db_session.add_all([with_draft, no_draft])
    await db_session.flush()
    db_session.add(
        ProtocolVersion(
            protocol_id=with_draft.id,
            version_number=5,
            name=with_draft.name,
            graph={},
            is_draft=True,
        )
    )
    # Older non-draft version shouldn't trigger the badge.
    db_session.add(
        ProtocolVersion(
            protocol_id=no_draft.id,
            version_number=1,
            name=no_draft.name,
            graph={},
            is_draft=False,
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/science/projects/{test_project.id}/protocols",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    by_name = {p["name"]: p for p in resp.json()}
    assert by_name["Has Draft"]["latest_draft_version_number"] == 5
    assert by_name["No Draft"]["latest_draft_version_number"] is None


@pytest.mark.asyncio
async def test_get_protocol_surfaces_latest_draft_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """The single-protocol GET endpoint must surface
    latest_draft_version_number so the editor's version toggle can jump
    to an unpublished draft."""
    from app.models.science import ProtocolVersion

    protocol = Protocol(
        name="Toggle Draft",
        project_id=test_project.id,
        graph={},
        status="APPROVED",
        version_number=4,
    )
    db_session.add(protocol)
    await db_session.flush()
    db_session.add(
        ProtocolVersion(
            protocol_id=protocol.id,
            version_number=5,
            name=protocol.name,
            graph={},
            is_draft=True,
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["latest_draft_version_number"] == 5


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
    """save_as_draft creates a draft snapshot without bumping version_number.

    For DRAFT-status protocols the live graph is also synced to the new draft
    so role/lane mutations stay consistent — see
    `test_save_as_draft_syncs_live_graph_for_unpublished_protocol`.
    """
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
async def test_save_draft_always_creates_version(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Save-as-draft always creates a draft version, even for unchanged graphs.

    The user's explicit intent to save means a draft must exist so it can be
    published. Skipping draft creation caused publish to fail with 404.
    """
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [{"id": "1"}], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save the exact same graph
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # A draft v1 should now exist so publish can find it
    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    versions = resp.json()
    assert any(v["version_number"] == 1 for v in versions)


@pytest.mark.asyncio
async def test_save_as_draft_syncs_live_graph_for_unpublished_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Unpublished (DRAFT) protocol's live graph mirrors the saved draft.

    Otherwise role mutations (which write to protocols.graph directly) and
    editor edits (which only wrote to a snapshot) drift apart and orphan
    swimLane nodes survive after their roles are deleted.
    """
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [{"id": "stale"}], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    new_graph = {"nodes": [{"id": "fresh"}], "edges": []}
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": new_graph},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(protocol)
    assert protocol.graph == new_graph


@pytest.mark.asyncio
async def test_save_as_draft_preserves_live_graph_for_published_protocol(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """APPROVED protocol's live graph stays frozen until the draft is published."""
    published_graph = {"nodes": [{"id": "published"}], "edges": []}
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="APPROVED",
        version_number=1,
        graph=published_graph,
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "wip"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(protocol)
    assert protocol.graph == published_graph


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
        f"/science/runs/{run_obj.id}/role-assignments/{assignment_id}",
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


@pytest.mark.asyncio
async def test_list_versions_returns_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """List endpoint exposes the version description field."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    from app.models.science import ProtocolVersion

    version = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=1,
        name=protocol.name,
        graph={"nodes": [], "edges": []},
        description="Tightened DO range",
        change_summary="DO 30 -> 25",
        is_draft=False,
    )
    db_session.add(version)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["description"] == "Tightened DO range"
    assert versions[0]["change_summary"] == "DO 30 -> 25"


@pytest.mark.asyncio
async def test_publish_draft_persists_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft accepts an optional body with description; the value is
    written onto the published version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"description": "Switched buffer from PBS to TBS"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Switched buffer from PBS to TBS"


@pytest.mark.asyncio
async def test_publish_draft_persists_change_summary(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft writes change_summary from the body."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"change_summary": "DO range tightened"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.json()["change_summary"] == "DO range tightened"


@pytest.mark.asyncio
async def test_publish_draft_without_body_still_works(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Existing callers that don't send a body must continue to work.
    Backward-compatibility regression guard."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["version_number"] == 1
