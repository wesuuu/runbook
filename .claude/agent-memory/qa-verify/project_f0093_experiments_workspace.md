---
name: f0093-experiments-workspace
description: QA findings for F-0093 Experiments Redesign (Phases 1-3) — Investigations workspace, org-wide index, lifecycle status rollup
metadata:
  type: project
---

F-0093 Phases 1-3 QA completed on 2026-05-23. One blocker fixed; otherwise GO.

## Fixed Bug
`ExperimentSchema` in `frontend/src/lib/schemas/experiments.ts` used `z.string().uuid()` which rejects dev seed UUIDs (version nibble `0`, e.g. `40000000-0000-0000-0000-000000000001`). Changed to `uuidString()` from `./common` throughout. Also added missing fields: `lifecycle_status`, `objective`, `success_criteria`, `project_name`, `run_summaries`, `owner`. Without this fix, `ExperimentCreateModal` displayed a Zod validation error after POST and `onCreated` callback never fired, blocking navigation to the detail page.

**Why:** The `common.ts` file has a `uuidString()` helper specifically for seeded UUIDs — new schemas must use it. The strict `.uuid()` rejects seeded UUIDs with version nibble outside [1-8].

## Architecture Notes
- Org experiments index: `frontend/src/routes/[org]/experiments/+page.svelte` — uses local `ExperimentRow` interface, NOT `ExperimentSchema` (intentional for now; schema TODO comment left in code)
- Experiment detail: `/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`
- ExperimentsTab on project page: `lib/components/project/ExperimentsTab.svelte` — tab selected via `?tab=experiments` URL param (NOT a separate route)
- Nav active state uses `nav-active` CSS class (not `aria-current` or `data-active`) — regex `/^\/[^\/]+\/experiments/` covers both index and detail pages
- Status rollup utility: `experimentStatusClasses` and `experimentStatusLabel` in `projectUtils.ts` — maps `lifecycle_status` string to display
- RunProgressBar: shows "N of M runs" only when `total > runs.length` (capped at 60); otherwise "N runs"

## Pre-existing in Seed Data
- Dev seed DB for this worktree is `batchrite_wt5` — starts empty, no seeded experiments
- ToS must be accepted before navigating: call `POST /auth/accept-tos` in QA login helpers

## Checklist Results (all PASS after fix)
- Nav entry (desktop + mobile): PASS
- Org-wide index stat strip (3 cards: Experiments/In progress/Runs): PASS  
- Filter pills (All/In progress/Complete/Draft): PASS
- Search box: PASS
- ExperimentsTab single-click nav: PASS
- Chevron expand (multi-row): PASS
- Mobile card ≥44px: PASS
- ExperimentCreateModal (Name/Objective/Description + cancel + submit): PASS (after schema fix)
- Experiment detail: no Edra, no status select, (auto) suffix, cursor-help tooltip: PASS
- Objective edit/save/persistence: PASS
- Empty objective italic callout: PASS
- lifecycle_status field in API response: PASS
- No console errors, no 4xx/5xx: PASS
