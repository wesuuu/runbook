"""Unit tests for F-0066: Org PROTOCOL_APPROVER permission grant."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.iam import (
    ObjectType,
    Organization,
    OrganizationMember,
    OrgRole,
    PermissionLevel,
    User,
)
from app.models.science import Project, Protocol
from app.services.core.permissions import check_permission


async def _setup_approver_user(db: AsyncSession, org: Organization) -> User:
    """Create a MEMBER+PROTOCOL_APPROVER user in the given org."""
    user = User(
        email=f"approver-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Approver",
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=[OrgRole.MEMBER.value, OrgRole.PROTOCOL_APPROVER.value],
        )
    )
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_org_protocol_approver_can_view_edit_approve_protocol(
    db_session: AsyncSession,
):
    """PROTOCOL_APPROVER should pass VIEW, EDIT, APPROVE on protocols."""
    org = Organization(name="AppOrg")
    db_session.add(org)
    await db_session.flush()

    user = await _setup_approver_user(db_session, org)

    project = Project(
        name="P",
        organization_id=org.id,
        settings={"permissions_enabled": True},
    )
    db_session.add(project)
    await db_session.flush()

    proto = Protocol(
        name="proto",
        project_id=project.id,
        graph={},
        requires_approval=True,
    )
    db_session.add(proto)
    await db_session.flush()

    for level in (PermissionLevel.VIEW, PermissionLevel.EDIT, PermissionLevel.APPROVE):
        ok = await check_permission(
            db_session,
            user.id,
            ObjectType.PROTOCOL,
            proto.id,
            level,
        )
        assert ok, f"PROTOCOL_APPROVER should pass {level}"


@pytest.mark.asyncio
async def test_org_protocol_approver_cannot_admin_protocol(
    db_session: AsyncSession,
):
    """PROTOCOL_APPROVER must NOT grant ADMIN on a protocol."""
    org = Organization(name="AppOrg2")
    db_session.add(org)
    await db_session.flush()

    user = await _setup_approver_user(db_session, org)

    project = Project(
        name="P2",
        organization_id=org.id,
        settings={"permissions_enabled": True},
    )
    db_session.add(project)
    await db_session.flush()

    proto = Protocol(
        name="proto2",
        project_id=project.id,
        graph={},
    )
    db_session.add(proto)
    await db_session.flush()

    not_admin = await check_permission(
        db_session,
        user.id,
        ObjectType.PROTOCOL,
        proto.id,
        PermissionLevel.ADMIN,
    )
    assert not not_admin, "PROTOCOL_APPROVER must NOT grant ADMIN"


@pytest.mark.asyncio
async def test_org_protocol_approver_no_project_access(
    db_session: AsyncSession,
):
    """PROTOCOL_APPROVER must NOT grant any access to PROJECT objects."""
    org = Organization(name="AppOrg3")
    db_session.add(org)
    await db_session.flush()

    user = await _setup_approver_user(db_session, org)

    project = Project(
        name="P3",
        organization_id=org.id,
        settings={"permissions_enabled": True},
    )
    db_session.add(project)
    await db_session.flush()

    for level in (
        PermissionLevel.VIEW,
        PermissionLevel.EDIT,
        PermissionLevel.APPROVE,
        PermissionLevel.ADMIN,
    ):
        ok = await check_permission(
            db_session,
            user.id,
            ObjectType.PROJECT,
            project.id,
            level,
        )
        assert not ok, f"PROTOCOL_APPROVER must NOT have PROJECT {level}"
