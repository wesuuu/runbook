# F-0093 — Experiments Redesign: Investigation Workspace (Phases 1–3)

**Status:** Design approved · **Date:** 2026-05-21 · **Scope:** Phases 1–3 of ClickUp F-0093

## Context

The Experiments feature (F-0063) is structurally complete but feels tacked on: a thin
folder around Runs with no discoverability, no payoff, and a decorative status field.
F-0093 reframes an Experiment as the primary scientific unit — an investigation with an
objective, runs as its conditions/replicates, a comparison, and a recorded conclusion.

The full task is 7 phases (XL). **This spec covers the first slice — Phases 1–3** —
which together make Experiments feel like a real feature: discoverable, with a stated
objective, and a status that reflects reality. Phases 4–7 (Conditions view, Results &
Conclusion, Export, Observations timeline) are deferred to a follow-up ClickUp task.

Approved mockup: `docs/mockups/experiments-redesign.html` (experiments index +
redesigned detail page). The mockup illustrates all 7 phases; only the Phase 1–3
surfaces are built here.

### Current state (post-TD-0083, on `main`)

- **Model:** `Experiment` in `backend/app/models/runs.py` — `name`, `description`,
  `content` (JSONB Edra doc), `status` (str), `notes` (JSONB), `slug`, `project_id`.
- **Schemas:** `backend/app/schemas/runs.py` — `ExperimentCreate/Update/Response`,
  `ExperimentStatus`.
- **Endpoints:** `backend/app/api/endpoints/experiments.py`, mounted with **no prefix**
  (`/experiments`, `/projects/{id}/experiments`, `/experiments/by-slug/...`).
- **Routing (F-0091):** org-scoped. Experiment detail lives at
  `/[org]/projects/[projectSlug]/experiments/[slug]`. There is **no** experiments index.
  URL builders are in `frontend/src/lib/paths.ts`.
- **Detail page:** `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`
  — blank "Content" Edra box, runs table, notes, a manual status `<select>`.
- **Project tab:** `frontend/src/lib/components/project/ExperimentsTab.svelte` — first
  row click *selects* (shows an inline runs panel), second click *navigates* (the
  double-click trap).
- **Nav:** `frontend/src/routes/+layout.svelte` — Dashboard / Library / AI Chat; no
  Experiments entry.

> The working branch `td-0083-split-science-module` is the stale TD-0083 dev branch
> and predates both TD-0083 and F-0091. All implementation branches from `main`,
> where both TD-0083 (the `models/science.py` split) and F-0091 (org-slug routing —
> the `[org]/...` route tree this spec builds on) are already merged. Do not read the
> current branch to gauge structure; read `main`.

## Goals

1. **Discoverable** — a top-level Experiments index across all projects, in the nav.
2. **Purposeful** — every experiment states an objective and success criteria.
3. **Honest status** — lifecycle status derived from child runs, not hand-set.

## Non-goals (deferred to the Phases 4–7 follow-up task)

Conditions view (varied-parameter diffing), Results comparison chart, editable
conclusion + completion gate, edit-reason policy for `conclusion`, summary export,
observations timeline. The `content` column is **kept** (not dropped) for these phases.

---

## Phase 1 — Discoverability & IA

### 1.1 Backend — org-wide experiments listing

New endpoint `GET /experiments` in `experiments.py`:

- **Org isolation is enforced in SQL**, not by permission checks: the query
  `JOIN`s `projects` and filters `Project.organization_id == user.selected_org_id`.
  A user with a null `selected_org_id` gets `400` (never an unfiltered result).
  The index lists experiments across **all** of the org's projects — `projects`
  has no lifecycle/archive column on `main` (projects are not archivable), so there
  is no archived-project set to exclude. Adding project archival is explicitly out
  of F-0093's scope; if it ever lands, the exclusion is added then.
