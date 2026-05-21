"""Unit tests for services/runs/validation.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.runs.validation import (
    assert_can_edit_completed_run,
    assert_can_reopen,
    assert_no_unjustified_edit_errors,
    assert_run_can_close,
    lane_assignment_gap,
)

# ---------------------------------------------------------------------------
# assert_no_unjustified_edit_errors
# ---------------------------------------------------------------------------


def test_assert_no_unjustified_edit_errors_passes_when_all_reasoned():
    delta = {
        "step1": {"value": 42, "edit_reason": "calibration drift"},
        "step2": {"value": 7, "edit_reason": "unit conversion"},
    }
    assert_no_unjustified_edit_errors(delta)


def test_assert_no_unjustified_edit_errors_fails_on_missing_reason():
    delta = {
        "step1": {"value": 42},  # missing edit_reason
        "step2": {"value": 7, "edit_reason": "fine"},
    }
    with pytest.raises(HTTPException) as exc:
        assert_no_unjustified_edit_errors(delta)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "EDIT_REASON_REQUIRED"
    assert exc.value.detail["issues"] == [{"step_id": "step1"}]


def test_assert_no_unjustified_edit_errors_fails_on_blank_reason():
    delta = {"step1": {"value": 42, "edit_reason": "  "}}
    with pytest.raises(HTTPException) as exc:
        assert_no_unjustified_edit_errors(delta)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "EDIT_REASON_REQUIRED"
    assert exc.value.detail["issues"] == [{"step_id": "step1"}]


def test_assert_no_unjustified_edit_errors_collects_all_missing():
    """All steps missing edit_reason are reported, not just the first."""
    delta = {
        "step1": {"value": 1},
        "step2": {"value": 2},
        "step3": {"value": 3, "edit_reason": "ok"},
    }
    with pytest.raises(HTTPException) as exc:
        assert_no_unjustified_edit_errors(delta)
    issues = exc.value.detail["issues"]
    step_ids = {i["step_id"] for i in issues}
    assert step_ids == {"step1", "step2"}


def test_assert_no_unjustified_edit_errors_passes_on_empty_delta():
    """Empty delta is trivially valid."""
    assert_no_unjustified_edit_errors({})


# ---------------------------------------------------------------------------
# assert_can_edit_completed_run
# ---------------------------------------------------------------------------


async def test_assert_can_edit_completed_run_passes_for_non_completed():
    """Non-COMPLETED runs are always editable — no signoff check needed."""
    mock_run = MagicMock()
    mock_run.status = "ACTIVE"
    # If it tried to query DB it would fail on a plain MagicMock
    await assert_can_edit_completed_run(db=MagicMock(), run=mock_run)


async def test_assert_can_edit_completed_run_passes_when_no_active_signoffs():
    """COMPLETED run with zero active signoffs can be edited."""
    mock_run = MagicMock()
    mock_run.status = "COMPLETED"
    mock_run.id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute.return_value = mock_result

    # Should not raise
    await assert_can_edit_completed_run(db=db, run=mock_run)


async def test_assert_can_edit_completed_run_raises_when_active_signoffs():
    """COMPLETED run with active signoffs requires reopen before edit."""
    mock_run = MagicMock()
    mock_run.status = "COMPLETED"
    mock_run.id = uuid4()

    mock_signoff = MagicMock()
    mock_signoff.role = "OPERATOR"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_signoff]

    db = AsyncMock()
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await assert_can_edit_completed_run(db=db, run=mock_run)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "RUN_IMMUTABLE_REOPEN_REQUIRED"
    assert "OPERATOR" in exc.value.detail["active_roles"]


async def test_assert_can_edit_completed_run_passes_for_edited_status():
    """EDITED status (reopen already done) does not block further edits."""
    mock_run = MagicMock()
    mock_run.status = "EDITED"
    mock_run.id = uuid4()

    # Should not even query DB
    await assert_can_edit_completed_run(db=MagicMock(), run=mock_run)


# ---------------------------------------------------------------------------
# assert_run_can_close
# ---------------------------------------------------------------------------


async def test_assert_run_can_close_passes_for_basic_run():
    """A basic (non-GLP) run enables no reviewer role, so it closes with no
    sign-off gate at all — not even OPERATOR (#18)."""
    mock_run = MagicMock()
    mock_run.id = uuid4()

    db = AsyncMock()

    # Neither require_* flag set → basic run, returns before any DB query.
    await assert_run_can_close(db=db, run=mock_run, glp_settings={})
    await assert_run_can_close(
        db=db,
        run=mock_run,
        glp_settings={"require_study_director": False, "require_qau": False},
    )
    db.execute.assert_not_called()


async def test_assert_run_can_close_requires_operator_on_glp_run():
    """A GLP run (a reviewer role is required) always needs OPERATOR (#18).

    With ``require_study_director`` set and no sign-offs at all, both the
    always-required OPERATOR and the gated STUDY_DIRECTOR are reported.
    """
    mock_run = MagicMock()
    mock_run.id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # no signoffs

    db = AsyncMock()
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await assert_run_can_close(
            db=db,
            run=mock_run,
            glp_settings={"require_study_director": True},
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "SIGNOFF_REQUIRED"
    assert set(exc.value.detail["missing_roles"]) == {
        "OPERATOR",
        "STUDY_DIRECTOR",
    }


async def test_assert_run_can_close_passes_when_glp_run_fully_signed():
    """GLP run requiring SD: OPERATOR + SD signed → passes."""
    mock_run = MagicMock()
    mock_run.id = uuid4()

    op_signoff = MagicMock()
    op_signoff.role = "OPERATOR"
    sd_signoff = MagicMock()
    sd_signoff.role = "STUDY_DIRECTOR"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [op_signoff, sd_signoff]

    db = AsyncMock()
    db.execute.return_value = mock_result

    # Should not raise
    await assert_run_can_close(
        db=db, run=mock_run, glp_settings={"require_study_director": True}
    )


async def test_assert_run_can_close_fails_when_sd_required_but_missing():
    """require_study_director=True, only OPERATOR signed → SD reported missing."""
    mock_run = MagicMock()
    mock_run.id = uuid4()

    op_signoff = MagicMock()
    op_signoff.role = "OPERATOR"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [op_signoff]

    db = AsyncMock()
    db.execute.return_value = mock_result

    glp_settings = {"require_study_director": True}

    with pytest.raises(HTTPException) as exc:
        await assert_run_can_close(db=db, run=mock_run, glp_settings=glp_settings)
    assert exc.value.status_code == 400
    assert "STUDY_DIRECTOR" in exc.value.detail["missing_roles"]
    assert "OPERATOR" not in exc.value.detail["missing_roles"]


async def test_assert_run_can_close_fails_when_qau_required_but_missing():
    """require_qau=True, only OPERATOR signed → QAU reported missing."""
    mock_run = MagicMock()
    mock_run.id = uuid4()

    op_signoff = MagicMock()
    op_signoff.role = "OPERATOR"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [op_signoff]

    db = AsyncMock()
    db.execute.return_value = mock_result

    glp_settings = {"require_qau": True}

    with pytest.raises(HTTPException) as exc:
        await assert_run_can_close(db=db, run=mock_run, glp_settings=glp_settings)
    assert "QAU" in exc.value.detail["missing_roles"]


async def test_assert_run_can_close_passes_when_all_required_present():
    """All required roles present → passes cleanly."""
    mock_run = MagicMock()
    mock_run.id = uuid4()

    op_signoff = MagicMock()
    op_signoff.role = "OPERATOR"
    sd_signoff = MagicMock()
    sd_signoff.role = "STUDY_DIRECTOR"
    qau_signoff = MagicMock()
    qau_signoff.role = "QAU"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        op_signoff,
        sd_signoff,
        qau_signoff,
    ]

    db = AsyncMock()
    db.execute.return_value = mock_result

    glp_settings = {
        "require_study_director": True,
        "require_qau": True,
    }
    # Should not raise
    await assert_run_can_close(db=db, run=mock_run, glp_settings=glp_settings)


# ---------------------------------------------------------------------------
# lane_assignment_gap
# ---------------------------------------------------------------------------


def _assignment(lane_id: str):
    a = MagicMock()
    a.lane_node_id = lane_id
    a.user_id = uuid4()
    return a


def test_lane_gap_no_assignees_no_swimlanes_blocks():
    gap = lane_assignment_gap({"nodes": []}, [])
    assert gap.has_assignee is False
    assert gap.unassigned_lane_ids == []
    assert gap.is_blocking is True


def test_lane_gap_assignee_no_swimlanes_is_ready():
    gap = lane_assignment_gap({"nodes": []}, [_assignment("lane-x")])
    assert gap.has_assignee is True
    assert gap.unassigned_lane_ids == []
    assert gap.is_blocking is False


def test_lane_gap_partial_swimlane_assignment_blocks():
    graph = {
        "nodes": [
            {"id": "lane-a", "type": "swimLane"},
            {"id": "lane-b", "type": "swimLane"},
        ]
    }
    gap = lane_assignment_gap(graph, [_assignment("lane-a")])
    assert gap.has_assignee is True
    assert gap.unassigned_lane_ids == ["lane-b"]
    assert gap.is_blocking is True


def test_lane_gap_all_swimlanes_assigned_is_ready():
    graph = {
        "nodes": [
            {"id": "lane-a", "type": "swimLane"},
            {"id": "lane-b", "type": "swimLane"},
        ]
    }
    gap = lane_assignment_gap(
        graph, [_assignment("lane-a"), _assignment("lane-b")]
    )
    assert gap.unassigned_lane_ids == []
    assert gap.is_blocking is False


def test_lane_gap_stale_assignment_to_deleted_lane_blocks():
    # Mirrors the live gate's set-equality check: an assignment pointing at a
    # lane_node_id that is not a swimlane in the current graph still blocks.
    graph = {
        "nodes": [
            {"id": "lane-a", "type": "swimLane"},
            {"id": "lane-b", "type": "swimLane"},
        ]
    }
    gap = lane_assignment_gap(
        graph,
        [
            _assignment("lane-a"),
            _assignment("lane-b"),
            _assignment("lane-gone"),
        ],
    )
    assert gap.unassigned_lane_ids == []
    assert gap.stale_lane_ids == ["lane-gone"]
    assert gap.is_blocking is True


def test_lane_gap_tolerates_empty_graph():
    gap = lane_assignment_gap({}, [])
    assert gap.is_blocking is True


# ---------------------------------------------------------------------------
# assert_can_reopen
# ---------------------------------------------------------------------------


async def test_assert_can_reopen_allows_org_admin():
    """Org admin membership → always allowed to reopen."""
    user_id = uuid4()
    run_id = uuid4()
    org_id = uuid4()
    project_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.project_id = project_id
    mock_run.outcome = None

    mock_user = MagicMock()
    mock_user.id = user_id

    # DB query: project → org_id
    mock_proj_result = MagicMock()
    mock_proj_result.scalar_one_or_none.return_value = org_id

    # DB query: org membership with ADMIN role
    mock_membership = MagicMock()
    mock_membership.roles = ["ADMIN", "MEMBER"]

    mock_member_result = MagicMock()
    mock_member_result.scalar_one_or_none.return_value = mock_membership

    db = AsyncMock()
    db.execute.side_effect = [mock_proj_result, mock_member_result]

    # Should not raise
    await assert_can_reopen(db=db, run=mock_run, user=mock_user)


async def test_assert_can_reopen_allows_project_admin():
    """User with ADMIN permission on the project can reopen (acts as project lead)."""
    from unittest.mock import patch

    user_id = uuid4()
    run_id = uuid4()
    org_id = uuid4()
    project_id = uuid4()
    protocol_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.project_id = project_id
    # Explicit protocol_id so we can control the SD signoff query result.
    mock_run.protocol_id = protocol_id
    mock_run.outcome = None

    mock_user = MagicMock()
    mock_user.id = user_id

    # DB query 1: project → org_id
    mock_proj_result = MagicMock()
    mock_proj_result.scalar_one_or_none.return_value = org_id

    # DB query 2: org membership with no ADMIN role
    mock_membership = MagicMock()
    mock_membership.roles = ["MEMBER"]
    mock_member_result = MagicMock()
    mock_member_result.scalar_one_or_none.return_value = mock_membership

    # DB query 3: SD signoff on protocol → no match (user is not SD)
    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_proj_result, mock_member_result, mock_sd_result]

    with patch(
        "app.services.runs.validation.check_permission",
        new_callable=AsyncMock,
        return_value=True,  # user has project ADMIN
    ):
        # Should not raise
        await assert_can_reopen(db=db, run=mock_run, user=mock_user)


