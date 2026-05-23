# TD-0091b — Notification inbox: UX, observability & test coverage

**Date:** 2026-05-21
**Task:** TD-0091b (subtask of TD-0091, 2026-05-21 notification-system QA audit)
**Priority:** P2/P3
**Base branch:** `main` — TD-0091a (the prerequisite critical-bug fixes) is merged to `main` but **not** to `td-0083-split-science-module`. All work branches from `main`.

## Problem

The 2026-05-21 QA audit of the in-app notification inbox found five quality gaps in
`frontend/src/lib/components/layout/NotificationBell.svelte` and the dispatcher:

1. **(P2) No real-time delivery.** Polling only — the unread count polls every 30 s; the
   list is fetched only when the dropdown opens and never refreshes while open. Up to 30 s
   badge latency.
2. **(P2) Errors are swallowed.** Every `catch` block in `NotificationBell.svelte` is empty.
   Failed count-polls, list fetches, and mark-read calls are invisible; optimistic mark-read
   updates can silently diverge from server state.
3. **(P2) No history page or retention policy.** The bell shows only the most recent 20
   notifications. There is no inbox/history route, the API's `offset` is unused, and
   `Notification` rows are never purged — the table grows unbounded.
4. **(P2) Clicks don't deep-link.** Clicking a notification marks it read but does not
   navigate, although `entity_type`/`entity_id` are stored.
5. **(P3) No test coverage.** `NotificationBell.svelte` and the dispatcher's
   `dispatch_event` / `retry_pending` paths are untested.

## Goals

- Reduce inbox staleness without new real-time infrastructure.
- Make every notification API failure observable.
- Give users a full, paginated notification history and bound the table's growth.
- Make notifications navigable to the entity they reference.
- Cover the bell, the deep-link resolver, the history page, and the dispatcher with tests.

## Non-goals

- SSE/WebSocket push (evaluated and rejected for this P2 tech-debt — see Decisions).
- A soft-archive model with an `archived_at` column (rejected — see Decisions).
- User-facing notification preferences / muting (covered by TD-0091c, out of scope here).
- Filters on the history page (e.g. unread-only) — explicitly out of scope.
- New notification event types or emitters (TD-0091i).
- Fixing the dispatcher `MAX_RETRIES` / `RETRY_BACKOFF` off-by-one (see Risks → routed to a
  follow-up task; this task only *tests* the retry path against its observed contract).

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Real-time approach | **Smarter polling** | The ticket states the minimum is "refresh the list on each poll / while the dropdown is open." SSE means a new endpoint, connection lifecycle, and query-token auth — disproportionate to a P2 tech-debt item. |
| Retention mechanism | **Hard-delete read, keep unread** | No model column change. Unread notifications are never lost. The history page shows whatever remains in the table. |
| Retention window | **90 days**, configurable | Generous history, bounded growth. New `BATCHRITE_NOTIFICATION_RETENTION_DAYS` env var; `<= 0` disables the sweep. |
| Purge cadence | **At most once per 24 h** | The recovery loop ticks every ~90 s; a 90-day-window purge does not need to run 960×/day. A module-level last-run guard in `main.py` throttles it. |
| History page UI | **Minimal** | Paginated list + mark-read actions + deep-links + empty state. No filters. |
| Delivery FK on purge | **No interaction — deliveries are orthogonal** | The dispatcher (`_dispatch_to_channel`) records `NotificationDelivery` rows with `notification_id` left **NULL** — inbox `Notification` rows and external-channel `NotificationDelivery` rows are decoupled today. A purge therefore cannot affect a delivery. `notification_deliveries.notification_id` being `ON DELETE SET NULL` is a defensive contract for a *future* linkage, not a current dependency; no extra delete logic. |
| GLP / audit implication | **Accepted** | In-app notifications are UI delivery artifacts, not primary audit records — `AuditLog` is the record of record under 21 CFR §58. The external `notification_deliveries` dispatch trail is a **separate** table the purge does not touch (deliveries are not children of inbox rows — see the row above). 90-day hard-delete of the *inbox view* is acceptable. No customer data-retention SLA exists today; revisit if an enterprise contract specifies one. |
| Index for the purge | **New partial index** `ix_notif_read_at` on `notifications(read_at) WHERE read_at IS NOT NULL` | The purge predicate filters on `read_at` alone (no `user_id`); the existing `(user_id, read_at)` index cannot serve it. Requires one Alembic migration. |

