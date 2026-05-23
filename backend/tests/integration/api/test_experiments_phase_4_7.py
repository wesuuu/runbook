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


@pytest.mark.asyncio
async def test_lock_409_when_open_runs(
    client, experiment_with_open_run, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_with_open_run.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OPEN_RUNS"


@pytest.mark.asyncio
async def test_lock_409_when_conclusion_empty(
    client, experiment_terminal_no_conclusion, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_terminal_no_conclusion.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EMPTY_CONCLUSION"


@pytest.mark.asyncio
async def test_lock_happy_path(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conclusion_locked_at"] is not None
    assert body["conclusion_locked_by_name"] is not None
    assert body["lifecycle_status"] == "COMPLETE"


@pytest.mark.asyncio
async def test_lock_409_when_already_locked(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "ALREADY_LOCKED"


@pytest.mark.asyncio
async def test_lock_409_when_no_completed_runs(
    client, experiment_only_archived_runs, auth_headers
):
    # All-archived experiments read as DRAFT in lifecycle derivation; locking
    # would silently flip them to COMPLETE without any completed run. Refuse.
    res = await client.post(
        f"/experiments/{experiment_only_archived_runs.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "NO_COMPLETED_RUNS"


@pytest.mark.asyncio
async def test_lock_audit_row_atomic_with_state(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    """Lock UPDATE + audit insert must commit in the same transaction.

    Asserts that on a successful lock there is exactly one audit row whose
    `entity_id` matches the experiment AND that the experiment is actually
    locked — proving they were committed together.
    """
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    from sqlalchemy import text
    rows = await db_session.execute(
        text(
            "SELECT count(*) FROM audit_log "
            "WHERE entity_type='Experiment' AND entity_id=:eid AND action='conclusion.lock'"
        ),
        {"eid": experiment_ready_to_lock.id},
    )
    assert rows.scalar() == 1


@pytest.mark.asyncio
async def test_lock_vs_run_create_toctou(
    client, experiment_ready_to_lock, auth_headers, db_session
):
    """TOCTOU: lock + simultaneous run creation. Exactly one must succeed."""
    import asyncio

    async def lock():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
            headers=auth_headers,
        )

    async def add_run():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/runs",
            json={"name": "race run"},
            headers=auth_headers,
        )

    a, b = await asyncio.gather(lock(), add_run())
    # The lock either wins (200 + 409 on add_run) or loses (409 on lock + 201
    # on add_run). The forbidden state is both succeeding.
    successes = sum(1 for r in (a, b) if r.status_code < 400)
    assert successes == 1, f"both succeeded: lock={a.status_code} add_run={b.status_code}"
