# TD-0082 — Gate Offline/PWA Behind a Feature Flag

**Status:** Approved
**Date:** 2026-04-29
**ClickUp:** TD-0082 ([86e157h8d](https://app.clickup.com/t/86e157h8d))

## Goal

Disable the offline/PWA stack at runtime via two env vars, leaving all existing
code in the tree. Default is **off**. Re-enabling later is a config change only,
no code edits required.

## Non-Goals

- Removing or refactoring offline code.
- Auditing IndexedDB schema migrations or sync-conflict resolution (deferred to
  the future-work item on the ticket).
- Adding a generic feature-flag framework. One bool, one place.

## Backend

### Settings

`backend/app/core/config.py` — add to `Settings`:

```python
offline_enabled: bool = False  # env: BATCHRITE_OFFLINE_ENABLED
```

Pydantic-Settings already prefixes `BATCHRITE_` and lowercases field names, so
no extra config is needed.

### Router gating

`backend/app/main.py` — wrap the existing registrations:

```python
if settings.offline_enabled:
    app.include_router(offline.router, tags=["offline"])
    app.include_router(sync.router, tags=["sync"])
```

Imports stay at the top of the file. Only registration is gated. With the flag
off, `GET /offline/...` and `GET /sync/...` return 404.

We do **not** create `backend/app/core/feature_flags.py`. `Settings` is the
existing module the ticket alludes to, and a single-bool wrapper adds nothing.

## Frontend

### Module

New file `frontend/src/lib/feature-flags.ts`:

```ts
export const OFFLINE_ENABLED: boolean =
    import.meta.env.VITE_OFFLINE_ENABLED === 'true';
```

Strict string compare — Vite passes env vars as strings, and we want any value
other than the literal `'true'` to default to off.

### UI gates

Wrap component mounts in `{#if OFFLINE_ENABLED}` in:

- `routes/+layout.svelte` — `<ConnectivityBanner/>`, `<ExpiryWarningBanner/>`,
  any PWA install prompt.
- `routes/runs/[id]/+page.svelte` — banners and `<GoOfflineDialog/>`.
- `routes/field/+page.svelte` — banners and dialog.
- `lib/components/field-mode/FieldModeRoleWizard.svelte` — "Go Offline" trigger.
- `lib/components/run/RoleAssignmentPanel.svelte` — "Go Offline" trigger.

### Boot/init guards

- `lib/pwa.svelte.ts` — early-return at the top of any init function. No
  service-worker registration, no `beforeinstallprompt` listener.
- `lib/sync-manager.ts` — early-return on init / start-polling. No timers, no
  queue setup.
- `lib/offline-db.ts` — early-return on init / open. No `indexedDB.open`.
- `lib/field-mode.svelte.ts` — gate the "go offline" entry path. Defense in
  depth (callers are hidden by the UI gate above).
- `lib/crypto.ts` — pure helpers, no top-level side effects. Leave alone after
  verifying.

### Acceptance evidence (frontend, flag off)

- DevTools network tab: zero requests to `/offline/*` or `/sync/*`.
- DevTools application tab: no service worker registered, no IndexedDB
  databases opened by the app.
- Connectivity banner, expiry banner, "Go Offline" dialog and triggers do not
  appear on any route.

## Documentation

- `backend/.env.example` — add `BATCHRITE_OFFLINE_ENABLED=false` with a one-line
  comment.
- New `frontend/.env.example` — add `VITE_OFFLINE_ENABLED=false` with a
  one-line comment.
- README — short "Feature flags" subsection naming both vars and noting that
  flipping them is the only change required to re-enable.

## Tests

### Backend (TDD, required)

`backend/tests/integration/test_offline_feature_flag.py` (new):

- With `BATCHRITE_OFFLINE_ENABLED=false`, build a fresh app and assert
  `/offline/...` and `/sync/...` return 404.
- With `BATCHRITE_OFFLINE_ENABLED=true`, assert those routes are registered
  (status is anything except 404 — 401/422/200 all acceptable).

The test uses a per-test app factory (or env-var monkeypatch + `importlib.reload`
on `app.main`) so router registration runs under the desired flag state.

### Frontend

UI behavior is verified manually in the browser via the qa-verify agent against
both flag states:

1. Default (`VITE_OFFLINE_ENABLED` unset/false): no offline UI, no
   offline/sync network calls, no SW, no IndexedDB.
2. Flipped (`VITE_OFFLINE_ENABLED=true`): all current offline behavior works.

No vitest coverage on `feature-flags.ts` — it's a one-line string compare and
the browser pass exercises both branches.

## Risks

- **Indirect imports.** A non-offline code path could import something from
  `offline-db.ts` and trigger evaluation of top-level side effects. Mitigation:
  grep for cross-module imports during implementation, push any side effects
  into init functions if found.
- **Service-worker carry-over.** Users who already have a registered SW from a
  prior build won't lose it just because the flag is off. Out of scope here —
  this flag is for fresh installs / pre-prod gating.

## Rollout

1. Land the flag with default off.
2. Local dev: keep flag off by default. Devs working on offline flip it on
   in their `.env`.
3. Re-enable later by flipping the two env vars. No code changes.
