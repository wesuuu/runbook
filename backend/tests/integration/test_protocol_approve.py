"""Integration tests for POST /protocols/{id}/approve."""

import uuid
from datetime import datetime, timezone

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
from app.models.signoffs import GlpSignoff, GlpSignoffRequest


async def _make_pending_protocol(
    db: AsyncSession,
    project: Project,
    creator_id: uuid.UUID,
    requested_user_id: uuid.UUID | None = None,
) -> Protocol:
    import uuid as _uuid
    proto = Protocol(
        name="Pending Protocol",
        project_id=project.id,
        status="PENDING_APPROVAL",
        created_by_id=creator_id,
        requires_approval=True,
        slug=f"pending-protocol-{_uuid.uuid4().hex[:8]}",
        owner_org_id=project.organization_id,
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


async def _make_user(
    db: AsyncSession,
    org: Organization,
    *,
    roles: list[str],
) -> tuple[User, dict]:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=hash_password("test"),
        full_name="Approver Person",
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
    token = create_access_token(
        user.id,
        org_id=org.id,
        subscription_tier=org.subscription_tier,
        email_verified=True,
    )
    return user, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_approve_happy_path_via_project_perm(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """User with project APPROVE perm approves; status flips, event written,
    open requests fulfilled, approved_by/at populated."""
    approver, headers = await _make_user(db_session, test_org, roles=["MEMBER"])
    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=approver.id,
            object_type=ObjectType.PROJECT.value,
            object_id=test_project.id,
            permission_level=PermissionLevel.APPROVE.value,
        )
    )
    await db_session.flush()
    proto = await _make_pending_protocol(
        db_session, test_project, test_user.id, requested_user_id=approver.id
    )

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={"comment": "looks good", "signature_statement": "I attest"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["approved_by_id"] == str(approver.id)
    assert body["approved_at"] is not None

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "Protocol",
                    AuditLog.entity_id == proto.id,
                    AuditLog.action == "PROTOCOL_APPROVAL_APPROVED",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].changes.get("comment") == "looks good"
    assert audits[0].changes.get("has_signature_statement") is True

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
    assert reqs[0].status == "APPROVED"
    assert reqs[0].fulfilled_by_id == approver.id
    assert reqs[0].fulfilled_at is not None


@pytest.mark.asyncio
async def test_approve_via_org_protocol_approver_role(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Org PROTOCOL_APPROVER (with no project perm) can also approve."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = await _make_pending_protocol(
        db_session, test_project, test_user.id, requested_user_id=approver.id
    )

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_approve_blocked_when_glp_signoffs_missing(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """If GLP settings require SD/QAU sign-off but no APPROVED GlpSignoff
    rows exist, /approve returns 400 with MISSING_GLP_SIGNOFFS."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = Protocol(
        name="GLP Pending Protocol",
        project_id=test_project.id,
        status="PENDING_APPROVAL",
        created_by_id=test_user.id,
        requires_approval=True,
        graph={
            "glpSettings": {
                "require_study_director": True,
                "require_qau": True,
            }
        },
        slug="glp-pending-protocol",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "MISSING_GLP_SIGNOFFS"
    assert set(detail["missing"]) == {"STUDY_DIRECTOR", "QAU"}


@pytest.mark.asyncio
async def test_approve_blocked_when_only_one_glp_role_signed(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Partial sign-offs still block — both required roles must be signed."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = Protocol(
        name="GLP Partial",
        project_id=test_project.id,
        status="PENDING_APPROVAL",
        created_by_id=test_user.id,
        requires_approval=True,
        graph={
            "glpSettings": {
                "require_study_director": True,
                "require_qau": True,
            }
        },
        slug="glp-partial",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    db_session.add(
        GlpSignoff(
            protocol_id=proto.id,
            role="STUDY_DIRECTOR",
            action="APPROVED",
            signer_id=approver.id,
            signed_at=datetime.now(timezone.utc),
            signature_image_path="signatures/test.png",
            attestation="I attest as Study Director.",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "MISSING_GLP_SIGNOFFS"
    assert detail["missing"] == ["QAU"]


@pytest.mark.asyncio
async def test_approve_succeeds_when_all_glp_signoffs_present(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """With both required roles signed (APPROVED, not invalidated), /approve
    succeeds and the protocol transitions to APPROVED."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = Protocol(
        name="GLP Full",
        project_id=test_project.id,
        status="PENDING_APPROVAL",
        created_by_id=test_user.id,
        requires_approval=True,
        graph={
            "glpSettings": {
                "require_study_director": True,
                "require_qau": True,
            }
        },
        slug="glp-full",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    for role, statement in (
        ("STUDY_DIRECTOR", "SD attest"),
        ("QAU", "QAU attest"),
    ):
        db_session.add(
            GlpSignoff(
                protocol_id=proto.id,
                role=role,
                action="APPROVED",
                signer_id=approver.id,
                signed_at=datetime.now(timezone.utc),
                signature_image_path="signatures/test.png",
                attestation=statement,
            )
        )
    await db_session.flush()

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_approve_ignores_invalidated_glp_signoffs(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    test_org: Organization,
    test_project: Project,
):
    """Invalidated GlpSignoff rows must not satisfy the gate."""
    approver, headers = await _make_user(
        db_session, test_org, roles=["MEMBER", "PROTOCOL_APPROVER"]
    )
    proto = Protocol(
        name="GLP Invalidated",
        project_id=test_project.id,
        status="PENDING_APPROVAL",
        created_by_id=test_user.id,
        requires_approval=True,
        graph={
            "glpSettings": {
                "require_study_director": True,
                "require_qau": False,
            }
        },
        slug="glp-invalidated",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    db_session.add(
        GlpSignoff(
            protocol_id=proto.id,
            role="STUDY_DIRECTOR",
            action="APPROVED",
            signer_id=approver.id,
            signed_at=datetime.now(timezone.utc),
            signature_image_path="signatures/test.png",
            attestation="SD attest (revoked)",
            invalidated_at=datetime.now(timezone.utc),
            invalidated_reason="Revoked for re-review.",
        )
    )
    await db_session.flush()

    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error"] == "MISSING_GLP_SIGNOFFS"


@pytest.mark.asyncio
async def test_approve_blocked_when_not_pending(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """If protocol is not PENDING_APPROVAL → 400."""
    proto = Protocol(
        name="Draft",
        project_id=test_project.id,
        status="DRAFT",
        created_by_id=test_user.id,
        requires_approval=True,
        slug="draft",
        owner_org_id=test_project.organization_id,
    )
    db_session.add(proto)
    await db_session.flush()
    resp = await client.post(
        f"/protocols/{proto.id}/approve",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
