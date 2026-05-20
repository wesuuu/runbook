import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_unit_ops_authenticated(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.get("/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_unit_ops_unauthenticated(client: AsyncClient):
    resp = await client.get("/unit-ops")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_unit_op(
    client: AsyncClient,
    auth_headers: dict,
):
    resp = await client.post(
        "/unit-ops",
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
