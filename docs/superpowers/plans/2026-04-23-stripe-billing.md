# F-0019a + F-0019b: Stripe Billing + Essentials Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Stripe test-mode billing end-to-end: new orgs start life on a trialing Essentials subscription; org admins upgrade/cancel via Stripe Customer Portal; webhooks reconcile tier/status; canceled/past_due orgs are locked out of writes but retain read access.

**Architecture:** Thin adapter around Stripe's Python SDK (`backend/app/services/billing/`) with module functions for subscription ops and webhook dispatch. New FastAPI router at `/billing` with three endpoints (`GET /subscription`, `POST /portal-session`, `POST /webhook`). Registration flow (F-0035) provisions the trial subscription. Write-lockout via a new `require_active_subscription` dep layered after existing `require_permission` / `require_org_role`. Frontend adds a Billing tab inside Organization Settings and a 402-response interceptor that shows a blocking modal.

**Tech Stack:** Python 3.13 + FastAPI + SQLAlchemy 2.0 (async) + Alembic + `stripe` Python package ≥ 10.0. Frontend: Svelte 5 runes + Zod + shadcn-svelte. Tests: pytest-asyncio + httpx AsyncClient.

**Spec:** `docs/superpowers/specs/2026-04-23-stripe-billing-design.md` — treat as the source of truth. This plan implements the spec verbatim.

**Critical context about the spec this plan encodes:**

- **ADMIN is a superset of BILLING.** The existing registration flow (`backend/app/api/endpoints/auth.py:161-165`) grants only `role="ADMIN"`. `OrganizationMember.role` is a single string column, not multi-valued. Rather than refactor roles, the `require_org_role` dep in Task 9 treats roles as a hierarchy: `ADMIN >= BILLING >= MEMBER`. An ADMIN implicitly satisfies a BILLING requirement. This matches the spec's intent ("F-0035 grants ADMIN + BILLING to org creators") without a model change.
- **`log_audit` requires a non-null `actor_id: UUID`.** Spec's Open Questions flagged this; the answer is a well-known `STRIPE_SYSTEM_ACTOR_ID` constant defined in `backend/app/services/billing/constants.py`. Task 7 introduces it.
- **No `.env.example` exists yet in `backend/`.** Task 3 creates it with Stripe placeholders; no backwards compat concern.
- **`stripe` Python package is not yet a dependency.** Task 1 adds it via Poetry.

---

## File Map

### Backend

**Create:**
- `backend/app/services/billing/__init__.py` — package marker, exports public functions
- `backend/app/services/billing/constants.py` — `STRIPE_SYSTEM_ACTOR_ID` UUID, price-ID-to-tier mapping helper
- `backend/app/services/billing/stripe_client.py` — module wrapping `stripe.*`; injectable for tests
- `backend/app/services/billing/subscription_service.py` — `create_trial_subscription`, `create_portal_session`, `get_subscription_state`
- `backend/app/services/billing/seat_limits.py` — `get_seat_count`, `get_seat_limit`, `check_seat_capacity`
- `backend/app/services/billing/webhook_handler.py` — `handle_event(db, event)` dispatcher
- `backend/app/api/endpoints/billing.py` — router: `GET /subscription`, `POST /portal-session`, `POST /webhook`
- `backend/app/schemas/billing.py` — `SubscriptionStateResponse`, `PortalSessionRequest`, `PortalSessionResponse`
- `backend/app/models/billing.py` — `StripeEvent` model
- `backend/alembic/versions/f0019a1b2c3d_add_stripe_billing_fields.py` — migration
- `backend/tests/unit/services/test_stripe_client.py`
- `backend/tests/unit/services/test_subscription_service.py`
- `backend/tests/unit/services/test_webhook_handler.py`
- `backend/tests/unit/services/test_seat_limits.py`
- `backend/tests/integration/test_seat_caps.py`
- `backend/tests/integration/test_billing_endpoints.py`
- `backend/tests/integration/test_billing_lockout.py`
- `backend/tests/integration/test_registration_billing.py`
- `backend/tests/fixtures/stripe/customer_subscription_created.json`
- `backend/tests/fixtures/stripe/customer_subscription_updated_upgrade.json`
- `backend/tests/fixtures/stripe/customer_subscription_updated_downgrade.json`
- `backend/tests/fixtures/stripe/customer_subscription_deleted.json`
- `backend/tests/fixtures/stripe/invoice_payment_failed.json`
- `backend/.env.example` — documented placeholders
- `docs/stripe-setup.md` — developer setup guide

**Modify:**
- `backend/pyproject.toml` — add `stripe` to `[tool.poetry.dependencies]`
- `backend/app/core/config.py` — add six Stripe-related `Settings` fields plus `seat_limit_essentials` / `seat_limit_pro`
- `backend/app/core/deps.py` — add `require_org_role`, `require_active_subscription`
- `backend/app/models/iam.py` — add stripe fields to `Organization`
- `backend/app/api/endpoints/auth.py` (lines 161-189) — call `create_trial_subscription` after org creation
- `backend/app/api/endpoints/iam.py` (lines 161-228, `add_org_member`) — call `check_seat_capacity` before inserting a new `OrganizationMember`
- `backend/app/schemas/billing.py` — add `seat_count` / `seat_limit` / `seat_limit_exceeded` to `SubscriptionStateResponse`
- `backend/app/main.py` (line 356-361 area) — import + mount `billing.router`
- Write endpoints across many routers — apply `require_active_subscription` dep (see Task 16 for file list)

### Frontend

**Create:**
- `frontend/src/lib/schemas/billing.ts` — `SubscriptionStateSchema`
- `frontend/src/lib/stores/subscription.svelte.ts` — reactive store
- `frontend/src/lib/components/settings/BillingTab.svelte`
- `frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte` — 402-response blocking modal

**Modify:**
- `frontend/src/lib/schemas/index.ts` — barrel export billing
- `frontend/src/lib/api.ts` — add `api.billing.*` methods; 402 interceptor
- `frontend/src/routes/settings/+page.svelte` (lines 26, 602-652, end of template) — add 'billing' tab

---

## Phase 1 — Foundation: Dependencies, Data Model, Config

### Task 1: Add `stripe` Python dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add stripe to Poetry dependencies**

Edit `backend/pyproject.toml`. In the `[tool.poetry.dependencies]` block (around line 10-35), append this line (before the build-system block):

```toml
stripe = "^11.1.0"
```

- [ ] **Step 2: Install the dependency**

```bash
cd backend && source .venv/bin/activate && poetry install --no-root
```

Expected: output ends with `Installing the current project: batchrite-backend (0.1.0)` (skipped because `--no-root`), and earlier lines show `stripe` being installed.

- [ ] **Step 3: Confirm import works**

```bash
cd backend && source .venv/bin/activate && python -c "import stripe; print(stripe.VERSION)"
```

Expected: prints a version number like `11.1.0`.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/poetry.lock
git commit -m "chore(billing): add stripe Python SDK dependency"
```

---

### Task 2: Add Stripe fields to Organization model and create StripeEvent model

**Files:**
- Modify: `backend/app/models/iam.py` (Organization class around line 75)
- Create: `backend/app/models/billing.py`

- [ ] **Step 1: Modify Organization model**

Edit `backend/app/models/iam.py`. Find the `Organization` class (starts at line 75). After the existing column declarations and before the `# Relationships` comment (around line 91), add these fields:

```python
    # Stripe billing (added F-0019a — nullable; existing orgs default to null)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, index=True
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    subscription_status: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    has_payment_method: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
```

Confirm these imports exist at the top of the file: `DateTime`, `Boolean` from `sqlalchemy`; `datetime` from `datetime`; `Optional` from `typing`. If `datetime` is missing, add `from datetime import datetime` near the other imports.

- [ ] **Step 2: Create StripeEvent model**

Create `backend/app/models/billing.py`:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class StripeEvent(Base, UUIDMixin, TimestampMixin):
    """Idempotency record for processed Stripe webhook events.

    Whenever the webhook handler processes a Stripe event, it upserts a row
    keyed by Stripe's event ID. Duplicate deliveries (Stripe retries on
    non-2xx for up to 3 days) are detected here and skipped.
    """

    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
```

- [ ] **Step 3: Register the new model with SQLAlchemy's metadata**

The model must be imported somewhere that `Base.metadata` sees before tests run. Check `backend/app/db/base.py` (or wherever `Base` is imported):

```bash
cat backend/app/db/base.py
```

If it re-imports all model modules, add this import line in the expected section:

```python
from app.models.billing import StripeEvent  # noqa: F401
```

If instead models are imported elsewhere (e.g., in `app/models/__init__.py`), add the import there. Confirm:

```bash
grep -rn "from app.models" backend/app/db/ backend/app/models/__init__.py 2>/dev/null
```

Add the `StripeEvent` import to the same place.

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit -q 2>&1 | tail -10
```

Expected: all passing (no new tests yet).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/iam.py backend/app/models/billing.py backend/app/db/base.py
git commit -m "feat(billing): add Stripe fields to Organization model and StripeEvent model"
```

---

### Task 3: Alembic migration for Stripe fields and StripeEvent table

**Files:**
- Create: `backend/alembic/versions/f0019a1b2c3d_add_stripe_billing_fields.py`

- [ ] **Step 1: Find the current head revision**

```bash
cd backend && source .venv/bin/activate && alembic heads
```

Expected: prints a single revision ID (should be `f0037a1b2c3d` based on recent migrations). If multiple heads appear, stop and report — resolve before proceeding.

- [ ] **Step 2: Autogenerate migration (for reference only)**

```bash
cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "add stripe billing fields" 2>&1 | tail -5
```

This creates a file in `backend/alembic/versions/`. Note its filename.

- [ ] **Step 3: Rewrite the generated migration with explicit content**

Delete the auto-generated file and create `backend/alembic/versions/f0019a1b2c3d_add_stripe_billing_fields.py` with:

```python
"""Add Stripe billing fields to organizations and StripeEvent table.

Adds nullable stripe_customer_id, stripe_subscription_id, subscription_status,
current_period_end, trial_end, cancel_at_period_end, and has_payment_method
columns to organizations. Creates stripe_events table for webhook idempotency.

Revision ID: f0019a1b2c3d
Revises: f0037a1b2c3d
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "f0019a1b2c3d"
down_revision = "f0037a1b2c3d"
branch_labels = None
depends_on = None


def upgrade():
    # organizations: nullable Stripe state columns
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("subscription_status", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "has_payment_method",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_organizations_stripe_customer_id",
        "organizations",
        ["stripe_customer_id"],
    )

    # stripe_events: idempotency record for processed webhook events
    op.create_table(
        "stripe_events",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("stripe_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_stripe_events_stripe_event_id",
        "stripe_events",
        ["stripe_event_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_stripe_events_stripe_event_id", table_name="stripe_events"
    )
    op.drop_table("stripe_events")

    op.drop_index(
        "ix_organizations_stripe_customer_id", table_name="organizations"
    )
    op.drop_column("organizations", "has_payment_method")
    op.drop_column("organizations", "cancel_at_period_end")
    op.drop_column("organizations", "trial_end")
    op.drop_column("organizations", "current_period_end")
    op.drop_column("organizations", "subscription_status")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
```

- [ ] **Step 4: Apply the migration**

```bash
cd backend && source .venv/bin/activate && alembic upgrade head 2>&1 | tail -5
```

Expected: `INFO [alembic.runtime.migration] Running upgrade f0037a1b2c3d -> f0019a1b2c3d, add stripe billing fields`.

- [ ] **Step 5: Verify columns exist**

```bash
cd backend && source .venv/bin/activate && python -c "
from sqlalchemy import create_engine, inspect
from app.core.config import settings
sync_url = settings.database_url.replace('+asyncpg', '+psycopg2')
# Fallback if psycopg2 not available: use raw URL with a psycopg3 or use SQLAlchemy's default
from sqlalchemy import create_engine
e = create_engine(settings.database_url.replace('+asyncpg', ''))
i = inspect(e)
cols = [c['name'] for c in i.get_columns('organizations')]
print([c for c in cols if 'stripe' in c or 'trial' in c or 'subscription_status' in c or 'current_period' in c or 'cancel_at' in c or 'payment' in c])
print('stripe_events' in i.get_table_names())
"
```

Expected: prints a list containing the seven new columns, then `True`.

If the above fails on the driver, alternative:

```bash
psql -h localhost -U postgres -d batchrite -c "\d organizations" | grep -E "stripe|trial|subscription_status|cancel_at|has_payment"
psql -h localhost -U postgres -d batchrite -c "\d stripe_events"
```

Expected: the seven org columns appear, and the `stripe_events` table shows.

- [ ] **Step 6: Run existing tests (they create tables from metadata, not migrations)**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit -q 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/f0019a1b2c3d_add_stripe_billing_fields.py
git commit -m "feat(billing): Alembic migration for Stripe fields + stripe_events table"
```

---

### Task 4: Add Stripe Settings fields and .env.example

**Files:**
- Modify: `backend/app/core/config.py` (Settings class, around line 138)
- Create: `backend/.env.example`

- [ ] **Step 1: Add Settings fields**

Edit `backend/app/core/config.py`. Find the Settings class. Before `model_config = {...}` (currently around line 140), add:

```python
    # Stripe billing (added F-0019a) -- all optional; endpoints return
    # 503 with a clear message when any required field is unset.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_essentials_price_id: str = ""
    stripe_pro_price_id: str = ""
    essentials_trial_days: int = 30
    stripe_portal_return_url: str = "/settings?tab=billing"

    # Seat caps per tier (added F-0019a). Enterprise has no cap;
    # handled in code by `get_seat_limit(tier)` returning None.
    seat_limit_essentials: int = 5
    seat_limit_pro: int = 25
```

- [ ] **Step 2: Verify config loads**

```bash
cd backend && source .venv/bin/activate && python -c "
from app.core.config import settings
print('stripe_secret_key:', repr(settings.stripe_secret_key))
print('essentials_trial_days:', settings.essentials_trial_days)
"
```

Expected: prints `stripe_secret_key: ''` and `essentials_trial_days: 30`.

- [ ] **Step 3: Create `.env.example`**

Create `backend/.env.example`:

```env
# Batchrite backend environment variables.
# Copy this file to `backend/.env` and fill in real values for local dev.
# Env prefix: BATCHRITE_ (set on every var Python reads via Settings).

# --- Database ---
# BATCHRITE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite

# --- Security ---
# BATCHRITE_SECRET_KEY=change-me-in-production

# --- Stripe (F-0019a) ---
# Test-mode values. Fetched from https://dashboard.stripe.com
# See docs/stripe-setup.md for the full walkthrough.
BATCHRITE_STRIPE_SECRET_KEY=sk_test_placeholder_replace_me
BATCHRITE_STRIPE_WEBHOOK_SECRET=whsec_placeholder_replace_me
BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID=price_placeholder_replace_me
BATCHRITE_STRIPE_PRO_PRICE_ID=price_placeholder_replace_me
# Trial length in days for new Essentials subscriptions.
# Default: 30. Set to 180 during the launch beta (3-6 month free period).
BATCHRITE_ESSENTIALS_TRIAL_DAYS=30
# Per-tier seat caps. Adjust per environment if desired.
BATCHRITE_SEAT_LIMIT_ESSENTIALS=5
BATCHRITE_SEAT_LIMIT_PRO=25
```

- [ ] **Step 4: Confirm `.env.example` is tracked and `backend/.env` is ignored**

```bash
grep -E "^\.env$|^backend/\.env$|^\*\*/\.env$" .gitignore backend/.gitignore 2>/dev/null
```

Expected: at least one match (confirms `.env` is ignored). If no match appears, stop and add `.env` to `.gitignore` before continuing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/.env.example
git commit -m "feat(billing): add Stripe config fields to Settings + .env.example"
```

---

## Phase 2 — Pauses 1 & 2 (Stripe Dashboard Setup)

### PAUSE 1 — Fetch the Stripe test-mode Secret Key

**This task pauses implementation.** The code from Phase 3 onward cannot be tested against real Stripe without this.

- [ ] **Step 1: Hand off to user with this exact message:**

> **PAUSE 1 — I need you to do this on stripe.com before I continue.**
>
> 1. Log in at https://dashboard.stripe.com.
> 2. Confirm top-left shows **"Test mode"** (orange pill). Toggle it on if it's in Live mode.
> 3. Fill in the minimum business profile details Stripe prompts for (name, country). You can skip "Activate payments" entirely — test mode works on an unverified account.
> 4. Left sidebar → **Developers → API keys**.
> 5. Click **"Reveal test key"** on the row labeled **Secret key**.
> 6. Copy the value (starts with `sk_test_...`).
>
> Paste the `sk_test_...` into `backend/.env` (gitignored):
>
> ```
> BATCHRITE_STRIPE_SECRET_KEY=sk_test_<your_value>
> ```
>
> Reply here with "Pause 1 done" once saved, or paste the key value so I can verify the shape (starts with `sk_test_`). **Do not paste this value into any git-tracked file.**

- [ ] **Step 2: Wait for user confirmation before proceeding. Verify the shape only (starts with `sk_test_`)**; never log the full key.

---

### PAUSE 2 — Create Essentials + Pro products; fetch Price IDs

- [ ] **Step 1: Hand off to user with this exact message:**

> **PAUSE 2 — Create two products in Stripe Test mode and copy their Price IDs.**
>
> Still in Test mode:
>
> 1. Left sidebar → **Product catalog** → **Add product**.
> 2. Create **Batchrite Essentials**:
>    - Name: `Batchrite Essentials`
>    - Pricing → **Recurring** → **Monthly**. Amount: any placeholder (e.g. `$29.00 USD`).
>    - Click **Add product**.
>    - On the product page, copy the **Price ID** (starts with `price_`).
> 3. Repeat for **Batchrite Pro** (e.g. `$99.00 USD`). Copy its Price ID.
>
> Paste both IDs into `backend/.env`:
>
> ```
> BATCHRITE_STRIPE_ESSENTIALS_PRICE_ID=price_<essentials>
> BATCHRITE_STRIPE_PRO_PRICE_ID=price_<pro>
> ```
>
> Reply with "Pause 2 done" once saved, and paste the two IDs so I can verify shape.

- [ ] **Step 2: Wait for user confirmation. Verify both IDs start with `price_`.**

---

## Phase 3 — Backend Service Layer

### Task 5: Create stripe_client adapter

**Files:**
- Create: `backend/app/services/billing/__init__.py`
- Create: `backend/app/services/billing/constants.py`
- Create: `backend/app/services/billing/stripe_client.py`
- Test: `backend/tests/unit/services/test_stripe_client.py`

- [ ] **Step 1: Create package marker**

Create `backend/app/services/billing/__init__.py`:

```python
"""Stripe billing services (F-0019a).

