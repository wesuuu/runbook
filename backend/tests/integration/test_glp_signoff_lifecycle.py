"""Integration tests for GLP sign-off lifecycle endpoints.

Tasks 12, 13, 14, 15, and 16 of F-0087 GLP Gap Fixes:

* ``POST /runs/{run_id}/signoffs``
* ``POST /protocols/{protocol_id}/signoffs``
* ``POST /runs/{run_id}/complete``
* ``POST /runs/{run_id}/reopen``
* ``GET  /runs/{run_id}/signoffs``
* ``GET  /protocols/{protocol_id}/signoffs``
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.protocols import Protocol
from app.models.runs import Run
from app.models.signoffs import GlpSignoff
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
    """Test user with a signature image file on disk.

    ``signature_full_path`` is stored RELATIVE to the storage root (the shape
    the ``/auth/me/signature`` upload writes) and the file is placed under
    ``{tmp_path}/uploads`` — the root ``_isolated_storage_root`` patches in —
    so ``create_signoff`` can resolve it the same way production does.
    """
    relative = "test-org/signatures/test-user-full.png"
    sig = tmp_path / "uploads" / relative
    sig.parent.mkdir(parents=True, exist_ok=True)
    sig.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_user.signature_full_path = relative
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


# --- Task 12: POST /runs/{run_id}/signoffs --------------------------


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
        f"/runs/{sample_run.id}/signoffs",
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
        f"/runs/{sample_run.id}/signoffs",
        headers=auth_headers,
        json={
            "role": "SPONSOR",
            "action": "APPROVED",
            "attestation": "x",
        },
    )
    assert res.status_code in (400, 422), res.text


# --- Task 13: POST /protocols/{protocol_id}/signoffs ---------------


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
        f"/protocols/{sample_protocol.id}/signoffs",
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
        f"/protocols/{sample_protocol.id}/signoffs",
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


# --- Task 14: POST /runs/{run_id}/complete -------------------------


@pytest.mark.asyncio
async def test_run_complete_requires_operator_signoff(
    client,
    auth_headers,
    sample_active_run,
):
    """Without an OPERATOR sign-off, /complete returns 400 SIGNOFF_REQUIRED."""
    res = await client.post(
        f"/runs/{sample_active_run.id}/complete",
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
        f"/runs/{sample_active_run_with_operator_signoff.id}/complete",
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


# --- Task 15: POST /runs/{run_id}/reopen ---------------------------


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
        f"/runs/{completed_run_with_signoffs.id}/reopen",
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
        f"/runs/{completed_run_with_signoffs.id}/reopen",
        headers=auth_headers,
        json={"reason": ""},
    )
    assert res.status_code in (400, 422), res.text


# --- Task 16: GET /runs|protocols/{id}/signoffs --------------------


@pytest.mark.asyncio
async def test_list_run_signoffs_includes_invalidated_when_requested(
    client,
    auth_headers,
    completed_run_with_signoffs,
):
    """After reopen, active=false returns invalidated rows; active=true is empty."""
    res = await client.post(
        f"/runs/{completed_run_with_signoffs.id}/reopen",
        headers=auth_headers,
        json={"reason": "fix step 8"},
    )
    assert res.status_code == 200, res.text

    res_all = await client.get(
        f"/runs/{completed_run_with_signoffs.id}/signoffs",
        headers=auth_headers,
    )
    assert res_all.status_code == 200, res_all.text
    rows = res_all.json()
    assert len(rows) >= 2
    assert any(r["invalidated_at"] is not None for r in rows)

    res_active = await client.get(
        f"/runs/{completed_run_with_signoffs.id}/signoffs?active=true",
        headers=auth_headers,
    )
    assert res_active.status_code == 200, res_active.text
    assert res_active.json() == []


# --- Task 17: PATCH /runs/{id}/state with edit_reasons ---------------------


@pytest.mark.asyncio
async def test_edited_transition_requires_edit_reason_per_modified_step(
    client,
    auth_headers,
    sample_active_run,
):
    res = await client.patch(
        f"/runs/{sample_active_run.id}/state",
        headers=auth_headers,
        json={
            "state": "EDITED",
            "edit_reasons": {},
            "execution_data_delta": {"step1": {"value": 7}},
        },
    )
    assert res.status_code == 400, res.text
    assert res.json()["detail"]["error"] == "EDIT_REASON_REQUIRED"


@pytest.mark.asyncio
async def test_edited_transition_passes_when_reasons_provided(
    client,
    auth_headers,
    sample_active_run,
):
    res = await client.patch(
        f"/runs/{sample_active_run.id}/state",
        headers=auth_headers,
        json={
            "state": "EDITED",
            "edit_reasons": {"step1": "probe drift"},
            "execution_data_delta": {"step1": {"value": 7}},
        },
    )
    assert res.status_code == 200, res.text


# --- Task 18: PLANNED -> ACTIVE stamps started_at --------------------------


@pytest_asyncio.fixture
async def sample_planned_run(
    db_session: AsyncSession, test_project, sample_active_protocol
) -> Run:
    """A PLANNED run linked to a protocol with empty glpSettings."""
    run = Run(
        name="Run Lifecycle Planned",
        project_id=test_project.id,
        protocol_id=sample_active_protocol.id,
        status="PLANNED",
        graph={"nodes": [], "edges": []},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_active_transition_sets_started_at(
    client,
    auth_headers,
    sample_planned_run,
):
    res = await client.patch(
        f"/runs/{sample_planned_run.id}/state",
        headers=auth_headers,
        json={"state": "ACTIVE"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["started_at"] is not None
    assert body["started_by_id"] is not None


# --- Task 19: step in_progress records started_by_user_id -----------------


@pytest.mark.asyncio
async def test_step_in_progress_records_started_by(
    client,
    auth_headers,
    sample_active_run,
    test_user,
):
    res = await client.patch(
        f"/runs/{sample_active_run.id}/steps/step1",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert res.status_code == 200, res.text
    run_after = await client.get(
        f"/runs/{sample_active_run.id}",
        headers=auth_headers,
    )
    assert run_after.status_code == 200, run_after.text
    step = run_after.json()["execution_data"]["step1"]
    assert step["started_by_user_id"] == str(test_user.id)
    assert step.get("started_at") is not None


# --- Task 20: POST /runs/{id}/steps/{step_id}/review ----------------------


@pytest_asyncio.fixture
async def sample_completed_step_run(
    db_session: AsyncSession,
    test_project,
    sample_active_protocol,
    test_user: User,
) -> Run:
    """An ACTIVE run whose step1 was started+completed by a different user
    so the calling test_user can act as the independent reviewer."""
    from uuid import uuid4

    other_user_id = str(uuid4())
    run = Run(
        name="Run Lifecycle Step Review",
        project_id=test_project.id,
        protocol_id=sample_active_protocol.id,
        status="ACTIVE",
        graph={"nodes": [], "edges": []},
        execution_data={
            "step1": {
                "status": "completed",
                "started_by_user_id": other_user_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        notes=[],
        attachments=[],
    )
    db_session.add(run)
    await db_session.flush()
    return run


@pytest.mark.asyncio
async def test_step_review_sets_reviewed_by_and_audit(
    client,
    auth_headers,
    sample_completed_step_run,
    test_user,
):
    res = await client.post(
        f"/runs/{sample_completed_step_run.id}/steps/step1/review",
        headers=auth_headers,
        json={},
    )
    assert res.status_code == 200, res.text
    run = (
        await client.get(
            f"/runs/{sample_completed_step_run.id}",
            headers=auth_headers,
        )
    ).json()
    step = run["execution_data"]["step1"]
    assert step["reviewed_by_user_id"] == str(test_user.id)
    assert step["reviewed_at"] is not None
