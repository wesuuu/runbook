---
name: project-f0043-coupling-patterns
description: Coupling hotspots discovered during F-0043 phases 4-7 impact analysis — lifecycle state consumers, lock-guard gaps, audit action rendering
metadata:
  type: project
---

**F-0043 phases 4-7 introduced AWAITING_CONCLUSION lifecycle state, conclusion lock, key_result triple on runs, and PDF export.**

Key coupling patterns discovered:

**Lifecycle status consumers (all handled correctly):**
- `experimentStatusClasses`, `experimentStatusLabel`, `experimentStatusTooltip` in `frontend/src/lib/components/project/projectUtils.ts` — all 5 states covered
- Index page (`[org]/experiments/+page.svelte`) — 5-tab filter + `awaitingConclusion` stat card added
- `ExperimentsTab.svelte` — delegates to projectUtils helpers; AWAITING_CONCLUSION falls through to label/class correctly
- `derive_lifecycle_status` call sites in `experiments.py` — all thread `conclusion_locked` via `exp.conclusion_locked_at is not None` EXCEPT the `POST /experiments` create endpoint (line 175), which is correct because a new experiment has no lock

**Lock guards (all covered):**
- `PUT /experiments/{id}` — line 458
- `POST /runs` (project-level, with experiment_id) — line 100 in runs.py
- `POST /experiments/{id}/runs` — line 774 in experiments.py (with TOCTOU FOR UPDATE)
- `PUT /experiments/{id}/notes` — line 899
- `DELETE /experiments/{id}/notes/{note_id}` — line 984
- `PUT /runs/{id}` for key_result fields — intentionally NOT locked per spec line 115: "no lock semantics on the run side"

**Unaddressed UX gaps (not correctness breaks):**
- `AssignToExperimentModal.svelte` — `ExperimentOption` type lacks `conclusion_locked_at`; locked experiments appear in dropdown but 409 at backend. VERIFY if this is acceptable UX.
- `RunCreatorNameStep.svelte` — same; wizard shows locked experiments to select; 409 at backend saves it.

**Audit action rendering gaps (SHOULD UPDATE):**
- `AuditTimeline.svelte` — falls back to `entry.action.toLowerCase()` for new actions (`conclusion.lock`, `conclusion.unlock`, `key_result.set`, `export.pdf`); will render as raw strings
- `ActivityTab.svelte` — `allEntityTypes = ["Project", "Protocol", "Run"]` missing "Experiment"; conclusion.lock audit rows (entity_type=Experiment) not filterable. `allActionTypes` also missing new action types.

**Stale test name (SHOULD UPDATE):**
- `backend/tests/unit/services/test_experiment_status.py:19` — `test_all_live_runs_completed_is_complete` now asserts AWAITING_CONCLUSION; name is a lie.

**F-0093 spec doc is stale (SHOULD UPDATE):**
- `docs/superpowers/specs/2026-05-21-f-0093-experiments-investigation-workspace-design.md` lines 414-419 — still shows 4-state table (DRAFT/IN_PROGRESS/COMPLETE/ARCHIVED) without AWAITING_CONCLUSION.

**Why:** These patterns will recur when F-0043 phases are merged and someone reads the old spec or adds a new audit action renderer.
**How to apply:** When touching experiment lifecycle or audit action display, check AuditTimeline labels map and ActivityTab allEntityTypes/allActionTypes for missing entries.
