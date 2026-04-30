---
name: Stripe Billing F-0019a QA Findings
description: QA verification findings for Stripe billing / Essentials trial feature (F-0019a + F-0019b)
type: project
---

QA verified F-0019a stripe billing on 2026-04-23. All 7 acceptance criteria tested via API + Playwright against backend :8010 / frontend :5183.

## Test Account Created
- `qa-f19a-api@test.local` / `qatest123` — registered with email verification flow
- Org ID: `20fdadf8-88de-43d3-8c91-fd5f70580572`
- Stripe customer: `cus_UONGX9ijAiH1Fp` / subscription: `sub_1TPaWKDKjJaJhlTii8LNZJec`

## Issues Found and Fixed

### FIXED: SubscriptionLockoutModal used custom div instead of shadcn Dialog
- File: `frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte`
- Replaced custom `div + backdrop` with `Dialog.Root / Dialog.Content / Dialog.Header / Dialog.Footer`
- Re-verified: modal shows correctly, dismiss works, `X` close button from Dialog also works

### FIXED: Settings page tab state not URL-driven
- File: `frontend/src/routes/settings/+page.svelte`
- `activeTab` was plain `$state` defaulting to 'organization', ignoring `?tab=billing` URL param
- Changed to `$derived.by` reading `$page.url.searchParams.get('tab')` with `VALID_TABS` guard
- Tab clicks now call `setTab()` which uses `goto(?tab=X)` instead of direct state assignment
- This fixes the Stripe Portal return flow (portal redirects to `?tab=billing`)
- Added `$effect` to auto-load notification channels when tab=notifications URL is used

## Known Bugs Observed (NOT Fixed - Requires Stripe Portal)
- Tests 2 (portal redirect), 3 (upgrade to Pro), 4 (cancel at period end) require interactive Stripe Portal — cannot be automated without a real browser session

## API Behavior Confirmed
- `GET /billing/subscription` returns 403 for non-ADMIN/BILLING users
- `POST /billing/portal-session` returns a valid `billing.stripe.com/p/session/...` URL
- `POST /projects/` returns 402 `subscription_required` when org.subscription_status='canceled'
- `POST /iam/organizations/{id}/members` returns 402 `seat_limit_reached` at seat cap (Essentials=5, Pro=25)
- Registration creates Stripe customer + trialing subscription atomically via webhook

## Vite Worktree @fs Issue
- The worktree's node_modules is a symlink to the main workspace's node_modules
- Playwright first run saw 403 @fs errors — these were transient; @fs endpoint actually returns 200
- Do NOT add server.fs.allow to vite.config.ts unless @fs actually breaks for real users

**Why:** Fixing the Stripe Portal return UX and the modal component consistency.
**How to apply:** When working on billing-adjacent pages, always check tab state is URL-driven. Always use shadcn Dialog for modals.
