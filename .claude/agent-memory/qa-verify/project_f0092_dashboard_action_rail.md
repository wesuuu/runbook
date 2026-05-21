---
name: f0092-dashboard-action-rail-qa
description: QA verification notes for F-0092 Dashboard Action Rail landing page rebuild
metadata:
  type: project
---

F-0092 Dashboard Action Rail QA verified 2026-05-21 — PASS on all checklist items.

Key facts:
- Feature lives in `frontend/src/routes/+page.svelte` + `frontend/src/lib/components/dashboard/` (ActionCounters, BlockerTag, CalibrationWidget, AwaitingSignoffWidget, RecentActivityWidget, LabStatusRail)
- Backend endpoint: GET `/dashboard?org_id=<id>` — returns `{my_work, lab_status, activity, counters}`
- Backend runs at port 8040 (slot-4 DB); CORS list needs `localhost:5213` added for this worktree's frontend

**Why:** QA was run while the backend CORS list didn't include port 5213; workaround was patchCors() in Playwright route intercept.

**How to apply:** When QA-verifying this worktree's frontend, either add `localhost:5213` to the running backend's CORS allow-list, or use route intercept to inject CORS headers.

Counter behaviors:
- `runs_blocked` → scrollPulse('#needs-action') — amber flash on the section
- `signoffs_pending` → scrollPulse('#awaiting-signoff') — amber flash on whole Lab Status rail (intentional)
- `calibrations_due` → goto('/settings?tab=sites')
- `active_runs` → goto('/projects')

Skeleton: dashboard-specific skeleton (not global spinner) appears at ~600ms during slow load; mirrors 4-counter row + 2-column layout.

ToS gate: Admin user hits /legal/accept on first login. QA driver must call `POST /auth/accept-tos` with Bearer token before navigating to dashboard.

TourModal: Welcome modal opens on first login (isWelcomeEmpty). QA driver must dismiss it (button "Dismiss") before clicking counter cards, as it overlays the page.

UI notes:
- BlockerTag: red badge, `LANES_UNASSIGNED` code → "1 lane unassigned" or "No one assigned" labels
- Portrait 820×1180: counters stack 2×2, My Work then Lab Status in single column — no overflow
- Error state: shows "!" circle + message + "Retry" link button (not a filled button)
- Pulse animation: 1.2s CSS animation via `.section-pulse` class applied to the section wrapper
