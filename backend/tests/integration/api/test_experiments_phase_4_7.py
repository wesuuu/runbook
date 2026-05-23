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
