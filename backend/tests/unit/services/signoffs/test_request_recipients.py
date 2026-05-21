"""Unit tests: _request_recipients excludes run actors from the QAU pool (F-0080)."""

import pytest

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.signoffs.requests import _request_recipients


@pytest.mark.asyncio
async def test_request_recipients_excludes_operator_who_is_org_qau(
    db_session,
    test_project,
    qau_user,
):
    """qau_user is the org QAU *and* the run operator (started_by_id). An
    unassigned QAU request must not fan a notification back to them."""
    run = Run(
        name="R",
        project_id=test_project.id,
        graph={},
        execution_data={},
        started_by_id=qau_user.id,
    )
    db_session.add(run)
    await db_session.flush()
    req = GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN")
    db_session.add(req)
    await db_session.flush()

    recipients = await _request_recipients(db_session, run, req)
    assert qau_user.id not in recipients


@pytest.mark.asyncio
async def test_request_recipients_returns_empty_for_unassigned_non_qau(
    db_session,
    test_project,
):
    """An unassigned (pool) request for STUDY_DIRECTOR has no one to notify —
    _request_recipients must return [] rather than falling through to the QAU
    pool lookup."""
    run = Run(
        name="R",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()
    req = GlpSignoffRequest(
        run_id=run.id,
        role="STUDY_DIRECTOR",
        status="OPEN",
        requested_user_id=None,
    )
    db_session.add(req)
    await db_session.flush()

    recipients = await _request_recipients(db_session, run, req)
    assert recipients == []


@pytest.mark.asyncio
async def test_request_recipients_returns_assignee_for_assigned_request(
    db_session,
    test_project,
    study_director_user,
):
    """An assigned request (non-null requested_user_id) notifies exactly that
    user — no pool lookup, no actor filtering."""
    run = Run(
        name="R",
        project_id=test_project.id,
        graph={},
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()
    req = GlpSignoffRequest(
        run_id=run.id,
        role="STUDY_DIRECTOR",
        status="OPEN",
        requested_user_id=study_director_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    recipients = await _request_recipients(db_session, run, req)
    assert recipients == [study_director_user.id]
