"""F-0043 — phases 4-7 integration tests."""

import pytest


@pytest.mark.asyncio
async def test_put_experiment_writes_conclusion_when_unlocked(
    client, seeded_experiment, auth_headers
):
    res = await client.put(
        f"/experiments/{seeded_experiment.id}",
        json={"conclusion": "Run 2 wins by 24%."},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["conclusion"] == "Run 2 wins by 24%."


@pytest.mark.asyncio
async def test_put_experiment_409_when_locked(
    client, locked_experiment, auth_headers
):
    # Lock guard freezes ALL fields, not just conclusion.
    for body in (
        {"conclusion": "new"},
        {"objective": "new objective"},
        {"description": "new desc"},
    ):
        res = await client.put(
            f"/experiments/{locked_experiment.id}",
            json=body,
            headers=auth_headers,
        )
        assert res.status_code == 409, body
        assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_post_run_to_locked_experiment_409(
    client, locked_experiment, test_project, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/runs",
        json={"name": "post-lock run", "protocol_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_create_run_via_runs_endpoint_to_locked_experiment_409(
    client, locked_experiment, test_project, auth_headers
):
    res = await client.post(
        "/runs",
        json={
            "name": "x",
            "project_id": str(test_project.id),
            "experiment_id": str(locked_experiment.id),
        },
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_add_note_to_locked_experiment_409(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/notes",
        json={"content": "post-lock observation", "flags": []},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_delete_note_from_locked_experiment_409(
    client, locked_experiment_with_note, auth_headers
):
    note_id = locked_experiment_with_note.notes[0]["id"]
    res = await client.delete(
        f"/experiments/{locked_experiment_with_note.id}/notes/{note_id}",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"
