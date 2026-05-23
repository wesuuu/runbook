"""Integration: creating a run GlpSignoff fulfills the matching request (F-0080)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.signoffs import GlpSignoffRequest
from app.services.core.file_storage import FileStorageService


@pytest.mark.asyncio
async def test_signoff_fulfills_open_request(
    client: AsyncClient,
    db_session,
    glp_run_completed,
    qau_user,
    glp_org,
    tmp_path,
    monkeypatch,
):
    """Creating a QAU sign-off on a run with an OPEN QAU request
    must flip that request's status to APPROVED (F-0080)."""

    # Redirect FileStorageService so shutil.copyfile has a writable root.
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )

    # Give qau_user a real signature file. signature_full_path is stored
    # RELATIVE to the storage root (the shape /auth/me/signature writes),
    # and the file lives under that root so create_signoff can resolve it.
    relative_sig = "test-org/signatures/quinn_auditor-full.png"
    sig_file = tmp_path / "uploads" / relative_sig
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    sig_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    qau_user.signature_full_path = relative_sig

    # An OPEN QAU request exists for the completed run.
    db_session.add(
        GlpSignoffRequest(
            run_id=glp_run_completed.id,
            role="QAU",
            status="OPEN",
            requested_user_id=qau_user.id,
        )
    )
    await db_session.flush()

    # qau_user signs off as QAU.
    from app.core.security import create_access_token

    token = create_access_token(
        qau_user.id,
        org_id=glp_org.id,
        subscription_tier=glp_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        f"/runs/{glp_run_completed.id}/signoffs",
        json={
            "role": "QAU",
            "action": "APPROVED",
            "attestation": "I have audited this study for GLP compliance.",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # The OPEN request must now be APPROVED.
    row = await db_session.execute(
        select(GlpSignoffRequest).where(
            GlpSignoffRequest.run_id == glp_run_completed.id,
            GlpSignoffRequest.role == "QAU",
        )
    )
    assert row.scalar_one().status == "APPROVED"


async def _attempt_qau_signoff(
    client: AsyncClient, run, qau_user, glp_org, tmp_path, monkeypatch
):
    """Set up a QAU signer with a real signature and POST a sign-off to ``run``."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )
    relative_sig = "test-org/signatures/quinn_auditor-full.png"
    sig_file = tmp_path / "uploads" / relative_sig
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    sig_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    qau_user.signature_full_path = relative_sig

    from app.core.security import create_access_token

    token = create_access_token(
        qau_user.id,
        org_id=glp_org.id,
        subscription_tier=glp_org.subscription_tier,
        email_verified=True,
    )
    return await client.post(
        f"/runs/{run.id}/signoffs",
        json={
            "role": "QAU",
            "action": "APPROVED",
            "attestation": "Attempting to sign a non-completed run.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_signoff_rejected_on_planned_run(
    client: AsyncClient, glp_run_planned, qau_user, glp_org, tmp_path, monkeypatch
):
    """A run sign-off may only be created on a COMPLETED run (F-0080-D5).

    GLP §58.35 QAU review is review of *completed* records — a PLANNED run
    has no finalized execution data to attest to. The endpoint must reject
    the sign-off with 409 RUN_NOT_COMPLETED before any row is inserted.
    """
    resp = await _attempt_qau_signoff(
        client, glp_run_planned, qau_user, glp_org, tmp_path, monkeypatch
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "RUN_NOT_COMPLETED"


@pytest.mark.asyncio
async def test_signoff_rejected_on_active_run(
    client: AsyncClient, glp_run_active, qau_user, glp_org, tmp_path, monkeypatch
):
    """An ACTIVE (in-progress) run cannot be QAU-signed off either (F-0080-D5)."""
    resp = await _attempt_qau_signoff(
        client, glp_run_active, qau_user, glp_org, tmp_path, monkeypatch
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "RUN_NOT_COMPLETED"


async def _attempt_operator_signoff(
    client: AsyncClient, run, test_user, auth_headers, tmp_path, monkeypatch
):
    """Give the authenticated user a signature and POST an OPERATOR sign-off."""
    monkeypatch.setattr(
        FileStorageService,
        "__init__",
        lambda self: setattr(self, "storage_root", tmp_path / "uploads") or None,
    )
    relative_sig = f"test-org/signatures/{test_user.id}-full.png"
    sig_file = tmp_path / "uploads" / relative_sig
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    sig_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = relative_sig
    return await client.post(
        f"/runs/{run.id}/signoffs",
        json={
            "role": "OPERATOR",
            "action": "APPROVED",
            "attestation": "I attest all steps were executed within specification.",
        },
        headers=auth_headers,
    )


@pytest.mark.asyncio
async def test_operator_signoff_accepted_on_active_run(
    client: AsyncClient,
    glp_run_active,
    test_user,
    auth_headers,
    tmp_path,
    monkeypatch,
):
    """The OPERATOR sign-off is a *precondition* of run closure
    (``assert_run_can_close`` gates the COMPLETED transition on it), so it
    must be recordable while the run is still ACTIVE — before /complete.

    Rejecting it here would deadlock GLP run completion: closure needs the
    OPERATOR sign-off, and the OPERATOR sign-off would need the run already
    COMPLETED (F-0080).
    """
    resp = await _attempt_operator_signoff(
        client, glp_run_active, test_user, auth_headers, tmp_path, monkeypatch
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "OPERATOR"


@pytest.mark.asyncio
async def test_operator_signoff_rejected_on_planned_run(
    client: AsyncClient,
    glp_run_planned,
    test_user,
    auth_headers,
    tmp_path,
    monkeypatch,
):
    """A PLANNED run has executed no steps, so there is nothing for the
    operator to attest to — reject with 409 RUN_NOT_STARTED (F-0080)."""
    resp = await _attempt_operator_signoff(
        client, glp_run_planned, test_user, auth_headers, tmp_path, monkeypatch
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "RUN_NOT_STARTED"
