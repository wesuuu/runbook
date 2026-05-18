"""Integration tests for F-0086 produces_lot validation and endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.iam import (ObjectPermission, ObjectType, PermissionLevel,
                            PrincipalType)
from app.models.science import Run


@pytest_asyncio.fixture
async def test_run(db_session, test_project, test_user):
    """A PLANNED run with lot_number=None and ADMIN permission for test_user."""
    run = Run(
        name="Test Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        lot_number=None,
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        ObjectPermission(
            principal_type=PrincipalType.USER,
            principal_id=test_user.id,
            object_type=ObjectType.RUN.value,
            object_id=run.id,
            permission_level=PermissionLevel.ADMIN.value,
        )
    )
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_create_run_produces_lot_without_lot_number_rejected(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "lot-without-number",
            "project_id": str(test_project.id),
            "produces_lot": True,
        },
    )
    assert resp.status_code == 422
    assert "lot_number" in resp.text


@pytest.mark.asyncio
async def test_create_run_produces_lot_with_lot_number_ok(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "ok-producer",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000001",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["produces_lot"] is True
    assert body["lot_number"] == "LOT-000001"


@pytest.mark.asyncio
async def test_update_run_produces_lot_without_lot_number_rejected(
    client: AsyncClient, auth_headers, test_run
):
    resp = await client.put(
        f"/science/runs/{test_run.id}",
        headers=auth_headers,
        json={"produces_lot": True},
    )
    assert resp.status_code == 422
    assert "lot_number" in resp.text


@pytest.mark.asyncio
async def test_list_project_runs_filter_produces_lot(
    client: AsyncClient, auth_headers, test_project
):
    # Create two runs: one producer, one not.
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "non-producer",
            "project_id": str(test_project.id),
        },
    )
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "producer",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000010",
        },
    )

    resp_true = await client.get(
        f"/science/projects/{test_project.id}/runs?produces_lot=true",
        headers=auth_headers,
    )
    assert resp_true.status_code == 200
    names = {r["name"] for r in resp_true.json()}
    assert names == {"producer"}

    resp_false = await client.get(
        f"/science/projects/{test_project.id}/runs?produces_lot=false",
        headers=auth_headers,
    )
    assert {r["name"] for r in resp_false.json()} == {"non-producer"}

    resp_all = await client.get(
        f"/science/projects/{test_project.id}/runs",
        headers=auth_headers,
    )
    assert {r["name"] for r in resp_all.json()} >= {"producer", "non-producer"}


@pytest.mark.asyncio
async def test_suggest_lot_number_empty_org_returns_first(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.status_code == 200
    assert resp.json() == {"lot_number": "LOT-000001"}


@pytest.mark.asyncio
async def test_suggest_lot_number_increments_after_existing(
    client: AsyncClient, auth_headers, test_project
):
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "first",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000042",
        },
    )
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.json() == {"lot_number": "LOT-000043"}


@pytest.mark.asyncio
async def test_suggest_lot_number_ignores_non_matching_values(
    client: AsyncClient, auth_headers, test_project
):
    # Manual entry that does not match the LOT-NNNNNN pattern is ignored
    # by the sequence calculation.
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "custom",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "PILOT-A7",
        },
    )
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.json() == {"lot_number": "LOT-000001"}
