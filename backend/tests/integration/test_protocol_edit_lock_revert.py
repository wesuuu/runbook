"""Integration tests for the APPROVED edit-lock + auto-revert (F-0066, Task 14).

Editing certain fields on an APPROVED protocol must:
  1. Be authorized (creator, project admin, or any APPROVE-permission holder).
  2. Auto-revert the protocol to DRAFT.
  3. Clear approved_by_id / approved_at (requires_approval is sticky).
  4. Emit exactly one PROTOCOL_APPROVAL_REVERTED audit-log row.

Editing any field on a PENDING_APPROVAL protocol must 409.
"""

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


def _minimal_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "unitOp",
                "data": {
                    "label": "Step 1",
                    "params": {},
                    "paramSchema": {"properties": {}},
                },
            }
        ],
        "edges": [],
    }


async def _make_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    *,
    status: str = "APPROVED",
    requires_approval: bool = True,
) -> Protocol:
    _hex = uuid.uuid4().hex[:6]
    proto = Protocol(
        name=f"P-{_hex}",
        project_id=project.id,
        status=status,
        requires_approval=requires_approval,
        created_by_id=creator_id,
        version_number=1,
        graph=_minimal_graph(),
        approved_by_id=creator_id if status == "APPROVED" else None,
        slug=f"p-{_hex}",
        owner_org_id=project.organization_id,
    )
    db.add(proto)
    await db.flush()
    return proto


async def _make_user_with_project_perm(
    db: AsyncSession,
    test_org: Organization,
    test_project: Project,
    *,
    permission: PermissionLevel = PermissionLevel.EDIT,
    org_role: str = "MEMBER",
    label: str = "user",
) -> tuple[User, dict]:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name=label.title(),
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=user.id,
            organization_id=test_org.id,
            roles=[org_role],
        )
    )
    db.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=permission.value,
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


async def _count_reverted_events(db: AsyncSession, protocol_id: uuid.UUID) -> int:
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "Protocol",
            AuditLog.entity_id == protocol_id,
            AuditLog.action == "PROTOCOL_APPROVAL_REVERTED",
        )
    )
    return len(result.scalars().all())


@pytest.mark.asyncio
async def test_edit_blocked_for_unauthorized_when_approved(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """A user with EDIT but not creator/admin/approver → 403 on rename."""
    proto = await _make_protocol(db_session, test_project, test_user.id)
    # Create a third-party user with EDIT (not project ADMIN, not creator,
    # not APPROVE on the protocol).
    _, edit_headers = await _make_user_with_project_perm(
        db_session,
        test_org,
        test_project,
        permission=PermissionLevel.EDIT,
        label="editor",
    )
    resp = await client.put(
        f"/protocols/{proto.id}",
        json={"name": "Renamed by editor"},
        headers=edit_headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_edit_by_creator_reverts_to_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """Creator renames an APPROVED protocol → 200, status=DRAFT, approval
    bookkeeping cleared, requires_approval still True, exactly one REVERTED
    event written."""
    proto = await _make_protocol(db_session, test_project, test_user.id)
    proto_id = proto.id

    resp = await client.put(
        f"/protocols/{proto_id}",
        json={"name": "Renamed by creator"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    refreshed = (
        await db_session.execute(select(Protocol).where(Protocol.id == proto_id))
    ).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.status == "DRAFT"
    assert refreshed.approved_by_id is None
    assert refreshed.approved_at is None
    assert refreshed.requires_approval is True
    assert refreshed.name == "Renamed by creator"

    assert await _count_reverted_events(db_session, proto_id) == 1


@pytest.mark.asyncio
async def test_edit_by_admin_reverts_to_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """A project admin (not creator) renames APPROVED protocol → reverts."""
    # Make the protocol with a different creator.
    other_creator = User(
        email=f"creator-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Other Creator",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(other_creator)
    await db_session.flush()
    proto = await _make_protocol(db_session, test_project, other_creator.id)
    proto_id = proto.id

    # Build an admin user: project ADMIN permission.
    _, admin_headers = await _make_user_with_project_perm(
        db_session,
        test_org,
        test_project,
        permission=PermissionLevel.ADMIN,
        label="projadmin",
    )

    resp = await client.put(
        f"/protocols/{proto_id}",
        json={"name": "Renamed by admin"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    refreshed = (
        await db_session.execute(select(Protocol).where(Protocol.id == proto_id))
    ).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.status == "DRAFT"
    assert refreshed.approved_by_id is None
    assert await _count_reverted_events(db_session, proto_id) == 1


@pytest.mark.asyncio
async def test_pending_approval_blocks_name_edit(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """A PENDING_APPROVAL protocol → 409 even on a metadata-only rename."""
    proto = await _make_protocol(
        db_session,
        test_project,
        test_user.id,
        status="PENDING_APPROVAL",
    )
    resp = await client.put(
        f"/protocols/{proto.id}",
        json={"name": "Try to rename"},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
