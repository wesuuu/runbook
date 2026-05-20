import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.projects import Project
from app.models.protocols import Protocol


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
        f"/protocols/{protocol.id}/roles",
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
        f"/protocols/{protocol.id}/roles",
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
    from app.models.protocols import ProtocolRole

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
        f"/protocols/{protocol.id}/roles/{role.id}",
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
    from app.models.protocols import ProtocolRole

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
        f"/protocols/{protocol.id}/roles/{role.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
