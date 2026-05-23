# Experiments Phases 4-7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Conditions, Key Results, Conclusion (with lock), Export PDF, and Observations to the experiment detail page, completing the F-0093 redesign.

**Architecture:** Three new experiment columns + key-result triple on runs (single Alembic migration with data backfill). New backend endpoints for conclusion lock/unlock, observations aggregation, and PDF export. Conditions and scatter chart computed client-side; PDF rehydrates a Python port from the same fixture. Lifecycle widens to 5 states with backwards-compatible helper signature. Frontend surfaces added as new components under `lib/components/experiment/`.

**Tech Stack:** FastAPI async, SQLAlchemy 2.0 async, Alembic, fpdf2, Svelte 5 runes, Zod, Tailwind, shadcn-svelte, pytest + Vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-05-22-experiments-phases-4-7-design.md`
**Mockup:** `docs/superpowers/specs/2026-05-22-experiments-phases-4-7-mockup.html`

---

## File Inventory

### Backend — Create
- `backend/alembic/versions/<rev>_phases_4_7_experiments.py` — migration
- `backend/app/services/experiments/observations.py` — UNION-ALL aggregation
- `backend/app/services/experiments/pdf_export.py` — fpdf2 renderer
- `backend/app/services/experiments/conditions.py` — Python port of `computeConditions`
- `backend/tests/fixtures/conditions_parity.json` — shared fixture (also symlinked from frontend tests)
- `backend/tests/unit/services/experiments/test_status_phase_4_7.py`
- `backend/tests/unit/services/experiments/test_observations.py`
- `backend/tests/unit/services/experiments/test_conditions_parity.py`
- `backend/tests/integration/api/test_experiments_phase_4_7.py`
- `backend/tests/integration/api/test_runs_phase_4_7.py`

### Backend — Modify
- `backend/app/models/runs.py` — Experiment + Run model columns
- `backend/app/schemas/runs.py` — Pydantic schemas
- `backend/app/services/experiments/status.py` — 5-state lifecycle
- `backend/app/api/endpoints/experiments.py` — 4 new + 1 extended endpoint
- `backend/app/api/endpoints/runs.py` — extend PUT
- `backend/tests/unit/services/test_experiment_status.py` — thread new arg

### Frontend — Create
- `frontend/src/lib/experiments/conditions.ts` — `computeConditions`
- `frontend/src/lib/schemas/observation.ts` — Zod
- `frontend/src/lib/components/experiment/ConditionsTable.svelte`
- `frontend/src/lib/components/experiment/KeyResultsTable.svelte`
- `frontend/src/lib/components/experiment/KeyResultsChart.svelte`
- `frontend/src/lib/components/experiment/ConclusionCard.svelte`
- `frontend/src/lib/components/experiment/ObservationsTimeline.svelte`
- `frontend/src/lib/components/experiment/ExportSummaryButton.svelte`
- `frontend/src/lib/components/run/RunKeyResultFields.svelte`
- `frontend/tests/fixtures/conditions_parity.json` — symlink target
- `frontend/tests/lib/experiments/conditions.test.ts`
- `frontend/tests/lib/components/experiment/ConditionsTable.test.ts`
- `frontend/tests/lib/components/experiment/ConclusionCard.test.ts`
- `frontend/tests/lib/components/experiment/KeyResultsChart.test.ts`
- `frontend/tests/e2e/experiments-phase-4-7.spec.ts`

### Frontend — Modify
- `frontend/src/lib/schemas/experiments.ts` — widen enum, add fields
- `frontend/src/lib/schemas/runs.ts` — add key_result triple
- `frontend/src/lib/components/project/projectUtils.ts` — `AWAITING_CONCLUSION` arms
- `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte` — wire new components
- `frontend/src/routes/[org]/experiments/+page.svelte` — filter tab + stats

---

## Task 1: DB migration — schema + backfill

**Files:**
- Create: `backend/alembic/versions/<rev>_phases_4_7_experiments.py` (run `alembic revision -m "phases 4-7 experiments"` to generate the file with a real revision id)

- [ ] **Step 1: Generate migration skeleton**

```bash
cd backend && source .venv/bin/activate
alembic revision -m "phases 4-7 experiments"
```

Open the generated file under `backend/alembic/versions/` and replace its body with the next step's content.

- [ ] **Step 2: Write `upgrade()` and `downgrade()`**

```python
"""phases 4-7 experiments

Adds conclusion lock columns to experiments, key_result triple to runs, and
backfills existing all-terminal experiments as locked so they don't silently
demote to AWAITING_CONCLUSION post-deploy.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "<filled by alembic>"
down_revision: Union[str, None] = "<filled by alembic>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("conclusion", sa.Text(), nullable=True),
    )
    op.add_column(
        "experiments",
        sa.Column("conclusion_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "experiments",
        sa.Column(
            "conclusion_locked_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "experiments",
        sa.Column("conclusion_locked_by_name", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        "fk_experiments_conclusion_locked_by_id",
        "experiments",
        "users",
        ["conclusion_locked_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "runs",
        sa.Column("key_result_label", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("key_result_value", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("key_result_unit", sa.String(length=32), nullable=True),
    )

    # NOT VALID skips the historical scan; VALIDATE runs without
    # ShareRowExclusiveLock in a separate autocommit transaction.
    op.execute(
        "ALTER TABLE runs ADD CONSTRAINT ck_runs_key_result_paired "
        "CHECK ((key_result_label IS NULL) = (key_result_value IS NULL)) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE runs VALIDATE CONSTRAINT ck_runs_key_result_paired")

    # NaN/Inf defense at the database layer: even though Pydantic rejects
    # NaN/Inf at the API, a raw-SQL admin tool or future bulk-import path
    # could write 'NaN' into Numeric. Reject it here.
    op.execute(
        "ALTER TABLE runs ADD CONSTRAINT ck_runs_key_result_value_finite "
        "CHECK (key_result_value IS NULL OR key_result_value::text NOT IN ('NaN', 'Infinity', '-Infinity')) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute("ALTER TABLE runs VALIDATE CONSTRAINT ck_runs_key_result_value_finite")

    # Backfill: lock any experiment that today reads as "complete" (has runs,
    # no open runs) so the AWAITING_CONCLUSION migration is invisible to users
    # who already perceive these as done.
    #
    # Policy decisions resulting from review panel:
    #   - Leave `conclusion` NULL (do NOT write a sentinel string). The
    #     experiment PDF will render "—" for the conclusion section. We do
    #     not want '[Auto-locked at migration]' surfacing in GxP exports.
    #   - `conclusion_locked_by_name = 'system'` is audit-defensible *only*
    #     in concert with the runbook comment below.
    #   - WHERE clause includes `conclusion_locked_at IS NULL` so this is
    #     idempotent across a downgrade→re-upgrade cycle; if a customer
    #     locked between cycles, their real signature is preserved.
    #   - Run in autocommit_block so the backfill does not extend the
    #     Alembic migration transaction's lock window on large tables.
    #
    # RUNBOOK ENTRY (for FDA-inspection narratives):
    #   "Experiments locked by this migration carry
    #    conclusion_locked_by_name = 'system' and conclusion = NULL.
    #    No human decision was made about these conclusions. Lock was
    #    applied to preserve the previously-displayed COMPLETE lifecycle
    #    state during the F-0043 phases 4-7 deploy. Locked experiments
    #    can be unlocked by an org admin via the standard unlock flow."
    with op.get_context().autocommit_block():
        op.execute(
            """
            UPDATE experiments e
            SET conclusion_locked_at = NOW(),
                conclusion_locked_by_id = NULL,
                conclusion_locked_by_name = 'system'
            WHERE conclusion_locked_at IS NULL
              AND conclusion IS NULL
              AND EXISTS (SELECT 1 FROM runs r WHERE r.experiment_id = e.id)
              AND NOT EXISTS (
                SELECT 1 FROM runs r
                WHERE r.experiment_id = e.id
                  AND r.status IN ('PLANNED', 'ACTIVE', 'EDITED')
              )
            """
        )


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS ck_runs_key_result_value_finite")
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS ck_runs_key_result_paired")
    op.drop_column("runs", "key_result_unit")
    op.drop_column("runs", "key_result_value")
    op.drop_column("runs", "key_result_label")
    op.drop_constraint(
        "fk_experiments_conclusion_locked_by_id",
        "experiments",
        type_="foreignkey",
    )
    op.drop_column("experiments", "conclusion_locked_by_name")
    op.drop_column("experiments", "conclusion_locked_by_id")
    op.drop_column("experiments", "conclusion_locked_at")
    op.drop_column("experiments", "conclusion")
```

- [ ] **Step 3: Apply and verify**

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
psql -U postgres -h localhost batchrite_wt<N> -c "\d experiments" | grep conclusion
psql -U postgres -h localhost batchrite_wt<N> -c "\d runs" | grep key_result
psql -U postgres -h localhost batchrite_wt<N> -c "SELECT conname, convalidated FROM pg_constraint WHERE conname IN ('ck_runs_key_result_paired','ck_runs_key_result_value_finite')"
```

Expected: four new columns on `experiments`, three on `runs`, both constraints show `convalidated = t`.

- [ ] **Step 4: Verify roundtrip**

```bash
alembic downgrade -1 && alembic upgrade head
```

Expected: clean cycle, no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(F-0043): migration for phases 4-7 columns + backfill"
```

---

## Task 2: SQLAlchemy model updates

**Files:**
- Modify: `backend/app/models/runs.py` — `Experiment` class (around line 176) and `Run` class (around line 43)

- [ ] **Step 1: Add columns to `Experiment` model**

In `backend/app/models/runs.py`, inside `class Experiment`, after `created_by_id` (around line 201) add:

```python
    # F-0043: conclusion + lock
    conclusion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conclusion_locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    conclusion_locked_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    conclusion_locked_by_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    conclusion_locked_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[conclusion_locked_by_id]
    )
```

Confirm `datetime`, `DateTime`, and `Text` are already imported at the top of the file (they should be from the existing schema). If `Text` is missing, add it to the `sqlalchemy` import line.

- [ ] **Step 2: Add columns to `Run` model**

In the same file, inside `class Run` (starts around line 43), add (placement: near the existing GxP execution metadata fields, e.g. `lot_number`):

```python
    # F-0043: structured key result for the experiment Results table + chart
    key_result_label: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    key_result_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    key_result_unit: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
```

Add to imports at top of file:
```python
from decimal import Decimal
from sqlalchemy import Numeric
```
(skip whichever is already present).

- [ ] **Step 3: Run existing tests to confirm model loads**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/services/test_experiment_status.py -q
```

Expected: still passes (we haven't changed any logic yet).

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/runs.py
git commit -m "feat(F-0043): SQLAlchemy columns for conclusion lock + key_result"
```

---

## Task 3: Lifecycle widening — `derive_lifecycle_status`

**Files:**
- Modify: `backend/app/services/experiments/status.py`
- Create: `backend/tests/unit/services/experiments/test_status_phase_4_7.py`
- Modify: `backend/tests/unit/services/test_experiment_status.py` (thread default arg)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/experiments/__init__.py` (empty file) and `backend/tests/unit/services/experiments/test_status_phase_4_7.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/services/experiments/test_status_phase_4_7.py -v
```

Expected: ImportError on `LIFECYCLE_AWAITING_CONCLUSION` or TypeError on the new arg.

- [ ] **Step 3: Update `status.py`**

Replace the body of `backend/app/services/experiments/status.py`:

```python
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
```

- [ ] **Step 4: Re-run new tests**

```bash
pytest tests/unit/services/experiments/test_status_phase_4_7.py -v
```

Expected: 7 passing.

- [ ] **Step 5: Re-run existing status tests AND update the three failing assertions**

```bash
pytest tests/unit/services/test_experiment_status.py -v
```

Expected: three failures at lines 22, 46, and 81 of `backend/tests/unit/services/test_experiment_status.py`. Each asserts `"COMPLETE"` for an all-terminal experiment without a `conclusion_locked` arg; the new default returns `"AWAITING_CONCLUSION"`.

For each of the three failing assertions:
1. Change the existing assertion's expected value from `"COMPLETE"` to `"AWAITING_CONCLUSION"` (do NOT add the new arg — keep these tests testing the no-lock case).
2. Add a companion assertion immediately below that calls the same function with `conclusion_locked=True` and asserts `"COMPLETE"` — this preserves coverage of the COMPLETE path that the original test was asserting.

Example for line 22 (`test_all_live_runs_completed_is_complete`):

```python
def test_all_live_runs_completed_is_complete():
    # No lock → AWAITING_CONCLUSION (was COMPLETE before F-0043 widening).
    assert derive_lifecycle_status("DRAFT", 3, 0) == "AWAITING_CONCLUSION"
    # With lock → COMPLETE (the previous semantic, now gated on the lock).
    assert derive_lifecycle_status("DRAFT", 3, 0, conclusion_locked=True) == "COMPLETE"
```

Apply the same pattern to lines 46 (`test_counts_exclude_archived_runs`) and 81 (`test_accepts_enum_experiment_status`).

Re-run:

```bash
pytest tests/unit/services/test_experiment_status.py -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/experiments/status.py \
        backend/tests/unit/services/experiments/__init__.py \
        backend/tests/unit/services/experiments/test_status_phase_4_7.py \
        backend/tests/unit/services/test_experiment_status.py
git commit -m "feat(F-0043): widen lifecycle to 5 states with AWAITING_CONCLUSION"
```

---

## Task 4: Thread `conclusion_locked` through all `derive_lifecycle_status` call sites

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py` (lines 162, 203, 251, 363, 409, 468)

> **IMPORTANT (review-panel finding):** Task 3 and Task 4 must land in the same commit. Between Task 3 (default arg `conclusion_locked=False`) and Task 4 (threading the column through), every existing call site silently returns `AWAITING_CONCLUSION` for backfilled-locked experiments. Treat these as one logical change.

- [ ] **Step 0: Confirm no out-of-scope call sites exist**

```bash
grep -rn "derive_lifecycle_status" backend/ frontend/
```

Expected output: 6 production call sites in `backend/app/api/endpoints/experiments.py` (lines 162, 203, 251, 363, 409, 468) plus test files. If you find a call site outside `experiments.py` — chat tools, AI summarizer, notifications, recovery loops, seed scripts — STOP and thread `conclusion_locked` through it in this task; do not rely on the default.

- [ ] **Step 1: Update call sites that already have the Experiment row in scope**

For each of these line numbers in `backend/app/api/endpoints/experiments.py`, change the `derive_lifecycle_status(exp.status, live, open_)` call to thread `conclusion_locked=exp.conclusion_locked_at is not None`. Specifically:

- Line 162 (`derive_lifecycle_status(experiment.status, 0, 0)`): leave as-is. A freshly-created experiment with 0 runs returns DRAFT regardless of lock state.
- Lines 251, 409, 468 (detail/update paths with `exp` in scope): add `conclusion_locked=exp.conclusion_locked_at is not None`.
- Lines 203, 363 (list paths): see Step 2 — these require the SQL to project the column first.

- [ ] **Step 2: Update list queries to project `conclusion_locked_at`**

Read `list_experiments` (starts around line 182) and `list_all_experiments` (starts around line 255). Both build SQL select statements that aggregate run counts; add `Experiment.conclusion_locked_at` to the column list. Then in the result loop, pass `conclusion_locked=row.conclusion_locked_at is not None` to `derive_lifecycle_status`.

Use `grep -n "select(.*Experiment" backend/app/api/endpoints/experiments.py` to locate the SQL builders. If the queries already SELECT the full `Experiment` row, no SQL change is needed — just thread the field through to `derive_lifecycle_status`.

- [ ] **Step 3: Run existing experiment integration tests**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_experiments_index.py tests/integration/api/ -k experiment -q
```

Expected: pass — backfill from Task 1 means existing "complete" fixtures (if any) now correctly read locked.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/endpoints/experiments.py
git commit -m "feat(F-0043): thread conclusion_locked through all lifecycle call sites"
```

---

## Task 5: Pydantic schemas — request + response

**Files:**
- Modify: `backend/app/schemas/runs.py` (`ExperimentUpdate` ~line 115, `ExperimentResponse` ~line 333, `RunUpdate` ~line 230, `RunResponse` ~line 262)

- [ ] **Step 1: Add `conclusion` to `ExperimentUpdate`**

In `backend/app/schemas/runs.py`, in `class ExperimentUpdate` (~line 115), add after `success_criteria`:

```python
    conclusion: Optional[str] = Field(default=None, max_length=65536)
```

- [ ] **Step 2: Add key_result triple + validator to `RunUpdate`**

In `class RunUpdate` (~line 230), add after `batch_number`:

```python
    key_result_label: Optional[str] = Field(default=None, max_length=120)
    key_result_value: Optional[float] = None
    key_result_unit: Optional[str] = Field(default=None, max_length=32)

    @field_validator("key_result_value")
    @classmethod
    def _bound_key_result(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        # Reject NaN / Inf and bound magnitude to Numeric(14,6) integer digits.
        if not (v == v):  # NaN
            raise ValueError("key_result_value cannot be NaN")
        if v in (float("inf"), float("-inf")):
            raise ValueError("key_result_value cannot be infinite")
        if abs(v) >= 10**14:
            raise ValueError("key_result_value magnitude exceeds 14 integer digits")
        return v
```

Confirm `field_validator` is in the existing `pydantic` import line at top of file; add it if missing.

- [ ] **Step 3: Add a paired-validation root validator on `RunUpdate`**

Still in `RunUpdate`, add below the field validator:

```python
    @model_validator(mode="after")
    def _key_result_pairing(self) -> "RunUpdate":
        label_present = self.key_result_label is not None
        value_present = self.key_result_value is not None
        if label_present != value_present:
            raise ValueError(
                "key_result_label and key_result_value must be set together"
            )
        return self
```

Add `model_validator` to the `pydantic` import.

- [ ] **Step 4: Extend `ExperimentResponse`**

In `class ExperimentResponse` (~line 333), add after `created_by_id`:

```python
    conclusion: Optional[str] = None
    conclusion_locked_at: Optional[datetime] = None
    conclusion_locked_by_id: Optional[UUID] = None
    conclusion_locked_by_name: Optional[str] = None
```

- [ ] **Step 5: Extend `RunResponse`**

In `class RunResponse` (~line 262), add after `batch_number`:

```python
    key_result_label: Optional[str] = None
    key_result_value: Optional[float] = None
    key_result_unit: Optional[str] = None
```

- [ ] **Step 6: Verify schemas import cleanly**

```bash
cd backend && source .venv/bin/activate
python -c "from app.schemas.runs import ExperimentUpdate, ExperimentResponse, RunUpdate, RunResponse; print('ok')"
```

Expected: `ok`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/runs.py
git commit -m "feat(F-0043): Pydantic schemas for conclusion + key_result fields"
```

---

## Task 6: Lock guard + `conclusion` write on `PUT /experiments/{id}`

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py` — `update_experiment` (~line 413-469)
- Create: `backend/tests/integration/api/test_experiments_phase_4_7.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/api/test_experiments_phase_4_7.py`:

```python
"""F-0043 — phases 4-7 integration tests."""

import pytest


@pytest.mark.asyncio
async def test_put_experiment_writes_conclusion_when_unlocked(
    client, seeded_experiment, auth_headers
):
    res = await client.put(
        f"/experiments/{seeded_experiment.id}",
        json={"conclusion": "Run 2 wins by 24%."},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["conclusion"] == "Run 2 wins by 24%."


@pytest.mark.asyncio
async def test_put_experiment_409_when_locked(
    client, locked_experiment, auth_headers
):
    # Lock guard freezes ALL fields, not just conclusion.
    for body in (
        {"conclusion": "new"},
        {"objective": "new objective"},
        {"description": "new desc"},
    ):
        res = await client.put(
            f"/experiments/{locked_experiment.id}",
            json=body,
            headers=auth_headers,
        )
        assert res.status_code == 409, body
        assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"
```

Add the fixtures `seeded_experiment`, `locked_experiment`, `auth_headers` to the existing `conftest.py` for this suite if they don't exist; use the existing experiment-creation helpers (`backend/tests/integration/conftest.py` is the canonical location). The `locked_experiment` fixture must `INSERT` a row with `conclusion='x'`, `conclusion_locked_at=now()`.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/api/test_experiments_phase_4_7.py::test_put_experiment_409_when_locked -v
```

Expected: FAIL — the endpoint currently returns 200 silently dropping `conclusion`.

- [ ] **Step 3: Patch `update_experiment`**

In `backend/app/api/endpoints/experiments.py`, replace the field-iteration block in `update_experiment` (~line 436-447):

```python
    # F-0043: lock guard — while locked, ALL mutations 409.
    if exp.conclusion_locked_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPERIMENT_LOCKED",
                "message": "Experiment conclusion is locked. Admin must unlock first.",
            },
        )

    changes = {}
    for field in (
        "name", "description", "content", "objective",
        "success_criteria", "conclusion",
    ):
        value = getattr(update_data, field)
        if value is not None:
            old = getattr(exp, field)
            resolved = value.value if isinstance(value, Enum) else value
            setattr(exp, field, resolved)
            changes[field] = {"old": old, "new": resolved}
    if update_data.content is not None:
        flag_modified(exp, "content")
    if update_data.success_criteria is not None:
        flag_modified(exp, "success_criteria")
```

- [ ] **Step 4: Update the response builder at the bottom of `update_experiment`**

Replace the `ExperimentResponse(...)` construction (~line 464-469) to thread the new fields:

```python
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_,
            conclusion_locked=exp.conclusion_locked_at is not None,
        ),
    )
```

Then update `_experiment_dict` (locate via grep — it's the helper that maps Experiment → dict) to include `conclusion`, `conclusion_locked_at`, `conclusion_locked_by_id`, `conclusion_locked_by_name`.

- [ ] **Step 5: Re-run tests**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -v
```

Expected: 2 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/experiments.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): conclusion field + lock guard on PUT /experiments"
```

---

## Task 6b: Lock guards on adjacent mutation endpoints

**Why this task exists (review-panel finding):** `PUT /experiments/{id}` is not the only way to mutate a locked experiment. `POST /runs`, `POST /experiments/{id}/runs`, and the notes endpoints all bypass the Task 6 guard. Without this task, a locked experiment can be silently demoted to `AWAITING_CONCLUSION` by adding a new run, or have its notes (which feed the observations timeline) edited after the lock signature was applied.

**Decision on notes:** post-lock notes are *blocked*, not allowed as addenda. Rationale: notes feed `ObservationsTimeline`, which is also embedded in the PDF export — a "locked PDF" must reflect the locked dataset, not include later additions.

**Files:**
- Modify: `backend/app/api/endpoints/runs.py` — `create_run` (~line 154)
- Modify: `backend/app/api/endpoints/experiments.py` — `add_run_to_experiment` (~line 525), notes endpoints starting at ~line 658
- Modify: `backend/tests/integration/api/test_experiments_phase_4_7.py`
- Modify: `backend/tests/integration/api/test_runs_phase_4_7.py` (create in Task 9 — for now leave a TODO marker)

- [ ] **Step 1: Write failing tests**

Append to `test_experiments_phase_4_7.py`:

```python
@pytest.mark.asyncio
async def test_post_run_to_locked_experiment_409(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/runs",
        json={"name": "post-lock run"},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_create_run_via_runs_endpoint_to_locked_experiment_409(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        "/runs",
        json={"name": "x", "experiment_id": str(locked_experiment.id)},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"


@pytest.mark.asyncio
async def test_add_note_to_locked_experiment_409(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/notes",
        json={"content": "post-lock observation", "flag": "observation"},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EXPERIMENT_LOCKED"
```

- [ ] **Step 2: Run to verify failures**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/api/test_experiments_phase_4_7.py -k "to_locked_experiment or add_note_to_locked" -v
```

Expected: 3 FAILS (current behavior is 201/200).

- [ ] **Step 3: Add the guard to `add_run_to_experiment`**

In `backend/app/api/endpoints/experiments.py`, in `add_run_to_experiment` (~line 525), after the existing ARCHIVED check (~line 554), insert:

```python
    if experiment.conclusion_locked_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPERIMENT_LOCKED",
                "message": "Cannot add a run to a locked experiment.",
            },
        )
```

- [ ] **Step 4: Add the guard to `create_run`**

In `backend/app/api/endpoints/runs.py`, in `create_run` (~line 154), find the block where `experiment_id` is resolved (around line 191-216 — look for the existing `LIFECYCLE_ARCHIVED` check). After that ARCHIVED check, insert the same lock guard. The `experiment` variable must already be in scope from the ARCHIVED check — reuse it. If it isn't loaded, load it: `experiment = await get_or_404(db, Experiment, run_in.experiment_id)`.

- [ ] **Step 5: Add the guard to the experiment notes endpoints**

In `backend/app/api/endpoints/experiments.py`, in each of:
- `add_experiment_note` (~line 658)
- The PUT and DELETE note endpoints below it (search for `/experiments/{experiment_id}/notes`)

After the `get_or_404(db, Experiment, ...)` call, before any mutation, insert:

```python
    if exp.conclusion_locked_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPERIMENT_LOCKED",
                "message": "Notes are frozen after the conclusion is locked.",
            },
        )
```

- [ ] **Step 6: Re-run tests**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -v
```

Expected: all post-lock guard tests passing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/runs.py \
        backend/app/api/endpoints/experiments.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): lock guards on run-create and notes endpoints"
```

---

## Task 7: `POST /experiments/{id}/conclusion/lock`

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py`
- Modify: `backend/tests/integration/api/test_experiments_phase_4_7.py`

- [ ] **Step 1: Write failing tests**

Append to `test_experiments_phase_4_7.py`:

```python
@pytest.mark.asyncio
async def test_lock_409_when_open_runs(
    client, experiment_with_open_run, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_with_open_run.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "OPEN_RUNS"


@pytest.mark.asyncio
async def test_lock_409_when_conclusion_empty(
    client, experiment_terminal_no_conclusion, auth_headers
):
    res = await client.post(
        f"/experiments/{experiment_terminal_no_conclusion.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "EMPTY_CONCLUSION"


@pytest.mark.asyncio
async def test_lock_happy_path(
    client, experiment_ready_to_lock, auth_headers, db
):
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conclusion_locked_at"] is not None
    assert body["conclusion_locked_by_name"] is not None
    assert body["lifecycle_status"] == "COMPLETE"


@pytest.mark.asyncio
async def test_lock_409_when_already_locked(
    client, locked_experiment, auth_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "ALREADY_LOCKED"


@pytest.mark.asyncio
async def test_lock_409_when_no_completed_runs(
    client, experiment_only_archived_runs, auth_headers
):
    # All-archived experiments read as DRAFT in lifecycle derivation; locking
    # would silently flip them to COMPLETE without any completed run. Refuse.
    res = await client.post(
        f"/experiments/{experiment_only_archived_runs.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "NO_COMPLETED_RUNS"


@pytest.mark.asyncio
async def test_lock_audit_row_atomic_with_state(
    client, experiment_ready_to_lock, auth_headers, db
):
    """Lock UPDATE + audit insert must commit in the same transaction.

    Asserts that on a successful lock there is exactly one audit row whose
    `entity_id` matches the experiment AND that the experiment is actually
    locked — proving they were committed together.
    """
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
        headers=auth_headers,
    )
    assert res.status_code == 200
    rows = await db.execute(
        text(
            "SELECT count(*) FROM audit_log "
            "WHERE entity_type='Experiment' AND entity_id=:eid AND action='conclusion.lock'"
        ),
        {"eid": experiment_ready_to_lock.id},
    )
    assert rows.scalar() == 1


@pytest.mark.asyncio
async def test_lock_vs_run_create_toctou(
    client, experiment_ready_to_lock, auth_headers, db
):
    """TOCTOU: lock + simultaneous run creation. Exactly one must succeed."""
    import asyncio

    async def lock():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/conclusion/lock",
            headers=auth_headers,
        )

    async def add_run():
        return await client.post(
            f"/experiments/{experiment_ready_to_lock.id}/runs",
            json={"name": "race run"},
            headers=auth_headers,
        )

    a, b = await asyncio.gather(lock(), add_run())
    # The lock either wins (200 + 409 on add_run) or loses (409 on lock + 201
    # on add_run). The forbidden state is both succeeding.
    successes = sum(1 for r in (a, b) if r.status_code < 400)
    assert successes == 1, f"both succeeded: lock={a.status_code} add_run={b.status_code}"
```

Add fixtures `experiment_with_open_run` (one PLANNED run), `experiment_terminal_no_conclusion` (one COMPLETED run, no conclusion text), `experiment_ready_to_lock` (one COMPLETED run, conclusion populated), and `experiment_only_archived_runs` (all runs ARCHIVED, conclusion populated) to `conftest.py`.

> **Conftest location (review-panel finding):** `backend/tests/integration/conftest.py` does not currently exist. Create it (pytest will auto-discover it). It inherits `auth_headers` from `backend/tests/conftest.py`. Only experiment-specific fixtures (`seeded_experiment`, `locked_experiment`, `experiment_with_open_run`, `experiment_terminal_no_conclusion`, `experiment_ready_to_lock`, `experiment_only_archived_runs`, `admin_headers`, `viewer_headers`) go in the new file — do NOT add them to the root conftest.

- [ ] **Step 2: Run to verify failures**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -v
```

Expected: 4 FAILS with 404 (route doesn't exist).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/endpoints/experiments.py`, after `update_experiment` add:

```python
@router.post(
    "/experiments/{experiment_id}/conclusion/lock",
    response_model=ExperimentResponse,
)
async def lock_experiment_conclusion(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.EDIT,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    # GxP signature durability: require profile name. Fall back to "User
    # {id}" instead of leaking email into the permanent record.
    profile_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    user_name = profile_name if profile_name else f"User {user.id}"

    # Atomic UPDATE: race-free against concurrent run transitions AND against
    # concurrent lock attempts (asyncpg returns a row when the WHERE matches;
    # asyncpg's `result.rowcount` is unreliable for `UPDATE ... RETURNING`,
    # so we branch on the returned row count via `result.all()`).
    #
    # Additional guard: require at least one COMPLETED run. Without this an
    # experiment whose only runs are ARCHIVED — which reads as DRAFT via
    # lifecycle_counts_from_runs — could be locked into COMPLETE state, a
    # contradiction.
    result = await db.execute(
        text(
            """
            UPDATE experiments
            SET conclusion_locked_at = NOW(),
                conclusion_locked_by_id = :user_id,
                conclusion_locked_by_name = :user_name
            WHERE id = :exp_id
              AND conclusion_locked_at IS NULL
              AND conclusion IS NOT NULL
              AND length(trim(conclusion)) > 0
              AND EXISTS (
                SELECT 1 FROM runs
                WHERE experiment_id = :exp_id
                  AND status = 'COMPLETED'
              )
              AND NOT EXISTS (
                SELECT 1 FROM runs
                WHERE experiment_id = :exp_id
                  AND status IN ('PLANNED', 'ACTIVE', 'EDITED')
              )
            RETURNING id, conclusion
            """
        ),
        {"exp_id": exp.id, "user_id": user.id, "user_name": user_name},
    )
    rows = result.all()
    if not rows:
        # Disambiguate the failure for the client. Re-read the row in the
        # same transaction; `db.refresh()` reads from snapshot which is
        # acceptable here because we're branching on already-committed state.
        await db.refresh(exp)
        has_completed = await db.scalar(
            select(func.count(Run.id)).where(
                Run.experiment_id == exp.id, Run.status == "COMPLETED"
            )
        )
        if exp.conclusion_locked_at is not None:
            code, message = "ALREADY_LOCKED", "This experiment is already locked. Refresh and try again."
        elif not (exp.conclusion or "").strip():
            code, message = "EMPTY_CONCLUSION", "Write a conclusion before locking."
        elif not has_completed:
            code, message = "NO_COMPLETED_RUNS", "At least one run must be COMPLETED before locking."
        else:
            code, message = "OPEN_RUNS", "This experiment has open runs. Refresh and try again."
        raise HTTPException(409, {"code": code, "message": message})

    # Atomic audit: log_audit only db.add()s the row. Insert it BEFORE the
    # single commit so business state and audit row land together. If
    # log_audit raises, the UPDATE rolls back too. See projects.py for the
    # established pattern.
    locked_row = rows[0]
    await log_audit(
        db,
        actor_id=user.id,
        action="conclusion.lock",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"conclusion_snapshot": locked_row.conclusion},
    )
    await db.commit()
    await db.refresh(exp)

    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=True,
        ),
    )
```

Confirm imports at top of file: `from sqlalchemy import text, select, func` and `from app.models.runs import Run`.

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -v
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/experiments.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): atomic conclusion lock endpoint"
```

---

## Task 8: `POST /experiments/{id}/conclusion/unlock`

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py`
- Modify: `backend/app/schemas/runs.py` (new request body schema)
- Modify: `backend/tests/integration/api/test_experiments_phase_4_7.py`

- [ ] **Step 1: Add `ConclusionUnlockRequest` schema**

In `backend/app/schemas/runs.py`, near `ExperimentUpdate`:

```python
class ConclusionUnlockRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)
```

- [ ] **Step 2: Write failing tests**

Append to `test_experiments_phase_4_7.py`:

```python
@pytest.mark.asyncio
async def test_unlock_403_for_non_admin(
    client, locked_experiment, viewer_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "data correction"},
        headers=viewer_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unlock_422_short_reason(
    client, locked_experiment, admin_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "short"},
        headers=admin_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_unlock_happy_path(
    client, locked_experiment, admin_headers
):
    res = await client.post(
        f"/experiments/{locked_experiment.id}/conclusion/unlock",
        json={"reason": "Re-analysis with corrected titer values."},
        headers=admin_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["conclusion_locked_at"] is None
    assert body["lifecycle_status"] == "AWAITING_CONCLUSION"


@pytest.mark.asyncio
async def test_unlock_409_when_already_unlocked(
    client, experiment_ready_to_lock, admin_headers
):
    res = await client.post(
        f"/experiments/{experiment_ready_to_lock.id}/conclusion/unlock",
        json={"reason": "data correction"},
        headers=admin_headers,
    )
    assert res.status_code == 409
```

Add `admin_headers` and `viewer_headers` fixtures if absent.

- [ ] **Step 3: Verify failures**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -k unlock -v
```

Expected: 4 FAILs (route missing).

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/endpoints/experiments.py`:

```python
@router.post(
    "/experiments/{experiment_id}/conclusion/unlock",
    response_model=ExperimentResponse,
)
async def unlock_experiment_conclusion(
    experiment_id: UUID,
    body: ConclusionUnlockRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.ADMIN,
    )
    if not allowed:
        raise HTTPException(403, "Admin only")

    conclusion_before = exp.conclusion
    locked_by_before = exp.conclusion_locked_by_name
    locked_at_before = exp.conclusion_locked_at
    result = await db.execute(
        text(
            """
            UPDATE experiments
            SET conclusion_locked_at = NULL,
                conclusion_locked_by_id = NULL,
                conclusion_locked_by_name = NULL
            WHERE id = :exp_id
              AND conclusion_locked_at IS NOT NULL
            RETURNING id
            """
        ),
        {"exp_id": exp.id},
    )
    rows = result.all()
    if not rows:
        raise HTTPException(
            409, {"code": "ALREADY_UNLOCKED", "message": "Not locked"},
        )

    # Atomic audit: insert before single commit. See lock endpoint above.
    await log_audit(
        db,
        actor_id=user.id,
        action="conclusion.unlock",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={
            "reason": body.reason,
            "conclusion_before": conclusion_before,
            "locked_by_before": locked_by_before,
            "locked_at_before": locked_at_before.isoformat() if locked_at_before else None,
        },
    )
    await db.commit()
    await db.refresh(exp)

    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(
            exp.status, live, open_, conclusion_locked=False,
        ),
    )
```

Add `ConclusionUnlockRequest` to the import block at the top.

- [ ] **Step 5: Re-run tests**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -k unlock -v
```

Expected: 4 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/experiments.py \
        backend/app/schemas/runs.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): admin-only conclusion unlock with audit reason"
```

---

## Task 9: `PUT /runs/{id}` extension — key_result triple

**Files:**
- Modify: `backend/app/api/endpoints/runs.py`
- Create: `backend/tests/integration/api/test_runs_phase_4_7.py`

- [ ] **Step 1: Write failing tests**

```python
"""F-0043 — PUT /runs/{id} key_result triple."""

import pytest


@pytest.mark.asyncio
async def test_put_run_accepts_key_result(client, seeded_run, auth_headers):
    res = await client.put(
        f"/runs/{seeded_run.id}",
        json={
            "key_result_label": "Titer",
            "key_result_value": 4.2,
            "key_result_unit": "g/L",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["key_result_label"] == "Titer"
    assert body["key_result_value"] == 4.2
    assert body["key_result_unit"] == "g/L"


@pytest.mark.asyncio
async def test_put_run_422_unpaired(client, seeded_run, auth_headers):
    for body in (
        {"key_result_label": "Titer"},
        {"key_result_value": 4.2},
    ):
        res = await client.put(
            f"/runs/{seeded_run.id}", json=body, headers=auth_headers,
        )
        assert res.status_code == 422, body


@pytest.mark.asyncio
async def test_put_run_422_invalid_value(client, seeded_run, auth_headers):
    for body in (
        {"key_result_label": "x", "key_result_value": float("nan")},
        {"key_result_label": "x", "key_result_value": float("inf")},
        {"key_result_label": "x", "key_result_value": 1e20},
    ):
        res = await client.put(
            f"/runs/{seeded_run.id}", json=body, headers=auth_headers,
        )
        assert res.status_code == 422, body
```

- [ ] **Step 2: Verify failure**

```bash
pytest tests/integration/api/test_runs_phase_4_7.py -v
```

Expected: FAILs — fields silently dropped.

- [ ] **Step 3: Patch `PUT /runs/{id}`**

Locate the run update handler in `backend/app/api/endpoints/runs.py` (search for `@router.put("/runs/{run_id}"`). In its field iteration block, add the three new fields to the writeable set. Pattern matches the existing `lot_number`, `batch_number` handling — extend the same way.

If the handler uses an explicit field list (`for field in (...)`), add `"key_result_label"`, `"key_result_value"`, `"key_result_unit"`. If it does `getattr(update_data, field)` over `update_data.model_dump(exclude_unset=True)`, no list update needed — the fields flow through automatically.

Either way, append a `log_audit` call **before the final `db.commit()`** when any of the three changed. The audit row MUST land in the same transaction as the state mutation — never split commits. Locate the existing single commit at the end of the handler; the `log_audit` insertion must precede it:

```python
        if any(k in changes for k in ("key_result_label", "key_result_value", "key_result_unit")):
            await log_audit(
                db,
                actor_id=user.id,
                action="key_result.set",
                entity_type="Run",
                entity_id=run.id,
                changes={k: changes[k] for k in ("key_result_label", "key_result_value", "key_result_unit") if k in changes},
            )
        # ... other field updates ...
        await db.commit()  # single commit covers state + audit atomically
```

If the existing handler already does `db.commit()` somewhere mid-flow then mutates again, fix the split first — never add the audit after a separate commit.

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/integration/api/test_runs_phase_4_7.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/api/test_runs_phase_4_7.py
git commit -m "feat(F-0043): PUT /runs accepts key_result triple"
```

---

## Task 10: Observations aggregation service + endpoint

**Files:**
- Create: `backend/app/services/experiments/observations.py`
- Create: `backend/tests/unit/services/experiments/test_observations.py`
- Modify: `backend/app/api/endpoints/experiments.py`
- Modify: `backend/tests/integration/api/test_experiments_phase_4_7.py`

- [ ] **Step 1: Write failing unit tests**

`backend/tests/unit/services/experiments/test_observations.py`:

```python
"""F-0043 — observations aggregation."""

import pytest
from uuid import uuid4
from datetime import datetime, timezone

from app.services.experiments.observations import aggregate_observations


@pytest.mark.asyncio
async def test_returns_experiment_and_run_notes_desc(db, experiment_with_notes):
    res = await aggregate_observations(db, experiment_with_notes.id)
    assert res.truncated is False
    assert len(res.items) >= 2
    # Sorted desc by created_at
    for a, b in zip(res.items, res.items[1:]):
        assert a.created_at >= b.created_at


@pytest.mark.asyncio
async def test_only_anomaly_from_runs(db, experiment_with_run_observation_note):
    # Run notes only allow `anomaly` per ALLOWED_NOTE_FLAGS; anything else
    # must not surface.
    res = await aggregate_observations(db, experiment_with_run_observation_note.id)
    run_items = [i for i in res.items if i.source == "run"]
    assert all(i.flag == "anomaly" for i in run_items)


@pytest.mark.asyncio
async def test_malformed_notes_filtered(db, experiment_with_malformed_notes):
    # Notes missing `flag` or `created_at` must be silently dropped, not raise.
    res = await aggregate_observations(db, experiment_with_malformed_notes.id)
    assert all(i.flag and i.created_at for i in res.items)


@pytest.mark.asyncio
async def test_empty_experiment(db, empty_experiment):
    res = await aggregate_observations(db, empty_experiment.id)
    assert res.items == []
    assert res.truncated is False


@pytest.mark.asyncio
async def test_truncated_flag(db, experiment_with_600_notes):
    res = await aggregate_observations(db, experiment_with_600_notes.id, limit=500)
    assert len(res.items) == 500
    assert res.truncated is True


@pytest.mark.asyncio
async def test_stable_composite_id(db, experiment_with_notes):
    res = await aggregate_observations(db, experiment_with_notes.id)
    ids = {item.id for item in res.items}
    assert len(ids) == len(res.items)
    for item in res.items:
        assert item.id.startswith(f"{item.source}:")
```

Add the listed fixtures to `backend/tests/unit/services/experiments/conftest.py` (create if missing). Each fixture should `INSERT` experiment + run rows with the relevant JSONB note shapes.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/services/experiments/test_observations.py -v
```

Expected: ImportError on `aggregate_observations`.

- [ ] **Step 3: Implement the service**

`backend/app/services/experiments/observations.py`:

```python
"""F-0043 — aggregate observations from experiment + run notes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ObservationSource = Literal["experiment", "run"]
ObservationFlag = Literal["observation", "anomaly"]


