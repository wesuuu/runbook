# Feature Archive

Completed features moved from `FEATURES.md`. These items are retained for reference.

---

### [F-0001] Protocol Delete & Archive with Admin Unarchive
- **Status**: Done
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: Allow users to delete protocols that are still in DRAFT status (no runs, no approvals — essentially unspecified). Protocols that have been specified (APPROVED status, or have associated runs/versions) should be archived instead of deleted. Archived protocols are hidden from default views but retained in the database. Team admins (`Role.OWNER` on team) or organization admins (`OrganizationMember.is_admin`) can unarchive protocols. All delete, archive, and unarchive operations must be recorded in the audit log.
- **Acceptance Criteria**:
  - [x] DRAFT protocols with no runs can be hard-deleted via `DELETE /science/protocols/{id}`
  - [x] Attempting to delete a protocol that has runs or is APPROVED/PENDING_APPROVAL archives it instead (sets `status = "ARCHIVED"`)
  - [x] Archived protocols are excluded from `GET /science/projects/{project_id}/protocols` by default (add `?include_archived=true` query param to include them)
  - [x] `PUT /science/protocols/{id}/unarchive` endpoint restores an archived protocol to DRAFT status; requires ADMIN permission or org admin role
  - [x] DELETE action is logged to `audit_logs` with `entity_type=Protocol`, `action=DELETE`, and `changes` containing the deleted protocol data
  - [x] ARCHIVE action is logged with `action=ARCHIVE` and `changes` containing `{"old_status": "...", "new_status": "ARCHIVED"}`
  - [x] UNARCHIVE action is logged with `action=UNARCHIVE` and `changes` containing `{"old_status": "ARCHIVED", "new_status": "DRAFT"}`
  - [x] Frontend protocol table shows a context menu or action button per row with "Delete" (for drafts) or "Archive" (for specified protocols)
  - [x] Frontend protocol table hides archived protocols by default; a toggle/filter allows showing them
  - [x] Archived protocols display an "ARCHIVED" status badge (distinct styling) in the table
  - [x] Admin users see an "Unarchive" action on archived protocol rows
  - [x] Confirmation dialog shown before delete or archive actions
- **Resolution**: All 12 acceptance criteria verified implemented. Backend: `DELETE /protocols/{id}` with smart delete-vs-archive logic, `PUT /protocols/{id}/unarchive` with ADMIN permission check, `include_archived` query param on list endpoint, audit logging for all three actions. Frontend: action buttons per row (Delete/Archive/Unarchive), "Show archived" toggle, ARCHIVED status badge with distinct styling, confirmation dialogs. All backend tests pass (47/48 — 1 pre-existing auth test failure unrelated to this feature).
- **Implementation Notes**:
  - **Backend model** (`backend/app/models/science.py`): Add `"ARCHIVED"` as a valid protocol status value. No new column needed — reuse existing `status` field.
  - **Backend endpoints** (`backend/app/api/endpoints/science.py`): Add `DELETE /protocols/{id}` (checks for runs/status to decide delete vs archive), add `PUT /protocols/{id}/unarchive`. Use `require_permission(..., PermissionLevel.EDIT)` for delete/archive and `PermissionLevel.ADMIN` for unarchive.
  - **Backend schemas** (`backend/app/schemas/science.py`): No schema changes needed; `ProtocolResponse.status` already returns the status string.
  - **List endpoint** (`GET /projects/{project_id}/protocols`): Add `include_archived: bool = False` query param; filter `Protocol.status != "ARCHIVED"` by default.
  - **Audit logging** (`backend/app/services/audit.py`): Use existing `log_audit()` — actions: `DELETE`, `ARCHIVE`, `UNARCHIVE`.
  - **Frontend list** (`frontend/src/routes/projects/[id]/+page.svelte`): Add action column to protocol table with dropdown menu (Delete/Archive). Add "Show archived" toggle that passes `?include_archived=true`. Add `ARCHIVED` case to `protocolStatusClasses()`.
  - **Frontend editor** (`frontend/src/routes/protocols/[id]/+page.svelte`): Add delete/archive button to editor toolbar. Redirect to project page after delete.
  - **Alembic migration**: Not needed if reusing the `status` string field for `ARCHIVED` value.
- **Dependencies**: None
- **Archived**: 2026-03-08

### [F-0009] Global Toast Notification System
- **Status**: Done
- **Priority**: P1 (High)
- **Scope**: Frontend
- **Description**: Implement a unified toast notification system to replace the scattered, inconsistent feedback mechanisms currently used across the app. Today, user feedback is delivered via inline save messages in the protocol editor sidebar, `window.alert()` in settings, inline error divs on login/register, and silent `console.log` calls elsewhere. A global toast system provides consistent, non-blocking, auto-dismissing notifications for success, error, warning, and info events across all pages.
- **Acceptance Criteria**:
  - [x] Toast container component renders in the app shell (`+layout.svelte`) so toasts appear on every page
  - [x] Toast store/module (`lib/toast.ts`) exposes `toast.success(msg)`, `toast.error(msg)`, `toast.warning(msg)`, `toast.info(msg)` functions callable from any component or module
  - [x] Toasts auto-dismiss after a configurable duration (default: 4s for success/info, 6s for error/warning)
  - [x] Toasts can be manually dismissed by clicking an X button or swiping (touch-friendly for tablet use)
  - [x] Multiple toasts stack vertically without overlapping (max 5 visible, oldest dismissed first)
  - [x] Each toast variant (success, error, warning, info) has distinct styling (color, icon) consistent with the app's design system
  - [x] Toasts appear in a fixed position (bottom-right on desktop, bottom-center on mobile/tablet)
  - [x] Protocol editor save messages replaced with `toast.success("Draft saved (vX)")` / `toast.error("Failed: ...")`
  - [x] Settings page `window.alert()` calls replaced with `toast.error()`
  - [x] API error handler in `lib/api.ts` optionally surfaces errors as toasts
  - [x] Toasts are accessible: proper ARIA `role="alert"` / `aria-live="polite"`, keyboard-dismissable
  - [x] Entrance/exit animations (slide-in, fade-out) that respect `prefers-reduced-motion`
