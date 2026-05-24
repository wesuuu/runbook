---
name: bug0008-protocol-editor-ui
description: BUG-0008 QA results — UnitOpNode text squish fix and EquipmentPickerModal layout/behavior fix (both passes)
metadata:
  type: project
---

## First Pass (original fix)

Both bugs in BUG-0008 confirmed fixed in the worktree (frontend :5243, backend :8070).

**Bug 1 — UnitOpNode param text squish in time mode:** PASS
- `.param-row` has `min-width: 0`; `.param-label` has `max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis`; `.param-value` has `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`
- Measured h=33px per row in time mode — single-line, no wrapping.

**Bug 2 — EquipmentPickerModal layout and behavior:** PASS
- Single scroll region; `+ Add New Equipment` hidden while create form open
- Discard resets form fields correctly; re-open shows empty fields
- IntersectionObserver drives sticky "Go to form ↓" correctly

## Second Pass (commit 1b5a298, second-pass review changes)

**Changes verified:**
1. Removed "✕ Close form" button from sticky search row — confirmed absent in all states
2. IntersectionObserver threshold 0.3 → 0 — 5px of form visible = button hidden (PASS)
3. UnitOpNode `title` split: `.param-row` now has NO title; `.param-label` has label text title; `.param-value` has value text title (PASS)

**Adversarial paths tested (#1, #3, #5, #6, #7, #10):**
- Long labels truncate with ellipsis; `title` attribute shows full text even when truncated. PASS.
- Rapid open/close (4 cycles via Escape): no stale form state on reopen. PASS.
- Discard mid-typing (4 fields filled): all reset, reopen shows empty fields. PASS.
- Threshold-0 edge: 5px form visible → "Go to form" hidden. PASS.
- Viewport 800px: dialog scrollWidth=clientWidth=510, no horizontal overflow. PASS.
- Empty submit: shows "Equipment name is required" error inline. PASS.

**Console errors: 0** (CORS errors are pre-existing — backend :8070 launched before CORS commit bfc40bb).

**CORS proxy pattern for this worktree:**
Backend :8070 started before CORS commit → :5243 origin rejected at runtime. QA driver workaround:
1. Use `page.route(API + '/**', ...)` to proxy all API requests server-side via `page.request.fetch()` (Playwright's request bypasses CORS)
2. Inject CORS headers (`Access-Control-Allow-Origin: FRONTEND`) into all responses
3. Also inject `cached_user`, `cached_orgs`, `cached_current_org` into localStorage so `initialize()` uses cache instead of calling `/auth/me`
4. Handle OPTIONS preflights with 204 + full CORS headers

**Why:** Stale uvicorn process (no --reload) doesn't pick up CORS changes post-commit.
**How to apply:** Any worktree QA driver where server started before the CORS commit should use this pattern.

**ADV#8 edge case:**
When org has no equipment (empty list), everything fits in the dialog without scrolling. "Go to form" correctly never appears. PASS.
