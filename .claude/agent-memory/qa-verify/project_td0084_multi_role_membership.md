---
name: TD-0084 Multi-Role Org Membership QA
description: QA findings and fixes for the MemberRolesPicker chip+popover component and multi-role PATCH endpoint
type: project
---

Feature: Settings → Organization tab replaces single-select role dropdown with MemberRolesPicker chip+popover.

**Critical bug fixed during QA**: Backend `PATCH /iam/organizations/{org_id}/members/{user_id}` at `backend/app/api/endpoints/iam.py` line ~378 had no last-admin guard. It checked max-3-admins when ADDING admin, but had no guard when REMOVING admin. A lone org admin could remove their own ADMIN role and lock the org. Fixed by adding a `losing_admin` check that returns HTTP 400 "Cannot remove the last admin from an organization" before committing.

**Polish fix**: `MemberRolesPicker.svelte` chip container used `flex items-center gap-1.5 flex-wrap` as a single flat div including the trigger button. With 3+ roles, the `▾` trigger button wrapped to a new row below all chips, looking orphaned. Fixed by wrapping chips in an inner `<div class="flex items-center gap-1.5 flex-wrap min-w-0">` while keeping the outer `<div class="flex items-center gap-1.5 min-w-0">` for the chips group + trigger. Now the trigger stays on the same flex row as the chips group's last row.

**Component: MemberRolesPicker.svelte** at `frontend/src/lib/components/settings/MemberRolesPicker.svelte`
- Commit on popover close (Escape or click-outside), not on each checkbox toggle
- `draft` state resets to `roles` prop when popover closes WITHOUT a change commit (via `$effect(() => { if (!open) draft = [...roles]; })` — but note this runs after `commit()`, so the reset only fires if `onChange` wasn't called via the no-change guard in `commit()`)
- MEMBER role is always added server-side and always shown as locked grey chip
- `disabled` prop hides the trigger entirely (no popover for non-admins)

**Viewer user 403**: `viewer@bioprocess.com` gets 403 on `/iam/organizations/{org_id}/members` fetch — correct, viewer is not an org member in the Acme Biologics org in the seed data.

**Mobile behavior**: On 375px, the mobile card subrow shows chips with `flex-wrap` and chips may stack to 2 lines — acceptable at this viewport width. Popover opens upward (Radix auto-repositions) which looks slightly awkward but is standard popover behavior. Not a bug.

**Filter**: `memberFilterFn` joins all role values with space and lowercases for search: `(item.roles ?? []).join(' ').toLowerCase()`. Searching "billing" or "admin" correctly finds members with those roles.

**Why:** Backend guard was simply missing from the implementation — max-admins-cap check was written but the inverse (min-1 guard) was not. Frontend chip wrapping was a flex layout oversight.