- **Permission filtering is a single bulk pass**, never a per-project loop. Resolve
  the distinct project IDs of the org's experiments, then in one step keep the
  projects the user can `VIEW`: org-admins and `permissions_enabled = false`
  projects pass automatically; for the rest, one `ObjectPermission` query with
  `object_id IN (...)` (user + team grants). ~3 queries total regardless of project
  count — `check_permission`'s ~6-query-per-call cost is not acceptable on a list
  endpoint.
- Returns a **lightweight** summary per experiment — not the heavy `ExperimentResponse`
  (which embeds full `RunResponse` objects).

New schema `ExperimentSummary` in `schemas/runs.py`:

```python
class ExperimentRunSummary(BaseModel):
    status: str            # RunStatus
    outcome: Optional[str] # RunOutcome | None

class ExperimentOwner(BaseModel):
    id: UUID
    name: str       # User.full_name, falling back to User.email
    initials: str   # see derivation below

class ExperimentSummary(BaseModel):
    id: UUID
    slug: str
    name: str
    objective: Optional[str] = None
    project_id: UUID
    project_slug: str
    project_name: str
    lifecycle_status: str          # see Phase 3
    run_count: int
    run_summaries: list[ExperimentRunSummary] = []   # capped — see below
    owner: Optional[ExperimentOwner] = None
    created_at: datetime
    updated_at: datetime
```

`run_count` is computed in SQL (`func.count` over runs), not by loading rows.
`run_summaries` is **capped at 60 entries** per experiment **in SQL** — a
`ROW_NUMBER() OVER (PARTITION BY run.experiment_id ORDER BY run.created_at)`
subquery keeps only rows with `row_number <= 60`, so the database never ships more
than 60 run rows per experiment to the app. (A plain `selectinload` of every run
would defeat the cap: it loads the full set into memory and only then slices, so an
experiment with thousands of runs still pays the full transfer.) `created_by` is
loaded with one `selectinload`. Results are ordered by `updated_at desc`.
`run_count` always carries the true total, so the cap bounds both the payload and
the `RunProgressBar` segment count without hiding how many runs really exist.

**`lifecycle_status` is computed from uncapped SQL aggregates, never from the
capped `run_summaries`.** The 60-row cap is a payload bound for the progress bar
*only*. If `derive_lifecycle_status` ran over the truncated list, an experiment
with 65 runs whose three open runs sit at positions 61–65 would derive a false
`COMPLETE` — exactly the dishonest-status bug F-0093 exists to kill. So the
endpoint computes, per experiment, two `COUNT(*) FILTER (...)` aggregates over the
*full* run set — `live_run_count` (runs whose status ≠ `ARCHIVED`) and
`open_run_count` (live runs whose status ≠ `COMPLETED`) — and feeds those counts to
`derive_lifecycle_status` (§3.1). The counts ride along in the same grouped query
as `run_count`; no extra round trip.

**Auth & observability.** `GET /experiments` is a read endpoint: it takes
`Depends(get_current_user)` + `Depends(get_db)` but **no** `require_active_subscription()`
— reading one's own experiments must not break when a subscription lapses; that
guard stays on the mutations (`POST` / `PUT` / `DELETE`), matching the existing
`experiments.py` pattern. The handler logs one slow-query line at `WARNING`
(`logger.warning`) when query wall-time exceeds a threshold (e.g. 500 ms), with the
org id and experiment count — so the move to server-side pagination (see Risks) is
triggered by data, not a complaint.

**Owner initials** are derived server-side: from `User.full_name`, take the first
letter of the first two whitespace-separated words, uppercased (`"Ada Lovelace"` →
`"AL"`, `"Ada"` → `"A"`); if `full_name` is empty, use the first letter of the
email local-part. `owner` is `None` when `created_by_id` is null — pre-feature
rows, or a since-deleted user via `ondelete="SET NULL"` — and the UI renders a
neutral placeholder avatar for that case.

### 1.2 Frontend — index route + nav