Thin adapters around Stripe's Python SDK; test-injectable via get_stripe().
"""
```

- [ ] **Step 2: Create constants module**

Create `backend/app/services/billing/constants.py`:

```python
"""Constants for the billing subsystem."""

from uuid import UUID

# System actor UUID used as actor_id in log_audit calls for webhook-driven
# state changes (where there is no authenticated user). Must be a valid
# UUID literal; does NOT need to exist in the users table since audit_logs
# does not enforce an FK on actor_id. (If an FK is added later, seed this
# UUID as a system user row.)
STRIPE_SYSTEM_ACTOR_ID: UUID = UUID("00000000-0000-0000-0000-00005771419e")
```

- [ ] **Step 3: Write the failing test for stripe_client**

Create `backend/tests/unit/services/test_stripe_client.py`:

```python
import pytest

from app.services.billing import stripe_client


def test_get_stripe_returns_stripe_module_when_configured(monkeypatch):
    """get_stripe() returns the real stripe module when secret key is set."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key",
        "sk_test_fake",
    )
    # Reset the cached client so the monkeypatch takes effect
    stripe_client._reset_cache()

    client = stripe_client.get_stripe()

    import stripe as real_stripe
    assert client is real_stripe
    assert real_stripe.api_key == "sk_test_fake"


def test_get_stripe_raises_when_unconfigured(monkeypatch):
    """get_stripe() raises BillingUnconfiguredError when no secret key."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    with pytest.raises(stripe_client.BillingUnconfiguredError):
        stripe_client.get_stripe()


def test_is_configured_true_when_all_keys_set(monkeypatch):
    """is_configured() returns True iff all required keys are set."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key",
        "sk_test_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_webhook_secret",
        "whsec_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_essentials_price_id",
        "price_ess",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_pro_price_id",
        "price_pro",
    )

    assert stripe_client.is_configured() is True


def test_is_configured_false_when_any_key_missing(monkeypatch):
    """is_configured() returns False when any required key is empty."""
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    assert stripe_client.is_configured() is False


def test_set_fake_client_injects_for_tests(monkeypatch):
    """set_fake_client replaces the stripe module for tests; cleared via _reset_cache."""
    fake = object()
    stripe_client.set_fake_client(fake)
    assert stripe_client.get_stripe() is fake

    stripe_client._reset_cache()
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    with pytest.raises(stripe_client.BillingUnconfiguredError):
        stripe_client.get_stripe()
```

- [ ] **Step 4: Run the test to confirm it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_stripe_client.py -v 2>&1 | tail -15
```

Expected: fails with `ModuleNotFoundError: No module named 'app.services.billing.stripe_client'`.

- [ ] **Step 5: Implement stripe_client**

Create `backend/app/services/billing/stripe_client.py`:

```python
"""Stripe Python SDK adapter.

Single point where we configure stripe.api_key from settings. Provides a
get_stripe() accessor that callers use instead of importing `stripe`
directly; this makes it possible to inject a fake during tests via
set_fake_client().
"""

from typing import Any

from app.core.config import settings


class BillingUnconfiguredError(RuntimeError):
    """Raised when billing code is invoked but Stripe config is missing."""


_cached_client: Any = None
_fake_client: Any = None


def _reset_cache() -> None:
    """Clear cached client. Test-only; not part of public API."""
    global _cached_client, _fake_client
    _cached_client = None
    _fake_client = None


def set_fake_client(fake: Any) -> None:
    """Inject a fake stripe-like object for tests.

    Once called, get_stripe() returns this object instead of the real
    stripe module until _reset_cache() is called.
    """
    global _fake_client
    _fake_client = fake


def is_configured() -> bool:
    """True iff all required Stripe settings are populated."""
    return bool(
        settings.stripe_secret_key
        and settings.stripe_webhook_secret
        and settings.stripe_essentials_price_id
        and settings.stripe_pro_price_id
    )


def get_stripe() -> Any:
    """Return the configured stripe module (or injected fake).

    Raises BillingUnconfiguredError if no secret key is set and no fake
    has been injected.
    """
    global _cached_client
    if _fake_client is not None:
        return _fake_client
    if _cached_client is not None:
        return _cached_client

    if not settings.stripe_secret_key:
        raise BillingUnconfiguredError(
            "Stripe is not configured (BATCHRITE_STRIPE_SECRET_KEY unset)."
        )

    import stripe

    stripe.api_key = settings.stripe_secret_key
    _cached_client = stripe
    return stripe
```

- [ ] **Step 6: Run the test to confirm it passes**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_stripe_client.py -v 2>&1 | tail -15
```

Expected: 5 passing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/billing/ backend/tests/unit/services/test_stripe_client.py
git commit -m "feat(billing): add stripe_client adapter with test-injection support"
```

---

### Task 6: Implement subscription_service.create_trial_subscription

**Files:**
- Create: `backend/app/services/billing/subscription_service.py`
- Test: `backend/tests/unit/services/test_subscription_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/test_subscription_service.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.iam import Organization, User
from app.services.billing import stripe_client, subscription_service


@pytest.fixture(autouse=True)
def reset_stripe_cache():
    yield
    stripe_client._reset_cache()


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.Customer.create.return_value = MagicMock(id="cus_test_123")
    trial_end_ts = int(
        datetime(2026, 5, 23, tzinfo=timezone.utc).timestamp()
    )
    period_end_ts = int(
        datetime(2026, 6, 23, tzinfo=timezone.utc).timestamp()
    )
    fake.Subscription.create.return_value = MagicMock(
        id="sub_test_456",
        status="trialing",
        trial_end=trial_end_ts,
        current_period_end=period_end_ts,
        cancel_at_period_end=False,
    )
    stripe_client.set_fake_client(fake)
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key",
        "sk_test_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_webhook_secret",
        "whsec_x",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_essentials_price_id",
        "price_ess",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_pro_price_id",
        "price_pro",
    )
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.essentials_trial_days",
        30,
    )
    return fake


@pytest.mark.asyncio
async def test_create_trial_subscription_creates_customer_and_subscription(
    db_session, fake_stripe
):
    org = Organization(name="Test Co")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    result = await subscription_service.create_trial_subscription(
        db_session, org, user
    )

    assert result.stripe_customer_id == "cus_test_123"
    assert result.stripe_subscription_id == "sub_test_456"
    assert result.subscription_status == "trialing"
    assert result.trial_end is not None
    assert result.current_period_end is not None

    fake_stripe.Customer.create.assert_called_once()
    kwargs = fake_stripe.Customer.create.call_args.kwargs
    assert kwargs["email"] == "owner@test.co"
    assert kwargs["name"] == "Test Co"
    assert kwargs["metadata"]["org_id"] == str(org.id)

    fake_stripe.Subscription.create.assert_called_once()
    sub_kwargs = fake_stripe.Subscription.create.call_args.kwargs
    assert sub_kwargs["customer"] == "cus_test_123"
    assert sub_kwargs["items"] == [{"price": "price_ess"}]
    assert sub_kwargs["trial_period_days"] == 30
    assert (
        sub_kwargs["trial_settings"]["end_behavior"][
            "missing_payment_method"
        ]
        == "cancel"
    )


@pytest.mark.asyncio
async def test_create_trial_subscription_is_idempotent(
    db_session, fake_stripe
):
    org = Organization(
        name="Test Co", stripe_subscription_id="sub_existing_789"
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    result = await subscription_service.create_trial_subscription(
        db_session, org, user
    )

    assert result.stripe_subscription_id == "sub_existing_789"
    fake_stripe.Customer.create.assert_not_called()
    fake_stripe.Subscription.create.assert_not_called()


@pytest.mark.asyncio
async def test_create_trial_subscription_noop_when_unconfigured(
    db_session, monkeypatch, caplog
):
    # No fake_stripe fixture here; Stripe is genuinely unconfigured
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    org = Organization(name="Test Co")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email="owner@test.co",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    with caplog.at_level("WARNING"):
        result = await subscription_service.create_trial_subscription(
            db_session, org, user
        )

    assert result.stripe_customer_id is None
    assert result.stripe_subscription_id is None
    assert any("Stripe not configured" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_subscription_service.py -v 2>&1 | tail -15
```

Expected: `ModuleNotFoundError` or `AttributeError` on `subscription_service.create_trial_subscription`.

- [ ] **Step 3: Implement create_trial_subscription**

Create `backend/app/services/billing/subscription_service.py`:

```python
"""Organization-facing billing operations: trial subscription, portal session, state.

All functions are async, take a db session, and commit caller-side so they
integrate cleanly into endpoint transactions. Stripe-unconfigured calls
log a warning and no-op (tests assert this) so the app boots without keys.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iam import Organization, User
from app.services.billing import stripe_client

logger = logging.getLogger(__name__)


async def create_trial_subscription(
    db: AsyncSession, org: Organization, user: User
) -> Organization:
    """Create a Stripe customer + trialing Essentials subscription for a new org.

    Idempotent: if `org.stripe_subscription_id` is already set, return the org
    unchanged. No-op with a warning when Stripe is unconfigured (registration
    must not fail just because billing isn't set up locally).

    Does not commit; the caller owns transaction scope.
    """
    if org.stripe_subscription_id:
        return org

    if not stripe_client.is_configured():
        logger.warning(
            "Stripe not configured; skipping trial subscription for org %s",
            org.id,
        )
        return org

    stripe = stripe_client.get_stripe()

    customer = stripe.Customer.create(
        email=user.email,
        name=org.name,
        metadata={
            "org_id": str(org.id),
            "user_id": str(user.id),
        },
    )

    subscription = stripe.Subscription.create(
        customer=customer.id,
        items=[{"price": settings.stripe_essentials_price_id}],
        trial_period_days=settings.essentials_trial_days,
        trial_settings={
            "end_behavior": {"missing_payment_method": "cancel"}
        },
        metadata={"org_id": str(org.id)},
    )

    org.stripe_customer_id = customer.id
    org.stripe_subscription_id = subscription.id
    org.subscription_status = subscription.status
    org.trial_end = _ts_to_dt(getattr(subscription, "trial_end", None))
    org.current_period_end = _ts_to_dt(
        getattr(subscription, "current_period_end", None)
    )
    org.cancel_at_period_end = bool(
        getattr(subscription, "cancel_at_period_end", False)
    )
    return org


def _ts_to_dt(ts: Optional[int]) -> Optional[datetime]:
    """Stripe returns Unix timestamps; convert to timezone-aware datetime."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_subscription_service.py -v 2>&1 | tail -15
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/billing/subscription_service.py backend/tests/unit/services/test_subscription_service.py
git commit -m "feat(billing): create_trial_subscription service (idempotent; no-op when unconfigured)"
```

