"""Tests for _build_approval_context helper used by SOP/batch PDF endpoints."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.protocol_pdfs import _build_approval_context
from app.core.security import hash_password
from app.models.iam import Organization, OrganizationMember, User
from app.models.science import Project, Protocol, ProtocolApprovalEvent


async def _make_user(db: AsyncSession, *, full_name: str, email: str, **kwargs) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("test"),
        full_name=full_name,
        email_verified=True,
        **kwargs,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_approval_context_for_approved_protocol_with_signature(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
):
    approver = await _make_user(
        db_session,
        full_name="Approver Bob",
        email="approver-bob@test.com",
        signature_full_path="system/sigs/approver-full.png",
    )
    db_session.add(
        OrganizationMember(
            user_id=approver.id,
            organization_id=test_org.id,
            roles=["MEMBER", "PROTOCOL_APPROVER"],
        )
    )

    proto = Protocol(
        name="Approved Proto",
        project_id=test_project.id,
        status="APPROVED",
        version_number=2,
        requires_approval=True,
        approved_by_id=approver.id,
        approved_at=datetime.now(timezone.utc),
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()

    db_session.add(
        ProtocolApprovalEvent(
            protocol_id=proto.id,
            actor_id=approver.id,
            action="APPROVED",
            comment="lgtm",
            signature_statement="I have reviewed and approved",
        )
    )
    await db_session.flush()

    ctx = await _build_approval_context(db_session, proto, test_project)
    assert ctx["approval"] is not None
    assert ctx["approval"]["approver_name"] == "Approver Bob"
    assert ctx["approval"]["approver_email"] == "approver-bob@test.com"
    assert ctx["approval"]["protocol_version"] == 2
    assert ctx["approval"]["signature_image_path"] is not None
    assert ctx["approval"]["signature_image_path"].endswith(
        "system/sigs/approver-full.png"
    )
    assert ctx["approval"]["signature_statement"] == "I have reviewed and approved"
    assert len(ctx["approval_history"]) == 1
    assert ctx["approval_history"][0]["action"] == "APPROVED"


@pytest.mark.asyncio
async def test_approval_context_for_unapproved_required(
    db_session: AsyncSession,
    test_org: Organization,
    test_user: User,
):
    project = Project(
        name="Strict Project",
        organization_id=test_org.id,
        owner_type="USER",
        owner_id=test_user.id,
        settings={"require_protocol_approval": True},
    )
    db_session.add(project)
    await db_session.flush()

    proto = Protocol(
        name="Draft Proto",
        project_id=project.id,
        status="DRAFT",
        requires_approval=True,
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()

    ctx = await _build_approval_context(db_session, proto, project)
    assert ctx["approval"] is None
    assert ctx["unapproved_warning"] is True


@pytest.mark.asyncio
async def test_approval_context_when_setting_off(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
):
    proto = Protocol(
        name="No Setting Proto",
        project_id=test_project.id,
        status="DRAFT",
        requires_approval=True,
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()

    # test_project has no require_protocol_approval setting
    ctx = await _build_approval_context(db_session, proto, test_project)
    assert ctx["unapproved_warning"] is False


@pytest.mark.asyncio
async def test_approval_history_newest_first(
    db_session: AsyncSession,
    test_org: Organization,
    test_project: Project,
    test_user: User,
):
    approver = await _make_user(
        db_session,
        full_name="Hist Approver",
        email="hist-approver@test.com",
    )

    proto = Protocol(
        name="Hist Proto",
        project_id=test_project.id,
        status="APPROVED",
        requires_approval=True,
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    e1 = ProtocolApprovalEvent(
        protocol_id=proto.id,
        actor_id=test_user.id,
        action="SUBMITTED",
        created_at=now - timedelta(hours=2),
    )
    e2 = ProtocolApprovalEvent(
        protocol_id=proto.id,
        actor_id=approver.id,
        action="APPROVED",
        created_at=now - timedelta(hours=1),
    )
    e3 = ProtocolApprovalEvent(
        protocol_id=proto.id,
        actor_id=approver.id,
        action="REVERTED",
        created_at=now,
    )
    db_session.add_all([e1, e2, e3])
    await db_session.flush()

    ctx = await _build_approval_context(db_session, proto, test_project)
    actions = [e["action"] for e in ctx["approval_history"]]
    assert actions == ["REVERTED", "APPROVED", "SUBMITTED"]


@pytest.mark.asyncio
async def test_actor_deleted_falls_back(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
):
    proto = Protocol(
        name="Deleted Actor Proto",
        project_id=test_project.id,
        status="DRAFT",
        requires_approval=False,
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()

    db_session.add(
        ProtocolApprovalEvent(
            protocol_id=proto.id,
            actor_id=None,  # simulates SET NULL on user deletion
            action="SUBMITTED",
        )
    )
    await db_session.flush()

    ctx = await _build_approval_context(db_session, proto, test_project)
    assert len(ctx["approval_history"]) == 1
    assert ctx["approval_history"][0]["actor_name"] == "(deleted user)"
