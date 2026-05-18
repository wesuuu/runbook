"""Integration tests for POST /science/protocols/{id}/reject."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.execution import AuditLog
from app.models.iam import Organization, OrganizationMember, User
from app.models.science import GlpSignoffRequest, Project, Protocol


async def _make_pending_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    requested_user_id: uuid.UUID | None = None,
) -> Protocol:
    proto = Protocol(
        name="Pending Protocol",
        project_id=project.id,
        status="PENDING_APPROVAL",
        created_by_id=creator_id,
        requires_approval=True,
    )
    db.add(proto)
    await db.flush()
    if requested_user_id is not None:
        db.add(
            GlpSignoffRequest(
                protocol_id=proto.id,
                requested_user_id=requested_user_id,
                requested_by_id=creator_id,
                status="OPEN",
            )
        )
        await db.flush()
    return proto


async def _make_org_approver(db: AsyncSession, org: Organization) -> tuple[User, dict]:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
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
            roles=["MEMBER", "PROTOCOL_APPROVER"],
        )
    )
    await db.flush()
    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=True,
    )
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_reject_requires_comment(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Empty/missing comment → 422 from Pydantic min_length validation."""
    approver, headers = await _make_org_approver(db_session, test_org)
    proto = await _make_pending_protocol(
        db_session, test_project, test_user.id, requested_user_id=approver.id
    )
    # missing comment
    resp = await client.post(
        f"/science/protocols/{proto.id}/reject",
        json={},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    # empty comment
    resp = await client.post(
        f"/science/protocols/{proto.id}/reject",
        json={"comment": ""},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_reject_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Reject flips status to DRAFT, writes REJECTED event with comment,
    and fulfills open approval requests."""
    approver, headers = await _make_org_approver(db_session, test_org)
    proto = await _make_pending_protocol(
        db_session, test_project, test_user.id, requested_user_id=approver.id
    )
    resp = await client.post(
        f"/science/protocols/{proto.id}/reject",
        json={"comment": "needs more detail in step 3"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "DRAFT"

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "Protocol",
                    AuditLog.entity_id == proto.id,
                    AuditLog.action == "PROTOCOL_APPROVAL_REJECTED",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].changes.get("comment") == "needs more detail in step 3"

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
    assert reqs[0].status == "REJECTED"
    assert reqs[0].fulfilled_by_id == approver.id