@dataclass
class ObservationItem:
    id: str
    source: ObservationSource
    source_id: UUID
    run_label: Optional[str]
    flag: ObservationFlag
    body: str
    author_name: str
    created_at: datetime


@dataclass
class ObservationsResponse:
    items: list[ObservationItem]
    truncated: bool


async def aggregate_observations(
    db: AsyncSession, experiment_id: UUID, limit: int = 500
) -> ObservationsResponse:
    """UNION ALL over experiment.notes + run.notes, filtered + sorted desc."""
    # Per-branch LIMIT pushed inside each subquery so Postgres can short-circuit
    # before merging. The malformed-timestamp regex guard prevents
    # `(note->>'created_at')::timestamptz` from raising on garbage data — bad
    # rows are silently dropped (covered by `test_malformed_notes_filtered`).
    # Archived runs are filtered out at the SQL level so a stale archived run's
    # anomalies don't pollute the active timeline.
    ts_regex = r"^\d{4}-\d{2}-\d{2}T"
    sql = text(
        """
        SELECT * FROM (
            (
                SELECT
                    'experiment' AS source,
                    e.id AS source_id,
                    NULL::text AS run_label,
                    (note->>'id') AS note_id,
                    (note->>'flag') AS flag,
                    (note->>'content') AS body,
                    COALESCE(note->>'author_name', 'Unknown') AS author_name,
                    (note->>'created_at')::timestamptz AS created_at
                FROM experiments e
                CROSS JOIN LATERAL jsonb_array_elements(e.notes) AS note
                WHERE e.id = :exp_id
                  AND note->>'flag' IN ('observation', 'anomaly')
                  AND note->>'created_at' ~ :ts_regex
                ORDER BY created_at DESC
                LIMIT :limit_plus_one
            )
            UNION ALL
            (
                SELECT
                    'run' AS source,
                    r.id AS source_id,
                    r.name AS run_label,
                    (note->>'id') AS note_id,
                    (note->>'flag') AS flag,
                    (note->>'content') AS body,
                    COALESCE(note->>'author_name', 'Unknown') AS author_name,
                    (note->>'created_at')::timestamptz AS created_at
                FROM runs r
                CROSS JOIN LATERAL jsonb_array_elements(r.notes) AS note
                WHERE r.experiment_id = :exp_id
                  AND r.status != 'ARCHIVED'
                  AND note->>'flag' = 'anomaly'
                  AND note->>'created_at' ~ :ts_regex
                ORDER BY created_at DESC
                LIMIT :limit_plus_one
            )
        ) merged
        ORDER BY created_at DESC
        LIMIT :limit_plus_one
        """
    )
    rows = (
        await db.execute(
            sql,
            {
                "exp_id": experiment_id,
                "limit_plus_one": limit + 1,
                "ts_regex": ts_regex,
            },
        )
    ).mappings().all()
    truncated = len(rows) > limit
    if truncated:
        import logging
        logging.getLogger(__name__).warning(
            "observations_truncated experiment_id=%s limit=%d",
            experiment_id,
            limit,
        )
    items = [
        ObservationItem(
            id=f"{r['source']}:{r['source_id']}:{r['note_id'] or 'noid'}",
            source=r["source"],
            source_id=r["source_id"],
            run_label=r["run_label"],
            flag=r["flag"],
            body=r["body"] or "",
            author_name=r["author_name"],
            created_at=r["created_at"],
        )
        for r in rows[:limit]
    ]
    return ObservationsResponse(items=items, truncated=truncated)
