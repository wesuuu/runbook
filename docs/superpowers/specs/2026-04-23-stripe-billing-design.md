# F-0019a + F-0019b: Stripe Billing + Essentials Trial — Design

Status: Draft
Date: 2026-04-23
Owner: wesuuu

## Summary

Self-serve subscription billing for Batchrite orgs using Stripe. Two paid tiers — Essentials and Pro — each backed by a Stripe subscription. New orgs begin life on a trialing Essentials subscription whose duration is config-controlled (default 30 days; 180 days during the 3-6 month launch beta). If the trial ends without a payment method on file, Stripe auto-cancels the subscription (`trial_settings.end_behavior.missing_payment_method='cancel'`). Users with `OrgRole.BILLING` manage their subscription through a new Billing tab in Organization Settings, which displays current state and deep-links to the Stripe Customer Portal for plan changes, payment methods, cancellation, and invoice history. Enterprise remains non-self-serve and shows a Contact Sales CTA.

## Goals

- Plumb full Stripe integration end-to-end in test mode: customer + subscription lifecycle, webhook reconciliation, audit logging, permission gating, frontend UI.
- New orgs automatically provisioned with a trialing Essentials subscription on registration (F-0035 integration).
- Trial duration is configurable so the same code serves both the beta period and post-beta state.
- No credit card required to start a trial; no charge if user never adds one (Stripe handles both).
- Smallest possible code surface area — defer plan changes, card management, cancellation, and invoice history to the Stripe Customer Portal (approach A from brainstorming).
- Environment-agnostic code: dev and staging use Stripe test mode; production uses live mode; behavior differs only by config.

## Deviations from the Original Task Description

The ClickUp task for F-0019a was authored before this brainstorming session. The decisions below supersede specific items in the task text:

- **Tier label "Free" → "Essentials."** The enum stays `essentials`; UI displays "Essentials." Reflects the long-term plan that Essentials is a paid tier (1-month free trial; extended 3-6 month trial during beta).
- **Originally separate F-0019b (trial/beta mechanics) is merged into this task.** Both tiers are paid Stripe subscriptions; trial handled natively via Stripe.
- **No `POST /billing/checkout-session` endpoint.** Plan upgrades happen through the Stripe Customer Portal, which handles the case where the customer already has a trialing subscription.
- **No `POST /billing/subscription/cancel` endpoint.** Cancellations and downgrades happen through the Stripe Customer Portal.
- **No `prorate` option in-app.** Prorated cancellations are handled case-by-case through Stripe Dashboard by a support operator.
- **No "Batchrite Free (archived)" Stripe product.** Two real products: Batchrite Essentials + Batchrite Pro.

## Non-Goals

- Production rollout (live keys, canary-charge runbook, dunning emails, tax handling) — separate follow-up task.
- In-app enforcement when `subscription_status='canceled'` (blocking reads/writes). For now, a canceled org sees a Billing-tab CTA to re-subscribe; app access is unchanged.
- In-app invoice table. Portal handles invoice history.
- In-app proration UI. Handled case-by-case through Stripe Dashboard.
- Migrating existing (pre-F-0019a) orgs to have Stripe customers. They get provisioned lazily on first billing interaction. Retroactive backfill is a separate task if needed.
- F-0036 closure as superseded — task-board hygiene, handled separately.

## High-Level Architecture

```
Registration (F-0035)
    └→ billing_service.create_trial_subscription(org)
           ├→ Stripe customer created
           └→ Stripe subscription created
                 · price = essentials_price_id
                 · trial_period_days = essentials_trial_days (config)
                 · missing_payment_method = 'cancel'

Org Settings > Billing tab  (requires OrgRole.BILLING)
    ├→ GET  /billing/subscription       → current tier/status/trial_end/next_bill/cancel_at_period_end
    └→ POST /billing/portal-session     → { url }  (Stripe Portal)

Stripe
    └→ POST /billing/webhook            (signature-verified)
           events: customer.subscription.created/updated/deleted,
                   invoice.payment_failed, checkout.session.completed
```

