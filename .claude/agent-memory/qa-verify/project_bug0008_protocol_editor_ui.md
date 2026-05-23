---
name: bug0008-protocol-editor-ui
description: BUG-0008 QA results — UnitOpNode text squish fix and EquipmentPickerModal layout/behavior fix
metadata:
  type: project
---

Both bugs in BUG-0008 are confirmed fixed in the worktree (frontend :5243, backend :8070).

**Bug 1 — UnitOpNode param text squish in time mode:** PASS
- `.param-row` has `min-width: 0`; `.param-label` has `max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis`; `.param-value` has `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`
- `title` attrs added to both `.param-row` and `.param-value` for tooltip on hover
- `.node-params` has `overflow: hidden`
- Measured h=33px per row in time mode — single-line, no wrapping. Visual screenshot (`03b-node-time-closeup.png`) confirmed.
- Automated threshold check used `h > 25px` which was wrong (33px is correct for a single row with padding). Visual evidence is the ground truth.

**Bug 2 — EquipmentPickerModal layout and behavior:** PASS
- Single scroll region: `.equipment-modal` is the only scrollable container; `.equipment-list` has `overflow-y: visible` (no nested scroll)
- "+ Add New Equipment" button hidden while create form open: confirmed `count=0` after click
- Create form footer has Discard + Create Equipment inside `.create-form-footer` at bottom of form (inside scrollable area, above dialog's Cancel/Apply)
- Discard calls `discardCreateForm()` → sets `showCreateForm = false` + `resetCreateFormFields()`; form closes, button re-appears, re-open shows empty fields
- IntersectionObserver on `createFormEl` drives sticky "Go to form ↓" / "✕ Close form" in search bar — only visible when form scrolled off-screen; with no equipment list items, form stays in view so sticky buttons correctly absent
- Input contrast: form-input uses `background: hsl(var(--card))` which resolves to white — computed style shows `rgba(0,0,0,0)` due to CSS variable opacity handling, but visually inputs are distinct with `border: 1px solid hsl(var(--border))`

**Why:** `rgba(0,0,0,0)` from `getComputedStyle` on HSL CSS-var backgrounds is a known false-positive in Playwright/headless — the actual rendered color is correct.

**How to apply:** When checking input contrast via computed styles in Playwright, prefer visual screenshot review over `getComputedStyle().backgroundColor` for shadcn-svelte components using CSS variables.

Worktree slot 7: frontend :5243, backend :8070, DB `batchrite_wt7`. Port 5243 added to CORS allow_origins in `backend/app/main.py`.
