# F-0093 Experiments Investigation Workspace (Phases 1–3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Experiments a real investigation unit — discoverable in a top-level org-wide index, with a stated objective, and a status honestly derived from child runs.

**Architecture:** Three new `Experiment` columns (`objective`, `success_criteria`, `created_by_id`) plus three indexes via one Alembic revision; a separate idempotent backfill script. A pure, count-based `derive_lifecycle_status` service computes lifecycle status at read time. A new org-wide `GET /experiments` endpoint reuses the existing `get_visible_project_ids` permission utility and computes run aggregates in SQL. Frontend adds an Experiments index route + nav entry, a reusable `RunProgressBar`, an extracted `ExperimentCreateModal`, and rewrites `ExperimentsTab` to kill the double-click trap.

**Tech Stack:** FastAPI (async) + SQLAlchemy 2.0 + Alembic + PostgreSQL (JSONB); Svelte 5 (Runes) + TailwindCSS 4 + shadcn-svelte; pytest + Vitest.

**Spec:** `docs/superpowers/specs/2026-05-21-f-0093-experiments-investigation-workspace-design.md` — read it before starting.

---

## Context an engineer needs before starting

This plan is implemented in a **worktree branched from `main`** (set up by the implement-task flow). All paths and line references below are against `main`. Key facts:

- **Models** (post-TD-0083): `Experiment` and `Run` live in `backend/app/models/runs.py`. `Project` in `backend/app/models/projects.py` — it has **no `status` column** (projects are not archivable).
- **Schemas:** `backend/app/schemas/runs.py`.
- **Endpoints:** `backend/app/api/endpoints/experiments.py` and `runs.py`, mounted with **no prefix** (`app.include_router(experiments.router, ...)` in `backend/app/main.py`). A new `@router.get("/experiments")` is picked up automatically — no registration change.
- **`Run` indexes on `main`:** only `ix_runs_outcome` and `uq_runs_project_slug`. **`runs.experiment_id` is unindexed** — this plan adds the first index on it.
- **Permissions:** `backend/app/services/core/permissions.py` already exports `get_visible_project_ids(db, user_id, org_id) -> list[UUID]` — org admins get all org projects; others get `permissions_enabled=false` projects plus direct/team-granted projects. **Reuse it** for `GET /experiments` rather than hand-rolling a bulk query.
- **`log_audit`** signature: `log_audit(db, actor_id, action, entity_type, entity_id, changes)`. `experiments.py` calls it with keyword args; `runs.py` calls it positionally — match the file you are editing.
- **Run model fields:** `Run.status` is a `String` column (`PLANNED/ACTIVE/COMPLETED/EDITED/ARCHIVED`), `Run.outcome` is a nullable `String` (`COMPLETED_NORMAL/COMPLETED_WITH_DEVIATIONS/ABORTED` or null). String comparisons in SQL (`Run.status != "ARCHIVED"`) are valid.
- **Test DB:** `conftest.py` builds the schema from ORM metadata, not from migrations. So model changes are reflected in tests automatically; the migration itself is verified manually against the dev DB (Task 1).
- **Test fixtures** (`backend/tests/conftest.py`): `client`, `db_session`, `test_org`, `test_user` (org **admin**: roles `["MEMBER","ADMIN"]`), `auth_headers`, `second_org`, `second_user`, `second_auth_headers`, `test_team`, `test_project`.
- **`test_project` is permissions-locked.** It is created with `settings={"permissions_enabled": True}` **and** an explicit ADMIN `ObjectPermission` for `test_user` only. `test_user` (an org admin) sees it via the admin short-circuit in `get_visible_project_ids`; a **plain member does not** see it without its own grant. Any test that needs a project a non-admin can see must create one with `settings={"permissions_enabled": False}`.
- **Style:** the repo is **not** blanket black/isort-clean — match each file's existing style; never run `black/isort app tests` across the tree.

---

## File Structure

**Backend — created:**
- `backend/alembic/versions/<hash>_add_experiment_objective_fields.py` — schema + indexes + status normalization
- `backend/app/services/experiments/__init__.py` — new package
- `backend/app/services/experiments/status.py` — `derive_lifecycle_status` + `lifecycle_counts_from_runs`
- `backend/app/services/experiments/backfill.py` — `_extract_text` + `backfill_objectives` (idempotent, restartable)
- `backend/scripts/backfill_experiment_objectives.py` — thin CLI wrapper for the backfill
- `backend/tests/unit/services/test_experiment_status.py`
- `backend/tests/integration/test_experiments_index.py`
- `backend/tests/integration/test_experiment_objective.py`
- `backend/tests/integration/test_run_experiment_guard.py`
- `backend/tests/integration/test_backfill_experiment_objectives.py`

**Backend — modified:**
- `backend/app/models/runs.py` — 3 fields + `created_by` relationship on `Experiment`
- `backend/app/schemas/runs.py` — new summary schemas; `ExperimentCreate/Update/Response` changes
- `backend/app/api/endpoints/experiments.py` — objective fields, `lifecycle_status`, new `GET /experiments`
- `backend/app/api/endpoints/runs.py` — `POST /runs` experiment guard

**Frontend — created:**
- `frontend/src/lib/components/experiment/runProgress.ts` — run-segment color helper
- `frontend/src/lib/components/experiment/runProgress.test.ts`
- `frontend/src/lib/components/experiment/RunProgressBar.svelte`
- `frontend/src/lib/components/experiment/ExperimentCreateModal.svelte`
- `frontend/src/routes/[org]/experiments/+page.svelte` — the index page

**Frontend — modified:**
- `frontend/src/lib/paths.ts` — `experiments()` builder
- `frontend/src/lib/utils/pageTitle.ts` — index route title
- `frontend/src/routes/+layout.svelte` — desktop nav link
- `frontend/src/lib/components/layout/MobileNav.svelte` — mobile nav link
- `frontend/src/lib/components/project/projectUtils.ts` — `experimentStatusClasses/Label` → lifecycle values + tokens
- `frontend/src/lib/components/project/ExperimentsTab.svelte` — double-click fix, theme tokens, pill
- `frontend/src/routes/[org]/projects/[projectSlug]/+page.svelte` — use `ExperimentCreateModal`
- `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte` — Objective block, derived status pill

**Docs:**
- `.claude/rules/conventions.md` — add the `experiment/` component bucket

---

# Phase A — Backend

> **Deploy order (for the eventual production rollout — not the worktree):**
> (1) apply the migration, (2) deploy the backend code, (3) run the backfill
> script. The migration only adds nullable columns + indexes, so it is safe to
> apply before the new code; deploying code first would let an `Experiment`
> insert reference `created_by_id` before the column exists. The backfill runs
> last because it depends on the new `objective` column.

## Task 1: Migration — columns, indexes, status normalization

**Files:**
- Create: `backend/alembic/versions/<hash>_add_experiment_objective_fields.py`

- [ ] **Step 1: Generate the empty revision**

From `backend/` with the venv active:

Run: `alembic revision -m "add experiment objective fields and indexes"`
Expected: prints `Generating .../versions/<hash>_add_experiment_objective_fields.py ... done`. The file is created with `down_revision` already set to the current head.

- [ ] **Step 2: Fill in the revision body**

Replace the generated `upgrade()` / `downgrade()` (keep the auto-generated `revision` / `down_revision` / `branch_labels` / `depends_on` lines untouched). Add the imports shown:

```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers — leave the auto-generated values in place.


def upgrade() -> None:
    # 1. Schema — three new columns on experiments.
    op.add_column("experiments", sa.Column("objective", sa.Text(), nullable=True))
    op.add_column(
        "experiments",
        sa.Column(
            "success_criteria",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "experiments",
        sa.Column(
            "created_by_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 2. Indexes — the GET /experiments listing query is unindexed on main.
    # `postgresql_ops` takes operator-class names, NOT a sort direction —
    # express the DESC column with `sa.text(...)` instead.
    op.create_index(
        "ix_experiments_project_updated",
        "experiments",
        ["project_id", sa.text("updated_at DESC")],
    )
    op.create_index(
        "ix_runs_experiment_created",
        "runs",
        ["experiment_id", "created_at"],
    )
    op.create_index(
        "ix_experiments_created_by",
        "experiments",
        ["created_by_id"],
    )

    # 3. Status normalization — collapse legacy ACTIVE/COMPLETED so the column
    #    means only "archived or not" (Phase 3 reads only ARCHIVED from it).
    op.execute(
        "UPDATE experiments SET status = 'DRAFT' "
        "WHERE status NOT IN ('DRAFT', 'ARCHIVED')"
    )


def downgrade() -> None:
    # Schema-only — status normalization is not reversed (one-way; see spec §2.2).
    op.drop_index("ix_runs_experiment_created", table_name="runs")
    op.drop_index("ix_experiments_created_by", table_name="experiments")
    op.drop_index("ix_experiments_project_updated", table_name="experiments")
    op.drop_column("experiments", "created_by_id")
    op.drop_column("experiments", "success_criteria")
    op.drop_column("experiments", "objective")
```

- [ ] **Step 3: Apply, verify, and round-trip the migration**

The status-normalization `UPDATE` is one-way — `downgrade()` does not restore
the pre-migration `ACTIVE`/`COMPLETED` values. Snapshot them first so the
operation is recoverable (cheap; do it on the dev DB too):

Run: `psql "$BATCHRITE_DATABASE_URL" -c "COPY (SELECT id, status FROM experiments WHERE status NOT IN ('DRAFT','ARCHIVED')) TO STDOUT CSV HEADER" > /tmp/f0093_experiment_status_snapshot.csv`
Expected: writes a CSV (possibly header-only on a fresh dev DB — that is fine).

Run: `alembic upgrade head`
Expected: completes without error.

Run: `psql "$BATCHRITE_DATABASE_URL" -c "\d experiments" -c "\d runs"` (or `\d+`)
Expected: `experiments` shows `objective`, `success_criteria`, `created_by_id`, and indexes `ix_experiments_project_updated`, `ix_experiments_created_by`; `runs` shows `ix_runs_experiment_created`.

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: both succeed — proves the downgrade is valid.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(experiments): migration for objective fields and indexes"
```

---

## Task 2: `Experiment` model fields

**Files:**
- Modify: `backend/app/models/runs.py` — the `Experiment` class

- [ ] **Step 1: Add the three columns and the `created_by` relationship**

In `backend/app/models/runs.py`, in the `Experiment` class, after the existing `slug` column and before the `# Relationships` comment, add:

```python
    # F-0093: investigation objective + success criteria.
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

In the `# Relationships` block of `Experiment`, after the `runs` relationship, add:

```python
    created_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by_id], lazy="selectin"
    )
```

`Text`, `ForeignKey`, and `JSONB` are already imported at the top of `runs.py` (verify the import line `from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, String, Text, ...)` and the `JSONB` import). The `server_default` above uses the lowercase `text` callable — add `text` to that same `from sqlalchemy import (...)` group if it is not already imported. Matching the migration's `sa.text("'[]'::jsonb")` exactly keeps `alembic revision --autogenerate` from emitting a spurious server-default diff. `User` is referenced as a string, so no import is needed.

- [ ] **Step 2: Verify the app still imports**

