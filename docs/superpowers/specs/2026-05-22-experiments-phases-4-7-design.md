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
| `conclusion` | `Text` nullable | Free-form markdown-flavored prose. Pydantic input bounded `max_length=65536` |
| `conclusion_locked_at` | `DateTime(timezone=True)` nullable | NULL ⇒ not locked |
| `conclusion_locked_by_id` | `UUID` FK `users.id` ON DELETE SET NULL | NULL when not locked |
| `conclusion_locked_by_name` | `String(255)` nullable | Snapshotted display name at lock time — survives user deletion for GxP signature durability |

### `runs` (new columns)

| Column | Type | Notes |
|---|---|---|
| `key_result_label` | `String(120)` nullable | e.g. "Titer", "VCD peak" |
| `key_result_value` | `Numeric(20, 6)` nullable | Numeric. Pydantic rejects NaN/Inf; magnitude capped to fit `Numeric(14,6)` integer digits |
| `key_result_unit` | `String(32)` nullable | Optional unit string |

### Constraints

- `CHECK ((key_result_label IS NULL) = (key_result_value IS NULL))` on `runs` — label and value live or die together; unit may be independently null.
- Migration adds the constraint `NOT VALID` then validates in an `autocommit_block()` so the historical scan runs without `ShareRowExclusiveLock`.

### No new tables

- Conclusion lives on the experiment row.
- Key result lives on the run row.
- Observations are derived from the existing `notes` JSONB on both entities at read time.

### Lifecycle widening

`derive_lifecycle_status` becomes a five-state machine. **Backwards-compatible signature** — `conclusion_locked` defaults to `False`:

```python
def derive_lifecycle_status(
    experiment_status: str,
    live_run_count: int,
    open_run_count: int,
    conclusion_locked: bool = False,
) -> str:
```

| Returns | When |
|---|---|
| `ARCHIVED` | `experiment_status == ARCHIVED` |
| `DRAFT` | `live_run_count == 0` |
| `IN_PROGRESS` | `open_run_count > 0` |
| `AWAITING_CONCLUSION` | all runs terminal AND `not conclusion_locked` |
| `COMPLETE` | all runs terminal AND `conclusion_locked` |

The default is **`False`** rather than `True` to keep the helper safe for callers that haven't been updated yet (they'll show `AWAITING_CONCLUSION` instead of `COMPLETE`, which is the more conservative direction). Every call site in `backend/app/api/endpoints/experiments.py` (lines 162, 203, 251, 363, 409, 468) and the existing test file `backend/tests/unit/services/test_experiment_status.py` must be updated in the same diff to thread the real value.

**SQL implication:** the two list aggregate queries (`list_experiments` at `experiments.py:182` and `list_all_experiments` at `experiments.py:255`) currently don't select `conclusion_locked_at`. Both must be updated to project the column on the experiment join so the boolean threads correctly. Without this, locked-complete experiments show as `AWAITING_CONCLUSION` in the list views even though they're actually complete.

### Migration data backfill

To prevent silently demoting customer-visible complete experiments to `AWAITING_CONCLUSION`, the migration includes a one-shot data backfill:

```sql
UPDATE experiments e
SET conclusion = '[Auto-locked at migration]',
    conclusion_locked_at = NOW(),
    conclusion_locked_by_id = NULL,
    conclusion_locked_by_name = 'system'
WHERE NOT EXISTS (
    SELECT 1 FROM runs r
    WHERE r.experiment_id = e.id
      AND r.status IN ('PLANNED', 'ACTIVE', 'EDITED')
)
AND EXISTS (
    SELECT 1 FROM runs r WHERE r.experiment_id = e.id
);
```

(Only experiments that already have runs AND no open runs — i.e. ones a customer perceives as "complete" today.) Migration commit message documents the backfill explicitly so QA isn't surprised.

### Theme

`experimentStatusClasses` / `experimentStatusLabel` in `frontend/src/lib/components/project/projectUtils.ts` (lines 163, 177) gain `AWAITING_CONCLUSION` → amber pill (`bg-amber-100 text-amber-900 border-amber-300`) with label "Awaiting conclusion". The pill on both the detail page and the index page carries a tooltip: "Status is derived from runs and the conclusion lock — all runs complete, conclusion not locked yet."

## Section 2 — API surface

