"""Integration tests for GLP sign-off lifecycle endpoints.

Tasks 12, 13, 14, and 15 of F-0087 GLP Gap Fixes:

* ``POST /science/runs/{run_id}/signoffs``
* ``POST /science/protocols/{protocol_id}/signoffs``
* ``POST /science/runs/{run_id}/complete``
* ``POST /science/runs/{run_id}/reopen``
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.science import GlpSignoff, Protocol, Run
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


# --- Task 14 fixtures and tests --------------------------------------------


@pytest_asyncio.fixture
async def sample_active_protocol(
    db_session: AsyncSession, test_project, test_user: User
) -> Protocol:
    """A protocol with an empty graph (no glpSettings overrides)."""
    proto = Protocol(
        name="Run Lifecycle Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=1,
        created_by_id=test_user.id,
        graph={"nodes": [], "edges": [], "glpSettings": {}},
    )
    db_session.add(proto)
    await db_session.flush()
    return proto


@pytest_asyncio.fixture
async def sample_active_run(
    db_session: AsyncSession, test_project, sample_active_protocol
) -> Run:
    """An ACTIVE run linked to a protocol with empty glpSettings.

    Only OPERATOR sign-off is required to close (Study Director and QAU
    are not gated by default).
    """
    run = Run(
        name="Run Lifecycle Active",
        project_id=test_project.id,
        protocol_id=sample_active_protocol.id,
        status="ACTIVE",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest_asyncio.fixture
async def sample_active_run_with_operator_signoff(
    db_session: AsyncSession,
    sample_active_run: Run,
    test_user: User,
) -> Run:
    """ACTIVE run that already has an active OPERATOR APPROVED sign-off."""
    so = GlpSignoff(
        run_id=sample_active_run.id,
        role="OPERATOR",
        action="APPROVED",
        signer_id=test_user.id,
        attestation="I performed the run.",
        signed_at=datetime.now(timezone.utc),
        signature_image_path="fixture/operator.png",
    )
    db_session.add(so)
    await db_session.flush()
    return sample_active_run


# --- Task 14: POST /science/runs/{run_id}/complete -------------------------


@pytest.mark.asyncio
async def test_run_complete_requires_operator_signoff(
    client,
    auth_headers,
    sample_active_run,
):
    """Without an OPERATOR sign-off, /complete returns 400 SIGNOFF_REQUIRED."""
    res = await client.post(
        f"/science/runs/{sample_active_run.id}/complete",
        headers=auth_headers,
        json={"outcome": "COMPLETED_NORMAL"},
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["error"] == "SIGNOFF_REQUIRED"
    assert "OPERATOR" in body["detail"]["missing_roles"]


@pytest.mark.asyncio
async def test_run_complete_sets_outcome_and_completed_at(
    client,
    auth_headers,
    sample_active_run_with_operator_signoff,
):
    """Happy path: outcome and completed_at populated; status -> COMPLETED."""
    res = await client.post(
        f"/science/runs/{sample_active_run_with_operator_signoff.id}/complete",
        headers=auth_headers,
        json={
            "outcome": "COMPLETED_WITH_DEVIATIONS",
            "outcome_notes": "pH drift on step 7",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "COMPLETED"
    assert body["outcome"] == "COMPLETED_WITH_DEVIATIONS"
    assert body["outcome_notes"] == "pH drift on step 7"
    assert body["completed_at"] is not None


# --- Task 15 fixtures and tests --------------------------------------------


@pytest_asyncio.fixture
async def completed_run_with_signoffs(
    db_session: AsyncSession,
    sample_active_run: Run,
    test_user: User,
) -> Run:
    """A COMPLETED run carrying OPERATOR + QAU active sign-offs."""
    sample_active_run.status = "COMPLETED"
    sample_active_run.completed_at = datetime.now(timezone.utc)
    sample_active_run.outcome = "COMPLETED_NORMAL"
    db_session.add(
        GlpSignoff(
            run_id=sample_active_run.id,
            role="OPERATOR",
            action="APPROVED",
            signer_id=test_user.id,
            attestation="Operator attestation.",
            signed_at=datetime.now(timezone.utc),
            signature_image_path="fixture/operator.png",
        )
    )
    db_session.add(
        GlpSignoff(
            run_id=sample_active_run.id,
            role="QAU",
            action="APPROVED",
            signer_id=test_user.id,
            attestation="QAU attestation.",
            signed_at=datetime.now(timezone.utc),
            signature_image_path="fixture/qau.png",
        )
    )
    await db_session.flush()
    return sample_active_run


# --- Task 15: POST /science/runs/{run_id}/reopen ---------------------------


@pytest.mark.asyncio
async def test_reopen_invalidates_all_active_signoffs(
    client,
    auth_headers,
    completed_run_with_signoffs,
    db_session: AsyncSession,
):
    """All active sign-offs (operator + QAU) get invalidated on reopen."""
    from sqlalchemy import select

    res = await client.post(
        f"/science/runs/{completed_run_with_signoffs.id}/reopen",
        headers=auth_headers,
        json={"reason": "pH probe drift on step 7-9"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] in ("EDITED", "ACTIVE")

    # Confirm no rows remain active for this run (queries DB directly until
    # the GET listing endpoint lands in Task 16).
    result = await db_session.execute(
        select(GlpSignoff).where(
            GlpSignoff.run_id == completed_run_with_signoffs.id,
            GlpSignoff.action == "APPROVED",
            GlpSignoff.invalidated_at.is_(None),
        )
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_reopen_requires_reason(
    client,
    auth_headers,
    completed_run_with_signoffs,
):
    """Empty/missing reason returns 400 or 422 from Pydantic min_length."""
    res = await client.post(
        f"/science/runs/{completed_run_with_signoffs.id}/reopen",
        headers=auth_headers,
        json={"reason": ""},
    )
    assert res.status_code in (400, 422), res.text
