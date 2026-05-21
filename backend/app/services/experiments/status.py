"""F-0093 — read-time lifecycle-status derivation for experiments.

Lifecycle status is never stored; it is derived from child-run counts on
every read. `derive_lifecycle_status` is count-based (not run-list-based) so
the org-wide index can feed it uncapped SQL aggregates while the detail page
feeds it counts from the full run set — the 60-row run-summary cap (§1.1)
can never corrupt the status.
"""

import logging

from app.schemas.runs import RunStatus

logger = logging.getLogger(__name__)

LIFECYCLE_DRAFT = "DRAFT"
LIFECYCLE_IN_PROGRESS = "IN_PROGRESS"
LIFECYCLE_COMPLETE = "COMPLETE"
LIFECYCLE_ARCHIVED = "ARCHIVED"

# Derived from the canonical RunStatus enum so it can never drift out of sync.
_KNOWN_RUN_STATUSES = {s.value for s in RunStatus}


def derive_lifecycle_status(
    experiment_status: str,
    live_run_count: int,
    open_run_count: int,
) -> str:
    """Derive an experiment's lifecycle status from child-run counts.

    Args:
        experiment_status: the experiment's stored ``status`` column.
        live_run_count: count of runs whose status != ``ARCHIVED``.
        open_run_count: count of live runs whose status != ``COMPLETED``.

    Never raises — it runs on every experiment read, including the org-wide
    list, and one bad row must not 500 the page.
    """
    # `experiment_status` may arrive as a str or an (str, Enum) member —
    # normalize so the equality check is enum-agnostic regardless of caller.
    status = (
        experiment_status
        if isinstance(experiment_status, str)
        else getattr(experiment_status, "value", str(experiment_status))
    )
    if status == LIFECYCLE_ARCHIVED:
        return LIFECYCLE_ARCHIVED
    if live_run_count <= 0:
        return LIFECYCLE_DRAFT
    if open_run_count <= 0:
        return LIFECYCLE_COMPLETE
    return LIFECYCLE_IN_PROGRESS


def lifecycle_counts_from_runs(runs) -> tuple[int, int]:
    """Return ``(live_run_count, open_run_count)`` from run-like objects.

    Each item must expose a ``.status`` (str or enum). Used by the detail
    path, which already has the full run set loaded. An unrecognized status
    is counted as open (never closed) and logged once.
    """
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