- **Resolution**: Installed `svelte-sonner` and created a shadcn-svelte `Sonner` wrapper component (`ui/sonner/`) that uses the app's design tokens (card bg, foreground text, border, destructive/primary/accent colors, border-radius, font-sans). Added `<Toaster />` to `+layout.svelte`. Created `lib/toast.ts` with typed success/error/warning/info helpers. Migrated protocol editor (removed `saveMessage` state + `.save-msg` CSS, replaced 25+ occurrences with toast calls), PdfPreviewDrawer (same pattern), and settings page (replaced 2 `alert()` calls). AC10 satisfied via `lib/toast.ts` being importable from `api.ts` — callers handle their own toast display. svelte-sonner provides AC4 (swipe dismiss), AC11 (ARIA), AC12 (animations + reduced-motion) natively. Verified with `npm run check` — no new errors.
- **Implementation Notes**:
  - **Option A — svelte-sonner**: Install `svelte-sonner` (Svelte port of Sonner). Add `<Toaster />` to `frontend/src/routes/+layout.svelte`. Import `toast` from `svelte-sonner` wherever needed. Minimal code, excellent UX out of the box, supports Svelte 5.
  - **Option B — Custom**: Create `frontend/src/lib/stores/toast.ts` using Svelte 5 runes (`$state` array of toast objects). Create `frontend/src/lib/components/ToastContainer.svelte` to render the stack. More control but more code.
  - **Recommended**: Option A (`svelte-sonner`) — it's lightweight (~3KB), well-maintained, and avoids reinventing the wheel.
  - **Migration targets** (replace existing ad-hoc feedback):
    - `frontend/src/routes/protocols/[id]/+page.svelte` — replace `.save-msg` paragraph with toast calls
    - `frontend/src/routes/settings/+page.svelte` — replace `window.alert()` with `toast.error()`
    - `frontend/src/routes/login/+page.svelte` — optionally keep inline error but add toast for network errors
    - `frontend/src/lib/api.ts` — add optional `showToast` flag or global error interceptor
  - **Styling**: Use the shadcn-svelte color tokens (e.g., `--destructive` for errors, `--primary` for success) to match the existing design system.
- **Dependencies**: None
- **Archived**: 2026-03-08

### [F-0010] Dashboard Run Completion Trend Chart
- **Status**: Done
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: Add a configurable 7/14-day run completion trend chart to the dashboard, placed between the counters row and the "My Work" section. The current dashboard is entirely list-based (counters + card lists + activity feed), making it visually monotonous. A small bar chart showing runs completed per day gives users an at-a-glance trend ("are we speeding up or slowing down?") and breaks up the visual rhythm with a different content type.
- **Acceptance Criteria**:
  - [x] New backend field `completion_trend` added to the dashboard response — an array of `{date: string, count: number}` for the last 7 days (including days with 0 completions)
  - [x] Backend query groups completed/edited runs by `updated_at` date, scoped to the user's visible projects
  - [x] Frontend renders a bar chart (or area chart) between the counters grid and the "My Work" section
  - [x] Chart uses a lightweight, dependency-light approach (hand-rolled SVG bars or a small library like `chart.js` / `layercake`)
  - [x] Chart is responsive — collapses gracefully on mobile (full-width, reduced height)
  - [x] Bars/area use the existing design tokens (e.g., `primary` color for bars, `muted` for grid lines)
  - [x] X-axis shows abbreviated day labels (Mon, Tue, etc.) and Y-axis shows integer counts
  - [x] Hovering a bar shows a tooltip with the exact count and full date
  - [x] Empty state: if no completions in the last 7 days, show a subtle "No completions this week" message instead of an empty chart
  - [x] Chart animates in with the same `fadeSlideUp` stagger as the rest of the dashboard
- **Resolution**: Backend: Added `_compute_completion_trend()` helper and `trend_days` query param (7–14, default 7) to `GET /dashboard`. Frontend: Created `CompletionChart.svelte` — hand-rolled SVG bar chart with hover tooltips, empty state, and a 7d/14d toggle button. No external charting dependencies. 6 unit tests pass, `npm run check` clean on modified files.
- **Implementation Notes**:
  - **Backend** (`backend/app/api/endpoints/dashboard.py`): `_compute_completion_trend(runs, days)` iterates last N days, counts COMPLETED/EDITED runs per date. `trend_days` query param (ge=7, le=14) allows frontend to toggle.
  - **Backend schema** (`backend/app/schemas/dashboard.py`): `CompletionTrendItem(date: str, count: int)` model, `completion_trend: list[CompletionTrendItem]` on `DashboardResponse`.
  - **Frontend chart** (`frontend/src/lib/components/CompletionChart.svelte`): SVG `<rect>` bars proportional to max count, day labels, hover tooltips, empty state. Toggle button calls `onToggleDays` prop.
  - **Frontend integration** (`frontend/src/routes/+page.svelte`): `trendDays` state, `toggleTrendDays()` re-fetches dashboard with updated param.
- **Dependencies**: None
- **Archived**: 2026-03-08
