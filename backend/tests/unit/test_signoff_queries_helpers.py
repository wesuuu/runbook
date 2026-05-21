"""Unit tests for pure helpers in services/signoffs/queries.py."""

from __future__ import annotations

from app.services.signoffs.queries import missing_signoff_roles


def test_operator_always_required():
    assert missing_signoff_roles(set(), {}) == ["OPERATOR"]
    assert missing_signoff_roles({"OPERATOR"}, {}) == []


def test_study_director_gated_by_flag():
    glp = {"require_study_director": True}
    assert missing_signoff_roles({"OPERATOR"}, glp) == ["STUDY_DIRECTOR"]
    assert missing_signoff_roles({"OPERATOR", "STUDY_DIRECTOR"}, glp) == []
    # flag off → not required even when absent
    assert missing_signoff_roles({"OPERATOR"}, {}) == []


def test_qau_gated_by_flag():
    glp = {"require_qau": True}
    assert missing_signoff_roles({"OPERATOR"}, glp) == ["QAU"]
    assert missing_signoff_roles({"OPERATOR", "QAU"}, glp) == []


def test_all_three_missing_preserves_order():
    glp = {"require_study_director": True, "require_qau": True}
    assert missing_signoff_roles(set(), glp) == [
        "OPERATOR",
        "STUDY_DIRECTOR",
        "QAU",
    ]
