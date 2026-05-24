---
name: f0019d-lifecycle-surfacing-coupling
description: Coupling sites for F-0019d in-app lifecycle surfacing — webhook, LIFECYCLE enum, banner, links.py
metadata:
  type: project
---

Coupling analysis for F-0019d (2026-05-24). Key findings:

**Template function signature mismatch**: TEMPLATES functions all take `(ctx: dict, personal: bool = True) -> tuple[str, str]` but the plan's `lifecycle()` stub uses `(context: dict) -> TemplateResult`. The exhaustive test calls `TEMPLATES["X"](ctx, personal=True)` — the stub will TypeError at runtime.

**settings page EVENT_TYPES list** is hardcoded at `frontend/src/routes/settings/+page.svelte:108-120`. Already missing several enum values (RUN_SIGNOFF_REQUESTED, RUN_SIGNOFF_CANCELLED, PENDING_IMAGE_ANALYSIS, OFFLINE_SYNC_PENDING). LIFECYCLE should NOT appear here (DEFAULT_POLICY has in_app=False, email=False) but the list is already inconsistent with the enum — worth noting.

**SubscriptionBanner placement in layout.svelte**: banner should go between ConnectivityBanner (line 224-226) and the nav's closing tag (line 227). Plan says "above the nav" but the code shows ConnectivityBanner is BELOW nav inside `{#if showNav}`. SubscriptionBanner must also go inside that block to be suppressed on auth routes.

**SubscriptionLockoutModal already exists** at `frontend/src/lib/components/shared/SubscriptionLockoutModal.svelte` and is already rendered in +layout.svelte at line 254 (triggered via lockoutModal store, opened by api.ts on 402). The new SubscriptionBanner locked-out variant creates a visual overlap concern — two separate locked-out surfaces.

**layout.svelte onMount**: no existing `loadSubscription()` call — plan adds it. But `loadSubscription` is already importable from subscription.svelte.ts. No onDestroy cleanup is registered for the refresh listener — plan adds it. Must use `let cleanupSubRefresh: (() => void) | undefined` declared outside onMount.

**links.py short-circuit**: line 123 `if not targets: return {n.id: None for n in notifications}` is a short-circuit that fires AFTER the entity-grouping loop (lines 66-69). Lifecycle notifications with entity_type="lifecycle" won't enter ids_by_type (not in _ROUTABLE), so they're not in targets either. The short-circuit at line 123 fires if ALL notifications are lifecycle, returning None for all — the plan's insertion point (before line 64 grouping) is correct, but the merge at the end (step 4 description) is slightly off: need `{**out, **result_map}` or `result_map.update(out)` before returning.

**backend/.env.example**: no LOOPS entries at all. `BATCHRITE_LOOPS_WEBHOOK_SECRET` is missing.

**hmac.new**: valid Python (alias for `hmac.HMAC`). Not a bug.

**NotificationEventType exhaustive test** (`test_all_event_types_have_templates`): asserts `enum_values == template_keys`. Task 5 must add LIFECYCLE to TEMPLATES — the plan covers this. But the template function signature must match the existing pattern `(ctx, personal=True) -> tuple[str, str]`, not `(context) -> TemplateResult`.
