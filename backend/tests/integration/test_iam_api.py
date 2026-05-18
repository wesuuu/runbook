from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    Team,
    TeamMember,
    User,
)
from app.models.science import Project

# --- Organizations ---


@pytest.mark.asyncio
async def test_create_org(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/iam/organizations",
        json={"name": "New Org"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Org"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_orgs(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
):
    resp = await client.get("/iam/organizations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    names = [o["name"] for o in data]
    assert "Test Org" in names


@pytest.mark.asyncio
async def test_get_org(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
):
    resp = await client.get(
        f"/iam/organizations/{test_org.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Org"


# --- Organization Members ---


@pytest.mark.asyncio
async def test_add_org_member(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    second_user: User,
):
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(second_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(second_user.id)
    assert data["role"] == "MEMBER"


@pytest.mark.asyncio
async def test_add_org_member_non_admin_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_org: Organization,
    second_user: User,
    db_session: AsyncSession,
):
    # second_user is not an org member, so can't add members
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(second_user.id)},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_org_members_as_non_admin(
    client: AsyncClient,
    second_auth_headers: dict,
    test_org: Organization,
    test_user: User,
    second_user: User,
    db_session: AsyncSession,
):
    """Non-admin org members should be able to list all org members."""
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/iam/organizations/{test_org.id}/members",
        headers=second_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2  # test_user (admin) + second_user (member)
    emails = [m["email"] for m in data]
    assert "second@example.com" in emails
    assert "testuser@example.com" in emails


@pytest.mark.asyncio
async def test_list_org_members_non_member_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_org: Organization,
):
    """Users who are not org members should get 403."""
    resp = await client.get(
        f"/iam/organizations/{test_org.id}/members",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_remove_org_member(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    second_user: User,
    db_session: AsyncSession,
):
    # Add second_user first
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    resp = await client.delete(
        f"/iam/organizations/{test_org.id}/members/{second_user.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_toggle_org_admin(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    second_user: User,
    db_session: AsyncSession,
):
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    resp = await client.patch(
        f"/iam/organizations/{test_org.id}/members/{second_user.id}",
        json={"role": "ADMIN"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "ADMIN"


# --- Teams ---


@pytest.mark.asyncio
async def test_create_team(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
):
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/teams",
        json={"name": "Alpha Team"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Alpha Team"


@pytest.mark.asyncio
async def test_create_team_non_admin_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_org: Organization,
    second_user: User,
):
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/teams",
        json={"name": "Should Fail"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_teams(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_team: Team,
):
    resp = await client.get(
        f"/iam/organizations/{test_org.id}/teams",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_delete_team(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_team: Team,
):
    resp = await client.delete(
        f"/iam/organizations/{test_org.id}/teams/{test_team.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


# --- Team Members ---


@pytest.mark.asyncio
async def test_add_team_member(
    client: AsyncClient,
    auth_headers: dict,
    test_team: Team,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    # Second user must be org member first
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/iam/teams/{test_team.id}/members",
        json={"user_id": str(second_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(second_user.id)


@pytest.mark.asyncio
async def test_remove_team_member(
    client: AsyncClient,
    auth_headers: dict,
    test_team: Team,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    db_session.add(
        TeamMember(
            user_id=second_user.id,
            team_id=test_team.id,
            role="MEMBER",
        )
    )
    await db_session.flush()

    resp = await client.delete(
        f"/iam/teams/{test_team.id}/members/{second_user.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


# --- Permissions ---


@pytest.mark.asyncio
async def test_grant_permission(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    resp = await client.post(
        "/iam/permissions",
        json={
            "principal_type": "USER",
            "principal_id": str(second_user.id),
            "object_type": "PROJECT",
            "object_id": str(test_project.id),
            "permission_level": "VIEW",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["permission_level"] == "VIEW"


@pytest.mark.asyncio
async def test_grant_permission_without_admin(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    # second_user has no perms on test_project
    resp = await client.post(
        "/iam/permissions",
        json={
            "principal_type": "USER",
            "principal_id": str(second_user.id),
            "object_type": "PROJECT",
            "object_id": str(test_project.id),
            "permission_level": "VIEW",
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_revoke_permission(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
):
    perm = ObjectPermission(
        principal_type=PrincipalType.USER,
        principal_id=second_user.id,
        object_type=ObjectType.PROJECT.value,
        object_id=test_project.id,
        permission_level=PermissionLevel.VIEW.value,
    )
    db_session.add(perm)
    await db_session.flush()

    resp = await client.delete(
        f"/iam/permissions/{perm.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_permissions_on_object(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.get(
        "/iam/permissions",
        params={
            "object_type": "PROJECT",
            "object_id": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # At least the admin perm from test_project fixture


@pytest.mark.asyncio
async def test_list_permissions_unauthenticated(client: AsyncClient):
    resp = await client.get(
        "/iam/permissions",
        params={
            "object_type": "PROJECT",
            "object_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 401  # auto_error=False → get_current_user raises 401


# --- User Search (Cross-Org Isolation) ---


@pytest.mark.asyncio
async def test_search_users_returns_same_org_only(
    client: AsyncClient,
    auth_headers: dict,
    test_user: User,
    second_user: User,
):
    """User search must only return users who share an org with the caller."""
    # test_user is in Test Org; second_user is in Second Org (no overlap)
    # Search for second_user's email — should NOT appear
    resp = await client.get(
        "/iam/users",
        params={"email": "second@example"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    emails = [u["email"] for u in data]
    assert "second@example.com" not in emails


@pytest.mark.asyncio
async def test_search_users_returns_shared_org_member(
    client: AsyncClient,
    auth_headers: dict,
    test_user: User,
    second_user: User,
    test_org: Organization,
    db_session: AsyncSession,
):
    """User search returns users who share an org with the caller."""
    # Add second_user to test_org so they share an org
    db_session.add(
        OrganizationMember(
            user_id=second_user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    await db_session.flush()

    resp = await client.get(
        "/iam/users",
        params={"email": "second@example"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    emails = [u["email"] for u in data]
    assert "second@example.com" in emails


@pytest.mark.asyncio
async def test_search_users_logs_cross_org_attempt(
    client: AsyncClient,
    auth_headers: dict,
    test_user: User,
    second_user: User,
    caplog,
):
    """A cross-org search attempt should log a warning to stdout."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app.api.endpoints.iam"):
        resp = await client.get(
            "/iam/users",
            params={"email": "second@example"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert len(resp.json()) == 0  # second_user excluded
    assert "Cross-org user search detected" in caplog.text
    assert str(test_user.id) in caplog.text
