# TD-0082 Offline Feature Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate the entire offline/PWA stack (backend routers, frontend UI, frontend boot init) behind two env vars so the app can ship with offline disabled and re-enable later via config alone.

**Architecture:** Backend `Settings.offline_enabled` (Pydantic) gates `include_router` calls in `app/main.py`. Frontend `feature-flags.ts` reads `VITE_OFFLINE_ENABLED` and exposes a typed `OFFLINE_ENABLED` constant; UI mounts wrap in `{#if OFFLINE_ENABLED}` and module init functions early-return when off.

**Tech Stack:** FastAPI, Pydantic-Settings, Svelte 5 (Runes), Vite, pytest, @xyflow/svelte (untouched).

**Spec:** `docs/superpowers/specs/2026-04-29-td-0082-offline-feature-flag-design.md`

---

## File Map

**Backend**
- Modify: `backend/app/core/config.py` — add `offline_enabled: bool = False`.
- Modify: `backend/app/main.py` — extract `_register_offline_routers(app, settings)` helper and gate it.
- Create: `backend/tests/integration/test_offline_feature_flag.py` — register-routes-by-flag tests.
- Modify: `backend/.env.example` — document `BATCHRITE_OFFLINE_ENABLED`.

**Frontend**
- Create: `frontend/src/lib/feature-flags.ts` — exports `OFFLINE_ENABLED`.
- Create: `frontend/.env.example` — document `VITE_OFFLINE_ENABLED`.
- Modify: `frontend/src/lib/pwa.svelte.ts` — early-return on init when off.
- Modify: `frontend/src/lib/sync-manager.ts` — early-return on init when off.
- Modify: `frontend/src/lib/offline-db.ts` — early-return on init/open when off.
- Modify: `frontend/src/lib/field-mode.svelte.ts` — gate "go offline" entry path.
- Modify: `frontend/src/routes/+layout.svelte` — gate banners + install prompt.
- Modify: `frontend/src/routes/+page.svelte` — gate any offline UI present.
- Modify: `frontend/src/routes/runs/[id]/+page.svelte` — gate banners + GoOfflineDialog.
- Modify: `frontend/src/routes/field/+page.svelte` — gate banners + GoOfflineDialog.
- Modify: `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte` — gate "Go Offline" trigger.
- Modify: `frontend/src/lib/components/run/RoleAssignmentPanel.svelte` — gate "Go Offline" trigger.

**Docs**
- Modify: `README.md` — Feature flags subsection.

---

## Task 1: Backend — `Settings.offline_enabled`

**Files:**
- Modify: `backend/app/core/config.py:139` (debug field neighborhood)

- [ ] **Step 1: Add the setting**

In `backend/app/core/config.py`, find the field group near `debug: bool = False` and add directly under it:

```python
    # Offline / PWA feature flag (TD-0082).
    # When False (default), offline + sync routers are not registered and the
    # frontend should not attempt to use them.
    offline_enabled: bool = False
```

- [ ] **Step 2: Verify the setting loads**

Run:

```bash
cd backend && source .venv/bin/activate && python -c "from app.core.config import settings; print(settings.offline_enabled)"
```

Expected: `False`

Then verify env override:

```bash
BATCHRITE_OFFLINE_ENABLED=true python -c "from app.core.config import settings; print(settings.offline_enabled)"
```

Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat(td-0082): add offline_enabled setting"
```

---

## Task 2: Backend — Router gating with TDD

**Files:**
- Create: `backend/tests/integration/test_offline_feature_flag.py`
- Modify: `backend/app/main.py:386-387` (the offline + sync include_router calls)

- [ ] **Step 1: Extract a helper in `app/main.py`**

In `backend/app/main.py`, replace these two lines (around line 386-387):

```python
app.include_router(offline.router, tags=["offline"])
app.include_router(sync.router, tags=["sync"])
```

With:

```python
def _register_offline_routers(target_app, current_settings):
    """Register offline/PWA routers iff the feature flag is on (TD-0082)."""
    if current_settings.offline_enabled:
        target_app.include_router(offline.router, tags=["offline"])
        target_app.include_router(sync.router, tags=["sync"])


