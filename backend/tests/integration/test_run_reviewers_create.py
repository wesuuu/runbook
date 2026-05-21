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
