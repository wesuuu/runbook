"""Integration tests for POST /protocols/{id}/submit-for-approval."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.execution import AuditLog
from app.models.iam import (
    ObjectPermission,
    ObjectType,
    Organization,
    OrganizationMember,
    PermissionLevel,
    PrincipalType,
    User,
)
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.signoffs import GlpSignoffRequest


async def _make_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    *,
    requires_approval: bool = True,
    status: str = "DRAFT",
) -> Protocol:
    proto = Protocol(
        name="Test Protocol",
        project_id=project.id,
        status=status,
        created_by_id=creator_id,
        requires_approval=requires_approval,
    )
    db.add(proto)
    await db.flush()
    return proto


async def _make_org_member(
    db: AsyncSession,
    org: Organization,
    *,
    roles: list[str],
    email: str | None = None,
) -> User:
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Approver",
        selected_org_id=org.id,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=roles,
        )
    )
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_submit_for_approval_requires_designation(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """If protocol.requires_approval is False → 400."""
    proto = await _make_protocol(
        db_session, test_project, test_user.id, requires_approval=False
    )
    other = await _make_org_member(
        db_session, test_project.organization, roles=["MEMBER"]
    )  # noqa: E501
    resp = await client.post(
        f"/protocols/{proto.id}/submit-for-approval",
        json={"requested_user_ids": [str(other.id)]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "require" in resp.text.lower()


@pytest.mark.asyncio
async def test_submit_for_approval_rejects_ineligible_user(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Requested user who is neither project APPROVE nor org PROTOCOL_APPROVER → 400."""
    proto = await _make_protocol(db_session, test_project, test_user.id)
    rando = await _make_org_member(db_session, test_org, roles=["MEMBER"])
    resp = await client.post(
        f"/protocols/{proto.id}/submit-for-approval",
        json={"requested_user_ids": [str(rando.id)]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "eligible" in resp.text.lower()


@pytest.mark.asyncio
async def test_submit_for_approval_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Happy path: status flips, OPEN request added, SUBMITTED event written."""
    proto = await _make_protocol(db_session, test_project, test_user.id)

    # Make an org PROTOCOL_APPROVER
    approver = await _make_org_member(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )

    resp = await client.post(
        f"/protocols/{proto.id}/submit-for-approval",
        json={"requested_user_ids": [str(approver.id)]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "PENDING_APPROVAL"

    # Verify audit-log row
    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "Protocol",
                    AuditLog.entity_id == proto.id,
                    AuditLog.action == "PROTOCOL_APPROVAL_SUBMITTED",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].actor_id == test_user.id
    assert str(approver.id) in audits[0].changes.get("requested_user_ids", [])

    # Verify OPEN request row
    reqs = (
        (
            await db_session.execute(
                select(GlpSignoffRequest).where(
                    GlpSignoffRequest.protocol_id == proto.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(reqs) == 1
    assert reqs[0].status == "OPEN"
    assert reqs[0].requested_user_id == approver.id
    assert reqs[0].requested_by_id == test_user.id


@pytest.mark.asyncio
async def test_submit_for_approval_project_approve_perm_eligible(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """User with project APPROVE permission is eligible (no org role)."""
    proto = await _make_protocol(db_session, test_project, test_user.id)
    user = await _make_org_member(db_session, test_org, roles=["MEMBER"])
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.APPROVE.value,
        )
    )
    await db_session.flush()
    resp = await client.post(
        f"/protocols/{proto.id}/submit-for-approval",
        json={"requested_user_ids": [str(user.id)]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