```

- [ ] **Step 4: Verify unit tests pass**

```bash
pytest tests/unit/services/experiments/test_observations.py -v
```

Expected: 6 passing.

- [ ] **Step 5: Add the endpoint**

In `backend/app/api/endpoints/experiments.py`:

```python
@router.get("/experiments/{experiment_id}/observations")
async def get_experiment_observations(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.READ,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    result = await aggregate_observations(db, experiment_id)
    response = JSONResponse(
        content={
            "items": [
                {
                    "id": i.id,
                    "source": i.source,
                    "source_id": str(i.source_id),
                    "run_label": i.run_label,
                    "flag": i.flag,
                    "body": i.body,
                    "author_name": i.author_name,
                    "created_at": i.created_at.isoformat(),
                }
                for i in result.items
            ],
            "truncated": result.truncated,
        },
    )
    # Observations don't fan out to other users in real time; a 30s private
    # cache keeps the page snappy on revisits without losing freshness.
    response.headers["Cache-Control"] = "private, max-age=30"
    return response
```

Confirm `from fastapi.responses import JSONResponse` and `from app.services.experiments.observations import aggregate_observations` are imported.

- [ ] **Step 6: Append integration test**

To `test_experiments_phase_4_7.py`:

```python
@pytest.mark.asyncio
async def test_observations_endpoint(client, experiment_with_notes, auth_headers):
    res = await client.get(
        f"/experiments/{experiment_with_notes.id}/observations",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["cache-control"] == "private, max-age=30"
    body = res.json()
    assert "items" in body and "truncated" in body
```

- [ ] **Step 7: Run integration test + commit**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -k observations -v
git add backend/app/services/experiments/observations.py \
        backend/tests/unit/services/experiments/test_observations.py \
        backend/tests/unit/services/experiments/conftest.py \
        backend/app/api/endpoints/experiments.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): observations aggregation service + endpoint"
```

---

## Task 11: Conditions parity — shared fixture + Python port

**Files:**
- Create: `backend/tests/fixtures/conditions_parity.json`
- Create: `backend/app/services/experiments/conditions.py`
- Create: `backend/tests/unit/services/experiments/test_conditions_parity.py`
- Create: `frontend/tests/fixtures/conditions_parity.json` (symlink target — actual symlink created at the end)

- [ ] **Step 1: Author the shared fixture**

`backend/tests/fixtures/conditions_parity.json`:

```json
{
  "scenarios": [
    {
      "name": "identical_runs_yield_no_varied",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Seeding",
            "params": {"density": 100000},
            "paramSchema": {"properties": {"density": {"unit": "cells/mL"}}}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Seeding",
            "params": {"density": 100000},
            "paramSchema": {"properties": {"density": {"unit": "cells/mL"}}}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Seeding", "paramKey": "density", "varied": false,
         "perRun": {"r1": {"value": 100000, "unit": "cells/mL"},
                    "r2": {"value": 100000, "unit": "cells/mL"}}}
      ]
    },
    {
      "name": "single_differing_param",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Feed",
            "params": {"glucose": 6, "ph": 7.0}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Feed",
            "params": {"glucose": 8, "ph": 7.0}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Feed", "paramKey": "glucose", "varied": true,
         "perRun": {"r1": {"value": 6}, "r2": {"value": 8}}},
        {"nodeLabel": "Feed", "paramKey": "ph", "varied": false,
         "perRun": {"r1": {"value": 7.0}, "r2": {"value": 7.0}}}
      ]
    },
    {
      "name": "missing_node_yields_null_cell",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Harvest", "params": {"day": 12}}}]}},
        {"id": "r2", "graph": {"nodes": []}}
      ],
      "expected": [
        {"nodeLabel": "Harvest", "paramKey": "day", "varied": true,
         "perRun": {"r1": {"value": 12}, "r2": {"value": null}}}
      ]
    },
    {
      "name": "float_with_trailing_zero_matches_int",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "pH", "params": {"target": 7}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "pH", "params": {"target": 7.0}}}]}}
      ],
      "expected": [
        {"nodeLabel": "pH", "paramKey": "target", "varied": false,
         "perRun": {"r1": {"value": 7}, "r2": {"value": 7.0}}}
      ]
    },
    {
      "name": "string_params_compare_canonically",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Buffer", "params": {"name": "Tris"}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Buffer", "params": {"name": "Tris"}}}]}},
        {"id": "r3", "graph": {"nodes": [{"id": "n3", "type": "unitOp",
          "data": {"label": "Buffer", "params": {"name": "PBS"}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Buffer", "paramKey": "name", "varied": true,
         "perRun": {"r1": {"value": "Tris"}, "r2": {"value": "Tris"},
                    "r3": {"value": "PBS"}}}
      ]
    },
    {
      "name": "boolean_and_null_distinct",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Sparge", "params": {"enabled": true}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Sparge", "params": {"enabled": false}}}]}},
        {"id": "r3", "graph": {"nodes": [{"id": "n3", "type": "unitOp",
          "data": {"label": "Sparge", "params": {"enabled": null}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Sparge", "paramKey": "enabled", "varied": true,
         "perRun": {"r1": {"value": true}, "r2": {"value": false},
                    "r3": {"value": null}}}
      ]
    },
    {
      "name": "nested_object_param",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Sparge",
            "params": {"gas": {"o2": 21, "co2": 5}}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Sparge",
            "params": {"gas": {"o2": 30, "co2": 5}}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Sparge", "paramKey": "gas", "varied": true,
         "perRun": {"r1": {"value": {"o2": 21, "co2": 5}},
                    "r2": {"value": {"o2": 30, "co2": 5}}}}
      ]
    },
    {
      "name": "unit_conflict_flagged",
      "runs": [
        {"id": "r1", "graph": {"nodes": [{"id": "n1", "type": "unitOp",
          "data": {"label": "Feed",
            "params": {"glucose": 6},
            "paramSchema": {"properties": {"glucose": {"unit": "g/L"}}}}}]}},
        {"id": "r2", "graph": {"nodes": [{"id": "n2", "type": "unitOp",
          "data": {"label": "Feed",
            "params": {"glucose": 6},
            "paramSchema": {"properties": {"glucose": {"unit": "mg/mL"}}}}}]}}
      ],
      "expected": [
        {"nodeLabel": "Feed", "paramKey": "glucose", "varied": true,
         "unitConflict": true,
         "perRun": {"r1": {"value": 6, "unit": "g/L"},
                    "r2": {"value": 6, "unit": "mg/mL"}}}
      ]
    }
  ]
}
```

Both Python `compute_conditions` and frontend `computeConditions` MUST consume this fixture. The `unit_conflict_flagged` scenario forces both implementations to surface heterogeneous units instead of silently coalescing — when a key appears with conflicting units across runs, set `varied=true` AND `unitConflict=true` on the row.

- [ ] **Step 2: Write the failing parity test**

`backend/tests/unit/services/experiments/test_conditions_parity.py`:

```python
"""F-0043 — Python port of computeConditions matches frontend output."""

import json
from pathlib import Path

import pytest

from app.services.experiments.conditions import compute_conditions

FIXTURE = Path(__file__).parents[3] / "fixtures" / "conditions_parity.json"


@pytest.mark.parametrize(
    "scenario",
    json.loads(FIXTURE.read_text())["scenarios"],
    ids=lambda s: s["name"],
)
def test_parity(scenario):
    actual = compute_conditions(scenario["runs"])
    # Normalize to a comparable shape.
    actual_norm = [
        {
            "nodeLabel": row["nodeLabel"],
            "paramKey": row["paramKey"],
            "varied": row["varied"],
            "perRun": row["perRun"],
        }
        for row in actual
    ]
    assert actual_norm == scenario["expected"]
```

- [ ] **Step 3: Verify failure**

```bash
pytest tests/unit/services/experiments/test_conditions_parity.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `compute_conditions`**

`backend/app/services/experiments/conditions.py`:

```python
"""F-0043 — Python port of frontend computeConditions for PDF export.

Keep in lockstep with frontend/src/lib/experiments/conditions.ts. Parity is
locked by backend/tests/fixtures/conditions_parity.json — both this module
and the Vitest test consume it.

Equality MUST use `json.dumps(value, sort_keys=True, default=str)`, NOT
`repr()`. Python's `repr(7) == '7'` and `repr(7.0) == '7.0'` would split
trailing-zero floats from integers and fail the parity fixture. `json.dumps`
emits `7` and `7.0` consistently and serializes nested dicts deterministically.
"""

import json
from typing import Any


def _canonicalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return value


def _eq_key(value: Any) -> str:
    """Canonical equality key matching frontend `JSON.stringify(value)`."""
    return json.dumps(value, sort_keys=True, default=str)


def compute_conditions(runs: list[dict]) -> list[dict]:
    """Build the varied-param table from a list of runs (dicts)."""
    # Map of (nodeLabel, paramKey) -> {run_id: cell}
    per_key: dict[tuple[str, str], dict[str, dict]] = {}
    # Track every unit seen per key so we can flag conflicts.
    units_seen_per_key: dict[tuple[str, str], set[str]] = {}
    run_ids: list[str] = []

    for run in runs:
        run_id = run["id"]
        run_ids.append(run_id)
        nodes = (run.get("graph") or {}).get("nodes") or []
        for node in nodes:
            if node.get("type") != "unitOp":
                continue
            data = node.get("data") or {}
            label = data.get("label")
            params = data.get("params") or {}
            schema = (data.get("paramSchema") or {}).get("properties") or {}
            if not label:
                continue
            for k, v in params.items():
                key = (label, k)
                cell: dict[str, Any] = {"value": _canonicalize(v)}
                unit = schema.get(k, {}).get("unit") if isinstance(schema.get(k), dict) else None
                if unit:
                    cell["unit"] = unit
                    units_seen_per_key.setdefault(key, set()).add(unit)
                per_key.setdefault(key, {})[run_id] = cell

    rows: list[dict] = []
    for (label, k), per_run in per_key.items():
        filled = {rid: per_run.get(rid, {"value": None}) for rid in run_ids}
        units = units_seen_per_key.get((label, k), set())
        unit_conflict = len(units) > 1
        # If exactly one unit was observed, re-apply to cells missing it.
        if len(units) == 1:
            (only_unit,) = units
            for rid, cell in filled.items():
                if cell.get("value") is not None and "unit" not in cell:
                    cell["unit"] = only_unit
        values = {_eq_key(c["value"]) for c in filled.values()}
        row: dict[str, Any] = {
            "nodeLabel": label,
            "paramKey": k,
            "varied": len(values) > 1 or unit_conflict,
            "perRun": filled,
        }
        if unit_conflict:
            row["unitConflict"] = True
        rows.append(row)
    return rows
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/services/experiments/test_conditions_parity.py -v
```

Expected: 3 passing.

- [ ] **Step 6: Symlink fixture for frontend**

```bash
mkdir -p frontend/tests/fixtures
ln -sf ../../../backend/tests/fixtures/conditions_parity.json \
       frontend/tests/fixtures/conditions_parity.json
```

- [ ] **Step 7: Commit**

```bash
git add backend/tests/fixtures/conditions_parity.json \
        backend/app/services/experiments/conditions.py \
        backend/tests/unit/services/experiments/test_conditions_parity.py \
        frontend/tests/fixtures/conditions_parity.json
git commit -m "feat(F-0043): conditions parity fixture + Python port"
```

---

## Task 12: PDF export service + endpoint

**Files:**
- Create: `backend/app/services/experiments/pdf_export.py`
- Modify: `backend/app/api/endpoints/experiments.py`
- Modify: `backend/tests/integration/api/test_experiments_phase_4_7.py`

- [ ] **Step 1: Write failing endpoint test**

Append to `test_experiments_phase_4_7.py`:

```python
@pytest.mark.asyncio
async def test_export_pdf_returns_pdf_with_lock_signature(
    client, locked_experiment, auth_headers
):
    res = await client.get(
        f"/experiments/{locked_experiment.id}/export.pdf",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000  # non-trivial PDF
    assert res.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_export_pdf_503_on_timeout(
    client, locked_experiment, auth_headers, monkeypatch
):
    import asyncio
    from app.services.experiments import pdf_export

    def slow(*args, **kwargs):
        import time
        time.sleep(31)
        return b""

    monkeypatch.setattr(pdf_export, "generate_experiment_pdf", slow)
    monkeypatch.setattr(
        "app.api.endpoints.experiments.EXPORT_TIMEOUT_SECONDS", 0.5
    )

    res = await client.get(
        f"/experiments/{locked_experiment.id}/export.pdf",
        headers=auth_headers,
    )
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "EXPORT_TIMEOUT"
```

- [ ] **Step 2: Verify failure**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -k export -v
```

Expected: FAILs (route + module missing).

- [ ] **Step 3: Implement PDF service**

`backend/app/services/experiments/pdf_export.py`:

```python
"""F-0043 — synchronous PDF export for an experiment summary.

CPU-bound fpdf2 work. Endpoint wraps the call in asyncio.to_thread +
asyncio.wait_for so the event loop and HTTP worker stay responsive.

Unicode-safe: biotech content uses µ, °, ±, Δ, β routinely. We register
DejaVuSans (shipped under `backend/app/static/fonts/DejaVuSans*.ttf` — copy
from a system install if absent) and use it for every cell. Helvetica is
Latin-1 only and would mojibake or raise on the first µ.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from fpdf import FPDF

from app.services.experiments.conditions import compute_conditions

_FONT_DIR = Path(__file__).resolve().parents[2] / "static" / "fonts"


def _make_pdf() -> FPDF:
    pdf = FPDF()
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.add_font("DejaVu", "I", str(_FONT_DIR / "DejaVuSans-Oblique.ttf"))
    return pdf


def _header(pdf: FPDF, experiment) -> None:
    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, f"Experiment: {experiment.name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(
        0, 6,
        f"Slug: {experiment.slug}  •  Exported: {datetime.utcnow().isoformat()}Z",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)


def _objective(pdf: FPDF, experiment) -> None:
    if not experiment.objective:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Objective", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(0, 5, experiment.objective)
    if experiment.success_criteria:
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 6, "Success criteria:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 10)
        for c in experiment.success_criteria:
            pdf.cell(0, 5, f"  • {c}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _conditions(pdf: FPDF, runs: Iterable[Any]) -> None:
    rows = compute_conditions(
        [{"id": str(r.id), "graph": r.graph or {}} for r in runs]
    )
    varied = [row for row in rows if row["varied"]]
    if not varied:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Conditions (varied parameters)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for row in varied:
        line = f"{row['nodeLabel']} / {row['paramKey']}: " + ", ".join(
            f"{rid}={c['value']}{(' ' + c['unit']) if c.get('unit') else ''}"
            for rid, c in row["perRun"].items()
        )
        pdf.multi_cell(0, 5, line)
    pdf.ln(4)


def _key_results(pdf: FPDF, runs: Iterable[Any]) -> None:
    with_kr = [r for r in runs if r.key_result_value is not None]
    if not with_kr:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Key results", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    best = max(with_kr, key=lambda r: r.key_result_value)
    for r in sorted(with_kr, key=lambda r: r.key_result_value, reverse=True):
        suffix = " (best)" if r.id == best.id else ""
        unit = f" {r.key_result_unit}" if r.key_result_unit else ""
        pdf.cell(
            0, 5,
            f"  {r.name}: {r.key_result_label} = {r.key_result_value}{unit}{suffix}",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.ln(4)


def _conclusion(pdf: FPDF, experiment) -> None:
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Conclusion", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    if experiment.conclusion_locked_at:
        pdf.multi_cell(0, 5, experiment.conclusion or "")
        pdf.ln(2)
        pdf.set_font("DejaVu", "I", 9)
        signer = experiment.conclusion_locked_by_name or "system"
        pdf.cell(
            0, 5,
            f"Locked by {signer} on {experiment.conclusion_locked_at.isoformat()}",
            new_x="LMARGIN", new_y="NEXT",
        )
    else:
        pdf.set_text_color(180, 90, 0)
        pdf.cell(0, 5, "Not yet locked — draft", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        if experiment.conclusion:
            pdf.multi_cell(0, 5, experiment.conclusion)
    pdf.ln(4)


def _observations(pdf: FPDF, observations: list[dict]) -> None:
    if not observations:
        return
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 8, "Observations", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for o in observations:
        flag = (o["flag"] or "").upper()
        ts = o["created_at"]
        body = o.get("body") or ""
        run = f" ({o['run_label']})" if o.get("run_label") else ""
        pdf.multi_cell(0, 4, f"[{flag}] {ts}{run} — {body}")
    pdf.ln(2)


def generate_experiment_pdf(experiment, runs: list[Any], observations: list[dict]) -> bytes:
    """Render the experiment summary to a PDF byte string.

    Synchronous and CPU-bound — caller is responsible for asyncio.to_thread.
    """
    pdf = _make_pdf()
    pdf.add_page()
    _header(pdf, experiment)
    _objective(pdf, experiment)
    _conditions(pdf, runs)
    _key_results(pdf, runs)
    _conclusion(pdf, experiment)
    _observations(pdf, observations)
    out = pdf.output(dest="S")
    return bytes(out) if not isinstance(out, bytes) else out
```

Note on font assets: copy `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`, `DejaVuSans-Oblique.ttf` from a system install (`/usr/share/fonts/truetype/dejavu/` on Debian) into `backend/app/static/fonts/`. Add the directory to `git add` so production deploys carry the font. The repo deliberately avoids `pdf_base` here — that module is document-conversion focused and doesn't expose a reusable Latin-9-safe writer.

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/endpoints/experiments.py`:

```python
import asyncio
import logging
import time
from fastapi.responses import Response
from app.services.experiments.pdf_export import generate_experiment_pdf
from app.services.experiments.observations import aggregate_observations

EXPORT_TIMEOUT_SECONDS = 30.0
_log = logging.getLogger(__name__)


@router.get("/experiments/{experiment_id}/export.pdf")
async def export_experiment_pdf(
    experiment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    exp = await get_or_404(db, Experiment, experiment_id)
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, exp.project_id, PermissionLevel.READ,
    )
    if not allowed:
        raise HTTPException(403, "Not allowed")

    # Project only the columns the PDF actually consumes. Run.notes and
    # Run.execution_data can be megabytes of JSONB per row — never load them
    # for an export that doesn't read them. ORDER BY locks byte-stable output
    # so two consecutive exports of a locked experiment produce identical PDFs
    # (regulators and tests both rely on this).
    runs_result = await db.execute(
        select(
            Run.id,
            Run.name,
            Run.graph,
            Run.status,
            Run.key_result_label,
            Run.key_result_value,
            Run.key_result_unit,
            Run.created_at,
        )
        .where(Run.experiment_id == experiment_id)
        .order_by(Run.created_at, Run.id)
    )
    runs = list(runs_result.all())

    obs = await aggregate_observations(db, experiment_id)
    obs_items = [
        {
            "flag": o.flag,
            "created_at": o.created_at.isoformat(),
            "body": o.body,
            "run_label": o.run_label,
        }
        for o in obs.items
    ]

    started = time.monotonic()
    try:
        content = await asyncio.wait_for(
            asyncio.to_thread(generate_experiment_pdf, exp, runs, obs_items),
            timeout=EXPORT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _log.warning(
            "pdf_export_timeout experiment_id=%s timeout_s=%s elapsed_ms=%d",
            experiment_id, EXPORT_TIMEOUT_SECONDS, elapsed_ms,
        )
        # Audit timeouts too — they are user-visible export failures and
        # appear in inspection histories.
        await log_audit(
            db,
            actor_id=user.id,
            action="export.pdf.timeout",
            entity_type="Experiment",
            entity_id=exp.id,
            changes={"timeout_s": EXPORT_TIMEOUT_SECONDS,
                     "elapsed_ms": elapsed_ms},
        )
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={"code": "EXPORT_TIMEOUT", "message": "PDF generation timed out"},
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    _log.info(
        "pdf_export_ok experiment_id=%s bytes=%d duration_ms=%d",
        experiment_id, len(content), duration_ms,
    )

    await log_audit(
        db,
        actor_id=user.id,
        action="export.pdf",
        entity_type="Experiment",
        entity_id=exp.id,
        changes={"bytes": len(content), "duration_ms": duration_ms},
    )
    await db.commit()

    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="experiment-{exp.slug}.pdf"',
        },
    )
```

Note: because `select(...columns...)` returns row tuples rather than `Run` instances, the PDF service must accept the tuple shape. Update `_conditions`, `_key_results`, etc. to read `r.graph`, `r.key_result_value`, etc. (the projected attributes still work via row attribute access).

- [ ] **Step 5: Run tests**

```bash
pytest tests/integration/api/test_experiments_phase_4_7.py -k export -v
```

Expected: 2 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/experiments/pdf_export.py \
        backend/app/api/endpoints/experiments.py \
        backend/tests/integration/api/test_experiments_phase_4_7.py
git commit -m "feat(F-0043): synchronous PDF export with 30s timeout guard"
```

---

## Task 13: Frontend Zod schemas + theme

**Files:**
- Modify: `frontend/src/lib/schemas/experiments.ts`
- Modify: `frontend/src/lib/schemas/runs.ts`
- Create: `frontend/src/lib/schemas/observation.ts`
- Modify: `frontend/src/lib/components/project/projectUtils.ts`

- [ ] **Step 1: Widen `LifecycleStatusEnum` and extend `ExperimentSchema`**

In `frontend/src/lib/schemas/experiments.ts`, replace the `LifecycleStatusEnum` (line 10) with:

```typescript
// Rolling-deploy safety: an old tab loaded before the deploy still holds the
// previous bundle (with the 4-state enum) while the backend has already shipped
// the 5-state contract. A strict z.enum() would throw on the first observed
// AWAITING_CONCLUSION. Use z.string() in dev/prod and let unknown values pass
// through; runtime code branches with switch statements that already have a
// default case. Vitest tests still get the strict enum via the exported type.
export const LifecycleStatusValues = [
    'DRAFT', 'IN_PROGRESS', 'AWAITING_CONCLUSION', 'COMPLETE', 'ARCHIVED',
] as const;
export type LifecycleStatus = (typeof LifecycleStatusValues)[number];
export const LifecycleStatusEnum = z.string().transform(
    (s) => s.toUpperCase() as LifecycleStatus,
);
```

This widening is the ONLY place where forward-compat needs special handling — every consumer goes through `experimentStatusLabel/Classes/Tooltip` which already has a `default:` arm, so an unrecognized server-side status will degrade to "Draft" styling rather than crash the page.

In `ExperimentSchema` (line 30), add after `created_by_id`:

```typescript
    conclusion: z.string().nullable().optional(),
    conclusion_locked_at: z.string().nullable().optional(),
    conclusion_locked_by_id: uuidString().nullable().optional(),
    conclusion_locked_by_name: z.string().nullable().optional(),
```

- [ ] **Step 2: Extend `RunSchema`**

In `frontend/src/lib/schemas/runs.ts` (`RunSchema` ~line 41), add three fields:

```typescript
    key_result_label: z.string().nullable().optional(),
    key_result_value: z.number().nullable().optional(),
    key_result_unit: z.string().nullable().optional(),
```

- [ ] **Step 3: Create `observation.ts`**

`frontend/src/lib/schemas/observation.ts`:

```typescript
import { z } from 'zod';
import { uuidString } from './common';

export const ObservationFlagEnum = z.enum(['observation', 'anomaly']);
export type ObservationFlag = z.infer<typeof ObservationFlagEnum>;

export const ObservationItemSchema = z.object({
    id: z.string(),
    source: z.enum(['experiment', 'run']),
    source_id: uuidString(),
    run_label: z.string().nullable().optional(),
    flag: ObservationFlagEnum,
    body: z.string(),
    author_name: z.string(),
    created_at: z.string(),
}).passthrough();

export type ObservationItem = z.infer<typeof ObservationItemSchema>;

export const ObservationsResponseSchema = z.object({
    items: z.array(ObservationItemSchema).default([]),
    truncated: z.boolean().default(false),
}).passthrough();

export type ObservationsResponse = z.infer<typeof ObservationsResponseSchema>;
```

Add to `frontend/src/lib/schemas/index.ts` the re-export `export * from './observation';`.

- [ ] **Step 4: Update theme utilities**

In `frontend/src/lib/components/project/projectUtils.ts`, replace `experimentStatusClasses` and `experimentStatusLabel`:

```typescript
export function experimentStatusClasses(status: string): string {
    switch (status?.toUpperCase()) {
        case "IN_PROGRESS":
            return "bg-primary/10 text-primary border border-primary/20";
        case "AWAITING_CONCLUSION":
            return "bg-amber-100 text-amber-900 border border-amber-300";
        case "COMPLETE":
            return "bg-accent/15 text-accent-foreground border border-accent/30";
        case "ARCHIVED":
            return "bg-muted text-muted-foreground border border-border";
        case "DRAFT":
        default:
            return "bg-muted text-muted-foreground border border-border";
    }
}

export function experimentStatusLabel(status: string): string {
    switch (status?.toUpperCase()) {
        case "IN_PROGRESS":
            return "In progress";
        case "AWAITING_CONCLUSION":
            return "Awaiting conclusion";
        case "COMPLETE":
            return "Complete";
        case "ARCHIVED":
            return "Archived";
        case "DRAFT":
        default:
            return "Draft";
    }
}

export function experimentStatusTooltip(status: string): string | undefined {
    if (status?.toUpperCase() === "AWAITING_CONCLUSION") {
        return "Status is derived from runs and the conclusion lock — all runs complete, conclusion not locked yet.";
    }
    return undefined;
}
```

- [ ] **Step 5: Run type-check**

```bash
cd frontend && npm run check
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/schemas/experiments.ts \
        frontend/src/lib/schemas/runs.ts \
        frontend/src/lib/schemas/observation.ts \
        frontend/src/lib/schemas/index.ts \
        frontend/src/lib/components/project/projectUtils.ts
git commit -m "feat(F-0043): Zod schemas + theme tokens for AWAITING_CONCLUSION"
```

---

## Task 14: `computeConditions` (frontend) + parity test

**Files:**
- Create: `frontend/src/lib/experiments/conditions.ts`
- Create: `frontend/tests/lib/experiments/conditions.test.ts`

- [ ] **Step 1: Write failing parity test**

`frontend/tests/lib/experiments/conditions.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import fixture from '../../fixtures/conditions_parity.json';
import { computeConditions } from '$lib/experiments/conditions';

describe('computeConditions parity', () => {
    for (const scenario of fixture.scenarios) {
        it(scenario.name, () => {
            const actual = computeConditions(scenario.runs as any);
            const normalized = actual.map(row => ({
                nodeLabel: row.nodeLabel,
                paramKey: row.paramKey,
                varied: row.varied,
                perRun: Object.fromEntries(row.perRun),
            }));
            expect(normalized).toEqual(scenario.expected);
        });
    }
});
```

- [ ] **Step 2: Verify failure**

```bash
cd frontend && npm run test -- conditions.test.ts
```

Expected: module not found.

- [ ] **Step 3: Implement**

`frontend/src/lib/experiments/conditions.ts`:

```typescript
type RunId = string;

export type CondCell = { value: unknown; unit?: string };
export type CondRow = {
    nodeLabel: string;
    paramKey: string;
    varied: boolean;
    unitConflict?: boolean;
    perRun: Map<RunId, CondCell>;
};

function canonicalize(value: unknown): unknown {
    if (value === null || value === undefined) return null;
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed === '' ? null : trimmed;
    }
    return value;
}

// Equality key must match the Python port's json.dumps(sort_keys=True). For
// JSON-serializable values JSON.stringify is sufficient, but objects must be
// sorted to match Python's sort_keys=True.
function eqKey(value: unknown): string {
    return JSON.stringify(value, (_k, v) => {
        if (v && typeof v === 'object' && !Array.isArray(v)) {
            return Object.keys(v as object).sort().reduce<Record<string, unknown>>(
                (acc, k) => { acc[k] = (v as Record<string, unknown>)[k]; return acc; },
                {},
            );
        }
        return v;
    });
}

export function computeConditions(runs: any[]): CondRow[] {
    const perKey = new Map<string, Map<RunId, CondCell>>();
    const unitsSeen = new Map<string, Set<string>>();
    const runIds: RunId[] = [];

    for (const run of runs) {
        const runId: RunId = run.id;
        runIds.push(runId);
        const nodes = run.graph?.nodes ?? [];
        for (const node of nodes) {
            if (node.type !== 'unitOp') continue;
            const label = node.data?.label;
            const params = node.data?.params ?? {};
            const schemaProps = node.data?.paramSchema?.properties ?? {};
            if (!label) continue;
            for (const [k, v] of Object.entries(params)) {
                const key = `${label}::${k}`;
                const cell: CondCell = { value: canonicalize(v) };
                const unit = schemaProps[k]?.unit;
                if (unit) {
                    cell.unit = unit;
                    let seen = unitsSeen.get(key);
                    if (!seen) { seen = new Set(); unitsSeen.set(key, seen); }
                    seen.add(unit);
                }
                let perRun = perKey.get(key);
                if (!perRun) {
                    perRun = new Map();
                    perKey.set(key, perRun);
                }
                perRun.set(runId, cell);
            }
        }
    }

    const rows: CondRow[] = [];
    for (const [key, perRun] of perKey) {
        const [nodeLabel, paramKey] = key.split('::');
        const filled = new Map<RunId, CondCell>();
        for (const rid of runIds) {
            filled.set(rid, perRun.get(rid) ?? { value: null });
        }
        const units = unitsSeen.get(key) ?? new Set<string>();
        const unitConflict = units.size > 1;
        if (units.size === 1) {
            const [onlyUnit] = units;
            for (const cell of filled.values()) {
                if (cell.value !== null && cell.unit === undefined) cell.unit = onlyUnit;
            }
        }
        const values = new Set(Array.from(filled.values(), c => eqKey(c.value)));
        rows.push({
            nodeLabel,
            paramKey,
            varied: values.size > 1 || unitConflict,
            ...(unitConflict ? { unitConflict: true } : {}),
            perRun: filled,
        });
    }
    return rows;
}
```

- [ ] **Step 4: Run test**

```bash
npm run test -- conditions.test.ts
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/experiments/conditions.ts \
        frontend/tests/lib/experiments/conditions.test.ts
git commit -m "feat(F-0043): frontend computeConditions with parity test"
```

---

## Task 15: `ConditionsTable.svelte`

**Files:**
- Create: `frontend/src/lib/components/experiment/ConditionsTable.svelte`
- Create: `frontend/tests/lib/components/experiment/ConditionsTable.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/tests/lib/components/experiment/ConditionsTable.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ConditionsTable from '$lib/components/experiment/ConditionsTable.svelte';

const runs = [
    {id: 'r1', name: 'RUN-1', graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 6}}}]}},
    {id: 'r2', name: 'RUN-2', graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 8}}}]}},
];

describe('ConditionsTable', () => {
    it('renders varied rows only by default', () => {
        const { getByText, queryByText } = render(ConditionsTable, { props: { runs } });
        expect(getByText('Feed')).toBeTruthy();
        expect(getByText('glucose')).toBeTruthy();
    });

    it('first column is sticky', () => {
        const { container } = render(ConditionsTable, { props: { runs } });
        const firstCol = container.querySelector('th.sticky-left');
        expect(firstCol).toBeTruthy();
    });
});
```

- [ ] **Step 2: Verify failure**

```bash
cd frontend && npm run test -- ConditionsTable.test.ts
```

Expected: component not found.

- [ ] **Step 3: Implement**

`frontend/src/lib/components/experiment/ConditionsTable.svelte`:

```svelte
<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions, type CondRow } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props {
    runs: Run[];
}
let { runs }: Props = $props();

let showConstants = $state(false);

const allRows: CondRow[] = $derived(computeConditions(runs as any));
const visibleRows: CondRow[] = $derived(
    showConstants ? allRows : allRows.filter(r => r.varied)
);
const runColumns = $derived(runs.map(r => ({ id: r.id, name: r.name })));
const groupedByStep = $derived(() => {
    const groups = new Map<string, CondRow[]>();
    for (const r of visibleRows) {
        const list = groups.get(r.nodeLabel) ?? [];
        list.push(r);
        groups.set(r.nodeLabel, list);
    }
    return Array.from(groups, ([label, rows]) => ({ label, rows }));
});
</script>

<Card>
    <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle>Conditions</CardTitle>
        <label class="text-sm flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showConstants} />
            Show constants
        </label>
    </CardHeader>
    <CardContent>
        {#if runs.length === 0}
            <EmptyState title="No runs yet"
                description="Add a run to populate the design matrix." />
        {:else if visibleRows.length === 0}
            <EmptyState title="All parameters match"
                description="No varied parameters across runs." />
        {:else}
            <div class="overflow-x-auto">
                <table class="conditions-table">
                    <thead>
                        <tr>
                            <th class="sticky-left">Step / Parameter</th>
                            {#each runColumns as col}
                                <th>{col.name}</th>
                            {/each}
                        </tr>
                    </thead>
                    <tbody>
                        {#each groupedByStep() as group}
                            <tr class="group-row">
                                <td class="sticky-left font-medium" colspan={1 + runColumns.length}>
                                    {group.label}
                                </td>
                            </tr>
                            {#each group.rows as row}
                                <tr>
                                    <td class="sticky-left">
                                        {row.paramKey}
                                        {#if row.varied}<span class="varied-dot"></span>{/if}
                                        {#if row.unitConflict}
                                            <span class="unit-conflict" title="Unit mismatch across runs">⚠ unit mismatch</span>
                                        {/if}
                                    </td>
                                    {#each runColumns as col}
                                        {@const cell = row.perRun.get(col.id)}
                                        <td class="font-mono text-sm">
                                            {#if cell?.value == null}
                                                —
                                            {:else}
                                                {cell.value}{cell.unit ? ` ${cell.unit}` : ''}
                                            {/if}
                                        </td>
                                    {/each}
                                </tr>
                            {/each}
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}
    </CardContent>
</Card>

<style>
.conditions-table {
    width: 100%;
    border-collapse: collapse;
}
.conditions-table th, .conditions-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
    text-align: left;
}
.sticky-left {
    position: sticky;
    left: 0;
    z-index: 2;
    background: var(--card);
}
.varied-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 3px;
    background: var(--accent);
    margin-left: 4px;
}
.unit-conflict {
    margin-left: 6px;
    font-size: 0.7rem;
    color: var(--destructive);
}
</style>
```
```

- [ ] **Step 4: Re-run test**

```bash
npm run test -- ConditionsTable.test.ts
```

Expected: passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/experiment/ConditionsTable.svelte \
        frontend/tests/lib/components/experiment/ConditionsTable.test.ts
git commit -m "feat(F-0043): ConditionsTable with sticky first column"
```

---

## Task 16: `KeyResultsTable.svelte` + `RunKeyResultFields.svelte`

**Files:**
- Create: `frontend/src/lib/components/experiment/KeyResultsTable.svelte`
- Create: `frontend/src/lib/components/run/RunKeyResultFields.svelte`

- [ ] **Step 1: Implement `KeyResultsTable.svelte`**

Uses shadcn `<Card>` (not the non-existent `.card` class), `--muted-fg` (not `--muted-foreground` — neither exists in `app.css`), `--accent-fg` (not `--accent-foreground`), and `<EmptyState>`. Adds a Condition column showing each run's varied parameters so the table tells the experimentalist story without forcing a jump up to ConditionsTable. Delta % is computed against the **lowest** value (baseline) rather than the median — for a 2-run experiment median and min coincide; for 3+ runs experimentalists read deltas relative to a control, not to a middle value.

```svelte
<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props { runs: Run[]; }
let { runs }: Props = $props();

const withResult = $derived(
    runs.filter(r => r.key_result_value != null)
        .sort((a, b) => (b.key_result_value ?? 0) - (a.key_result_value ?? 0))
);

// Baseline = the smallest reported value. Each row's delta% is reported
// relative to this baseline (NOT a median): more intuitive when comparing
// against a control, and stable as runs are added.
const baseline = $derived(
    withResult.length === 0
        ? null
        : Math.min(...withResult.map(r => r.key_result_value!))
);

const best = $derived(withResult[0]);

const condByRun = $derived(() => {
    const rows = computeConditions(runs as any).filter(r => r.varied);
    const m = new Map<string, string>();
    for (const r of runs) {
        const parts: string[] = [];
        for (const row of rows) {
            const cell = row.perRun.get(r.id);
            if (cell?.value != null) {
                parts.push(`${row.paramKey}=${cell.value}${cell.unit ? ' ' + cell.unit : ''}`);
            }
        }
        m.set(r.id, parts.join(', '));
    }
    return m;
});

function deltaPct(value: number): string {
    if (baseline === null || baseline === 0) return '';
    const pct = ((value - baseline) / baseline) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`;
}
</script>

<Card>
    <CardHeader>
        <CardTitle>Key results</CardTitle>
    </CardHeader>
    <CardContent>
        {#if withResult.length === 0}
            <EmptyState title="No key results yet"
                description="Enter a key result on each run's detail page." />
        {:else}
            <table class="w-full">
                <thead>
                    <tr><th>Run</th><th>Condition</th><th>Label</th><th>Value</th><th>vs. baseline</th></tr>
                </thead>
                <tbody>
                    {#each withResult as r}
                        <tr class:best={r.id === best.id}>
                            <td>{r.name}</td>
                            <td class="text-sm text-muted-fg">{condByRun().get(r.id) ?? ''}</td>
                            <td>{r.key_result_label}</td>
                            <td class="font-mono">
                                {r.key_result_value}{r.key_result_unit ? ` ${r.key_result_unit}` : ''}
                            </td>
                            <td>
                                <span class="text-xs text-muted-fg">{deltaPct(r.key_result_value!)}</span>
                                {#if r.id === best.id}
                                    <span class="tag-best ml-2">best</span>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    </CardContent>
</Card>

<style>
.best { background: color-mix(in oklch, var(--accent) 8%, transparent); }
.tag-best { font-size: 0.75rem; color: var(--accent-fg); }
</style>
```

- [ ] **Step 2: Implement `RunKeyResultFields.svelte`**

Uses shadcn `<Input>` (no `.input` class exists). Layout uses Tailwind `grid-cols-1 sm:grid-cols-3 gap-3` so the three fields stack on tablet portrait (`<sm`) and side-by-side on desktop — the fixed `[1fr_1fr_120px]` columns from the original draft squeeze the Value cell on iPad.

```svelte
<script lang="ts">
import { Input } from '$lib/components/ui/input';

interface Props {
    label: string | null | undefined;
    value: number | null | undefined;
    unit: string | null | undefined;
    onChange: (next: { label: string | null; value: number | null; unit: string | null }) => void;
}
let { label, value, unit, onChange }: Props = $props();

let localLabel = $state(label ?? '');
let localValue = $state(value?.toString() ?? '');
let localUnit = $state(unit ?? '');

function emit() {
    const parsed = localValue.trim() === '' ? null : Number(localValue);
    onChange({
        label: localLabel.trim() === '' ? null : localLabel.trim(),
        value: parsed != null && Number.isFinite(parsed) ? parsed : null,
        unit: localUnit.trim() === '' ? null : localUnit.trim(),
    });
}
</script>

<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
    <label class="text-sm">
        Label
        <Input bind:value={localLabel} onblur={emit} placeholder="e.g. Titer" />
    </label>
    <label class="text-sm">
        Value
        <Input type="number" step="any" bind:value={localValue} onblur={emit} />
    </label>
    <label class="text-sm">
        Unit
        <Input bind:value={localUnit} onblur={emit} placeholder="g/L" />
    </label>
</div>
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npm run check
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/experiment/KeyResultsTable.svelte \
        frontend/src/lib/components/run/RunKeyResultFields.svelte
git commit -m "feat(F-0043): KeyResultsTable + RunKeyResultFields"
```

---

## Task 17: `KeyResultsChart.svelte`

**Files:**
- Create: `frontend/src/lib/components/experiment/KeyResultsChart.svelte`
- Create: `frontend/tests/lib/components/experiment/KeyResultsChart.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import KeyResultsChart from '$lib/components/experiment/KeyResultsChart.svelte';

const runs = [
    {id: 'r1', name: 'RUN-1', key_result_value: 4.2,
     graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 6}}}]}},
    {id: 'r2', name: 'RUN-2', key_result_value: 5.0,
     graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 8}}}]}},
];

