# Experiments Redesign — Phases 4-7 Design

**ClickUp task:** `86e1h960k` (F-0043 follow-up)
**Predecessor spec:** `docs/superpowers/specs/2026-05-21-f-0093-experiments-investigation-workspace-design.md`
**Mockup:** `docs/superpowers/specs/2026-05-22-experiments-phases-4-7-mockup.html`

## Background

F-0093 shipped Phases 1-3 of the Experiments Redesign (lifecycle status, objective/success criteria, notes). It deliberately kept `Experiment.content` JSONB on the model so that the deferred phases — Conditions, Results & Conclusion, Export, Observations — could land without another schema churn.

This spec covers those four phases as a single slice, delivered through one worktree, one migration, and one merge.

## Decisions (locked)

1. **Slice strategy:** all four phases in one slice. Conditions and Results table share data plumbing; Conclusion lock is the lifecycle terminator; Observations + Export read across both. Splitting would invent integration seams that don't exist in the product.
2. **Key-result storage:** structured per-run columns (`key_result_label`, `key_result_value`, `key_result_unit`) rather than reusing `Run.outcome_notes` or a free-form JSONB blob. Lets the scatter chart and the export reuse the same numeric type without parsing text.
3. **Lock semantics:** new lifecycle state `AWAITING_CONCLUSION` between `IN_PROGRESS` and `COMPLETE`. Explicit `POST .../conclusion/lock` and admin-only `POST .../conclusion/unlock` endpoints; unlock requires a non-empty `reason` written to the audit log.
4. **Varied-param detection:** auto-detect by `(node.data.label, paramKey)` walking each run's snapshotted graph. No user marking required.
5. **Value rendering:** value + unit pulled from `paramSchema.properties[k].unit` when declared; bare value otherwise.
6. **Export:** synchronous `application/pdf` via fpdf2, reusing the batch-record PDF primitives.
7. **Observations source:** `experiment.notes` flagged `observation` or `anomaly`, plus `run.notes` flagged `anomaly` (run notes don't permit `observation` per `ALLOWED_NOTE_FLAGS`).

## Section 1 — Schema & data model

### `experiments` (new columns)

| Column | Type | Notes |
|---|---|---|
| `conclusion` | `Text` nullable | Free-form markdown-flavored prose |
| `conclusion_locked_at` | `DateTime(timezone=True)` nullable | NULL ⇒ not locked |
| `conclusion_locked_by_id` | `UUID` FK `users.id` ON DELETE SET NULL | NULL when not locked |

### `runs` (new columns)

| Column | Type | Notes |
|---|---|---|
| `key_result_label` | `String(120)` nullable | e.g. "Titer", "VCD peak" |
| `key_result_value` | `Numeric(20, 6)` nullable | Numeric — chart and export read directly |
| `key_result_unit` | `String(32)` nullable | Optional unit string |

### Constraints

- `CHECK ((key_result_label IS NULL) = (key_result_value IS NULL))` on `runs` — label and value live or die together; unit may be independently null.

### No new tables

- Conclusion lives on the experiment row.
- Key result lives on the run row.
- Observations are derived from the existing `notes` JSONB on both entities at read time.

### Lifecycle widening

`derive_lifecycle_status` becomes a five-state machine. Helper signature:

```python
def derive_lifecycle_status(
    experiment_status: str,
    live_run_count: int,
    open_run_count: int,
    conclusion_locked: bool,
) -> str:
```

| Returns | When |
|---|---|
| `ARCHIVED` | `experiment_status == ARCHIVED` |
| `DRAFT` | `live_run_count == 0` |
| `IN_PROGRESS` | `open_run_count > 0` |
| `AWAITING_CONCLUSION` | all runs terminal AND `not conclusion_locked` |
| `COMPLETE` | all runs terminal AND `conclusion_locked` |

Existing complete experiments materialize as `AWAITING_CONCLUSION` after the migration — expected behavior, called out in the migration commit message so QA isn't surprised.

### Theme

`experimentStatusClasses` / `experimentStatusLabel` gain `AWAITING_CONCLUSION` → amber pill (`bg-amber-100 text-amber-900 border-amber-300`) with label "Awaiting conclusion".

## Section 2 — API surface

Experiments router mounts at root (`/experiments/...`); runs router at `/runs/...`. No `/science` prefix.

### Existing endpoints, extended

- `PUT /experiments/{id}` — accepts new optional `conclusion: str | None`. Returns 409 if `conclusion_locked_at IS NOT NULL`. Audit log on success.
- `PUT /runs/{id}` — accepts `key_result_label`, `key_result_value`, `key_result_unit`. 422 if exactly one of label/value is provided. Editable for the run's whole life — no lock semantics on the run side.

### New endpoints

- `POST /experiments/{id}/conclusion/lock` — 409 if any run is open (PLANNED/ACTIVE/PAUSED), or conclusion is null/empty, or already locked. Sets `conclusion_locked_at = now()`, `conclusion_locked_by_id = current_user`. Audit log.
- `POST /experiments/{id}/conclusion/unlock` — admin-only. Body `{ "reason": str }` (min 8 chars). Clears the two lock columns. `reason` written to `audit_logs.details`.
- `GET /experiments/{id}/observations` — UNION ALL aggregation over experiment + run notes. Returns flat list sorted by `created_at` desc:
  ```
  { id, source: "experiment"|"run", source_id, run_label?, flag, body, author_name, created_at }
  ```
- `GET /experiments/{id}/export.pdf` — synchronous, `Content-Type: application/pdf`. 30s soft wall-clock guard.

### Response schema additions

- `ExperimentResponse`: + `conclusion`, `conclusion_locked_at`, `conclusion_locked_by_id`, `conclusion_locked_by` (nested user summary). `lifecycle_status` enum widens to include `AWAITING_CONCLUSION`.
- `RunResponse`: + `key_result_label`, `key_result_value` (float on the wire), `key_result_unit`.

### No new read endpoints

- Conditions table and scatter chart compute client-side from `run.graph.nodes[*].data.params` and the runs list.

## Section 3 — Services & computation

### `backend/app/services/experiments/status.py`

Adds `LIFECYCLE_AWAITING_CONCLUSION = "AWAITING_CONCLUSION"`. `derive_lifecycle_status` gains the `conclusion_locked: bool` parameter. `lifecycle_counts_from_runs` is unchanged; callers thread `conclusion_locked_at IS NOT NULL` from the experiment row.

### `backend/app/services/experiments/observations.py` (new)

```python
async def aggregate_observations(
    db: AsyncSession, experiment_id: UUID
) -> list[ObservationItem]:
```

Single SQL statement, UNION ALL over `jsonb_array_elements(e.notes)` filtered to `observation|anomaly` and `jsonb_array_elements(r.notes)` filtered to `anomaly`, joined to `runs` for `run_label`. Sorted desc. Composite id `f"{source}:{source_id}:{note_id}"` for stable client keys.

### `backend/app/services/experiments/pdf_export.py` (new)

Reuses fpdf2 primitives. Extracts the heading / key-value table / paragraph / signature-block helpers from `app.services.batch.batch_record_generator` into `app.services.batch.pdf_primitives` and imports them from both sites. No deeper refactor.

Layout: header → objective + success criteria → conditions (varied params only, server-side port of the frontend algorithm) → key results → conclusion + lock signature (or "Not yet locked — draft" banner) → observations.

### `frontend/src/lib/experiments/conditions.ts` (new)

Pure function:

```ts
type CondCell = { value: unknown; unit?: string };
type CondRow  = { nodeLabel: string; paramKey: string; varied: boolean; perRun: Map<RunId, CondCell> };

export function computeConditions(runs: Run[]): CondRow[];
```

Walks `node.data.params` keyed by `(node.data.label, paramKey)` for `node.type === "unitOp"`. Unit pulled from `node.data.paramSchema.properties[k].unit` when declared. A row is `varied` when the canonicalized set of values has cardinality > 1; canonicalize: numbers stay numeric, strings trimmed, null/undefined collapse.

### Audit logging

`log_audit` invocations at every mutation: conclusion edit (`entity_type="experiment"`), lock, unlock (with `reason` in details), and key_result update (`entity_type="run"`).

## Section 4 — Frontend surfaces

### Route

Only `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte` changes. Two-column layout: left column scrolls, right column (Observations) sticky on `lg:`, stacks below.

### New components — `lib/components/experiment/`

| Component | Purpose |
|---|---|
| `ConditionsTable.svelte` | Phase 4 — varied-params table grouped by step. Internal `showConstants` toggle. Uses `computeConditions`. |
| `KeyResultsTable.svelte` | Phase 5 left — runs sorted by `key_result_value` desc; best run highlighted. |
| `KeyResultsChart.svelte` | Phase 5 right — hand-rolled SVG scatter. X = most-varied numeric param (dropdown override), Y = `key_result_value`. No charting lib. |
| `ConclusionCard.svelte` | Phase 6 — editable / locked / admin-unlock-dialog states. |
| `ObservationsTimeline.svelte` | Phase 7 right rail — flag pills, source links. |
| `ExportSummaryButton.svelte` | Phase 6 — outline button, fetches PDF blob, triggers download. |

`RunKeyResultFields.svelte` (label/value/unit triple) is added to the existing run edit surface; lives in `lib/components/run/`.

### Page state

```ts
let experiment = $state<Experiment | null>(null);
let runs = $state<Run[]>([]);
let observations = $state<ObservationItem[]>([]);
let observationsLoading = $state(true);

const conditions = $derived(runs.length ? computeConditions(runs) : []);
const hasOpenRuns = $derived(runs.some(r => isOpenStatus(r.status)));
const lifecycle = $derived(experiment?.lifecycle_status);
const canAdmin = $derived(currentUser.roles.includes("ADMIN"));
```

Three parallel fetches on mount: experiment, runs, observations. Observations refetched after any note add/delete and after lock/unlock.

### Zod schemas

- `lib/schemas/experiment.ts` — `ExperimentSchema` gains the conclusion + lock fields; `LifecycleStatusEnum` widens.
- `lib/schemas/run.ts` — `RunSchema` gains the key-result triple.
- `lib/schemas/observation.ts` (new) — `ObservationItemSchema`, `ObservationsResponseSchema`.

### Non-features

- Conditions "Show constants" toggle is local state only (no URL param).
- Chart axis picker persists to `sessionStorage` keyed by experiment id; not server-side.
- No realtime push — observations refresh on user action.

## Section 5 — Testing & migration

### Alembic migration

Single revision adding the six new columns and the runs check constraint. No data migration. Downgrade drops the constraint then columns. Migration commit message explicitly calls out that existing complete experiments will display as `AWAITING_CONCLUSION` until someone locks.

### Indexes

None added. Lock columns are read per row, never filtered. Key-result columns are read alongside the run row. Observation aggregation is bounded by `experiment_id` which is already indexed on `runs`. Revisit if export reports get slow.

### Backend tests (TDD)

- `tests/unit/services/experiments/test_status_phase_4_7.py` — all five lifecycle states; AWAITING_CONCLUSION returns after admin unlock.
- `tests/unit/services/experiments/test_observations.py` — experiment-flagged `observation` + `anomaly`; run-flagged `anomaly` only; desc sort; empty experiment → empty list; stable composite id.
- `tests/integration/api/test_experiments_phase_4_7.py` — PUT conclusion happy / 409 locked; lock 409s (open run, empty conclusion, already locked); lock happy path; unlock 403 non-admin / 200 admin / 422 short reason; audit log captures reason; observations endpoint; PDF endpoint returns `application/pdf` with non-empty body and lock signature when locked.
- `tests/integration/api/test_runs_phase_4_7.py` — PUT runs accepts triple; 422 unpaired; DB constraint rejects direct violations.

### Frontend tests (Vitest)

- `tests/lib/experiments/conditions.test.ts` — identical runs → no varied rows; one differing param → one varied row; missing node in some runs → "—" cell; unit pulled from paramSchema.
- `tests/lib/components/experiment/ConclusionCard.test.ts` — editable state disables Lock with reason tooltip when body empty or `hasOpenRuns`; locked state shows signature + admin unlock; unlock dialog blocks submit until reason ≥ 8 chars.
- `tests/lib/components/experiment/KeyResultsChart.test.ts` — one circle per run with `key_result_value`; best run gets accent class; axis dropdown reflects varied numeric params.

### E2E (Playwright)

One golden-path spec at `tests/e2e/experiments-phase-4-7.spec.ts`: open experiment with three finished runs holding key_results → assert "Awaiting conclusion" pill → conditions / results / chart render → type conclusion → Lock → status flips to "Complete" with signature → Export summary triggers a `.pdf` download.

### Coverage gates

≥80% per CLAUDE.md. New service modules (status widening, observations, pdf_export) target ≥90%.

### Rollout

No feature flag. Phases 4-7 are additive: nullable columns plus a derivation function that already reads NULL as "not locked". Ship migration → backend → frontend in sequence so production never sees a half-state.