_register_offline_routers(app, settings)
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/integration/test_offline_feature_flag.py`:

```python
"""TD-0082: verify offline + sync routers are gated by Settings.offline_enabled."""

from fastapi import FastAPI

from app.core.config import Settings
from app.main import _register_offline_routers


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_offline_routers_absent_when_flag_off():
    app = FastAPI()
    _register_offline_routers(app, Settings(offline_enabled=False))
    paths = _route_paths(app)

    assert "/offline/runs/{run_id}/prefetch" not in paths
    assert "/auth/offline-session" not in paths
    assert "/auth/offline-session/{jti}" not in paths
    assert "/sync/offline-queue/{run_id}" not in paths


def test_offline_routers_present_when_flag_on():
    app = FastAPI()
    _register_offline_routers(app, Settings(offline_enabled=True))
    paths = _route_paths(app)

    assert "/offline/runs/{run_id}/prefetch" in paths
    assert "/auth/offline-session" in paths
    assert "/auth/offline-session/{jti}" in paths
    assert "/sync/offline-queue/{run_id}" in paths
```

- [ ] **Step 3: Run tests, expect PASS**

Both tests should pass: the helper from Step 1 already implements the gating. (We
wrote the helper before the test only because the helper exists in `main.py`
which has many other side effects; writing it together is the practical TDD
shape here.)

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_offline_feature_flag.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Spot-check with the live app**

The default `Settings()` has `offline_enabled=False`, so the imported app should
also lack offline routes:

```bash
cd backend && source .venv/bin/activate && python -c "
from app.main import app
paths = {getattr(r, 'path', '') for r in app.routes}
assert '/offline/runs/{run_id}/prefetch' not in paths, 'offline route leaked'
assert '/sync/offline-queue/{run_id}' not in paths, 'sync route leaked'
print('OK: live app has offline routes hidden by default')
"
```

Expected: `OK: live app has offline routes hidden by default`

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/integration/test_offline_feature_flag.py
git commit -m "feat(td-0082): gate offline+sync routers behind offline_enabled"
```

---

## Task 3: Backend — `.env.example`

**Files:**
- Modify: `backend/.env.example`

- [ ] **Step 1: Document the var**

Append to `backend/.env.example` (after the existing `BATCHRITE_SEAT_LIMIT_PRO` line, with a blank line above):

```
# --- Feature flags (TD-0082) ---
# Offline/PWA stack (sync queue, IndexedDB cache, "Go Offline" flow).
# Default: false. Flip to true to re-enable.
BATCHRITE_OFFLINE_ENABLED=false
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env.example
git commit -m "docs(td-0082): document BATCHRITE_OFFLINE_ENABLED in env.example"
```

---

## Task 4: Frontend — `feature-flags.ts`

**Files:**
- Create: `frontend/src/lib/feature-flags.ts`
- Create: `frontend/.env.example`

- [ ] **Step 1: Create the module**

Create `frontend/src/lib/feature-flags.ts`:

```ts
/**
 * Runtime feature flags. Read from Vite env vars at build time. Flags must be
 * cheap to read everywhere — keep this file dependency-free.
 *
 * TD-0082: Offline/PWA stack is gated behind OFFLINE_ENABLED. Default off.
 * Re-enabling means flipping VITE_OFFLINE_ENABLED on the frontend and
 * BATCHRITE_OFFLINE_ENABLED on the backend.
 */

export const OFFLINE_ENABLED: boolean =
    import.meta.env.VITE_OFFLINE_ENABLED === 'true';
```

- [ ] **Step 2: Create frontend env example**

Create `frontend/.env.example`:

```
# Frontend environment variables consumed by Vite.
# Copy to `frontend/.env.local` for local overrides.

# --- Feature flags (TD-0082) ---
# Offline/PWA stack. Default: false. Set to "true" to re-enable.
VITE_OFFLINE_ENABLED=false
```

- [ ] **Step 3: Type-check frontend**

