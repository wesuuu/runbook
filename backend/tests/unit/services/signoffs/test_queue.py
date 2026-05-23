"""Unit tests for the unified review queue (F-0080)."""

import uuid

import pytest

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.signoffs.queue import list_review_queue_for_user


async def _run(db, project_id) -> Run:
    run = Run(
        name="R",
        slug=f"run-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        graph={},
        execution_data={},
    )
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_assigned_run_request_appears(db_session, test_project, qau_user):
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(
            run_id=run.id, role="QAU", status="OPEN",
            requested_user_id=qau_user.id,
        )
    )
    await db_session.flush()
    items = await list_review_queue_for_user(db_session, qau_user.id)
    run_items = [i for i in items if i["type"] == "run"]
    assert len(run_items) == 1
    assert run_items[0]["target_id"] == run.id
    assert run_items[0]["assigned"] is True


@pytest.mark.asyncio
async def test_unassigned_qau_request_visible_to_org_qau(
    db_session, test_project, qau_user,
):
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN")
    )
    await db_session.flush()
    items = await list_review_queue_for_user(db_session, qau_user.id)
    run_items = [i for i in items if i["type"] == "run"]
    assert len(run_items) == 1
    assert run_items[0]["assigned"] is False


@pytest.mark.asyncio
async def test_unassigned_qau_request_hidden_from_non_qau(
    db_session, test_project, operator_user,
):
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN")
    )
    await db_session.flush()
    items = await list_review_queue_for_user(db_session, operator_user.id)
    assert [i for i in items if i["type"] == "run"] == []


@pytest.mark.asyncio
async def test_other_org_qau_request_not_leaked(
    db_session, second_org, second_user, test_project,
):
    """A QAU request in org A must not appear for a QAU in org B."""
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(run_id=run.id, role="QAU", status="OPEN")
    )
    await db_session.flush()
    items = await list_review_queue_for_user(db_session, second_user.id)
    assert [i for i in items if i["type"] == "run"] == []
