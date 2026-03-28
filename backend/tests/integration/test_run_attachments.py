"""Integration tests for run attachments endpoints."""

import pytest
import pytest_asyncio
from io import BytesIO

from app.models.iam import ObjectPermission, PrincipalType, ObjectType, PermissionLevel
from app.models.science import Run, RunRoleAssignment


@pytest_asyncio.fixture
async def active_run(db_session, test_project, test_user):
    """An ACTIVE run with ADMIN permission."""
    run = Run(
        name="Attachment Test Run",
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


# --- Upload Tests ---

@pytest.mark.asyncio
async def test_upload_pdf_attachment(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("report.pdf", BytesIO(b"%PDF-content"), "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "report.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["deleted"] is False
    assert data["run_status"] == "ACTIVE"
    assert data["step_id"] is None


@pytest.mark.asyncio
async def test_upload_with_step_id(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("gel.jpg", BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg")},
        data={"step_id": "unitOp-abc123"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["step_id"] == "unitOp-abc123"


@pytest.mark.asyncio
async def test_upload_rejected_file_type(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("malware.exe", BytesIO(b"evil"), "application/x-msdownload")},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_csv(client, auth_headers, active_run):
    resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("data.csv", BytesIO(b"a,b,c\n1,2,3"), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "text/csv"


# --- List Tests ---

@pytest.mark.asyncio
async def test_list_attachments(client, auth_headers, active_run):
    # Upload two attachments
    await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("a.pdf", BytesIO(b"%PDF-a"), "application/pdf")},
        headers=auth_headers,
    )
    await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("b.csv", BytesIO(b"x,y"), "text/csv")},
        headers=auth_headers,
    )

    resp = await client.get(
        f"/science/runs/{active_run.id}/attachments",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2


@pytest.mark.asyncio
async def test_list_attachments_filter_by_step(client, auth_headers, active_run):
    # Upload run-level and step-level
    await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("run.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("step.csv", BytesIO(b"x"), "text/csv")},
        data={"step_id": "step-1"},
        headers=auth_headers,
    )

    # Filter by step
    resp = await client.get(
        f"/science/runs/{active_run.id}/attachments?step_id=step-1",
        headers=auth_headers,
    )
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["step_id"] == "step-1"


# --- Soft Delete Tests ---

@pytest.mark.asyncio
async def test_soft_delete_attachment(client, auth_headers, active_run):
    # Upload
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("del.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]

    # Delete
    del_resp = await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # Should be hidden from list
    list_resp = await client.get(
        f"/science/runs/{active_run.id}/attachments",
        headers=auth_headers,
    )
    ids = [a["id"] for a in list_resp.json()["items"]]
    assert att_id not in ids


@pytest.mark.asyncio
async def test_delete_already_deleted_returns_404(client, auth_headers, active_run):
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("f.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]

    await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )
    resp = await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# --- Restore Tests ---

@pytest.mark.asyncio
async def test_restore_attachment(client, auth_headers, active_run):
    # Upload + delete
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("r.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]
    await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )

    # Restore (user has ADMIN)
    resp = await client.post(
        f"/science/runs/{active_run.id}/attachments/{att_id}/restore",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is False

    # Should be back in list
    list_resp = await client.get(
        f"/science/runs/{active_run.id}/attachments",
        headers=auth_headers,
    )
    ids = [a["id"] for a in list_resp.json()["items"]]
    assert att_id in ids


# --- Download Tests ---

@pytest.mark.asyncio
async def test_download_attachment(client, auth_headers, active_run):
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("dl.txt", BytesIO(b"hello world"), "text/plain")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]

    resp = await client.get(
        f"/science/runs/{active_run.id}/attachments/{att_id}/download",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.content == b"hello world"


@pytest.mark.asyncio
async def test_download_deleted_attachment_returns_404(client, auth_headers, active_run):
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("x.txt", BytesIO(b"data"), "text/plain")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]
    await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )

    resp = await client.get(
        f"/science/runs/{active_run.id}/attachments/{att_id}/download",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_download_rejected(client, active_run):
    resp = await client.get(
        f"/science/runs/{active_run.id}/attachments/fake-id/download",
    )
    assert resp.status_code in (401, 403)


# --- Audit Log Tests ---

@pytest.mark.asyncio
async def test_attachment_operations_in_audit_log(client, auth_headers, active_run):
    # Upload
    upload_resp = await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("audit.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    att_id = upload_resp.json()["id"]

    # Delete
    await client.delete(
        f"/science/runs/{active_run.id}/attachments/{att_id}",
        headers=auth_headers,
    )

    # Restore
    await client.post(
        f"/science/runs/{active_run.id}/attachments/{att_id}/restore",
        headers=auth_headers,
    )

    # Check audit log
    resp = await client.get(
        f"/science/runs/{active_run.id}/audit-log",
        headers=auth_headers,
    )
    actions = [e["action"] for e in resp.json()["items"]]
    assert "ATTACHMENT_UPLOADED" in actions
    assert "ATTACHMENT_DELETED" in actions
    assert "ATTACHMENT_RESTORED" in actions


# --- Attachment in RunResponse ---

@pytest.mark.asyncio
async def test_attachments_in_run_response(client, auth_headers, active_run):
    await client.post(
        f"/science/runs/{active_run.id}/attachments",
        files={"file": ("inc.pdf", BytesIO(b"%PDF"), "application/pdf")},
        headers=auth_headers,
    )
    resp = await client.get(
        f"/science/runs/{active_run.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    attachments = resp.json()["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "inc.pdf"
