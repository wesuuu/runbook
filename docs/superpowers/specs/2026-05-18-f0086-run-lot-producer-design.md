# F-0086 · Designate Run as Lot Producer — Design

**Status:** approved
**Date:** 2026-05-18
**ClickUp:** [F-0086](https://app.clickup.com/t/86e1eexx6)
**Mockup:** [`mockups/f0086-lot-producer.html`](mockups/f0086-lot-producer.html)

## Problem

`Run.lot_number` and `Run.batch_number` exist as free-text optional strings (added in QA-0008) but a run is never *explicitly* designated as producing a lot. The Runs list cannot filter to lot-producing runs, and there is no auto-generation helper for lot numbers.

This feature introduces a first-class "this run produces a lot" designation on `Run`, an auto-generation endpoint, a soft-duplicate check, and a Runs-list filter.

## Decisions (resolved during brainstorming)

| Question | Decision |
|---|---|
| Designation field | Explicit `produces_lot: bool` column on `Run`, not derived from `lot_number IS NOT NULL`. |
| Auto-generate pattern | Hardcoded default `LOT-{seq}` with `{seq}` zero-padded to 6 digits (e.g. `LOT-000042`). Monotonic per-org. No date encoding. |
| Uniqueness | Non-unique. Indexed on `runs.lot_number` for lookup. Org-scoping done in the query (JOIN through `projects`). Soft warning surfaced via a check endpoint; never blocks save. |
| Post-creation edit | Allowed on any run status. Captured via existing `log_audit()`. |
| Run-list filter | Backend query param `?produces_lot=true`, applied in SQL. |
| Template engine gating | In scope. `produces_lot` is exposed in the Jinja context; the batch-record template's lot/batch row is wrapped in `{%tr if produces_lot %} … {%tr endif %}` so the row disappears entirely when the run is not a lot producer. |
| Org-settings table | Out of scope. Defer until a second per-org config knob lands. |

## Data model

Add one column to `runs`:

```python
# backend/app/models/science.py
produces_lot: Mapped[bool] = mapped_column(
    Boolean, default=False, server_default="false", nullable=False, index=True
)
```

Migration (Alembic): new boolean column with `server_default="false"`; index on `produces_lot`; non-unique index on `lot_number`. No backfill — existing rows default to `false`.

Run already joins to Project → Organization, so org-scoping happens in queries via JOIN. We do not denormalize `organization_id` onto `Run`.

## API

| Endpoint | Change |
|---|---|
| `POST /science/runs` | Accept `produces_lot`. Reject (422) if `produces_lot=true` and `lot_number` is empty/`None`. |
| `PUT /science/runs/{id}` | Same validation. Existing `log_audit()` already captures field-level diffs. |
| `GET /science/projects/{id}/runs` | New optional `?produces_lot=true\|false` query param; filters in SQL. |
| `POST /science/runs/suggest-lot-number` | New. Body: `{project_id: UUID}`. Returns `{lot_number: "LOT-000042"}`. Computes `max(numeric_suffix)+1` over runs in the same org with `lot_number ~ '^LOT-[0-9]{6}$'`, zero-padded to 6. |
| `GET /science/runs/check-lot-number` | New. Query: `?project_id=X&lot_number=Y`. Returns `{exists: bool, count: int}` scoped to the project's org. Drives the soft duplicate warning. |

### Schema changes

`backend/app/schemas/science.py`:
- `RunCreate.produces_lot: bool = False`
- `RunUpdate.produces_lot: Optional[bool] = None`
- `RunResponse.produces_lot: bool = False`

## Frontend

Mockup: [`mockups/f0086-lot-producer.html`](mockups/f0086-lot-producer.html) — three frames covering the views below.

### Switch primitive

No `Switch` exists in `$lib/components/ui/`. Implementation adds `$lib/components/ui/switch/switch.svelte` as a thin wrapper over `bits-ui` `Switch.Root`, following the existing shadcn-svelte primitive pattern used by Button/Badge/Card. Theme tokens (`bg-primary`, `bg-input`) from `app.css`.

### View 1 — Run Creator step (`RunCreatorNameStep.svelte`)

- Replace the always-on lot input with a Card containing the `produces_lot` Switch.
- When on: reveal the lot input, an Auto-generate button (`POST /suggest-lot-number`), and an inline amber duplicate-warning slot (style matches `IndexingStatusBanner.svelte` — `border-l-4 border-l-amber-400 bg-amber-50`).
- On blur of the lot input, call `GET /check-lot-number`; if `exists`, render the warning. Never blocks the wizard.
- When off: input is hidden and any stale value is cleared from local state before submission.
- Batch input remains as today.
- Props expand: `producesLot: boolean` added to `onChange` payload.

### View 2 — Project Runs tab (`RunsTab.svelte`)

- Toolbar gains a filter chip "Lot producer only" beside the search input, using the existing primary-soft badge style with a × clear affordance.
- Chip state is held in component-local Svelte 5 state and wired through the parent's run-loader.
- When active, the table renders a new `Lot #` column (mono font for readability), positioned between Name and Experiment.
- API call adds `?produces_lot=true` when the chip is active. Server filters in SQL.
- Clearing the chip removes the column and reloads unfiltered.

### View 3 — Run Detail inline editor (`/routes/runs/[id]/+page.svelte`)

- New `Lot output` Card on the right column (beside attachments/notes).
- Visible in any run status. Contains the Switch, lot input, Auto-generate button, and per-card Save/Discard buttons.
- Save dispatches `PUT /science/runs/{id}` with `{produces_lot, lot_number}`. Existing `log_audit()` captures the diff; the existing run history view surfaces it (we are not adding a separate audit card despite the mockup illustrating one — that section in the mockup is decorative).

### Schema (`frontend/src/lib/schemas/runs.ts`)

- `RunSchema`: add `produces_lot: z.boolean().default(false)`.
- `RunCreatePayloadSchema`: add `produces_lot: z.boolean().optional()`.

## Batch record template

The batch record template (`backend/app/services/documents/templates/batch_record_default.docx` and its companion in `backend/uploads/system/document_templates/batch_record_default.docx`) currently has a "Batch / Lot Number" row, but the value cell is incorrectly bound to `{{ run_name }}` — fix to bind to the run's actual `lot_number` (with `batch_number` displayed alongside or below as appropriate).

Wrap the table row in docxtpl row-scope conditionals so the row is removed cleanly when the run does not produce a lot:

```
{%tr if produces_lot %}
| Lot Number | {{ lot_number }} |
{%tr endif %}
```

Backend additions to support this:

- `backend/app/services/protocols/template_engine.py`:
  - Add `"produces_lot"` to `KNOWN_VARIABLES`.
  - Pass `produces_lot` (boolean, defaults to `False`) into the rendered Jinja context alongside the existing `lot_number` / `batch_number` keys.
- No code change is needed if a run that does not produce a lot still has a leftover `lot_number` value — the row simply hides; nothing renders. (We rely on `produces_lot` rather than `bool(lot_number)` so an explicit toggle wins over stale strings.)

Two `.docx` files are touched (the system template and the seed in `uploads/`); both must be edited in lockstep so re-seeding does not regress the change.

## Audit / GxP

Every mutation of `produces_lot` and `lot_number` flows through the existing `PUT /science/runs/{id}` handler which already calls `log_audit(action="UPDATE", changes=...)`. No new audit infrastructure.

## Tests

### Backend (`backend/tests/unit/`)

`test_run_produces_lot.py`:
- `produces_lot=true` without `lot_number` → 422 on POST.
- `produces_lot=true` with `lot_number` → 201; row persisted with both.
- PUT toggling `produces_lot` records the diff via `log_audit`.
- `POST /suggest-lot-number` returns `LOT-000001` on empty org; increments to `LOT-000002` after one lot-producing run; ignores non-matching custom values (e.g. `PILOT-A7`) when computing max.
- `GET /check-lot-number` returns `exists=true` within same org; returns `exists=false` for an identical value in a different org.
- `GET /projects/{id}/runs?produces_lot=true` returns only lot-producing runs.

`test_template_engine_produces_lot.py`:
- `build_render_context(...)` for a lot-producing run exposes `produces_lot=True` and the run's `lot_number`.
- Same call for a non-producer exposes `produces_lot=False` (the docx template's `{%tr if produces_lot %}` block is responsible for hiding the row; the engine just hands over the boolean).

### Frontend (`frontend/src/lib/components/`)

`run/RunCreatorNameStep.test.ts`:
- Switch toggle shows/hides the lot input.
- Clicking Auto-generate calls the API and populates the field.
- When the check endpoint returns `exists=true`, the amber warning renders; clears when value changes.

`project/RunsTab.test.ts`:
- Activating the chip triggers a fetch with `?produces_lot=true`.
- `Lot #` column appears only when the filter is active.

## Out of scope

- `OrganizationSettings` table / per-org pattern configuration.
- Strict uniqueness constraint on `lot_number`.
- Batch-number-producer designation (this feature concerns lots only).

## Files touched

```
backend/app/models/science.py
backend/app/schemas/science.py
backend/app/api/endpoints/runs.py
backend/app/services/protocols/template_engine.py
backend/app/services/documents/templates/batch_record_default.docx
backend/uploads/system/document_templates/batch_record_default.docx
backend/alembic/versions/<new>_add_run_produces_lot.py
backend/tests/unit/test_run_produces_lot.py

frontend/src/lib/components/ui/switch/         (new primitive)
frontend/src/lib/components/run/RunCreatorNameStep.svelte
frontend/src/lib/components/run/RunCreatorNameStep.test.ts
frontend/src/lib/components/project/RunsTab.svelte
frontend/src/lib/components/project/RunsTab.test.ts
frontend/src/lib/schemas/runs.ts
frontend/src/routes/runs/[id]/+page.svelte
```
