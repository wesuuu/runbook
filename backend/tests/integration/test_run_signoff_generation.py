"""Integration: sign-off requests fire on every completion path (F-0080)."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification
from app.models.runs import Run
from app.models.signoffs import GlpSignoff, GlpSignoffRequest


async def _open_count(db: AsyncSession, run_id) -> int:
    rows = await db.execute(
        select(GlpSignoffRequest).where(
            GlpSignoffRequest.run_id == run_id,
            GlpSignoffRequest.status == "OPEN",
        )
    )
    return len(list(rows.scalars().all()))


async def _add_operator_signoff(db: AsyncSession, run: Run, signer_id) -> None:
    """Create an OPERATOR APPROVED sign-off so complete_run passes assert_run_can_close."""
    signoff = GlpSignoff(
        run_id=run.id,
        role="OPERATOR",
        action="APPROVED",
        signer_id=signer_id,
        attestation="I performed this run accurately.",
        signature_image_path="signatures/test/operator.png",
        signed_at=datetime.now(timezone.utc),
    )
    db.add(signoff)
    await db.flush()


@pytest.mark.asyncio
async def test_complete_endpoint_generates_requests(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
    qau_user,
):
    glp_run_active.study_director_id = study_director_user.id
    glp_run_active.qau_reviewer_id = qau_user.id
    await db_session.flush()
    await _add_operator_signoff(db_session, glp_run_active, study_director_user.id)
    resp = await client.post(
        f"/runs/{glp_run_active.id}/complete",
        json={"outcome": "COMPLETED_NORMAL", "outcome_notes": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert await _open_count(db_session, glp_run_active.id) == 2


@pytest.mark.asyncio
async def test_complete_blocked_when_sd_unassigned(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
):
    glp_run_active.study_director_id = None
    await db_session.flush()
    await _add_operator_signoff(db_session, glp_run_active, study_director_user.id)
    resp = await client.post(
        f"/runs/{glp_run_active.id}/complete",
        json={"outcome": "COMPLETED_NORMAL", "outcome_notes": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "RUN_SD_UNASSIGNED"


@pytest.mark.asyncio
async def test_reopen_cancels_then_recomplete_reissues(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
    qau_user,
):
    glp_run_active.study_director_id = study_director_user.id
    glp_run_active.qau_reviewer_id = qau_user.id
    await db_session.flush()
    await _add_operator_signoff(db_session, glp_run_active, study_director_user.id)
    await client.post(
        f"/runs/{glp_run_active.id}/complete",
        json={"outcome": "COMPLETED_NORMAL", "outcome_notes": ""},
        headers=auth_headers,
    )
    await client.post(
        f"/runs/{glp_run_active.id}/reopen",
        json={"reason": "fix a value"},
        headers=auth_headers,
    )
    assert await _open_count(db_session, glp_run_active.id) == 0
    # After reopen the run is EDITED; add another operator signoff so
    # complete_run passes assert_run_can_close on the second attempt.
    run_row = await db_session.get(Run, glp_run_active.id)
    await _add_operator_signoff(db_session, run_row, study_director_user.id)
    await client.post(
        f"/runs/{glp_run_active.id}/complete",
        json={"outcome": "COMPLETED_NORMAL", "outcome_notes": ""},
        headers=auth_headers,
    )
    assert await _open_count(db_session, glp_run_active.id) == 2


@pytest.mark.asyncio
async def test_patch_state_completion_generates_requests(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
    qau_user,
):
    """PATCH /runs/{id}/state COMPLETED also fires on_run_completed."""
    glp_run_active.study_director_id = study_director_user.id
    glp_run_active.qau_reviewer_id = qau_user.id
    await db_session.flush()
    resp = await client.patch(
        f"/runs/{glp_run_active.id}/state",
        json={"state": "COMPLETED"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert await _open_count(db_session, glp_run_active.id) == 2


@pytest.mark.asyncio
async def test_put_run_completion_generates_requests(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
    qau_user,
):
    """PUT /runs/{id} with a COMPLETED status also fires on_run_completed."""
    glp_run_active.study_director_id = study_director_user.id
    glp_run_active.qau_reviewer_id = qau_user.id
    # Mark all unit ops completed so update_run's step-completion gate passes.
    unit_op_ids = ["u0", "u1", "u2"]
    glp_run_active.execution_data = {
        uid: {"status": "completed"} for uid in unit_op_ids
    }
    await db_session.flush()
    resp = await client.put(
        f"/runs/{glp_run_active.id}",
        json={"status": "COMPLETED", "execution_data": {
            uid: {"status": "completed"} for uid in unit_op_ids
        }},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert await _open_count(db_session, glp_run_active.id) == 2


@pytest.mark.asyncio
async def test_complete_and_reopen_create_notification_rows(
    client: AsyncClient,
    auth_headers,
    db_session,
    glp_run_active,
    study_director_user,
    qau_user,
):
    """Completing a GLP run fans out RUN_SIGNOFF_REQUESTED Notification rows;
    reopening fans out RUN_SIGNOFF_CANCELLED rows for the previously-assigned
    reviewers."""
    glp_run_active.study_director_id = study_director_user.id
    glp_run_active.qau_reviewer_id = qau_user.id
    await db_session.flush()
    await _add_operator_signoff(db_session, glp_run_active, study_director_user.id)

    # ── Complete the run ────────────────────────────────────────────────
    resp = await client.post(
        f"/runs/{glp_run_active.id}/complete",
        json={"outcome": "COMPLETED_NORMAL", "outcome_notes": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Both assigned reviewers should each get a RUN_SIGNOFF_REQUESTED notification.
    result = await db_session.execute(
        select(Notification).where(
            Notification.event_type == "RUN_SIGNOFF_REQUESTED",
            Notification.entity_id == glp_run_active.id,
        )
    )
    requested_notifs = list(result.scalars().all())
    recipient_ids = {n.user_id for n in requested_notifs}
    assert study_director_user.id in recipient_ids, (
        "study_director_user should receive a RUN_SIGNOFF_REQUESTED notification"
    )
    assert qau_user.id in recipient_ids, (
        "qau_user should receive a RUN_SIGNOFF_REQUESTED notification"
    )

    # ── Reopen the run ──────────────────────────────────────────────────
    resp = await client.post(
        f"/runs/{glp_run_active.id}/reopen",
        json={"reason": "fix a value"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # The assigned reviewers should each get a RUN_SIGNOFF_CANCELLED notification.
    result = await db_session.execute(
        select(Notification).where(
            Notification.event_type == "RUN_SIGNOFF_CANCELLED",
            Notification.entity_id == glp_run_active.id,
        )
    )
    cancelled_notifs = list(result.scalars().all())
    cancelled_recipient_ids = {n.user_id for n in cancelled_notifs}
    # study_director_user had an assigned request, so must be notified.
    assert study_director_user.id in cancelled_recipient_ids, (
        "study_director_user should receive a RUN_SIGNOFF_CANCELLED notification"
    )
    # qau_user also had an assigned request, so must also be notified.
    assert qau_user.id in cancelled_recipient_ids, (
        "qau_user should receive a RUN_SIGNOFF_CANCELLED notification"
    )
