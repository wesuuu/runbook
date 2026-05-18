"""Integration tests for POST /science/protocols/{id}/designate-approval."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.science import Project, Protocol


async def _make_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    status: str = "DRAFT",
) -> Protocol:
    proto = Protocol(
        name="Test Protocol",
        project_id=project.id,
        status=status,
        created_by_id=creator_id,
    )
    db.add(proto)
    await db.flush()
    return proto


async def _make_edit_user(
    db: AsyncSession,
    test_org: Organization,
    test_project: Project,
) -> tuple[User, dict]:
    user = User(
        email=f"editor-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Editor",
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
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_designate_approval_requires_project_setting(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """When project.settings.require_protocol_approval is False,
    enabling requires_approval must 400."""
    # test_project fixture only sets permissions_enabled — flag is absent.
    proto = await _make_protocol(db_session, test_project, test_user.id)
    resp = await client.post(
        f"/science/protocols/{proto.id}/designate-approval",
        json={"requires_approval": True},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "require_protocol_approval" in resp.text


@pytest.mark.asyncio
async def test_designate_approval_non_creator_non_admin_403(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """A different user who only has EDIT (not ADMIN, not creator) → 403."""
    test_project.settings = {
        **(test_project.settings or {}),
        "require_protocol_approval": True,
    }
    await db_session.flush()
    proto = await _make_protocol(db_session, test_project, test_user.id)
    _, edit_headers = await _make_edit_user(db_session, test_org, test_project)
    resp = await client.post(
        f"/science/protocols/{proto.id}/designate-approval",
        json={"requires_approval": True},
        headers=edit_headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_designate_approval_creator_with_setting_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """Creator + setting enabled → 200, requires_approval flips."""
    test_project.settings = {
        **(test_project.settings or {}),
        "require_protocol_approval": True,
    }
    await db_session.flush()
    proto = await _make_protocol(db_session, test_project, test_user.id)
    resp = await client.post(
        f"/science/protocols/{proto.id}/designate-approval",
        json={"requires_approval": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["requires_approval"] is True


@pytest.mark.asyncio
async def test_designate_approval_blocked_when_not_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """Status != DRAFT → 400."""
    test_project.settings = {
        **(test_project.settings or {}),
        "require_protocol_approval": True,
    }
    await db_session.flush()
    proto = await _make_protocol(
        db_session, test_project, test_user.id, status="PENDING_APPROVAL"
    )
    resp = await client.post(
        f"/science/protocols/{proto.id}/designate-approval",
        json={"requires_approval": True},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "DRAFT" in resp.text
