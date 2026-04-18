# F-0015 — Site Walkthrough & Guided Onboarding Tour

**Status:** Approved (2026-04-17)
**Task:** [F-0015] Site Walkthrough & Guided Onboarding Tour
**Scope:** Frontend + backend (user state, sample seeding, tour artifact endpoints)
**Priority:** P1
**Source:** GAP-007

## Problem

New users land on the dashboard with no guidance. With a 30-day trial model, first impressions determine conversion, and today there is no first-run experience: no welcome, no sample content, no explanation of how the three key surfaces (projects, protocol editor, run execution) fit together.

## Solution

A user-controlled, segmented guided tour covering three contexts — **Projects**, **Protocol Editor**, **Runner** — plus a single seeded sample project per new org. The tour is gated by a small modal between segments so the user is never trapped in a walkthrough they didn't choose.

Driver.js (~10kb, zero deps) powers the spotlight popovers. Tour state is persisted on the `User` model so completed and dismissed segments are remembered across sessions and devices.

## User Flow

1. **First login** (after email verification) → dashboard loads → welcome modal auto-opens.
2. Welcome modal: two buttons — **[Check out how projects are laid out]** / **[Dismiss]**.
3. **Project tour**: navigates to an active project, 5-step driver.js tour over tabs (Protocols → Experiments → Runs → Activity → Settings).
4. End of project tour → modal: **[Tour how to construct a protocol]** / **[End]**.
5. **Protocol tour**: find-or-creates a sample protocol (pre-populated canvas), navigates to editor, 4-step tour over sidebar / canvas / toolbar / inspector.
6. End of protocol tour → modal: **[Tour how to run a protocol]** / **[End]**.
7. **Run tour**: creates a sample run, navigates to run page, 4-step tour over role assignment / step cards / completion. **Auto-deletes sample run on tour end.**
8. User can dismiss at any segment-gate modal or anywhere mid-tour (ESC / skip). Dismissed = permanent opt-out for that segment.
9. Untoured, undismissed contexts show a pulsing hint dot on their page; clicking the dot re-opens the same two-button modal for that segment.

### Modal State Model

When any tour modal is open, three closures:

- **[Take tour / next segment]** → starts the tour. Pulse stays; only cleared on tour completion (segment marked `completed`).
- **[Dismiss / End]** → pulse goes away permanently. Segment marked `dismissed`. No more dot, no more modal for that segment.
- **ESC or click-outside** → soft close. No state change. Pulse continues next time. ("Not now", not "never".)

### Replay Mechanism

A "?" help button sits in the corner of each of the three tour pages (`/projects/[id]`, `/protocols/[id]`, `/runs/[id]`). Clicking it opens a small menu with "Take tour". This bypasses the completion check — the tour runs again with find-or-create semantics on the underlying sample artifacts.

## Artifact Lifecycle

### Sample Project (seeded)

- Created at org registration with name "My First Project". **Normal project** — no `is_tour_sample` flag. User can rename, delete, extend.
- Project tour navigates to any active project the user has. If all projects are archived, the tour-start endpoint lazily creates "My First Project" so the tour has a landing page.

### Sample Protocol (find-or-create on tour start)

- `Protocol` row with `is_tour_sample=True`, nested in any active project (find-or-create the project first if needed).
- Pre-populated graph: 3–4 unit-op nodes wired with edges to illustrate structure without requiring drag-drop. Spotlight targets are CSS selectors against the editor chrome (`.toolbar`, `.sidebar`, `.canvas-wrapper`), **not** specific node IDs — so the tour remains stable even if the user has edited the protocol.
- Renders a small "Sample" badge wherever it appears in lists (protocols table on project detail page).
- Deletable from the normal delete UI with no confirmation friction (bypasses archival guards).

### Sample Run (create-on-start, delete-on-end)

- `Run` row with `is_tour_sample=True`, derived from the sample protocol.
- **Cleanup rules:**
  - On run-tour start: delete any pre-existing `is_tour_sample=True` run for this user (belt-and-suspenders for orphans from closed browsers).
  - On run-tour end (completed OR dismissed mid-tour): delete the sample run.
- Not intended to appear in run history. Renders a "Sample" badge if the user somehow sees it in a list (unlikely window between create and end).

## Architecture

### Backend

**Schema changes:**

