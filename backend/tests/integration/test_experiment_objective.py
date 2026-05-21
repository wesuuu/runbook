"""F-0093 — objective fields + derived lifecycle_status on experiment CRUD."""

import pytest


@pytest.mark.asyncio
async def test_create_persists_objective_and_creator(
    client, auth_headers, test_project
):
    resp = await client.post(
        "/experiments",
        headers=auth_headers,
        json={
            "name": "Glucose sweep",
            "project_id": str(test_project.id),
            "objective": "Does raising glucose increase titer?",
            "success_criteria": ["day-12 titer up >=10%"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["objective"] == "Does raising glucose increase titer?"
    assert body["success_criteria"] == ["day-12 titer up >=10%"]
    assert body["created_by_id"] is not None
    assert body["lifecycle_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_update_objective_and_reject_status_write(
    client, auth_headers, test_project
):
    created = (
        await client.post(
            "/experiments",
            headers=auth_headers,
            json={"name": "Exp A", "project_id": str(test_project.id)},
        )
    ).json()

    ok = await client.put(
        f"/experiments/{created['id']}",
        headers=auth_headers,
        json={"objective": "Revised question", "success_criteria": ["c1", "c2"]},
    )
    assert ok.status_code == 200
    assert ok.json()["objective"] == "Revised question"
    assert ok.json()["success_criteria"] == ["c1", "c2"]

    get_resp = await client.get(
        f"/experiments/{created['id']}",
        headers=auth_headers,
    )
    assert get_resp.json()["objective"] == "Revised question"
    assert get_resp.json()["success_criteria"] == ["c1", "c2"]

    rejected = await client.put(
        f"/experiments/{created['id']}",
        headers=auth_headers,
        json={"status": "COMPLETED"},
    )
    assert rejected.status_code == 422
