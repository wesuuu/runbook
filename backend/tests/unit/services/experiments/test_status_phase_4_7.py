"""F-0043 — 5-state lifecycle with conclusion lock."""

from app.services.experiments.status import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_AWAITING_CONCLUSION,
    LIFECYCLE_COMPLETE,
    LIFECYCLE_DRAFT,
    LIFECYCLE_IN_PROGRESS,
    derive_lifecycle_status,
)


def test_archived_overrides_everything():
    assert derive_lifecycle_status("ARCHIVED", 3, 1, conclusion_locked=True) == LIFECYCLE_ARCHIVED


def test_draft_when_no_live_runs():
    assert derive_lifecycle_status("DRAFT", 0, 0, conclusion_locked=False) == LIFECYCLE_DRAFT


def test_in_progress_when_any_open():
    assert derive_lifecycle_status("DRAFT", 3, 1, conclusion_locked=False) == LIFECYCLE_IN_PROGRESS


def test_awaiting_conclusion_when_all_terminal_unlocked():
    assert (
        derive_lifecycle_status("DRAFT", 3, 0, conclusion_locked=False)
        == LIFECYCLE_AWAITING_CONCLUSION
    )


def test_complete_when_all_terminal_locked():
    assert (
        derive_lifecycle_status("DRAFT", 3, 0, conclusion_locked=True)
        == LIFECYCLE_COMPLETE
    )


def test_default_conclusion_locked_is_false():
    # Backwards-compat for callers not yet updated.
    assert (
        derive_lifecycle_status("DRAFT", 3, 0) == LIFECYCLE_AWAITING_CONCLUSION
    )


def test_admin_unlock_returns_to_awaiting():
    # Same row, lock toggled off, lifecycle drops back to AWAITING.
    assert (
        derive_lifecycle_status("DRAFT", 3, 0, conclusion_locked=False)
        == LIFECYCLE_AWAITING_CONCLUSION
    )
