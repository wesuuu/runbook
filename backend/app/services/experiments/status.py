"""F-0093 + F-0043 — read-time lifecycle derivation for experiments."""

import logging

from app.schemas.runs import RunStatus

logger = logging.getLogger(__name__)

LIFECYCLE_DRAFT = "DRAFT"
LIFECYCLE_IN_PROGRESS = "IN_PROGRESS"
LIFECYCLE_AWAITING_CONCLUSION = "AWAITING_CONCLUSION"
LIFECYCLE_COMPLETE = "COMPLETE"
LIFECYCLE_ARCHIVED = "ARCHIVED"

_KNOWN_RUN_STATUSES = {s.value for s in RunStatus}


def derive_lifecycle_status(
    experiment_status: str,
    live_run_count: int,
    open_run_count: int,
    conclusion_locked: bool = False,
) -> str:
    """Derive an experiment's lifecycle status.

    Five-state machine: DRAFT -> IN_PROGRESS -> AWAITING_CONCLUSION -> COMPLETE
    with ARCHIVED as an orthogonal terminal. `conclusion_locked` defaults to
    False so legacy callers default to the conservative AWAITING_CONCLUSION
    rather than silently claiming COMPLETE.

    Never raises — runs on every experiment read, including the org-wide list.
    """
    status = (
        experiment_status
        if isinstance(experiment_status, str)
        else getattr(experiment_status, "value", str(experiment_status))
    )
    if status == LIFECYCLE_ARCHIVED:
        return LIFECYCLE_ARCHIVED
    if live_run_count <= 0:
        return LIFECYCLE_DRAFT
    if open_run_count > 0:
        return LIFECYCLE_IN_PROGRESS
    if not conclusion_locked:
        return LIFECYCLE_AWAITING_CONCLUSION
    return LIFECYCLE_COMPLETE


def lifecycle_counts_from_runs(runs) -> tuple[int, int]:
    """Return ``(live_run_count, open_run_count)`` from run-like objects."""
    live = 0
    open_ = 0
    for run in runs:
        raw = run.status
        status = raw if isinstance(raw, str) else getattr(raw, "value", str(raw))
        if status == "ARCHIVED":
            continue
        live += 1
        if status != "COMPLETED":
            open_ += 1
            if status not in _KNOWN_RUN_STATUSES:
                logger.warning(
                    "Unknown run status %r on run %s — counted as open",
                    status,
                    getattr(run, "id", "?"),
                )
    return live, open_
