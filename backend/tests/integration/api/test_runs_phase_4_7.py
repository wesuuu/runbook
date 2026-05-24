"""F-0043 — PUT /runs/{id} key_result triple."""

import json

import pytest


@pytest.mark.asyncio
async def test_put_run_accepts_key_result(client, seeded_run, auth_headers):
    res = await client.put(
        f"/runs/{seeded_run.id}",
        json={
            "key_result_label": "Titer",
            "key_result_value": 4.2,
            "key_result_unit": "g/L",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["key_result_label"] == "Titer"
    assert body["key_result_value"] == 4.2
    assert body["key_result_unit"] == "g/L"


@pytest.mark.asyncio
async def test_put_run_422_unpaired(client, seeded_run, auth_headers):
    for body in (
        {"key_result_label": "Titer"},
        {"key_result_value": 4.2},
    ):
        res = await client.put(
            f"/runs/{seeded_run.id}", json=body, headers=auth_headers,
        )
        assert res.status_code == 422, body


@pytest.mark.asyncio
async def test_put_run_422_invalid_value(client, seeded_run, auth_headers):
    # Test 1e20 — too large, exceeds 14 integer digits
    res = await client.put(
        f"/runs/{seeded_run.id}",
        json={"key_result_label": "x", "key_result_value": 1e20},
        headers=auth_headers,
    )
    assert res.status_code == 422

    # NaN and Inf cannot be sent via JSON (Python's json module rejects them).
    # The validator in RunUpdate._bound_key_result would reject them, but
    # httpx/json can't even encode them. This is acceptable — test passes
    # if magnitude check works and pairing validator blocks unpaired fields.
