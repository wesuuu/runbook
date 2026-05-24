---
name: f0019d-lifecycle-coupling
description: Coupling map for F-0019d in-app lifecycle surfacing — Loops webhook + SubscriptionBanner. Key blast-radius sites for NotificationEventType.LIFECYCLE addition.
metadata:
  type: project
---

## Key coupling sites found (F-0019d)

**NotificationEventType enum exhaustive-sync contracts (all MUST update for LIFECYCLE):**
- `backend/app/services/core/notifications/templates.py:265` — `TEMPLATES` dict, iterated by `test_all_event_types_have_templates` test which asserts `enum_values == template_keys`. Adding LIFECYCLE to enum WITHOUT a TEMPLATES entry breaks this test at line 40.
- `backend/app/services/core/notifications/policy.py:21` — `DEFAULT_POLICY` dict. Iterated by `test_notification_policy.py:15` assertion. `provisioning.py:88` also iterates DEFAULT_POLICY to seed subscriptions on user creation.
- `backend/tests/unit/test_notifications.py:34` — `test_all_event_types_have_templates`: asserts enum == TEMPLATES keys exactly.
- `backend/tests/unit/test_notification_policy.py:7` — asserts `DEFAULT_POLICY.keys() == expected` (the email-enabled subset from enum).

**AuthMiddleware exemption mechanism:**
- `backend/app/core/middleware.py:7` — `PUBLIC_PATHS` is a hardcoded `set` with exact path strings. `/billing/webhook` is one. `/webhooks/*` needs `startswith("/webhooks/")` added to the dispatch method's condition (line 36-40), mirroring the existing `/legal/` and `/internal/` startswith checks. NOT a regex; NOT a settings-driven list.

**`app_host` setting — does NOT exist yet in config.py.** The spec references `settings.app_host` for the allowlist in `links.py`. Must be added to `backend/app/core/config.py`.

**`links.py` _ROUTABLE frozenset:**
- `backend/app/services/core/notifications/links.py:33` — `_ROUTABLE = frozenset({"run", "experiment", "protocol", "project"})`. The resolver short-circuits to `None` for any entity_type not in this set. "lifecycle" must be handled by a new code branch BEFORE the _ROUTABLE gate, not added to _ROUTABLE (since lifecycle has no DB entity to look up — it gets link_url from payload directly).

**`backend/app/db/base.py`** — must import LoopsEvent from `models/lifecycle.py` for Alembic to see it in autogenerate. Pattern: line 5 imports `StripeEvent` from `models/billing.py`.

**Frontend EVENT_ICONS / EVENT_TONES:**
- `frontend/src/lib/notifications.ts:22` — `EVENT_ICONS` record. Falls back gracefully to `Bell` for unknown types (line 38). No update strictly required, but adding a LIFECYCLE entry gives it a distinct icon.
- `frontend/src/lib/notifications.ts:44` — `EVENT_TONES` record. Falls back to muted. Same situation.
- These are soft failures (SHOULD UPDATE), not hard breaks.

**Zod NotificationResponse schema:**
- `frontend/src/lib/schemas/notifications.ts` — `entity_type: z.string()` (open string), `event_type: z.string()` (open string). No enum-constrained type. No change needed for LIFECYCLE.

**`docs/loops-campaigns.md`** — file already exists. Spec says to APPEND an "Inbound" section.

**SubscriptionBanner placement in +layout.svelte:**
- `ConnectivityBanner` is at line 225 inside `{#if showNav}` / `{#if OFFLINE_ENABLED}`. The spec's mount point (below ConnectivityBanner) is correct.
- `SubscriptionLockoutModal` at line 254 is OUTSIDE the `{#if showNav}` block. The new SubscriptionBanner should be INSIDE showNav (matches spec).
- No layout tests exist — safe to add without breaking snapshots.

**Why:** Record these sites so future conversations on notification subsystem changes find them immediately.
**How to apply:** Any addition to NotificationEventType must also update TEMPLATES, DEFAULT_POLICY, and the test assertions. Any `links.py` entity_type branch must avoid the `_ROUTABLE` short-circuit.
