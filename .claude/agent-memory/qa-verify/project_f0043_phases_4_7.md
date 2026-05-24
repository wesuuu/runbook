---
name: f0043-phases-4-7-qa
description: QA verification findings for F-0043 Experiments Redesign Phases 4-7 (Conditions, Results, Export, Observations Timeline)
metadata:
  type: project
---

# F-0043 Experiments Phases 4-7 QA Findings

Feature: Conditions table, KeyResultsChart, ConclusionCard with lock/unlock, PDF export, ObservationsTimeline.

## Worktree Setup
- Frontend port 5253, backend port 8080
- Seeded experiment: ID `50000000-0043-0000-0000-000000000001`, slug `phases-4-7-seed`
- Project: `mab-production-v2`, Org: `bioprocess-inc`
- 3 pre-seeded COMPLETED runs with key_result_value set (4.0, 4.5, 5.0 g/L Titer)

## Bugs Fixed

### 1. PDF export 500 (FAIL)
`_observations` called `pdf.multi_cell(0, 4, text)` after a prior multi_cell that left x at the right margin. fpdf2 `multi_cell(w=0, ...)` uses current x as start — if x is at right margin, available width = 0. Fix: add `new_x="LMARGIN", new_y="NEXT"` to all multi_cell calls in `_objective`, `_conditions`, `_conclusion`, `_observations`.
File: `backend/app/services/experiments/pdf_export.py`

### 2. Runs lost after PUT /experiments (FAIL)
PUT /experiments/{id} (save objective, save conclusion) and POST conclusion/lock|unlock all return `runs=[]` for performance. The page was doing `experiment = updated` which wiped the runs array, blanking Conditions table, KeyResultsChart, KeyResultsTable. Fix: `experiment = { ...updated, runs: experiment?.runs ?? [] }` in all four update paths (saveObjective, saveConclusion, lockConclusion, unlockConclusion).
File: `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`

## Polish Fixed

### 3. ObservationsTimeline absolute timestamps (POLISH)
Used `toLocaleString()` instead of `formatDate()`. Fixed to use relative timestamps (via `formatDate`) with absolute timestamp on hover (`title=` attribute).
File: `frontend/src/lib/components/experiment/ObservationsTimeline.svelte`

### 4. KeyResultsTable missing header styling and overflow wrapper (POLISH)
Table used `<table class="w-full">` with unstyled `th` elements. Fixed: added `overflow-x-auto` wrapper and `.kr-table th` CSS with small-caps, muted-foreground styling to match ConditionsTable.
File: `frontend/src/lib/components/experiment/KeyResultsTable.svelte`

### 5. CORS missing port 5253 (SETUP)
Added `http://localhost:5253` to allowed origins in backend/app/main.py.

## Design Discrepancy (not fixed)
Spec mentions "Tabs: Runs / Conditions / Notes" with URL `?tab=conditions`, but implementation renders all sections inline in a single scrollable page. This is a valid design pivot for tablet-first — not a bug.

## API Patterns for Future QA
- Lock guard: `PUT /runs/{id}` returns 409 with `{"code":"EXPERIMENT_LOCKED"}` when parent experiment is locked
- Lock endpoint: `POST /experiments/{id}/conclusion/lock` — requires non-empty conclusion, all runs non-open, at least 1 COMPLETED
- Unlock: admin-only via `POST /experiments/{id}/conclusion/unlock` with `{reason: string}` (>= 8 chars enforced in UI, not backend)
- AssignToExperimentModal filters locked experiments via `e.conclusion_locked_at == null` (client-side)
- lifecycle_status: COMPLETE after lock, AWAITING_CONCLUSION after unlock
- Observations: `GET /experiments/{id}/observations` — UNION of experiment notes (flag=observation|anomaly) + run notes (flag=anomaly only)

## Pre-existing Issues (not fixed)
- Nav overflow at 768px viewport — global nav has too many items, pre-existing
- viewer@bioprocess.com needs ToS acceptance before testing viewer role
EOF