"""Pure license-compatibility classifier (F-0090)."""

import pytest

from app.services.ai.subagents.protocol_knowledgebase.licenses import (
    classify_license,
)


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("CC0 1.0", "CC0"),
        ("CC BY 4.0", "CC-BY"),
        ("CC-BY-SA 3.0", "CC-BY-SA"),
        ("public domain", "PUBLIC-DOMAIN"),
    ],
)
def test_import_safe_licenses_allowed(raw, normalized):
    v = classify_license(raw)
    assert v.import_allowed is True
    assert v.normalized == normalized
    assert v.reason


@pytest.mark.parametrize(
    "raw", ["CC BY-NC 4.0", "CC-BY-ND 4.0", "CC BY-NC-ND 4.0"]
)
def test_nc_and_nd_licenses_blocked(raw):
    v = classify_license(raw)
    assert v.import_allowed is False
    assert v.reason


@pytest.mark.parametrize("raw", [None, "", "   ", "All rights reserved", "MIT"])
def test_unknown_or_empty_fails_closed(raw):
    v = classify_license(raw)
    assert v.import_allowed is False
    assert v.normalized == "UNKNOWN"


def test_normalization_strips_version_not_cc0_zero():
    # The "0" in CC0 is part of the name, not a version number.
    assert classify_license("CC0 1.0").normalized == "CC0"
