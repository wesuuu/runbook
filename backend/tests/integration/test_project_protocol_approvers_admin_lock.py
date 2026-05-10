"""Integration tests for F-0066: /approvers endpoints locked to project ADMIN."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.iam import (ObjectPermission, ObjectType, Organization,
                            OrganizationMember, PermissionLevel, PrincipalType,
                            User)
from app.models.science import Project


async def _make_edit_user_and_headers(
    db: AsyncSession,
    test_org: Organization,
    test_project: Project,
) -> dict:
    """Create a MEMBER user with only EDIT on the project (not ADMIN)."""
    user = User(
        email=f"edit-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Edit User",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db.add(user)
    await db.flush()

    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=["MEMBER"],
        )
    )
    db.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.EDIT.value,
        )
    )
    await db.flush()

    token = create_access_token(
        user.id,
        org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_approvers_requires_admin(
    client: AsyncClient,
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
):
    """GET /approvers must return 403 for a user with only EDIT on the project."""
    edit_headers = await _make_edit_user_and_headers(db_session, test_org, test_project)
    resp = await client.get(
        f"/projects/{test_project.id}/approvers",
        headers=edit_headers,
    )
    assert (
        resp.status_code == 403
    ), f"Expected 403 for EDIT user, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_get_approvers_admin_ok(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
):
    """GET /approvers must return 200 for a user with ADMIN on the project."""
    resp = await client.get(
        f"/projects/{test_project.id}/approvers",
        headers=auth_headers,
    )
    assert (
        resp.status_code == 200
    ), f"Expected 200 for ADMIN user, got {resp.status_code}: {resp.text}"
