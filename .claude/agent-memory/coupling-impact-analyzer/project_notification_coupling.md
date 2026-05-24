---
name: notification-coupling-map
description: Coupling map for the notification subsystem — call sites, schema consumers, test fixtures, and frontend bell behavior
metadata:
  type: project
---

## send_notification call sites (as of TD-0091d analysis)

**Actual invocation count: 13 call sites across 7 files.** The plan's "5 call sites" refers to files, not invocations.

| File | Lines | Style |
|------|-------|-------|
| `api/endpoints/runs.py` | 846, 988, 1002, 1029, 1447, 1492, 1575 | mixed: some positional, most keyword |
| `api/endpoints/auth.py` | 589 | positional |
| `api/endpoints/iam.py` | 590, 738 | positional |
| `api/endpoints/offline.py` | 100 | keyword |
| `api/endpoints/protocol_versions.py` | 457, 593 | positional (passed to `background_tasks.add_task`) |
| `api/endpoints/protocols.py` | 1006 | positional |
| `services/signoffs/requests.py` | 239, 273 | keyword |

**CRITICAL:** `runs.py:1575` uses POSITIONAL args (the late-added ROLE_UNASSIGNED site). Adding `payload` as a positional parameter instead of keyword-only would silently break these. The plan correctly adds `payload` as keyword-only after `context`. Safe.

## Notification model consumers that construct Notification() objects directly

**Tests that build Notification without payload (will rely on server_default):**
- `tests/unit/test_notifications.py:495,590`
- `tests/unit/test_notification_links.py:14`
- `tests/integration/test_notification_api.py:330,369,393,417,442,473,501,527`
- `tests/integration/test_notifications_gating.py:24`

These will work because `server_default="{}"::jsonb` covers them at DB level, and `default=dict` covers in-Python construction. No code changes needed in these test files.

## NotificationResponse Pydantic schema

`backend/app/schemas/notifications.py:64` — does NOT include `payload`. Intentional per spec/plan (payload consumed only by resolver, frontend reads resolved URL). The plan notes this explicitly.

## Frontend Zod schema

`frontend/src/lib/schemas/notifications.ts` — uses `.passthrough()` so payload from server would pass through silently. Intentionally not declared.

## goto(href) with fragments — two navigation paths

**NotificationBell:** `frontend/src/lib/components/layout/NotificationBell.svelte:116` — `goto(href)` bare, no fragment guard.  
**Notifications full page:** `frontend/src/routes/notifications/+page.svelte:111` — `goto(href)` bare, same issue.

Both need verification or the fallback `window.location.href` for hash URLs. The plan only checks the bell; the full-page inbox has identical code.

## RoleWizard mount points

- `routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte:1173` — receives `initialStepId` (plan covers this)
- `lib/components/run/RunEditMode.svelte:62` — does NOT receive `initialStepId` (by design; edit mode is not a notification target)

## FieldModeRoleWizard

`frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte:473,477,493,497` — has SAME `id="step-value"` and `id="step-notes"` collision. Explicitly out of scope per plan, but the same DOM id collision risk exists there.

## RunResultsSummary mount points

Mounted twice in `+page.svelte` — COMPLETED state (line 1370) and EDITED state (line 1534). Both need `data-step-id` stamps; the plan's Task 7 adds them to the component, so both instances are covered automatically.

## Seed scripts

`scripts/seed_db.py` — no direct notification inserts. No seed script changes needed.
