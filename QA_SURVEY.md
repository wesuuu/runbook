# QA Survey Report

> Automated browser survey of the Runbook app
> Date: 2026-03-07
> Users tested: admin@bioprocess.com (Admin), scientist1@bioprocess.com (Upstream Team), viewer@bioprocess.com (QA Team — API only)

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| UI/UX | 0 | 0 | 3 | 2 | 5 |
| Performance | 0 | 1 | 0 | 0 | 1 |
| Data | 0 | 0 | 2 | 0 | 2 |
| Accessibility | 0 | 0 | 0 | 1 | 1 |
| **Total** | **0** | **1** | **5** | **3** | **9** |

*Last surveyed: 2026-03-07*
*Users tested: admin@bioprocess.com, scientist1@bioprocess.com, viewer@bioprocess.com*

---

## Issues

### [QA-0005] Duplicate API calls on page load — /projects called with and without trailing slash
- **Severity**: High
- **Category**: Performance
- **Page**: / (Dashboard)
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Log in as admin
  2. Navigate to Dashboard
  3. Monitor network requests
- **Expected**: Single API call per resource
- **Actual**: Two project list requests fire on dashboard load: `GET /projects?organization_id=...` (returns 200) and `GET /projects/?organization_id=...` (307 redirect → pending). The trailing-slash variant triggers a redirect, causing an extra round trip.
- **Network Errors**: `GET /projects/?organization_id=...` → 307 redirect
- **Recommendation**: Normalize API URLs in `lib/api.ts` to never include trailing slashes, or configure FastAPI `redirect_slashes=False`.

### [QA-0006] Projects page has redundant subtitle text
- **Severity**: Medium
- **Category**: UI/UX
- **Page**: /projects
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Navigate to /projects
  2. Observe two description lines: "A list of all projects in your organization." (under "All Projects") and "A list of your recent projects." (above the table)
- **Expected**: Single, clear description
- **Actual**: Two overlapping subtitles create confusion — one says "all projects in your organization" and another says "your recent projects"
- **Recommendation**: Remove the duplicate subtitle. Keep one accurate description.

### [QA-0007] Organization column shows "N/A" for all projects
- **Severity**: Medium
- **Category**: Data
- **Page**: /projects
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Navigate to /projects
  2. All 3 projects show "N/A" in the Organization column
- **Expected**: Projects should display their associated organization name
- **Actual**: Organization column shows "N/A" for every project despite the user belonging to "BioProcess Inc"
- **Recommendation**: Check that the projects API returns the organization name. If all users belong to a single org, consider removing the Organization column entirely.

### [QA-0008] Runs table has inconsistent checkbox rendering
- **Severity**: Medium
- **Category**: UI/UX
- **Page**: /projects/[id]?tab=runs
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Navigate to any project detail → Runs tab
  2. First row ("ai" run) does not have a checkbox, while other rows do
- **Expected**: All rows should have consistent checkbox presence
- **Actual**: The first run row is missing its selection checkbox while other rows display them
- **Recommendation**: Investigate why some runs don't render the checkbox. May be conditional based on run status or a rendering bug.

### [QA-0009] No mobile responsive design — tables and nav overflow on small screens
- **Severity**: Medium
- **Category**: UI/UX
- **Page**: All pages
- **User**: All users
- **Steps to Reproduce**:
  1. Access the app on a mobile device or resize browser to <768px width
  2. Navigation bar items overflow or get squished
  3. Data tables don't adapt to small screens
- **Expected**: Responsive layout with collapsible nav and mobile-friendly table views
- **Actual**: Fixed desktop layout with no responsive breakpoints for mobile. Navigation uses fixed `gap-6` spacing. Tables use fixed column widths. Dashboard counter cards stay in 3+ column grid on all widths.
- **Recommendation**: See feature spec [F-0008] in FEATURES.md for detailed implementation plan. Key changes: hamburger menu for nav, card-based table layouts on mobile, `sm:` breakpoint coverage.