async def test_assert_can_reopen_rejects_unauthorized():
    """Regular org member without project ADMIN → REOPEN_NOT_AUTHORIZED."""
    from unittest.mock import patch

    user_id = uuid4()
    run_id = uuid4()
    org_id = uuid4()
    project_id = uuid4()
    protocol_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.project_id = project_id
    mock_run.protocol_id = protocol_id
    mock_run.outcome = None

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_proj_result = MagicMock()
    mock_proj_result.scalar_one_or_none.return_value = org_id

    mock_membership = MagicMock()
    mock_membership.roles = ["MEMBER"]
    mock_member_result = MagicMock()
    mock_member_result.scalar_one_or_none.return_value = mock_membership

    # SD signoff on protocol → no match (user is not SD)
    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [mock_proj_result, mock_member_result, mock_sd_result]

    with patch(
        "app.services.runs.validation.check_permission",
        new_callable=AsyncMock,
        return_value=False,  # does NOT have project ADMIN
    ):
        with pytest.raises(HTTPException) as exc:
            await assert_can_reopen(db=db, run=mock_run, user=mock_user)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "REOPEN_NOT_AUTHORIZED"


async def test_assert_can_reopen_allows_sd_with_protocol_signoff():
    """User who is the active STUDY_DIRECTOR signer on the run's protocol can reopen."""
    user_id = uuid4()
    run_id = uuid4()
    org_id = uuid4()
    project_id = uuid4()
    protocol_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.project_id = project_id
    mock_run.protocol_id = protocol_id
    mock_run.outcome = None

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_proj_result = MagicMock()
    mock_proj_result.scalar_one_or_none.return_value = org_id

    # Not an org admin
    mock_membership = MagicMock()
    mock_membership.roles = ["MEMBER"]

    mock_member_result = MagicMock()
    mock_member_result.scalar_one_or_none.return_value = mock_membership

    # SD signoff on the protocol
    mock_sd_row = MagicMock()
    mock_sd_row.signer_id = user_id

    mock_sd_result = MagicMock()
    mock_sd_result.scalar_one_or_none.return_value = mock_sd_row

    db = AsyncMock()
    db.execute.side_effect = [mock_proj_result, mock_member_result, mock_sd_result]

    # Should not raise — SD identity grants reopen
    await assert_can_reopen(db=db, run=mock_run, user=mock_user)
