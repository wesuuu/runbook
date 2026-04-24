# Stripe Setup for Batchrite

Batchrite uses Stripe for subscription billing (F-0019a). This guide walks a new developer through setting up their local Stripe test-mode account so the billing integration works end-to-end.

All steps happen in Stripe **Test mode**. No real charges are ever made in development or CI.

## Prerequisites

- A Stripe account at https://dashboard.stripe.com (the free one is enough).
- The Stripe CLI installed: https://stripe.com/docs/stripe-cli (`brew install stripe/stripe-cli/stripe` on macOS).

## 1. Confirm Test mode and fetch API keys

1. Log in at https://dashboard.stripe.com.
2. Top-left: confirm the **"Test mode"** toggle is ON (orange pill). Everything below happens in Test mode.
3. Left sidebar → **Developers → API keys**.
4. Copy the **Secret key** (starts with `sk_test_`). A restricted key (`rk_test_`) also works if it includes write access to customers, subscriptions, and billing_portal; use `sk_test_` if unsure.
5. Paste into `backend/.env`:

    ```
    BATCHRITE_STRIPE_SECRET_KEY=sk_test_...
    ```

## 2. Create Essentials and Pro products

1. Left sidebar → **Product catalog** → **Add product**.
2. Create **Batchrite Essentials**:
    - Name: `Batchrite Essentials`
    - Pricing: Recurring → Monthly → any placeholder amount (e.g. `$29.00 USD`)
    - Click **Add product**.
    - On the resulting page, copy the **Price ID** (starts with `price_`).
3. Create **Batchrite Pro** the same way (e.g. `$99.00 USD`). Copy its Price ID.
4. Paste both into `backend/.env`:

    ```
    BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID=price_...
    BATCHRITE_STRIPE_PRO_PRICE_ID=price_...
    ```

## 3. Configure Customer Portal

Our app deep-links users to Stripe's hosted Customer Portal for plan changes, card updates, and cancellations. The Portal must be configured before "Upgrade" / "Downgrade" / "Manage billing" buttons work.

1. Direct link: https://dashboard.stripe.com/test/settings/billing/portal
2. Under **Functionality**, enable:
    - ☑ Customers can update their payment method
    - ☑ Customers can view their invoice history
    - ☑ Customers can cancel subscriptions → select **"At the end of the billing period"**
    - ☑ Customers can switch plans
3. Under **Products** ("Plans customers can switch to"): add both Essentials and Pro.
4. Set a support email under **Business information**.
5. Click **Save changes**.

## 4. Forward webhooks to local dev

Stripe cannot reach `localhost`. The Stripe CLI creates an authenticated tunnel from Stripe's servers into your laptop. In production you paste a public URL into the dashboard instead and skip the CLI.

1. Log in the CLI once: `stripe login` (opens a browser).
2. Start forwarding (leave this terminal running while you develop):

    ```bash
    stripe listen --forward-to localhost:8000/billing/webhook
    ```

    In a worktree, use the alternate backend port (e.g. `localhost:8010`).

3. The first line prints a signing secret:

    ```
    Ready! Your webhook signing secret is whsec_...
    ```

4. Paste into `backend/.env`:

    ```
    BATCHRITE_STRIPE_WEBHOOK_SECRET=whsec_...
    ```

This secret changes every time you restart `stripe listen`. If your webhook calls start returning 400, check whether the secret rotated.

## 5. Configure the trial length (optional)

By default, new orgs get a 30-day Essentials trial. During the launch beta (3-6 months), set this to 180 days:

```
BATCHRITE_ESSENTIALS_TRIAL_DAYS=180
```

## 6. Configure per-tier seat caps (optional)

Defaults: Essentials 5, Pro 25, Enterprise unlimited (no cap). Override per-environment if desired:

```
BATCHRITE_SEAT_LIMIT_ESSENTIALS=5
BATCHRITE_SEAT_LIMIT_PRO=25
```

Enterprise has no cap regardless of env vars — handled in code.

## Test cards for QA

In Test mode, any future expiry + any CVC + any ZIP passes basic validation. Card numbers determine behavior:

| Card                | Behavior                                            |
|---------------------|-----------------------------------------------------|
| 4242 4242 4242 4242 | Always approves (happy path)                        |
| 4000 0000 0000 0341 | Attaches, then subsequent charges fail              |
| 4000 0000 0000 9995 | Insufficient funds decline                          |
| 4000 0025 0000 3155 | 3DS authentication required                         |
| 4000 0000 0000 0002 | Generic decline at payment time                     |

## Production rollout

Production uses **Live mode** and a different set of keys (`sk_live_...`). Rollout is documented in a separate runbook (not yet written; filed as a follow-up). Plan on a canary charge + refund pattern to verify end-to-end flow without waiting for a real customer.
