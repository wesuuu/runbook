"""Unit tests for run sign-off request generation (F-0080)."""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.signoffs.requests import (
    assert_run_completable,
    generate_signoff_requests,
)


def _glp(require_sd=True, require_qau=True) -> dict:
    return {
        "glpSettings": {
            "require_study_director": require_sd,
            "require_qau": require_qau,
        }
    }


async def _run(db, project_id, *, graph, sd=None, qau=None) -> Run:
    run = Run(
        name="R", slug=f"run-{uuid.uuid4().hex[:12]}",
        project_id=project_id, graph=graph, execution_data={},
        status="COMPLETED", study_director_id=sd, qau_reviewer_id=qau,
    )
    db.add(run)
    await db.flush()
    return run


async def _open_requests(db, run_id) -> list[GlpSignoffRequest]:
    rows = await db.execute(
        select(GlpSignoffRequest).where(
            GlpSignoffRequest.run_id == run_id,
            GlpSignoffRequest.status == "OPEN",
        )
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_generates_one_request_per_required_role(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(
        db_session, test_project.id, graph=_glp(),
        sd=study_director_user.id, qau=qau_user.id,
    )
    count = await generate_signoff_requests(db_session, run)
    reqs = await _open_requests(db_session, run.id)
    roles = {r.role for r in reqs}
    assert count == 2
    assert roles == {"STUDY_DIRECTOR", "QAU"}


@pytest.mark.asyncio
async def test_require_qau_false_skips_qau(
    db_session, test_project, study_director_user,
):
    run = await _run(
        db_session, test_project.id, graph=_glp(require_qau=False),
        sd=study_director_user.id,
    )
    await generate_signoff_requests(db_session, run)
    reqs = await _open_requests(db_session, run.id)
    assert {r.role for r in reqs} == {"STUDY_DIRECTOR"}


@pytest.mark.asyncio
async def test_protocol_less_run_generates_nothing(db_session, test_project):
    run = await _run(db_session, test_project.id, graph={})
    count = await generate_signoff_requests(db_session, run)
    assert count == 0


@pytest.mark.asyncio
async def test_null_qau_creates_unassigned_request(
    db_session, test_project, study_director_user,
):
    run = await _run(
        db_session, test_project.id, graph=_glp(),
        sd=study_director_user.id, qau=None,
    )
    await generate_signoff_requests(db_session, run)
    reqs = await _open_requests(db_session, run.id)
    qau_req = next(r for r in reqs if r.role == "QAU")
    assert qau_req.requested_user_id is None


@pytest.mark.asyncio
async def test_generation_is_idempotent(
    db_session, test_project, study_director_user, qau_user,
):
    run = await _run(
        db_session, test_project.id, graph=_glp(),
        sd=study_director_user.id, qau=qau_user.id,
    )
    await generate_signoff_requests(db_session, run)
    second = await generate_signoff_requests(db_session, run)
    reqs = await _open_requests(db_session, run.id)
    assert second == 0
    assert len(reqs) == 2


@pytest.mark.asyncio
async def test_assert_run_completable_blocks_unassigned_sd(
    db_session, test_project,
):
    run = await _run(db_session, test_project.id, graph=_glp(), sd=None)
    with pytest.raises(HTTPException) as exc:
        await assert_run_completable(db_session, run)
    assert exc.value.detail["error"] == "RUN_SD_UNASSIGNED"


@pytest.mark.asyncio
async def test_assert_run_completable_allows_unassigned_qau(
    db_session, test_project, study_director_user,
):
    run = await _run(
        db_session, test_project.id, graph=_glp(),
        sd=study_director_user.id, qau=None,
    )
    await assert_run_completable(db_session, run)  # must not raise
