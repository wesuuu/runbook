"""Integration tests for GET /science/protocols/awaiting-my-approval."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.iam import Organization, OrganizationMember, User
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.signoffs import GlpSignoffRequest


async def _make_user(
    db: AsyncSession,
    org: Organization,
    *,
    roles: list[str] = ("MEMBER",),
) -> tuple[User, dict]:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Some User",
        selected_org_id=org.id,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=org.id,
            roles=list(roles),
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


async def _make_pending_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    *,
    name: str = "Pending",
    requested_user_id: uuid.UUID | None = None,
    submitter_id: uuid.UUID | None = None,
) -> Protocol:
    proto = Protocol(
        name=name,
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
                requested_by_id=submitter_id or creator_id,
                status="OPEN",
            )
        )
    await db.flush()
    return proto


@pytest.mark.asyncio
async def test_awaiting_open_request_user_sees_protocol(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """User with an OPEN request sees the pending protocol."""
    requested_user, headers = await _make_user(db_session, test_org)
    proto = await _make_pending_protocol(
        db_session,
        test_project,
        test_user.id,
        name="P-Request",
        requested_user_id=requested_user.id,
        submitter_id=test_user.id,
    )

    resp = await client.get("/science/protocols/awaiting-my-approval", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["protocol_id"] == str(proto.id)
    assert items[0]["name"] == "P-Request"
    assert items[0]["project_id"] == str(test_project.id)
    assert items[0]["organization_id"] == str(test_org.id)
    assert items[0]["submitted_by"]["id"] == str(test_user.id)


@pytest.mark.asyncio
async def test_awaiting_org_approver_sees_pending_in_org(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Org PROTOCOL_APPROVER sees any pending protocol in their org,
    even with no direct request."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = await _make_pending_protocol(
        db_session, test_project, test_user.id, name="P-Org"
    )

    resp = await client.get("/science/protocols/awaiting-my-approval", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["protocol_id"] == str(proto.id)


@pytest.mark.asyncio
async def test_awaiting_dedupes_when_both_paths_match(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """User who is both an approver AND requested only sees the protocol once."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = await _make_pending_protocol(
        db_session,
        test_project,
        test_user.id,
        name="P-Dedupe",
        requested_user_id=approver.id,
        submitter_id=test_user.id,
    )

    resp = await client.get("/science/protocols/awaiting-my-approval", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    assert items[0]["protocol_id"] == str(proto.id)


@pytest.mark.asyncio
async def test_awaiting_empty_when_no_context(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """A plain MEMBER with no requests gets an empty list."""
    plain, headers = await _make_user(db_session, test_org)
    await _make_pending_protocol(db_session, test_project, test_user.id, name="P-Other")
    resp = await client.get("/science/protocols/awaiting-my-approval", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