All webhook-driven state updates write audit log entries for tier changes (before/after values).

## Environment Strategy

Stripe has fully isolated **test mode** and **live mode**. Every Stripe resource (products, prices, customers, webhooks, Portal config, events) exists separately in each mode. Which mode you operate in is determined purely by which API key you send; our code does not branch on environment.

| Environment | Stripe mode | Keys                                          | Real charges? |
|-------------|-------------|-----------------------------------------------|---------------|
| Dev (local) | Test        | `sk_test_*` — per-developer or shared sandbox | No            |
| Staging     | Test        | `sk_test_*` — shared staging Stripe project   | No            |
| Production  | Live        | `sk_live_*` — Batchrite Stripe account        | Yes           |

**Test cards (dev/staging QA)** — any future expiry, any CVC, any ZIP:

| Card                | Behavior                                              |
|---------------------|-------------------------------------------------------|
| 4242 4242 4242 4242 | Always approves (happy path)                          |
| 4000 0000 0000 0341 | Attaches, then subsequent charges fail (invoice.payment_failed testing) |
| 4000 0000 0000 9995 | Insufficient funds decline                            |
| 4000 0025 0000 3155 | 3DS authentication required                           |
| 4000 0000 0000 0002 | Generic decline at payment time                       |

**Production verification (out of scope, documented as follow-up runbook):** canary charge + refund. A trusted operator signs up, upgrades to Pro with a real card, verifies webhook + DB + UI end-to-end, then cancels and refunds via Stripe Dashboard (5-10 minutes, free for recent charges). This is the only honest way to rubber-stamp a live Stripe integration without waiting for a real customer.

## Data Model

### Alembic migration: `add_stripe_billing_fields_to_organizations`

Add to `organizations`:

```python
stripe_customer_id: str | None          # indexed
stripe_subscription_id: str | None
subscription_status: str | None         # active | trialing | past_due | canceled | incomplete
current_period_end: datetime | None
trial_end: datetime | None
cancel_at_period_end: bool              # default false
```

All fields nullable. Existing orgs default to null (pre-billing state). `subscription_tier` stays as-is from F-0034.

### Optional: `stripe_events` table (idempotency)

```python
class StripeEvent(Base, UUIDMixin, TimestampMixin):
    stripe_event_id: str  # unique; Stripe event ID
    event_type: str
    processed_at: datetime
```

Webhook handler upserts by `stripe_event_id`; duplicates are no-ops. Alternative: rely on state comparison only (apply-if-different), no event table. **Decision: include the table.** It's ~15 lines of migration, gives us a clean audit trail of what Stripe sent us, and eliminates a class of idempotency bugs where state comparison fails (e.g., two subscription.updated events for the same state change).

## Config

`backend/app/core/config.py` — `Settings`:

```python
stripe_secret_key: str = ""
stripe_webhook_secret: str = ""
stripe_essentials_price_id: str = ""
stripe_pro_price_id: str = ""
essentials_trial_days: int = 30
stripe_portal_return_url: str = "/settings?tab=billing"
```

Env prefix remains `BATCHRITE_`. All stripe_* fields optional — billing endpoints return **503 with a clear configuration message** when any required key is unset. App boots either way. Registration's `create_trial_subscription` is a no-op when Stripe is unconfigured (logs a warning; org gets billing plumbing on first interaction instead).

## Backend Service Layer

New directory: `backend/app/services/billing/`

- `stripe_client.py` — thin adapter exposing the subset of `stripe.*` calls we use. Enables test injection of a fake client. Module-level singleton initialized from config.
- `subscription_service.py` — org-facing operations:
  - `create_trial_subscription(db, org) → Organization` — creates Stripe customer + Essentials trialing subscription; writes stripe_* fields to the org. Idempotent (no-ops if `stripe_subscription_id` already set).
  - `create_portal_session(org, return_url) → str` — returns Portal URL.
  - `get_subscription_state(org) → SubscriptionState` — returns current tier/status/period/trial/cancel flags. Reads DB (already reconciled by webhooks); does not hit Stripe on every request.
