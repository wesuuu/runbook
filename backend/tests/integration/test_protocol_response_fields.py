"""Integration tests for the F-0066 ProtocolResponse / RunResponse fields."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run
from app.models.signoffs import GlpSignoff


@pytest.mark.asyncio
async def test_protocol_response_includes_approval_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """GET /protocols/{id} surfaces requires_approval, created_by_id,
    approved_by_id, approved_at, latest_signature_statement, and
    latest_approval_comment."""
    proto = Protocol(
        name="Approved Protocol",
        project_id=test_project.id,
        status="APPROVED",
        requires_approval=True,
        created_by_id=test_user.id,
        approved_by_id=test_user.id,
        approved_at=datetime.now(timezone.utc),
    )
    db_session.add(proto)
    await db_session.flush()
    db_session.add(
        GlpSignoff(
            protocol_id=proto.id,
            signer_id=test_user.id,
            role="STUDY_DIRECTOR",
            action="APPROVED",
            attestation="I approve in compliance with SOP.",
            signed_at=datetime.now(timezone.utc),
            signature_image_path="fixture/sig.png",
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{proto.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requires_approval"] is True
    assert body["created_by_id"] == str(test_user.id)
    assert body["approved_by_id"] == str(test_user.id)
    assert body["approved_at"] is not None
    # latest_approval_comment has no equivalent in GlpSignoff (Task 27).
    assert body["latest_approval_comment"] is None
    assert body["latest_signature_statement"] == "I approve in compliance with SOP."


@pytest.mark.asyncio
async def test_run_response_includes_is_strict(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    test_user: User,
    test_project: Project,
):
    """Listing runs surfaces is_strict (default False, propagates True)."""
    run = Run(
        name="Strict Run",
        project_id=test_project.id,
        status="PLANNED",
        created_by_id=test_user.id,
        is_strict=True,
    )
    db_session.add(run)
    await db_session.flush()

    resp = await client.get(
        f"/science/projects/{test_project.id}/runs",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    matched = [r for r in items if r["id"] == str(run.id)]
    assert len(matched) == 1
    assert matched[0]["is_strict"] is True
