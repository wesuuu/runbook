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
    """An ACTIVE (in-progress) run cannot be signed off either (F-0080-D5)."""
    resp = await _attempt_qau_signoff(
        client, glp_run_active, qau_user, glp_org, tmp_path, monkeypatch
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "RUN_NOT_COMPLETED"
