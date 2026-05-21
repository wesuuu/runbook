# TD-0091a — Notification System Critical Bug Fixes (P0/P1)

**Date:** 2026-05-21
**ClickUp:** TD-0091a (`86e1g9zkz`), subtask of TD-0091 — 2026-05-21 in-app notification system QA audit
**Type:** Tech debt — bug fixes

## Summary

The 2026-05-21 notification-system QA audit found four concrete defects, each with
a known fix. This spec covers the P0/P1 bundle. The remaining audit findings are
tracked separately (TD-0091b — inbox UX/observability/tests; TD-0091c — delivery
model & sequenced email) and are explicitly out of scope here.

This spec was hardened by a subagent review panel (adversarial, production-ops,
DRY/reuse, DB-scalability) — see "Review notes" at the end for what changed.

## Scope

In scope — exactly these four defects, plus the hardening that wiring the
orphaned retry path necessarily entails (see Fix 2):

1. **(P0)** Infinite request loop on Settings → Notifications.
2. **(P1)** Orphaned delivery `retry_pending()` — transient external-delivery
   failures never retry.
3. **(P1)** `PROTOCOL_APPROVAL_REQUESTED` missing from the `NotificationEventType`
   enum.
4. **(P1)** `_get_user_org_id` ignores `selected_org_id` — multi-org users see the
   wrong org's channels/deliveries.

Out of scope: real-time delivery, error surfacing in the inbox, history/retention,
deep-linking, sequenced email, dead event-type cleanup, subscription-gating
consistency. These belong to TD-0091b / TD-0091c. Six smaller follow-ups the
review panel surfaced are listed under "Deferred follow-ups" and routed to new
tickets rather than absorbed here.

## Fix 1 (P0) — Infinite request loop on Settings → Notifications

### Root cause

`frontend/src/routes/settings/+page.svelte:789`:

```js
$effect(() => {
    if (activeTab === 'notifications' && channels.length === 0 && !channelsLoading) {
        loadChannels();
    }
});
```

`loadChannels()` sets `channelsLoading = true`, awaits the API, assigns
`channels = await api.get(...)` (or `channels = []` on error / empty result), then
clears `channelsLoading` in `finally`. For a user with **no channels** the API
returns `[]`: `channels` is reassigned to a fresh empty-array reference and
`channelsLoading` returns to `false`, so the effect's guard
(`channels.length === 0 && !channelsLoading`) is satisfied again and the effect
re-fires — unbounded. The audit observed 753+ `GET /notifications/channels/me`
requests from one page visit; the tab is stuck on "Loading channels…" forever. A
user *with* channels does not loop, because `channels.length` becomes non-zero.

### Fix

Replace the `channels.length`-based guard with a one-shot `channelsLoaded` flag
that the API result never mutates.

- Add `let channelsLoaded = $state(false);` alongside `channels` / `channelsLoading`.
- In `loadChannels()`, set `channelsLoaded = true` in the `finally` block (so it is
  set on both success and error — a failed load does not auto-retry, which also
  prevents the loop under a persistently-failing API).
- Change the `$effect` guard to
  `activeTab === 'notifications' && !channelsLoaded && !channelsLoading`.
- The Notifications tab `onclick` (line ~847) inlines a redundant
  `loadChannels()` call. Changing `activeTab` already fires the effect for both
  URL navigation and click navigation, so the inline call is duplicate logic.
  Simplify the handler to `onclick={() => setTab('notifications')}`.

### Why the fix terminates

The effect reads `activeTab`, `channelsLoaded`, `channelsLoading`. During
`loadChannels()`: `channelsLoading = true` → effect re-runs, guard fails (no call);
the `channels` assignment is no longer read by the effect, so it triggers no
re-run; `finally` sets `channelsLoading = false` **and** `channelsLoaded = true`
→ effect re-runs, `!channelsLoaded` is false → no call. Steady state reached after
exactly one load.

### One-shot latch — org switching

`channelsLoaded` is a one-shot latch with no reset path. This is correct here:
`GET /notifications/channels/me` is served by `list_user_channels`, which filters
by `current_user.id` only — personal channels are **user-scoped, not
org-scoped**. Switching the active org while the settings page is mounted
therefore does not change this tab's data, so no reload is needed and the latch
intentionally stays set. (If an org-scoped surface is later added to this tab, it
must not rely on this latch.) `addChannel` / `deleteChannel` /
`toggleChannelEnabled` already call `loadChannels()` directly to refresh after a
mutation; the latch does not block those.

