"""Unit tests for GLP sign-off cross-context validators."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.signoffs.validation import (
    SignoffPayload, assert_attestation_and_image_present,
    assert_qau_independent)

# ---------------------------------------------------------------------------
# assert_attestation_and_image_present
# ---------------------------------------------------------------------------


def test_assert_attestation_and_image_present_passes_for_non_approved():
    payload = SignoffPayload(
        role="QAU",
        action="REJECTED",
        attestation=None,
        signature_image_path=None,
    )
    # Should not raise
    assert_attestation_and_image_present(payload)


def test_assert_attestation_and_image_present_fails_for_approved_without_attestation():
    payload = SignoffPayload(
        role="QAU",
        action="APPROVED",
        attestation=None,
        signature_image_path="p.png",
    )
    with pytest.raises(HTTPException) as exc:
        assert_attestation_and_image_present(payload)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "ATTESTATION_REQUIRED"


def test_assert_attestation_and_image_present_fails_for_approved_without_image():
    payload = SignoffPayload(
        role="QAU",
        action="APPROVED",
        attestation="I attest this is correct.",
        signature_image_path=None,
    )
    with pytest.raises(HTTPException) as exc:
        assert_attestation_and_image_present(payload)
    assert exc.value.detail["error"] == "ATTESTATION_REQUIRED"


def test_assert_attestation_and_image_present_passes_for_approved_with_both():
    payload = SignoffPayload(
        role="OPERATOR",
        action="APPROVED",
        attestation="I attest.",
        signature_image_path="signatures/op.png",
    )
    # Should not raise
    assert_attestation_and_image_present(payload)


def test_assert_attestation_and_image_present_passes_requested_changes_no_image():
    payload = SignoffPayload(
        role="STUDY_DIRECTOR",
        action="REQUESTED_CHANGES",
        attestation=None,
        signature_image_path=None,
    )
    assert_attestation_and_image_present(payload)


# ---------------------------------------------------------------------------
# assert_qau_independent — non-QAU role short-circuits
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_skips_non_qau():
    """Non-QAU roles are never checked for independence."""
    db = AsyncMock()
    # If it somehow tried to query DB it would raise AttributeError — we check it
    # doesn't by passing a bare MagicMock
    await assert_qau_independent(
        db=MagicMock(),
        entity_type="run",
        entity_id=uuid4(),
        signer_id=uuid4(),
        role="OPERATOR",
    )


# ---------------------------------------------------------------------------
# assert_qau_independent — started_by_id conflict (OPERATOR)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_rejects_operator():
    """QAU signer == run.started_by_id → QAU_NOT_INDEPENDENT / OPERATOR."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = signer_id
    mock_run.created_by_id = None
    mock_run.execution_data = {}
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    # scalars().all() for role assignments → empty list
    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    # SD signoff query → None
    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "OPERATOR"


# ---------------------------------------------------------------------------
# assert_qau_independent — created_by_id conflict (CREATED_BY)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_rejects_creator():
    """QAU signer == run.created_by_id → QAU_NOT_INDEPENDENT / CREATED_BY."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()  # different user
    mock_run.created_by_id = signer_id
    mock_run.execution_data = {}
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "CREATED_BY"


# ---------------------------------------------------------------------------
# assert_qau_independent — step actor conflict (STEP_ACTOR)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_rejects_step_actor_started_by():
    """QAU signer appears in execution_data[*].started_by_user_id → STEP_ACTOR."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {
        "step-001": {
            "started_by_user_id": str(signer_id),
            "results": {},
        },
        "step-002": {"results": {}},
    }
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "STEP_ACTOR"


async def test_assert_qau_independent_rejects_step_actor_reviewed_by():
    """QAU signer appears in execution_data[*].reviewed_by_user_id → STEP_ACTOR."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {
        "step-001": {
            "reviewed_by_user_id": str(signer_id),
        },
    }
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "STEP_ACTOR"


# ---------------------------------------------------------------------------
# assert_qau_independent — lane assignment conflict (LANE_ASSIGNMENT)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_rejects_lane_assignment():
    """QAU signer appears in RunRoleAssignment → LANE_ASSIGNMENT."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {}
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignment = MagicMock()
    mock_assignment.user_id = signer_id

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = [mock_assignment]

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "LANE_ASSIGNMENT"


# ---------------------------------------------------------------------------
# assert_qau_independent — study director conflict (STUDY_DIRECTOR)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_rejects_study_director_on_run():
    """QAU signer is also active STUDY_DIRECTOR on the run → STUDY_DIRECTOR."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {}
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_row = MagicMock()
    mock_sd_row.signer_id = signer_id

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = mock_sd_row

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "STUDY_DIRECTOR"


# ---------------------------------------------------------------------------
# assert_qau_independent — protocol entity type
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_protocol_rejects_study_director():
    """Protocol QAU: signer is active STUDY_DIRECTOR on the protocol → rejected."""
    signer_id = uuid4()
    protocol_id = uuid4()

    mock_sd_row = MagicMock()
    mock_sd_row.signer_id = signer_id

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = mock_sd_row

    db = AsyncMock()
    db.execute.return_value = mock_sd_result

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="protocol",
            entity_id=protocol_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "STUDY_DIRECTOR"


async def test_assert_qau_independent_protocol_passes_unrelated_signer():
    """Protocol QAU: unrelated signer passes."""
    signer_id = uuid4()
    protocol_id = uuid4()

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.return_value = mock_sd_result

    # Should not raise
    await assert_qau_independent(
        db=db,
        entity_type="protocol",
        entity_id=protocol_id,
        signer_id=signer_id,
        role="QAU",
    )


# ---------------------------------------------------------------------------
# assert_qau_independent — run, completely clean signer passes
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_run_passes_unrelated_signer():
    """Run QAU: signer unrelated to any run actor → passes."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {
        "step-001": {
            "started_by_user_id": str(uuid4()),
            "reviewed_by_user_id": str(uuid4()),
        }
    }
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    # Should not raise
    await assert_qau_independent(
        db=db,
        entity_type="run",
        entity_id=run_id,
        signer_id=signer_id,
        role="QAU",
    )


# ---------------------------------------------------------------------------
# assert_qau_independent — execution_data UUID comparison (UUID vs str)
# ---------------------------------------------------------------------------


async def test_assert_qau_independent_step_actor_uuid_comparison():
    """execution_data keys may hold UUID objects; comparison must handle both."""
    signer_id = uuid4()
    run_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    # Store the UUID object (not string) to test coercion
    mock_run.execution_data = {
        "step-001": {"started_by_user_id": signer_id},
    }
    mock_run.protocol_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_assignments_result, mock_sd_result]

    with pytest.raises(HTTPException) as exc:
        await assert_qau_independent(
            db=db,
            entity_type="run",
            entity_id=run_id,
            signer_id=signer_id,
            role="QAU",
        )
    assert exc.value.detail["conflict_role"] == "STEP_ACTOR"
