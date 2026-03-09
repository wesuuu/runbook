"""Unit tests for dashboard completion trend computation."""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from app.api.endpoints.dashboard import _compute_completion_trend


def _make_run(status: str, updated_at: datetime):
    return SimpleNamespace(status=status, updated_at=updated_at)


def test_trend_counts_completed_runs():
    now = datetime.now(timezone.utc)
    runs = [
        _make_run("COMPLETED", now),
        _make_run("COMPLETED", now),
        _make_run("EDITED", now),
        _make_run("ACTIVE", now),  # should be excluded
        _make_run("PLANNED", now),  # should be excluded
    ]
    trend = _compute_completion_trend(runs, days=7)
    assert len(trend) == 7
    # Today should have 3 (2 COMPLETED + 1 EDITED)
    assert trend[-1].count == 3
    # Other days should be 0
    for item in trend[:-1]:
        assert item.count == 0


def test_trend_spans_correct_days():
    now = datetime.now(timezone.utc)
    trend = _compute_completion_trend([], days=7)
    assert len(trend) == 7
    # First entry should be 6 days ago, last should be today
    expected_first = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    expected_last = now.strftime("%Y-%m-%d")
    assert trend[0].date == expected_first
    assert trend[-1].date == expected_last


def test_trend_14_days():
    now = datetime.now(timezone.utc)
    runs = [
        _make_run("COMPLETED", now - timedelta(days=10)),
    ]
    trend = _compute_completion_trend(runs, days=14)
    assert len(trend) == 14
    # The run 10 days ago should appear in the correct bucket
    target_date = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    matching = [t for t in trend if t.date == target_date]
    assert len(matching) == 1
    assert matching[0].count == 1


def test_trend_excludes_runs_outside_window():
    now = datetime.now(timezone.utc)
    runs = [
        _make_run("COMPLETED", now - timedelta(days=30)),  # outside 7-day window
    ]
    trend = _compute_completion_trend(runs, days=7)
    assert all(t.count == 0 for t in trend)


def test_trend_handles_none_updated_at():
    runs = [
        _make_run("COMPLETED", None),
    ]
    trend = _compute_completion_trend(runs, days=7)
    assert all(t.count == 0 for t in trend)


def test_trend_distributes_across_days():
    now = datetime.now(timezone.utc)
    runs = [
        _make_run("COMPLETED", now),
        _make_run("COMPLETED", now - timedelta(days=1)),
        _make_run("COMPLETED", now - timedelta(days=1)),
        _make_run("COMPLETED", now - timedelta(days=3)),
    ]
    trend = _compute_completion_trend(runs, days=7)
    assert trend[-1].count == 1  # today
    assert trend[-2].count == 2  # yesterday
    assert trend[-4].count == 1  # 3 days ago
