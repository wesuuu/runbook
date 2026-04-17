"""Unit tests for batch_record_scoring (no LLM)."""

from tests.benchmarks.batch_record_scoring import (
    RunScoreDetails,
    RunScores,
    _fuzzy_match,
    _numeric_equal,
    _unit_equal,
)


def test_run_scores_defaults():
    s = RunScores(fixture_name="t")
    assert s.overall == 0.0
    assert not s.passed


def test_run_scores_perfect():
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
        timestamps=1.0,
        signatures=1.0,
        deviations=1.0,
        na_correctness=1.0,
        notes_preservation=1.0,
        run_metadata=1.0,
    )
    assert s.overall == 1.0
    assert s.passed


def test_run_scores_weighted_sum():
    # step_completeness 20% + param_accuracy 25% = 45%
    s = RunScores(
        fixture_name="t",
        step_completeness=1.0,
        param_accuracy=1.0,
    )
    assert abs(s.overall - 0.45) < 1e-6


def test_fuzzy_match_aliased():
    assert _fuzzy_match("Buffer Prep", "buffer prep") == 1.0


def test_numeric_equal():
    assert _numeric_equal(100.0, 104.9)
    assert not _numeric_equal(100.0, 110.0)
    assert _numeric_equal(7.00, 7.01)
    assert not _numeric_equal(7.00, 7.05)


def test_unit_equal():
    assert _unit_equal("°C", "C")
    assert _unit_equal("μm", "um")
    assert not _unit_equal("g", "mg")
    assert _unit_equal(None, None)
    assert not _unit_equal("mL", None)
