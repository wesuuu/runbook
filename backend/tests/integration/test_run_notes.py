"""Integration tests for run notes endpoints."""

from uuid import uuid4

import pytest
import pytest_asyncio

from app.models.iam import ObjectPermission, ObjectType, PermissionLevel, PrincipalType
from app.models.runs import Run, RunRoleAssignment


@pytest_asyncio.fixture
async def test_run(db_session, test_project, test_user):
    """A PLANNED run with role assignment and EDIT permission."""
    run = Run(
        name="Test Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()

    # Grant EDIT on the run
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


@pytest_asyncio.fixture
async def active_run(db_session, test_project, test_user):
    """An ACTIVE run."""
    run = Run(
        name="Active Run",
        project_id=test_project.id,
        status="ACTIVE",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        started_by_id=test_user.id,
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

    # Add a role assignment so the run is valid
    db_session.add(
        RunRoleAssignment(
            run_id=run.id,
            lane_node_id="lane-1",
            role_name="Operator",
            user_id=test_user.id,
        )
    )
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def completed_run(db_session, test_project, test_user):
    """A COMPLETED run."""
    run = Run(
        name="Completed Run",
        project_id=test_project.id,
        status="COMPLETED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
        started_by_id=test_user.id,
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


# --- Add Note Tests ---


@pytest.mark.asyncio
async def test_add_note_to_planned_run(client, auth_headers, test_run):
    resp = await client.post(
        f"/science/runs/{test_run.id}/notes",
        json={"content": "Pre-run setup note", "flags": []},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Pre-run setup note"
    assert data["run_status"] == "PLANNED"
    assert data["flags"] == []
    assert "id" in data
    assert "author_id" in data
    assert data["author_name"] == "Test User"
    assert "created_at" in data


@pytest.mark.asyncio
async def test_add_note_to_active_run(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Culture looked cloudy", "flags": ["anomaly"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Culture looked cloudy"
    assert data["run_status"] == "ACTIVE"
    assert data["flags"] == ["anomaly"]


@pytest.mark.asyncio
async def test_add_note_to_completed_run_does_not_change_status(
    client, auth_headers, completed_run
):
    resp = await client.post(
        f"/science/runs/{completed_run.id}/notes",
        json={"content": "Post-run observation"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["run_status"] == "COMPLETED"

    # Verify run status is still COMPLETED
    run_resp = await client.get(
        f"/science/runs/{completed_run.id}",
        headers=auth_headers,
    )
    assert run_resp.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_notes_are_append_only(client, auth_headers, active_run):
    await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Note 1"},
        headers=auth_headers,
    )
    await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Note 2"},
        headers=auth_headers,
    )

    resp = await client.get(
        f"/science/runs/{active_run.id}/notes",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["content"] == "Note 1"
    assert items[1]["content"] == "Note 2"


@pytest.mark.asyncio
async def test_invalid_flag_rejected(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Test", "flags": ["invalid_flag"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_content_rejected(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "", "flags": []},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_note_included_in_run_response(client, auth_headers, active_run):
    await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Observation"},
        headers=auth_headers,
    )
    resp = await client.get(
        f"/science/runs/{active_run.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert len(notes) == 1
    assert notes[0]["content"] == "Observation"


@pytest.mark.asyncio
async def test_note_audit_log(client, auth_headers, active_run):
    await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Audit test note", "flags": ["anomaly"]},
        headers=auth_headers,
    )
    resp = await client.get(
        f"/science/runs/{active_run.id}/audit-log",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    note_entries = [e for e in items if e["action"] == "NOTE_ADDED"]
    assert len(note_entries) == 1
    assert note_entries[0]["changes"]["content"] == "Audit test note"
    assert note_entries[0]["changes"]["run_status"] == "ACTIVE"
    assert note_entries[0]["changes"]["flags"] == ["anomaly"]


@pytest.mark.asyncio
async def test_unauthenticated_note_rejected(client, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/notes",
        json={"content": "Should fail"},
    )
    assert resp.status_code in (401, 403)