```bash
cd frontend && npm run check
```

Expected: passes (or only pre-existing unrelated warnings).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/feature-flags.ts frontend/.env.example
git commit -m "feat(td-0082): add OFFLINE_ENABLED frontend flag"
```

---

## Task 5: Frontend — Boot/init guards

**Files:**
- Modify: `frontend/src/lib/pwa.svelte.ts:17` (`initConnectivity`)
- Modify: `frontend/src/lib/sync-manager.ts:45,128,157` (`drainQueue`, `initSyncManager`, `syncNow`)
- Modify: `frontend/src/lib/offline-db.ts:53` (`openDb`)
- Modify: `frontend/src/lib/field-mode.svelte.ts:130,172,348` (`activateFieldMode`, `restoreFieldMode`, `initFieldMode`)

- [ ] **Step 1: Add the import to each gated module**

At the top of each of the four files (after existing imports), add:

```ts
import { OFFLINE_ENABLED } from '$lib/feature-flags';
```

- [ ] **Step 2: Guard `pwa.svelte.ts:initConnectivity`**

In `frontend/src/lib/pwa.svelte.ts`, modify `initConnectivity` so its body
starts with the flag check. The existing function adds `online`/`offline`
window listeners — we want to skip those when the flag is off:

```ts
export function initConnectivity(): void {
    if (!OFFLINE_ENABLED) return;
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    // ... existing body unchanged
}
```

`isOnline()` and `destroyConnectivity()` are safe to call unguarded
(`isOnline` reads `navigator.onLine`; `destroyConnectivity` removes listeners
that were never added — `removeEventListener` is a no-op for missing
listeners). Leave them alone.

- [ ] **Step 3: Guard `sync-manager.ts` (3 entry points)**

In `frontend/src/lib/sync-manager.ts`, add `if (!OFFLINE_ENABLED) return;` (or
the appropriate stubbed return value) as the first line of:

- `initSyncManager` (line 128) — `void` return, use `if (!OFFLINE_ENABLED) return;`.
- `drainQueue` (line 45) — returns `Promise<{synced; failed}>`. Use:
  ```ts
  if (!OFFLINE_ENABLED) return { synced: 0, failed: 0 };
  ```
- `syncNow` (line 157) — same return type as `drainQueue`. Use the same stub.

`destroySyncManager`, `isSyncing` are read-only and safe; leave alone.

- [ ] **Step 4: Guard `offline-db.ts:openDb`**

In `frontend/src/lib/offline-db.ts:53`, add the guard at the top of `openDb`:

```ts
function openDb(): Promise<IDBDatabase> {
    if (!OFFLINE_ENABLED) {
        return Promise.reject(
            new Error('Offline DB is disabled (VITE_OFFLINE_ENABLED=false)'),
        );
    }
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        // ... existing body unchanged
    });
}
```

This blocks `indexedDB.open` from ever being called when the flag is off. Every
exported CRUD function (`saveSession`, `enqueueAction`, etc.) flows through
`tx()` → `openDb()` and will reject. Callers should already be hidden by the
Task 6 UI gate, so this is defense-in-depth.

- [ ] **Step 5: Guard `field-mode.svelte.ts` activate/restore/init**

In `frontend/src/lib/field-mode.svelte.ts`, add the guard as the first line of:

- `activateFieldMode` (line 130) — async, returns void/state. Stub:
  ```ts
  if (!OFFLINE_ENABLED) {
      throw new Error('Offline field mode is disabled (VITE_OFFLINE_ENABLED=false)');
  }
  ```
- `restoreFieldMode` (line 172) — async, returns `boolean`. Stub:
  ```ts
  if (!OFFLINE_ENABLED) return false;
  ```
- `initFieldMode` (line 348) — async, void. Stub:
  ```ts
  if (!OFFLINE_ENABLED) return;
  ```

Read-only getters (`isFieldModeActive`, `getFieldModeState`, etc.) are safe —
they just read the in-memory state, which will simply be the empty default
when nothing was ever activated. Leave them alone.

- [ ] **Step 6: Verify `crypto.ts` has no top-level side effects**

Run:

```bash
sed -n '1,15p' frontend/src/lib/crypto.ts
```

Confirm the file only declares helper functions and constants. From the
exploration during planning we already saw it's pure helpers (PBKDF2 +
AES-GCM wrappers). No changes needed; the spec lists it for completeness.

- [ ] **Step 7: Type-check + run unit tests**

```bash
cd frontend && npm run check && npm run test
```

Expected: passes. (Existing tests for these modules — if any — call the now-
guarded functions. They run with `VITE_OFFLINE_ENABLED` unset, so the guards
will short-circuit. If a test breaks, the test is asserting on offline
behavior; set `VITE_OFFLINE_ENABLED=true` for that test via vitest's `vi.stubEnv`
or update the test to reflect the new gated behavior — pick whichever is a
smaller diff.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/pwa.svelte.ts frontend/src/lib/sync-manager.ts \
        frontend/src/lib/offline-db.ts frontend/src/lib/field-mode.svelte.ts
git commit -m "feat(td-0082): guard offline module init when flag off"
```