- `webhook_handler.py` — `handle_event(db, event) → None`:
  - Dispatches per `event.type`.
  - Loads org by `stripe_customer_id`.
  - Compares pre-state to event payload; writes updated fields.
  - If `subscription_tier` changes → `log_audit` with before/after.
  - Upserts `StripeEvent` for idempotency.

Service abstraction follows `.claude/rules/conventions.md`:
- `subscription_service.py` — module functions (stateless, `db` + domain args).
- `stripe_client.py` — class or module singleton; holds client + config.
- `webhook_handler.py` — module functions.

## Backend Endpoints

New router: `backend/app/api/endpoints/billing.py`, mounted at `/billing`.

All endpoints require:
- `get_current_user`
- A new `require_org_role(OrgRole.BILLING)` dep that verifies the user has the BILLING role on their `selected_org_id` via `OrganizationMember`. If not present in `core/deps.py`, add it.

### `GET /billing/subscription`

Response:
```python
class SubscriptionStateResponse(BaseModel):
    tier: str                               # essentials | pro | enterprise
    status: str | None                      # active | trialing | past_due | canceled | incomplete
    trial_end: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    has_payment_method: bool                # derived from Stripe customer default_payment_method; cached on the org
```

503 if Stripe unconfigured.

### `POST /billing/portal-session`

Request (optional `return_url` override):
```python
class PortalSessionRequest(BaseModel):
    return_url: str | None = None           # defaults to stripe_portal_return_url config
```

Response: `{ "url": "https://billing.stripe.com/..." }`. 503 if Stripe unconfigured.

### `POST /billing/webhook`

- Signature verified via `stripe.Webhook.construct_event(payload, sig_header, stripe_webhook_secret)`.
- Calls `webhook_handler.handle_event`.
- Returns 200 on success. On signature failure, returns 400 (Stripe will not retry — signature is deterministic). On internal failure (e.g., DB error), returns 500 so Stripe retries within its 3-day retry window. `StripeEvent` idempotency ensures retries are safe.
- **No auth middleware** on this route (Stripe is the caller, uses signature).

### Events handled

