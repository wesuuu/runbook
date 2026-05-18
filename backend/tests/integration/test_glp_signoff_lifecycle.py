"""Integration tests for GLP sign-off lifecycle endpoints.

Tasks 12 and 13 of F-0087 GLP Gap Fixes:

* ``POST /science/runs/{run_id}/signoffs``
* ``POST /science/protocols/{protocol_id}/signoffs``

Both endpoints are thin wrappers over
``app.services.signoffs.service.create_signoff``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.science import Protocol, Run
from app.services.core.file_storage import FileStorageService


@pytest_asyncio.fixture
async def sample_run(db_session: AsyncSession, test_project) -> Run:
    """A minimal PLANNED run for sign-off endpoint tests."""
    run = Run(
        name="Signoff Lifecycle Test Run",
        project_id=test_project.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def sample_protocol(
    db_session: AsyncSession, test_project, test_user: User
) -> Protocol:
    """A minimal protocol for sign-off endpoint tests."""
    proto = Protocol(
        name="Signoff Lifecycle Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=1,
        created_by_id=test_user.id,
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def sample_user_with_signature(test_user: User, tmp_path) -> User:
    """Test user with a signature image file on disk."""
    sig = tmp_path / "sig.png"
    sig.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = str(sig)
    return test_user


@pytest_asyncio.fixture
def _isolated_storage_root(tmp_path, monkeypatch):
    """Redirect FileStorageService storage root into tmp_path."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )
    return tmp_path / "uploads"


# --- Task 12: POST /science/runs/{run_id}/signoffs --------------------------


@pytest.mark.asyncio
async def test_post_run_signoff_creates_active_row(
    client,
    auth_headers,
    sample_run,
    sample_user_with_signature,
    _isolated_storage_root,
):
    """Happy path: OPERATOR/APPROVED returns 201 with signature path set."""
    res = await client.post(
        f"/science/runs/{sample_run.id}/signoffs",
        headers=auth_headers,
        json={
            "role": "OPERATOR",
            "action": "APPROVED",
            "attestation": "I performed this run accurately.",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role"] == "OPERATOR"
    assert body["run_id"] == str(sample_run.id)
    assert body["signature_image_path"] is not None


@pytest.mark.asyncio
async def test_post_run_signoff_rejects_invalid_role_for_run(
    client,
    auth_headers,
    sample_run,
    sample_user_with_signature,
    _isolated_storage_root,
):
    """ck_run_signoff_roles refuses SPONSOR on a run."""
    res = await client.post(
        f"/science/runs/{sample_run.id}/signoffs",
        headers=auth_headers,
        json={
            "role": "SPONSOR",
            "action": "APPROVED",
            "attestation": "x",
        },
    )
    assert res.status_code in (400, 422), res.text


# --- Task 13: POST /science/protocols/{protocol_id}/signoffs ---------------


@pytest.mark.asyncio
async def test_post_protocol_signoff_creates_active_row(
    client,
    auth_headers,
    sample_protocol,
    sample_user_with_signature,
    _isolated_storage_root,
):
    """Happy path: QAU/APPROVED on a protocol returns 201."""
    res = await client.post(
        f"/science/protocols/{sample_protocol.id}/signoffs",
        headers=auth_headers,
        json={
            "role": "QAU",
            "action": "APPROVED",
            "attestation": "QAU attests.",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["protocol_id"] == str(sample_protocol.id)
    assert body["role"] == "QAU"


@pytest.mark.asyncio
async def test_post_protocol_signoff_rejects_operator_role(
    client,
    auth_headers,
    sample_protocol,
    sample_user_with_signature,
    _isolated_storage_root,
):
    """ck_protocol_signoff_roles refuses OPERATOR on a protocol."""
    res = await client.post(
        f"/science/protocols/{sample_protocol.id}/signoffs",
        headers=auth_headers,
        json={
            "role": "OPERATOR",
            "action": "APPROVED",
            "attestation": "x",
        },
    )
    assert res.status_code in (400, 422), res.text
