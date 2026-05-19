---
name: f0088-equipment-registry-qa
description: QA findings for F-0088 Equipment Registry & First-class Sites feature
metadata:
  type: project
---

# F-0088 Equipment Registry QA

**Date:** 2026-05-18

## Infrastructure notes

- F-0088 worktree is at `/home/wesuuu/Code/trellisbio/.claude/worktrees/f0088-equipment-registry`
- Worktree had NO running servers at QA time — had to start them manually
- Backend started on port 8040 (`uvicorn app.main:app --port 8040`)
- Frontend started on port 5193 (`VITE_API_PORT=8040 npx vite --port 5193`)
- System inotify watch limit was exhausted (too many other worktrees' Vite servers running) — needed to patch `vite.config.ts` temporarily to add `server.watch.ignored: ['**']`, then restart after the fix

## Bugs fixed

### FAIL 1: SiteList col-span-3 missing (layout bug)
- `SiteList.svelte` rendered `<aside class="site-rail">` with no grid column class
- Inside a `grid-cols-12` page layout, the aside defaulted to `col-span-1`, making the left rail ~85px wide and causing the sticky `<nav>` to intercept click events on the `+ New` button
- **Fix**: Added `col-span-3` to the aside in `SiteList.svelte` line 15
- File: `frontend/src/lib/components/sites/SiteList.svelte`

### FAIL 2: ck_org_member_roles check constraint blocks SITE_MANAGER (migration bug)
- Migration `f0088_sites_equipment.py` tried to drop `ck_organization_members_roles_valid` and add a new version, but the existing constraint is named `ck_org_member_roles`
- Result: old `ck_org_member_roles` constraint remained; `PATCH /iam/organizations/.../members/...` with `SITE_MANAGER` in roles returned 500 IntegrityError
- **Fix**: Updated migration to drop `ck_org_member_roles` (old name) AND `ck_organization_members_roles_valid` before adding new constraint as `ck_org_member_roles` with `SITE_MANAGER` included
- File: `backend/alembic/versions/f0088_sites_equipment.py` lines 121-126 and 165-169
- Re-ran `alembic downgrade -1 && alembic upgrade head` to apply

## Verified items

- A1: Default Site auto-created, appears in left rail, col-span-3 applied ✓
- A2: `+ New` button opens SiteFormDialog, creates site, appears in rail ✓
- A3: Rename button opens prefilled SiteFormDialog, saves update ✓
- A4: Archive wizard: 3-step (Destination → Review moves → Confirm & archive) ✓
- A5: Default site archive button disabled, tooltip set ✓
- A6: Equipment filter bar, `+ Add equipment` → EquipmentFormDialog with site prefilled as "Default Site" ✓
- B: Managers panel shows on non-default sites; "Add site managers" picker lists org users with checkboxes; 1+ granted badge updates ✓
- C: MemberRolesPicker popover: Admin/Billing/Protocol approver/Site manager/Member options; ticking Site manager shows inline "Managed sites / Select at least one site / + Add site" section; SITE_MANAGER badge shows destructive (red) border with 0 sites; badge appears in member row table ✓
- D: Inspector "Manage Equipment" button opens EquipmentPickerModal with equipment list; "+ Add New Equipment" toggles create form with Name/Type/Room/Bench/Site fields; site defaults to localStorage `f0088:lastSiteId` (falls back to org default); `localStorage.getItem('f0088:lastSiteId')` set correctly ✓
- D4: `GET /equipment` returns 200; old `/iam/organizations/.../equipment` path returns 404 ✓

## No console errors

Zero `console.error` or `pageerror` events across all test flows.

## Remaining untested

- Revoke confirmation dialog (unticking SITE_MANAGER when sites already granted) — couldn't test because org only had 1 user (admin) and sites were sparse
- Archive wizard "Confirm & archive" submit step (tested up to step 3 screenshot but didn't click final confirm)
- Equipment tag editing inline
- Equipment soft-delete / archive row flow

**Why:** relates to [[f0088-equipment-registry-qa]]
