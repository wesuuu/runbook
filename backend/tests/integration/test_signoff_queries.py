"""Integration tests for services/signoffs/queries.py."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AuditLog
from app.models.runs import Run
from app.models.signoffs import GlpSignoff
from app.services.signoffs.queries import (
    get_signoff_by_role,
    invalidate_active_signoffs,
    list_active_signoffs,
)


@pytest_asyncio.fixture
async def test_run(db_session: AsyncSession, test_project):
    """A minimal PLANNED run for signoff query tests."""
    run = Run(
        name="Signoff Query Test Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


async def test_list_active_signoffs_returns_only_non_invalidated(
    db_session: AsyncSession,
    test_run: Run,
    test_user,
):
    # Active sign-off
    active = GlpSignoff(
        run_id=test_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="x",
        signature_image_path="p.png",
        signed_at=datetime.now(timezone.utc),
    )
    # Invalidated sign-off (different role to avoid unique partial index conflict)
    invalid = GlpSignoff(
        run_id=test_run.id,
        role="QAU",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="x",
        signature_image_path="p.png",
        signed_at=datetime.now(timezone.utc),
        invalidated_at=datetime.now(timezone.utc),
        invalidated_reason="reopened",
    )
    db_session.add_all([active, invalid])
    await db_session.flush()

    rows = await list_active_signoffs(db_session, "run", test_run.id)
    assert len(rows) == 1
    assert rows[0].role == "OPERATOR"


async def test_invalidate_active_signoffs_marks_all(
    db_session: AsyncSession,
    test_run: Run,
    test_user,
):
    for role in ("OPERATOR", "QAU"):
        db_session.add(
            GlpSignoff(
                run_id=test_run.id,
                role=role,
                action="APPROVED",
                signer_id=test_user.id,
                attestation="x",
                signature_image_path="p.png",
                signed_at=datetime.now(timezone.utc),
            )
        )
    await db_session.flush()

    count = await invalidate_active_signoffs(
        db_session,
        test_run.id,
        reason="probe drift",
        user_id=test_user.id,
    )
    assert count == 2
    rows = await list_active_signoffs(db_session, "run", test_run.id)
    assert rows == []


async def test_invalidate_active_signoffs_with_audit_event_id_sets_supersession_fk(
    db_session: AsyncSession,
    test_run: Run,
    test_user,
):
    """Grilling decision #15: reopen-supersession sets superseded_by_reopen_audit_event_id FK."""
    # Create an active OPERATOR sign-off
    signoff = GlpSignoff(
        run_id=test_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="x",
        signature_image_path="p.png",
        signed_at=datetime.now(timezone.utc),
    )
    db_session.add(signoff)

    # Create an audit log entry representing the reopen event
    audit = AuditLog(
        entity_type="Run",
        entity_id=test_run.id,
        actor_id=test_user.id,
        action="RUN_REOPENED",
        changes={},
    )
    db_session.add(audit)
    await db_session.flush()

    count = await invalidate_active_signoffs(
        db_session,
        test_run.id,
        reason="run reopened",
        user_id=test_user.id,
        superseded_by_reopen_audit_event_id=audit.id,
    )
    assert count == 1

    # Reload and verify the FK was set
    await db_session.refresh(signoff)
    assert signoff.invalidated_at is not None
    assert signoff.superseded_by_reopen_audit_event_id == audit.id


async def test_invalidate_active_signoffs_without_audit_event_id_leaves_fk_null(
    db_session: AsyncSession,
    test_run: Run,
    test_user,
):
    """Edit-invalidation (no audit event id) leaves superseded_by_reopen_audit_event_id NULL."""
    signoff = GlpSignoff(
        run_id=test_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="x",
        signature_image_path="p.png",
        signed_at=datetime.now(timezone.utc),
    )
    db_session.add(signoff)
    await db_session.flush()

    count = await invalidate_active_signoffs(
        db_session,
        test_run.id,
        reason="RUN_EDITED",
        user_id=test_user.id,
    )
    assert count == 1

    await db_session.refresh(signoff)
    assert signoff.invalidated_at is not None
    assert signoff.superseded_by_reopen_audit_event_id is None


async def test_get_signoff_by_role_returns_active_row(
    db_session: AsyncSession,
    test_run: Run,
    test_user,
):
    """get_signoff_by_role returns the active signoff for a given role, or None."""
    signoff = GlpSignoff(
        run_id=test_run.id,
        role="STUDY_DIRECTOR",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="x",
        signature_image_path="p.png",
        signed_at=datetime.now(timezone.utc),
    )
    db_session.add(signoff)
    await db_session.flush()

    found = await get_signoff_by_role(db_session, "run", test_run.id, "STUDY_DIRECTOR")
    assert found is not None
    assert found.id == signoff.id

    missing = await get_signoff_by_role(db_session, "run", test_run.id, "QAU")
    assert missing is None