Experiments router mounts at root (`/experiments/...`); runs router at `/runs/...`. No `/science` prefix.

### Existing endpoints, extended

- `PUT /experiments/{id}` —
  - accepts new optional `conclusion: str | None` (added to `ExperimentUpdate` Pydantic model + to the field whitelist tuple at `experiments.py:437`)
  - **While `conclusion_locked_at IS NOT NULL`, returns 409 on ANY field mutation** (name, description, content, objective, success_criteria, status, notes, conclusion). Admin must unlock first. Single guard at the top of the handler.
  - Audit log on success.

- `PUT /runs/{id}` — accepts `key_result_label`, `key_result_value`, `key_result_unit`. 422 if exactly one of label/value is provided. `key_result_value` Pydantic validator rejects NaN/Inf and bounds magnitude to ≤ 14 integer digits. Editable for the run's whole life — no lock semantics on the run side.

### New endpoints

- `POST /experiments/{id}/conclusion/lock` —

  Atomic single-statement guard against TOCTOU:

  ```sql
  UPDATE experiments
  SET conclusion_locked_at = NOW(),
      conclusion_locked_by_id = :user_id,
      conclusion_locked_by_name = :user_name
  WHERE id = :exp_id
    AND conclusion_locked_at IS NULL
    AND conclusion IS NOT NULL
    AND length(trim(conclusion)) > 0
    AND NOT EXISTS (
      SELECT 1 FROM runs
      WHERE experiment_id = :exp_id
        AND status IN ('PLANNED', 'ACTIVE', 'EDITED')
    )
  RETURNING id, conclusion_locked_at, conclusion_locked_by_id, conclusion_locked_by_name
  ```

  Zero rows returned → 409 with structured `{code, message}` so the frontend can surface the precise reason (separate query to disambiguate: already-locked vs empty-conclusion vs open-runs). Audit log: `entity_type="experiment"`, `action="conclusion.lock"`, `changes={"conclusion_snapshot": <text>}`.

  **Open-run statuses are `PLANNED`, `ACTIVE`, `EDITED`** — these are the three non-terminal members of `RunStatus`. `PAUSED` does not exist in the enum.