Run: `python -c "import app.main"`
Expected: no error (the ORM mapper configures cleanly).

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/runs.py
git commit -m "feat(experiments): add objective, success_criteria, created_by to Experiment model"
```

---

## Task 3: `derive_lifecycle_status` service

**Files:**
- Create: `backend/app/services/experiments/__init__.py`
- Create: `backend/app/services/experiments/status.py`
- Test: `backend/tests/unit/services/test_experiment_status.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/services/test_experiment_status.py`:

```python
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
    assert (
        derive_lifecycle_status("DRAFT", live_run_count=3, open_run_count=0)
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
    # 1 COMPLETED + 2 ARCHIVED -> 1 live, 0 open -> COMPLETE.
    live, open_ = lifecycle_counts_from_runs(
        [_run("COMPLETED"), _run("ARCHIVED"), _run("ARCHIVED")]
    )
    assert (live, open_) == (1, 0)
    assert derive_lifecycle_status("DRAFT", live, open_) == "COMPLETE"


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
    assert (
        derive_lifecycle_status(
            ExperimentStatus.DRAFT, live_run_count=2, open_run_count=0
        )
        == "COMPLETE"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/services/test_experiment_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.experiments'`.

- [ ] **Step 3: Create the package and the service**

Create `backend/app/services/experiments/__init__.py` (empty file).

Create `backend/app/services/experiments/status.py`:

```python
"""F-0093 — read-time lifecycle-status derivation for experiments.

Lifecycle status is never stored; it is derived from child-run counts on
every read. `derive_lifecycle_status` is count-based (not run-list-based) so
the org-wide index can feed it uncapped SQL aggregates while the detail page
feeds it counts from the full run set — the 60-row run-summary cap (§1.1)
can never corrupt the status.
"""

import logging

logger = logging.getLogger(__name__)

LIFECYCLE_DRAFT = "DRAFT"
LIFECYCLE_IN_PROGRESS = "IN_PROGRESS"
LIFECYCLE_COMPLETE = "COMPLETE"
LIFECYCLE_ARCHIVED = "ARCHIVED"

_KNOWN_RUN_STATUSES = {"PLANNED", "ACTIVE", "COMPLETED", "EDITED", "ARCHIVED"}


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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/services/test_experiment_status.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/experiments/ backend/tests/unit/services/test_experiment_status.py
git commit -m "feat(experiments): add count-based lifecycle-status derivation"
```

---

## Task 4: Schemas

**Files:**
- Modify: `backend/app/schemas/runs.py`

- [ ] **Step 1: Add the summary schemas**

In `backend/app/schemas/runs.py`, ensure `ConfigDict` is importable — change the pydantic import line to:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
```

Immediately after the `ExperimentNoteListResponse` class, add:

```python
class ExperimentRunSummary(BaseModel):
    """A child run reduced to what the index needs (F-0093)."""

    status: str
    outcome: Optional[str] = None


class ExperimentOwner(BaseModel):
    """The experiment's creator, for the index owner avatar (F-0093)."""

    id: UUID
    name: str
    initials: str


class ExperimentSummary(BaseModel):
    """Lightweight per-experiment row for the org-wide index (F-0093)."""

    id: UUID
    slug: str
    name: str
    objective: Optional[str] = None
    project_id: UUID
    project_slug: str
    project_name: str
    lifecycle_status: str
    run_count: int
    run_summaries: List[ExperimentRunSummary] = Field(default_factory=list)
    owner: Optional[ExperimentOwner] = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Update `ExperimentCreate`, `ExperimentUpdate`, `ExperimentResponse`**

Replace the `ExperimentCreate` class with:

```python
class ExperimentCreate(BaseModel):
    name: str
    project_id: UUID
    description: Optional[str] = None
    objective: Optional[str] = None
    success_criteria: List[str] = Field(default_factory=list)
```

Replace the `ExperimentUpdate` class with:

```python
class ExperimentUpdate(BaseModel):
    # `status` is intentionally absent — lifecycle status is derived, not set
    # (F-0093 §3.3). `extra="forbid"` turns a stale `{"status": ...}` write
    # into an explicit 422 instead of silently dropping it.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    objective: Optional[str] = None
    success_criteria: Optional[List[str]] = None
```

In `ExperimentResponse`, add the four new fields. After the `description` line add `objective` / `success_criteria` / `created_by_id`, and after `run_count` add `lifecycle_status`:

```python
class ExperimentResponse(BaseModel):
    id: UUID
    project_id: UUID
    slug: str
    project_slug: str
    name: str
    description: Optional[str] = None
    objective: Optional[str] = None
    success_criteria: List[str] = Field(default_factory=list)
    created_by_id: Optional[UUID] = None
    content: Dict[str, Any] = Field(default_factory=dict)
    # `status` is the stored archived/not-archived flag (it keeps a default for
    # back-compat with callers that build the response by hand). `lifecycle_status`
    # is *derived* from child runs at read time — every handler must supply it,
    # so it is intentionally required (no default) to fail loudly if one forgets.
    status: str = ExperimentStatus.DRAFT
    lifecycle_status: str
    notes: list[ExperimentNote] = Field(default_factory=list)
    runs: list[RunResponse] = Field(default_factory=list)
    run_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 3: Verify schemas import**

Run: `python -c "import app.schemas.runs"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/runs.py
git commit -m "feat(experiments): add summary schemas and objective/lifecycle fields"
```

---

## Task 5: `experiments.py` — objective fields + `lifecycle_status` on existing handlers

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py`
- Test: `backend/tests/integration/test_experiment_objective.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_experiment_objective.py`:

```python
"""F-0093 — objective fields + derived lifecycle_status on experiment CRUD."""

import pytest


@pytest.mark.asyncio
async def test_create_persists_objective_and_creator(
    client, auth_headers, test_project
):
    resp = await client.post(
        "/experiments",
        headers=auth_headers,
        json={
            "name": "Glucose sweep",
            "project_id": str(test_project.id),
            "objective": "Does raising glucose increase titer?",
            "success_criteria": ["day-12 titer up >=10%"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["objective"] == "Does raising glucose increase titer?"
    assert body["success_criteria"] == ["day-12 titer up >=10%"]
    assert body["created_by_id"] is not None
    assert body["lifecycle_status"] == "DRAFT"


@pytest.mark.asyncio
async def test_update_objective_and_reject_status_write(
    client, auth_headers, test_project
):
    created = (
        await client.post(
            "/experiments",
            headers=auth_headers,
            json={"name": "Exp A", "project_id": str(test_project.id)},
        )
    ).json()

    ok = await client.put(
        f"/experiments/{created['id']}",
        headers=auth_headers,
        json={"objective": "Revised question", "success_criteria": ["c1", "c2"]},
    )
    assert ok.status_code == 200
    assert ok.json()["objective"] == "Revised question"
    assert ok.json()["success_criteria"] == ["c1", "c2"]

    rejected = await client.put(
        f"/experiments/{created['id']}",
        headers=auth_headers,
        json={"status": "COMPLETED"},
    )
    assert rejected.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_experiment_objective.py -v`
Expected: FAIL — `create` returns a body with no `objective`/`lifecycle_status`; the status-write returns 200 instead of 422.

- [ ] **Step 3: Add imports and helpers to `experiments.py`**

In `backend/app/api/endpoints/experiments.py`, change the SQLAlchemy import line to add `and_`:

```python
from sqlalchemy import and_, func, select, update
```

Add the lifecycle-service import next to the other `app.services` imports:

```python
from app.services.experiments.status import (
    derive_lifecycle_status,
    lifecycle_counts_from_runs,
)
```

Replace the `_experiment_dict` helper with the version that carries the new fields:

```python
def _experiment_dict(exp: Experiment) -> dict:
    """Convert Experiment ORM instance to a dict for ExperimentResponse.

    `lifecycle_status` is NOT set here — it depends on child runs and is
    supplied by each handler from run counts.
    """
    return {
        "id": exp.id,
        "project_id": exp.project_id,
        "slug": exp.slug,
        "project_slug": exp.project_slug,
        "name": exp.name,
        "description": exp.description,
        "objective": exp.objective,
        "success_criteria": list(exp.success_criteria or []),
        "created_by_id": exp.created_by_id,
        "content": exp.content or {},
        "status": exp.status if isinstance(exp.status, str) else exp.status.value,
        "notes": [ExperimentNote(**n) for n in (exp.notes or [])],
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
    }


async def _run_lifecycle_counts(
    db: AsyncSession, experiment_id: UUID
) -> tuple[int, int, int]:
    """Return (run_count, live_run_count, open_run_count) for one experiment."""
    row = (
        await db.execute(
            select(
                func.count(Run.id),
                func.count(Run.id).filter(Run.status != "ARCHIVED"),
                func.count(Run.id).filter(
                    and_(Run.status != "ARCHIVED", Run.status != "COMPLETED")
                ),
            ).where(Run.experiment_id == experiment_id)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2])
```

- [ ] **Step 4: Update `create_experiment`**

In `create_experiment`, set the new fields on the `Experiment(...)` constructor and pass `lifecycle_status` to the response:

```python
    experiment = Experiment(
        name=exp_in.name,
        project_id=exp_in.project_id,
        description=exp_in.description,
        objective=exp_in.objective,
        success_criteria=exp_in.success_criteria,
        created_by_id=user.id,
    )
```

Change the final `return` to:

```python
    return ExperimentResponse(
        **_experiment_dict(experiment),
        runs=[],
        run_count=0,
        lifecycle_status=derive_lifecycle_status(experiment.status, 0, 0),
    )
```

- [ ] **Step 5: Update `update_experiment`**

In `update_experiment`, change the field loop from `("name", "description", "content", "status")` to:

```python
    changes = {}
    for field in ("name", "description", "content", "objective", "success_criteria"):
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

The `log_audit` call below it is unchanged — `objective` / `success_criteria` edits are audited like any other field change.

Replace the run-count block and the `return` at the end of `update_experiment` with:

```python
    run_count, live, open_ = await _run_lifecycle_counts(db, experiment_id)

    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[],
        run_count=run_count,
        lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
    )
```

- [ ] **Step 6: Update `get_experiment`, `get_experiment_by_slug`, `list_experiments`**

In both `get_experiment` and `get_experiment_by_slug`, the handler already loads `runs`. Change their final `return` to compute lifecycle from the loaded list:

```python
    live, open_ = lifecycle_counts_from_runs(runs)
    return ExperimentResponse(
        **_experiment_dict(exp),
        runs=[RunResponse.model_validate(r) for r in runs],
        run_count=len(runs),
        lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
    )
```

In `list_experiments` (the per-project `GET /projects/{project_id}/experiments`), change the query and the return to carry lifecycle counts:

```python
    result = await db.execute(
        select(
            Experiment,
            func.count(Run.id).label("run_count"),
            func.count(Run.id).filter(Run.status != "ARCHIVED").label("live"),
            func.count(Run.id)
            .filter(and_(Run.status != "ARCHIVED", Run.status != "COMPLETED"))
            .label("open"),
        )
        .outerjoin(Run, Run.experiment_id == Experiment.id)
        .where(Experiment.project_id == project_id)
        .group_by(Experiment.id)
        .order_by(Experiment.created_at.desc())
    )
    rows = result.all()

    return [
        ExperimentResponse(
            **_experiment_dict(exp),
            runs=[],
            run_count=cnt,
            lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
        )
        for exp, cnt, live, open_ in rows
    ]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/integration/test_experiment_objective.py -v`
Expected: PASS (2 tests).

Run: `pytest tests/integration/ -k experiment -q`
Expected: existing experiment tests still PASS (no regressions from the schema change).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/experiments.py backend/tests/integration/test_experiment_objective.py
git commit -m "feat(experiments): persist objective fields, derive lifecycle_status on CRUD"
```

---

## Task 6: `GET /experiments` — org-wide index endpoint

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py`
- Test: `backend/tests/integration/test_experiments_index.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_experiments_index.py`:

```python
"""F-0093 — org-wide GET /experiments index endpoint."""

import pytest

from app.models.projects import Project
from app.models.runs import Experiment, Run


async def _make_experiment(db, project_id, name, slug):
    exp = Experiment(name=name, slug=slug, project_id=project_id)
    db.add(exp)
    await db.flush()
    return exp


@pytest.mark.asyncio
async def test_lists_org_experiments_with_summary(
    client, auth_headers, db_session, test_project
):
    await _make_experiment(db_session, test_project.id, "Exp One", "exp-one")
    await db_session.commit()

    resp = await client.get("/experiments", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Exp One"
    assert row["project_name"] == test_project.name
    assert row["lifecycle_status"] == "DRAFT"
    assert row["run_count"] == 0
    assert row["run_summaries"] == []


@pytest.mark.asyncio
async def test_org_isolation(
    client, auth_headers, second_auth_headers, db_session,
    test_project, second_org,
):
    # An experiment in a different org must not appear for test_user.
    other_project = Project(
        name="Other", organization_id=second_org.id, slug="other-project",
        owner_type="USER",
    )
    db_session.add(other_project)
    await db_session.flush()
    await _make_experiment(db_session, other_project.id, "Hidden", "hidden")
    await _make_experiment(db_session, test_project.id, "Visible", "visible")
    await db_session.commit()

    rows = (await client.get("/experiments", headers=auth_headers)).json()
    names = {r["name"] for r in rows}
    assert "Visible" in names
    assert "Hidden" not in names


@pytest.mark.asyncio
async def test_lifecycle_status_correct_past_60_run_cap(
    client, auth_headers, db_session, test_project
):
    exp = await _make_experiment(db_session, test_project.id, "Big", "big")
    # 62 COMPLETED runs then 3 PLANNED runs — the open runs sit past the cap.
    for i in range(62):
        db_session.add(
            Run(
                name=f"r{i}", slug=f"big-r{i}", project_id=test_project.id,
                experiment_id=exp.id, status="COMPLETED",
            )
        )
    for i in range(3):
        db_session.add(
            Run(
                name=f"p{i}", slug=f"big-p{i}", project_id=test_project.id,
                experiment_id=exp.id, status="PLANNED",
            )
        )
    await db_session.commit()

    rows = (await client.get("/experiments", headers=auth_headers)).json()
    row = next(r for r in rows if r["name"] == "Big")
    assert row["run_count"] == 65
    assert len(row["run_summaries"]) == 60   # capped
    assert row["lifecycle_status"] == "IN_PROGRESS"  # derived from uncapped counts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_experiments_index.py -v`
Expected: FAIL — `GET /experiments` 404s (route does not exist; `/experiments/{experiment_id}` does not match a non-UUID).

- [ ] **Step 3: Add the imports**

In `experiments.py`, extend the permissions import:

```python
from app.services.core.permissions import check_permission, get_visible_project_ids
```

Also add the SQLAlchemy ORM loader-option import (next to the other
`sqlalchemy` imports) — the index query uses both:

```python
from sqlalchemy.orm import lazyload, selectinload
```

- [ ] **Step 4: Add the endpoint**

Add this handler in `experiments.py` **above** `@router.get("/experiments/{experiment_id}", ...)` — a literal path must be registered before the `{experiment_id}` parametrized path so `/experiments` is not captured as an id. Also add `ExperimentSummary`, `ExperimentRunSummary`, `ExperimentOwner` to the `from app.schemas.runs import (...)` block.

```python
@router.get("/experiments", response_model=list[ExperimentSummary])
async def list_all_experiments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Org-wide experiments index (F-0093 §1.1).

    Org isolation is enforced by scoping to `user.selected_org_id`;
    permission filtering reuses `get_visible_project_ids`. Read endpoint —
    no `require_active_subscription` (a lapsed subscription must not block
    reading one's own experiments).
    """
    if user.selected_org_id is None:
        raise HTTPException(400, "No organization selected")

    visible_project_ids = await get_visible_project_ids(
        db, user.id, user.selected_org_id
    )
    if not visible_project_ids:
        return []

    started = datetime.now(timezone.utc)

    # Experiments + owner, newest-touched first.
    #   - selectinload(created_by): one batched query for owner avatars.
    #   - lazyload(project): `Experiment.project` is `lazy="selectin"` on the
    #     model; this endpoint reads slug/name from the JOIN and never touches
    #     `exp.project`, so suppress the relationship to avoid a redundant
    #     org-wide project fetch on every call.
    #   - limit(500): safety backstop. The org-wide index is unpaginated in
    #     this slice (§1.1 — pagination is a deferred follow-up); 500 caps a
    #     pathological org so an unbounded result set can't OOM the worker.
    exp_rows = (
        await db.execute(
            select(Experiment, Project.slug, Project.name)
            .join(Project, Experiment.project_id == Project.id)
            .where(Experiment.project_id.in_(visible_project_ids))
            .options(
                selectinload(Experiment.created_by),
                lazyload(Experiment.project),
            )
            .order_by(Experiment.updated_at.desc())
            .limit(500)
        )
    ).all()
    if not exp_rows:
        return []

    experiment_ids = [exp.id for exp, _, _ in exp_rows]

    # Run aggregates per experiment — uncapped, used for run_count + lifecycle.
    agg_rows = (
        await db.execute(
            select(
                Run.experiment_id,
                func.count(Run.id),
                func.count(Run.id).filter(Run.status != "ARCHIVED"),
                func.count(Run.id).filter(
                    and_(Run.status != "ARCHIVED", Run.status != "COMPLETED")
                ),
            )
            .where(Run.experiment_id.in_(experiment_ids))
            .group_by(Run.experiment_id)
        )
    ).all()
    agg = {
        exp_id: (int(total), int(live), int(open_))
        for exp_id, total, live, open_ in agg_rows
    }

    # Capped run summaries — 60 oldest runs per experiment, in SQL.
    ranked = (
        select(
            Run.experiment_id.label("experiment_id"),
            Run.status.label("status"),
            Run.outcome.label("outcome"),
            func.row_number()
            .over(partition_by=Run.experiment_id, order_by=Run.created_at.asc())
            .label("rn"),
        )
        .where(Run.experiment_id.in_(experiment_ids))
        .subquery()
    )
    summary_rows = (
        await db.execute(
            select(ranked.c.experiment_id, ranked.c.status, ranked.c.outcome)
            .where(ranked.c.rn <= 60)
            .order_by(ranked.c.experiment_id, ranked.c.rn)
        )
    ).all()
    summaries: dict = {}
    for exp_id, status, outcome in summary_rows:
        summaries.setdefault(exp_id, []).append(
            ExperimentRunSummary(status=status, outcome=outcome)
        )

    results = []
    for exp, project_slug, project_name in exp_rows:
        total, live, open_ = agg.get(exp.id, (0, 0, 0))
        results.append(
            ExperimentSummary(
                id=exp.id,
                slug=exp.slug,
                name=exp.name,
                objective=exp.objective,
                project_id=exp.project_id,
                project_slug=project_slug,
                project_name=project_name,
                lifecycle_status=derive_lifecycle_status(exp.status, live, open_),
                run_count=total,
                run_summaries=summaries.get(exp.id, []),
                owner=_owner_summary(exp.created_by),
                created_at=exp.created_at,
                updated_at=exp.updated_at,
            )
        )

    elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    if elapsed_ms > 500:
        logger.warning(
            "GET /experiments slow: %.0f ms, org=%s, experiments=%d",
            elapsed_ms,
            user.selected_org_id,
            len(results),
        )
    return results
```

Add the owner helper near `_experiment_dict`:

```python
def _owner_initials(full_name: str | None, email: str) -> str:
    """First letters of the first two name words; else first email char."""
    if full_name and full_name.strip():
        words = full_name.split()
        return "".join(w[0] for w in words[:2]).upper()
    return email[:1].upper()


def _owner_summary(creator) -> "ExperimentOwner | None":
    if creator is None:
        return None
    name = creator.full_name or creator.email
    return ExperimentOwner(
        id=creator.id,
        name=name,
        initials=_owner_initials(creator.full_name, creator.email),
    )
```

`datetime` and `timezone` are already imported at the top of `experiments.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/integration/test_experiments_index.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Add the permission-filtering + null-org tests**

Append to `test_experiments_index.py`:

```python
@pytest.mark.asyncio
async def test_400_when_no_org_selected(client, db_session):
    from app.core.security import create_access_token
    from app.models.iam import User
    from app.core.security import hash_password

    orphan = User(
        email="orphan@example.com", hashed_password=hash_password("x"),
        full_name="Orphan", selected_org_id=None, email_verified=True,
    )
    db_session.add(orphan)
    await db_session.commit()
    token = create_access_token(
        orphan.id, org_id=None, subscription_tier="free", email_verified=True
    )
    resp = await client.get(
        "/experiments", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_permission_filters_restricted_projects(
    client, db_session, test_org,
):
    """A non-admin member sees only projects they can VIEW.

    Note: the `test_project` fixture is itself permissions-locked
    (`permissions_enabled=True` + an ADMIN grant for `test_user` only), so it
    is NOT a valid "visible" case for a plain member. This test creates its
    own genuinely-open project instead.
    """
    from app.core.security import create_access_token, hash_password
    from app.models.iam import OrganizationMember, User

    # An org-open project (permissions disabled) -> visible to every member.
    open_proj = Project(
        name="Open", organization_id=test_org.id, slug="open-proj",
        owner_type="USER", settings={"permissions_enabled": False},
    )
    # A permissions-locked project with no grant for the member -> hidden.
    locked = Project(
        name="Locked", organization_id=test_org.id, slug="locked",
        owner_type="USER", settings={"permissions_enabled": True},
    )
    db_session.add_all([open_proj, locked])
    await db_session.flush()
    await _make_experiment(db_session, open_proj.id, "Open Exp", "open-exp")
    await _make_experiment(db_session, locked.id, "Locked Exp", "locked-exp")

    member = User(
        email="member@example.com", hashed_password=hash_password("x"),
        full_name="Plain Member", selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=member.id, organization_id=test_org.id, roles=["MEMBER"]
        )
    )
    await db_session.commit()

    token = create_access_token(
        member.id, org_id=test_org.id, subscription_tier="free",
        email_verified=True,
    )
    rows = (
        await client.get(
            "/experiments", headers={"Authorization": f"Bearer {token}"}
        )
    ).json()
    names = {r["name"] for r in rows}
    assert "Open Exp" in names
    assert "Locked Exp" not in names
```

Run: `pytest tests/integration/test_experiments_index.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/experiments.py backend/tests/integration/test_experiments_index.py
git commit -m "feat(experiments): add org-wide GET /experiments index endpoint"
```

---

## Task 7: `POST /runs` experiment guard

**Files:**
- Modify: `backend/app/api/endpoints/runs.py`
- Test: `backend/tests/integration/test_run_experiment_guard.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_run_experiment_guard.py`:

```python
"""F-0093 §1.6 — POST /runs must validate experiment_id."""

import pytest

from app.models.projects import Project
from app.models.runs import Experiment


async def _experiment(db, project_id, name, slug, status="DRAFT"):
    exp = Experiment(name=name, slug=slug, project_id=project_id, status=status)
    db.add(exp)
    await db.flush()
    return exp


@pytest.mark.asyncio
async def test_rejects_experiment_in_other_project(
    client, auth_headers, db_session, test_org, test_project,
):
    other = Project(
        name="Other", organization_id=test_org.id, slug="other-p",
        owner_type="USER",
    )
    db_session.add(other)
    await db_session.flush()
    exp = await _experiment(db_session, other.id, "Foreign", "foreign")
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Bad run",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RUN_EXPERIMENT_PROJECT_MISMATCH"


@pytest.mark.asyncio
async def test_rejects_archived_experiment(
    client, auth_headers, db_session, test_project,
):
    exp = await _experiment(
        db_session, test_project.id, "Closed", "closed", status="ARCHIVED"
    )
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Run on archived",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "RUN_EXPERIMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_allows_same_project_experiment(
    client, auth_headers, db_session, test_project,
):
    exp = await _experiment(db_session, test_project.id, "Good", "good")
    await db_session.commit()

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Valid run",
            "project_id": str(test_project.id),
            "experiment_id": str(exp.id),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["experiment_id"] == str(exp.id)


@pytest.mark.asyncio
async def test_rejects_nonexistent_experiment(
    client, auth_headers, test_project,
):
    """A run pointing at a non-existent experiment_id 404s via get_or_404."""
    import uuid

    resp = await client.post(
        "/runs",
        headers=auth_headers,
        json={
            "name": "Run on ghost",
            "project_id": str(test_project.id),
            "experiment_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_run_experiment_guard.py -v`
Expected: FAIL — the mismatch/archived cases return 201 (no guard exists).
`test_rejects_nonexistent_experiment` already passes once the guard's
`get_or_404` lookup is in place; before the guard it returns 201.

- [ ] **Step 3: Add the guard to `create_run`**

In `backend/app/api/endpoints/runs.py`, `Experiment` is not yet imported — change the models import line to:

```python
from app.models.runs import Experiment, Run, RunRoleAssignment
```

In `create_run`, immediately after the project null-check (`if project is None: raise HTTPException(404, ...)`) and before `initial_graph: dict = {}`, insert:

```python
    # F-0093 §1.6: a run's experiment must share its project and be non-archived.
    if run_in.experiment_id is not None:
        experiment = await get_or_404(db, Experiment, run_in.experiment_id)
        if experiment.project_id != run_in.project_id:
            logger.warning(
                "POST /runs experiment-project mismatch: org=%s user=%s "
                "project=%s experiment=%s",
                user.selected_org_id, user.id, run_in.project_id,
                run_in.experiment_id,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "RUN_EXPERIMENT_PROJECT_MISMATCH",
                    "message": "Experiment must belong to the run's project.",
                },
            )
        exp_status = (
            experiment.status
            if isinstance(experiment.status, str)
            else experiment.status.value
        )
        if exp_status == "ARCHIVED":
            logger.warning(
                "POST /runs on archived experiment: org=%s user=%s experiment=%s",
                user.selected_org_id, user.id, run_in.experiment_id,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "RUN_EXPERIMENT_ARCHIVED",
                    "message": "Cannot add a run to an archived experiment.",
                },
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/integration/test_run_experiment_guard.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_experiment_guard.py
git commit -m "feat(experiments): validate experiment_id on POST /runs"
```

---

## Task 8: Objective backfill script

**Files:**
- Create: `backend/app/services/experiments/backfill.py` — `_extract_text` + `backfill_objectives`
- Create: `backend/scripts/backfill_experiment_objectives.py` — thin CLI wrapper
- Test: `backend/tests/integration/test_backfill_experiment_objectives.py`

The backfill *logic* lives in `app.services.experiments.backfill` — an
importable package. It deliberately does **not** live in `scripts/`:
`backend/scripts/` has no `__init__.py`, so `from scripts... import ...` raises
`ModuleNotFoundError` and the test could not import it.
`scripts/backfill_experiment_objectives.py` is a thin CLI that opens a session
via `AsyncSessionLocal` and calls `backfill_objectives`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_backfill_experiment_objectives.py`:

```python
"""F-0093 §2.2 — objective backfill from Experiment.content."""

import pytest

from app.models.runs import Experiment
from app.services.experiments.backfill import backfill_objectives


def _doc(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


@pytest.mark.asyncio
async def test_backfill_populates_truncates_and_is_idempotent(
    db_session, test_project,
):
    long_text = "Q " * 400  # > 280 chars
    with_content = Experiment(
        name="Has content", slug="has-content", project_id=test_project.id,
        content=_doc(long_text),
    )
    already = Experiment(
        name="Already set", slug="already", project_id=test_project.id,
        objective="kept", content=_doc("ignored"),
    )
    empty = Experiment(
        name="No content", slug="no-content", project_id=test_project.id,
        content={},
    )
    db_session.add_all([with_content, already, empty])
    await db_session.commit()

    # backfill_objectives commits per batch internally — no trailing commit.
    stats = await backfill_objectives(db_session, batch_size=2)

    await db_session.refresh(with_content)
    await db_session.refresh(already)
    assert with_content.objective is not None
    assert len(with_content.objective) == 280
    assert already.objective == "kept"
    assert stats["backfilled"] == 1
    assert stats["already_set"] == 1

    # Second run is a no-op.
    stats2 = await backfill_objectives(db_session, batch_size=2)
    assert stats2["backfilled"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_backfill_experiment_objectives.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.experiments.backfill'` (the `experiments` package exists from Task 3; the `backfill` module does not yet).

- [ ] **Step 3: Write the backfill service**

Create `backend/app/services/experiments/backfill.py`:

```python
"""F-0093 §2.2 — backfill Experiment.objective from the legacy `content` doc.

Idempotent: only touches rows where `objective IS NULL`. Run once after the
migration deploys; safe to re-run. Batches via a keyset cursor on `id` so
skipped (over-cap / unparseable) rows can never cause an infinite loop, and
commits after each batch so a crash mid-run leaves completed batches
persisted — a re-run resumes cleanly from the first still-NULL row.
"""

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runs import Experiment

logger = logging.getLogger("backfill_experiment_objectives")

SIZE_CAP_BYTES = 256 * 1024
OBJECTIVE_MAX_CHARS = 280


def _extract_text(content: dict) -> str | None:
    """Concatenate text nodes from a Tiptap/Edra doc, iteratively."""
    if not isinstance(content, dict) or not content:
        return None
    if len(json.dumps(content)) > SIZE_CAP_BYTES:
        raise ValueError("content exceeds size cap")
    parts: list[str] = []
    stack = [content]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            children = node.get("content")
            if isinstance(children, list):
                stack.extend(reversed(children))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    text = " ".join(p.strip() for p in parts if p.strip())
    return text or None


async def backfill_objectives(
    db: AsyncSession, *, batch_size: int = 500
) -> dict[str, int]:
    """Backfill objectives in keyset-paginated batches.

    Commits after each batch — the operation is restartable: a crash leaves
    every completed batch persisted, and a re-run skips them (their
    `objective` is no longer NULL). Returns count stats.
    """
    stats = {
        "total": 0,
        "already_set": 0,
        "backfilled": 0,
        "skipped_over_cap": 0,
        "skipped_unparseable": 0,
    }
    cursor = None
    while True:
        stmt = select(Experiment).where(Experiment.objective.is_(None))
        if cursor is not None:
            stmt = stmt.where(Experiment.id > cursor)
        stmt = stmt.order_by(Experiment.id).limit(batch_size)
        batch = list((await db.execute(stmt)).scalars().all())
        if not batch:
            break
        for exp in batch:
            stats["total"] += 1
            cursor = exp.id
            try:
                text = _extract_text(exp.content or {})
            except ValueError:
                stats["skipped_over_cap"] += 1
                continue
            if not text:
                stats["skipped_unparseable"] += 1
                continue
            exp.objective = text[:OBJECTIVE_MAX_CHARS]
            stats["backfilled"] += 1
        # Commit each batch so a crash never re-does completed work. The
        # keyset cursor is a plain UUID captured before commit, so the next
        # iteration's `id > cursor` query is unaffected by the expire.
        await db.commit()

    # `already_set` is everything else — count rows that already had an objective.
    not_null = (
        await db.execute(
            select(func.count(Experiment.id)).where(
                Experiment.objective.is_not(None)
            )
        )
    ).scalar() or 0
    stats["already_set"] = max(0, not_null - stats["backfilled"])
    return stats
```

- [ ] **Step 4: Write the CLI wrapper**

Create `backend/scripts/backfill_experiment_objectives.py`:

```python
"""F-0093 §2.2 — CLI for the objective backfill.

Run once after the migration deploys; safe to re-run (the work is idempotent
and restartable — see `app.services.experiments.backfill`).

Usage (from backend/, venv active):  python scripts/backfill_experiment_objectives.py
"""

import asyncio
import logging

from app.db.session import AsyncSessionLocal
from app.services.experiments.backfill import backfill_objectives

logger = logging.getLogger("backfill_experiment_objectives")


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AsyncSessionLocal() as db:
        stats = await backfill_objectives(db)
    skipped = stats["skipped_over_cap"] + stats["skipped_unparseable"]
    line = (
        "backfill_experiment_objectives complete: "
        f"total={stats['total']} already_set={stats['already_set']} "
        f"backfilled={stats['backfilled']} "
        f"skipped_over_cap={stats['skipped_over_cap']} "
        f"skipped_unparseable={stats['skipped_unparseable']}"
    )
    if skipped:
        logger.warning(line)
    else:
        logger.info(line)


if __name__ == "__main__":
    asyncio.run(_main())
```

`backfill_objectives` commits per batch, so `_main()` needs no trailing
commit. `AsyncSessionLocal` is the session factory exported by
`app/db/session.py` (confirmed against `main`).

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/integration/test_backfill_experiment_objectives.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/experiments/backfill.py backend/scripts/backfill_experiment_objectives.py backend/tests/integration/test_backfill_experiment_objectives.py
git commit -m "feat(experiments): idempotent objective backfill script"
```

---

# Phase B — Frontend

## Task 9: Path builder + page title

**Files:**
- Modify: `frontend/src/lib/paths.ts`
- Modify: `frontend/src/lib/utils/pageTitle.ts`

- [ ] **Step 1: Add the `experiments()` path builder**

In `frontend/src/lib/paths.ts`, inside the `paths` object, add after the `experiment` builder:

```typescript
  experiments: (): string => `/${orgSlug()}/experiments`,
```

- [ ] **Step 2: Add the index route title and fix the stale detail guard**

In `frontend/src/lib/utils/pageTitle.ts`, in `routeName`, in the prefix-matching block (the `if (p.startsWith(...))` group near the bottom):

1. Add the index-route title **before** the existing `if (p.startsWith('/projects/'))` line:

   ```typescript
       if (/^\/[^/]+\/experiments\/?$/.test(p)) return 'Experiments';
   ```

2. The file still carries a pre-F-0091 guard `if (p.startsWith('/experiments/')) return 'Experiment';`. It is dead code — org-slug routing means the experiment detail route is now `/[org]/projects/[projectSlug]/experiments/[slug]`, never `/experiments/...`. **Replace** that stale line with an org-scoped detail guard:

   ```typescript
       if (/^\/[^/]+\/projects\/[^/]+\/experiments\/[^/]+/.test(p)) return 'Experiment';
   ```

- [ ] **Step 3: Verify the frontend type-checks**

Run (from `frontend/`): `npm run check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/paths.ts frontend/src/lib/utils/pageTitle.ts
git commit -m "feat(experiments): add experiments index path + page title"
```

---

## Task 10: Nav links

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/lib/components/layout/MobileNav.svelte`

- [ ] **Step 1: Add the desktop nav link**

In `frontend/src/routes/+layout.svelte`, add a `derived` next to `libraryHref` (search for `const libraryHref =`):

```typescript
    const experimentsHref = $derived(currentOrg ? paths.experiments() : '');
```

In the desktop `<nav>`, the Dashboard link looks like:

```svelte
<a
    href="/"
    class="hidden md:block relative py-1 transition-colors {$page.url.pathname === '/' ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
>
    Dashboard
</a>
```

Immediately after that Dashboard `<a>`, add:

```svelte
<a
    href={experimentsHref}
    class="hidden md:block relative py-1 transition-colors {/^\/[^/]+\/experiments/.test($page.url.pathname) ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
>
    Experiments
</a>
```

- [ ] **Step 2: Add the mobile nav link**

Open `frontend/src/lib/components/layout/MobileNav.svelte`. It does **not** render links one-by-one — it builds a `$derived` array and `{#each}`es over it:

```typescript
const links = $derived(getCurrentOrg()
    ? [{ href: '/', label: 'Dashboard' }, { href: paths.library(), label: 'Library' }, ...]
    : [{ href: '/', label: 'Dashboard' }, { href: '/chat', label: 'AI Chat' }, ...]);
```

`paths` is already imported. Add the Experiments entry as the **second element of the `getCurrentOrg() ? [...]` branch only** — right after the Dashboard entry:

```typescript
{ href: paths.experiments(), label: 'Experiments' },
```

Do **not** add it to the no-org `[...]` branch (that branch has no Library/Projects either — Experiments is org-scoped). The file's `isActive(href)` helper already drives active styling generically, so no styling change is needed.

- [ ] **Step 3: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/+layout.svelte frontend/src/lib/components/layout/MobileNav.svelte
git commit -m "feat(experiments): add Experiments nav entry"
```

---

## Task 11: `RunProgressBar` component + color helper

**Files:**
- Create: `frontend/src/lib/components/experiment/runProgress.ts`
- Test: `frontend/src/lib/components/experiment/runProgress.test.ts`
- Create: `frontend/src/lib/components/experiment/RunProgressBar.svelte`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/experiment/runProgress.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { runSegmentClass, runSegmentLabel } from './runProgress';

describe('runSegmentClass', () => {
  it('maps a normal completion to accent green', () => {
    expect(runSegmentClass('COMPLETED', 'COMPLETED_NORMAL')).toBe('bg-accent');
  });
  it('maps a deviated completion to amber', () => {
    expect(runSegmentClass('COMPLETED', 'COMPLETED_WITH_DEVIATIONS')).toBe(
      'bg-amber-400 dark:bg-amber-500',
    );
  });
  it('maps an aborted completion to destructive', () => {
    expect(runSegmentClass('COMPLETED', 'ABORTED')).toBe('bg-destructive');
  });
  it('treats a legacy null-outcome completion as normal', () => {
    expect(runSegmentClass('COMPLETED', null)).toBe('bg-accent');
  });
  it('maps ACTIVE and EDITED to primary', () => {
    expect(runSegmentClass('ACTIVE', null)).toBe('bg-primary');
    expect(runSegmentClass('EDITED', null)).toBe('bg-primary');
  });
  it('maps PLANNED to muted and ARCHIVED to a faded track', () => {
    expect(runSegmentClass('PLANNED', null)).toBe('bg-muted');
    expect(runSegmentClass('ARCHIVED', null)).toBe('bg-muted-foreground/30');
  });
});

describe('runSegmentLabel', () => {
  it('describes status and outcome for the accessible label', () => {
    expect(runSegmentLabel('COMPLETED', 'COMPLETED_WITH_DEVIATIONS')).toBe(
      'Completed (with deviations)',
    );
    expect(runSegmentLabel('PLANNED', null)).toBe('Planned');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm run test -- runProgress`
Expected: FAIL — cannot resolve `./runProgress`.

- [ ] **Step 3: Write the helper**

Create `frontend/src/lib/components/experiment/runProgress.ts`:

```typescript
/**
 * Single source of truth for RunProgressBar segment colors + labels (F-0093).
 * Color alone is not accessible — every segment also carries runSegmentLabel
 * as its title / aria-label.
 */

export function runSegmentClass(
  status: string,
  outcome: string | null | undefined,
): string {
  const s = (status ?? '').toUpperCase();
  const o = (outcome ?? '').toUpperCase();
  if (s === 'COMPLETED') {
    if (o === 'COMPLETED_WITH_DEVIATIONS') return 'bg-amber-400 dark:bg-amber-500';
    if (o === 'ABORTED') return 'bg-destructive';
    return 'bg-accent'; // COMPLETED_NORMAL or legacy null outcome
  }
  if (s === 'ACTIVE' || s === 'EDITED') return 'bg-primary';
  if (s === 'ARCHIVED') return 'bg-muted-foreground/30';
  return 'bg-muted'; // PLANNED and anything unrecognized
}

export function runSegmentLabel(
  status: string,
  outcome: string | null | undefined,
): string {
  const s = (status ?? '').toUpperCase();
  const o = (outcome ?? '').toUpperCase();
  if (s === 'COMPLETED') {
    if (o === 'COMPLETED_WITH_DEVIATIONS') return 'Completed (with deviations)';
    if (o === 'ABORTED') return 'Completed (aborted)';
    return 'Completed';
  }
  if (s === 'ACTIVE') return 'Active';
  if (s === 'EDITED') return 'Edited';
  if (s === 'PLANNED') return 'Planned';
  if (s === 'ARCHIVED') return 'Archived';
  return status || 'Unknown';
}

export function isPulsing(status: string): boolean {
  return (status ?? '').toUpperCase() === 'ACTIVE';
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm run test -- runProgress`
Expected: PASS.

- [ ] **Step 5: Write the component**

Create `frontend/src/lib/components/experiment/RunProgressBar.svelte`:

```svelte
<script lang="ts">
  import { runSegmentClass, runSegmentLabel, isPulsing } from './runProgress';

  interface RunSummary {
    status: string;
    outcome?: string | null;
  }

  interface Props {
    /** Capped run summaries (<= 60) from the API. */
    runs: RunSummary[];
    /** True total — may exceed runs.length. */
    total: number;
  }

  let { runs, total }: Props = $props();

  const hiddenCount = $derived(Math.max(0, total - runs.length));
</script>

<div class="flex items-center gap-2">
  {#if runs.length === 0}
    <div class="h-2 flex-1 rounded-full bg-muted" aria-label="No runs yet"></div>
  {:else}
    <div class="flex h-2 flex-1 gap-1 overflow-hidden rounded-full">
      {#each runs as run, i (i)}
        <div
          class="h-full flex-1 rounded-sm {runSegmentClass(run.status, run.outcome)} {isPulsing(
            run.status,
          )
            ? 'animate-pulse'
            : ''}"
          title={runSegmentLabel(run.status, run.outcome)}
          aria-label={runSegmentLabel(run.status, run.outcome)}
        ></div>
      {/each}
    </div>
  {/if}
  <span class="whitespace-nowrap text-xs text-muted-foreground">
    {runs.length}{hiddenCount > 0 ? `+${hiddenCount}` : ''} / {total} run{total === 1
      ? ''
      : 's'}
  </span>
</div>
```

- [ ] **Step 6: Verify and commit**

Run (from `frontend/`): `npm run check`
Expected: no new errors.

```bash
git add frontend/src/lib/components/experiment/
git commit -m "feat(experiments): add RunProgressBar component"
```

---

## Task 12: `projectUtils` — lifecycle status pill helpers

**Files:**
- Modify: `frontend/src/lib/components/project/projectUtils.ts`

- [ ] **Step 1: Rewrite `experimentStatusClasses` and `experimentStatusLabel`**

In `frontend/src/lib/components/project/projectUtils.ts`, replace the existing `experimentStatusClasses` and `experimentStatusLabel` functions with versions keyed on the four `lifecycle_status` values, using shadcn-svelte token classes:

```typescript
export function experimentStatusClasses(status: string): string {
    switch (status?.toUpperCase()) {
        case "IN_PROGRESS":
            return "bg-primary/10 text-primary border border-primary/20";
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
        case "COMPLETE":
            return "Complete";
        case "ARCHIVED":
            return "Archived";
        case "DRAFT":
        default:
            return "Draft";
    }
}
```

- [ ] **Step 2: Verify and commit**

Run (from `frontend/`): `npm run check`
Expected: no new errors.

```bash
git add frontend/src/lib/components/project/projectUtils.ts
git commit -m "refactor(experiments): lifecycle-status pill helpers with theme tokens"
```

---

## Task 13: `ExperimentCreateModal` component

**Files:**
- Create: `frontend/src/lib/components/experiment/ExperimentCreateModal.svelte`

- [ ] **Step 1: Write the component**

Create `frontend/src/lib/components/experiment/ExperimentCreateModal.svelte`. Compose from existing `ui/` primitives — check the actual prop API of `$lib/components/ui/dialog`, `ui/input`, `ui/textarea`, `ui/button`, `ui/label` in the repo and match it (the pattern below mirrors existing modals such as `AddExistingRunModal.svelte`):

```svelte
<script lang="ts">
  import { api } from '$lib/api';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Label } from '$lib/components/ui/label';
  import * as Dialog from '$lib/components/ui/dialog';

  interface Props {
    open: boolean;
    projectId: string;
    /** Called with the created experiment on success. */
    onCreated: (experiment: any) => void;
  }

  let { open = $bindable(), projectId, onCreated }: Props = $props();

  let name = $state('');
  let objective = $state('');
  let description = $state('');
  let error = $state<string | null>(null);
  let saving = $state(false);

  function reset() {
    name = '';
    objective = '';
    description = '';
    error = null;
  }

  async function submit() {
    if (!name.trim() || saving) return;
    saving = true;
    error = null;
    try {
      const created = await api.post('/experiments', {
        name: name.trim(),
        project_id: projectId,
        objective: objective.trim() || null,
        description: description.trim() || null,
      });
      open = false;
      reset();
      onCreated(created);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to create experiment.';
    } finally {
      saving = false;
    }
  }
</script>

<Dialog.Root bind:open onOpenChange={(v) => !v && reset()}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>New experiment</Dialog.Title>
      <Dialog.Description>
        An experiment is an investigation — give it a question to answer.
      </Dialog.Description>
    </Dialog.Header>

    <div class="space-y-4 py-2">
      <div class="space-y-1.5">
        <Label for="exp-name">Name</Label>
        <Input id="exp-name" bind:value={name} placeholder="Experiment name" />
      </div>

      <div class="space-y-1.5">
        <Label for="exp-objective">Objective</Label>
        <Textarea
          id="exp-objective"
          bind:value={objective}
          placeholder="What question are you investigating?"
          rows={3}
        />
        <p class="text-xs text-muted-foreground">
          Tip: phrase it as a testable hypothesis, e.g. "Does raising the
          glucose setpoint increase day-12 titer?"
        </p>
      </div>

      <div class="space-y-1.5">
        <Label for="exp-description">Description <span class="text-muted-foreground">(optional)</span></Label>
        <Textarea id="exp-description" bind:value={description} rows={2} />
        <p class="text-xs text-muted-foreground">
          Background or scope — distinct from the objective question above.
        </p>
      </div>

      {#if error}
        <p class="text-sm text-destructive">{error}</p>
      {/if}
    </div>

    <Dialog.Footer>
      <Button
        variant="ghost"
        onclick={() => {
          open = false;
          reset();
        }}
      >
        Cancel
      </Button>
      <Button onclick={submit} disabled={!name.trim() || saving}>
        {saving ? 'Creating…' : 'Create experiment'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 2: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors. If a `ui/` import path or prop name differs from the above, correct it to the repo's actual API.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/experiment/ExperimentCreateModal.svelte
git commit -m "feat(experiments): extract ExperimentCreateModal component"
```

---

## Task 14: Experiments index page

**Files:**
- Create: `frontend/src/routes/[org]/experiments/+page.svelte`

- [ ] **Step 1: Write the page**

Create `frontend/src/routes/[org]/experiments/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { paths } from '$lib/paths';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
  import ErrorAlert from '$lib/components/ui/error-alert.svelte';
  import RunProgressBar from '$lib/components/experiment/RunProgressBar.svelte';
  import ExperimentCreateModal from '$lib/components/experiment/ExperimentCreateModal.svelte';
  import {
    shortId,
    formatDate,
    experimentStatusClasses,
    experimentStatusLabel,
  } from '$lib/components/project/projectUtils';
  import { goto } from '$app/navigation';

  interface ExperimentRow {
    id: string;
    slug: string;
    name: string;
    objective: string | null;
    project_id: string;
    project_slug: string;
    project_name: string;
    lifecycle_status: string;
    run_count: number;
    run_summaries: { status: string; outcome: string | null }[];
    owner: { id: string; name: string; initials: string } | null;
    created_at: string;
    updated_at: string;
  }

  let experiments = $state<ExperimentRow[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let showCreate = $state(false);

  // Filter state.
  const FILTERS = ['All', 'In progress', 'Complete', 'Draft'] as const;
  let activeFilter = $state<(typeof FILTERS)[number]>('All');
  let query = $state('');

  // The create modal needs a project; index-level creation is deferred to a
  // follow-up — for now the button routes the user to pick a project.
  let createProjectId = $state<string>('');

  async function load() {
    loading = true;
    error = null;
    try {
      experiments = (await api.get('/experiments')) as ExperimentRow[];
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load experiments.';
    } finally {
      loading = false;
    }
  }

  onMount(load);

  // NOTE: `filtered` and `stats` below run over the full client-side list.
  // That is correct only while GET /experiments is unpaginated (§1.1). When
  // pagination lands (deferred follow-up), filtering and the stat strip must
  // move server-side or they will silently reflect only the loaded page.
  const filtered = $derived(
    experiments.filter((e) => {
      const matchesFilter =
        activeFilter === 'All' ||
        (activeFilter === 'In progress' && e.lifecycle_status === 'IN_PROGRESS') ||
        (activeFilter === 'Complete' && e.lifecycle_status === 'COMPLETE') ||
        (activeFilter === 'Draft' && e.lifecycle_status === 'DRAFT');
      const q = query.trim().toLowerCase();
      const matchesQuery =
        !q ||
        e.name.toLowerCase().includes(q) ||
        (e.objective ?? '').toLowerCase().includes(q) ||
        e.project_name.toLowerCase().includes(q);
      return matchesFilter && matchesQuery;
    }),
  );

  const stats = $derived({
    total: experiments.length,
    inProgress: experiments.filter((e) => e.lifecycle_status === 'IN_PROGRESS').length,
    runs: experiments.reduce((sum, e) => sum + e.run_count, 0),
  });
</script>

<div class="space-y-6">
  <!-- Header — single column; the spec's "New experiment" button is omitted
       on the index (see the note at the end of this task), so there is no
       second flex child to justify-between against. -->
  <div>
    <p class="font-mono text-xs uppercase tracking-widest text-accent">
      Investigations
    </p>
    <h1 class="mt-1 text-2xl font-semibold text-foreground">Experiments</h1>
    <p class="mt-1 text-sm text-muted-foreground">
      Every investigation across your projects — objective, runs, and status.
    </p>
  </div>

  {#if loading}
    <LoadingSpinner />
  {:else if error}
    <ErrorAlert message={error} onRetry={load} />
  {:else}
    <!-- Stat strip -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="rounded-lg border border-border bg-card p-4">
        <p class="text-xs text-muted-foreground">Experiments</p>
        <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.total}</p>
      </div>
      <div class="rounded-lg border border-border bg-card p-4">
        <p class="text-xs text-muted-foreground">In progress</p>
        <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.inProgress}</p>
      </div>
      <div class="rounded-lg border border-border bg-card p-4">
        <p class="text-xs text-muted-foreground">Runs across all</p>
        <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.runs}</p>
      </div>
    </div>

    <!-- Filter row — composed from shadcn `Button` / `Input` primitives, not
         raw <button>/<input> (conventions.md "Frontend components"). -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="flex gap-1">
        {#each FILTERS as f}
          <Button
            variant={activeFilter === f ? 'default' : 'outline'}
            size="sm"
            onclick={() => (activeFilter = f)}
          >
            {f}
          </Button>
        {/each}
      </div>
      <Input
        bind:value={query}
        placeholder="Search experiments…"
        class="h-9 min-w-[200px] flex-1"
      />
    </div>

    <!-- Rows -->
    {#if filtered.length === 0}
      <div class="rounded-lg border border-dashed border-border py-16 text-center">
        <p class="text-sm font-semibold text-foreground">
          {experiments.length === 0 ? 'No experiments yet' : 'No matching experiments'}
        </p>
        <p class="mt-1 text-sm text-muted-foreground">
          {experiments.length === 0
            ? 'Open a project to start your first investigation.'
            : 'Try a different filter or search term.'}
        </p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each filtered as e (e.id)}
          <a
            href={paths.experiment(e.project_slug, e.slug)}
            class="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="truncate font-medium text-foreground">{e.name}</span>
                  <span class="shrink-0 font-mono text-xs text-muted-foreground">
                    EXP-{shortId(e.id)}
                  </span>
                  <span
                    class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold {experimentStatusClasses(
                      e.lifecycle_status,
                    )}"
                  >
                    {#if e.lifecycle_status === 'IN_PROGRESS'}
                      <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                    {/if}
                    {experimentStatusLabel(e.lifecycle_status)}
                  </span>
                </div>
                {#if e.objective}
                  <p class="mt-1 truncate text-sm text-muted-foreground">
                    {e.objective}
                  </p>
                {:else}
                  <p
                    class="mt-1 truncate text-sm italic text-muted-foreground/70"
                  >
                    Objective not set yet — add an objective and the first run to begin.
                  </p>
                {/if}
                <div class="mt-3 max-w-md">
                  <RunProgressBar runs={e.run_summaries} total={e.run_count} />
                </div>
              </div>
              <div
                class="flex flex-col items-end gap-1 whitespace-nowrap text-xs text-muted-foreground"
              >
                <span class="rounded bg-muted px-1.5 py-0.5">{e.project_name}</span>
                <span
                  class="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground"
                  title={e.owner?.name ?? 'Unknown owner'}
                >
                  {e.owner?.initials ?? '—'}
                </span>
                <span>{formatDate(e.updated_at)}</span>
              </div>
            </div>
          </a>
        {/each}
      </div>
    {/if}
  {/if}
</div>

{#if createProjectId}
  <ExperimentCreateModal
    bind:open={showCreate}
    projectId={createProjectId}
    onCreated={(exp) => goto(paths.experiment(exp.project_slug, exp.slug))}
  />
{/if}
```

> **Note on the "New experiment" button:** the spec's index header has a "New experiment" button, but creating an experiment requires a project. Since this index spans all projects, surface the modal only once a project is chosen — for this slice, omit the header button on the index and rely on per-project creation (project page + `ExperimentsTab`). The `ExperimentCreateModal` import and the bottom block above are wired and ready for a project-picker follow-up; leave `createProjectId` empty so the modal is inert. Confirm this with QA during verification — if a header entry point is wanted now, add a small project-picker dropdown that sets `createProjectId` then `showCreate = true`.

- [ ] **Step 2: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors. Adjust any `ui/` import that does not match the repo (e.g. `loading-spinner` / `error-alert` filenames — confirm against `frontend/src/lib/components/ui/`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/[org]/experiments/
git commit -m "feat(experiments): add org-wide experiments index page"
```

---

## Task 15: Rewrite `ExperimentsTab` — kill the double-click trap

**Files:**
- Modify (full rewrite): `frontend/src/lib/components/project/ExperimentsTab.svelte`

- [ ] **Step 1: Replace the file**

The current `ExperimentsTab.svelte` has the double-click trap (first click selects, second navigates) and raw `slate-*` colors. Replace the whole file with the version below — row body navigates immediately, an explicit chevron toggles an inline runs panel, multiple panels can be open at once, theme tokens throughout, and the status pill uses `lifecycle_status` via `experimentStatusClasses`.

```svelte
<script lang="ts">
    import { goto } from "$app/navigation";
    import { paths } from "$lib/paths";
    import {
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from "./projectUtils";
    import ProjectDataTable from "./ProjectDataTable.svelte";
    import RunsTab from "./RunsTab.svelte";
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import { Button } from "$lib/components/ui/button";
    import { ChevronRight } from "lucide-svelte";

    interface Props {
        experiments: any[];
        runs: any[];
        protocols: any[];
        projectId: string;
    }

    let { experiments, runs, protocols, projectId }: Props = $props();

    let showRunModal = $state(false);
    let runModalExperiment = $state<{ id: string; name: string } | null>(null);

    // Multiple rows may be expanded at once (replaces the single-select trap).
    let expandedIds = $state<Set<string>>(new Set());

    function toggleExpanded(id: string) {
        const next = new Set(expandedIds);
        if (next.has(id)) {
            next.delete(id);
        } else {
            next.add(id);
        }
        expandedIds = next;
    }

    function openExperiment(e: any) {
        goto(paths.experiment(e.project_slug, e.slug));
    }

    function openCreateRunFor(e: any) {
        runModalExperiment = { id: e.id, name: e.name };
        showRunModal = true;
    }

    function runsFor(experimentId: string): any[] {
        return runs.filter((r: any) => r.experiment_id === experimentId);
    }

    const columns = [
        { key: "expand", label: "", align: "left" as const },
        { key: "name", label: "Name", sortable: true },
        { key: "objective", label: "Objective", hideBelow: "md" as const },
        { key: "lifecycle_status", label: "Status", sortable: true },
        { key: "run_count", label: "Runs", align: "right" as const },
        {
            key: "updated_at",
            label: "Last Modified",
            sortable: true,
            align: "right" as const,
        },
    ];

    function filterFn(item: any, query: string): boolean {
        if (!query) return true;
        return (
            item.name?.toLowerCase().includes(query) ||
            item.objective?.toLowerCase().includes(query) ||
            item.lifecycle_status?.toLowerCase().includes(query)
        );
    }
</script>

<ProjectDataTable
    items={experiments}
    {columns}
    filterPlaceholder="Filter experiments..."
    {filterFn}
    onRowClick={openExperiment}
>
    {#snippet mobileCard(e)}
        <button
            type="button"
            class="w-full py-3 text-left"
            onclick={() => openExperiment(e)}
        >
            <div class="mb-1 flex items-center justify-between">
                <span class="text-sm font-medium text-foreground">{e.name}</span>
                <span
                    class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold {experimentStatusClasses(
                        e.lifecycle_status,
                    )}"
                >
                    {experimentStatusLabel(e.lifecycle_status)}
                </span>
            </div>
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
                {#if e.objective}
                    <span class="max-w-[180px] truncate">{e.objective}</span>
                    <span>&middot;</span>
                {/if}
                <span>{e.run_count} run{e.run_count !== 1 ? "s" : ""}</span>
                <span>&middot;</span>
                <span>{formatDate(e.updated_at || e.created_at)}</span>
            </div>
        </button>
    {/snippet}

    {#snippet cells(e)}
        <td class="py-3 pl-6 pr-2 sm:pl-8">
            <button
                type="button"
                class="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={expandedIds.has(e.id) ? "Hide runs" : "Show runs"}
                aria-expanded={expandedIds.has(e.id)}
                onclick={(ev) => {
                    ev.stopPropagation();
                    toggleExpanded(e.id);
                }}
            >
                <ChevronRight
                    class="h-4 w-4 transition-transform {expandedIds.has(e.id)
                        ? 'rotate-90'
                        : ''}"
                />
            </button>
        </td>
        <td class="py-3 px-4 text-sm font-medium text-foreground">{e.name}</td>
        <td
            class="hidden max-w-[250px] truncate px-4 py-3 text-sm text-muted-foreground md:table-cell"
        >
            {e.objective || "--"}
        </td>
        <td class="whitespace-nowrap px-4 py-3">
            <span
                class="inline-block rounded-full px-3 py-0.5 text-xs font-semibold {experimentStatusClasses(
                    e.lifecycle_status,
                )}"
            >
                {experimentStatusLabel(e.lifecycle_status)}
            </span>
        </td>
        <td class="px-4 py-3 text-right text-sm text-foreground">{e.run_count}</td>
        <td
            class="whitespace-nowrap px-4 py-3 pr-6 text-right text-sm text-muted-foreground sm:pr-8"
        >
            {formatDate(e.updated_at || e.created_at)}
        </td>
    {/snippet}

    {#snippet empty()}
        {#if experiments.length === 0}
            <p class="text-[15px] font-semibold text-foreground">
                No experiments yet
            </p>
            <p class="text-[13px] text-muted-foreground">
                Create one to start organizing your runs.
            </p>
        {:else}
            <p class="text-[15px] font-semibold text-foreground">
                No matching experiments
            </p>
            <p class="text-[13px] text-muted-foreground">
                Try a different search term.
            </p>
        {/if}
    {/snippet}
</ProjectDataTable>

<!-- Inline runs panels — one per expanded row. -->
{#each experiments as e (e.id)}
    {#if expandedIds.has(e.id)}
        {@const expRuns = runsFor(e.id)}
        <div class="mt-4 px-4 sm:px-8">
            <div class="mb-3 flex items-center gap-3">
                <div class="h-px flex-1 bg-border"></div>
                <a
                    href={paths.experiment(e.project_slug, e.slug)}
                    class="text-xs font-medium uppercase tracking-wider text-primary hover:underline"
                >
                    {e.name} — Runs ({expRuns.length})
                </a>
                <div class="h-px flex-1 bg-border"></div>
            </div>
            {#if expRuns.length > 0}
                <RunsTab
                    runs={expRuns}
                    {protocols}
                    {experiments}
                    hideExperimentColumn={true}
                    hideExportColumn={true}
                />
                <div class="mt-3 text-right">
                    <Button variant="outline" size="sm" onclick={() => openCreateRunFor(e)}>
                        + Add run
                    </Button>
                </div>
            {:else}
                <div
                    class="rounded-lg border border-dashed border-border py-8 text-center"
                >
                    <p class="mb-1 text-[15px] font-semibold text-foreground">
                        This experiment doesn't have any run data yet.
                    </p>
                    <p class="mb-4 text-[13px] text-muted-foreground">
                        Create a run to start collecting data.
                    </p>
                    <Button onclick={() => openCreateRunFor(e)}>+ Create Run</Button>
                </div>
            {/if}
        </div>
    {/if}
{/each}

<RunCreatorWizardModal
    bind:open={showRunModal}
    {projectId}
    {protocols}
    forExperiment={runModalExperiment}
    onCreated={() => {
        runModalExperiment = null;
    }}
/>
```

> If `ProjectDataTable` does not support a leading non-data `expand` column cleanly, drop the `expand` column entry from `columns` and instead render the chevron as the first element inside the `name` cell. Verify against `ProjectDataTable.svelte`'s actual column/snippet contract before finalizing.

> **Icon import:** the repo uses both `lucide-svelte` (named imports) and
> `@lucide/svelte/icons/<name>` (per-icon). `ChevronRight` above uses the
> named-import form; if `npm run check` cannot resolve it, switch to
> `import ChevronRight from '@lucide/svelte/icons/chevron-right';`.

> **Caution — runs-panel vs. `run_count`:** the inline panel renders `RunsTab`
> from the project page's `runs` prop, filtered client-side by `experiment_id`.
> The row's `Runs` column comes from the experiment's server-side `run_count`.
> These agree only while the project page loads its runs **unpaginated**. If
> run pagination is later added to the project page, the expanded panel will
> under-count — at that point the panel must fetch the experiment's runs
> directly instead of filtering a partial prop.

- [ ] **Step 2: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/project/ExperimentsTab.svelte
git commit -m "fix(experiments): remove ExperimentsTab double-click trap, migrate to theme tokens"
```

---

## Task 16: Project page — use `ExperimentCreateModal`

**Files:**
- Modify: `frontend/src/routes/[org]/projects/[projectSlug]/+page.svelte`

- [ ] **Step 1: Replace the inline create-experiment modal**

In `frontend/src/routes/[org]/projects/[projectSlug]/+page.svelte`:

1. Add the import near the other component imports:
   ```typescript
   import ExperimentCreateModal from "$lib/components/experiment/ExperimentCreateModal.svelte";
   ```
2. Remove the inline experiment-modal state — the `newExperimentName`, `newExperimentDescription`, `createExperimentError` `$state` declarations and the `createExperiment()` function (the inline modal markup it drives).
3. Keep `showExperimentModal` — it now drives the extracted modal.
4. Where the inline experiment modal markup currently renders, replace it with:
   ```svelte
   <ExperimentCreateModal
       bind:open={showExperimentModal}
       projectId={project?.id ?? ''}
       onCreated={(exp) => goto(paths.experiment(exp.project_slug, exp.slug))}
   />
   ```
5. The "+ New Experiment" button already sets `showExperimentModal = true` — leave it (drop the `createExperimentError = null` line if `createExperimentError` was removed).

- [ ] **Step 2: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors, no unused-variable warnings for the removed state.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/[org]/projects/[projectSlug]/+page.svelte
git commit -m "refactor(experiments): use shared ExperimentCreateModal on project page"
```

---

## Task 17: Detail page — Objective block + derived status pill

**Files:**
- Modify: `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`

This page is ~355 lines. Read it fully before editing. The changes:

- [ ] **Step 1: Remove the Edra editor and the manual status `<select>`**

In the `<script>`:
- Delete the Edra lazy-load: the `EdraEditor` / `EdraToolBar` `$state`, the `onMount` import block that loads `$lib/components/edra/shadcn`, and the `editor` / `Editor` references.
- Delete `let status = $state("DRAFT");` and `const statusOptions = [...]`.
- In `loadData()`, delete the line `status = experiment.status;`.
- In the save function, stop sending `content` and `status`. The save body becomes `{ name, description, objective, success_criteria }`. Add `objective` and `success_criteria` to the page `$state` (initialized from `experiment.objective` / `experiment.success_criteria` in `loadData()`).

- [ ] **Step 2: Replace the "Content" Edra block with the Objective section**

Find the `<!-- Content Editor -->` block (the `<h3>Content</h3>` + Edra `<svelte:component>` region) and replace the whole block with a structured Objective section. It is read-only by default and enters edit mode via an explicit Edit button:

```svelte
<!-- Objective -->
<div class="rounded-lg border border-border bg-card p-5">
    <div class="mb-3 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">Objective</h3>
        {#if !editingObjective}
            <Button
                variant="ghost"
                size="sm"
                class="min-h-11"
                onclick={() => (editingObjective = true)}
            >
                Edit
            </Button>
        {/if}
    </div>

    {#if editingObjective}
        <div class="space-y-4">
            <div class="space-y-1.5">
                <label class="text-xs font-medium text-muted-foreground" for="obj">
                    The question
                </label>
                <Textarea id="obj" bind:value={objective} rows={3} />
            </div>
            <div class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">
                    Success criteria
                </span>
                {#each successCriteria as _, i}
                    <div class="flex items-center gap-2">
                        <Input bind:value={successCriteria[i]} placeholder="Criterion" />
                        <Button
                            variant="ghost"
                            size="icon"
                            class="shrink-0"
                            aria-label="Remove criterion"
                            onclick={() =>
                                (successCriteria = successCriteria.filter(
                                    (_, j) => j !== i,
                                ))}
                        >
                            <X class="h-4 w-4" />
                        </Button>
                    </div>
                {/each}
                <Button
                    variant="outline"
                    size="sm"
                    onclick={() => (successCriteria = [...successCriteria, ''])}
                >
                    + Add criterion
                </Button>
            </div>
            <div class="flex justify-end gap-2">
                <Button variant="ghost" onclick={cancelObjectiveEdit}>Cancel</Button>
                <Button onclick={saveObjective} disabled={saving}>
                    {saving ? 'Saving…' : 'Save'}
                </Button>
            </div>
        </div>
    {:else if objective}
        <div class="space-y-3">
            <div>
                <p class="text-xs font-medium text-muted-foreground">The question</p>
                <p class="mt-0.5 text-sm text-foreground">{objective}</p>
            </div>
            {#if successCriteria.length > 0}
                <div>
                    <p class="text-xs font-medium text-muted-foreground">
                        Success criteria
                    </p>
                    <ul class="mt-1 list-inside list-disc space-y-0.5 text-sm text-foreground">
                        {#each successCriteria as c}
                            <li>{c}</li>
                        {/each}
                    </ul>
                </div>
            {/if}
        </div>
    {:else}
        <p class="text-sm italic text-muted-foreground">
            Objective not set yet — add an objective and the first run to begin.
        </p>
    {/if}
</div>
```

Add the supporting script state and functions (place near the other `$state`):

```typescript
import { Input } from '$lib/components/ui/input';
import { Textarea } from '$lib/components/ui/textarea';
import { X } from 'lucide-svelte'; // or '@lucide/svelte/icons/x' — match repo

let objective = $state('');
let successCriteria = $state<string[]>([]);
let editingObjective = $state(false);

function cancelObjectiveEdit() {
    objective = experiment?.objective ?? '';
    successCriteria = [...(experiment?.success_criteria ?? [])];
    editingObjective = false;
}

async function saveObjective() {
    saving = true;
    try {
        const updated = await api.put(`/experiments/${id}`, {
            objective: objective.trim() || null,
            success_criteria: successCriteria.map((c) => c.trim()).filter(Boolean),
        });
        experiment = updated;
        objective = updated.objective ?? '';
        successCriteria = [...(updated.success_criteria ?? [])];
        editingObjective = false;
    } catch (e) {
        error = e instanceof Error ? e.message : 'Failed to save objective.';
    } finally {
        saving = false;
    }
}
```

In `loadData()`, after `experiment` is assigned, add:
```typescript
objective = experiment.objective ?? '';
successCriteria = [...(experiment.success_criteria ?? [])];
```

- [ ] **Step 3: Replace the status `<select>` with a read-only pill**

Find the `<select bind:value={status} ...>` block and replace it with a read-only pill driven by `experiment.lifecycle_status`, with the derivation tooltip:

```svelte
<span
    class="inline-block cursor-help rounded-full px-3 py-1 text-xs font-semibold {experimentStatusClasses(
        experiment?.lifecycle_status ?? 'DRAFT',
    )}"
    title="Status is derived from this experiment's runs — add or complete runs to advance it."
>
    {experimentStatusLabel(experiment?.lifecycle_status ?? 'DRAFT')}
</span>
```

`experimentStatusClasses` / `experimentStatusLabel` are already imported on this page.

- [ ] **Step 4: Keep the status pill current after run mutations (T3 reactive)**

`lifecycle_status` is derived server-side on every fetch — the pill only moves
when the detail page refetches. So **every** path that mutates this
experiment's run set must end in an `await loadData()`, or the pill silently
goes stale. This is the reactive-UI half of the **T3** tier for the status
rollup (see `conventions.md` "Validation Tiers"); note the tier in the PR.

Do not assume the callbacks are wired — **open the file and check each one**.
Audit these call sites and add `await loadData()` to any that is missing it
(closing the modal is not enough):
- `RunCreatorWizardModal` — `onCreated`
- `AddExistingRunModal` — `onAdded` / `onCreated`
- the run-unlink / remove-run handler
- any run-complete or run-status-change callback wired on this page

If a callback only closes its modal, that is the bug — append the refetch.

- [ ] **Step 5: Verify**

Run (from `frontend/`): `npm run check`
Expected: no new errors. Remove any now-unused imports (`flip`, `blockDuration`, edra types) the type-checker flags.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte
git commit -m "feat(experiments): Objective block and derived status pill on detail page"
```

---

# Phase C — Wrap-up

## Task 18: Update `.claude/rules/conventions.md`

**Files:**
- Modify: `.claude/rules/conventions.md`

- [ ] **Step 1: Add the `experiment/` component bucket**

In `.claude/rules/conventions.md`, in the "Component placement" list, add a new bullet (keep the list's alphabetical-ish grouping — place near `equipment/`):

```markdown
- `experiment/` — org-wide experiments index surfaces, run progress bar, experiment create modal
```

- [ ] **Step 2: Commit**

```bash
git add .claude/rules/conventions.md
git commit -m "docs(experiments): register experiment/ component bucket"
```

---

## Task 19: Full verification sweep

- [ ] **Step 1: Backend test suite**

Run (from `backend/`): `pytest tests/unit tests/integration -q`
Expected: all pass, no regressions. Investigate any failure before proceeding.

- [ ] **Step 2: Backend lint**

Run (from `backend/`): `mypy app/services/experiments app/api/endpoints/experiments.py`
Expected: clean. Match file-local style for any formatting — do not run blanket `black`/`isort`.

- [ ] **Step 3: Frontend checks**

Run (from `frontend/`): `npm run check && npm run test`
Expected: both pass.

- [ ] **Step 4: Migration sanity on the worktree dev DB**

With the worktree dev DB provisioned: `alembic upgrade head` is already applied (Task 1). Confirm `python -m app.db.seed` still succeeds and the app boots (`uvicorn app.main:app` starts clean).

- [ ] **Step 5: Browser verification**

This is the qa-verify step of the implement-task flow — hand off to the `qa-verify` agent. Manual smoke list:
- Experiments nav entry appears, routes to `/[org]/experiments`, highlights when active.
- Index lists experiments across projects with stat strip, filter pills, search; draft rows show the "Objective not set yet" callout; `RunProgressBar` renders.
- `ExperimentsTab` on a project page: a single row click navigates straight to the detail page; the chevron expands an inline runs panel; multiple panels open independently.
- Create an experiment via the project page modal — objective + helper copy present; created experiment opens.
- Detail page: Objective block edits via the Edit button → Save round-trip; status pill is read-only with the derivation tooltip; no Edra editor, no manual status select; no right-rail; no Export button.
- Add a run to an experiment, complete it — the detail-page status pill advances DRAFT → IN_PROGRESS → COMPLETE after refetch.

---

## Review panel — changes applied

This plan was reviewed by the implement-task step-2d panel
(adversarial-risk-auditor, production-ops-reviewer, dry-reuse-auditor,
db-scalability-reviewer, uiux-design-reviewer). Every disputed claim was
verified against `main` before acting. Changes folded in:

**Blockers (would have failed at implementation time):**
- **Task 8 — wrong session factory + un-importable `scripts/`.** The script
  imported `async_session_factory` (real export is `AsyncSessionLocal`) and the
  test imported `from scripts...` (`backend/scripts/` has no `__init__.py`).
  Restructured: backfill logic now lives in
  `app/services/experiments/backfill.py` (importable); `scripts/...py` is a thin
  CLI using `AsyncSessionLocal`. Hedge note removed.
- **Task 1 — `postgresql_ops={"updated_at": "DESC"}` is invalid** (it takes
  operator-class names, not sort direction). Replaced with
  `["project_id", sa.text("updated_at DESC")]`.
- **Task 6 — `test_permission_filters_restricted_projects` false premise.** It
  asserted `test_project` is visible to a plain member, but `test_project` is
  permissions-locked with an ADMIN grant for `test_user` only. Rewritten to
  create its own `permissions_enabled=False` project for the visible case; a
  Context note now documents the fixture's locked nature.
- **Task 10 — MobileNav structure.** Step 2 assumed per-link markup; MobileNav
  builds a `$derived` `links` array. Rewritten to insert the entry into the
  org-branch array only.

**Correctness / robustness:**
- Task 8 backfill now **commits per batch** — restartable after a crash.
- Task 3 — `derive_lifecycle_status` normalizes enum/str input defensively;
  added an enum-input test (9 tests total).
- Task 4 — `ExperimentResponse.lifecycle_status` is now a **required** field
  (no default) so a handler that forgets to supply it fails loudly.
- Task 7 — added `test_rejects_nonexistent_experiment` (random UUID → 404).
- Task 9 — Step 2 now also replaces a dead pre-F-0091 `pageTitle` guard
  (`/experiments/...`) with an org-scoped detail guard.

**Scalability:**
- Task 6 — `GET /experiments` query gains `selectinload(created_by)` +
  `lazyload(project)` (suppresses a redundant org-wide project fetch) and a
  `.limit(500)` safety backstop; the no-op owner-loading loop was deleted.

**UI/UX (uiux-design-reviewer):**
- Task 11 — `RunProgressBar` segments: `gap-1` + `rounded-sm` per segment.
- Task 13 — `ExperimentCreateModal` Cancel explicitly resets; description gains
  a helper line.
- Task 14 — index page: raw `<button>`/`<input>` replaced with shadcn `Button`
  / `Input`; `font-mono` on stat numbers; `EXP-…` moved into the title row;
  single-column header; a comment flags that client-side filtering/stats are
  valid only while the endpoint is unpaginated.
- Task 15 — `ExperimentsTab` inline-SVG chevron replaced with lucide
  `ChevronRight`; caution note on the runs-panel vs. `run_count` disconnect.
- Task 17 — Objective Edit button gets a `min-h-11` tablet touch target;
  success-criteria "Remove" is now an icon button; Step 4 callback audit
  strengthened with an explicit checklist and the T3-tier note.

**Rejected:** a db-scalability claim that `downgrade()` leaks indexes — verified
false; `downgrade()` already drops all three indexes before the columns.

---

## Spec coverage check

| Spec section | Task(s) |
| --- | --- |
| §1.1 `GET /experiments`, summary schemas, SQL run cap, lifecycle aggregates, auth, slow-query log | 4, 6 |
| §1.2 index route + nav + page title | 9, 10 |
| §1.3 index page contents (eyebrow, stat strip, filter row, rows, draft callout, states) | 14 |
| §1.4 `RunProgressBar` + color helper + accessibility | 11 |
| §1.5 `ExperimentsTab` double-click fix + theme + pill | 12, 15 |
| §1.6 `POST /runs` integrity guard + `logger.warning` | 7 |
| §2.1 model fields | 2 |
| §2.2 migration (DDL + indexes + normalization) + idempotent backfill script | 1, 8 |
| §2.3 schemas (`ExperimentCreate/Update/Response`, `extra="forbid"`) | 4 |
| §2.4 `ExperimentCreateModal` + reuse on project page | 13, 16 |
| §2.5 detail-page Objective block, scope guards (no right-rail / Export) | 17 |
| §3.1 `derive_lifecycle_status` count-based, never-raises | 3 |
| §3.3 API surface — `lifecycle_status` everywhere, `status` dropped, `PUT` keeps `log_audit` | 4, 5 |
| §3.4 frontend pills, `projectUtils` rewrite to lifecycle values + tokens | 12, 15, 17 |
| §3.5 T3 reactive — pill refetch on run mutations | 17 |
| Component placement (`experiment/` bucket) | 18 |

All spec sections map to a task.