describe('KeyResultsChart', () => {
    it('renders one circle per run with key_result_value', () => {
        const { container } = render(KeyResultsChart, { props: { runs } });
        expect(container.querySelectorAll('circle').length).toBe(2);
    });

    it('best run has accent class', () => {
        const { container } = render(KeyResultsChart, { props: { runs } });
        expect(container.querySelector('circle.best')).toBeTruthy();
    });

    it('each circle has a <title> for tap-to-identify', () => {
        const { container } = render(KeyResultsChart, { props: { runs } });
        const titles = container.querySelectorAll('circle title');
        expect(titles.length).toBe(2);
    });
});
```

- [ ] **Step 2: Verify failure**

```bash
npm run test -- KeyResultsChart.test.ts
```

- [ ] **Step 3: Implement**

```svelte
<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props { runs: Run[]; experimentId: string; }
let { runs, experimentId }: Props = $props();

const withResult = $derived(runs.filter(r => r.key_result_value != null));
const best = $derived(
    withResult.reduce<Run | null>(
        (acc, r) => (acc == null || r.key_result_value! > acc.key_result_value!) ? r : acc, null,
    )
);

const conditions = $derived(computeConditions(runs as any));
const variedNumeric = $derived(
    conditions.filter(r => r.varied && Array.from(r.perRun.values())
        .every(c => c.value === null || typeof c.value === 'number')),
);