1. `User` — add `tour_state: JSONB` (nullable, default `{}`) with shape:
   ```json
   { "completed": ["project"], "dismissed": ["run"] }
   ```
   A segment in either list suppresses its dot and modal. Valid segments: `project`, `protocol`, `run`.
2. `Protocol` — add `is_tour_sample: Boolean NOT NULL DEFAULT false` + index.
3. `Run` — add `is_tour_sample: Boolean NOT NULL DEFAULT false` + index.

**Alembic migration** autogenerates all three.

**New endpoints** (router: `/api/onboarding/`):

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/state` | Returns the current user's `tour_state`. |
| `PATCH` | `/state` | Body: `{segment: "project"|"protocol"|"run", status: "completed"|"dismissed"}`. Upserts into `tour_state`. |
| `POST` | `/tour/project/start` | Returns `{project_id}`. Picks first active project; creates "My First Project" if none. |
| `POST` | `/tour/protocol/start` | Returns `{project_id, protocol_id}`. Find-or-create sample project (if needed) + sample protocol with pre-populated graph. |
| `POST` | `/tour/run/start` | Returns `{run_id}`. Deletes any prior `is_tour_sample` run for this user, then creates a fresh one from the sample protocol. |
| `POST` | `/tour/run/end` | Deletes the user's `is_tour_sample` run. Idempotent (safe if already gone). |

**Seeding:** `app/api/endpoints/auth.py:register` creates the "My First Project" row alongside the org.

**Services:** a small `app/services/onboarding.py` module with stateless functions:
- `find_or_create_sample_project(db, user, org) -> Project`
- `find_or_create_sample_protocol(db, user, org) -> Protocol`
- `find_or_create_sample_run(db, user, protocol) -> Run`
- `delete_sample_run(db, user) -> None`
- `get_sample_protocol_graph() -> dict` — returns the canonical pre-populated graph.

**Archival bypass:** when an endpoint or service attempts to delete a `Protocol` or `Run` where `is_tour_sample=True`, skip any archival / completion / locked-status guards. Implementation audits existing delete paths (`endpoints/science.py`), and if guards are present, they add an explicit early branch for `is_tour_sample` rows. If no guards exist, no bypass is needed.

### Frontend

**Library addition:** `driver.js` in `package.json`.

**New module: `frontend/src/lib/onboarding/`**

```
lib/onboarding/
  tourState.svelte.ts       # Svelte 5 rune store (completed / dismissed)
  tours/
    projectTour.ts          # driver.js step config for 5-step project tour
    protocolTour.ts         # driver.js step config for 4-step editor tour
    runTour.ts              # driver.js step config for 4-step runner tour
  TourModal.svelte          # reusable two-button modal
  HintDot.svelte            # pulsing dot (positioned via props: top/right)
  HelpMenu.svelte           # "?" corner button with "Take tour" item
  index.ts                  # re-exports