---

### Task 7: Add create_portal_session and get_subscription_state

**Files:**
- Modify: `backend/app/services/billing/subscription_service.py`
- Modify: `backend/tests/unit/services/test_subscription_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/unit/services/test_subscription_service.py`:

```python
@pytest.mark.asyncio
async def test_create_portal_session_returns_url(db_session, fake_stripe):
    fake_stripe.billing_portal.Session.create.return_value = MagicMock(
        url="https://billing.stripe.com/session/abc"
    )
    org = Organization(name="X", stripe_customer_id="cus_xyz")
    db_session.add(org)
    await db_session.flush()

    url = await subscription_service.create_portal_session(
        org, return_url="https://app.batchrite.local/settings?tab=billing"
    )

    assert url == "https://billing.stripe.com/session/abc"
    fake_stripe.billing_portal.Session.create.assert_called_once_with(
        customer="cus_xyz",
        return_url="https://app.batchrite.local/settings?tab=billing",
    )


@pytest.mark.asyncio
async def test_create_portal_session_raises_when_no_customer(db_session):
    org = Organization(name="X")  # no stripe_customer_id
    db_session.add(org)
    await db_session.flush()

    with pytest.raises(ValueError, match="no Stripe customer"):
        await subscription_service.create_portal_session(
            org, return_url="https://x"
        )


def test_get_subscription_state_pro_trialing_with_card():
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=5)
    period_end = now + timedelta(days=5)

    org = Organization(
        name="X",
        subscription_tier="pro",
        subscription_status="trialing",
        trial_end=trial_end,
        current_period_end=period_end,
        cancel_at_period_end=False,
        has_payment_method=True,
    )

    state = subscription_service.get_subscription_state(org)

    assert state["tier"] == "pro"
    assert state["status"] == "trialing"
    assert state["trial_end"] == trial_end
    assert state["current_period_end"] == period_end
    assert state["cancel_at_period_end"] is False
    assert state["has_payment_method"] is True
    assert state["days_remaining_in_trial"] in (5, 4)  # ±1 for clock drift
    assert state["is_locked_out"] is False


def test_get_subscription_state_canceled_is_locked_out():
    org = Organization(
        name="X",
        subscription_tier="essentials",
        subscription_status="canceled",
        trial_end=None,
        current_period_end=None,
        cancel_at_period_end=False,
        has_payment_method=False,
    )

    state = subscription_service.get_subscription_state(org)

    assert state["is_locked_out"] is True
    assert state["status"] == "canceled"
    assert state["days_remaining_in_trial"] is None


def test_get_subscription_state_past_due_is_locked_out():
    org = Organization(
        name="X",
        subscription_tier="pro",
        subscription_status="past_due",
        has_payment_method=True,
    )

    state = subscription_service.get_subscription_state(org)

    assert state["is_locked_out"] is True


def test_get_subscription_state_active_not_trialing_no_days_remaining():
    from datetime import timedelta
    org = Organization(
        name="X",
        subscription_tier="pro",
        subscription_status="active",
        trial_end=datetime.now(timezone.utc) - timedelta(days=10),
        has_payment_method=True,
    )

    state = subscription_service.get_subscription_state(org)

    assert state["status"] == "active"
    assert state["days_remaining_in_trial"] is None  # only report while trialing
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_subscription_service.py::test_create_portal_session_returns_url tests/unit/services/test_subscription_service.py::test_get_subscription_state_canceled_is_locked_out -v 2>&1 | tail -10
```

Expected: failures about missing `create_portal_session` / `get_subscription_state`.

- [ ] **Step 3: Implement both functions**

Append to `backend/app/services/billing/subscription_service.py`:

```python
async def create_portal_session(org: Organization, return_url: str) -> str:
    """Create a Stripe Customer Portal session URL for this org's customer."""
    if not org.stripe_customer_id:
        raise ValueError(
            f"Organization {org.id} has no Stripe customer; "
            "cannot open a billing portal session."
        )

    stripe = stripe_client.get_stripe()
    session = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=return_url,
    )
    return session.url


_LOCKED_OUT_STATUSES = {"canceled", "past_due", "unpaid"}


def get_subscription_state(org: Organization) -> dict:
    """Read-only projection of the org's current billing state.

    Reads columns populated by the registration flow and webhook handler;
    does not hit Stripe. Adds two derived fields:
      - days_remaining_in_trial: int when status=trialing, else None
      - is_locked_out: True when status in LOCKED_OUT_STATUSES
    """
    days_remaining: Optional[int] = None
    if org.subscription_status == "trialing" and org.trial_end is not None:
        now = datetime.now(timezone.utc)
        delta = org.trial_end - now
        days_remaining = max(0, (delta.days + (1 if delta.seconds > 0 else 0)))

    return {
        "tier": org.subscription_tier,
        "status": org.subscription_status,
        "trial_end": org.trial_end,
        "days_remaining_in_trial": days_remaining,
        "current_period_end": org.current_period_end,
        "cancel_at_period_end": org.cancel_at_period_end,
        "has_payment_method": org.has_payment_method,
        "is_locked_out": org.subscription_status in _LOCKED_OUT_STATUSES,
    }
```