- `POST /experiments/{id}/conclusion/unlock` —

  Permission: `require_permission(ObjectType.EXPERIMENT, "experiment_id", PermissionLevel.ADMIN)` — matches the existing project-level admin pattern. Frontend `canAdmin` derives from the same check (via the user's organization permissions table); the unlock UI element is only rendered when `canAdmin === true`.

  Body: `{ "reason": str }` (min 8 chars, max 1000).

  Atomic UPDATE:
  ```sql
  UPDATE experiments
  SET conclusion_locked_at = NULL,
      conclusion_locked_by_id = NULL,
      conclusion_locked_by_name = NULL
  WHERE id = :exp_id
    AND conclusion_locked_at IS NOT NULL
  RETURNING id
  ```
  Zero rows → 409 (already unlocked). Audit log: `entity_type="experiment"`, `action="conclusion.unlock"`, `changes={"reason": <reason>, "conclusion_before": <text>}`.

- `GET /experiments/{id}/observations` — UNION ALL aggregation over experiment + run notes. Filters out malformed rows (`note->>'flag' IS NULL OR note->>'created_at' IS NULL`). Capped at `LIMIT 500`. Returns:
  ```
  { items: [{ id, source: "experiment"|"run", source_id, run_label?, flag, body, author_name, created_at }],
    truncated: boolean }
  ```
  When `truncated === true`, frontend banner reads "Showing 500 most recent observations." Response carries `Cache-Control: no-store`.

- `GET /experiments/{id}/export.pdf` — `Content-Type: application/pdf`. Generation pattern:
  ```python
  try:
      content = await asyncio.wait_for(
          asyncio.to_thread(generate_experiment_pdf, experiment, runs, observations),
          timeout=30.0,
      )
  except asyncio.TimeoutError:
      raise HTTPException(503, {"code": "EXPORT_TIMEOUT", "detail": "..."})
  ```
  Audit log: `entity_type="experiment"`, `action="export.pdf"` (so exports are recorded for GxP).

### Response schema additions

- `ExperimentResponse`: + `conclusion`, `conclusion_locked_at`, `conclusion_locked_by_id`, `conclusion_locked_by_name`, `conclusion_locked_by` (nested user summary; nullable when the user has been deleted but the name snapshot remains). `lifecycle_status` enum widens to include `AWAITING_CONCLUSION`.
- `RunResponse`: + `key_result_label`, `key_result_value` (float on the wire), `key_result_unit`.

### No new read endpoints

- Conditions table and scatter chart compute client-side from `run.graph.nodes[*].data.params` and the runs list.

## Section 3 — Services & computation

### `backend/app/services/experiments/status.py`

Adds `LIFECYCLE_AWAITING_CONCLUSION = "AWAITING_CONCLUSION"`. `derive_lifecycle_status` gains `conclusion_locked: bool = False` (defaulted — see Section 1 rationale). `lifecycle_counts_from_runs` is unchanged; callers thread `conclusion_locked_at IS NOT NULL` from the experiment row alongside the existing count tuple.

### `backend/app/services/experiments/observations.py` (new)

```python
async def aggregate_observations(
    db: AsyncSession, experiment_id: UUID, limit: int = 500
) -> ObservationsResponse:
```

Single SQL statement, UNION ALL over `jsonb_array_elements(e.notes)` filtered to `observation|anomaly` (with `note->>'flag' IS NOT NULL AND note->>'created_at' IS NOT NULL`) and `jsonb_array_elements(r.notes)` filtered to `anomaly`, joined to `runs` for `run_label`. Sorted desc by `(note->>'created_at')::timestamptz`. Capped at `limit + 1` rows to detect truncation. Composite id `f"{source}:{source_id}:{note_id}"` for stable client keys.

### `backend/app/services/experiments/pdf_export.py` (new)

**Imports primitives directly from `app.services.documents.pdf_base`** — no new shared module. `batch_record_generator.py` already imports from `pdf_base`; reusing the same source avoids creating a third home for the same symbols. No touching `batch_record_generator.py`.

Layout: header → objective + success criteria → conditions (varied params only) → key results → conclusion + lock signature (`Locked by {conclusion_locked_by_name} on {conclusion_locked_at}`) → observations.

The PDF generation function is **synchronous** (fpdf2 is CPU-bound); the endpoint wraps it in `asyncio.to_thread` + `asyncio.wait_for(30.0)`.

### Conditions parity

`computeConditions` exists in two places: `frontend/src/lib/experiments/conditions.ts` (interactive table + chart) and a Python port in `pdf_export.py` (server-side render). Both implementations consume a shared fixture at `backend/tests/fixtures/conditions_parity.json` (also referenced from `frontend/tests/fixtures/`); pytest and Vitest assert against the same expected output to lock the contract.

### `frontend/src/lib/experiments/conditions.ts` (new)

Pure function:

```ts
type CondCell = { value: unknown; unit?: string };
type CondRow  = { nodeLabel: string; paramKey: string; varied: boolean; perRun: Map<RunId, CondCell> };

export function computeConditions(runs: Run[]): CondRow[];
```

Walks `node.data.params` keyed by `(node.data.label, paramKey)` for `node.type === "unitOp"`. Unit pulled from `node.data.paramSchema.properties[k].unit` when declared. A row is `varied` when the canonicalized set of values has cardinality > 1; canonicalize: numbers stay numeric, strings trimmed, null/undefined collapse.

### Audit logging

`log_audit` invocations at every mutation: conclusion edit (`entity_type="experiment"`, action `conclusion.edit`), lock (`conclusion.lock` — `changes={"conclusion_snapshot": text}`), unlock (`conclusion.unlock` — `changes={"reason": ..., "conclusion_before": text}`), key_result update (`entity_type="run"`, action `key_result.set`), PDF export (`action="export.pdf"`).

## Section 4 — Frontend surfaces

### Route

Only `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte` changes. Two-column layout: left column scrolls, right column (Observations) sticky on `lg:`, stacks below.

### Index page update

`frontend/src/routes/[org]/experiments/+page.svelte`:
- Filter tabs array (line 44) gains `"Awaiting conclusion"`.
- Filter predicate (lines 82-84) handles the new tab.
- Stats counter (lines 95-97) gains an `awaitingConclusion` field rendered as a fourth stat card.
- Pill on each row continues using `experimentStatusLabel`, which now returns "Awaiting conclusion" for the new state with the tooltip.

### New components — `lib/components/experiment/`

| Component | Purpose |
|---|---|
| `ConditionsTable.svelte` | Phase 4 — varied-params table grouped by step. Internal `showConstants` toggle. Uses `computeConditions`. First column `position: sticky; left: 0; z-index: 2; background: var(--card)` for horizontal-scroll readability with many runs. |
| `KeyResultsTable.svelte` | Phase 5 left — runs sorted by `key_result_value` desc; best run highlighted with an in-row caption "best (+N% vs baseline RUN-X)". |
| `KeyResultsChart.svelte` | Phase 5 right — hand-rolled SVG scatter. X = most-varied numeric param (dropdown override), Y = `key_result_value`. Each `<circle>` carries a `<title>` for tap-to-identify; a tap handler shows a labelled run tag overlay. In-chart caption: "Trend line is a smoothing hint, not a fit." No charting lib. |
| `ConclusionCard.svelte` | Phase 6 — editable / locked / admin-unlock-dialog states. **Primary Lock CTA placed adjacent to the amber "Completion gate" warning** at the top of the card; a secondary footer Lock button is also rendered for long conclusions. **Admin unlock button is conditionally rendered — only when `canAdmin === true`**. |
| `ObservationsTimeline.svelte` | Phase 7 right rail — flag pills, source links. Renders "Showing 500 most recent observations" banner when `truncated`. |
| `ExportSummaryButton.svelte` | Phase 6 — outline button **placed in the Conclusion card footer** (natural next action after lock), not in the page-header CTA row. Uses the existing `downloadBlob(endpoint, filename)` helper from `lib/api.ts`. |

`RunKeyResultFields.svelte` (label/value/unit triple) is added to the existing run edit surface; lives in `lib/components/run/` (confirmed no overlap with the existing `RunResultsSummary.svelte`).

### Empty states

| Surface | Copy when empty |
|---|---|
| Conditions card | "No runs yet — add a run to populate the design matrix." |
| Key Results table | "Enter a key result on each run's detail page." (with link affordance) |
| Key Results chart | (hidden when no runs have `key_result_value`) |
| Observations rail | "No observations or anomalies flagged yet." |

All rendered as the existing `.empty-hint` dashed-border muted block.

### Page state

```ts
let experiment = $state<Experiment | null>(null);
let runs = $state<Run[]>([]);
let observations = $state<ObservationItem[]>([]);
let observationsTruncated = $state(false);
let observationsLoading = $state(true);

const conditions = $derived(runs.length ? computeConditions(runs) : []);
const hasOpenRuns = $derived(runs.some(r => isOpenStatus(r.status)));
const lifecycle = $derived(experiment?.lifecycle_status);
const canAdmin = $derived(checkExperimentAdmin(currentUser, experiment));
```

Three parallel fetches on mount: experiment, runs, observations. Observations refetched after: any note add/delete, lock/unlock, and `visibilitychange` event flipping tab back to visible (cross-tab refresh hole).

### Zod schemas

- `lib/schemas/experiments.ts` — `ExperimentSchema` gains the conclusion + lock fields, **all `.nullable().optional()`** so old replicas mid-rolling-deploy don't break the parser. `LifecycleStatusEnum` widens to include `"AWAITING_CONCLUSION"`.
- `lib/schemas/runs.ts` — `RunSchema` gains the key-result triple, all `.nullable().optional()`.
- `lib/schemas/observation.ts` (new) — `ObservationItemSchema`, `ObservationsResponseSchema`.

### Non-features

- Conditions "Show constants" toggle is local state only (no URL param).
- Chart axis picker persists to `sessionStorage` keyed by experiment id; not server-side.
- No realtime push — observations refresh on user action and on `visibilitychange`.

## Section 5 — Testing & migration

### Alembic migration

Single revision adding the seven new columns (4 on `experiments`, 3 on `runs`), the runs CHECK constraint (added `NOT VALID`, then `VALIDATE CONSTRAINT` in `autocommit_block`), and the data backfill UPDATE (Section 1). Downgrade drops the constraint then columns; backfilled rows remain locked (the columns vanish, but the application no longer reads them — acceptable since downgrade is a recovery path, not a runtime state).

### Indexes

None added. Lock columns are read per row, never filtered. Key-result columns are read alongside the run row. Observation aggregation is bounded by `experiment_id` on `runs`, already covered by the existing `ix_runs_experiment_created` index. Revisit if export reports get slow.

### Backend tests (TDD)

- `tests/unit/services/experiments/test_status_phase_4_7.py` — all five lifecycle states; AWAITING_CONCLUSION returns after admin unlock.
- **`tests/unit/services/test_experiment_status.py` (existing) updated** — every `derive_lifecycle_status` call gets the new arg (default `False` keeps tests passing where lock state is irrelevant; explicit `True` added where it isn't).
- `tests/unit/services/experiments/test_observations.py` — experiment-flagged `observation` + `anomaly`; run-flagged `anomaly` only; desc sort; empty experiment → empty list; stable composite id; **malformed JSONB notes filtered (missing flag, missing created_at)**; truncation at LIMIT 500.
- `tests/unit/services/experiments/test_conditions_parity.py` — Python port of `computeConditions` consumes `tests/fixtures/conditions_parity.json` and matches expected output.
- `tests/integration/api/test_experiments_phase_4_7.py` —
  - PUT conclusion happy path / 409 when locked
  - **PUT objective/description/notes 409 when locked** (lock guard freezes all fields)
  - Lock 409 cases: open run, empty conclusion, already locked (each with structured `code`)
  - Lock happy path → atomic UPDATE, audit log captures conclusion snapshot
  - **Lock TOCTOU test**: simultaneously transition a run to ACTIVE and attempt lock; assert one of them 409s (no inconsistent state)
  - Unlock 403 non-admin / 200 admin / 422 short reason; audit log captures reason + `conclusion_before`
  - Concurrent unlock test: second 409s
  - Observations endpoint: cap at 500, `truncated` flag, `Cache-Control: no-store` header
  - PDF endpoint: `application/pdf`, lock signature when locked, 503 `EXPORT_TIMEOUT` on simulated slow render
  - PDF endpoint writes an `export.pdf` audit log entry
- `tests/integration/api/test_runs_phase_4_7.py` — PUT runs accepts triple; 422 unpaired; 422 NaN/Inf; 422 magnitude overflow; DB constraint rejects direct violations.

### Frontend tests (Vitest)

- `tests/lib/experiments/conditions.test.ts` — consumes `frontend/tests/fixtures/conditions_parity.json` (same fixture as backend); identical runs → no varied rows; one differing param → one varied row; missing node in some runs → "—" cell; unit pulled from paramSchema.
- `tests/lib/components/experiment/ConclusionCard.test.ts` — editable state disables Lock with reason tooltip when body empty or `hasOpenRuns`; locked state shows signature with `conclusion_locked_by_name`; **admin unlock button absent when `canAdmin === false`**; unlock dialog blocks submit until reason ≥ 8 chars.
- `tests/lib/components/experiment/KeyResultsChart.test.ts` — one circle per run with `key_result_value`; best run gets accent class; each circle has a `<title>` for tap-to-identify; axis dropdown reflects varied numeric params.
- `tests/lib/components/experiment/ConditionsTable.test.ts` — first column has `position: sticky` style; "Show constants" toggle adds non-varied rows.

### E2E (Playwright)

One golden-path spec at `tests/e2e/experiments-phase-4-7.spec.ts`: open experiment with three finished runs holding key_results → assert "Awaiting conclusion" pill → conditions / results / chart render → type conclusion → Lock → status flips to "Complete" with signature line including the user's name → Export summary triggers a `.pdf` download.

### Coverage gates

≥80% per CLAUDE.md. New service modules (status widening, observations, pdf_export) target ≥90%.

### Rollout

No feature flag. Phases 4-7 are additive: nullable columns plus a derivation function with a backwards-compatible default. Migration's data backfill prevents customer-visible demotion. Zod schemas use `.nullable().optional()` on new fields so the frontend stays compatible with old backend replicas during rolling deploy. Ship migration → backend → frontend in sequence so production never sees a half-state for more than a deploy window.

### Follow-up TECH_DEBT tickets (not in scope for this slice)

- Unlock-without-relock detection: runbook entry plus alert query against `audit_logs` for `conclusion.unlock` with no subsequent `conclusion.lock` on the same `entity_id` within N hours.
- Per-org rate limit on `GET /experiments/{id}/export.pdf` via `RateLimitService` (10/min/org).
- Async PDF export path (`BackgroundJob` + `202 Accepted` + email delivery) if export concurrency becomes a problem.