const sessionKey = `kr-chart-axis:${experimentId}`;
let selectedKey = $state<string | null>(
    typeof window !== 'undefined' ? window.sessionStorage.getItem(sessionKey) : null,
);
const xAxis = $derived(
    variedNumeric.find(r => `${r.nodeLabel}::${r.paramKey}` === selectedKey)
        ?? variedNumeric[0],
);

function setAxis(k: string) {
    selectedKey = k;
    if (typeof window !== 'undefined') window.sessionStorage.setItem(sessionKey, k);
}

const points = $derived(() => {
    if (!xAxis) return [];
    return withResult
        .map(r => {
            const cell = xAxis.perRun.get(r.id);
            const x = typeof cell?.value === 'number' ? cell.value : null;
            return x == null ? null : { id: r.id, name: r.name, x, y: r.key_result_value! };
        })
        .filter((p): p is { id: string; name: string; x: number; y: number } => p !== null);
});

const W = 360, H = 220, PAD = 32;
function scaleX(v: number): number {
    const pts = points();
    if (pts.length === 0) return 0;
    const xs = pts.map(p => p.x);
    const min = Math.min(...xs), max = Math.max(...xs);
    if (min === max) return W / 2;
    return PAD + ((v - min) / (max - min)) * (W - 2 * PAD);
}
function scaleY(v: number): number {
    const pts = points();
    if (pts.length === 0) return 0;
    const ys = pts.map(p => p.y);
    const min = Math.min(...ys), max = Math.max(...ys);
    if (min === max) return H / 2;
    return H - PAD - ((v - min) / (max - min)) * (H - 2 * PAD);
}
</script>

