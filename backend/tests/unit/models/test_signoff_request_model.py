"""Model-level tests for the run-scoped GlpSignoffRequest extension (F-0080)."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest


async def _make_run(db: AsyncSession, project_id: uuid.UUID) -> Run:
    run = Run(name="R", project_id=project_id, graph={}, execution_data={})
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_run_scoped_request_persists(db_session, test_project):
    run = await _make_run(db_session, test_project.id)
    req = GlpSignoffRequest(
        run_id=run.id, role="QAU", status="OPEN", protocol_id=None,
    )
    db_session.add(req)
    await db_session.flush()
    assert req.id is not None
    assert req.protocol_id is None


@pytest.mark.asyncio
async def test_cancelled_status_accepted(db_session, test_project):
    run = await _make_run(db_session, test_project.id)
    req = GlpSignoffRequest(run_id=run.id, role="QAU", status="CANCELLED")
    db_session.add(req)
    await db_session.flush()
    assert req.status == "CANCELLED"


@pytest.mark.asyncio
async def test_xor_rejects_both_null(db_session):
    req = GlpSignoffRequest(protocol_id=None, run_id=None, status="OPEN")
    db_session.add(req)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_active_run_role_unique(db_session, test_project):
    run = await _make_run(db_session, test_project.id)
    db_session.add(GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN"))
    await db_session.flush()
    db_session.add(GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