### [QA-0010] Error message "Failed to fetch" is not user-friendly
- **Severity**: Medium
- **Category**: Data
- **Page**: / (Dashboard), /projects
- **User**: scientist1@bioprocess.com
- **Steps to Reproduce**:
  1. Trigger any API failure (e.g., 500/503 from backend)
  2. Dashboard shows "Failed to fetch" with a Retry button
  3. Projects page shows "Error: Failed to fetch" in a red banner
- **Expected**: User-friendly error messages with actionable guidance
- **Actual**: Raw "Failed to fetch" error provides no context. Different pages show errors inconsistently (centered icon vs. red banner).
- **Recommendation**: Standardize error display with a consistent component. Show friendly messages (e.g., "Something went wrong. Please try again.") with optional technical details.

### [QA-0011] Dashboard "Active Runs" counter (5) doesn't match displayed list (3)
- **Severity**: Low
- **Category**: UI/UX
- **Page**: / (Dashboard)
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Log in as admin
  2. Counter card shows "5 ACTIVE RUNS"
  3. Active Runs section only displays 3 runs
- **Expected**: Counter matches displayed items, or scope difference is clearly labeled
- **Actual**: Mismatch between counter (5 org-wide) and list (3 user-relevant). No indication that the list is filtered.
- **Recommendation**: Add "View all" link, or label the counter as "Org Active Runs" vs the list as "My Active Runs."

### [QA-0012] Protocol editor blocks navigation via URL bar
- **Severity**: Low
- **Category**: UI/UX
- **Page**: /protocols/[id]
- **User**: admin@bioprocess.com
- **Steps to Reproduce**:
  1. Open a protocol in the editor
  2. Attempt to navigate to a different page via URL bar or programmatic navigation
  3. Navigation is blocked — page stays on protocol editor
- **Expected**: Navigation should work from any page
- **Actual**: The protocol editor intercepts navigation attempts, likely due to the `beforeunload` unsaved-changes handler.
- **Recommendation**: Ensure the `beforeunload` handler shows a confirmation but doesn't block programmatic navigation completely. Check for custom route guards.

### [QA-0013] Login page lacks visible error feedback for wrong credentials
- **Severity**: Low
- **Category**: Accessibility
- **Page**: /login
- **User**: N/A
- **Steps to Reproduce**:
  1. Cannot test — auth is currently disabled (`auth_enabled=False`), all credentials accepted
- **Expected**: Clear inline error for invalid credentials when auth is enabled
- **Actual**: Unable to verify error state. Should be tested before enabling auth in production.
- **Recommendation**: Test login error UX with auth enabled. Ensure form shows inline validation messages.

---

## Pages Surveyed

| Page | Admin | Scientist | Notes |
|------|-------|-----------|-------|
| Login | Pass | Pass | Auth disabled; any credentials work |
| Dashboard | Pass (initially) | **FAIL** (503) | Backend error for non-admin; degrades for all |
| Projects List | Pass | **FAIL** (503) | Backend error for non-admin |
| Project Detail — Protocols | Pass | Not tested | 8 protocols displayed correctly |
| Project Detail — Runs | Pass | Not tested | 10 runs; checkbox inconsistency on first row |
| Project Detail — Activity | Pass | Not tested | Timeline with filter chips working |
| Project Detail — Settings | Pass | Not tested | Protocol approval + access control |
| Protocol Editor | Pass | Not tested | Graph canvas, sidebar, toolbar all functional |
| Run Detail | Pass | Not tested | Edit tracking with strikethrough values working |
| Settings — Organization | Pass | Partial | Non-admin: "No members found" + visible admin actions |
| Settings — Teams | Pass | Not tested | 3 teams listed with expand/delete |
| Export | Pass (empty) | Not tested | Empty state shown (no runs selected) |

---

## Recommendations

### Priority 1 — Fix Soon
1. **Deduplicate API calls** — normalize URL trailing slashes in `lib/api.ts`

### Priority 2 — Improve
2. **Standardize error handling UI** across all pages with consistent component
3. **Fix checkbox consistency** in runs table
4. **Remove redundant subtitle** on projects page
5. **Implement mobile responsive design** per [F-0008] in FEATURES.md
6. **Clarify dashboard counter vs. list scope** for Active Runs mismatch