---

## Task 6: Frontend — UI guards

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/routes/runs/[id]/+page.svelte`
- Modify: `frontend/src/routes/field/+page.svelte`
- Modify: `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte`
- Modify: `frontend/src/lib/components/run/RoleAssignmentPanel.svelte`

- [ ] **Step 1: Identify each offline UI mount point**

Run:

```bash
cd frontend && grep -n "ConnectivityBanner\|ExpiryWarningBanner\|GoOfflineDialog\|InstallPrompt\|beforeinstallprompt\|Go Offline\|goOffline" src/routes/+layout.svelte src/routes/+page.svelte src/routes/runs/\[id\]/+page.svelte src/routes/field/+page.svelte src/lib/components/field-mode/FieldModeRoleWizard.svelte src/lib/components/run/RoleAssignmentPanel.svelte
```

Note line numbers and what each mount does.

- [ ] **Step 2: Add import to each file that needs the flag**

In each file from Step 1, add (in the existing `<script>` block):

```ts
import { OFFLINE_ENABLED } from '$lib/feature-flags';
```

If the file already imports from `$lib/feature-flags`, skip.

- [ ] **Step 3: Wrap each banner / dialog mount**

For each `<ConnectivityBanner ... />`, `<ExpiryWarningBanner ... />`, and
`<GoOfflineDialog ... />` mount, wrap with:

```svelte
{#if OFFLINE_ENABLED}
    <ConnectivityBanner ... />
{/if}
```

Apply identically to `<ExpiryWarningBanner>` and `<GoOfflineDialog>` mounts.

- [ ] **Step 4: Hide "Go Offline" trigger in field-mode wizard + role panel**

In `FieldModeRoleWizard.svelte` and `RoleAssignmentPanel.svelte`, find the
button or step that initiates offline (look for label "Go Offline" or a
handler calling `goOffline`/`startOfflineSession`). Wrap the trigger in:

```svelte
{#if OFFLINE_ENABLED}
    <Button on:click={goOffline}>Go Offline</Button>
{/if}
```

If the trigger is a wizard step, also remove it from the steps list when the
flag is off — pass the steps array through a `$derived` filter:

```ts
const steps = $derived(
    OFFLINE_ENABLED
        ? ALL_STEPS
        : ALL_STEPS.filter((s) => s.id !== 'go-offline'),
);
```

(Adapt to the actual step-id and array name used in the file.)

- [ ] **Step 5: Hide PWA install prompt**

In `+layout.svelte`, find any `beforeinstallprompt` listener or `<InstallPrompt>`
mount. Wrap its registration in:

```ts
if (OFFLINE_ENABLED) {
    window.addEventListener('beforeinstallprompt', /* existing handler */);
}
```

For the install-prompt UI mount:

```svelte
{#if OFFLINE_ENABLED && showInstallPrompt}
    <InstallPrompt ... />
{/if}
```

- [ ] **Step 6: Type-check + run tests**

```bash
cd frontend && npm run check && npm run test
```

Expected: passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/+layout.svelte frontend/src/routes/+page.svelte \
        frontend/src/routes/runs/\[id\]/+page.svelte frontend/src/routes/field/+page.svelte \
        frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte \
        frontend/src/lib/components/run/RoleAssignmentPanel.svelte
git commit -m "feat(td-0082): hide offline UI when flag off"
```

---

## Task 7: README — Feature flags section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Feature Flags section**

Append to `README.md` (or insert under an existing "Configuration" section if
present — check first with `grep -n "## " README.md`):

```markdown
## Feature flags

Some features are gated by env vars so we can ship with them disabled and flip
them on later without code changes.

| Flag | Backend env | Frontend env | Default | Notes |
| --- | --- | --- | --- | --- |
| Offline / PWA | `BATCHRITE_OFFLINE_ENABLED` | `VITE_OFFLINE_ENABLED` | `false` | Offline field-mode session, IndexedDB cache, sync queue, "Go Offline" flow, PWA install. Flip both vars to `true` to re-enable. (TD-0082) |

Flags must be set on **both** sides to take effect end-to-end. Flipping only
the frontend leaves the UI live but the backend will 404 on `/offline/*` and
`/sync/*`; flipping only the backend leaves the routes mounted but unreachable
from the UI.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(td-0082): document offline feature flag in README"
```

---

## Task 8: Verification — both flag states

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && source .venv/bin/activate && pytest
```

Expected: all green. Pay attention to anything in `tests/integration/test_offline*`
or `test_sync*` — those should still pass when the flag is on (the suite
doesn't pre-set the env var, so default is off; if there are existing offline
tests, they may need `monkeypatch.setenv("BATCHRITE_OFFLINE_ENABLED", "true")`
to run. If any fail because they hit `/offline/*` and now get 404, add the
monkeypatch + module reload to those tests' fixtures, or mark them xfail with
a note pointing back to TD-0082 — pick the lighter touch).

- [ ] **Step 2: Run frontend test suite + type check**

```bash
cd frontend && npm run check && npm run test
```

Expected: all green.

- [ ] **Step 3: Browser QA — flag OFF (default)**

Launch the qa-verify agent (per implement-task skill). Brief:

- Login at `localhost:5183` (worktree port) with any seeded user.
- **Verify flag-off behavior:** No `<ConnectivityBanner>` visible on any page;
  no `<ExpiryWarningBanner>`; no "Go Offline" button in field mode or role
  wizard; no PWA install prompt; DevTools network tab shows zero requests to
  `/offline/*` or `/sync/*`; DevTools application tab shows no service worker
  registered and no IndexedDB databases for the app.

- [ ] **Step 4: Browser QA — flag ON**

Set `VITE_OFFLINE_ENABLED=true` in `frontend/.env.local`,
`BATCHRITE_OFFLINE_ENABLED=true` in `backend/.env`, restart both servers, and
relaunch qa-verify with brief:

- **Verify flag-on behavior:** All offline UI surfaces render; the "Go Offline"
  flow works end-to-end (open a run, enter field mode, go offline, see the
  expiry banner, return online); `/offline/*` and `/sync/*` requests succeed;
  service worker registers; IndexedDB opens.

- [ ] **Step 5: Commit any QA fixes**

If qa-verify finds issues, fix them and commit. Then re-run the failed step.

---

## Task 9: User sign-off + close

- [ ] **Step 1: Summarize for the user**

Post a short summary: backend setting + router gate, frontend flag module + UI
gates + boot init guards, env.example + README updates, tests for the backend
flag, browser QA passes for both states.

- [ ] **Step 2: Wait for explicit sign-off**

Do NOT close the task without the user saying "ship it" / "looks good" / etc.

- [ ] **Step 3: Exit worktree (keep)**

```
ExitWorktree action=keep
```

- [ ] **Step 4: ClickUp comment + close**

`clickup_create_task_comment` with: files modified, env vars added, tests
added, browser QA evidence (both flag states).

`clickup_update_task` with `status: complete`.
