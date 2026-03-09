"""Tests for offline field mode endpoints: session creation, prefetch, revocation."""

import pytest
import pytest_asyncio
from uuid import uuid4

from app.core.security import hash_password, create_access_token, create_offline_token
from app.models.iam import User
from app.models.science import Run, RunStatus, RunRoleAssignment, Project, UnitOpDefinition


@pytest_asyncio.fixture
async def run_with_assignment(db_session, test_user, test_project):
    """Create an ACTIVE run with a role assignment for test_user."""
    run = Run(
        name="Offline Test Run",
        project_id=test_project.id,
        status=RunStatus.ACTIVE,
        graph={
            "nodes": [
                {"id": "step-1", "type": "unitOp", "data": {"label": "Seeding", "unitOpId": None}},
            ],
            "edges": [],
        },
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()

    assignment = RunRoleAssignment(
        run_id=run.id,
        lane_node_id="__run__",
        role_name="Operator",
        user_id=test_user.id,
    )
    db_session.add(assignment)
    await db_session.flush()
    return run


# --- POST /auth/offline-session ---

async def test_create_offline_session_success(client, auth_headers, test_user, run_with_assignment):
    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run_with_assignment.id), "password": "testpass"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "offline_token" in data
    assert data["run_id"] == str(run_with_assignment.id)
    assert "expires_at" in data


async def test_create_offline_session_wrong_password(client, auth_headers, run_with_assignment):
    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run_with_assignment.id), "password": "wrongpass"},
        headers=auth_headers,
    )
    assert resp.status_code == 401
    assert "Invalid password" in resp.json()["detail"]


async def test_create_offline_session_run_not_active(client, auth_headers, test_user, test_project, db_session):
    run = Run(
        name="Planned Run",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        graph={},
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

    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run.id), "password": "testpass"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "ACTIVE" in resp.json()["detail"]


async def test_create_offline_session_no_role(client, auth_headers, test_project, db_session):
    run = Run(
        name="No Role Run",
        project_id=test_project.id,
        status=RunStatus.ACTIVE,
        graph={},
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()

    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run.id), "password": "testpass"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    assert "assigned" in resp.json()["detail"]


async def test_create_offline_session_run_not_found(client, auth_headers):
    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(uuid4()), "password": "testpass"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# --- GET /offline/runs/{run_id}/prefetch ---

async def test_prefetch_run_data(client, auth_headers, run_with_assignment):
    resp = await client.get(
        f"/offline/runs/{run_with_assignment.id}/prefetch",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == str(run_with_assignment.id)
    assert data["run_name"] == "Offline Test Run"
    assert data["run_status"] == "ACTIVE"
    assert "graph" in data
    assert "execution_data" in data
    assert len(data["role_assignments"]) == 1
    assert data["role_assignments"][0]["role_name"] == "Operator"


async def test_prefetch_includes_unit_op_defs(client, auth_headers, test_project, test_user, db_session):
    # Create a unit op definition
    uod = UnitOpDefinition(
        name="Buffer Mix",
        category="Media Prep",
        param_schema={"properties": {"volume": {"type": "number"}}},
    )
    db_session.add(uod)
    await db_session.flush()

    run = Run(
        name="Run With UnitOps",
        project_id=test_project.id,
        status=RunStatus.ACTIVE,
        graph={
            "nodes": [
                {"id": "s1", "type": "unitOp", "data": {"label": "Mix", "unitOpId": str(uod.id)}},
            ],
            "edges": [],
        },
        execution_data={},
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(RunRoleAssignment(
        run_id=run.id, lane_node_id="__run__",
        role_name="Operator", user_id=test_user.id,
    ))
    await db_session.flush()

    resp = await client.get(f"/offline/runs/{run.id}/prefetch", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert str(uod.id) in data["unit_op_definitions"]
    assert data["unit_op_definitions"][str(uod.id)]["name"] == "Buffer Mix"


async def test_prefetch_run_not_found(client, auth_headers):
    resp = await client.get(f"/offline/runs/{uuid4()}/prefetch", headers=auth_headers)
    assert resp.status_code == 404


# --- DELETE /auth/offline-session/{jti} ---

async def test_revoke_offline_token(client, auth_headers, run_with_assignment):
    # First create an offline session
    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run_with_assignment.id), "password": "testpass"},
        headers=auth_headers,
    )
    token_data = resp.json()

    # Decode to get JTI
    from app.core.security import decode_offline_token
    payload = decode_offline_token(token_data["offline_token"])
    jti = payload["jti"]

    # Revoke it
    resp = await client.request(
        "DELETE",
        f"/auth/offline-session/{jti}",
        headers=auth_headers,
        json={"reason": "Admin override"},
    )
    assert resp.status_code == 200
    assert resp.json()["jti"] == jti

    # Verify the revoked token is rejected
    offline_headers = {"Authorization": f"Bearer {token_data['offline_token']}"}
    resp = await client.post(
        f"/sync/offline-queue/{run_with_assignment.id}",
        json={"actions": []},
        headers=offline_headers,
    )
    assert resp.status_code == 401
    assert "revoked" in resp.json()["detail"]


async def test_revoke_already_revoked(client, auth_headers, run_with_assignment):
    resp = await client.post(
        "/auth/offline-session",
        json={"run_id": str(run_with_assignment.id), "password": "testpass"},
        headers=auth_headers,
    )
    from app.core.security import decode_offline_token
    jti = decode_offline_token(resp.json()["offline_token"])["jti"]

    await client.request("DELETE", f"/auth/offline-session/{jti}", headers=auth_headers)
    resp2 = await client.request("DELETE", f"/auth/offline-session/{jti}", headers=auth_headers)
    assert resp2.status_code == 409
