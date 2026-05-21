"""§58.35 independence of a protocol's designated SD and QAU reviewers.

``assert_glp_settings_reviewers_independent`` reads a protocol's
``glpSettings`` block and blocks designating one person as both Study
Director and QAU (F-0080) — the protocol-side equivalent of
``assert_reviewers_independent``, which guards the run reviewer endpoints.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.services.signoffs.validation import (
    assert_glp_settings_reviewers_independent,
)


def test_same_sd_and_qau_user_rejected():
    """SPECIFIC_USER QAU equal to the Study Director → 400 QAU_NOT_INDEPENDENT."""
    uid = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        assert_glp_settings_reviewers_independent(
            {
                "require_study_director": True,
                "require_qau": True,
                "qau_mode": "SPECIFIC_USER",
                "study_director_user_id": uid,
                "qau_user_id": uid,
            }
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "QAU_NOT_INDEPENDENT"
    assert exc.value.detail["conflict_role"] == "STUDY_DIRECTOR"


def test_distinct_sd_and_qau_users_allowed():
    """Distinct designees → no raise."""
    assert_glp_settings_reviewers_independent(
        {
            "require_study_director": True,
            "require_qau": True,
            "qau_mode": "SPECIFIC_USER",
            "study_director_user_id": str(uuid.uuid4()),
            "qau_user_id": str(uuid.uuid4()),
        }
    )


def test_any_org_qau_mode_not_statically_checked():
    """ANY_ORG_QAU resolves the pool with the SD excluded at sign time, so
    pool mode is not blocked here even if the SD id is echoed in qau_user_id."""
    uid = str(uuid.uuid4())
    assert_glp_settings_reviewers_independent(
        {
            "require_study_director": True,
            "require_qau": True,
            "qau_mode": "ANY_ORG_QAU",
            "study_director_user_id": uid,
            "qau_user_id": uid,
        }
    )


def test_qau_not_required_allowed():
    """If QAU isn't required there is no pairing to conflict."""
    uid = str(uuid.uuid4())
    assert_glp_settings_reviewers_independent(
        {
            "require_study_director": True,
            "require_qau": False,
            "qau_mode": "SPECIFIC_USER",
            "study_director_user_id": uid,
            "qau_user_id": uid,
        }
    )


def test_partial_designation_allowed():
    """Both roles required but only one designee set → nothing to compare."""
    assert_glp_settings_reviewers_independent(
        {
            "require_study_director": True,
            "require_qau": True,
            "qau_mode": "SPECIFIC_USER",
            "study_director_user_id": str(uuid.uuid4()),
        }
    )


def test_missing_or_empty_glp_settings_allowed():
    """None / empty / non-dict glpSettings → no raise."""
    assert_glp_settings_reviewers_independent(None)
    assert_glp_settings_reviewers_independent({})
    assert_glp_settings_reviewers_independent("not-a-dict")  # type: ignore[arg-type]