## Design

### 1. Smarter polling (Gap 1) — frontend only

`NotificationBell.svelte` keeps the existing 30 s `setInterval`. The polled callback is
changed so that, when the dropdown is open, it refetches the **list** in addition to the
count. The badge count is **always** taken from `GET /notifications/unread-count` — never
derived from the fetched list slice (a `limit=20` slice undercounts a user with >20 unread,
making the badge jump when the dropdown opens/closes).

- Dropdown open → poll tick calls `fetchNotifications()` **and** `fetchUnreadCount()`.
- Dropdown closed → poll tick calls `fetchUnreadCount()` only.
- Dropdown `onOpenChange(open=true)` triggers an immediate `fetchNotifications()` +
  `fetchUnreadCount()`.
- A `visibilitychange` listener refetches on tab refocus (tablet-first app — a backgrounded
  tab throttles `setInterval`, so the staleness-on-refocus is otherwise unbounded).

**Concurrency guard.** Smarter polling plus user actions means multiple `fetchNotifications()`
calls can be in flight at once; `api.get` is not cancelable. Each call captures a
monotonically increasing sequence number; when it resolves it assigns `notifications` only
if its sequence is still the latest. This prevents a slow earlier response from clobbering a
fresh later one. The same guard applies to the history page's page fetches.

No backend change for this gap.

### 2. Error observability (Gap 2) — frontend only

Every empty `catch {}` in `NotificationBell.svelte` (and the new history page) is replaced
with explicit handling, split by how the call was triggered:

- **Background count-poll failures** → `console.error` only. No toast: a toast every 30 s
  on a flaky connection is worse than the bug. The next successful poll self-heals.
- **User-initiated failures** (opening the dropdown → list fetch; `markRead`; `markAllRead`;
  history-page load / pagination) → `console.error` **and** a `toast.error(...)` via
  `$lib/toast`.

**Optimistic-update reconciliation.** `markRead` and `markAllRead` apply their optimistic UI
change first (snappy), then call the API. On failure they **refetch from the server**
(`fetchNotifications()` + `fetchUnreadCount()` for the bell; the current page +
`unread-count` for the history view) so the UI converges to authoritative server state. The
error toast tells the user the action did not stick.

`markAllRead` is a **server-wide** action (`PUT /notifications/read-all` marks every unread
notification for the user). The history page therefore refetches the current page **on
success too** — not only on failure — because other pages' rows are now stale; and it
refreshes the badge via `unread-count`.

### 3. History page + retention (Gap 3)

**Frontend — new route `src/routes/notifications/+page.svelte`.**
- Lives behind the existing app auth gate (same as `/runs`, `/protocols`).
- Paginated list, newest-first (`ORDER BY created_at DESC`, backend-enforced), **25 per
  page** (`HISTORY_PAGE_SIZE`). `Prev` / `Next` controls plus an `X–Y of N` indicator built
  from the API's `total` and the current `offset`.
- **`offset` is held in the URL search param** (`/notifications?offset=N`, navigated via
  `goto(..., { keepFocus: true, noScroll: true })`) so browser back/forward restores the
  page position, matching the tab-state convention in `.claude/rules/frontend-components.md`.
- Rows rendered by the shared `NotificationRow` component (see §5) in **non-compact** mode.
- Row click → mark read + deep-link navigate (see Gap 4).
- `Mark all read` action in the page header — hidden when the current page has no unread
  rows (consistent with the bell).
- Loading state uses the shared `LoadingSpinner`
  (`lib/components/ui/loading-spinner.svelte`); empty state uses the shared `EmptyState`
  (`lib/components/ui/empty-state`) — title "No notifications", description "Activity from
  your runs and protocols will appear here.", no action button.
