"""Integration: run creation persists GLP reviewer columns (F-0080)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_run_persists_reviewers(
    client: AsyncClient, auth_headers, test_project,
    study_director_user, qau_user,
):
    resp = await client.post(
        "/runs",
        json={
            "name": "Reviewed Run",
            "project_id": str(test_project.id),
            "study_director_id": str(study_director_user.id),
            "qau_reviewer_id": str(qau_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["study_director_id"] == str(study_director_user.id)
    assert body["qau_reviewer_id"] == str(qau_user.id)


@pytest.mark.asyncio
async def test_create_run_rejects_same_sd_and_qau(
    client: AsyncClient, auth_headers, test_project, qau_user,
):
    """§58.35: a run cannot be created with one person as both reviewers."""
    resp = await client.post(
        "/runs",
        json={
            "name": "Conflicted Run",
            "project_id": str(test_project.id),
            "study_director_id": str(qau_user.id),
            "qau_reviewer_id": str(qau_user.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "QAU_NOT_INDEPENDENT"
    assert detail["conflict_role"] == "STUDY_DIRECTOR"
