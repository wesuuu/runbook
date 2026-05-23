"""Integration: GET /signoff-requests (F-0080)."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest


async def _run(db, project_id) -> Run:
    run = Run(
        name="Queued Run",
        slug=f"run-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        graph={},
        execution_data={},
    )
    db.add(run)
    await db.flush()
    return run


@pytest.mark.asyncio
async def test_queue_returns_assigned_run_request(
    client: AsyncClient,
    db_session,
    test_project,
    qau_user,
    glp_org,
):
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(
            run_id=run.id,
            role="QAU",
            status="OPEN",
            requested_user_id=qau_user.id,
        )
    )
    await db_session.flush()

    from app.core.security import create_access_token

    token = create_access_token(
        qau_user.id,
        org_id=glp_org.id,
        subscription_tier=glp_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get("/signoff-requests", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert any(
        i["type"] == "run" and i["target_id"] == str(run.id) for i in body
    )


@pytest.mark.asyncio
async def test_queue_excludes_other_users_requests(
    client: AsyncClient,
    auth_headers,
    db_session,
    test_project,
    qau_user,
):
    run = await _run(db_session, test_project.id)
    db_session.add(
        GlpSignoffRequest(
            run_id=run.id,
            role="QAU",
            status="OPEN",
            requested_user_id=qau_user.id,
        )
    )
    await db_session.flush()
    # test_user (auth_headers) is not the assignee and not a QAU.
    resp = await client.get("/signoff-requests", headers=auth_headers)
    assert resp.status_code == 200
    assert all(i["target_id"] != str(run.id) for i in resp.json())
