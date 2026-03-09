import pytest
from httpx import AsyncClient

from app.core.security import hash_password
from app.models.iam import User


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/auth/register", json={
        "email": "newuser@example.com",
        "password": "securepass",
        "full_name": "New User",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(
    client: AsyncClient, test_user: User,
):
    resp = await client.post("/auth/register", json={
        "email": test_user.email,
        "password": "anything",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user: User):
    resp = await client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "testpass",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user: User):
    resp = await client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "wrongpass",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client: AsyncClient):
    resp = await client.post("/auth/login", json={
        "email": "nobody@example.com",
        "password": "anything",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(
    client: AsyncClient, test_user: User, auth_headers: dict,
):
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "testuser@example.com"
    assert data["id"] == str(test_user.id)


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401  # auto_error=False → get_current_user raises 401


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert resp.status_code == 401
