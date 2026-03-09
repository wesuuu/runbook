"""Tests for offline sync queue endpoint."""

import base64
import pytest
import pytest_asyncio
from uuid import uuid4

from app.core.security import hash_password, create_access_token, create_offline_token
from app.models.iam import User
from app.models.ai import RunImage
from app.models.science import Run, RunStatus, RunRoleAssignment


@pytest_asyncio.fixture
async def active_run(db_session, test_user, test_project):
    """Create an ACTIVE run with assignment and return (run, offline_token)."""
    run = Run(
        name="Sync Test Run",
        project_id=test_project.id,
        status=RunStatus.ACTIVE,
        graph={"nodes": [], "edges": []},
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()

    assignment = RunRoleAssignment(
        run_id=run.id, lane_node_id="__run__",
        role_name="Operator", user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()

    token, jti, expires = create_offline_token(test_user.id, run.id)
    return run, token


# --- POST /sync/offline-queue/{run_id} ---

async def test_sync_empty_queue(client, auth_headers, active_run):
    run, _ = active_run
    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={"actions": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["succeeded"] == 0
    assert data["failed"] == 0


async def test_sync_with_offline_token(client, active_run):
    run, token = active_run
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={"actions": []},
        headers=headers,
    )
    assert resp.status_code == 200


async def test_sync_offline_token_wrong_run(client, active_run, test_project, db_session, test_user):
    _, token = active_run
    # Create a different run
    run2 = Run(
        name="Other Run",
        project_id=test_project.id,
        status=RunStatus.ACTIVE,
        graph={}, execution_data={},
    )
    db_session.add(run2)
    await db_session.flush()

    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"/sync/offline-queue/{run2.id}",
        json={"actions": []},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "scoped" in resp.json()["detail"]


async def test_sync_image_upload(client, auth_headers, active_run):
    run, _ = active_run
    # Create a small test image
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    image_b64 = base64.b64encode(image_bytes).decode()

    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {
                    "action_type": "image_upload",
                    "step_id": "step-1",
                    "image_data": image_b64,
                    "image_filename": "test.png",
                    "parameter_tags": ["volume"],
                }
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["succeeded"] == 1
    assert data["results"][0]["success"] is True
    assert data["results"][0]["image_id"] is not None


async def test_sync_image_upload_missing_data(client, auth_headers, active_run):
    run, _ = active_run
    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {"action_type": "image_upload", "step_id": "step-1"}
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["failed"] == 1
    assert "image_data" in data["results"][0]["error"]


async def test_sync_parameter_tag(client, auth_headers, active_run, db_session, test_user):
    run, _ = active_run
    # Create an image first
    image = RunImage(
        run_id=run.id, step_id="step-1",
        file_path="test/path.jpg", original_filename="test.jpg",
        mime_type="image/jpeg", file_size_bytes=100,
        uploaded_by_id=test_user.id,
    )
    db_session.add(image)
    await db_session.flush()

    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {
                    "action_type": "parameter_tag",
                    "image_id": str(image.id),
                    "parameter_tags": ["volume", "pH"],
                }
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1


async def test_sync_manual_values(client, auth_headers, active_run):
    run, _ = active_run
    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {
                    "action_type": "manual_values",
                    "step_id": "step-1",
                    "values": {"volume": 1000, "pH": 7.2},
                }
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["succeeded"] == 1


async def test_sync_manual_values_detects_discrepancy(client, auth_headers, active_run, db_session):
    run, _ = active_run
    # Pre-populate AI results
    run.execution_data = {
        "step-1": {
            "status": "completed",
            "results": {"volume": 1000, "pH": 7.0},
        }
    }
    await db_session.flush()

    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {
                    "action_type": "manual_values",
                    "step_id": "step-1",
                    "values": {"volume": 1050, "pH": 8.5},  # volume within 5%, pH way off
                }
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 1


async def test_sync_mixed_actions(client, auth_headers, active_run):
    run, _ = active_run
    image_b64 = base64.b64encode(b"\x89PNG" + b"\x00" * 50).decode()

    resp = await client.post(
        f"/sync/offline-queue/{run.id}",
        json={
            "actions": [
                {
                    "action_type": "image_upload",
                    "step_id": "step-1",
                    "image_data": image_b64,
                    "parameter_tags": ["volume"],
                },
                {
                    "action_type": "manual_values",
                    "step_id": "step-1",
                    "values": {"volume": 500},
                },
                {
                    "action_type": "unknown_type",
                },
            ]
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["succeeded"] == 2
    assert data["failed"] == 1
    assert data["results"][2]["error"] == "Unknown action type: unknown_type"


async def test_sync_run_not_found(client, auth_headers):
    resp = await client.post(
        f"/sync/offline-queue/{uuid4()}",
        json={"actions": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404
