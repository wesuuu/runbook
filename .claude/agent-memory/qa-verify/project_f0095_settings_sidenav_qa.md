---
name: f0095-settings-sidenav-qa
description: QA results for F-0095 grouped vertical settings sidenav — two bugs fixed, all 8 acceptance criteria verified
metadata:
  type: project
---

Feature F-0095 replaced the horizontal overflow-scrolling tab bar on `/settings` with a grouped vertical sidenav. QA completed 2026-05-21.

## Key findings

**Fixed: Non-admin deep-link toast silently dropped (FAIL)**
- `toast.info('That section requires admin access')` was called inside a Svelte `$effect` that fires when `isInitialized()` becomes true.
- At that exact moment, the Sonner `Toaster` lives inside the layout's `{#if isInitialized()}` block and may not have finished mounting.
- Fix: wrap the toast call in `tick().then(...)` to defer one Svelte render cycle.
- File: `frontend/src/routes/settings/+page.svelte` (~line 842)

**Fixed: Collapse toggle icon misaligned in collapsed rail (POLISH)**
- The Expand/Collapse toggle button at the bottom of the `<lg` collapsed rail used `justify-start px-3` in all states, making its icon left-aligned while nav items above used `justify-center px-0` in collapsed state.
- Fix: Apply the same conditional `justify-center / px-0` vs `justify-start` logic already used for nav items.
- File: `frontend/src/lib/components/settings/SettingsNav.svelte` (~line 163)

## QA environment notes
- This worktree uses `batchrite_wt3` DB, backend on :8030, frontend on :5203
- `BATCHRITE_AUTH_ENABLED=false` in the backend `.env` — tokens are accepted but users still exist in DB
- Users still require TOS acceptance: call `POST /auth/accept-tos` with Bearer token before testing, otherwise redirected to `/legal/accept`
- `waitForLoadState('networkidle')` times out on the Notifications tab — use a timeout instead

## All acceptance criteria verified
1. Grouped rail (WORKSPACE + ACCOUNT labels, all 10 items) — PASS
2. Active state (teal left bar + bg-card + ring-1 + font-semibold) — PASS
3. Navigation drives URL (?tab=X) and swaps panel — PASS for all 10 tabs
4. Admin gating (AI Models, Templates, Billing hidden for non-admin) — PASS
5. Non-admin deep-link guard (redirects + toast) — PASS after fix
6. Responsive collapse (60px icon-only below 1024px, toggle button, tooltips) — PASS
7. No horizontal overflow at 1440px, 900px, 700px — PASS
8. Sticky rail (nav stays visible when scrolling long panels) — PASS

**Why:** [[svelte-toast-toaster-mounting]] The Sonner Toaster mounting timing is a pattern to watch: any toast fired in an `$effect` that fires at `isInitialized()` transition needs `tick()` deferred call.
