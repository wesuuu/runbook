"""Unit tests for GLP sign-off cross-context validators."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.signoffs.validation import (
    SignoffPayload,
    assert_attestation_and_image_present,
    assert_qau_independent,
    validate_signoff_role_assignable,
)

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


async def test_assert_qau_independent_run_rejects_protocol_sd_signer():
    """QAU signer is also the active STUDY_DIRECTOR on the run's protocol →
    STUDY_DIRECTOR conflict.

    The SD sign-off lives on the protocol (pre-execution approval), NOT on
    the run.  Grilling decision #5, plan lines 4262-4263.
    """
    signer_id = uuid4()
    run_id = uuid4()
    protocol_id = uuid4()

    mock_run = MagicMock()
    mock_run.started_by_id = uuid4()
    mock_run.created_by_id = uuid4()
    mock_run.execution_data = {}
    mock_run.protocol_id = protocol_id  # run IS linked to a protocol

    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_run

    mock_assignments_result = MagicMock()
    mock_assignments_result.scalars.return_value.all.return_value = []

    # SD sign-off is on the PROTOCOL, not the run.
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


# ---------------------------------------------------------------------------
# validate_signoff_role_assignable
# ---------------------------------------------------------------------------


async def test_validate_signoff_role_assignable_passes_with_permission():
    """User has APPROVE on the protocol → QAU role is allowed."""
    user_id = uuid4()
    protocol_id = uuid4()

    with patch(
        "app.services.signoffs.validation.check_permission",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_check:
        await validate_signoff_role_assignable(
            db=AsyncMock(),
            entity_type="protocol",
            entity_id=protocol_id,
            user_id=user_id,
            role="QAU",
        )

    mock_check.assert_awaited_once()


async def test_validate_signoff_role_assignable_raises_403_without_permission():
    """User lacks APPROVE on the protocol → 403 ROLE_NOT_AUTHORIZED."""
    user_id = uuid4()
    protocol_id = uuid4()

    with patch(
        "app.services.signoffs.validation.check_permission",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with pytest.raises(HTTPException) as exc:
            await validate_signoff_role_assignable(
                db=AsyncMock(),
                entity_type="protocol",
                entity_id=protocol_id,
                user_id=user_id,
                role="STUDY_DIRECTOR",
            )

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "ROLE_NOT_AUTHORIZED"
    assert exc.value.detail["role"] == "STUDY_DIRECTOR"
    assert exc.value.detail["entity_type"] == "protocol"


async def test_validate_signoff_role_assignable_operator_checks_run_edit():
    """OPERATOR role checks EDIT on the run itself, not the protocol."""
    from app.models.iam import ObjectType, PermissionLevel

    user_id = uuid4()
    run_id = uuid4()

    captured_args: dict = {}

    async def fake_check_permission(
        db, user_id, object_type, object_id, required_level
    ):
        captured_args["object_type"] = object_type
        captured_args["object_id"] = object_id
        captured_args["required_level"] = required_level
        return True

    with patch(
        "app.services.signoffs.validation.check_permission",
        side_effect=fake_check_permission,
    ):
        mock_run = MagicMock()
        mock_run.protocol_id = uuid4()
        mock_run_result = MagicMock()
        mock_run_result.scalar_one.return_value = mock_run

        db = AsyncMock()
        db.execute.return_value = mock_run_result

        await validate_signoff_role_assignable(
            db=db,
            entity_type="run",
            entity_id=run_id,
            user_id=user_id,
            role="OPERATOR",
        )

    assert captured_args["object_type"] == ObjectType.RUN
    assert captured_args["object_id"] == run_id
    assert captured_args["required_level"] == PermissionLevel.EDIT


async def test_validate_signoff_role_assignable_sponsor_uses_project_admin():
    """SPONSOR role requires ADMIN on the project that owns the protocol."""
    from app.models.iam import ObjectType, PermissionLevel

    user_id = uuid4()
    protocol_id = uuid4()
    project_id = uuid4()

    captured_args: dict = {}

    async def fake_check_permission(
        db, user_id, object_type, object_id, required_level
    ):
        captured_args["object_type"] = object_type
        captured_args["object_id"] = object_id
        captured_args["required_level"] = required_level
        return True

    mock_proj_result = MagicMock()
    mock_proj_result.scalar_one_or_none.return_value = project_id

    db = AsyncMock()
    db.execute.return_value = mock_proj_result

    with patch(
        "app.services.signoffs.validation.check_permission",
        side_effect=fake_check_permission,
    ):
        await validate_signoff_role_assignable(
            db=db,
            entity_type="protocol",
            entity_id=protocol_id,
            user_id=user_id,
            role="SPONSOR",
        )

    assert captured_args["object_type"] == ObjectType.PROJECT
    assert captured_args["object_id"] == project_id
    assert captured_args["required_level"] == PermissionLevel.ADMIN