- [ ] **Step 4: Run all subscription_service tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_subscription_service.py -v 2>&1 | tail -20
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/billing/subscription_service.py backend/tests/unit/services/test_subscription_service.py
git commit -m "feat(billing): create_portal_session and get_subscription_state helpers"
```

---

### Task 8: Implement webhook_handler with per-event dispatch

**Files:**
- Create: `backend/app/services/billing/webhook_handler.py`
- Create: `backend/tests/unit/services/test_webhook_handler.py`
- Create: `backend/tests/fixtures/stripe/*.json` (5 fixture files)

- [ ] **Step 1: Create fixture directory and sample payloads**

```bash
mkdir -p backend/tests/fixtures/stripe
```

Create `backend/tests/fixtures/stripe/customer_subscription_updated_upgrade.json`:

```json
{
    "id": "evt_test_upgrade_001",
    "object": "event",
    "type": "customer.subscription.updated",
    "created": 1714000000,
    "data": {
        "object": {
            "id": "sub_test_456",
            "object": "subscription",
            "customer": "cus_test_123",
            "status": "active",
            "trial_end": null,
            "current_period_end": 1716678400,
            "cancel_at_period_end": false,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_pro",
                            "object": "price"
                        }
                    }
                ]
            }
        }
    }
}
```

Create `backend/tests/fixtures/stripe/customer_subscription_updated_downgrade.json`:

```json
{
    "id": "evt_test_downgrade_001",
    "object": "event",
    "type": "customer.subscription.updated",
    "created": 1714000001,
    "data": {
        "object": {
            "id": "sub_test_456",
            "object": "subscription",
            "customer": "cus_test_123",
            "status": "active",
            "trial_end": null,
            "current_period_end": 1716678400,
            "cancel_at_period_end": true,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_pro",
                            "object": "price"
                        }
                    }
                ]
            }
        }
    }
}
```

Create `backend/tests/fixtures/stripe/customer_subscription_deleted.json`:

```json
{
    "id": "evt_test_deleted_001",
    "object": "event",
    "type": "customer.subscription.deleted",
    "created": 1714000002,
    "data": {
        "object": {
            "id": "sub_test_456",
            "object": "subscription",
            "customer": "cus_test_123",
            "status": "canceled",
            "trial_end": null,
            "current_period_end": 1716678400,
            "cancel_at_period_end": false,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_ess",
                            "object": "price"
                        }
                    }
                ]
            }
        }
    }
}
```

Create `backend/tests/fixtures/stripe/invoice_payment_failed.json`:

```json
{
    "id": "evt_test_payment_failed_001",
    "object": "event",
    "type": "invoice.payment_failed",
    "created": 1714000003,
    "data": {
        "object": {
            "id": "in_test_abc",
            "object": "invoice",
            "customer": "cus_test_123",
            "subscription": "sub_test_456"
        }
    }
}
```

Create `backend/tests/fixtures/stripe/customer_subscription_created.json`:

```json
{
    "id": "evt_test_created_001",
    "object": "event",
    "type": "customer.subscription.created",
    "created": 1713999999,
    "data": {
        "object": {
            "id": "sub_test_456",
            "object": "subscription",
            "customer": "cus_test_123",
            "status": "trialing",
            "trial_end": 1716592000,
            "current_period_end": 1716678400,
            "cancel_at_period_end": false,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_ess",
                            "object": "price"
                        }
                    }
                ]
            }
        }
    }
}
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/unit/services/test_webhook_handler.py`:

```python
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.billing import StripeEvent
from app.models.execution import AuditLog
from app.models.iam import Organization
from app.services.billing import webhook_handler

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "stripe"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
async def org_with_pro_trial(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.billing.webhook_handler.settings.stripe_essentials_price_id",
        "price_ess",
    )
    monkeypatch.setattr(
        "app.services.billing.webhook_handler.settings.stripe_pro_price_id",
        "price_pro",
    )
    org = Organization(
        name="Test",
        stripe_customer_id="cus_test_123",
        stripe_subscription_id="sub_test_456",
        subscription_tier="essentials",
        subscription_status="trialing",
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest.mark.asyncio
async def test_subscription_updated_upgrade_flips_tier_and_writes_audit(
    db_session, org_with_pro_trial
):
    event = _load("customer_subscription_updated_upgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_tier == "pro"
    assert org_with_pro_trial.subscription_status == "active"
    assert org_with_pro_trial.cancel_at_period_end is False

    audit_rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == org_with_pro_trial.id)
    )).scalars().all()
    assert any(
        row.action == "UPDATE"
        and "subscription_tier" in (row.changes or {})
        and row.changes["subscription_tier"] == ["essentials", "pro"]
        for row in audit_rows
    )


@pytest.mark.asyncio
async def test_subscription_updated_downgrade_sets_cancel_flag_no_tier_change(
    db_session, org_with_pro_trial
):
    # First upgrade to pro so downgrade is meaningful
    org_with_pro_trial.subscription_tier = "pro"
    org_with_pro_trial.subscription_status = "active"
    await db_session.flush()

    event = _load("customer_subscription_updated_downgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_tier == "pro"  # unchanged until period ends
    assert org_with_pro_trial.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_subscription_deleted_sets_canceled_and_writes_audit(
    db_session, org_with_pro_trial
):
    event = _load("customer_subscription_deleted")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_status == "canceled"

    audit_rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == org_with_pro_trial.id)
    )).scalars().all()
    assert any(
        row.action == "UPDATE"
        and row.changes
        and row.changes.get("subscription_status") == ["trialing", "canceled"]
        for row in audit_rows
    )


@pytest.mark.asyncio
async def test_invoice_payment_failed_sets_past_due(
    db_session, org_with_pro_trial
):
    org_with_pro_trial.subscription_status = "active"
    await db_session.flush()

    event = _load("invoice_payment_failed")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    await db_session.refresh(org_with_pro_trial)
    assert org_with_pro_trial.subscription_status == "past_due"


@pytest.mark.asyncio
async def test_handle_event_is_idempotent(db_session, org_with_pro_trial):
    event = _load("customer_subscription_updated_upgrade")

    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()

    audit_rows = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_id == org_with_pro_trial.id
        )
    )).scalars().all()
    tier_change_rows = [
        r for r in audit_rows
        if r.changes and "subscription_tier" in r.changes
    ]
    assert len(tier_change_rows) == 1  # second apply was a no-op

    events_seen = (await db_session.execute(
        select(StripeEvent).where(
            StripeEvent.stripe_event_id == event["id"]
        )
    )).scalars().all()
    assert len(events_seen) == 1


@pytest.mark.asyncio
async def test_handle_event_unknown_customer_logs_and_returns(
    db_session, caplog
):
    # No org with cus_test_123; StripeEvent row should still be created to dedupe
    event = _load("customer_subscription_updated_upgrade")
    with caplog.at_level("WARNING"):
        await webhook_handler.handle_event(db_session, event)
        await db_session.flush()

    events_seen = (await db_session.execute(
        select(StripeEvent).where(
            StripeEvent.stripe_event_id == event["id"]
        )
    )).scalars().all()
    assert len(events_seen) == 1
    assert any("no matching org" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 3: Run the tests — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_webhook_handler.py -v 2>&1 | tail -15
```

Expected: `ModuleNotFoundError` on `webhook_handler`.

- [ ] **Step 4: Implement webhook_handler**

Create `backend/app/services/billing/webhook_handler.py`:

```python
"""Dispatch Stripe webhook events and reconcile org billing state.

Contract:
  - Called with a parsed event dict (already signature-verified by the endpoint).
  - Idempotent: writes a StripeEvent row keyed by event ID; duplicate deliveries
    short-circuit before mutating org state.
  - Writes audit log entries on subscription_tier or subscription_status changes
    with before/after values.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import StripeEvent
from app.models.iam import Organization
from app.services.billing.constants import STRIPE_SYSTEM_ACTOR_ID
from app.services.core.audit import log_audit

logger = logging.getLogger(__name__)


async def handle_event(db: AsyncSession, event: dict[str, Any]) -> None:
    """Dispatch a Stripe webhook event.

    Called from POST /billing/webhook after signature verification. Does not
    commit; the caller owns transaction scope.
    """
    event_id = event["id"]
    event_type = event["type"]

    # Idempotency: has this event ID been processed before?
    existing = await db.execute(
        select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(
            "Stripe event %s (%s) already processed; skipping.",
            event_id,
            event_type,
        )
        return

    # Mark the event as seen BEFORE mutating state so a crash between mutation
    # and commit still leaves us idempotent on retry (caller's transaction
    # rolls back the StripeEvent row too, which is fine — Stripe retries).
    db.add(StripeEvent(stripe_event_id=event_id, event_type=event_type))

    handlers = {
        "customer.subscription.created": _apply_subscription_state,
        "customer.subscription.updated": _apply_subscription_state,
        "customer.subscription.deleted": _apply_subscription_deleted,
        "invoice.payment_failed": _apply_invoice_payment_failed,
        "checkout.session.completed": _apply_checkout_completed,
    }
    handler = handlers.get(event_type)
    if handler is None:
        logger.info("Ignoring unhandled Stripe event type: %s", event_type)
        return

    await handler(db, event["data"]["object"])


async def _apply_subscription_state(
    db: AsyncSession, subscription: dict[str, Any]
) -> None:
    """Reconcile org state from a subscription.created or subscription.updated payload."""
    customer_id = subscription["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe subscription event for customer %s has no matching org",
            customer_id,
        )
        return

    new_tier = _tier_from_price_id(_price_id(subscription))
    new_status = subscription["status"]
    changes: dict[str, list[Any]] = {}
    if new_tier is not None and org.subscription_tier != new_tier:
        changes["subscription_tier"] = [org.subscription_tier, new_tier]
        org.subscription_tier = new_tier
    if org.subscription_status != new_status:
        changes["subscription_status"] = [org.subscription_status, new_status]
        org.subscription_status = new_status

    org.stripe_subscription_id = subscription["id"]
    org.trial_end = _ts_to_dt(subscription.get("trial_end"))
    org.current_period_end = _ts_to_dt(subscription.get("current_period_end"))
    org.cancel_at_period_end = bool(
        subscription.get("cancel_at_period_end", False)
    )

    if changes:
        await log_audit(
            db,
            actor_id=STRIPE_SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes=changes,
        )


async def _apply_subscription_deleted(
    db: AsyncSession, subscription: dict[str, Any]
) -> None:
    customer_id = subscription["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe subscription.deleted for customer %s has no matching org",
            customer_id,
        )
        return

    changes: dict[str, list[Any]] = {}
    if org.subscription_status != "canceled":
        changes["subscription_status"] = [org.subscription_status, "canceled"]
        org.subscription_status = "canceled"
    # Defensive: revert tier to essentials if somehow left on pro
    if org.subscription_tier == "pro":
        changes["subscription_tier"] = ["pro", "essentials"]
        org.subscription_tier = "essentials"

    org.cancel_at_period_end = False

    if changes:
        await log_audit(
            db,
            actor_id=STRIPE_SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes=changes,
        )


async def _apply_invoice_payment_failed(
    db: AsyncSession, invoice: dict[str, Any]
) -> None:
    customer_id = invoice["customer"]
    org = await _org_by_customer(db, customer_id)
    if org is None:
        logger.warning(
            "Stripe invoice.payment_failed for customer %s has no matching org",
            customer_id,
        )
        return

    if org.subscription_status != "past_due":
        await log_audit(
            db,
            actor_id=STRIPE_SYSTEM_ACTOR_ID,
            action="UPDATE",
            entity_type="Organization",
            entity_id=org.id,
            changes={
                "subscription_status": [org.subscription_status, "past_due"]
            },
        )
        org.subscription_status = "past_due"


async def _apply_checkout_completed(
    db: AsyncSession, session_obj: dict[str, Any]
) -> None:
    # We don't use Checkout directly (Portal handles upgrades), but handle
    # defensively in case Stripe fires this during Portal-driven flows.
    # Reconciliation happens via the subsequent subscription.updated event.
    logger.info(
        "Received checkout.session.completed for customer %s; "
        "awaiting subscription.updated for state reconciliation.",
        session_obj.get("customer"),
    )


async def _org_by_customer(
    db: AsyncSession, customer_id: str
) -> Optional[Organization]:
    result = await db.execute(
        select(Organization).where(
            Organization.stripe_customer_id == customer_id
        )
    )
    return result.scalar_one_or_none()


def _price_id(subscription: dict[str, Any]) -> Optional[str]:
    items = subscription.get("items", {}).get("data", [])
    if not items:
        return None
    return items[0].get("price", {}).get("id")


def _tier_from_price_id(price_id: Optional[str]) -> Optional[str]:
    if price_id is None:
        return None
    if price_id == settings.stripe_essentials_price_id:
        return "essentials"
    if price_id == settings.stripe_pro_price_id:
        return "pro"
    return None


def _ts_to_dt(ts: Optional[int]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)
```

- [ ] **Step 5: Run webhook_handler tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_webhook_handler.py -v 2>&1 | tail -20
```

Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/billing/webhook_handler.py backend/app/services/billing/constants.py backend/tests/unit/services/test_webhook_handler.py backend/tests/fixtures/stripe/
git commit -m "feat(billing): webhook_handler dispatch with idempotency + audit logging"
```

---

## Phase 4 — Registration Integration

### Task 9: Wire create_trial_subscription into the registration flow

**Files:**
- Modify: `backend/app/api/endpoints/auth.py` (lines 112-189 — the `register` endpoint)
- Create: `backend/tests/integration/test_registration_billing.py`

- [ ] **Step 1: Write failing integration test**

Create `backend/tests/integration/test_registration_billing.py`:

```python
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization, User
from app.services.billing import stripe_client


@pytest.fixture(autouse=True)
def reset_stripe_cache():
    yield
    stripe_client._reset_cache()


@pytest.fixture
def configured_fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.Customer.create.return_value = MagicMock(id="cus_reg_111")
    fake.Subscription.create.return_value = MagicMock(
        id="sub_reg_222",
        status="trialing",
        trial_end=1716000000,
        current_period_end=1718000000,
        cancel_at_period_end=False,
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )
    return fake


@pytest.mark.asyncio
async def test_register_creates_trial_subscription_when_stripe_configured(
    client: AsyncClient, db_session, configured_fake_stripe
):
    resp = await client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "password123",
            "full_name": "New User",
        },
    )
    assert resp.status_code == 200

    user = (await db_session.execute(
        select(User).where(User.email == "newuser@example.com")
    )).scalar_one()
    org = (await db_session.execute(
        select(Organization).where(Organization.id == user.selected_org_id)
    )).scalar_one()

    assert org.stripe_customer_id == "cus_reg_111"
    assert org.stripe_subscription_id == "sub_reg_222"
    assert org.subscription_status == "trialing"


@pytest.mark.asyncio
async def test_register_succeeds_without_stripe_configured(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    resp = await client.post(
        "/auth/register",
        json={
            "email": "unconfigured@example.com",
            "password": "password123",
            "full_name": "NC User",
        },
    )
    assert resp.status_code == 200

    user = (await db_session.execute(
        select(User).where(User.email == "unconfigured@example.com")
    )).scalar_one()
    org = (await db_session.execute(
        select(Organization).where(Organization.id == user.selected_org_id)
    )).scalar_one()

    assert org.stripe_customer_id is None
    assert org.stripe_subscription_id is None
```

- [ ] **Step 2: Run test — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_registration_billing.py -v 2>&1 | tail -15
```

Expected: first test fails — `org.stripe_customer_id` is None. Second test passes already (registration currently doesn't touch Stripe).

- [ ] **Step 3: Modify the register endpoint**

Edit `backend/app/api/endpoints/auth.py`. Locate the `register` function (around line 112-189). Between the `db.add(OrganizationMember(...))` block (ends around line 165) and the `# Seed "My First Project"` block (starts around line 167), insert the trial-subscription call. The final structure should look like this — find your current code and add the new block before the "Seed My First Project" comment:

```python
    db.add(OrganizationMember(
        user_id=user.id,
        organization_id=org.id,
        role="ADMIN",
    ))

    # Create Stripe trialing Essentials subscription (F-0019a).
    # No-op if Stripe is unconfigured (logs a warning); safe to call before commit.
    from app.services.billing.subscription_service import (
        create_trial_subscription,
    )
    await create_trial_subscription(db, org, user)

    # Seed "My First Project" for onboarding (F-0015)
    from app.models.science import Project
    ...
```

(Keep the rest of the function unchanged.)

- [ ] **Step 4: Run integration tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_registration_billing.py -v 2>&1 | tail -15
```

Expected: both tests pass.

- [ ] **Step 5: Confirm existing auth tests still pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_auth_api.py -q 2>&1 | tail -10
```

Expected: all passing (no regressions).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_registration_billing.py
git commit -m "feat(billing): provision trialing Essentials subscription on registration"
```

---

## Phase 5 — Permission Deps

### Task 10: Add require_org_role dep (ADMIN ≥ BILLING ≥ MEMBER hierarchy)

**Files:**
- Modify: `backend/app/core/deps.py`
- Create: `backend/tests/unit/core/test_deps_require_org_role.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/core/test_deps_require_org_role.py`:

```python
import pytest
from fastapi import HTTPException

from app.core.deps import require_org_role
from app.models.iam import OrganizationMember, OrgRole


@pytest.mark.asyncio
async def test_admin_satisfies_billing_requirement(
    db_session, test_org, test_user
):
    db_session.add(OrganizationMember(
        user_id=test_user.id,
        organization_id=test_org.id,
        role=OrgRole.ADMIN.value,
    ))
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_billing_satisfies_billing_requirement(
    db_session, test_org, test_user
):
    db_session.add(OrganizationMember(
        user_id=test_user.id,
        organization_id=test_org.id,
        role=OrgRole.BILLING.value,
    ))
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_member_rejected_for_billing_requirement(
    db_session, test_org, test_user
):
    db_session.add(OrganizationMember(
        user_id=test_user.id,
        organization_id=test_org.id,
        role=OrgRole.MEMBER.value,
    ))
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_org_role(OrgRole.BILLING)
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_no_membership_rejected(db_session, test_user):
    test_user.selected_org_id = None
    dep = require_org_role(OrgRole.BILLING)
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/core/test_deps_require_org_role.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'require_org_role' from 'app.core.deps'`.

- [ ] **Step 3: Implement the dep**

Edit `backend/app/core/deps.py`. After the existing `require_tier` function (ends around line 140), append:

```python
def require_org_role(required_role: "OrgRole"):
    """Factory that returns a dependency enforcing a minimum OrgRole.

    Treats the three roles as a hierarchy: ADMIN >= BILLING >= MEMBER.
    An ADMIN implicitly satisfies BILLING or MEMBER requirements.
    """
    from app.models.iam import OrganizationMember, OrgRole

    _RANK = {
        OrgRole.ADMIN: 2,
        OrgRole.BILLING: 1,
        OrgRole.MEMBER: 0,
    }

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if user.selected_org_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No organization selected",
            )
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id == user.selected_org_id,
                OrganizationMember.archived == False,  # noqa: E712
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
            )
        user_rank = _RANK.get(OrgRole(member.role), -1)
        required_rank = _RANK[required_role]
        if user_rank < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role.value} role or above",
            )
        return user

    return _check
```

Also confirm the top-of-file has the forward reference string typing. If `"OrgRole"` complains, add `from app.models.iam import OrgRole` at top of file.

- [ ] **Step 4: Run tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/core/test_deps_require_org_role.py -v 2>&1 | tail -15
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/deps.py backend/tests/unit/core/test_deps_require_org_role.py
git commit -m "feat(deps): add require_org_role with ADMIN>=BILLING>=MEMBER hierarchy"
```

---

### Task 11: Add require_active_subscription dep

**Files:**
- Modify: `backend/app/core/deps.py`
- Create: `backend/tests/unit/core/test_deps_require_active_subscription.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/core/test_deps_require_active_subscription.py`:

```python
import pytest
from fastapi import HTTPException

from app.core.deps import require_active_subscription


@pytest.mark.asyncio
async def test_active_status_passes(db_session, test_org, test_user):
    test_org.subscription_status = "active"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_trialing_status_passes(db_session, test_org, test_user):
    test_org.subscription_status = "trialing"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_null_status_passes_for_pre_billing_orgs(
    db_session, test_org, test_user
):
    """Existing orgs without Stripe state aren't locked out."""
    test_org.subscription_status = None
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    result = await dep(user=test_user, db=db_session)
    assert result is test_user


@pytest.mark.asyncio
async def test_canceled_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "canceled"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "subscription_required"
    assert exc.value.detail["status"] == "canceled"


@pytest.mark.asyncio
async def test_past_due_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "past_due"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_unpaid_status_raises_402(db_session, test_org, test_user):
    test_org.subscription_status = "unpaid"
    await db_session.flush()
    test_user.selected_org_id = test_org.id

    dep = require_active_subscription()
    with pytest.raises(HTTPException) as exc:
        await dep(user=test_user, db=db_session)
    assert exc.value.status_code == 402
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/core/test_deps_require_active_subscription.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'require_active_subscription'`.

- [ ] **Step 3: Implement the dep**

Edit `backend/app/core/deps.py`. Append after `require_org_role`:

```python
_LOCKED_OUT_STATUSES = frozenset({"canceled", "past_due", "unpaid"})


def require_active_subscription():
    """Factory returning a dep that 402s if the user's org is locked out.

    Layered after require_permission / require_org_role on write endpoints.
    Reads org.subscription_status from the DB (not JWT, which is stale).
    Orgs with NULL status (pre-billing, not yet provisioned) pass through.
    """
    from app.models.iam import Organization

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if user.selected_org_id is None:
            return user  # no org selected -> other deps will 403 if needed
        org = await db.get(Organization, user.selected_org_id)
        if org is None:
            return user
        if org.subscription_status in _LOCKED_OUT_STATUSES:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "subscription_required",
                    "message": (
                        "Your subscription is not active. "
                        "Add a payment method to continue."
                    ),
                    "status": org.subscription_status,
                },
            )
        return user

    return _check
```

- [ ] **Step 4: Run tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/core/test_deps_require_active_subscription.py -v 2>&1 | tail -15
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/deps.py backend/tests/unit/core/test_deps_require_active_subscription.py
git commit -m "feat(deps): add require_active_subscription for write-lockout enforcement"
```

---

### Task 11b: seat_limits service + unit tests

**Files:**
- Create: `backend/app/services/billing/seat_limits.py`
- Create: `backend/tests/unit/services/test_seat_limits.py`

The `GET /billing/subscription` handler in Task 13 will consume `get_seat_count` and `get_seat_limit` from this service. Ship it before the endpoint so the handler can import it cleanly.

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/unit/services/test_seat_limits.py`:

```python
from uuid import uuid4

import pytest
from httpx import HTTPError
from fastapi import HTTPException

from app.models.iam import (
    Organization,
    OrganizationMember,
    SubscriptionTier,
    User,
)
from app.services.billing import seat_limits


@pytest.mark.asyncio
async def test_get_seat_limit_per_tier():
    # Config defaults from Settings: essentials=5, pro=25, enterprise=None
    assert seat_limits.get_seat_limit(SubscriptionTier.ESSENTIALS) == 5
    assert seat_limits.get_seat_limit(SubscriptionTier.PRO) == 25
    assert seat_limits.get_seat_limit(SubscriptionTier.ENTERPRISE) is None


@pytest.mark.asyncio
async def test_get_seat_count_counts_only_active(db_session, test_org):
    active_user = User(email="a@x.com", hashed_password="x")
    archived_user = User(email="b@x.com", hashed_password="x")
    db_session.add_all([active_user, archived_user])
    await db_session.flush()
    db_session.add_all([
        OrganizationMember(user_id=active_user.id, organization_id=test_org.id, role="MEMBER", archived=False),
        OrganizationMember(user_id=archived_user.id, organization_id=test_org.id, role="MEMBER", archived=True),
    ])
    await db_session.flush()
    # test_org's creating user was already added as ADMIN in the fixture (1 seat).
    # Plus our 1 new active = 2 active total. Archived doesn't count.
    count = await seat_limits.get_seat_count(db_session, test_org.id)
    assert count == 2


@pytest.mark.asyncio
async def test_check_seat_capacity_allows_when_under_cap(db_session, test_org):
    # test_org has 1 member (creator); Essentials cap is 5.
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.flush()
    # Should not raise.
    await seat_limits.check_seat_capacity(db_session, test_org)


@pytest.mark.asyncio
async def test_check_seat_capacity_blocks_when_at_cap(db_session, test_org):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    # Fill to the cap (5 total active members). test_org already has 1 from fixture; add 4 more.
    for i in range(4):
        u = User(email=f"fill{i}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(OrganizationMember(user_id=u.id, organization_id=test_org.id, role="MEMBER", archived=False))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await seat_limits.check_seat_capacity(db_session, test_org)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "seat_limit_reached"
    assert exc.value.detail["tier"] == "essentials"
    assert exc.value.detail["limit"] == 5
    assert exc.value.detail["current"] == 5


@pytest.mark.asyncio
async def test_check_seat_capacity_allows_enterprise_at_any_count(db_session, test_org):
    test_org.subscription_tier = SubscriptionTier.ENTERPRISE
    db_session.add(test_org)
    # Add 30 members — well over any numeric cap.
    for i in range(30):
        u = User(email=f"big{i}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(OrganizationMember(user_id=u.id, organization_id=test_org.id, role="MEMBER", archived=False))
    await db_session.flush()
    # Enterprise has no cap — should not raise.
    await seat_limits.check_seat_capacity(db_session, test_org)
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_seat_limits.py -v 2>&1 | tail -10
```

Expected: failures about missing `app.services.billing.seat_limits` module.

- [ ] **Step 3: Write the service**

Create `backend/app/services/billing/seat_limits.py`:

```python
"""Per-tier seat caps.

Policy:
  - Essentials: `settings.seat_limit_essentials` (default 5).
  - Pro: `settings.seat_limit_pro` (default 25).
  - Enterprise: unlimited (None).

Enforcement:
  - `check_seat_capacity` raises HTTPException(403) if the org has already hit its cap.
    Callers invoke this immediately before inserting a new non-archived OrganizationMember.
  - Downgrades (via Stripe Portal) are NOT blocked here — they flow through the webhook
    handler unchanged. The resulting overage is surfaced via `seat_limit_exceeded` in
    `GET /billing/subscription`.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iam import Organization, OrganizationMember, SubscriptionTier


def get_seat_limit(tier: SubscriptionTier | str | None) -> int | None:
    """Return the seat cap for a tier, or None for unlimited / unknown tiers."""
    if tier == SubscriptionTier.ESSENTIALS or tier == "essentials":
        return settings.seat_limit_essentials
    if tier == SubscriptionTier.PRO or tier == "pro":
        return settings.seat_limit_pro
    if tier == SubscriptionTier.ENTERPRISE or tier == "enterprise":
        return None
    return None


async def get_seat_count(db: AsyncSession, org_id: UUID) -> int:
    """Count non-archived memberships for an org."""
    result = await db.execute(
        select(func.count()).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.archived == False,  # noqa: E712
        )
    )
    return int(result.scalar() or 0)


async def check_seat_capacity(db: AsyncSession, org: Organization) -> None:
    """Raise HTTPException(403, seat_limit_reached) if adding a member would exceed the cap.

    Call BEFORE inserting a new OrganizationMember row. Callers that reactivate
    an existing archived member should skip this check — the count doesn't change.
    """
    limit = get_seat_limit(org.subscription_tier)
    if limit is None:
        return  # Enterprise / unlimited
    current = await get_seat_count(db, org.id)
    if current >= limit:
        tier_str = (
            org.subscription_tier.value
            if hasattr(org.subscription_tier, "value")
            else str(org.subscription_tier)
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "seat_limit_reached",
                "message": (
                    f"Your {tier_str.capitalize()} plan allows up to {limit} "
                    "members. Upgrade to Pro to add more."
                ),
                "tier": tier_str,
                "limit": limit,
                "current": current,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_seat_limits.py -v 2>&1 | tail -15
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/billing/seat_limits.py backend/tests/unit/services/test_seat_limits.py
git commit -m "feat(billing): seat_limits service — per-tier cap enforcement primitives"
```

---

## Phase 6 — Billing Endpoints

### Task 12: Pydantic schemas for billing

**Files:**
- Create: `backend/app/schemas/billing.py`

- [ ] **Step 1: Write the schema file**

Create `backend/app/schemas/billing.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SubscriptionStateResponse(BaseModel):
    tier: str  # essentials | pro | enterprise
    status: Optional[str]  # active | trialing | past_due | canceled | incomplete | None
    trial_end: Optional[datetime]
    days_remaining_in_trial: Optional[int]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    has_payment_method: bool
    is_locked_out: bool
    seat_count: int
    seat_limit: Optional[int]  # None for Enterprise (unlimited)
    seat_limit_exceeded: bool

    model_config = ConfigDict(from_attributes=True)


class PortalSessionRequest(BaseModel):
    return_url: Optional[str] = None


class PortalSessionResponse(BaseModel):
    url: str
```

- [ ] **Step 2: Smoke-check imports**

```bash
cd backend && source .venv/bin/activate && python -c "
from app.schemas.billing import SubscriptionStateResponse, PortalSessionRequest, PortalSessionResponse
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/billing.py
git commit -m "feat(billing): Pydantic schemas for subscription and portal session"
```

---

### Task 13: Billing router with GET /subscription and POST /portal-session

**Files:**
- Create: `backend/app/api/endpoints/billing.py`
- Modify: `backend/app/main.py` (around line 356-384 — router imports and registrations)
- Create: `backend/tests/integration/test_billing_endpoints.py`

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/integration/test_billing_endpoints.py`:

```python
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.iam import Organization, OrganizationMember, OrgRole
from app.services.billing import stripe_client


@pytest.fixture(autouse=True)
def reset_stripe_cache():
    yield
    stripe_client._reset_cache()


@pytest.fixture
def configured_fake_stripe(monkeypatch):
    fake = MagicMock()
    fake.billing_portal.Session.create.return_value = MagicMock(
        url="https://billing.stripe.com/session/xyz"
    )
    stripe_client.set_fake_client(fake)
    for key in (
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_essentials_price_id",
        "stripe_pro_price_id",
    ):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )
    return fake


async def _make_billing_user(db_session, role: str = OrgRole.ADMIN.value):
    from app.core.security import hash_password
    from app.models.iam import User
    org = Organization(
        name="Billing Test",
        subscription_tier="essentials",
        subscription_status="trialing",
        stripe_customer_id="cus_test_billing",
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email=f"billing{uuid4().hex[:6]}@test.co",
        hashed_password=hash_password("x"),
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=org.id, role=role
    ))
    await db_session.flush()
    return user, org


async def _auth_headers_for(user):
    from app.core.security import create_access_token
    from app.models.iam import SubscriptionTier
    token = create_access_token(
        user_id=user.id,
        org_id=user.selected_org_id,
        subscription_tier=SubscriptionTier.ESSENTIALS.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_subscription_returns_state(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, org = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "essentials"
    assert data["status"] == "trialing"
    assert "days_remaining_in_trial" in data
    assert data["is_locked_out"] is False


@pytest.mark.asyncio
async def test_get_subscription_rejects_non_billing_member(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(
        db_session, role=OrgRole.MEMBER.value
    )
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_portal_session_returns_url(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.post(
        "/billing/portal-session", json={}, headers=headers
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["url"].startswith("https://billing.stripe.com/")


@pytest.mark.asyncio
async def test_create_portal_session_uses_custom_return_url(
    client: AsyncClient, db_session, configured_fake_stripe
):
    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.post(
        "/billing/portal-session",
        json={"return_url": "https://myapp/custom"},
        headers=headers,
    )

    assert resp.status_code == 200
    configured_fake_stripe.billing_portal.Session.create.assert_called_with(
        customer="cus_test_billing",
        return_url="https://myapp/custom",
    )


@pytest.mark.asyncio
async def test_endpoints_return_503_when_unconfigured(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(
        "app.services.billing.stripe_client.settings.stripe_secret_key", ""
    )
    stripe_client._reset_cache()

    user, _ = await _make_billing_user(db_session)
    headers = await _auth_headers_for(user)

    resp = await client.get("/billing/subscription", headers=headers)
    assert resp.status_code == 503
    assert "Billing" in resp.json()["detail"]

    resp = await client.post(
        "/billing/portal-session", json={}, headers=headers
    )
    assert resp.status_code == 503
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_endpoints.py -v 2>&1 | tail -10
```

Expected: 404 on all endpoint calls — router doesn't exist yet.

- [ ] **Step 3: Create the billing router**

Create `backend/app/api/endpoints/billing.py`:

```python
"""Billing endpoints (F-0019a).

All endpoints (except /webhook) require the BILLING role on the user's
selected org. Webhook handler uses signature verification instead.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db, require_org_role
from app.models.iam import Organization, OrgRole, User
from app.schemas.billing import (
    PortalSessionRequest,
    PortalSessionResponse,
    SubscriptionStateResponse,
)
from app.services.billing import (
    seat_limits,
    stripe_client,
    subscription_service,
    webhook_handler,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_configured() -> None:
    if not stripe_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Billing is not configured in this environment. "
                "Contact an administrator."
            ),
        )


@router.get("/subscription", response_model=SubscriptionStateResponse)
async def get_subscription(
    user: User = Depends(require_org_role(OrgRole.BILLING)),
    db: AsyncSession = Depends(get_db),
):
    _require_configured()
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    state = subscription_service.get_subscription_state(org)
    seat_count = await seat_limits.get_seat_count(db, org.id)
    seat_limit = seat_limits.get_seat_limit(org.subscription_tier)
    state["seat_count"] = seat_count
    state["seat_limit"] = seat_limit
    state["seat_limit_exceeded"] = (
        seat_limit is not None and seat_count > seat_limit
    )
    return SubscriptionStateResponse(**state)


@router.post("/portal-session", response_model=PortalSessionResponse)
async def create_portal_session(
    body: PortalSessionRequest,
    user: User = Depends(require_org_role(OrgRole.BILLING)),
    db: AsyncSession = Depends(get_db),
):
    _require_configured()
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return_url = body.return_url or settings.stripe_portal_return_url
    try:
        url = await subscription_service.create_portal_session(org, return_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PortalSessionResponse(url=url)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    _require_configured()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe = stripe_client.get_stripe()
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except Exception as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # event is a stripe.Event object; convert to plain dict for our handler
    if hasattr(event, "to_dict_recursive"):
        event_dict = event.to_dict_recursive()
    else:
        event_dict = dict(event)

    try:
        await webhook_handler.handle_event(db, event_dict)
        await db.commit()
    except Exception:
        logger.exception("Stripe webhook handling failed for event %s", event.get("id") if isinstance(event, dict) else event.id)
        await db.rollback()
        # Return 500 so Stripe retries within its 3-day window.
        # StripeEvent idempotency guards against double-apply on retry.
        raise HTTPException(status_code=500, detail="Webhook handling failed")

    return {"received": True}
```

- [ ] **Step 4: Register the router in main.py**

Edit `backend/app/main.py`. In the import block around lines 356-361, add `billing` to the imported endpoints list:

Change:
```python
from app.api.endpoints import (ai, auth, batch_record_import, chat, dashboard,
                               experiments, export_data, iam, library,
                               notifications, offline, onboarding,
                               project_members, projects, protocol_pdfs,
                               protocol_versions, protocols, runs, sync,
                               template_convert, templates, unit_ops)
```

To:
```python
from app.api.endpoints import (ai, auth, batch_record_import, billing, chat,
                               dashboard, experiments, export_data, iam,
                               library, notifications, offline, onboarding,
                               project_members, projects, protocol_pdfs,
                               protocol_versions, protocols, runs, sync,
                               template_convert, templates, unit_ops)
```

After the last `app.include_router(...)` call (around line 384, after `onboarding.router`), add:

```python
app.include_router(billing.router, prefix="/billing", tags=["billing"])
```

- [ ] **Step 5: Add /billing/webhook to public paths (auth middleware bypass)**

```bash
grep -n "public_path\|PUBLIC_PATH\|/auth/login" backend/app/core/middleware.py | head -5
```

Find the list of public paths in `backend/app/core/middleware.py`. Add `/billing/webhook` to it so auth middleware doesn't require a JWT.

Edit `backend/app/core/middleware.py` to include `/billing/webhook` wherever `/health`, `/docs`, or `/auth/login` appear in the public-paths allowlist. The exact edit depends on the middleware's structure — match the existing pattern.

Example (adjust to actual code):

```python
PUBLIC_PATHS = {"/health", "/docs", "/auth/login", "/auth/register",
                "/auth/verify-email", "/billing/webhook"}
```

Or, if paths use prefix matching:

```python
if path.startswith(("/auth/", "/docs", "/health", "/billing/webhook")):
    return await call_next(request)
```

- [ ] **Step 6: Run billing endpoint tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_endpoints.py -v 2>&1 | tail -20
```

Expected: all 5 tests pass.

- [ ] **Step 7: Confirm nothing else broke**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit tests/integration -q 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/billing.py backend/app/main.py backend/app/core/middleware.py backend/tests/integration/test_billing_endpoints.py
git commit -m "feat(billing): /billing router (GET subscription, POST portal-session, POST webhook)"
```

---

### Task 14: Integration test — webhook signature verification and dispatch

**Files:**
- Modify: `backend/tests/integration/test_billing_endpoints.py`

- [ ] **Step 1: Add webhook signature tests**

Append to `backend/tests/integration/test_billing_endpoints.py`:

```python
import hmac
import hashlib
import json
import time


def _sign_stripe_event(payload: bytes, secret: str, ts: int = None) -> str:
    """Construct a Stripe-style signature header for a test payload."""
    ts = ts or int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


@pytest.mark.asyncio
async def test_webhook_accepts_valid_signature(
    client: AsyncClient, db_session, monkeypatch
):
    secret = "whsec_test_signing_secret"
    for key, val in [
        ("stripe_secret_key", "sk_test_x"),
        ("stripe_webhook_secret", secret),
        ("stripe_essentials_price_id", "price_ess"),
        ("stripe_pro_price_id", "price_pro"),
    ]:
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", val
        )
        monkeypatch.setattr(
            f"app.api.endpoints.billing.settings.{key}", val
        )
    stripe_client._reset_cache()

    # Pre-create the org so the event has a matching customer
    org = Organization(
        name="WebhookTest",
        stripe_customer_id="cus_test_123",
        stripe_subscription_id="sub_test_456",
        subscription_tier="essentials",
        subscription_status="trialing",
    )
    db_session.add(org)
    await db_session.flush()
    await db_session.commit()

    # Use the real stripe module for construct_event (it's the only fn we need)
    stripe_client._reset_cache()
    from app.services.billing.stripe_client import get_stripe
    _ = get_stripe()  # primes the real stripe module with the fake secret key

    payload = json.dumps({
        "id": "evt_sig_test_001",
        "object": "event",
        "type": "customer.subscription.updated",
        "created": 1714000000,
        "data": {"object": {
            "id": "sub_test_456",
            "object": "subscription",
            "customer": "cus_test_123",
            "status": "active",
            "trial_end": None,
            "current_period_end": 1716678400,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }},
    }).encode()
    sig = _sign_stripe_event(payload, secret)

    resp = await client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": sig, "content-type": "application/json"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(
    client: AsyncClient, monkeypatch
):
    for key, val in [
        ("stripe_secret_key", "sk_test_x"),
        ("stripe_webhook_secret", "whsec_signing"),
        ("stripe_essentials_price_id", "price_ess"),
        ("stripe_pro_price_id", "price_pro"),
    ]:
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", val
        )
    stripe_client._reset_cache()

    resp = await client.post(
        "/billing/webhook",
        content=b'{"id": "evt_bogus"}',
        headers={"stripe-signature": "t=1,v1=badsig", "content-type": "application/json"},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run the added tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_endpoints.py::test_webhook_accepts_valid_signature tests/integration/test_billing_endpoints.py::test_webhook_rejects_invalid_signature -v 2>&1 | tail -15
```

Expected: both pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_billing_endpoints.py
git commit -m "test(billing): webhook signature verification integration tests"
```

---

## Phase 7 — Pauses 3 & 4 (Portal + Webhook CLI)

### PAUSE 3 — Configure Stripe Customer Portal

- [ ] **Step 1: Hand off to user:**

> **PAUSE 3 — Configure Stripe Customer Portal. No code to paste; this is dashboard-only.**
>
> 1. Left sidebar → **Settings** (gear icon) → **Billing** → **Customer portal**. Direct link: https://dashboard.stripe.com/test/settings/billing/portal
> 2. Under **Functionality**, enable:
>    - ☑ Customers can update their payment method
>    - ☑ Customers can view their invoice history
>    - ☑ Customers can cancel subscriptions → **At the end of the billing period** (not Immediately)
>    - ☑ Customers can switch plans
> 3. Under **Products** (the "Plans customers can switch to" section), add BOTH:
>    - **Batchrite Essentials** (monthly price)
>    - **Batchrite Pro** (monthly price)
> 4. Under **Business information**, set a support email (yours is fine for now).
> 5. Click **Save changes**.
>
> Reply with "Pause 3 done" when saved.

- [ ] **Step 2: Wait for confirmation.**

---

### PAUSE 4 — Start `stripe listen` and fetch webhook signing secret

- [ ] **Step 1: Hand off to user:**

> **PAUSE 4 — Start Stripe CLI webhook forwarding.**
>
> 1. Install the Stripe CLI if you haven't: https://stripe.com/docs/stripe-cli. On macOS: `brew install stripe/stripe-cli/stripe`. Linux: see the page.
> 2. Log in once: `stripe login` (opens browser).
> 3. In a **persistent terminal** (leave running while developing):
>
>    ```
>    stripe listen --forward-to localhost:8000/billing/webhook
>    ```
>
> 4. First line of output shows:
>
>    ```
>    Ready! Your webhook signing secret is whsec_...
>    ```
>
> Paste that value into `backend/.env`:
>
> ```
> BATCHRITE_STRIPE_WEBHOOK_SECRET=whsec_...
> ```
>
> Note: this secret is per-CLI-session. If you restart `stripe listen`, the secret changes — paste the new one. Reply "Pause 4 done" with the secret shape confirmed (starts with `whsec_`).

- [ ] **Step 2: Wait for confirmation.**

---

## Phase 8 — Manual Smoke Test

### Task 15: End-to-end smoke test — register a new org and confirm Stripe subscription

**Files:** (none — manual verification)

- [ ] **Step 1: Start the backend**

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
```

In a second terminal, confirm `stripe listen` is still running (from Pause 4).

- [ ] **Step 2: Register a new user via the API**

In a third terminal:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"smoketest@batchrite.local","password":"smoketest123","full_name":"Smoke Test"}'
```

Expected: 200 response with a verification token payload.

- [ ] **Step 3: Verify the Stripe Dashboard shows the customer and subscription**

Go to https://dashboard.stripe.com/test/customers. You should see a customer named "Smoke Test's Organization" (or similar), with a trialing Batchrite Essentials subscription.

- [ ] **Step 4: Verify the DB was updated**

```bash
psql -h localhost -U postgres -d batchrite -c "
SELECT name, stripe_customer_id, stripe_subscription_id, subscription_status, trial_end
FROM organizations WHERE name LIKE '%Smoke%';
"
```

Expected: one row with non-null `stripe_customer_id` (starts `cus_`), `stripe_subscription_id` (starts `sub_`), `subscription_status = 'trialing'`, `trial_end` set.

- [ ] **Step 5: Verify the `stripe listen` terminal shows the webhook being received**

Expected output lines include:
```
customer.created [evt_...]
customer.subscription.created [evt_...]
```

And the backend's stdout should show log lines acknowledging the events.

- [ ] **Step 6: Commit a note if anything is manual-only**

No code to commit. If you had to adjust middleware or code to make the smoke test pass, commit those adjustments with an informative message now.

---

## Phase 9 — Write-Lockout Enforcement Sweep

### Task 16: Apply require_active_subscription to all write endpoints

**Files:**
- Modify: all router files under `backend/app/api/endpoints/` that have POST / PUT / PATCH / DELETE routes, EXCEPT the exempt ones
- Create: `backend/tests/integration/test_billing_lockout.py`

**Exempt routers (NO `require_active_subscription` added):**
- `auth.py` (login/register/verify/reset)
- `billing.py` (obviously)
- `iam.py` endpoints for `GET /users/me`, `POST /users/me` (self-profile update), and `POST /organizations/{id}/switch` — see below

**Non-exempt routers (sweep and add the dep to every write route):**
- `projects.py`, `protocols.py`, `protocol_versions.py`, `protocol_pdfs.py`, `runs.py`, `experiments.py`, `unit_ops.py`, `chat.py`, `templates.py`, `batch_record_import.py`, `export_data.py` (if it has any POST/PUT/PATCH/DELETE), `project_members.py`, `ai.py`, `notifications.py`, `library.py`, `offline.py` (writes only), `sync.py` (writes only), `onboarding.py`, `template_convert.py`

- [ ] **Step 1: Write the lockout integration test**

Create `backend/tests/integration/test_billing_lockout.py`:

```python
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.iam import (
    Organization,
    OrganizationMember,
    OrgRole,
    SubscriptionTier,
    User,
)
from app.models.science import Project


async def _setup_locked_out_org(db_session, status: str = "canceled"):
    org = Organization(
        name="Locked Out",
        subscription_tier="essentials",
        subscription_status=status,
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        email=f"locked{uuid4().hex[:6]}@test.co",
        hashed_password=hash_password("x"),
        selected_org_id=org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=org.id, role=OrgRole.ADMIN.value
    ))
    await db_session.flush()
    return user, org


def _headers(user):
    token = create_access_token(
        user_id=user.id,
        org_id=user.selected_org_id,
        subscription_tier=SubscriptionTier.ESSENTIALS.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_write_endpoint_402s_when_subscription_canceled(
    client: AsyncClient, db_session
):
    user, _ = await _setup_locked_out_org(db_session, status="canceled")
    headers = _headers(user)

    resp = await client.post(
        "/projects",
        json={"name": "should fail"},
        headers=headers,
    )

    assert resp.status_code == 402
    body = resp.json()
    assert body["detail"]["code"] == "subscription_required"
    assert body["detail"]["status"] == "canceled"


@pytest.mark.asyncio
async def test_write_endpoint_402s_when_past_due(
    client: AsyncClient, db_session
):
    user, _ = await _setup_locked_out_org(db_session, status="past_due")
    resp = await client.post(
        "/projects",
        json={"name": "should fail"},
        headers=_headers(user),
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_read_endpoint_succeeds_when_locked_out(
    client: AsyncClient, db_session
):
    user, org = await _setup_locked_out_org(db_session, status="canceled")
    # Seed a project so GET /projects has something to return
    db_session.add(Project(name="p1", organization_id=org.id))
    await db_session.flush()

    resp = await client.get("/projects", headers=_headers(user))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_billing_portal_session_accessible_when_locked_out(
    client: AsyncClient, db_session, monkeypatch
):
    from unittest.mock import MagicMock
    from app.services.billing import stripe_client
    fake = MagicMock()
    fake.billing_portal.Session.create.return_value = MagicMock(
        url="https://billing.stripe.com/session/abc"
    )
    stripe_client.set_fake_client(fake)
    for key in ("stripe_secret_key", "stripe_webhook_secret",
                "stripe_essentials_price_id", "stripe_pro_price_id"):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )

    user, org = await _setup_locked_out_org(db_session)
    org.stripe_customer_id = "cus_test_lockout"
    await db_session.flush()

    resp = await client.post(
        "/billing/portal-session", json={}, headers=_headers(user)
    )
    assert resp.status_code == 200
    stripe_client._reset_cache()


@pytest.mark.asyncio
async def test_trialing_user_can_write(client: AsyncClient, db_session):
    user, _ = await _setup_locked_out_org(db_session, status="trialing")
    resp = await client.post(
        "/projects",
        json={"name": "ok"},
        headers=_headers(user),
    )
    assert resp.status_code == 201 or resp.status_code == 200


@pytest.mark.asyncio
async def test_null_status_user_can_write(client: AsyncClient, db_session):
    """Pre-billing org (no Stripe provisioning) behaves as 'not locked out'."""
    user, org = await _setup_locked_out_org(db_session, status="trialing")
    org.subscription_status = None
    await db_session.flush()

    resp = await client.post(
        "/projects",
        json={"name": "ok"},
        headers=_headers(user),
    )
    assert resp.status_code in (200, 201)
```

- [ ] **Step 2: Run — confirm first test fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_lockout.py::test_write_endpoint_402s_when_subscription_canceled -v 2>&1 | tail -15
```

Expected: fails because `POST /projects` still returns 200 or 201 (dep not applied yet).

- [ ] **Step 3: Apply the dep to projects.py as a first target**

Open `backend/app/api/endpoints/projects.py`. Add to the imports near the top:

```python
from app.core.deps import require_active_subscription
```

For **every** `@router.post`, `@router.put`, `@router.patch`, `@router.delete` in this file, add the dep as a positional `Depends()` parameter. Example:

Before:
```python
@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...
```

After:
```python
@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    ...
```

Note: the leading-underscore parameter name indicates an unused result from a gate-only dependency — matches the convention already used for `require_permission` elsewhere in the codebase.

- [ ] **Step 4: Run the first lockout test — confirm pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_lockout.py::test_write_endpoint_402s_when_subscription_canceled -v 2>&1 | tail -10
```

Expected: pass. Read / exempt / trialing tests also pass because they use `/projects` writes and reads.

- [ ] **Step 5: Sweep the remaining non-exempt routers**

For each file in the non-exempt list (see Task 16 preamble), apply the same pattern: add the import and apply `Depends(require_active_subscription())` to every write route. Shell helper to count write routes per file to gauge scope:

```bash
cd backend && for f in app/api/endpoints/*.py; do
  count=$(grep -cE "^@router\.(post|put|patch|delete)" "$f")
  if [ "$count" -gt 0 ]; then
    echo "$f: $count write route(s)"
  fi
done
```

Work through each non-exempt file one at a time. After every file, run the full test suite:

```bash
pytest tests/unit tests/integration -q 2>&1 | tail -5
```

If any test fails, revisit the routes in that file — the dep may have been applied to a read endpoint by mistake, or to an exempt path.

- [ ] **Step 6: Exempt routes in iam.py**

In `backend/app/api/endpoints/iam.py`, identify:
- `POST /users/me` (self-profile update) — **do NOT add** the dep
- `POST /organizations/{id}/switch` or equivalent org-switch endpoint — **do NOT add** the dep
- All other write endpoints (org create, member add/remove/update, team create, invitation accept/revoke) — **add** the dep

If unsure whether an endpoint qualifies as self-profile-update, re-read the spec's exemption list in the Write-Lockout section.

- [ ] **Step 7: Run full lockout test file**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_billing_lockout.py -v 2>&1 | tail -15
```

Expected: all 6 tests pass.

- [ ] **Step 8: Run the complete test suite**

```bash
cd backend && source .venv/bin/activate && pytest -q 2>&1 | tail -10
```

Expected: all passing (or identify any pre-existing unrelated failures and note them).

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/endpoints/*.py backend/tests/integration/test_billing_lockout.py
git commit -m "feat(billing): apply require_active_subscription to write endpoints; lockout tests"
```

---

### Task 17: Cache has_payment_method on webhook state reconciliation

**Files:**
- Modify: `backend/app/services/billing/webhook_handler.py`
- Modify: `backend/tests/unit/services/test_webhook_handler.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/services/test_webhook_handler.py`:

```python
@pytest.mark.asyncio
async def test_subscription_updated_caches_has_payment_method(
    db_session, org_with_pro_trial, monkeypatch
):
    from unittest.mock import MagicMock
    from app.services.billing import stripe_client
    fake = MagicMock()
    fake.Customer.retrieve.return_value = MagicMock(
        invoice_settings=MagicMock(default_payment_method="pm_test_card")
    )
    stripe_client.set_fake_client(fake)
    for key in ("stripe_secret_key", "stripe_webhook_secret",
                "stripe_essentials_price_id", "stripe_pro_price_id"):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )

    event = _load("customer_subscription_updated_upgrade")
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await db_session.refresh(org_with_pro_trial)

    assert org_with_pro_trial.has_payment_method is True
    fake.Customer.retrieve.assert_called_with("cus_test_123")
    stripe_client._reset_cache()


@pytest.mark.asyncio
async def test_subscription_updated_reflects_no_payment_method(
    db_session, org_with_pro_trial, monkeypatch
):
    from unittest.mock import MagicMock
    from app.services.billing import stripe_client
    fake = MagicMock()
    fake.Customer.retrieve.return_value = MagicMock(
        invoice_settings=MagicMock(default_payment_method=None)
    )
    stripe_client.set_fake_client(fake)
    for key in ("stripe_secret_key", "stripe_webhook_secret",
                "stripe_essentials_price_id", "stripe_pro_price_id"):
        monkeypatch.setattr(
            f"app.services.billing.stripe_client.settings.{key}", "x"
        )

    org_with_pro_trial.has_payment_method = True
    await db_session.flush()

    event = _load("customer_subscription_updated_upgrade")
    await webhook_handler.handle_event(db_session, event)
    await db_session.flush()
    await db_session.refresh(org_with_pro_trial)

    assert org_with_pro_trial.has_payment_method is False
    stripe_client._reset_cache()
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_webhook_handler.py::test_subscription_updated_caches_has_payment_method -v 2>&1 | tail -10
```

Expected: fails — `has_payment_method` stays False / True as before.

- [ ] **Step 3: Update _apply_subscription_state to refresh has_payment_method**

Edit `backend/app/services/billing/webhook_handler.py`. In `_apply_subscription_state`, after `org.cancel_at_period_end = ...`, add the payment-method lookup:

```python
    # Refresh has_payment_method by reading customer.invoice_settings.default_payment_method
    try:
        stripe = stripe_client.get_stripe()
        customer = stripe.Customer.retrieve(customer_id)
        pm = getattr(
            getattr(customer, "invoice_settings", None),
            "default_payment_method",
            None,
        )
        org.has_payment_method = pm is not None
    except Exception:
        logger.exception(
            "Failed to refresh has_payment_method for customer %s",
            customer_id,
        )
```

Add this import near the other imports in the file:

```python
from app.services.billing import stripe_client
```

- [ ] **Step 4: Run tests**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/services/test_webhook_handler.py -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/billing/webhook_handler.py backend/tests/unit/services/test_webhook_handler.py
git commit -m "feat(billing): cache has_payment_method on subscription state reconciliation"
```

---

### Task 17b: Enforce seat cap in `add_org_member` + integration tests

**Files:**
- Modify: `backend/app/api/endpoints/iam.py` — `add_org_member` handler (current lines 161-228)
- Create: `backend/tests/integration/test_seat_caps.py`

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/integration/test_seat_caps.py`:

```python
"""Integration tests for per-tier seat caps on POST /iam/organizations/{org_id}/members."""
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.iam import (
    Organization,
    OrganizationMember,
    SubscriptionTier,
    User,
)


async def _fill_org_to(db_session, org_id, target_count, start_count=1):
    """Add (target_count - start_count) active members to org."""
    for i in range(target_count - start_count):
        u = User(email=f"fill_{uuid4().hex[:6]}@x.com", hashed_password="x")
        db_session.add(u)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                user_id=u.id, organization_id=org_id, role="MEMBER", archived=False,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_add_member_blocked_when_essentials_cap_reached(
    client: AsyncClient, db_session, test_org, auth_headers,
):
    # Fill test_org (tier=essentials by default) to the cap of 5.
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=5)

    # Attempt to add a 6th member.
    new_user = User(email="overflow@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    body = resp.json()["detail"]
    assert body["code"] == "seat_limit_reached"
    assert body["tier"] == "essentials"
    assert body["limit"] == 5
    assert body["current"] == 5


@pytest.mark.asyncio
async def test_add_member_succeeds_at_cap_minus_one(
    client: AsyncClient, db_session, test_org, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=4)

    new_user = User(email="ok@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reactivate_archived_member_bypasses_cap(
    client: AsyncClient, db_session, test_org, auth_headers,
):
    """Reactivating an archived member doesn't change the non-archived count,
    so it should succeed even when the org is at its cap."""
    test_org.subscription_tier = SubscriptionTier.ESSENTIALS
    db_session.add(test_org)
    await db_session.commit()
    await _fill_org_to(db_session, test_org.id, target_count=5)

    # Archive one member to make room.
    archived_user = User(email="comeback@x.com", hashed_password="x")
    db_session.add(archived_user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            user_id=archived_user.id,
            organization_id=test_org.id,
            role="MEMBER",
            archived=True,
        )
    )
    await db_session.commit()
    # Org is still at 5 active members; archived user doesn't count.
    # Reactivation request should succeed.
    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(archived_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enterprise_has_no_cap(
    client: AsyncClient, db_session, test_org, auth_headers,
):
    test_org.subscription_tier = SubscriptionTier.ENTERPRISE
    db_session.add(test_org)
    await db_session.commit()
    # Fill well beyond any numeric cap.
    await _fill_org_to(db_session, test_org.id, target_count=30)

    new_user = User(email="yetanother@x.com", hashed_password="x")
    db_session.add(new_user)
    await db_session.commit()

    resp = await client.post(
        f"/iam/organizations/{test_org.id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_seat_caps.py -v 2>&1 | tail -20
```

Expected: `test_add_member_blocked_when_essentials_cap_reached` fails (6th member currently succeeds — no cap enforced yet). Reactivation / enterprise / cap-minus-one tests may already pass.

- [ ] **Step 3: Hook `check_seat_capacity` into `add_org_member`**

Edit `backend/app/api/endpoints/iam.py`. Find the `add_org_member` function (currently around line 165). Add the seat-capacity check in the branch that creates a new (non-reactivated) membership.

Add the import near the top with other `app.services.*` imports:

```python
from app.services.billing import seat_limits
```

Then, in the `else` branch (new membership), after the ADMIN-cap check and before the `OrganizationMember(...)` construction, add the seat-capacity check. The structure becomes:

```python
    if existing is not None:
        if not existing.archived:
            raise HTTPException(status_code=409, detail="User is already a member")
        # Reactivating archived member — count doesn't change, no seat check needed.
        existing.archived = False
        existing.role = body.role
        membership = existing
    else:
        # Existing ADMIN cap check stays.
        if body.role == "ADMIN":
            admin_count = await db.execute(
                select(func.count()).where(
                    OrganizationMember.organization_id == org_id,
                    OrganizationMember.role == "ADMIN",
                    OrganizationMember.archived == False,
                )
            )
            if (admin_count.scalar() or 0) >= 3:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum of 3 admins per organization",
                )

        # NEW: per-tier seat cap check.
        org = await db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        await seat_limits.check_seat_capacity(db, org)

        membership = OrganizationMember(
            user_id=body.user_id,
            organization_id=org_id,
            role=body.role,
        )
        db.add(membership)
```

- [ ] **Step 4: Run the integration tests to verify they pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_seat_caps.py -v 2>&1 | tail -20
```

Expected: all 4 tests pass.

- [ ] **Step 5: Run the broader iam test suite to confirm no regressions**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_iam.py -v 2>&1 | tail -20
```

Expected: all previously-green tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/iam.py backend/tests/integration/test_seat_caps.py
git commit -m "feat(billing): enforce per-tier seat caps in add_org_member"
```

---

## Phase 10 — Frontend

### Task 18: Zod schema for billing

**Files:**
- Create: `frontend/src/lib/schemas/billing.ts`
- Modify: `frontend/src/lib/schemas/index.ts`

- [ ] **Step 1: Create the schema**

Create `frontend/src/lib/schemas/billing.ts`:

```typescript
import { z } from 'zod';

export const SubscriptionStateSchema = z.object({
    tier: z.enum(['essentials', 'pro', 'enterprise']),
    status: z.string().nullable(),
    trial_end: z.string().nullable(),
    days_remaining_in_trial: z.number().int().nullable(),
    current_period_end: z.string().nullable(),
    cancel_at_period_end: z.boolean(),
    has_payment_method: z.boolean(),
    is_locked_out: z.boolean(),
    seat_count: z.number().int(),
    seat_limit: z.number().int().nullable(),
    seat_limit_exceeded: z.boolean(),
}).passthrough();

export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;

export const PortalSessionResponseSchema = z.object({
    url: z.string().url(),
}).passthrough();

export type PortalSessionResponse = z.infer<typeof PortalSessionResponseSchema>;
```

- [ ] **Step 2: Add to barrel export**

Edit `frontend/src/lib/schemas/index.ts`. Append:

```typescript
export * from './billing';
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run check 2>&1 | tail -10
```

Expected: no new errors introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/schemas/billing.ts frontend/src/lib/schemas/index.ts
git commit -m "feat(billing): Zod schemas for subscription state and portal session"
```

---

### Task 19: API client methods for billing

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Locate the api object**

```bash
grep -n "^export const api" frontend/src/lib/api.ts
```

This should show the `api` object around line 195.

- [ ] **Step 2: Add billing methods**

Edit `frontend/src/lib/api.ts`. At the top of the file, add import for the billing schemas:

```typescript
import { SubscriptionStateSchema, PortalSessionResponseSchema, type SubscriptionState, type PortalSessionResponse } from '$lib/schemas/billing';
```

After the closing `};` of the `api` object, append:

```typescript
export const billingApi = {
    getSubscription: (): Promise<SubscriptionState> =>
        api.get<SubscriptionState>('/billing/subscription', { schema: SubscriptionStateSchema }),

    createPortalSession: (returnUrl?: string): Promise<PortalSessionResponse> =>
        api.post<PortalSessionResponse>('/billing/portal-session', { return_url: returnUrl }, { schema: PortalSessionResponseSchema }),
};
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run check 2>&1 | tail -10
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(billing): billingApi client methods (getSubscription, createPortalSession)"
```

---

### Task 20: Subscription store (Svelte rune)

**Files:**
- Create: `frontend/src/lib/stores/subscription.svelte.ts`

- [ ] **Step 1: Check the stores directory exists**

```bash
ls frontend/src/lib/stores/ 2>/dev/null || mkdir -p frontend/src/lib/stores
```

- [ ] **Step 2: Create the store**

Create `frontend/src/lib/stores/subscription.svelte.ts`:

```typescript
import { billingApi } from '$lib/api';
import { ApiError } from '$lib/api';
import type { SubscriptionState } from '$lib/schemas/billing';

let state = $state<SubscriptionState | null>(null);
let loading = $state(false);
let error = $state<string | null>(null);
let unconfigured = $state(false);

export const subscription = {
    get state() { return state; },
    get loading() { return loading; },
    get error() { return error; },
    get unconfigured() { return unconfigured; },
};

export async function loadSubscription(): Promise<void> {
    loading = true;
    error = null;
    unconfigured = false;
    try {
        state = await billingApi.getSubscription();
    } catch (e) {
        if (e instanceof ApiError && e.status === 503) {
            unconfigured = true;
            state = null;
        } else if (e instanceof ApiError && e.status === 403) {
            // User doesn't have BILLING role; leave state null silently
            state = null;
        } else {
            error = e instanceof Error ? e.message : 'Failed to load subscription';
        }
    } finally {
        loading = false;
    }
}

export async function openPortal(returnUrl?: string): Promise<void> {
    const resolvedReturn = returnUrl ?? `${window.location.origin}/settings?tab=billing`;
    try {
        const { url } = await billingApi.createPortalSession(resolvedReturn);
        window.location.href = url;
    } catch (e) {
        error = e instanceof Error ? e.message : 'Failed to open billing portal';
    }
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run check 2>&1 | tail -10
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/stores/subscription.svelte.ts
git commit -m "feat(billing): subscription store with loadSubscription + openPortal helpers"
```

---

### Task 21: BillingTab component

**Files:**
- Create: `frontend/src/lib/components/settings/BillingTab.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/lib/components/settings/BillingTab.svelte`:

```svelte
<script lang="ts">
    import { onMount } from 'svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
    import { subscription, loadSubscription, openPortal } from '$lib/stores/subscription.svelte';

    onMount(loadSubscription);

    function planLabel(tier: string | undefined): string {
        if (tier === 'essentials') return 'Essentials';
        if (tier === 'pro') return 'Pro';
        if (tier === 'enterprise') return 'Enterprise';
        return '—';
    }

    function statusLabel(status: string | null): string {
        if (!status) return 'No subscription';
        const map: Record<string, string> = {
            trialing: 'Trialing',
            active: 'Active',
            past_due: 'Past due',
            canceled: 'Canceled',
            unpaid: 'Unpaid',
            incomplete: 'Incomplete',
        };
        return map[status] ?? status;
    }

    function statusClasses(status: string | null): string {
        if (!status) return 'bg-muted text-muted-foreground';
        const map: Record<string, string> = {
            trialing: 'bg-blue-100 text-blue-800',
            active: 'bg-green-100 text-green-800',
            past_due: 'bg-amber-100 text-amber-800',
            canceled: 'bg-red-100 text-red-800',
            unpaid: 'bg-red-100 text-red-800',
            incomplete: 'bg-amber-100 text-amber-800',
        };
        return map[status] ?? 'bg-muted text-muted-foreground';
    }

    function formatDate(iso: string | null): string {
        if (!iso) return '';
        return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
    }
</script>

{#if subscription.loading}
    <p class="text-sm text-muted-foreground py-8 text-center">Loading billing…</p>
{:else if subscription.unconfigured}
    <Card>
        <CardHeader>
            <CardTitle>Billing unavailable</CardTitle>
            <CardDescription>Billing is not configured for this environment. Contact an administrator.</CardDescription>
        </CardHeader>
    </Card>
{:else if subscription.error}
    <Card>
        <CardHeader>
            <CardTitle>Unable to load billing</CardTitle>
            <CardDescription>{subscription.error}</CardDescription>
        </CardHeader>
        <CardContent>
            <Button onclick={loadSubscription}>Try again</Button>
        </CardContent>
    </Card>
{:else if subscription.state}
    {@const s = subscription.state}
    <div class="space-y-6">
        <!-- Header card: current plan + status -->
        <Card>
            <CardHeader>
                <div class="flex items-start justify-between gap-4">
                    <div>
                        <CardTitle>{planLabel(s.tier)}</CardTitle>
                        <CardDescription class="mt-1">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {statusClasses(s.status)}">
                                {statusLabel(s.status)}
                            </span>
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent class="space-y-3 text-sm">
                {#if s.status === 'trialing' && s.days_remaining_in_trial != null}
                    <p>
                        {s.days_remaining_in_trial} day{s.days_remaining_in_trial === 1 ? '' : 's'} left in your trial.
                        Add a payment method to keep your subscription active.
                    </p>
                    <Button onclick={() => openPortal()}>Add payment method</Button>
                {:else if s.cancel_at_period_end && s.current_period_end}
                    <p>
                        Your subscription will end on {formatDate(s.current_period_end)}. You can reactivate from the billing portal.
                    </p>
                    <Button variant="outline" onclick={() => openPortal()}>Manage billing</Button>
                {:else if s.is_locked_out}
                    <p class="text-destructive">
                        Your subscription is not active. Reads and exports remain available, but new changes are blocked.
                    </p>
                    <Button onclick={() => openPortal()}>Re-subscribe</Button>
                {:else if s.status === 'active' && s.current_period_end}
                    <p>Next billing date: {formatDate(s.current_period_end)}.</p>
                {/if}

                <!-- Seat usage -->
                <p class="text-muted-foreground">
                    {#if s.seat_limit == null}
                        {s.seat_count} {s.seat_count === 1 ? 'member' : 'members'}
                    {:else}
                        {s.seat_count} of {s.seat_limit} {s.seat_limit === 1 ? 'seat' : 'seats'} used
                    {/if}
                </p>

                {#if s.seat_limit_exceeded && s.seat_limit != null}
                    <div class="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900 text-sm">
                        Your organization has {s.seat_count} members but the {planLabel(s.tier)} plan allows {s.seat_limit}.
                        Remove {s.seat_count - s.seat_limit} {s.seat_count - s.seat_limit === 1 ? 'member' : 'members'}
                        or upgrade to clear this warning.
                        <div class="mt-2 flex gap-2">
                            <Button size="sm" onclick={() => openPortal()}>Upgrade</Button>
                            <a href="/settings?tab=members" class="text-sm underline underline-offset-4 self-center">Manage members</a>
                        </div>
                    </div>
                {/if}
            </CardContent>
        </Card>

        <!-- Plan rows -->
        <Card>
            <CardHeader>
                <CardTitle>Plans</CardTitle>
            </CardHeader>
            <CardContent class="divide-y divide-border">
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Essentials</p>
                        <p class="text-xs text-muted-foreground">Included tier for new orgs.</p>
                    </div>
                    {#if s.tier === 'essentials'}
                        <span class="text-xs text-muted-foreground">Your plan</span>
                    {:else}
                        <Button variant="outline" size="sm" onclick={() => openPortal()}>Downgrade</Button>
                    {/if}
                </div>
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Pro</p>
                        <p class="text-xs text-muted-foreground">Advanced features for teams.</p>
                    </div>
                    {#if s.tier === 'pro'}
                        <span class="text-xs text-muted-foreground">Your plan</span>
                    {:else}
                        <Button size="sm" onclick={() => openPortal()}>Upgrade</Button>
                    {/if}
                </div>
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Enterprise</p>
                        <p class="text-xs text-muted-foreground">Custom deployment, SLA, dedicated support.</p>
                    </div>
                    <a href="mailto:sales@batchrite.com" class="text-sm underline underline-offset-4">Contact sales</a>
                </div>
            </CardContent>
        </Card>

        <!-- Manage billing -->
        <Card>
            <CardContent class="flex items-center justify-between pt-6">
                <div>
                    <p class="font-medium">Manage billing</p>
                    <p class="text-sm text-muted-foreground">Update payment method, view invoice history, or cancel.</p>
                </div>
                <Button variant="outline" onclick={() => openPortal()}>Open billing portal</Button>
            </CardContent>
        </Card>
    </div>
{:else}
    <Card>
        <CardHeader>
            <CardTitle>Billing</CardTitle>
            <CardDescription>You don't have billing access for this organization.</CardDescription>
        </CardHeader>
    </Card>
{/if}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run check 2>&1 | tail -10
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/settings/BillingTab.svelte
git commit -m "feat(billing): BillingTab component with plan rows + portal CTAs"
```

---

### Task 22: Wire BillingTab into Settings page

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Update the activeTab type**

Edit `frontend/src/routes/settings/+page.svelte` at line 26:

Before:
```typescript
let activeTab = $state<'organization' | 'teams' | 'profile' | 'notifications' | 'ai' | 'templates'>('organization');
```

After:
```typescript
let activeTab = $state<'organization' | 'teams' | 'profile' | 'notifications' | 'ai' | 'templates' | 'billing'>('organization');
```

- [ ] **Step 2: Import BillingTab**

Around the existing settings-tab imports (line 20-21):

```typescript
import AiSettingsTab from '$lib/components/settings/AiSettingsTab.svelte';
import TemplatesTab from '$lib/components/settings/TemplatesTab.svelte';
```

Add:
```typescript
import BillingTab from '$lib/components/settings/BillingTab.svelte';
```

- [ ] **Step 3: Add the tab button**

In the tab-button block around lines 602-651, after the Templates button (around line 650-651), add:

```svelte
        <Button
            variant="tab"
            data-active={activeTab === 'billing'}
            onclick={() => (activeTab = 'billing')}
            class="py-2.5 min-h-11"
        >
            Billing
        </Button>
```

- [ ] **Step 4: Add the tab content block**

At the end of the tab-content conditional chain (after the `{:else if activeTab === 'templates'}` block at line 1198), add:

```svelte
    {:else if activeTab === 'billing'}
        <BillingTab />
```

- [ ] **Step 5: Start dev server and check**

```bash
cd frontend && npm run dev 2>&1 &
sleep 3
```

In another terminal, open http://localhost:5173/settings and confirm the Billing tab is visible (auth may be required — log in first).

- [ ] **Step 6: Typecheck and tests**

```bash
cd frontend && npm run check 2>&1 | tail -5
```

Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(billing): add Billing tab to Settings page"
```

---

### Task 23: 402-response interceptor + blocking modal

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte`
- Create: `frontend/src/lib/stores/lockoutModal.svelte.ts`
- Modify: `frontend/src/routes/+layout.svelte`

- [ ] **Step 1: Create a lockout-modal store**

Create `frontend/src/lib/stores/lockoutModal.svelte.ts`:

```typescript
let open = $state(false);
let message = $state<string>('Your subscription is not active. Reads remain available, but new changes are blocked.');

export const lockoutModal = {
    get open() { return open; },
    get message() { return message; },
};

export function showLockout(msg?: string) {
    if (msg) message = msg;
    open = true;
}

export function dismissLockout() {
    open = false;
}
```

- [ ] **Step 2: Intercept 402 in api.ts**

Edit `frontend/src/lib/api.ts`. Find `_handleErrorResponse` (around line 30). Before `throw new ApiError(...)` at the end of the function, add the 402 branch:

```typescript
    if (response.status === 402) {
        let detail: any = null;
        try {
            detail = await response.json();
        } catch {}
        // Dynamic import to avoid circular dep on module-load order
        import('$lib/stores/lockoutModal.svelte').then(({ showLockout }) => {
            const msg = detail?.detail?.message || 'Your subscription is not active. Add a payment method to continue.';
            showLockout(msg);
        });
        throw new ApiError(402, 'subscription_required', detail);
    }
```

Place it immediately after the 401 block so both special statuses are handled.

- [ ] **Step 3: Create the modal component**

Create `frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte`:

```svelte
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { lockoutModal, dismissLockout } from '$lib/stores/lockoutModal.svelte';
    import { openPortal } from '$lib/stores/subscription.svelte';
</script>

{#if lockoutModal.open}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
        <div class="bg-background rounded-lg shadow-xl max-w-md w-full p-6 space-y-4">
            <h2 class="text-lg font-semibold">Subscription required</h2>
            <p class="text-sm text-muted-foreground">{lockoutModal.message}</p>
            <div class="flex justify-end gap-2">
                <Button variant="outline" onclick={dismissLockout}>Dismiss and continue reading</Button>
                <Button onclick={() => openPortal()}>Add payment method</Button>
            </div>
        </div>
    </div>
{/if}
```

- [ ] **Step 4: Render the modal globally**

Edit `frontend/src/routes/+layout.svelte`. Near the end of the template, inside the main wrapper, add:

```svelte
<script lang="ts">
    import SubscriptionLockoutModal from '$lib/components/shared/SubscriptionLockoutModal.svelte';
    // ... existing imports
</script>

<!-- ... existing layout ... -->

<SubscriptionLockoutModal />
```

If the layout file doesn't have a `<script>` tag yet, add one. If it does, append the import to the existing one.

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npm run check 2>&1 | tail -10
```

Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/stores/lockoutModal.svelte.ts frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte frontend/src/routes/+layout.svelte
git commit -m "feat(billing): 402-response interceptor and global lockout modal"
```

---

## Phase 11 — Browser QA

### Task 24: Browser verification via qa-verify agent

**Files:** (none — agent-driven)

- [ ] **Step 1: Ensure dev servers are running in the worktree**

Per `.claude/rules/conventions.md`:
- Worktree 1 dev ports: backend :8010, frontend :5183
- Set `VITE_API_PORT=8010` before starting frontend

Start both:

```bash
# Terminal A
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010

# Terminal B
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

Keep `stripe listen --forward-to localhost:8010/billing/webhook` running in a third terminal.

- [ ] **Step 2: Launch the qa-verify agent**

Dispatch the `qa-verify` agent with the following context:

> **Feature:** Stripe billing + Essentials trial (F-0019a + F-0019b).
>
> **Login:**
> - Register a new user at http://localhost:5183/register with any email (e.g., `qa-test+<random>@batchrite.local`) and password `qatest123`. Email verification may need to be bypassed locally — check `localhost:5183/register` flow; if a verification link is emailed, read it from the backend logs.
>
> **Pages affected:**
> - `/settings?tab=billing` — the new Billing tab.
>
> **Acceptance criteria to verify:**
> 1. After registering, the new user's org is shown on Essentials tier with status "Trialing" and a countdown (e.g. "30 days left in your trial").
> 2. The "Add payment method" button opens the Stripe Customer Portal (expect full-page redirect to `billing.stripe.com`).
> 3. In the Portal: add test card `4242 4242 4242 4242` (any future expiry, any CVC, any ZIP). Return to the app. The Billing tab should now show:
>    - Still Essentials trialing, BUT
>    - The countdown may still show, and the plan row for Pro has an "Upgrade" CTA.
> 4. Back in the Portal, upgrade to Pro. Return. Billing tab should now show Pro + Active, next billing date displayed.
> 5. Back in the Portal, cancel subscription (at period end). Return. Billing tab should show a "Your subscription will end on [date]" message with a Manage billing CTA.
> 6. In a separate tab, navigate to `/projects` and attempt to create a project while locked-out state is simulated: trigger the locked-out case by running this SQL manually: `UPDATE organizations SET subscription_status='canceled' WHERE name ILIKE '%qa-test%';` — then try `POST /projects` via the UI. Expected: blocking modal appears with "Subscription required" / "Add payment method" / "Dismiss and continue reading" buttons.
> 7. Reset the DB state by setting `subscription_status='active'` again.
>
> **Edge cases to test:**
> - Browser back button on a locked-out state: reads still work; try creating something and the modal shows.
> - The Billing tab should NOT appear for a non-ADMIN user (create a second user, add them as MEMBER to the first org; the tab should render an empty state or hide entirely).
> - **Seat caps:** the Billing tab shows an "X of 5 seats used" line under the header. Add members via `/settings?tab=members` up to 5; the sixth member add should fail with a toast/error "Your Essentials plan allows up to 5 members." Then in the Stripe Portal upgrade to Pro; return to Billing — the line should now read "6 of 25 seats used" and a 7th member add succeeds.
> - **Seat overage after downgrade:** starting from Pro with 6 members, use Portal to downgrade to Essentials (at period end is fine — force the effective change by firing `customer.subscription.updated` via `stripe trigger` or manual SQL on `subscription_tier`). The Billing tab should render an amber banner "Your organization has 6 members but the Essentials plan allows 5. Remove 1 member or upgrade to clear this warning." Writes should still work (overage is a nudge, not a lockout).
>
> **UI/UX quality audit:**
> - Status badge colors match semantic meanings (green for active, red for canceled, amber for past_due, blue for trialing).
> - Countdown text reads naturally at 30/14/7/3/1 days.
> - Button widths and spacing match the existing Settings tabs.

- [ ] **Step 3: Resolve any FAIL or POLISH issues the qa-verify agent reports**

Do not proceed until the agent confirms all checks pass.

- [ ] **Step 4: Commit any bug-fix diffs from QA verification**

```bash
git status
# if there are fixes
git add <files>
git commit -m "fix(billing): address QA findings from browser verification"
```

---

## Phase 12 — Developer Docs

### Task 25: Write docs/stripe-setup.md

**Files:**
- Create: `docs/stripe-setup.md`

- [ ] **Step 1: Write the setup doc**

Create `docs/stripe-setup.md`:

```markdown
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
4. Copy the **Secret key** (starts with `sk_test_`).
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

1. Log in the CLI once: `stripe login` (opens a browser).
2. Start forwarding (leave this terminal running while you develop):

    ```bash
    stripe listen --forward-to localhost:8000/billing/webhook
    ```

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
```

- [ ] **Step 2: Commit**

```bash
git add docs/stripe-setup.md
git commit -m "docs(billing): developer setup guide for Stripe test mode"
```

---

## Self-Review (for the implementer)

Before closing the task:

- [ ] **All tests pass:** `cd backend && source .venv/bin/activate && pytest -q` and `cd frontend && npm run check && npm run test`.
- [ ] **Smoke test still works:** Register a user, confirm Stripe customer + subscription appear, confirm webhook fires, confirm Billing tab renders correctly.
- [ ] **The dep sweep is complete:** spot-check a write endpoint in each non-exempt router file — `grep -c "require_active_subscription" app/api/endpoints/*.py` should show a nonzero count in every non-exempt file listed in Task 16.
- [ ] **Audit logs are written:** after firing a webhook-driven tier change (manually via `stripe trigger customer.subscription.updated`), confirm a new row in `audit_logs` with `entity_type='Organization'` and `changes->'subscription_tier'` containing before/after values.
- [ ] **No sensitive keys committed:** `git log -p` and `git grep -E "sk_test_|sk_live_|whsec_"` should return no matches across staged or committed files.
- [ ] **`.env.example` placeholders updated:** the file should contain stubs, never real values.

## Task Closure (after user confirms)

1. Update ClickUp task `86e0ja78c` → status "complete" with a summary comment of files changed and tests added.
2. Exit the worktree with `ExitWorktree` action "keep" (preserves the commits for merge).