- New route `frontend/src/routes/[org]/experiments/+page.svelte`.
- `paths.ts`: add `experiments(): string => '/${orgSlug()}/experiments'`.
- `routes/+layout.svelte`: add an "Experiments" nav link (desktop nav + mobile nav),
  after Dashboard, active when the path matches `^/[^/]+/experiments`. Href is the
  org-prefixed `paths.experiments()` (empty pre-org, like `libraryHref`).
- `lib/utils/pageTitle.ts`: add a title for the new route.

### 1.3 Index page contents (per mockup, screen 1)

- **Header:** a small mono "Investigations" eyebrow (`font-mono`, uppercase, tracked,
  `text-accent`) above the page title, then description + "New experiment" button
  (opens `ExperimentCreateModal`, §2.4).
- **Summary strip — 3 stat cards:** Experiments (total), In progress
  (`lifecycle_status == IN_PROGRESS`), Runs across all (sum of `run_count`).
  *(The mockup's 4th "Runs need action" card is dropped — no defined metric.)*
- **Filter row:** segmented pills `All / In progress / Complete / Draft` + a search box.
  Both filter **client-side** over the fetched list. Acceptable for early orgs; see
  Risks for when this and the missing pagination must become server-side.
- **Experiment rows:** name + status pill on the title line; objective line below;
  segmented `RunProgressBar` with `n / m runs`; a right-side metadata column with
  project tag, short id (`shortId()` → `EXP-{first 8 hex}`), owner avatar, and
  relative updated-at. The whole row links to `paths.experiment(projectSlug, slug)`.
  **No separate status dot** — the pill carries the state with a text label
  (color-only encoding is not accessible); for an `IN_PROGRESS` experiment the pulse
  lives *inside* the pill, not as a second standalone circle.
- **Draft rows:** when `objective` is null, the objective line renders the callout
  "Objective not set yet — add an objective and the first run to begin." rather than
  an empty line, with the dashed-border draft treatment from the mockup.
- **Loading / error / empty** states consistent with existing pages: a skeleton row
  set while loading (fading to content), an inline error card with retry, and an
  empty state with a "New experiment" call to action.

### 1.4 `RunProgressBar` component

New `frontend/src/lib/components/experiment/RunProgressBar.svelte` — one flex segment
per run, colored by run status + outcome. Reused on index rows and the detail page.
Color mapping (single source of truth, exported helper):

| Run state | Color |
| --- | --- |
| `COMPLETED` + `COMPLETED_NORMAL` | accent (green) |
| `COMPLETED` + `COMPLETED_WITH_DEVIATIONS` | amber (`amber-400`, `dark:amber-500`) |
| `COMPLETED` + `ABORTED` | destructive (red) |
| `COMPLETED` + null outcome (legacy rows) | accent (green) — treated as normal |
| `ACTIVE` / `EDITED` | primary (pulse for `ACTIVE`) |
| `PLANNED` | muted |
| `ARCHIVED` | muted/gray |

Empty state (0 runs): a single muted track.

Color alone is not an accessible encoding: each segment carries a `title` /
`aria-label` of its run status + outcome, so the bar is legible to screen readers
and on hover. When `run_count > 60` the bar shows the 60 oldest segments while the
`n / m runs` label states the true total — add a "+N more" affordance so the
truncation is not silent.

### 1.5 `ExperimentsTab` double-click fix

`frontend/src/lib/components/project/ExperimentsTab.svelte`:

- Row click navigates straight to the detail page (`goto(paths.experiment(...))`) —
  no select-then-navigate.
- The inline runs panel moves behind an **explicit per-row disclosure control** (a
  chevron button in the row). Clicking the chevron toggles that experiment's inline
  runs panel; clicking the row body navigates.
- Replace the single `selectedExperimentId` nav-state with an `expandedExperimentIds`
  set, so multiple rows can be expanded independently. The existing
  `openCreateRunForExperiment` / inline-runs flow currently reads
  `selectedExperimentId` — the refactor must re-wire it to take its experiment from
  the expanded row's context so that flow is not orphaned. Each expanded panel keeps
  its own scoped "Add run" affordance (the empty-state "Create Run" button for a
  0-run experiment; an "Add run" button under the run list otherwise).
- **Theme cleanup.** `ExperimentsTab.svelte` is currently raw `slate-*` Tailwind
  classes; once the index page lands in the `shadcn-svelte` token system the two
  experiment surfaces would read as two different apps on one project page. Since
  this file is already being rewritten for the double-click fix, migrate its colors
  to tokens (`bg-muted`, `text-muted-foreground`, `bg-primary`, `border-border`, …)
  in the same pass, and render its status pill via the shared `experimentStatusClasses`
  helper (§3.4) rather than bespoke classes.

### 1.6 Run↔experiment integrity hardening

`POST /runs` (`runs.py`) currently assigns `experiment_id` straight from the request
body with no validation — a run can be created pointing at an experiment in a
different project or even a different org, which would pollute that experiment's
`lifecycle_status` (Phase 3) and leak the run's status into the org-wide index. The
link path (`POST /experiments/{id}/runs`) already enforces same-project; the create
path must match it.

When `RunCreate.experiment_id` is set, `POST /runs` must:

- `get_or_404` the experiment;
- reject with `400` / error code `RUN_EXPERIMENT_PROJECT_MISMATCH` if
  `experiment.project_id != run_in.project_id` — same-project covers org isolation,
  since the project carries the org;
- reject with `400` / `RUN_EXPERIMENT_ARCHIVED` if the experiment is `ARCHIVED`.

This enforces the invariant — *a run's experiment shares its project* — that Phase
3's read-time derivation depends on. T1 (backend-only): the run-create UI already
constrains its experiment picker to in-project experiments, so the error is a
belt-and-braces guard, not a button gate.

Because the guard should be unreachable through the UI, each rejection emits a
`logger.warning` (org id, user id, run's `project_id`, target `experiment_id`):
a client that actually trips it has an experiment picker that drifted out of sync,
which ops should see rather than have silently swallowed as a routine `400`.

---

## Phase 2 — Objective

### 2.1 Model

`Experiment` in `models/runs.py` gains:

- `objective: Mapped[Optional[str]]` — `Text`, nullable.
- `success_criteria: Mapped[list]` — `JSONB`, `default=list`, `server_default="[]"`,
  `nullable=False`. A list of strings.
- `created_by_id: Mapped[Optional[uuid.UUID]]` — FK `users.id`, `ondelete="SET NULL"`,
  nullable. Plus a `created_by` relationship.

The `content` column is **retained** (deprecated, no longer edited in the UI).

### 2.2 Migration + backfill

The schema change and the data backfill are **separate deliverables** so a slow or
failed backfill can never block or roll back the migration.

**Alembic revision — DDL + indexes + status normalization only:**

1. **Schema.** `ADD COLUMN` for all three (`objective`, `success_criteria`,
   `created_by_id`). `success_criteria` is added `NOT NULL DEFAULT '[]'` in a single
   statement so it succeeds against existing rows; review the autogenerated SQL by
   hand — Alembic mis-handles JSONB server defaults. (`ADD COLUMN ... NOT NULL
   DEFAULT '[]'` with a constant default is a metadata-only change on Postgres 11+ —
   no table rewrite.)
2. **Indexes.** The `GET /experiments` listing query (§1.1) is unindexed on `main`
   today — add three indexes in this revision. All three tables are small at current
   scale, so plain (non-`CONCURRENTLY`) creation inside the transactional migration
   is fine:
   - `ix_experiments_project_updated` on `experiments (project_id, updated_at DESC)`
     — serves the `ORDER BY updated_at DESC` after the `projects` join; without it
     the planner does an in-memory sort of the whole org's experiment set.
   - `ix_runs_experiment_created` on `runs (experiment_id, created_at)` — **`runs`
     has no index on `experiment_id` at all on `main`.** This one index covers the
     `ROW_NUMBER() OVER (PARTITION BY experiment_id ORDER BY created_at)` run-summary
     window (§1.1), the `COUNT(*) FILTER` lifecycle aggregates (§3.1), *and* the
     `experiment_id` lookups behind §1.6's `POST /runs` guard.
   - `ix_experiments_created_by` on `experiments (created_by_id)` — the new owner FK;
     cheap to add now, expensive (`CONCURRENTLY`, separate revision) once the table
     is large.
   The exact column order for `ix_experiments_project_updated` is validated against
   `EXPLAIN (ANALYZE, BUFFERS)` on seeded data during implementation; if the planner
   prefers a standalone `experiments (updated_at DESC)` index, the plan adjusts.
3. **Status normalization.** `UPDATE experiments SET status = 'DRAFT' WHERE status
   NOT IN ('DRAFT', 'ARCHIVED')` — collapses legacy `ACTIVE` / `COMPLETED` values so
   the column means only "archived or not" (Phase 3 reads only `ARCHIVED` from it).
   This is a row-locked `UPDATE` on a small table, safe inside the migration txn.
4. `created_by_id` is left `NULL` for existing rows (acceptable — pre-feature data).

**Downgrade** is schema-only: `DROP COLUMN` the three columns (which drops their
indexes) and `DROP INDEX ix_runs_experiment_created`. The status normalization is
not reversed — the original `ACTIVE` / `COMPLETED` values are not recoverable, and
re-upgrade simply re-derives `lifecycle_status` from runs. This is acceptable, and
is stated here so it is not mistaken for an omission.

**Objective backfill — separate idempotent script
`backend/scripts/backfill_experiment_objectives.py`:**

Run once after the migration deploys; safe to re-run because it only touches rows
where `objective IS NULL`, so a second run is a no-op. For each such experiment it
walks the `content` Tiptap/Edra JSON **iteratively** (an explicit stack, not
recursion — docs can be deeply nested), skipping any doc whose serialized size
exceeds a cap (256 KB) to avoid loading multi-MB JSONB into the process. It
concatenates text nodes, **truncates to 280 characters** (`objective` is a one-line
question, not the whole doc). `content` is preserved regardless.

**Batch by a keyset cursor on `id`, not a bare `LIMIT`.** The batch query is
`WHERE objective IS NULL AND id > :cursor ORDER BY id LIMIT 500`, and the cursor
advances to the last `id` of the batch *after every batch — including rows that
were skipped*. A naive `WHERE objective IS NULL LIMIT 500` would re-select the
skipped (over-cap / unparseable) rows on every iteration, since they stay
`objective IS NULL` forever — an infinite loop. Keyset pagination steps the cursor
past skipped rows so the script always terminates. Commit per batch (~500 rows).

The script ends with one **structured summary line** — at `INFO`, and additionally
at `WARNING` if anything was skipped — carrying the counts `total`, `already_set`,
`backfilled`, `skipped_over_cap`, `skipped_unparseable`. That line is the operator's
evidence the backfill ran and how many experiments still need a hand-entered
objective; without it the skipped rows are silent.

**Deploy checklist** (goes in the PR description): (a) before running the
migration, snapshot `SELECT id, status FROM experiments` to a file — the status
normalization is one-way, and the snapshot is the only way to reconstruct
pre-migration `ACTIVE` / `COMPLETED` values if the deploy is reverted; (b)
`alembic upgrade head`; (c) run `backfill_experiment_objectives.py`; (d) check the
summary log line for the `skipped_*` counts.

### 2.3 Schemas

`schemas/runs.py`:

- `ExperimentCreate`: add `objective: Optional[str] = None`,
  `success_criteria: list[str] = []`.
- `ExperimentUpdate`: add `objective`, `success_criteria` (both optional); set
  `model_config = ConfigDict(extra="forbid")`. With `status` removed (§3.3), a
  client still sending `{"status": ...}` would otherwise be **silently dropped** by
  Pydantic's default — `extra="forbid"` turns that into an explicit `422` so stale
  callers fail loudly instead of believing a status write succeeded.
- `ExperimentResponse`: add `objective`, `success_criteria`, and `created_by_id`.

### 2.4 Create flow

The create-experiment modal is currently inline in
`routes/[org]/projects/[projectSlug]/+page.svelte`. Extract it into a shared
`frontend/src/lib/components/experiment/ExperimentCreateModal.svelte`:

- Fields: name, objective, optional description.
- The objective field is introduced cold mid-workflow, so it carries scaffolding
  copy: placeholder `"What question are you investigating?"` and helper text below
  the field — `"Tip: phrase it as a testable hypothesis, e.g. 'Does raising the
  glucose setpoint increase day-12 titer?'"`. Objective stays optional, but the copy
  makes its purpose scannable without docs.
- `created_by_id` is set server-side from the authenticated user on `POST /experiments`.
- Reused by the project page **and** the index page's "New experiment" button.

### 2.5 Detail page — Objective block

Replace the blank "Content" Edra box with a structured **Objective** section (mockup
screen 2, block 1), in the detail page's main column:

- "The question" — the `objective` text.
- "Success criteria" — the `success_criteria` list of line items.

**Editing model.** The section is read-only by default and enters edit mode via an
explicit "Edit" icon button on the section header — *not* invisible click-to-edit,
which a gloved hand on a tablet cannot distinguish from static text. Edit mode shows
the objective as a textarea and the criteria as add/remove rows, with explicit
**Save** and **Cancel** buttons; Save issues one `PUT /experiments/{id}`. A null
objective renders the same "not set yet" callout as the index draft row (§1.3).

The Edra editor import and the `content` round-trip are removed from the detail page.

**Scope guards for the detail page in this slice:**
- The mockup's **right-rail** (progress card, "best uplift", "target close", close-out
  gate) is **deferred** — its content belongs to Phases 4–7. Phase 1–3 adds only the
  Objective block, a `RunProgressBar`, and the status pill, all in the main column.
- The mockup's **"Export summary"** header button is **deferred** (Phase 6) and must
  not be rendered. The detail header keeps its existing actions plus "Add run".

---

## Phase 3 — Status rollup (T3 — reactive)

### 3.1 Derivation

Lifecycle status is **derived at read time** from child runs — never stored as a
rolled-up value. Pure helper `derive_lifecycle_status` in a new
`backend/app/services/experiments/status.py`.

**The helper is count-based, not run-list-based.** It takes the experiment's
`status` plus two integers — `live_run_count` (runs whose status ≠ `ARCHIVED`) and
`open_run_count` (live runs whose status ∉ {`COMPLETED`}) — and returns:

```
ARCHIVED      if experiment.status == "ARCHIVED"
DRAFT         elif live_run_count == 0
COMPLETE      elif open_run_count == 0
IN_PROGRESS   otherwise
```

Taking counts rather than a list of runs is deliberate: the org-wide index caps
`run_summaries` at 60 rows (§1.1), and deriving status from that truncated list
would mis-derive `COMPLETE` for an experiment whose open runs sit past position 60.
Both callers supply the counts from a **full, uncapped** source — the list endpoint
from SQL `COUNT(*) FILTER` aggregates (§1.1), the detail endpoint from the full run
set it already loads — so the cap can never corrupt the status.

`ARCHIVED` runs are **excluded from the rollup**, not counted as "closed." Counting
them as closed would make an experiment whose runs were *all* thrown away derive
`COMPLETE` — the exact dishonest-status problem F-0093 exists to kill. An experiment
with only archived runs therefore derives `DRAFT` (`live_run_count == 0`). Among
live runs, `PLANNED` / `ACTIVE` / `EDITED` are open and only `COMPLETED` is closed
— so a run reopened `COMPLETED → EDITED` correctly flips the experiment back to
`IN_PROGRESS`.

**`derive_lifecycle_status` never raises.** It runs on every experiment read,
including the org-wide list — one malformed row must not 500 the whole index. The
count-based shape makes this near-automatic: the SQL `FILTER` predicate that builds
`open_run_count` treats any status that is not the literal `COMPLETED` as open, so
an unrecognized run status counts toward `open_run_count` and the experiment
derives `IN_PROGRESS`, never a false `COMPLETE`. Where statuses are classified in
Python (the detail path), an unknown status is logged once at `WARNING` with the
run id and likewise counted as open. The function always returns one of the four
known values.

The existing `status` column is **retained** but its only manually-settable value is
`ARCHIVED`, set via the existing archive endpoint (`DELETE /experiments/{id}`). It is
no longer a free-form lifecycle field.

### 3.2 Why read-time derivation

The Phase 3 AC — "status recomputes when a run is added, completed, or unlinked" — is
satisfied for free: every read recomputes. The alternative (a denormalized stored
status with recompute hooks in every run-create / complete / unlink endpoint) is more
code and a standing drift risk for no benefit.

### 3.3 API surface

- `ExperimentResponse` and `ExperimentSummary` expose a computed `lifecycle_status`.
- `ExperimentUpdate` **drops** the `status` field — it is no longer client-settable.
  The `PUT /experiments/{id}` handler stops reading `status` but **keeps its existing
  `log_audit` call** — `objective` / `success_criteria` edits are audited like any
  other experiment-field change.
- Archive remains `DELETE /experiments/{id}` (unchanged).

### 3.4 Frontend

- Detail page: remove the manual status `<select>`; render a read-only status pill
  driven by `lifecycle_status`. The pill carries a tooltip explaining the changed
  model — *"Status is derived from this experiment's runs — add or complete runs to
  advance it."* — so a scientist who used to set status by hand understands why the
  control is gone and why the pill moves on its own.
- `ExperimentsTab` and the index page render the same pill from `lifecycle_status`.
- `projectUtils.ts` `experimentStatusClasses` / `experimentStatusLabel` are
  **rewritten** to the four `lifecycle_status` values — `DRAFT`, `IN_PROGRESS`,
  `COMPLETE`, `ARCHIVED` — replacing the stale `ACTIVE` / `COMPLETED` cases (legacy
  rows are normalized by the §2.2 migration and `lifecycle_status` is derived, so
  those values never reach the frontend). `experimentStatusLabel` returns
  "In progress" / "Complete" to match the filter-pill labels (§1.3). Both use
  `shadcn-svelte` token classes, not raw `emerald-*` / `slate-*`.

### 3.5 Validation tier

Status rollup is **T3** (reactive UI): the pill surfaces ambient state on index +
detail + project tab. `lifecycle_status` is **point-in-time per fetch** — every read
recomputes it and the pill renders reactively from the latest fetched response; it
is not a live subscription. Surfaces that mutate run state must refetch the
experiment so the pill stays current — concretely, the detail page's `loadData()`
runs in the `onCreated` / `onCompleted` / unlink callback of every run-mutation
modal. No button is gated by it in this slice (the completion gate is Phase 5).
Integration test asserts `lifecycle_status` recomputes when a run is added,
completed, and unlinked.

---

## Testing

TDD throughout (Red-Green-Refactor), >80% coverage.

**Backend**
- `derive_lifecycle_status` — count-based, unit tests for every branch:
  `live_run_count == 0` → `DRAFT`; `open_run_count == 0` → `COMPLETE`; mixed →
  `IN_PROGRESS`; experiment `status == ARCHIVED`; `EDITED` counts as open;
  **only-archived-runs → `DRAFT`, never `COMPLETE`**; one `COMPLETED` + several
  `ARCHIVED` → `COMPLETE` (archived excluded); an unrecognized run status counts as
  open → `IN_PROGRESS` and the function does **not** raise.
- `GET /experiments` — returns org experiments; org isolation holds even with
  `auth_enabled = false` (SQL-level filter); `400` on null `selected_org_id`;
  permission-filters non-VIEW projects; caps `run_summaries` at 60 with the true
  `run_count`; returns `200` for a user whose subscription has lapsed (no
  `require_active_subscription`).
- **`lifecycle_status` correctness past the 60-run cap** — an experiment with 65
  runs where the 3 open runs sit at positions 61–65 must still report
  `IN_PROGRESS`, proving the status is derived from the uncapped `COUNT(*) FILTER`
  aggregates, not the truncated `run_summaries`.
- `POST /experiments` — persists `objective`, `success_criteria`, sets `created_by_id`.
- `PUT /experiments/{id}` — updates `objective` / `success_criteria`; a body
  containing `status` returns `422` (`extra="forbid"`).
- `POST /runs` — `experiment_id` in another project → `400 RUN_EXPERIMENT_PROJECT_MISMATCH`;
  archived experiment → `400 RUN_EXPERIMENT_ARCHIVED`; same-project experiment → ok.
- Migration — three columns added; the three indexes
  (`ix_experiments_project_updated`, `ix_runs_experiment_created`,
  `ix_experiments_created_by`) created; legacy `ACTIVE` / `COMPLETED` status
  normalized to `DRAFT`.
- Backfill script — populates `objective` from `content`, truncates to 280 chars,
  skips over-cap / unparseable docs; **terminates** when every candidate row is
  skipped (keyset cursor advances past skipped rows — no infinite loop); a second
  run is a no-op (idempotent); the summary line carries correct `backfilled` /
  `skipped_over_cap` / `skipped_unparseable` counts.
- **T3 integration test** — `lifecycle_status` transitions DRAFT → IN_PROGRESS →
  COMPLETE as a run is added, completed, and unlinked.

**Frontend**
- `RunProgressBar` — segment count + color mapping per run state; empty state;
  `aria-label` per segment; `>60`-run truncation shows "+N more".
- Index page — renders rows, 3-stat strip, client-side filter pills + search; a
  null-`objective` row shows the draft callout, not a blank line.
- `ExperimentsTab` — row click navigates; chevron toggles inline runs (no
  double-click); per-row "Add run" reaches the right experiment.
- `ExperimentCreateModal` — submits name + objective; objective placeholder/helper
  copy present.
- Detail page — Objective block edits via the Edit button → Save round-trip; status
  pill is read-only with the derivation tooltip; no right-rail, no Export button.

## Component placement

New frontend components go in a new `frontend/src/lib/components/experiment/` bucket
(`RunProgressBar.svelte`, `ExperimentCreateModal.svelte`, and any index-row piece) —
the experiment surfaces are org-scoped and span projects, so neither `project/` nor
`run/` fits. `.claude/rules/conventions.md`'s component-placement list is updated to
add the `experiment/` bucket (skill step 7).

## Risks / notes

- **Index scale.** The index is org-wide (spans all projects), so it has higher row
  cardinality than the per-project `ExperimentsTab`. Permission filtering is a bulk
  query (§1.1), but the list itself is unpaginated and filter/search run client-side.
  Acceptable for early orgs; server-side pagination + filtering is the first thing to
  add when an org exceeds ~200 experiments. Logged here, not built now.
- **`projects.organization_id`** has no dedicated index, but the existing
  `uq_projects_org_slug` unique constraint leads with `organization_id`, so the
  `GET /experiments` org filter is index-covered. No new index needed now; a
  partial index becomes worthwhile only once project archival exists and the filter
  gains a `status` predicate (out of F-0093 scope). Validate with `EXPLAIN` during
  implementation — if a Seq Scan appears, add `ix_projects_org_id`.
- **`content` backfill** is best-effort; over-cap or unparseable docs leave
  `objective` null. The `content` column is preserved either way, so no data is lost.
- **Pre-feature experiments** have `created_by_id = NULL` → no owner avatar; the UI
  renders a neutral placeholder. A later-deleted owner (`ondelete="SET NULL"`) lands
  in the same state.
- **Edit-reason policy.** `objective` and `success_criteria` are *not* "of record"
  fields under §58.130(e) — they are not part of an audited run dataset — so editing
  them needs no `edit_reason`. (The `conclusion` field, which will, is Phase 5.)