{#snippet axisLabels()}
    <!-- numeric tick labels along the bottom (x) and left (y) axes -->
    {@const pts = points()}
    {@const xs = pts.map(p => p.x)}
    {@const ys = pts.map(p => p.y)}
    {@const xMin = Math.min(...xs)}
    {@const xMax = Math.max(...xs)}
    {@const yMin = Math.min(...ys)}
    {@const yMax = Math.max(...ys)}
    <text x={PAD} y={H - PAD + 12} class="tick" font-size="9">{xMin}</text>
    <text x={W - PAD} y={H - PAD + 12} class="tick" font-size="9" text-anchor="end">{xMax}</text>
    <text x={PAD - 6} y={H - PAD} class="tick" font-size="9" text-anchor="end">{yMin}</text>
    <text x={PAD - 6} y={PAD + 4} class="tick" font-size="9" text-anchor="end">{yMax}</text>
{/snippet}

{#snippet trendPath()}
    <!-- Dashed straight line from leftmost to rightmost point — explicitly
         labelled "smoothing hint, not a fit" in the legend below. -->
    {@const sorted = points().slice().sort((a, b) => a.x - b.x)}
    {#if sorted.length >= 2}
        <path d={`M ${scaleX(sorted[0].x)},${scaleY(sorted[0].y)} L ${scaleX(sorted[sorted.length - 1].x)},${scaleY(sorted[sorted.length - 1].y)}`}
              stroke="currentColor" stroke-dasharray="4 4" opacity="0.4" fill="none" />
    {/if}
{/snippet}

<script lang="ts">
let selectedPoint = $state<{ name: string; x: number; y: number } | null>(null);
function tapPoint(p: { id: string; name: string; x: number; y: number }) {
    selectedPoint = (selectedPoint?.name === p.name) ? null : { name: p.name, x: p.x, y: p.y };
}
</script>

<Card>
    <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle>Results — chart</CardTitle>
        {#if variedNumeric.length > 1}
            <select class="text-sm border rounded px-2 py-1"
                    onchange={e => setAxis((e.currentTarget as HTMLSelectElement).value)}>
                {#each variedNumeric as r}
                    <option value={`${r.nodeLabel}::${r.paramKey}`}
                            selected={xAxis && r.nodeLabel === xAxis.nodeLabel && r.paramKey === xAxis.paramKey}>
                        {r.nodeLabel} / {r.paramKey}
                    </option>
                {/each}
            </select>
        {/if}
    </CardHeader>

    <CardContent>
        {#if points().length === 0}
            <EmptyState title="Not enough data"
                description="Need at least two runs with a varied numeric param and a key result." />
        {:else}
            <div class="relative">
                <svg viewBox="0 0 {W} {H}" class="w-full" aria-label="Key results scatter chart">
                    <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="currentColor" opacity="0.4" />
                    <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="currentColor" opacity="0.4" />
                    {@render axisLabels()}
                    {@render trendPath()}
                    {#each points() as p}
                        <!-- SVG <title> doesn't fire on tablet tap — we use an
                             explicit onclick + a positioned label overlay so
                             field-mode users on iPad can identify points. -->
                        <circle cx={scaleX(p.x)} cy={scaleY(p.y)} r="6"
                                class:best={best && p.id === best.id}
                                onclick={() => tapPoint(p)}
                                fill={best && p.id === best.id ? 'var(--accent)' : 'var(--primary)'}>
                            <title>{p.name}: ({p.x}, {p.y})</title>
                        </circle>
                    {/each}
                </svg>
                {#if selectedPoint}
                    <div class="absolute top-2 right-2 bg-card border rounded px-2 py-1 text-xs shadow">
                        <strong>{selectedPoint.name}</strong>: ({selectedPoint.x}, {selectedPoint.y})
                    </div>
                {/if}
            </div>
            <p class="text-xs text-muted-fg mt-2">Dashed trend is a smoothing hint, not a fit.</p>
        {/if}
    </CardContent>
</Card>

<style>
.tick { fill: var(--muted-fg); }
</style>
```

- [ ] **Step 4: Run test + commit**

```bash
npm run test -- KeyResultsChart.test.ts
git add frontend/src/lib/components/experiment/KeyResultsChart.svelte \
        frontend/tests/lib/components/experiment/KeyResultsChart.test.ts
git commit -m "feat(F-0043): SVG scatter chart with tap-to-identify titles"
```

---

## Task 18: `ConclusionCard.svelte`

**Files:**
- Create: `frontend/src/lib/components/experiment/ConclusionCard.svelte`
- Create: `frontend/tests/lib/components/experiment/ConclusionCard.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ConclusionCard from '$lib/components/experiment/ConclusionCard.svelte';

const baseProps = {
    experiment: { id: 'e1', conclusion: '', conclusion_locked_at: null,
                  conclusion_locked_by_name: null } as any,
    hasOpenRuns: false,
    canAdmin: false,
    onSave: () => {},
    onLock: () => {},
    onUnlock: (_reason: string) => {},
};

describe('ConclusionCard', () => {
    it('disables Lock when body empty', () => {
        const { getByRole } = render(ConclusionCard, { props: baseProps });
        const btn = getByRole('button', { name: /lock/i });
        expect(btn.hasAttribute('disabled')).toBe(true);
    });

    it('disables Lock when runs are open', () => {
        const { getByRole } = render(ConclusionCard, {
            props: { ...baseProps,
                     experiment: { ...baseProps.experiment, conclusion: 'done' },
                     hasOpenRuns: true },
        });
        const btn = getByRole('button', { name: /lock/i });
        expect(btn.hasAttribute('disabled')).toBe(true);
    });

    it('hides admin unlock when canAdmin is false', () => {
        const { queryByRole } = render(ConclusionCard, {
            props: {
                ...baseProps,
                experiment: { ...baseProps.experiment, conclusion: 'x',
                              conclusion_locked_at: '2026-05-22T00:00:00Z',
                              conclusion_locked_by_name: 'Alice' },
                canAdmin: false,
            },
        });
        expect(queryByRole('button', { name: /unlock/i })).toBeNull();
    });

    it('blocks unlock submit until reason >= 8 chars', async () => {
        const { getByRole, getByLabelText } = render(ConclusionCard, {
            props: {
                ...baseProps,
                experiment: { ...baseProps.experiment, conclusion: 'x',
                              conclusion_locked_at: '2026-05-22T00:00:00Z',
                              conclusion_locked_by_name: 'Alice' },
                canAdmin: true,
            },
        });
        await fireEvent.click(getByRole('button', { name: /unlock/i }));
        const submit = getByRole('button', { name: /submit unlock/i });
        expect(submit.hasAttribute('disabled')).toBe(true);
        const ta = getByLabelText(/reason/i);
        await fireEvent.input(ta, { target: { value: 'short' } });
        expect(submit.hasAttribute('disabled')).toBe(true);
        await fireEvent.input(ta, { target: { value: 'long enough reason' } });
        expect(submit.hasAttribute('disabled')).toBe(false);
    });
});
```

- [ ] **Step 2: Implement**

Uses shadcn `<Card>`, `<Button variant="default|outline">`, `<Dialog>` (no hand-rolled `.modal`/`.btn-primary`/`.btn-outline` — those classes don't exist). Single Lock CTA in the card footer; remove the pre-textarea button + inline-reason `<span>` so the lock affordance is a single bottom-right action with the rationale surfaced as a tooltip on hover and an accessible note below. `ExportSummaryButton` is rendered in this card's footer per spec (Task 19 just defines the component; Task 18 places it).

```svelte
<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '$lib/components/ui/card';
import { Button } from '$lib/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '$lib/components/ui/dialog';
import ExportSummaryButton from './ExportSummaryButton.svelte';
import type { Experiment } from '$lib/schemas/experiments';

interface Props {
    experiment: Experiment;
    hasOpenRuns: boolean;
    canAdmin: boolean;
    onSave: (next: string) => void;
    onLock: () => void;
    onUnlock: (reason: string) => void;
}
let { experiment, hasOpenRuns, canAdmin, onSave, onLock, onUnlock }: Props = $props();

let draft = $state(experiment.conclusion ?? '');
let unlockOpen = $state(false);
let unlockReason = $state('');

const isLocked = $derived(experiment.conclusion_locked_at != null);
const lockDisabled = $derived(hasOpenRuns || draft.trim().length === 0);
const lockReason = $derived(
    hasOpenRuns
        ? 'Cannot lock — runs are still open.'
        : draft.trim().length === 0
        ? 'Cannot lock — conclusion is empty.'
        : ''
);
const unlockSubmitDisabled = $derived(unlockReason.trim().length < 8);

function saveDraft() {
    if (draft !== (experiment.conclusion ?? '')) onSave(draft);
}
function submitUnlock() {
    onUnlock(unlockReason.trim());
    unlockOpen = false;
    unlockReason = '';
}
</script>

<Card>
    <CardHeader>
        <CardTitle>Conclusion</CardTitle>
    </CardHeader>
    <CardContent>
        {#if !isLocked}
            {#if hasOpenRuns}
                <div class="warning mb-3">
                    <strong>Completion gate.</strong> Finish all runs before locking the conclusion.
                </div>
            {/if}

            <textarea class="w-full min-h-[160px] border rounded p-2"
                      bind:value={draft}
                      onblur={saveDraft}
                      placeholder="Write the conclusion of this investigation…" />
            {#if lockReason}
                <p class="mt-2 text-sm text-muted-fg" id="lock-reason">{lockReason}</p>
            {/if}
        {:else}
            <div class="prose whitespace-pre-wrap">{experiment.conclusion}</div>
            <div class="mt-3 text-sm text-muted-fg italic">
                Locked by {experiment.conclusion_locked_by_name ?? 'system'}
                on {new Date(experiment.conclusion_locked_at!).toLocaleString()}
            </div>
        {/if}
    </CardContent>

    <CardFooter class="flex items-center justify-between">
        <ExportSummaryButton experimentId={experiment.id} slug={experiment.slug ?? experiment.id} />

        {#if !isLocked}
            <Button variant="default"
                    disabled={lockDisabled}
                    title={lockReason}
                    aria-describedby={lockReason ? 'lock-reason' : undefined}
                    onclick={onLock}>
                Lock conclusion
            </Button>
        {:else if canAdmin}
            <Button variant="outline" onclick={() => unlockOpen = true}>
                Unlock and edit (admin only)
            </Button>
        {/if}
    </CardFooter>
</Card>

<Dialog bind:open={unlockOpen}>
    <DialogContent>
        <DialogHeader>
            <DialogTitle>Unlock conclusion</DialogTitle>
        </DialogHeader>
        <label for="unlock-reason" class="text-sm">
            Reason (required, ≥ 8 characters)
        </label>
        <textarea id="unlock-reason"
                  aria-label="Reason"
                  bind:value={unlockReason}
                  class="w-full border rounded p-2 min-h-[100px]"
                  placeholder="e.g. Updated titer data from re-analysis" />
        <DialogFooter>
            <Button variant="outline"
                    onclick={() => { unlockOpen = false; unlockReason = ''; }}>
                Cancel
            </Button>
            <Button variant="default"
                    aria-label="Submit unlock"
                    disabled={unlockSubmitDisabled}
                    onclick={submitUnlock}>
                Submit unlock
            </Button>
        </DialogFooter>
    </DialogContent>
</Dialog>

<style>
.warning {
    background: color-mix(in oklch, oklch(0.85 0.18 80) 30%, transparent);
    border: 1px solid oklch(0.7 0.18 80);
    padding: 0.75rem; border-radius: 0.5rem;
}
</style>
```

- [ ] **Step 3: Run tests + commit**

```bash
npm run test -- ConclusionCard.test.ts
git add frontend/src/lib/components/experiment/ConclusionCard.svelte \
        frontend/tests/lib/components/experiment/ConclusionCard.test.ts
git commit -m "feat(F-0043): ConclusionCard with admin-gated unlock dialog"
```

---

## Task 19: `ObservationsTimeline.svelte` + `ExportSummaryButton.svelte`

**Files:**
- Create: `frontend/src/lib/components/experiment/ObservationsTimeline.svelte`
- Create: `frontend/src/lib/components/experiment/ExportSummaryButton.svelte`

- [ ] **Step 1: Implement `ObservationsTimeline.svelte`**

```svelte
<script lang="ts">
import type { ObservationItem } from '$lib/schemas/observation';

interface Props {
    items: ObservationItem[];
    truncated: boolean;
    loading: boolean;
}
let { items, truncated, loading }: Props = $props();
</script>

Wraps shadcn `<Card>`. Each run_label becomes a link to `/runs/<source_id>` so the reader can jump from "anomaly on RUN-3" straight to that run. Uses `--muted-fg` (not the non-existent `--muted-foreground`).

```svelte
<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import type { ObservationItem } from '$lib/schemas/observation';

interface Props {
    items: ObservationItem[];
    truncated: boolean;
    loading: boolean;
}
let { items, truncated, loading }: Props = $props();
</script>

<aside class="sticky top-4">
    <Card>
        <CardHeader>
            <CardTitle>Observations</CardTitle>
        </CardHeader>
        <CardContent>
            {#if loading}
                <div class="text-sm text-muted-fg">Loading…</div>
            {:else if items.length === 0}
                <EmptyState title="Nothing flagged yet"
                    description="No observations or anomalies flagged yet." />
            {:else}
                <ol class="timeline">
                    {#each items as item (item.id)}
                        <li class="timeline-item">
                            <span class="flag" class:anomaly={item.flag === 'anomaly'}>
                                {item.flag}
                            </span>
                            <div>
                                <div class="text-sm">{item.body}</div>
                                <div class="text-xs text-muted-fg">
                                    {item.author_name} • {new Date(item.created_at).toLocaleString()}
                                    {#if item.source === 'run' && item.run_label}
                                        • <a class="underline" href={`/runs/${item.source_id}`}>{item.run_label}</a>
                                    {/if}
                                </div>
                            </div>
                        </li>
                    {/each}
                </ol>
                {#if truncated}
                    <div class="text-xs text-muted-fg mt-2">
                        Showing 500 most recent observations.
                    </div>
                {/if}
            {/if}
        </CardContent>
    </Card>
</aside>

<style>
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline-item {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-left: 2px solid var(--border);
    padding-left: 0.75rem;
    margin-left: 0.25rem;
}
.flag {
    font-size: 0.65rem;
    text-transform: uppercase;
    background: var(--muted);
    color: var(--muted-fg);
    padding: 0.1rem 0.35rem;
    border-radius: 0.25rem;
    height: fit-content;
}
.flag.anomaly {
    background: color-mix(in oklch, oklch(0.85 0.18 80) 30%, transparent);
    color: oklch(0.4 0.2 60);
}
</style>
```

- [ ] **Step 2: Implement `ExportSummaryButton.svelte`**

Uses shadcn `<Button variant="outline">` (no `.btn-outline` class). On failure the catch arm surfaces a toast via `$lib/components/ui/sonner` (the project's existing toast surface used in 12+ places). The component is rendered inside `ConclusionCard`'s footer (Task 18) — not as a standalone page surface.

```svelte
<script lang="ts">
import { Button } from '$lib/components/ui/button';
import { toast } from 'svelte-sonner';
import { api } from '$lib/api';

interface Props {
    experimentId: string;
    slug: string;
}
let { experimentId, slug }: Props = $props();

let busy = $state(false);

async function download() {
    busy = true;
    try {
        await api.downloadBlob(
            `/experiments/${experimentId}/export.pdf`,
            `experiment-${slug}.pdf`,
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : 'PDF export failed';
        toast.error(msg);
    } finally {
        busy = false;
    }
}
</script>

<Button variant="outline" disabled={busy} onclick={download}>
    {busy ? 'Generating…' : 'Export summary'}
</Button>
```

- [ ] **Step 3: Type-check + commit**

```bash
cd frontend && npm run check
git add frontend/src/lib/components/experiment/ObservationsTimeline.svelte \
        frontend/src/lib/components/experiment/ExportSummaryButton.svelte
git commit -m "feat(F-0043): ObservationsTimeline + ExportSummaryButton"
```

---

## Task 20: Wire the experiment detail page

**Files:**
- Modify: `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`

- [ ] **Step 1: Read current state and locate the layout block**

```bash
sed -n '1,60p' frontend/src/routes/\[org\]/projects/\[projectSlug\]/experiments/\[slug\]/+page.svelte
```

Inspect imports, props, and where the existing Runs / Notes sections live.

- [ ] **Step 2: Replace the body block with two-column layout**

In the same file, restructure the post-header content so the page renders:

```svelte
<script lang="ts">
// (existing imports preserved)
import ConditionsTable from '$lib/components/experiment/ConditionsTable.svelte';
import KeyResultsTable from '$lib/components/experiment/KeyResultsTable.svelte';
import KeyResultsChart from '$lib/components/experiment/KeyResultsChart.svelte';
import ConclusionCard from '$lib/components/experiment/ConclusionCard.svelte';
import ObservationsTimeline from '$lib/components/experiment/ObservationsTimeline.svelte';
import ExportSummaryButton from '$lib/components/experiment/ExportSummaryButton.svelte';
import { ObservationsResponseSchema, type ObservationItem } from '$lib/schemas/observation';
import { api } from '$lib/api';
import { onMount, onDestroy } from 'svelte';

import { toast } from 'svelte-sonner';
import { getCurrentOrgRoles } from '$lib/stores/org';  // existing helper

let observations = $state<ObservationItem[]>([]);
let observationsTruncated = $state(false);
let observationsLoading = $state(true);
let observationsError = $state<string | null>(null);

async function loadObservations() {
    observationsLoading = true;
    observationsError = null;
    try {
        const res = await api.get(
            `/experiments/${experiment.id}/observations`,
            { schema: ObservationsResponseSchema },
        );
        observations = res.items;
        observationsTruncated = res.truncated;
    } catch (err) {
        observationsError = err instanceof Error ? err.message : 'Failed to load observations';
    } finally {
        observationsLoading = false;
    }
}

async function loadRuns() {
    // Existing handler that re-fetches the experiment's runs. Define here if
    // the page doesn't already expose one; otherwise import.
    experiment = await api.get(`/experiments/${experiment.id}`, { schema: ExperimentSchema });
}

// Refresh on visibility change to catch cross-tab note + run edits.
function onVisible() {
    if (document.visibilityState === 'visible') {
        loadObservations();
        loadRuns();
    }
}
onMount(() => {
    loadObservations();
    document.addEventListener('visibilitychange', onVisible);
});
onDestroy(() => document.removeEventListener('visibilitychange', onVisible));

// Server is source of truth — derive runs from the loaded experiment so the
// page never reads `runs` before the fetch resolves.
const runs = $derived(experiment?.runs ?? []);
const hasOpenRuns = $derived(
    runs.some(r => ['PLANNED', 'ACTIVE', 'EDITED'].includes(r.status)),
);
// Admin role gating — `ADMIN` is the canonical org-role string; check
// `frontend/src/lib/stores/org.ts` for the exact label if changed.
const canAdmin = $derived(getCurrentOrgRoles().includes('ADMIN'));

async function saveConclusion(next: string) {
    try {
        const updated = await api.put(
            `/experiments/${experiment.id}`,
            { conclusion: next },
            { schema: ExperimentSchema },
        );
        experiment = updated;
    } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to save conclusion';
        toast.error(msg);
    }
}
async function lockConclusion() {
    try {
        experiment = await api.post(
            `/experiments/${experiment.id}/conclusion/lock`, {},
            { schema: ExperimentSchema },
        );
        loadObservations();
    } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to lock conclusion';
        toast.error(msg);
    }
}
async function unlockConclusion(reason: string) {
    try {
        experiment = await api.post(
            `/experiments/${experiment.id}/conclusion/unlock`, { reason },
            { schema: ExperimentSchema },
        );
        loadObservations();
    } catch (err) {
        const msg = err instanceof Error ? err.message : 'Failed to unlock conclusion';
        toast.error(msg);
    }
}
</script>

<div class="experiment-grid">
    <div class="main-col flex flex-col gap-4">
        <!-- existing Objective block stays here -->

        <ConditionsTable {runs} />

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <KeyResultsTable {runs} />
            <KeyResultsChart {runs} experimentId={experiment.id} />
        </div>

        <!-- ConclusionCard owns the ExportSummaryButton in its footer; do NOT
             render a separate ExportSummaryButton row above or below the card. -->
        <ConclusionCard
            {experiment}
            {hasOpenRuns}
            {canAdmin}
            onSave={saveConclusion}
            onLock={lockConclusion}
            onUnlock={unlockConclusion}
        />

        <!-- existing Runs and Notes sections stay below -->
    </div>

    <div>
        {#if observationsError}
            <div class="p-3 mb-2 border rounded bg-destructive/10 text-destructive text-sm">
                {observationsError}
                <button class="underline ml-2" onclick={loadObservations}>Retry</button>
            </div>
        {/if}
        <ObservationsTimeline
            items={observations}
            truncated={observationsTruncated}
            loading={observationsLoading}
        />
    </div>
</div>

<style>
.experiment-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
}
@media (min-width: 1024px) {
    .experiment-grid {
        grid-template-columns: 1fr 320px;
    }
}
</style>
```

Preserve the existing header (breadcrumb, name + status pill, edit affordances) and the existing Runs/Notes sections. Only the body-grid restructure is new.

- [ ] **Step 3: Verify build and dev render**

```bash
cd frontend && npm run check && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/\[org\]/projects/\[projectSlug\]/experiments/\[slug\]/+page.svelte
git commit -m "feat(F-0043): wire phases 4-7 surfaces into experiment detail page"
```

---

## Task 21: Wire run-edit surface for `RunKeyResultFields`

**Files:**
- Modify: the run edit surface (locate via `grep -l "lot_number" frontend/src/lib/components/run/` — the same form that handles `lot_number` should host the new fields)

- [ ] **Step 1: Locate the form**

```bash
grep -rln "lot_number" frontend/src/lib/components/run/
```

Open the file that renders the run edit form. Import `RunKeyResultFields`:

```typescript
import RunKeyResultFields from '$lib/components/run/RunKeyResultFields.svelte';
```

- [ ] **Step 2: Wire it**

Inside the form, add:

```svelte
<RunKeyResultFields
    label={run.key_result_label}
    value={run.key_result_value}
    unit={run.key_result_unit}
    onChange={async (next) => {
        run = await api.put(`/runs/${run.id}`, next, { schema: RunSchema });
    }}
/>
```

Add `RunSchema` import if missing.

- [ ] **Step 3: Type-check + commit**

```bash
cd frontend && npm run check
git add frontend/src/lib/components/run/
git commit -m "feat(F-0043): expose key_result fields on run edit form"
```

---

## Task 22: Experiments index page — filter tab + stats

**Files:**
- Modify: `frontend/src/routes/[org]/experiments/+page.svelte`

- [ ] **Step 1: Update filter tabs and predicate**

In `frontend/src/routes/[org]/experiments/+page.svelte`:

Replace the `FILTERS` const around line 44:

```typescript
const FILTERS = ['All', 'In progress', 'Awaiting conclusion', 'Complete', 'Draft'] as const;
```

Find the filter predicate around lines 82-84 and add a case:

```typescript
const filtered = $derived(experiments.filter(e => {
    if (activeFilter === 'All') return true;
    if (activeFilter === 'In progress') return e.lifecycle_status === 'IN_PROGRESS';
    if (activeFilter === 'Awaiting conclusion') return e.lifecycle_status === 'AWAITING_CONCLUSION';
    if (activeFilter === 'Complete') return e.lifecycle_status === 'COMPLETE';
    if (activeFilter === 'Draft') return e.lifecycle_status === 'DRAFT';
    return true;
}));
```

- [ ] **Step 2: Update stats counter**

Replace the `stats` derived around lines 95-97:

```typescript
const stats = $derived({
    total: experiments.length,
    inProgress: experiments.filter(e => e.lifecycle_status === 'IN_PROGRESS').length,
    awaitingConclusion: experiments.filter(e => e.lifecycle_status === 'AWAITING_CONCLUSION').length,
    complete: experiments.filter(e => e.lifecycle_status === 'COMPLETE').length,
});
```

Render a fourth stat card in the existing stats row (search for the existing `inProgress` card and clone the structure for `awaitingConclusion` with the amber pill class).

- [ ] **Step 3: Replace the hardcoded status tooltip**

There is a hardcoded experiment-status tooltip at `frontend/src/routes/[org]/experiments/+page.svelte:200` that still hardcodes the 4-state list. Replace it with a call to `experimentStatusTooltip(e.lifecycle_status)` so the new AWAITING_CONCLUSION case actually surfaces. Grep first:

```bash
grep -n "tooltip\|title=" frontend/src/routes/\[org\]/experiments/+page.svelte | head -5
```

Then update the row to:

```svelte
<span title={experimentStatusTooltip(e.lifecycle_status) ?? experimentStatusLabel(e.lifecycle_status)}
      class={experimentStatusClasses(e.lifecycle_status) + ' px-2 py-0.5 rounded text-xs'}>
    {experimentStatusLabel(e.lifecycle_status)}
</span>
```

Ensure all three helpers are imported from `$lib/components/project/projectUtils`.

- [ ] **Step 4: Type-check + commit**

```bash
cd frontend && npm run check
git add frontend/src/routes/\[org\]/experiments/+page.svelte
git commit -m "feat(F-0043): index page filter + stats card for AWAITING_CONCLUSION"
```

---

## Task 23: E2E Playwright spec

**Files:**
- Create: `frontend/tests/e2e/experiments-phase-4-7.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
import { test, expect } from '@playwright/test';

test('experiment phases 4-7 golden path', async ({ page }) => {
    await page.goto('/login');
    await page.fill('input[name="email"]', 'admin@bioprocess.com');
    await page.fill('input[name="password"]', 'password123');
    await page.click('button[type="submit"]');

    // Seed: pick an org/project that has an experiment with 3 terminal runs
    // holding key_result_values. The seed script must populate one.
    await page.goto('/bioprocess/projects/sample-project/experiments/phases-4-7-seed');

    await expect(page.getByText('Awaiting conclusion')).toBeVisible();
    await expect(page.locator('table.conditions-table')).toBeVisible();
    await expect(page.locator('svg circle.best')).toBeVisible();

    await page.fill('textarea[placeholder*="conclusion"]', 'Run 2 wins by 24%.');
    await page.getByRole('button', { name: /lock conclusion/i }).first().click();

    await expect(page.getByText('Complete')).toBeVisible();
    await expect(page.getByText(/Locked by/)).toBeVisible();

    const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: /export summary/i }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
});
```

The seed script for this fixture lives in `backend/app/db/seed.py` — add a small block (idempotent) that creates the `phases-4-7-seed` experiment with three completed runs each carrying a `key_result_value`.

- [ ] **Step 2: Run locally**

```bash
cd frontend && npm run test:e2e -- experiments-phase-4-7
```

Expected: passing once seed exists and dev servers are up.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/experiments-phase-4-7.spec.ts \
        backend/app/db/seed.py
git commit -m "test(F-0043): e2e golden path for phases 4-7"
```

---

## Task 24: Coverage + final smoke

**Files:** none new

- [ ] **Step 1: Backend coverage**

```bash
cd backend && source .venv/bin/activate
pytest --cov=app --cov-report=term-missing tests/ -q
```

Expected: ≥80% overall. New modules (`status.py`, `observations.py`, `pdf_export.py`, `conditions.py`) ≥90%.

- [ ] **Step 2: Frontend tests**

```bash
cd frontend && npm run test
```

Expected: all green.

- [ ] **Step 3: Type-check + build**

```bash
npm run check && npm run build
```

- [ ] **Step 4: Refresh project rules (per implement-task step 7)**

Update `.claude/rules/*.md` and root `CLAUDE.md` only where the changes from this task introduce new conventions:
- New lifecycle state: ensure no `.claude/rules/*.md` file documents the lifecycle as 4-state. Grep with `grep -rn "DRAFT.*IN_PROGRESS.*COMPLETE" .claude/`.
- New audit-log actions (`conclusion.lock`, `conclusion.unlock`, `key_result.set`, `export.pdf`, `export.pdf.timeout`): if an audit-log conventions doc exists, append.
- Lock-guard mutation surfaces: any rules doc that lists "experiment mutation endpoints" must enumerate the full guarded set — PUT /experiments/{id}, POST /runs (with experiment_id), POST /experiments/{id}/runs, POST/PUT/DELETE /experiments/{id}/notes. Prune any references to a smaller subset.

Commit any doc updates as `docs(F-0043): refresh project rules for phases 4-7`.

- [ ] **Step 5: Final commit if needed**

```bash
git status
git diff --stat
```

If clean, the task is ready for the verification panel.

---

## Self-Review Notes

**Spec coverage:** Task numbers map to spec sections — 1-4 cover Section 1 (schema + lifecycle), 5-9 cover Section 2 (API), 10-12 cover Section 3 services, 13-22 cover Section 4 frontend, 23-24 cover Section 5 testing/rollout. Migration backfill (spec §1) is Task 1 step 2. Audit-log snapshots (spec §3) are in Tasks 7, 8, 9. Lock-guard freezing all fields (spec §2) is Task 6 + Task 6b (adjacent mutation endpoints).

**Conditions parity** — fixture is the single source of truth; both implementations (Python in Task 11, TypeScript in Task 14) consume it. Equality key uses `json.dumps(..., sort_keys=True)` / `JSON.stringify(... sorted)` — never `repr()`.

**TOCTOU defense** — Task 7's single-statement UPDATE with the `EXISTS (... status='COMPLETED')` predicate is the atomic guard the adversarial review demanded. The disambiguation refresh runs only when `result.all()` is empty (asyncpg's `rowcount` is unreliable on `UPDATE ... RETURNING`).

**Audit/state atomicity** — every conclusion lock/unlock, key-result mutation, and PDF export logs audit **before** the single `db.commit()` so a partial failure can't leave the audit log out of sync with the state row. Tasks 7, 8, 9, 12.

**Audit action naming** — use dotted lowercase consistently: `conclusion.lock`, `conclusion.unlock`, `key_result.set`, `export.pdf`, `export.pdf.timeout`. No mixed-style action strings (no `conclusion_lock`, no `lockConclusion`).

**Rolling deploy tolerance** — Task 13 widens `LifecycleStatusEnum` to `z.string().transform(...)` so an old tab loaded before the deploy doesn't crash on the new `AWAITING_CONCLUSION` value. All consuming switch statements already have `default:` arms.

**Backfill safety** — Task 1's UPDATE only touches experiments with runs AND zero open runs AND `conclusion = NULL AND conclusion_locked_at IS NULL`, so it's idempotent on downgrade→re-upgrade and never overwrites human-authored conclusions. No sentinel string is written; the PDF renders `—` for missing conclusions.

**Pre-deploy CS/QA communication** — the new `AWAITING_CONCLUSION` lifecycle state is visible to every existing experiment that has all-completed runs but no locked conclusion. Before merging, send a one-pager to CS + QA explaining:
- "Complete" in the UI now requires the experimentalist to explicitly lock the conclusion (previously it derived from runs alone)
- The migration backfills existing "Complete"-displayed experiments to a locked state under a `system` signature so no production data flips back to "Awaiting conclusion" on deploy
- The amber pill = "all runs done, conclusion not signed off"; this is not an error state

**Coupling fix — AssignToExperimentModal** — When listing target experiments for a "move run to experiment" action, the modal must filter out locked experiments (`conclusion_locked_at !== null`). Add the predicate in `frontend/src/lib/components/run/AssignToExperimentModal.svelte` (or wherever the modal lives — grep first) and add a test that a locked experiment is absent from the list.

**Coupling fix — projectUtils test coverage** — `experimentStatusLabel` / `experimentStatusClasses` / `experimentStatusTooltip` (Task 13 step 4) need test coverage in `frontend/tests/lib/components/project/projectUtils.test.ts` for all 5 states including the new `AWAITING_CONCLUSION`. If that file doesn't exist yet, create it as part of Task 13.

**`key_result_unit` standalone** — Deferred. The current schema allows `key_result_unit` without `key_result_label`/`value` because the migration adds the columns as nullable independents. If labs start writing unit-only rows by accident, file a follow-up TECH_DEBT to add `CHECK (key_result_unit IS NULL OR key_result_label IS NOT NULL)`. Out of scope for this plan.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-f-0043-experiments-phases-4-7.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints.

**Which approach?**