- Page + per-row Svelte transitions per `.claude/rules/frontend-components.md`
  (`fade` on the page wrapper, `animate:flip` + `in:fade` on rows).

**Bell — "View all" footer link.** A footer `DropdownMenu.Item` wrapping
`<a href="/notifications">` (so it keeps the dropdown's focus ring and ARIA menu role).
Visible whenever the dropdown is open, regardless of unread count.

**Backend — `list_notifications` gains `include_total`.** The endpoint currently always runs
a `COUNT(*)` subquery. A new `include_total: bool = Query(False)` skips the count when false.
The bell omits it (the bell's badge comes from `unread-count`, not `total`); the history page
passes `include_total=true`. When false, `total` is returned as `0` and callers must not
rely on it. Signature change is additive (new optional param, default preserves a safe
subset of old behavior for the only caller, the bell, which ignored `total`).

**Backend — retention sweep.**
- New module `backend/app/services/core/notifications/retention.py` exposing
  `purge_read_notifications(db: AsyncSession, *, older_than_days: int) -> int`.
  - `cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)` — an
    **aware UTC** datetime (`read_at` is `DateTime(timezone=True)`; a naive cutoff would
    raise or mis-compare under asyncpg).
  - **Chunked delete:** repeatedly `DELETE FROM notifications WHERE id IN (SELECT id FROM
    notifications WHERE read_at IS NOT NULL AND read_at < :cutoff LIMIT 500)`, committing
    after each chunk, until a chunk deletes fewer than 500 rows. This bounds lock duration
    and WAL on the first sweep against a large unpurged table.
  - `older_than_days <= 0` → return `0` immediately, issue no DELETE.
  - Returns the total rows deleted.
- The sweep touches only the `notifications` (inbox) table. `NotificationDelivery` rows are
  a separate audit trail the dispatcher writes with `notification_id` NULL, so they are not
  children of inbox rows and the purge cannot affect them — no extra handling. (The FK is
  `ON DELETE SET NULL` purely as a defensive contract should the two ever be linked.)
- New setting `notification_retention_days: int = 90` on `Settings`
  (`BATCHRITE_NOTIFICATION_RETENTION_DAYS`).
- **New partial index** `ix_notif_read_at` on `notifications(read_at) WHERE read_at IS NOT
  NULL`, added to the model `__table_args__` (so the test DB schema, built from ORM
  metadata, matches) **and** created by an Alembic migration using
  `CREATE INDEX CONCURRENTLY` outside a transaction (`op.execute("COMMIT")` /
  AUTOCOMMIT isolation — a plain `op.create_index` would fail `CONCURRENTLY` inside
  Alembic's transaction on a non-empty table).

**Backend — recovery-loop wiring (`app/main.py`).**
- New `_purge_old_notifications()` step in `_recovery_loop`, in its own `try/except`,
  placed **after** `_retry_pending_deliveries()` (so a purge of a notification whose
  delivery is mid-retry happens after that retry batch settles within the tick).
- A module-level `_last_notification_purge_at` timestamp throttles the sweep to **at most
  once per 24 h** — the recovery loop ticks far more often than a 90-day-window purge needs.
- On a run, it logs `INFO`: `"Retention sweep: deleted %d read notifications older than %d
  days"` (count + window) — the only operator-visible signal that the sweep is healthy. A
  `0` count still logs, distinguishing "ran, nothing eligible" from "never ran".
- When `notification_retention_days <= 0`, logs a one-time `INFO` that retention is
  disabled (mirroring the existing `"Recovery loop disabled"` line) and skips.
- Uses a fresh `AsyncSessionLocal()` session; loop-only (no startup sweep), matching the
  `_retry_pending_deliveries` pattern.

No `Notification` data-column change; one migration (the index only).

### 4. Deep-linking (Gap 4)

A new pure resolver `notificationHref(entityType: string, entityId: string): string | null`
in `frontend/src/lib/notifications.ts`:

| `entity_type` | Route |
| --- | --- |
| `run` | `/runs/{id}` |
| `protocol` | `/protocols/{id}` |
| `experiment` | `/experiments/{id}` |
| `project` | `/projects/{id}` |
| anything else, or a falsy / non-UUID `entityId` | `null` |

Today's emitters use only `run` and `protocol`; `experiment`/`project` are mapped
defensively. An unknown type or a malformed `entityId` returns `null` and degrades to "mark
read only".

**Click behavior** (bell and history page, both via `NotificationRow`'s `onSelect`):
1. If the row is unread, optimistically mark it read in local state and **fire** the
   `PUT /notifications/{id}/read` call (initiated synchronously, before any navigation).
   An already-read row skips the mark-read call but still deep-links.
2. If `notificationHref` returns a route, navigate via `goto(route)` (the bell also closes
   its dropdown).
3. Mark-read failure handling on a deep-link click is **toast-only** — no reconciliation
   refetch, because the originating component is unmounting as navigation proceeds. A
   plain (non-navigating) mark-read click keeps the §2 reconciliation refetch.

Multi-org note: the history list is user-scoped (not org-scoped — correct, notifications
belong to a user). A deep-link to an entity in an org the user is not currently switched
into will land on the destination route, which enforces its own permission gate. This is an
accepted, documented limitation (no new exposure; the destination shows its standard
error); org-aware routing is out of scope here.

### 5. Shared components & helpers (DRY)

- **`frontend/src/lib/schemas/notifications.ts` (new)** — Zod schemas per
  `.claude/rules/frontend-api.md` (API response types are Zod schemas in `lib/schemas/`,
  barrel-exported from `index.ts`): `NotificationSchema`, `NotificationListResponseSchema`,
  `UnreadCountResponseSchema`, each `.passthrough()`; types via `z.infer`
  (`NotificationItem`, …). Replaces the raw `interface` blocks currently inside
  `NotificationBell.svelte`. Added to `schemas/index.ts`.
- **`frontend/src/lib/notifications.ts` (new)** — view helpers only (no types, no
  `timeAgo`):
  - `eventIcon(eventType)` → a **lucide-svelte** icon component (the rest of the app uses
    lucide; the existing Unicode glyphs are replaced as part of this extraction).
  - `notificationHref(entityType, entityId)` — the Gap 4 resolver.
  - `BELL_LIMIT = 20`, `HISTORY_PAGE_SIZE = 25` constants.
- **`timeAgo` is reused** from the existing `frontend/src/lib/utils.ts` (canonical copy;
  already used by `VersionHistoryDrawer` and `routes/+page.svelte`). The local copy in
  `NotificationBell.svelte` is deleted — no third implementation.
- **`frontend/src/lib/components/notifications/NotificationRow.svelte` (new)** — shared
  presentational row. Props: `item: NotificationItem`, `compact: boolean`,
  `onSelect: (item: NotificationItem) => void`.
  - `compact` (bell dropdown, `w-80`): tight padding, `line-clamp-2` message, inline
    relative time, unread dot.
  - non-compact (history page, full width): roomier padding, unread rows get a
    `border-l-2 border-primary` left accent (the small dot is lost at full width).
  - Renders as `<a href={notificationHref(...)}>` when a deep-link resolves (right-click /
    open-in-new-tab / keyboard for free), otherwise `<button>`; `onSelect` still fires for
    mark-read in both cases.
- A new `notifications/` component bucket is introduced; it is added to the bucket list in
  `.claude/rules/conventions.md` in the same change.

`NotificationBell.svelte` stays in `layout/` (global app chrome) and imports the shared
schema, helpers, and row. The history `+page.svelte` does the same.

### 6. Test coverage (Gap 5)

**Frontend (Vitest + `@testing-library/svelte`, jsdom; `api`, `toast`, `goto` mocked):**
- `NotificationBell` — badge renders from `unread-count`; opening the dropdown fetches the
  list; a poll tick refetches the list **and** count while open; `markRead` marks one row +
  decrements the badge; `markAllRead` clears the badge; empty state; **error state** — a
  failed user-initiated call surfaces a toast and triggers a reconciliation refetch; a
  failed background poll does **not** toast; a stale (out-of-sequence) response does not
  clobber fresher state.
- `notifications.ts` — `notificationHref` for each known type, unknown type → `null`,
  falsy / malformed `entityId` → `null`; `eventIcon` returns a component for known and
  unknown event types.
- History `+page.svelte` — initial load; `Next`/`Prev` updates `?offset` and refetches;
  `Mark all read`; empty state; loading state.
- `NotificationRow` — compact vs non-compact rendering; renders `<a>` when a href resolves,
  `<button>` otherwise; `onSelect` fires on click.
- Backend `schemas/notifications.ts` Zod parsing is covered implicitly by the component
  tests' mocked responses.

**Backend (pytest, extend `tests/unit/test_notifications.py`):**
- `dispatch_event` — fans out to org-level channels (broadcast message) and to each
  recipient's user-level channels (personal message); one `NotificationDelivery` per
  subscribed channel; a channel with no matching enabled subscription receives nothing; an
  event with zero subscribed channels creates zero deliveries and does not error.
- `retry_pending` — asserts the **observed** contract of `_execute_send`
  (`attempts` incremented, then `attempts < MAX_RETRIES` → `RETRYING` with `next_retry_at`
  from `RETRY_BACKOFF[attempts-1]`, else `FAILED`; `PermanentError` → `FAILED` immediately;
  disabled/deleted channel → `FAILED`). A code comment and the follow-up task (see Risks)
  record that `RETRY_BACKOFF[2]` is currently unreachable.
- `purge_read_notifications` — deletes read notifications older than the cutoff; keeps
  unread rows of any age and read rows inside the window; returns the exact count; chunking
  works across >500 eligible rows; `older_than_days <= 0` is a no-op returning `0`; the
  cutoff comparison succeeds against an aware-UTC `read_at`. A **schema-contract** test
  artificially links a `RETRYING` delivery to a notification (production never does — the
  dispatcher leaves `notification_id` NULL) and asserts the `ON DELETE SET NULL` FK holds if
  the two are ever linked.

## Architecture / data flow

```
30s tick / visibilitychange ─► dropdown open? ─yes─► GET /notifications/?limit=20
                                                  ├─► GET /notifications/unread-count
                                              ─no──► GET /notifications/unread-count
   (each list fetch tagged with a sequence number; stale responses discarded)

click row ─► (if unread) optimistic read + PUT /notifications/{id}/read
          └► notificationHref(type,id) ─► goto(route)   [bell also closes dropdown]
             mark-read failure: toast; refetch only for non-navigating clicks

/notifications?offset=N ─► GET /notifications/?include_total=true&limit=25&offset=N
                        ─► page slice + total ─► X–Y of N + Prev/Next

recovery loop tick ─► _retry_pending_deliveries()                  (TD-0091a, unchanged)
                   └► _purge_old_notifications()  ── throttled to ≤1/24h ──►
                          purge_read_notifications(): chunked DELETE of old read rows
```

## Files

**Backend**
- `app/core/config.py` — add `notification_retention_days` setting.
- `app/models/notifications.py` — add the `ix_notif_read_at` partial index to
  `Notification.__table_args__`.
- `app/services/core/notifications/retention.py` — **new**: `purge_read_notifications`.
- `app/api/endpoints/notifications.py` — add `include_total` to `list_notifications`.
- `app/main.py` — add the throttled `_purge_old_notifications()` step to `_recovery_loop`.
- `alembic/versions/<rev>_*.py` — **new**: `CREATE INDEX CONCURRENTLY ix_notif_read_at`.
- `tests/unit/test_notifications.py` — extend with dispatch/retry/purge tests.

**Frontend**
- `src/lib/schemas/notifications.ts` — **new**: Zod schemas + types; add to `index.ts`.
- `src/lib/notifications.ts` — **new**: `eventIcon`, `notificationHref`, limit constants.
- `src/lib/components/notifications/NotificationRow.svelte` — **new**: shared row.
- `src/lib/components/layout/NotificationBell.svelte` — smarter poll + concurrency guard,
  error handling, deep-link, "View all" link; use shared schema/helpers/row; drop the
  local `timeAgo`.
- `src/routes/notifications/+page.svelte` — **new**: history page.
- `src/lib/notifications.test.ts`, `NotificationRow.test.ts`,
  `src/lib/components/layout/NotificationBell.test.ts`,
  `src/routes/notifications/page.test.ts` — **new** test files.

**Docs / rules** (step 8 of implement-task)
- `.claude/rules/conventions.md` — add the `notifications/` component bucket.
- `CLAUDE.md` — document `BATCHRITE_NOTIFICATION_RETENTION_DAYS` (incl. `<= 0` = disabled).

## Validation tier

- **Deep-link / mark-read / error toasts** — T1 (backend is the authority; the UI reflects
  API results). No preflight predicate to mirror.
- **Retention** — backend-only background sweep; no UI surface.

No new stable backend error codes are required.

## Risks

- **Dispatcher `MAX_RETRIES` off-by-one.** `_execute_send` increments `attempts` then tests
  `attempts < MAX_RETRIES` (=3), so a delivery is sent at most 3 times and `RETRY_BACKOFF[2]`
  (the 600 s entry) is never used — only 2 retries occur despite the `MAX_RETRIES = 3`
  naming. This is pre-existing dispatcher behavior, not introduced here. TD-0091b **tests
  the observed contract** and routes the discrepancy to a new TECH_DEBT task via `/add_task`
  rather than changing retry semantics inside a test-coverage ticket.
- **Toast spam on a flaky connection.** Mitigated — only user-initiated failures toast;
  background polls log silently.
- **First-run purge on a large backlog.** Mitigated by chunked 500-row deletes (bounded
  locks/WAL), the `ix_notif_read_at` partial index (index scan, not seq scan), and the
  ≤1/24 h throttle.
- **Purge vs. delivery-retry interaction.** Purge runs after `_retry_pending_deliveries`
  within a tick; chunked deletes keep `ON DELETE SET NULL` cascade locks brief; the lock
  order (DELETE parent → cascade child) is consistent, so no deadlock with a concurrent
  retry. Covered by a test.
- **Multi-org deep-link 403.** A notification can deep-link to an entity in another org;
  the destination route gates it. Accepted, documented (§4).
- **`goto` during an in-flight mark-read.** The PUT is initiated before `goto`; failure is
  toast-only on navigating clicks (no refetch into an unmounting component). The history
  page additionally carries an `onDestroy` guard so a page-load fetch resolving after a
  deep-link navigation cannot write `$state` on the unmounted component.
- **Interrupted `CREATE INDEX CONCURRENTLY` leaves an INVALID index.** `CONCURRENTLY` is
  non-transactional; an OOM-kill / `statement_timeout` / cancel mid-build leaves a leftover
  INVALID `ix_notif_read_at`. The migration's `IF NOT EXISTS` then matches that bad index by
  name on re-run, so the migration "succeeds" while the planner ignores the index and the
  sweep predicate silently falls back to a sequential scan. Mitigated by an operator note in
  the plan (Task 2): check `pg_index.indisvalid` and `DROP INDEX CONCURRENTLY` a bad index
  before re-running the migration.
- **Retention misconfiguration causes irreversible data loss.** The sweep is a hard delete
  with no soft-delete and no undo. A too-small `BATCHRITE_NOTIFICATION_RETENTION_DAYS`
  (e.g. a stray `1`) destroys recent history on the first sweep. Mitigated by a pre-deploy
  checklist in the plan (Operational Notes): confirm the resolved value and pre-count the
  first-sweep blast radius before the recovery loop's first tick; `0` ships the feature with
  the sweep dormant.
- **Per-process purge throttle.** `_last_notification_purge_at` is a module global, so the
  ≤1/24 h throttle is per worker/pod and resets on every restart — a multi-worker
  deployment runs one sweep per worker per day, not one globally. The sweep is idempotent so
  this is safe, just not globally minimal. A distributed throttle lock is routed to a
  follow-up task.

## Review-panel amendments (2026-05-21)

The 2b review panel (adversarial-risk-auditor, production-ops-reviewer, dry-reuse-auditor,
db-scalability-reviewer, uiux-design-reviewer) produced the following changes to the
original spec:

- **Badge accuracy** — badge is now always sourced from `unread-count`, never derived from
  the `limit=20` list slice (would undercount >20-unread users). [adversarial]
- **Concurrency guard** — added a request-sequence guard so stale list responses can't
  clobber fresh state; added a `visibilitychange` refetch for backgrounded tablet tabs.
  [adversarial]
- **Retention indexing** — added the `ix_notif_read_at` partial index (model + a
  `CREATE INDEX CONCURRENTLY` migration); the spec previously claimed "no migration".
  [db-scalability]
- **Chunked purge** — the DELETE is now batched (500/chunk, commit per chunk) instead of one
  unbounded statement. [db-scalability, adversarial]
- **Purge cadence** — throttled to ≤1/24 h via a last-run guard in `main.py`; ordered after
  the delivery-retry sweep. [production-ops, adversarial]
- **Purge observability** — added a mandatory success-path `INFO` log (count + window) and a
  disabled-state log. [production-ops]
- **GLP decision** — added an explicit Decisions row accepting 90-day hard-delete of the
  inbox view, with `AuditLog` / `notification_deliveries` as the durable record. [production-ops]
- **`COUNT(*)` cost** — added `include_total` to `list_notifications`; the bell omits it.
  [db-scalability]
- **`timeAgo` reuse** — reuse `lib/utils.ts:timeAgo`; do not create a third copy.
  [dry-reuse]
- **Zod schemas** — notification API types move to `lib/schemas/notifications.ts` as Zod
  schemas per `frontend-api.md`, not raw interfaces in a helper module. [dry-reuse]
- **`NotificationRow` layout variants** — added a `compact` prop so one component works in
  both the `w-80` dropdown and the full-width history page; rows render as `<a>` when a
  deep-link resolves. [uiux]
- **History `offset` in the URL** — paging uses `?offset=N` so browser back/forward
  restores position. [uiux]
- **Shared UI primitives** — history page must use `EmptyState` and `LoadingSpinner`; the
  "View all" link is a `DropdownMenu.Item` wrapping `<a>`. [uiux]
- **lucide icons** — `eventIcon` returns lucide components, replacing the Unicode glyphs, to
  match app-wide iconography. [uiux]
- **Deep-link click semantics** — PUT initiated before `goto`; navigating-click failures are
  toast-only (no refetch); already-read rows still navigate. [adversarial, uiux]
- **`markAllRead` on the history page** — refetch the current page on success too (the
  action is server-wide; other pages go stale). [adversarial]
- **Retry-test honesty** — the `retry_pending` tests assert observed behavior; the
  `MAX_RETRIES` off-by-one is routed to a follow-up task, not silently pinned. [adversarial]

Deferred to follow-up tasks (via `/add_task`, not implemented here): the dispatcher
`MAX_RETRIES`/`RETRY_BACKOFF` off-by-one fix; an ops runbook entry for "user reports missing
notification history".

### Plan-review (2d) corrections back-ported to this spec

The implementation-plan review panel (step 2d) found that this spec's original GLP /
delivery-FK rationale was inaccurate: it described `notification_deliveries` as surviving a
purge "with a NULL FK as dispatch evidence", implying deliveries are linked children of
inbox rows. Verified against `main` — the dispatcher leaves `notification_id` NULL, so
deliveries are an **orthogonal** audit trail the purge never touches. The `Delivery FK on
purge` and `GLP / audit implication` Decisions rows, the §3 retention-sweep bullet, and the
§6 delivery-survival test description were corrected accordingly. Three Risks were added —
interrupted-`CONCURRENTLY` INVALID index, retention-misconfiguration data loss, and the
per-process purge throttle. The full plan-side amendment record lives in the plan's
"Review Panel Amendments (step 2d)" section.
