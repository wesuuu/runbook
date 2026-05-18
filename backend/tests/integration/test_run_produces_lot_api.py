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