```

**`tourState.svelte.ts`** responsibilities:
- Hydrates from `GET /api/onboarding/state` on login.
- Exposes `isCompleted(segment)`, `isDismissed(segment)`, `shouldShowDot(segment)`.
- `markCompleted(segment)` / `markDismissed(segment)` → PATCHes backend, updates local state.

**`TourModal.svelte`** props:
- `open: boolean`
- `title: string`
- `primaryLabel: string` (e.g., "Check out how projects are laid out")
- `secondaryLabel: string` (e.g., "Dismiss")
- `onPrimary: () => void`
- `onSecondary: () => void` — wiring caller should call `markDismissed()`
- Built on existing shadcn-svelte `Dialog` primitive (per project conventions).

**`HintDot.svelte`** — absolute-positioned, Tailwind `animate-ping` on an overlay circle + solid dot, anchored to a relative-positioned parent. Click → opens the segment's modal.

**Page integrations:**

- `routes/+page.svelte` (dashboard) — on mount, if `tour_state` is empty (no entries in `completed` or `dismissed`), open the welcome modal. Clicking **[Dismiss]** on the welcome modal marks all three segments as `dismissed`. Clicking **[Take tour]** navigates into the project tour (no preemptive state write; `completed` is set when that tour finishes). Refreshing before acting shows the modal again — acceptable.
- `routes/projects/[id]/+page.svelte` — mount `HelpMenu` + `HintDot` keyed to `project` segment.
- `routes/protocols/[id]/+page.svelte` — mount `HelpMenu` + `HintDot` keyed to `protocol` segment.
- `routes/runs/[id]/+page.svelte` — mount `HelpMenu` + `HintDot` keyed to `run` segment.

**Empty state CTAs:** extend the existing `EmptyState` component (from TD-0072) with two new optional props — `secondaryActionLabel?: string` and `secondaryOnAction?: () => void` — rendered as a ghost-variant link below the primary button. Then update three call sites:
- Dashboard "No runs yet" — secondary: "Take the tour" → opens welcome modal.
- Projects page "No projects found" — secondary: "Take the tour" → opens welcome modal.
- Protocols tab empty state on project detail page — secondary: "Take the tour" → opens welcome modal.

The welcome modal is the single entry point — all three CTAs route to the same place so users who skipped the initial auto-modal can still opt in.

### Driver.js Step Configuration (sketch)

**Project tour (5 steps):**
1. `.project-tab-protocols` — "Protocols are the recipes your team runs."
2. `.project-tab-experiments` — "Experiments snapshot a protocol at a point in time."
3. `.project-tab-runs` — "Runs are active or completed executions."
4. `.project-tab-activity` — "Activity shows who's doing what."
5. `.project-tab-settings` — "Manage project members and templates here."

**Protocol tour (4 steps):**
1. `.protocol-sidebar` — "Unit ops live here. Drag them onto the canvas."
2. `.protocol-canvas` — "Connect steps with edges to define the workflow."
3. `.protocol-toolbar .save-button` — "Save your changes."
4. `.protocol-inspector` — "Selected nodes show their params here."

**Run tour (4 steps):**
1. `.run-role-panel` — "Assign team members to the roles this protocol needs."
2. `.run-step-list` — "Work through the steps in order."
3. `.run-step-complete-button` — "Check each step off as you go."
4. `.run-results-summary` — "See run status and results here."

Selectors are added to existing markup as stable `data-tour` / class hooks during implementation.

## Edge Cases

| Scenario | Behavior |
|---|---|
| Sample project deleted, all projects archived | Project-tour start endpoint recreates "My First Project" before returning id. |
| Sample protocol deleted | Protocol-tour start recreates via find-or-create. |
| Sample run orphaned (browser closed mid-tour) | Run-tour start deletes existing `is_tour_sample` run before creating fresh. |
| User heavily edited sample protocol | Tour reuses it; spotlights target UI chrome (selectors) not nodes — tour still narrates correctly. |
| User replays from "?" menu after completing | Bypasses completion check; runs again with find-or-create semantics. Does not clear `completed` flag. |
| Multi-org user switches org mid-tour | Tour state is per-user (not per-org). Switching org during a tour is an edge case not specifically handled — tour continues, but artifact endpoints are scoped to the current selected org. Acceptable for v1. |
| Field mode (`/field` route) | Out of scope for v1. Field mode is a focused read-only variant; no tour added. |

## Testing

**Backend (pytest):**
- Unit: `find_or_create_sample_project`, `find_or_create_sample_protocol`, `find_or_create_sample_run`, `delete_sample_run` — covering find path, create path, orphan cleanup.
- Integration: each of the 6 new endpoints — happy path, auth, idempotency (e.g., second `/tour/run/end` is a no-op).
- Integration: `auth/register` — verify "My First Project" is created.

**Frontend (Vitest + Playwright):**
- Unit: `tourState.svelte.ts` — hydration, marking, derivation of `shouldShowDot`.
- Component: `TourModal` — renders labels, fires callbacks on each button; ESC / outside-click does NOT fire `onSecondary`.
- Component: `HintDot` — only renders when `shouldShowDot` is true.
- E2E (Playwright): happy path for each segment (complete), dismiss path (no dots after), replay path (from "?" menu).

## Acceptance Criteria (from task)

- [x] Driver.js-based multi-page guided tour
- [x] Context-specific tours (editor, runner)
- [x] Pulsing hint dots
- [x] Sample protocol for new orgs (sample project seeded; sample protocol find-or-created on tour start)
- [x] Empty state CTAs linking into the tour

## Out of Scope

- Tours for AI Chat, Library, Settings, Field mode.
- Interactive drag-drop detection / xyflow event hooks (observation-only tour for v1).
- Analytics instrumentation on tour events (can be added later).
- A "reset sample content" action in the "?" menu.
- Per-org tour state (tour state is per-user).
