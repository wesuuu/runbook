"""Unit tests for the GlpSignoff data model and its enums."""

from datetime import date

from sqlalchemy import Date

from app.models.science import (Equipment, GlpRole, GlpSignoffAction, Run,
                                RunOutcome)


def test_glp_role_values():
    assert GlpRole.SPONSOR == "SPONSOR"
    assert GlpRole.STUDY_DIRECTOR == "STUDY_DIRECTOR"
    assert GlpRole.QAU == "QAU"
    assert GlpRole.OPERATOR == "OPERATOR"
    assert {r.value for r in GlpRole} == {
        "SPONSOR",
        "STUDY_DIRECTOR",
        "QAU",
        "OPERATOR",
    }


def test_glp_signoff_action_values():
    assert {a.value for a in GlpSignoffAction} == {
        "APPROVED",
        "REJECTED",
        "REQUESTED_CHANGES",
    }


def test_run_has_glp_columns():
    cols = {c.name for c in Run.__table__.columns}
    assert "started_at" in cols
    assert "completed_at" in cols
    assert "outcome" in cols
    assert "outcome_notes" in cols


def test_run_outcome_values():
    assert {o.value for o in RunOutcome} == {
        "COMPLETED_NORMAL",
        "COMPLETED_WITH_DEVIATIONS",
        "ABORTED",
    }


def test_run_outcome_index_exists():
    """ix_runs_outcome index for QAU audit queries (grilling decision #14)."""
    idx_names = {i.name for i in Run.__table__.indexes}
    assert "ix_runs_outcome" in idx_names


def test_equipment_has_calibration_columns():
    cols = {c.name for c in Equipment.__table__.columns}
    assert "serial_number" in cols
    assert "last_calibration_date" in cols
    assert "next_calibration_date" in cols
    assert "calibration_certificate_path" in cols


def test_equipment_calibration_columns_are_date_not_datetime():
    cols = {c.name: c for c in Equipment.__table__.columns}
    assert isinstance(cols["last_calibration_date"].type, Date)
    assert isinstance(cols["next_calibration_date"].type, Date)
