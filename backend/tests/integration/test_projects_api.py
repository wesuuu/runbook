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
from app.models.science import Project


@pytest.mark.asyncio
async def test_create_project(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
):
    resp = await client.post(
        "/projects/",
        json={
            "name": "New Project",
            "description": "A test project",
            "organization_id": str(test_org.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Project"
    assert data["owner_type"] == "USER"


@pytest.mark.asyncio
async def test_create_project_non_org_member(
    client: AsyncClient,
    second_auth_headers: dict,
    test_org: Organization,
    second_user: User,
):
    resp = await client.post(
        "/projects/",
        json={
            "name": "Should Fail",
            "organization_id": str(test_org.id),
        },
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_project_unauthenticated(
    client: AsyncClient, test_org: Organization,
):
    resp = await client.post(
        "/projects/",
        json={
            "name": "No Auth",
            "organization_id": str(test_org.id),
        },
    )
    assert resp.status_code == 403  # HTTPBearer missing


@pytest.mark.asyncio
async def test_list_projects_sees_permitted_only(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    test_org: Organization,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
):
    # second_user is not in the org, should see nothing
    db_session.add(OrganizationMember(
        user_id=second_user.id,
        organization_id=test_org.id,
        is_admin=False,
    ))
    await db_session.flush()

    resp = await client.get(
        "/projects/",
        params={"organization_id": str(test_org.id)},
        headers=second_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # second_user has no permissions on test_project
    assert len(data) == 0


@pytest.mark.asyncio
async def test_list_projects_org_admin_sees_all(
    client: AsyncClient,
    auth_headers: dict,
    test_org: Organization,
    test_project: Project,
):
    resp = await client.get(
        "/projects/",
        params={"organization_id": str(test_org.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(p["name"] == "Test Project" for p in data)


@pytest.mark.asyncio
async def test_get_project_with_permission(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.get(
        f"/projects/{test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Project"


@pytest.mark.asyncio
async def test_get_project_without_permission(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
):
    resp = await client.get(
        f"/projects/{test_project.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_project_with_edit_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.put(
        f"/projects/{test_project.id}",
        json={"name": "Updated Name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_project_view_only_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
    # Give second_user VIEW only
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

    resp = await client.put(
        f"/projects/{test_project.id}",
        json={"name": "Should Fail"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_project_with_admin_perm(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    resp = await client.delete(
        f"/projects/{test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_project_edit_only_forbidden(
    client: AsyncClient,
    second_auth_headers: dict,
    test_project: Project,
    second_user: User,
    db_session: AsyncSession,
    test_org: Organization,
):
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
        permission_level=PermissionLevel.EDIT.value,
    ))
    await db_session.flush()

    resp = await client.delete(
        f"/projects/{test_project.id}",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403
