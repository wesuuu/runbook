import pytest
from httpx import AsyncClient
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
from app.models.science import Project, Protocol, Experiment


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
    assert resp.status_code == 403


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
        is_admin=False,
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


# --- Experiments ---

@pytest.mark.asyncio
async def test_create_experiment(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.post(
        "/science/experiments",
        json={
            "name": "New Experiment",
            "project_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Experiment"


@pytest.mark.asyncio
async def test_create_experiment_no_project_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    resp = await client.post(
        "/science/experiments",
        json={
            "name": "Should Fail",
            "project_id": str(test_project.id),
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_experiment_with_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    experiment = Experiment(
        name="Readable Experiment",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(experiment)
    await db_session.flush()

    resp = await client.get(
        f"/science/experiments/{experiment.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Readable Experiment"


@pytest.mark.asyncio
async def test_get_experiment_without_perm(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
    second_user: User,
):
    experiment = Experiment(
        name="Secret Experiment",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(experiment)
    await db_session.flush()

    resp = await client.get(
        f"/science/experiments/{experiment.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_experiment_with_edit_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    experiment = Experiment(
        name="Editable Experiment",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(experiment)
    await db_session.flush()

    resp = await client.put(
        f"/science/experiments/{experiment.id}",
        json={"name": "Updated Experiment"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Experiment"


@pytest.mark.asyncio
async def test_list_experiments_for_project(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    experiment = Experiment(
        name="Listed Experiment",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(experiment)
    await db_session.flush()

    resp = await client.get(
        f"/science/projects/{test_project.id}/experiments",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
