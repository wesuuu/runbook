"""Integration: PUT /runs/{id}/reviewers (F-0080)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_update_reviewers_ok(
    client: AsyncClient, auth_headers, glp_run_planned,
    study_director_user, qau_user,
):
    resp = await client.put(
        f"/runs/{glp_run_planned.id}/reviewers",
        json={
            "study_director_id": str(study_director_user.id),
            "qau_reviewer_id": str(qau_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["qau_reviewer_id"] == str(qau_user.id)


@pytest.mark.asyncio
async def test_non_qau_reviewer_rejected(
    client: AsyncClient, auth_headers, glp_run_planned, operator_user,
):
    resp = await client.put(
        f"/runs/{glp_run_planned.id}/reviewers",
        json={"qau_reviewer_id": str(operator_user.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "REVIEWER_NOT_QUALIFIED"


@pytest.mark.asyncio
async def test_reviewers_locked_when_completed(
    client: AsyncClient, auth_headers, glp_run_completed, qau_user,
):
    resp = await client.put(
        f"/runs/{glp_run_completed.id}/reviewers",
        json={"qau_reviewer_id": str(qau_user.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "RUN_REVIEWERS_LOCKED"