### Validation tier

T1 (backend has no role here; this is a pure client-side reactivity bug). No
preflight or reactive-UI surface required.

### Known limitation (deferred)

`loadChannels()`'s `catch` swallows the error and shows a false "No channels
configured yet." With the `channelsLoaded` flag a failed load is now also
one-shot. Surfacing load errors is explicitly TD-0091b's scope and is not
addressed here.

## Fix 2 (P1) — Orphaned delivery `retry_pending()`

### Root cause

`backend/app/services/core/notifications/dispatcher.py` defines
`retry_pending(db)` — it selects `NotificationDelivery` rows in `RETRYING` status
whose `next_retry_at <= now` and re-sends them. Nothing calls it. `_execute_send`
writes `RETRYING` status, `next_retry_at`, and a backoff for `TransientError`s,
but no scheduler consumes them, so transient external-delivery failures (network
blips to Slack/webhook/etc.) are effectively permanent.

### Fix — wiring

Wire `retry_pending()` into the existing recovery infrastructure in
`backend/app/main.py`, mirroring the `BackgroundJob` recovery pattern.

- Add `_retry_pending_deliveries()` to `main.py`. It uses
  `async with AsyncSessionLocal() as session:` (the shared module pool, with the
  context manager's automatic rollback-on-exception), calls `retry_pending(session)`,
  then `await session.commit()`. `AsyncSessionLocal` — not a private
  `create_async_engine` — is the right choice for a sweep that runs at
  steady-state frequency: no per-sweep engine create/dispose churn, and the
  `async with` exception semantics guarantee no partial state is committed if a
  SQLAlchemy-level error escapes. (Consolidating the two older sweeps —
  `_recover_stalled_jobs` / `_recover_stalled_documents`, which still spin
  private engines — onto the shared pool is a deferred follow-up.)
- `_retry_pending_deliveries()` logs at `INFO`: `retry_pending` returns the count
  of deliveries it retried; log `"Delivery retry sweep: retried %d deliveries"`
  with that count. (A zero count is fine to log too — it confirms the sweep ran.)
- In `_recovery_loop()`, add a third independent sweep calling
  `_retry_pending_deliveries()`, wrapped in its own `try/except` logging exactly
  `"Recovery loop: delivery retry sweep failed"` (consistent prefix with the
  existing `"Recovery loop: job sweep failed"` / `"... doc sweep failed"`).
- **No before-`yield` startup sweep.** `retry_pending` does outbound network I/O
  in a loop; running it before `yield` in `lifespan` would block the app from
  accepting traffic on a slow/unreachable channel. `_recovery_loop()` is started
  as a background task and runs its first sweep immediately (before its first
  `sleep`), so first-retry latency after boot is unaffected. Job/document
  recovery keep their existing before-`yield` startup sweeps (DB-only, fast) —
  only the network-bound retry sweep is loop-only.

### Fix — hardening `retry_pending` itself

Wiring an orphaned function into a loop that runs every 90s makes its latent
defects live. Three are fixed here, in `dispatcher.py`:

1. **N+1 channel fetch.** `retry_pending` currently does
   `await db.get(NotificationChannel, delivery.channel_id)` per row — up to 50
   point lookups per sweep against a fresh session. Replace with
   `selectinload(NotificationDelivery.channel)` on the deliveries query (the
   `channel` relationship and `selectinload` import already exist), collapsing
   it to two index scans.
2. **Non-deterministic / unfair drain.** The select has no `ORDER BY`; with a
   backlog over the `.limit(50)` cap, PostgreSQL may return any 50 rows. Add
   `ORDER BY next_retry_at` so the most-overdue deliveries drain first. The
   composite index `ix_notif_del_status (status, next_retry_at)` already covers
   this sort within the `status = 'RETRYING'` range — no new index.
3. **Batch poisoning.** The per-row loop has no error isolation. If one row
   raises an *uncaught* exception — e.g. `get_channel()` raises `ValueError` for
   a `channel_type` no longer in the registry (`ValueError` is **not** caught by
   `_execute_send`, which only catches `TransientError`/`PermanentError`/
   `Exception` *inside the send*) — the exception escapes `retry_pending`, the
   wrapper's `commit()` is skipped, and **already-completed re-sends in the same
   batch are rolled back**. The next sweep re-selects those still-`RETRYING` rows
   and re-sends them → duplicate external messages. Fix: wrap each delivery's
   processing in `retry_pending`'s loop in its own `try/except` that, on an
   unexpected exception, marks that one delivery `FAILED` with a `status_detail`
   and continues. With per-row isolation no exception escapes the loop, so the
   single end-of-sweep `commit()` is safe.

### Cadence and effective retry count

`_recovery_loop()` runs every `recovery_interval_seconds` (default 90). The
backoff schedule is **`[30, 120]s` — two retries**, not three: `_execute_send`
indexes `RETRY_BACKOFF[attempts - 1]` only while `attempts < MAX_RETRIES (3)`, so
only `attempts ∈ {1, 2}` schedule a retry and `RETRY_BACKOFF[2] = 600` is
currently unreachable dead code. Worst-case extra latency before a due retry is
one sweep interval (~90s) — acceptable for best-effort external delivery. The
off-by-one (the unreachable `600` tier) is a pre-existing quirk; correcting the
retry *count* is a behaviour change beyond "wire it up" and is routed to a
follow-up ticket, not changed here.

### Operating-volume assumption and monitoring

At `.limit(50)` per sweep and a 90s interval the loop drains ~33 deliveries/min.
This is sufficient when sustained transient-failure volume stays well below that;
a larger sustained failure rate (e.g. a long external-channel outage fanning out
to many subscribers) lets the `RETRYING` backlog outpace the drain. That is
acceptable for best-effort delivery — deliveries still flip to `FAILED` after
their retries — but the operational signal for "retry backlog is unhealthy" is a
count of `notification_deliveries` rows in `RETRYING` whose `next_retry_at` is
well in the past. A dead-letter queue or alerting on that count is out of scope
here; raising the limit or adding `FOR UPDATE SKIP LOCKED` is a deferred
follow-up.

### Recovery-loop knob

`_recovery_loop()` returns early when `recovery_interval_seconds <= 0`. With the
retry sweep loop-only (no startup sweep), setting the knob to `0` now disables
**delivery retries** as well as job/document recovery. This is intentional and
consistent — one knob, one loop — but the config field's docstring/comment in
`backend/app/core/config.py` will be updated to say so.

### Concurrency note

`retry_pending()` selects with `.limit(50)` and no row locking. The app runs one
recovery loop per worker; a multi-worker deployment could double-send a delivery.
This pre-existing characteristic is unchanged here — external delivery is
best-effort and channel adapters should tolerate redelivery. `FOR UPDATE SKIP
LOCKED` is a deferred follow-up.

## Fix 3 (P1) — `PROTOCOL_APPROVAL_REQUESTED` missing from enum

### Root cause

`templates.py`'s `TEMPLATES` registry has 14 entries;
`NotificationEventType` in `backend/app/models/notifications.py` has 13 — it is
missing `PROTOCOL_APPROVAL_REQUESTED`. The event is emitted at
`protocol_versions.py:456` and the in-app notification renders (it goes through
`TEMPLATES`), but `_validate_event_type` (used by `create_subscription`) rejects
the value, so no external channel can subscribe to protocol-approval-requested
events.

### Fix

- Add `PROTOCOL_APPROVAL_REQUESTED = "PROTOCOL_APPROVAL_REQUESTED"` to
  `NotificationEventType`, positioned after `PROTOCOL_REVERTED`.
- **No migration.** The `event_type` columns on `NotificationSubscription`,
  `Notification`, and `NotificationDelivery` are `String`, not a Postgres enum
  type — the enum is a Python-side value set only.
- Strengthen the existing `TestTemplates.test_all_event_types_have_templates`
  test (currently one-directional) into a **bidirectional** assertion:
  `{e.value for e in NotificationEventType}` equals `set(TEMPLATES.keys())`. This
  currently fails in the TEMPLATES→enum direction and will catch future drift
  either way.
- Add `{ value: 'PROTOCOL_APPROVAL_REQUESTED', label: 'Protocol Approval
  Requested' }` to the `EVENT_TYPES` array in
  `frontend/src/routes/settings/+page.svelte` (after `PROTOCOL_REVERTED`).
  Without this, the backend would accept the subscription but the UI would never
  render the checkbox — Fix 3's stated goal ("no external channel can subscribe")
  is only met end-to-end with the frontend list updated.

The frontend `EVENT_TYPES` array is *also* missing `PENDING_IMAGE_ANALYSIS`,
`OFFLINE_SYNC_PENDING`, and `OFFLINE_VALUE_DISCREPANCY`. That broader parity gap
is not part of this defect and is routed to a follow-up ticket.

## Fix 4 (P1) — `_get_user_org_id` ignores `selected_org_id`

### Root cause

`backend/app/api/endpoints/notifications.py`:

```python
async def _get_user_org_id(db: AsyncSession, user_id: UUID) -> UUID:
    """Get the user's first org membership. Raises 400 if none."""
    stmt = (
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .limit(1)
    )
    ...
```

It returns the user's *first* membership, ignoring `User.selected_org_id` (the
codebase's standard org-context field — see `.claude/rules/backend-endpoints.md`).
A multi-org user whose active org is not their first membership sees the wrong
org's channels and delivery log.

### Fix

Fix `notifications.py`'s `_get_user_org_id` in place:

- Change the signature from `(db, user_id: UUID)` to `(db, user: User)`. All
  three callers — `create_org_channel`, `list_org_channels`, `list_deliveries` —
  already have `current_user` in scope and pass `current_user.id` today; they
  will pass `current_user`.
- Resolution logic: if `user.selected_org_id` is set **and** an
  `OrganizationMember` row exists for `(user.id, user.selected_org_id)`, return
  `selected_org_id`. Otherwise fall back to the first membership, ordered
  `OrganizationMember.created_at` for determinism (the existing `.limit(1)` has no
  `ORDER BY`). Raise `HTTPException(400, ...)` if the user belongs to no
  organization.
- The membership re-check is required, not cosmetic: `list_org_channels` queries
  channels by `org_id` with **no** downstream membership gate (unlike
  `create_org_channel` and `list_deliveries`, which call `_require_org_admin`).
  Blindly trusting a stale `selected_org_id` could leak another org's channel
  list. Verifying membership preserves the invariant the first-membership query
  gave for free. The check matches the existing `_require_org_member` helper — it
  does **not** filter on `OrganizationMember.archived`; archived-membership
  handling is pre-existing behaviour and is not changed here.

### Behaviour change across all three callers

This is a deliberate behaviour change for multi-org users on every endpoint that
calls the helper, and must be tested as such:

- `create_org_channel` — a new org-level channel is created under the user's
  *selected* org instead of their first membership. `_require_org_admin` still
  re-validates admin rights on that org.
- `list_org_channels` — lists the selected org's channels.
- `list_deliveries` — a multi-org **admin** now sees the *selected* org's
  delivery audit log instead of their first membership's. `_require_org_admin`
  still gates access.

### Parallel copy in `library.py` — deferred

`backend/app/api/endpoints/library.py` has its own private `_get_user_org_id`
(signature `(user, db)`, raises 403, ~9 call sites) with the **identical**
`selected_org_id` bug. Unifying both into one shared org-resolution helper — and
thereby fixing `library.py` too — is the right end state, but it would change
behaviour across ~9 unrelated `library.py` endpoints and is beyond TD-0091a's
scope. TD-0091a fixes `notifications.py` in place; the unification + `library.py`
fix is routed to a follow-up ticket. The two copies remain (within the
"duplicated twice" tolerance) until that ticket lands.

### Cost

One extra point-lookup on `OrganizationMember`, covered by the `uq_org_member`
unique-constraint index on `(user_id, organization_id)`, only when
`selected_org_id` is set. The fallback query is covered by the leading
`user_id` column of the same index. Negligible; these endpoints are
low-frequency (settings/admin surfaces, not hot paths).

### Validation tier

T1 — server-side org resolution; the user neither anticipates nor controls when
it fires.

## Testing

### Backend — unit (`backend/tests/unit/test_notifications.py`)

- **Enum↔TEMPLATES sync (Fix 3):** rewrite `test_all_event_types_have_templates`
  as a bidirectional set-equality assertion. Red before the enum value is added,
  green after.
- **`retry_pending` happy path (Fix 2):** create a `RETRYING`
  `NotificationDelivery` with `next_retry_at` in the past, run `retry_pending(db)`,
  assert it returns `1` and the delivery transitions to `SENT`.
- **`retry_pending` not-yet-due:** a `RETRYING` delivery with `next_retry_at` in
  the future is not picked up (returns `0`, status unchanged).
- **`retry_pending` failure paths:** the existing `FakeChannel` always succeeds,
  so add a configurable failing channel test double (raises `TransientError` /
  `PermanentError` on demand). Cover: a retry that fails transiently again →
  stays `RETRYING`, `attempts` incremented, `next_retry_at` advanced; a retry on
  its last attempt → `FAILED`; a delivery whose channel is disabled → `FAILED`,
  no send; a delivery whose `channel_type` is unknown (`get_channel` raises
  `ValueError`) → that row is marked `FAILED` and does **not** abort the batch.
- **`retry_pending` batch isolation:** a batch with one poison row plus several
  good rows — assert the good rows still transition to `SENT` and are not
  re-selected on a second `retry_pending` call.

### Backend — integration (`backend/tests/integration/test_notification_api.py`)

- **`selected_org_id` honored (Fix 4):** a user who is a member of two orgs with
  `selected_org_id` pointing at the second org sees the second org's channels via
  `GET /notifications/channels`.
- **`list_deliveries` honors `selected_org_id`:** a multi-org **admin** with
  `selected_org_id` set to the non-first org sees that org's delivery log.
- **Fallback when `selected_org_id` is unset:** a single-org user with
  `selected_org_id = None` resolves to their one membership (regression guard for
  existing single-org fixtures).
- **Stale `selected_org_id`:** `selected_org_id` points at an org the user is not
  a member of → resolution falls back to a real membership; no 403, no leak.
- **`PROTOCOL_APPROVAL_REQUESTED` subscribable (Fix 3):** `POST
  /notifications/channels/{id}/subscriptions` with
  `event_type=PROTOCOL_APPROVAL_REQUESTED` returns 201 (previously 400).

### Frontend — P0 (Fix 1)

Verified via the `/implement-task` browser-QA step:
- A channel-**less** user opens Settings → Notifications both by clicking the tab
  and by direct URL `?tab=notifications`; the `GET /notifications/channels/me`
  request count stays at exactly one and the tab renders "No notification
  channels configured yet."
- A user **with** channels opens the tab via both paths; channels render and the
  request count stays at one.

A dedicated Vitest harness for the 1400-line settings page is not warranted for
this fix; component-level test coverage for notification surfaces is TD-0091b /
TD-0091k scope.

## Files touched

| File | Change |
| --- | --- |
| `frontend/src/routes/settings/+page.svelte` | `channelsLoaded` flag; effect guard; dedupe tab `onclick`; add `PROTOCOL_APPROVAL_REQUESTED` to `EVENT_TYPES` |
| `backend/app/models/notifications.py` | add `PROTOCOL_APPROVAL_REQUESTED` enum value |
| `backend/app/api/endpoints/notifications.py` | `_get_user_org_id(db, user)` honors `selected_org_id`; update 3 callers |
| `backend/app/services/core/notifications/dispatcher.py` | `retry_pending`: `selectinload` channel, `ORDER BY next_retry_at`, per-row error isolation |
| `backend/app/main.py` | `_retry_pending_deliveries()` (shared-pool session, INFO logging); wire into `_recovery_loop()` |
| `backend/app/core/config.py` | docstring/comment: `recovery_interval_seconds <= 0` also disables delivery retries |
| `backend/tests/unit/test_notifications.py` | bidirectional enum↔TEMPLATES test; `retry_pending` happy/failure/batch tests; failing-channel test double |
| `backend/tests/integration/test_notification_api.py` | `selected_org_id` resolution tests; `PROTOCOL_APPROVAL_REQUESTED` subscription test |

No database migration. No new dependencies. No new config or feature flags.

## Risks

- **Fix 1:** the effect must read only `activeTab` / `channelsLoaded` /
  `channelsLoading` — never `channels` — or the loop returns.
- **Fix 2:** an exception inside the new sweep must not break the job/document
  sweeps — enforced by an independent `try/except`. Per-row isolation inside
  `retry_pending` must catch *all* unexpected exceptions (including
  `get_channel`'s `ValueError`) so the batch `commit()` is reached and prior
  re-sends are not rolled back. `selectinload` must not change which rows the
  query returns (it does not — it only changes how the `channel` relationship is
  loaded).
- **Fix 4:** the signature change to `_get_user_org_id` touches all three call
  sites in the same change; it is a module-private helper, so there are no
  external callers. The behaviour change is intentional and covered by tests.

## Deferred follow-ups (routed to new tickets, not dropped)

1. Unify the two `_get_user_org_id` copies (`notifications.py` + `library.py`)
   into one shared org-resolution helper; fixes `library.py`'s identical
   `selected_org_id` multi-org bug across its ~9 call sites.
2. `RETRY_BACKOFF` / `MAX_RETRIES` off-by-one — `RETRY_BACKOFF[2] = 600` is
   unreachable; deliveries get two retries, not three. Decide intended count.
3. Frontend `EVENT_TYPES` parity — also missing `PENDING_IMAGE_ANALYSIS`,
   `OFFLINE_SYNC_PENDING`, `OFFLINE_VALUE_DISCREPANCY`.
4. `FOR UPDATE SKIP LOCKED` on `retry_pending`'s select for multi-worker
   double-send safety; consider raising `.limit(50)` / alerting on `RETRYING`
   backlog depth.
5. Degraded retry message content — retries send `FormattedMessage(title="(retry)",
   body="")` because original content is not persisted on `NotificationDelivery`;
   needs a runbook note or content fix (TD-0091c-adjacent).
6. Consolidate `main.py`'s recovery sweeps onto the shared `AsyncSessionLocal`
   pool — `_recover_stalled_jobs` / `_recover_stalled_documents` still spin
   private per-call engines.

## Review notes

Applied from the subagent review panel (adversarial, production-ops, DRY/reuse,
DB-scalability):

- **Fix 2 substantially hardened.** Added: `selectinload` to kill the per-row
  N+1 channel fetch (DB-scalability BLOCKER); `ORDER BY next_retry_at` for fair
  drain; per-row `try/except` inside `retry_pending` to stop a poison row
  (`get_channel` `ValueError`) from rolling back a whole batch and causing
  duplicate sends (adversarial HIGH). Wrapper now uses `async with
  AsyncSessionLocal()` for auto-rollback and shared-pool reuse instead of a
  private engine (production-ops / DRY); logs retry counts at `INFO`
  (production-ops HIGH). Dropped the before-`yield` startup sweep — it would
  block boot on network I/O (adversarial); the loop's first iteration covers it.
  Corrected the Cadence section: effective backoff is `[30, 120]s` / two
  retries, with `600` dead code (adversarial HIGH). Documented the `.limit(50)`
  operating-volume assumption and the `recovery_interval_seconds <= 0`
  implication (production-ops).
- **Fix 1.** Documented that `/channels/me` is user-scoped, so the one-shot
  `channelsLoaded` latch is correct across org switches (adversarial MEDIUM).
  Added QA coverage for a user *with* channels via both nav paths.
- **Fix 3.** Added the frontend `EVENT_TYPES` entry — the backend fix alone left
  the event unsubscribable in the UI (adversarial LOW). Added an integration
  test on `create_subscription`.
- **Fix 4.** Explicitly documented the behaviour change on all three callers,
  including `list_deliveries` for multi-org admins (adversarial MEDIUM). Added
  `ORDER BY created_at` to the fallback for determinism. Corrected the index name
  (`uq_org_member`, not `ix_org_member`). Noted the parallel `library.py` copy
  and routed its unification to a follow-up (DRY/reuse BLOCKER — kept TD-0091a
  in scope rather than absorbing `library.py`'s ~9 call sites).
- **Testing expanded** with a failing-channel test double and retry
  failure/batch-isolation cases (adversarial MEDIUM — `FakeChannel` cannot fail).
- Six smaller findings routed to "Deferred follow-ups" above rather than dropped.
