---
name: project-f0043-phases47-coupling
description: Coupling sites found for F-0043 phases 4-7 (Experiments Redesign — Conclusion, Results, Observations, Export). Key misses the spec left for implementors.
metadata:
  type: project
---

Key coupling sites for F-0043 phases 4-7 plan (2026-05-22).
**Status: plan reviewed 2026-05-23 — findings below are gaps NOT covered by the plan.**

## CONFIRMED GAPS (plan does NOT cover these)

**POST /runs lock guard missing** — `backend/app/api/endpoints/runs.py:216` only checks `LIFECYCLE_ARCHIVED`. After conclusion is locked, `POST /runs` will still accept new runs for that experiment. The test file `test_run_experiment_guard.py` only tests the archived case. The plan does NOT mention adding a `conclusion_locked_at IS NOT NULL` guard to this endpoint.

**POST /experiments/{id}/runs lock guard missing** — `backend/app/api/endpoints/experiments.py:547` similarly only checks `ARCHIVED`. Add the same `conclusion_locked_at` guard here or add runs will bypass the lock.

**`derive_lifecycle_status` call at line 251 (`get_experiment_by_slug`) not listed** — The plan's Task 4 Step 1 only lists lines 162, 203, 251 (listed in text but says leave 162 alone), 363, 409, 468. Line 251 in `get_experiment_by_slug` uses `lifecycle_counts_from_runs(runs)` and passes to `derive_lifecycle_status(exp.status, live, open_)`. It needs `conclusion_locked=exp.conclusion_locked_at is not None` — the exp ORM row is loaded, so no SQL change needed.

**`canAdmin` derivation is a placeholder on the experiment detail page** — `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte` has no admin-role checking yet. Task 20 in the plan writes `const canAdmin = $derived(/* existing admin derivation */);` but there is no existing admin derivation on this page. The correct pattern (from auth.svelte.ts) is `getCurrentOrgRoles().includes('ADMIN')`.

**`AssignToExperimentModal` will silently try to add a run to a locked experiment** — `frontend/src/lib/components/project/AssignToExperimentModal.svelte:28` filters only `status !== 'ARCHIVED'`. After lock, users can still attempt to assign a run; the backend will 409 with `EXPERIMENT_LOCKED` but the modal shows a generic error. Plan does NOT mention updating this modal.

**Hardcoded tooltip text on experiments index page** — `frontend/src/routes/[org]/experiments/+page.svelte:200` has `title="Status is derived from this experiment's runs — add or complete runs to advance it."` which is now incomplete for the AWAITING_CONCLUSION state (where the conclusion lock, not runs, determines COMPLETE). Plan does not mention updating this.

**`pdf_export.py` import of `pdf_base` uses wrong import style** — Plan at Task 12 Step 3 writes `from app.services.documents import pdf_base` but the entire codebase uses `from app.services.documents.pdf_base import (...)`. The module-level import will fail at startup.

**Existing `test_experiment_status.py` asserts `"COMPLETE"` without `conclusion_locked`** — Lines 22, 46, 81 assert `derive_lifecycle_status(...) == "COMPLETE"` using the 3-arg form. Once the default `conclusion_locked=False` is added, these will instead return `"AWAITING_CONCLUSION"`. The plan (Task 3 Step 5) says "if any test asserts COMPLETE, update that single assertion to AWAITING_CONCLUSION" — this IS covered by the plan.

**`ExperimentUpdate.model_config = ConfigDict(extra="forbid")`** — Adding `conclusion` to `ExperimentUpdate` (Task 5 Step 1) is fine. But the lock guard check at Task 6 Step 3 raises 409 BEFORE iterating fields, so the `conclusion` field would silently be rejected by the lock guard even if conclusion is what's being updated. This is intentional per spec (all mutations block while locked), but worth verifying the test covers the case where conclusion is the field being sent.

## ALREADY COVERED BY PLAN

- `LifecycleStatusEnum` in `frontend/src/lib/schemas/experiments.ts:10` — Task 13
- `experimentStatusClasses` / `experimentStatusLabel` in `projectUtils.ts:163,177` — Task 13 Step 4
- Experiment index page filter + stats — Task 22
- All 6 `derive_lifecycle_status` call sites in experiments.py — Task 4
- `_experiment_dict` helper update — Task 6 Step 4
- `ExperimentResponse` new fields — Task 5 Step 4
- `RunResponse` new fields — Task 5 Step 5
- Existing `test_experiment_status.py` COMPLETE assertions → AWAITING_CONCLUSION — Task 3 Step 5
- `schemas/index.ts` re-export for observation.ts — Task 13 Step 3
- E2E seed script in `backend/app/db/seed.py` — Task 23

## ARCHITECTURE NOTES (for future conversations)

- `_experiment_dict()` is the single function that maps Experiment ORM → dict for ExperimentResponse; any new column on Experiment must be added here.
- `derive_lifecycle_status` has exactly 2 callers: `experiments.py` (6 call sites) and the new `test_status_phase_4_7.py`. Both runs.py and test files import only `LIFECYCLE_ARCHIVED` from status.py.
- `pdf_base.py` is marked DEPRECATED; correct import is `from app.services.documents.pdf_base import (function_name)`, NOT `import pdf_base`.
- `ExperimentUpdate` uses `extra="forbid"` so any new field MUST be added to the schema or it will 422.
- `AssignToExperimentModal` filters by `status !== 'ARCHIVED'` (ORM status, not lifecycle_status). After lock, the lifecycle_status becomes COMPLETE but ORM status stays DRAFT — so the modal will still show locked experiments as selectable.