| Event                               | Action                                                                                             |
|-------------------------------------|----------------------------------------------------------------------------------------------------|
| `customer.subscription.created`     | Set subscription_id, status, period, trial_end. Usually redundant with registration path.          |
| `customer.subscription.updated`     | Reconcile all fields. Detect tier change (price_id → tier). Audit log on tier change.              |
| `customer.subscription.deleted`     | Set status=canceled. Revert tier to essentials if currently pro (shouldn't happen since Essentials is the fallback, but defensive). Audit log. |
| `invoice.payment_failed`            | Set status=past_due. No tier change yet. (Stripe will retry; eventually fires subscription.deleted if all retries fail.)   |
| `checkout.session.completed`        | Rare for us since we don't use Checkout directly, but handle defensively — reconcile via subscription lookup. |

## Frontend

### Zod schema

New file `frontend/src/lib/schemas/billing.ts`:

```typescript
export const SubscriptionStateSchema = z.object({
    tier: z.enum(['essentials', 'pro', 'enterprise']),
    status: z.string().nullable(),
    trial_end: z.string().nullable(),
    current_period_end: z.string().nullable(),
    cancel_at_period_end: z.boolean(),
    has_payment_method: z.boolean(),
}).passthrough();

export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;
```

Barrel export updated.

### API client

`frontend/src/lib/api.ts` already has the `request` helper. Add:

```typescript
billing: {
    getSubscription: () => api.get('/billing/subscription', { schema: SubscriptionStateSchema }),
    createPortalSession: (return_url?: string) => api.post('/billing/portal-session', { return_url }),
},
```

### Settings tab

- Route: `frontend/src/routes/settings/+page.svelte` — add new tab "Billing" (visible only when current user has BILLING on selected org). Tab ordering to match existing pattern.
- Component: `frontend/src/lib/components/settings/BillingTab.svelte`.

### BillingTab layout

- **Header card** — current plan name + status badge (Trialing / Active / Past Due / Canceled / Essentials-no-sub).
- **Trial banner** (when `status=trialing`) — "X days left in your trial. Add a payment method to keep your subscription active." CTA launches Portal.
- **Cancel-at-period-end banner** (when `cancel_at_period_end=true`) — "Your subscription will end on [date]. You can reactivate from the billing portal."
- **Plan rows**:
  - Essentials — marked "Your plan" if tier=essentials, otherwise "Downgrade" CTA (launches Portal).
  - Pro — marked "Your plan" if tier=pro, otherwise "Upgrade" CTA (launches Portal).
  - Enterprise — always "Contact Sales" mailto (`sales@batchrite.com` or similar; configurable via env later).
- **Manage billing** button at the bottom — opens Portal with no specific action hint. Handles cards, invoices, cancel, change plan.
- **Unconfigured state** — if the backend returns 503 (Stripe not configured), the tab shows a clear "Billing is not configured for this environment" card. Useful for dev/CI where Stripe keys aren't set.

### Portal redirect flow

1. User clicks any Portal-launching CTA.
2. Frontend calls `POST /billing/portal-session` → gets `{ url }`.
3. Frontend `window.location.href = url` (full-page redirect; not an iframe/modal — Stripe Portal is not embeddable).
4. User interacts on Stripe. Stripe fires webhooks to our backend as state changes.
5. Stripe redirects user back to `return_url` (default `/settings?tab=billing`).
6. On return, the Billing tab's mount effect re-fetches `GET /billing/subscription` — webhooks have already reconciled the DB, so the fresh read shows the new state.

No polling; webhooks are synchronous-ish (Stripe fires within seconds of the Portal action completing), and the user has to traverse a redirect before reaching the refreshed tab. If a rare race occurs, a manual refresh resolves it.

## Permissions

- All `/billing/*` endpoints (except `/webhook`) gated by `require_org_role(OrgRole.BILLING)` on the user's `selected_org_id`.
- Billing tab only renders when the current user has BILLING on the selected org. Backend enforces; frontend hides the tab as a UX nicety.
- F-0035 registration flow already grants ADMIN + BILLING to org creators, so the default new-user can access Billing.
- Members without BILLING get 403 on endpoints and don't see the tab.

## Audit Logging

All tier changes caused by webhooks write `log_audit(db, actor_id=None, "UPDATE", "Organization", org.id, changes={...})`:

```python
changes = {
    "subscription_tier": [before, after],
    "subscription_status": [before, after],
}
```

`actor_id=None` since the cause is Stripe, not an authenticated user. (If `log_audit`'s signature requires a non-null actor, we pass a well-known system UUID and document it.)

User-initiated portal sessions don't write audit logs directly; the eventual webhook write captures the outcome.

## Tests

### Unit

- `webhook_handler` — one test per event type, using fixture JSON payloads from `tests/fixtures/stripe/`. Verifies:
  - DB state updated correctly.
  - Audit log written on tier change.
  - Idempotency: replay the same event → no duplicate state change, no duplicate audit log.
  - Signature rejection returns 400.
- `subscription_service.create_trial_subscription` — mocked Stripe client:
  - Creates customer + subscription with correct params.
  - Stores returned IDs on org.
  - Idempotent when called twice.
  - No-op and logs a warning when Stripe unconfigured.

### Integration

- Registration creates trialing Essentials subscription (with mocked Stripe).
- Upgrade flow: simulate Portal upgrade by firing `customer.subscription.updated` webhook (price_id changes to pro_price_id). Assert tier flips, audit log written.
- Downgrade flow: fire `customer.subscription.updated` with `cancel_at_period_end=true` (downgrade scheduled); assert DB flag set, tier unchanged. Then fire `customer.subscription.deleted` at cycle end; assert status=canceled, audit log.
- Trial expiry without card: fire `customer.subscription.deleted` with prior status=trialing; assert status=canceled, tier stays essentials, audit log.
- Invoice payment failed: fire `invoice.payment_failed`; assert status=past_due, tier unchanged.
- Permission: non-BILLING users get 403 on `/billing/subscription` and `/billing/portal-session`.
- 503 when Stripe unconfigured — same endpoints.

### Stripe mocking approach

- `stripe_client` module exposes a singleton `get_stripe()` that returns either the real `stripe` module or a fake depending on config.
- Tests inject a fake via dependency override or monkeypatch of `get_stripe`.
- Webhook signature tests generate signatures using a known test secret and `stripe.WebhookSignature` helpers.

### E2E (deferred)

Playwright E2E on the Portal flow is impractical (redirect to stripe.com). Covered implicitly by integration tests + manual QA using test cards in dev.

## Bootstrap / Developer Setup

New doc: `docs/stripe-setup.md`

Contents:

1. **Create Stripe test-mode account** (or reuse the team sandbox).
2. **Create products and prices** (in test mode):
   - "Batchrite Essentials" — monthly recurring price.
   - "Batchrite Pro" — monthly recurring price.
3. **Configure Customer Portal** (Settings → Billing → Customer Portal):
   - Allowed actions: update payment method, view invoice history, cancel subscription (at period end), change plan (Essentials ↔ Pro).
   - Allowed products: Essentials + Pro, both prices.
4. **Create webhook endpoint**:
   - URL: `https://<env-host>/billing/webhook` (localhost tunneled via `stripe listen` for dev).
   - Enabled events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `checkout.session.completed`.
5. **Copy keys into `.env`**:
   ```
   BATCHRITE_STRIPE_SECRET_KEY=sk_test_...
   BATCHRITE_STRIPE_WEBHOOK_SECRET=whsec_...
   BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID=price_...
   BATCHRITE_STRIPE_PRO_PRICE_ID=price_...
   ```
6. **Local webhook forwarding**: `stripe listen --forward-to localhost:8000/billing/webhook`. Copy the displayed signing secret into `.env` for this session.
7. **Test cards** (repeat of the table in the Environment Strategy section).

Also seed placeholders in `.env.example`.

## Stripe Dashboard Setup (Manual — User Actions)

These steps happen on https://dashboard.stripe.com and cannot be automated. The implementation plan will pause at each of these points. The user performs the step, copies the resulting value(s) back into the chat, and implementation proceeds.

### Pause 1 — Verify the Stripe account & locate the Test-mode API keys

**Why it pauses implementation:** the backend code cannot be wired up or tested without a real test-mode secret key.

User actions:

1. Log in at https://dashboard.stripe.com.
2. Confirm the top-left toggle shows **"Test mode"** (orange pill labeled "Test mode"). If it shows "Live mode," click to switch — **everything in this task happens in test mode only**.
3. Fill in the minimum required business profile details Stripe prompts for (business name, country). Full verification (bank account, tax ID) is **not** required for test mode — you can skip / defer any "Activate payments" prompts. Test mode works on an unverified account.
4. In the left sidebar, click **Developers → API keys**.
5. Copy the two keys shown:
   - **Publishable key** — starts with `pk_test_...` (not used server-side; capture it so we can add to frontend config later if needed).
   - **Secret key** — starts with `sk_test_...`. Click "Reveal test key" to see it. **Never commit this; never paste it in a Git-tracked file or PR.**

Hand back: the `sk_test_...` value (or confirmation it's set in your local `.env` — see below). The `pk_test_...` is optional; we won't need it until frontend billing work, and only if we ever embed Stripe.js, which we are not.

Where it goes: `backend/.env` (this file is gitignored):
```
BATCHRITE_STRIPE_SECRET_KEY=sk_test_...
```

### Pause 2 — Create Products and Prices (in Test mode)

**Why it pauses implementation:** price IDs are required to create subscriptions. The code needs these IDs in config before registration integration can be wired up and tested.

User actions:

1. Still in Test mode: left sidebar → **Product catalog** → **Add product**.
2. Create **Batchrite Essentials**:
   - Name: `Batchrite Essentials`
   - Description (optional): short blurb.
   - Pricing → **Recurring** → **Monthly**. Amount: pick any test number (e.g. `$29.00 USD`) — this is test mode, pricing is just a placeholder until product decides real numbers.
   - Click **Add product**.
   - On the resulting product page, copy the **Price ID** under the price row. It looks like `price_1ABC...` (about 30 chars).
3. Repeat for **Batchrite Pro**:
   - Name: `Batchrite Pro`.
   - Recurring / Monthly / e.g. `$99.00 USD`.
   - Copy its Price ID.

Hand back: the two Price IDs.

Where they go: `backend/.env`:
```
BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID=price_...
BATCHRITE_STRIPE_PRO_PRICE_ID=price_...
```

### Pause 3 — Configure Customer Portal (in Test mode)

**Why it pauses implementation:** the frontend's "Manage billing" / "Upgrade" / "Downgrade" buttons all launch the Portal. If Portal isn't configured with the two products and the right allowed actions, clicks will succeed at the API level but the UI the user sees on Stripe will be broken/empty.

User actions:

1. Left sidebar → **Settings** (gear icon, bottom-left) → **Billing** → **Customer portal**. (Direct link: https://dashboard.stripe.com/test/settings/billing/portal)
2. Under **Functionality**, enable:
   - ☑ **Customers can update their payment method**
   - ☑ **Customers can view their invoice history**
   - ☑ **Customers can cancel subscriptions** → choose **"At the end of the billing period"** (not "Immediately")
   - ☑ **Customers can switch plans**
3. Under **Products** (the "Plans customers can switch to" section):
   - Add **Batchrite Essentials** (its monthly price).
   - Add **Batchrite Pro** (its monthly price).
4. Under **Business information**:
   - Set a **support email** (your email is fine for now).
   - Set **Terms of service** URL and **Privacy policy** URL if you have them; otherwise skip — Stripe won't block you.
5. Click **Save changes**.

Hand back: confirmation that you saved the Portal config. No value to copy; the Portal config is referenced automatically when we create Portal sessions with that Stripe account.

### Pause 4 — Create Webhook Endpoint & Get Signing Secret (Test mode)

**Why it pauses implementation:** the webhook handler's signature verification needs the signing secret. For local dev, you use the Stripe CLI which generates its own per-session secret; for staging/prod you use a dashboard-created endpoint.

There are **two webhook setups** you'll do — one for local dev, one for staging/production.

#### Pause 4a — Local dev (Stripe CLI)

User actions:

1. Install the Stripe CLI if not installed: https://stripe.com/docs/stripe-cli (Homebrew: `brew install stripe/stripe-cli/stripe`).
2. Log in the CLI: `stripe login` — this opens a browser to authenticate. Confirm it.
3. In a terminal that stays running while you develop:
   ```
   stripe listen --forward-to localhost:8000/billing/webhook
   ```
4. The first line of output prints the signing secret:
   ```
   Ready! Your webhook signing secret is whsec_1ABC...
   ```

Hand back: that `whsec_...` value.

Where it goes: `backend/.env`:
```
BATCHRITE_STRIPE_WEBHOOK_SECRET=whsec_...
```

Note: this secret changes each time you start a new `stripe listen` session. Keep the CLI running while developing; restart it if you kill the terminal, and update `.env` with the new secret.

#### Pause 4b — Staging / Production (Dashboard webhook endpoint)

Skipped for this task — this is part of the production rollout runbook (out of scope). For now, local dev uses `stripe listen`; when staging/prod are being stood up, the user follows this procedure at that time:

1. Developers → **Webhooks** → **Add endpoint**.
2. URL: `https://<staging-or-prod-host>/billing/webhook`.
3. Select events: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `checkout.session.completed`.
4. Click Add endpoint. Copy the signing secret (starts `whsec_...`). Paste into the environment's secret store.

### Summary of values to collect

By the end of Pauses 1-4a, the user will have:

| Value                                 | Shape           | Env var                                 |
|---------------------------------------|-----------------|-----------------------------------------|
| Test secret key                       | `sk_test_...`   | `BATCHRITE_STRIPE_SECRET_KEY`           |
| Essentials price ID                   | `price_...`     | `BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID`  |
| Pro price ID                          | `price_...`     | `BATCHRITE_STRIPE_PRO_PRICE_ID`         |
| CLI webhook signing secret            | `whsec_...`     | `BATCHRITE_STRIPE_WEBHOOK_SECRET`       |

All four go in `backend/.env` (already gitignored). `.env.example` will be updated with placeholder stub values so new devs know what to populate.

## Rollout Order Within This Task

Brainstorming determined F-0019a (Pro plumbing) and F-0019b (Essentials trial + beta mode) ship together. Within this task, implementation order is:

1. Alembic migration (fields + StripeEvent table).
2. Config additions + `.env.example` placeholders.
3. **PAUSE 1** — user completes Stripe Dashboard Setup **Pause 1** (fetch `sk_test_...`). Paste into `backend/.env`.
4. **PAUSE 2** — user completes Stripe Dashboard Setup **Pause 2** (create Essentials + Pro products; fetch price IDs). Paste into `backend/.env`.
5. `stripe_client` + `subscription_service.create_trial_subscription` + unit tests (can now run against real test-mode keys).
6. `webhook_handler` + all event handlers + unit tests.
7. Registration (F-0035) integration + integration test covering trial subscription creation.
8. Endpoints (`GET /billing/subscription`, `POST /billing/portal-session`, `POST /billing/webhook`) + integration tests.
9. **PAUSE 3** — user completes Stripe Dashboard Setup **Pause 3** (Customer Portal config). No code changes; prepares the Portal for the upcoming frontend work.
10. **PAUSE 4a** — user completes Stripe Dashboard Setup **Pause 4a** (start `stripe listen`; fetch `whsec_...`). Paste into `backend/.env`. Webhook endpoint is now reachable from Stripe.
11. Manual smoke test: create a new org locally, confirm trialing subscription appears in Stripe Dashboard and `organizations.stripe_subscription_id` is populated.
12. Frontend Zod schema, API client methods, BillingTab component, settings route integration.
13. Browser verification via qa-verify (using test cards from Environment Strategy section).
14. Developer docs (`docs/stripe-setup.md` — a cleaned-up version of the four Pause sections for future devs).

## Open Questions / Decisions for the Plan

- **Exact Stripe price amounts.** Placeholder values in test mode; real pricing is a product decision independent of this code. The code does not care about the amount.
- **Enterprise "Contact Sales" destination.** `mailto:sales@batchrite.com` for now; parameterize via config in a later task if needed.
- **System UUID for Stripe-driven audit logs.** If `log_audit` requires non-null actor_id, create a well-known `STRIPE_SYSTEM_ACTOR_ID` constant and document it. Otherwise pass `None`.
- **`has_payment_method` derivation.** Query customer's default_payment_method when the webhook runs, cache on org as `has_payment_method: bool`. Alternative: live-lookup on every `GET /billing/subscription`. Prefer cached field for responsiveness.

## Risks / Open Concerns

- **JWT staleness on tier change.** Our `require_tier` reads tier from the JWT payload. When a webhook flips a user's tier, their JWT still holds the old tier until they re-login. For billing-tab display this is fine (we read fresh from DB). For tier-gated feature access, users may see stale denials/permissions until they re-auth. **Not new to this task**; F-0034 has the same property. Possible follow-up: invalidate JWTs on tier change, or issue short-lived JWTs. Out of scope for now; flag in rollout.
- **Webhook delivery during downtime.** Stripe retries failed deliveries for 3 days. `StripeEvent` idempotency means replayed events are safe. No special handling needed.
- **Two trialing subscriptions per customer.** Shouldn't happen (`create_trial_subscription` is idempotent on `stripe_subscription_id`). Guard with a check; log and skip if one already exists.
- **Stripe Portal misconfiguration.** If Portal isn't set up correctly (no allowed products, wrong return URL), the Portal button fails with a Stripe-side error. Setup doc is the primary mitigation.
