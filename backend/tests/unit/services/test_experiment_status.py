"""Unit tests for F-0093 lifecycle-status derivation."""

from types import SimpleNamespace

from app.services.experiments.status import (
    derive_lifecycle_status,
    lifecycle_counts_from_runs,
)


def _run(status: str):
    return SimpleNamespace(id="r", status=status)


def test_no_runs_is_draft():
    assert derive_lifecycle_status("DRAFT", live_run_count=0, open_run_count=0) == "DRAFT"


def test_all_live_runs_completed_is_complete():
    # No lock → AWAITING_CONCLUSION (was COMPLETE before F-0043 widening).
    assert (
        derive_lifecycle_status("DRAFT", live_run_count=3, open_run_count=0)
        == "AWAITING_CONCLUSION"
    )
    # With lock → COMPLETE (the previous semantic, now gated on the lock).
    assert (
        derive_lifecycle_status("DRAFT", live_run_count=3, open_run_count=0, conclusion_locked=True)
        == "COMPLETE"
    )


def test_mixed_runs_is_in_progress():
    assert (
        derive_lifecycle_status("DRAFT", live_run_count=3, open_run_count=1)
        == "IN_PROGRESS"
    )


def test_archived_experiment_short_circuits():
    assert (
        derive_lifecycle_status("ARCHIVED", live_run_count=3, open_run_count=0)
        == "ARCHIVED"
    )


def test_counts_exclude_archived_runs():
    # 1 COMPLETED + 2 ARCHIVED -> 1 live, 0 open -> AWAITING_CONCLUSION (no lock).
    live, open_ = lifecycle_counts_from_runs(
        [_run("COMPLETED"), _run("ARCHIVED"), _run("ARCHIVED")]
    )
    assert (live, open_) == (1, 0)
    # No lock → AWAITING_CONCLUSION (was COMPLETE before F-0043 widening).
    assert derive_lifecycle_status("DRAFT", live, open_) == "AWAITING_CONCLUSION"
    # With lock → COMPLETE (the previous semantic, now gated on the lock).
    assert derive_lifecycle_status("DRAFT", live, open_, conclusion_locked=True) == "COMPLETE"


def test_only_archived_runs_is_draft_never_complete():
    live, open_ = lifecycle_counts_from_runs([_run("ARCHIVED"), _run("ARCHIVED")])
    assert (live, open_) == (0, 0)
    assert derive_lifecycle_status("DRAFT", live, open_) == "DRAFT"


def test_edited_run_counts_as_open():
    live, open_ = lifecycle_counts_from_runs([_run("COMPLETED"), _run("EDITED")])
    assert (live, open_) == (2, 1)
    assert derive_lifecycle_status("DRAFT", live, open_) == "IN_PROGRESS"


def test_unknown_run_status_counts_as_open_and_does_not_raise():
    live, open_ = lifecycle_counts_from_runs([_run("WAT")])
    assert (live, open_) == (1, 1)
    assert derive_lifecycle_status("DRAFT", live, open_) == "IN_PROGRESS"


def test_accepts_enum_experiment_status():
    """`derive_lifecycle_status` tolerates an (str, Enum) status, not just str."""
    from app.schemas.runs import ExperimentStatus

    assert (
        derive_lifecycle_status(
            ExperimentStatus.ARCHIVED, live_run_count=2, open_run_count=0
        )
        == "ARCHIVED"
    )
    # No lock → AWAITING_CONCLUSION (was COMPLETE before F-0043 widening).
    assert (
        derive_lifecycle_status(
            ExperimentStatus.DRAFT, live_run_count=2, open_run_count=0
        )
        == "AWAITING_CONCLUSION"
    )
    # With lock → COMPLETE (the previous semantic, now gated on the lock).
    assert (
        derive_lifecycle_status(
            ExperimentStatus.DRAFT, live_run_count=2, open_run_count=0, conclusion_locked=True
        )
        == "COMPLETE"
    )
