"""Sanity checks on the drafted legal content. These tests validate that
the documents include the load-bearing sections required by the spec —
not the prose itself, which is reviewed in PR diffs.
"""

from app.legal import service as legal_service
from app.legal.versions import CURRENT_VERSION


def test_terms_contains_required_sections():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    required = [
        "Research Use Only",  # RUO designation
        "21 CFR 820",         # FDA medical device reference
        "Protected Health Information",  # HIPAA section
        "45 CFR 160.103",     # HIPAA citation
        "Business Associate", # BAA disclaimer
        "Limitation of Liability",
        "Governing Law",
        "California",         # governing law state
        "legal@batchrite.com",
    ]
    for needle in required:
        assert needle in terms, f"Terms missing required section/phrase: {needle!r}"


def test_privacy_contains_required_sections():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    required = [
        "Information We Collect",
        "AI",                  # AI processing disclosure
        "Cookies",
        "Retention",
        "Your Rights",
        "do not use customer data to train",  # AI training commitment
        "privacy@batchrite.com",
    ]
    for needle in required:
        assert needle in privacy, f"Privacy missing required section/phrase: {needle!r}"


def test_terms_has_version_header():
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "**Version:** 2026-04-27" in terms
    assert "**Effective Date:** 2026-04-27" in terms


def test_privacy_has_version_header():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    assert "**Version:** 2026-04-27" in privacy
    assert "**Effective Date:** 2026-04-27" in privacy


def test_terms_includes_counsel_todo_marker():
    """Source-only marker so future-us remembers to involve counsel."""
    terms = legal_service.get_document(CURRENT_VERSION, "terms")["markdown"]
    assert "TODO: Have counsel review" in terms


def test_privacy_includes_counsel_todo_marker():
    privacy = legal_service.get_document(CURRENT_VERSION, "privacy")["markdown"]
    assert "TODO: Have counsel review" in privacy
