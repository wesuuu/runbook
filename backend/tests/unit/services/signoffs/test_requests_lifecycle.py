"""Cancellation, fulfillment, and reopen-cycle tests (F-0080)."""

import pytest
from sqlalchemy import select

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.signoffs.requests import (
    cancel_signoff_requests,
    fulfill_signoff_request,
    generate_signoff_requests,
)

_GLP = {"glpSettings": {"require_study_director": True, "require_qau": True}}


async def _run(db, project_id, sd, qau) -> Run:
    run = Run(
        name="R", project_id=project_id, graph=_GLP, execution_data={},
        status="COMPLETED", study_director_id=sd, qau_reviewer_id=qau,
    )
    db.add(run)
    await db.flush()
    return run


async def _statuses(db, run_id) -> list[str]:
    rows = await db.execute(
        select(GlpSignoffRequest.status).where(GlpSignoffRequest.run_id == run_id)
    )
    return sorted(rows.scalars().all())


@pytest.mark.asyncio
async def test_cancel_flips_open_to_cancelled(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(db_session, test_project.id, study_director_user.id, qau_user.id)
    await generate_signoff_requests(db_session, run)
    cancelled = await cancel_signoff_requests(db_session, run)
    assert cancelled == 2
    assert await _statuses(db_session, run.id) == ["CANCELLED", "CANCELLED"]


@pytest.mark.asyncio
async def test_fulfill_flips_matching_open_request(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(db_session, test_project.id, study_director_user.id, qau_user.id)
    await generate_signoff_requests(db_session, run)
    n = await fulfill_signoff_request(
        db_session, run_id=run.id, role="QAU", status="APPROVED"
    )
    assert n == 1
    assert await _statuses(db_session, run.id) == ["APPROVED", "OPEN"]


@pytest.mark.asyncio
async def test_fulfill_is_noop_without_open_request(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(db_session, test_project.id, study_director_user.id, qau_user.id)
    n = await fulfill_signoff_request(
        db_session, run_id=run.id, role="QAU", status="APPROVED"
    )
    assert n == 0


@pytest.mark.asyncio
async def test_reopen_recomplete_cycle_keeps_one_open_per_role(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(db_session, test_project.id, study_director_user.id, qau_user.id)
    await generate_signoff_requests(db_session, run)
    await cancel_signoff_requests(db_session, run)        # reopen
    await generate_signoff_requests(db_session, run)      # re-complete
    open_rows = await db_session.execute(
        select(GlpSignoffRequest).where(
            GlpSignoffRequest.run_id == run.id,
            GlpSignoffRequest.status == "OPEN",
        )
    )
    open_reqs = list(open_rows.scalars().all())
    assert len(open_reqs) == 2
    assert {r.role for r in open_reqs} == {"STUDY_DIRECTOR", "QAU"}
