"""Unit tests for the GlpSignoff data model and its enums."""

from sqlalchemy import Date

from app.models.equipment import Equipment
from app.models.runs import Run, RunOutcome
from app.models.signoffs import GlpRole, GlpSignoff, GlpSignoffAction


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


def test_glp_signoff_has_expected_columns():
    cols = {c.name for c in GlpSignoff.__table__.columns}
    expected = {
        "id",
        "created_at",
        "updated_at",
        "protocol_id",
        "run_id",
        "role",
        "action",
        "signer_id",
        "attestation",
        "signed_at",
        "signature_image_path",
        "signoff_request_id",
        "invalidated_at",
        "invalidated_reason",
        "invalidated_by_id",
        "superseded_by_reopen_audit_event_id",
    }
    missing = expected - cols
    assert not missing, f"Missing columns: {missing}"


def test_glp_signoff_has_scope_check_constraint():
    names = {c.name for c in GlpSignoff.__table__.constraints if c.name}
    assert "ck_glp_signoff_scope" in names
    assert "ck_glp_signoff_role" in names
    assert "ck_glp_signoff_action" in names
    assert "ck_protocol_signoff_roles" in names
    assert "ck_run_signoff_roles" in names
    assert "ck_approved_requires_attestation" in names


def test_glp_signoff_has_partial_unique_indexes():
    idx_names = {idx.name for idx in GlpSignoff.__table__.indexes}
    assert "ux_glp_signoff_active_protocol" in idx_names
    assert "ux_glp_signoff_active_run" in idx_names
