# QA Survey Report

> Automated browser survey of the Runbook app
> Date: 2026-03-07
> Users tested: admin@bioprocess.com (Admin), scientist1@bioprocess.com (Upstream Team), viewer@bioprocess.com (QA Team — API only)

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Functionality | 2 | 1 | 0 | 0 | 3 |
| UI/UX | 0 | 0 | 3 | 2 | 5 |
| Performance | 0 | 1 | 0 | 0 | 1 |
| Security | 0 | 1 | 0 | 0 | 1 |
| Data | 0 | 0 | 2 | 0 | 2 |
| Accessibility | 0 | 0 | 0 | 1 | 1 |
| **Total** | **2** | **3** | **5** | **3** | **13** |

*Last surveyed: 2026-03-07*
*Users tested: admin@bioprocess.com, scientist1@bioprocess.com, viewer@bioprocess.com*

---

## Issues

### [QA-0001] Dashboard and Projects endpoints return 500/503 for non-admin users
- **Severity**: Critical
- **Category**: Functionality
- **Page**: / (Dashboard), /projects
- **User**: scientist1@bioprocess.com (Upstream Team)
- **Steps to Reproduce**:
  1. Log in as scientist1@bioprocess.com
  2. Dashboard loads with "Failed to fetch" error and Retry button
  3. Navigate to /projects — shows "Error: Failed to fetch" in a red banner
  4. Retry button does not resolve the issue
- **Expected**: Dashboard and projects list should load for all authenticated users
- **Actual**: Both endpoints return HTTP 503 (Service Unavailable) or 500 (Internal Server Error). Only `/auth/me`, `/iam/organizations`, and `/notifications/unread-count` return 200.
- **Console Errors**: None (error handled gracefully in UI)
- **Network Errors**: `GET /dashboard?org_id=...` → 503, `GET /projects?organization_id=...` → 503
- **Recommendation**: Investigate the backend `/dashboard` and `/projects` endpoints for errors when the requesting user is not an org admin. Check database connection pool health — the server has been running since March 2 and may have exhausted connections. Add backend error logging with tracebacks for 500s.

### [QA-0002] Backend server degrades over time — eventually returns 500 for all users
- **Severity**: Critical
- **Category**: Functionality
- **Page**: All API-dependent pages
- **User**: All users
- **Steps to Reproduce**:
  1. Backend server running since March 2 (5+ days without restart)
  2. Initially works for admin user (dashboard, projects, runs all load)
  3. After continued use, `/dashboard` and `/projects` start returning 500 for admin too
  4. Auth endpoints (`/auth/login`, `/auth/me`) continue working
- **Expected**: Backend should handle sustained operation without degradation
- **Actual**: After extended runtime, complex query endpoints start failing with 500 while simple endpoints still work. Suggests database connection pool exhaustion or session leak.
- **Recommendation**: Add connection pool monitoring. Check SQLAlchemy async session lifecycle — ensure sessions are properly closed after each request (verify `get_db` dependency disposes sessions). Consider adding a health check endpoint that validates DB connectivity. Add `pool_recycle` and `pool_pre_ping` settings to the engine config.

### [QA-0003] Settings Organization tab shows "No members found" for non-admin users
- **Severity**: High
- **Category**: Functionality
- **Page**: /settings (Organization tab)
- **User**: scientist1@bioprocess.com (Upstream Team)
- **Steps to Reproduce**:
  1. Log in as scientist1@bioprocess.com
  2. Navigate to /settings
  3. Organization tab shows "BioProcess Inc" but lists "No members found."
- **Expected**: Non-admin users should see organization members (read-only), or the member list should show a clear "access denied" message
- **Actual**: Shows "No members found" as if the org is empty — misleading. The API either returns an empty list or fails silently.
- **Recommendation**: Either grant read access to the member list endpoint for all org members, or show a "You don't have permission to view members" message instead of the misleading "No members found."

### [QA-0004] Non-admin users see "Invite Member" button on Organization settings
- **Severity**: High
- **Category**: Security
- **Page**: /settings (Organization tab)
- **User**: scientist1@bioprocess.com (Upstream Team)
- **Steps to Reproduce**:
  1. Log in as scientist1@bioprocess.com
  2. Navigate to /settings → Organization tab
  3. "Invite Member" button is visible
- **Expected**: Only admins should see the "Invite Member" button
- **Actual**: Non-admin users can see and potentially click the invite button. Even if the backend rejects the request, the UI should not show admin-only actions to non-admins.
- **Recommendation**: Conditionally render admin-only actions (Invite Member, Make Admin, Remove Admin, Remove) based on the user's admin status. The `is_admin` flag should be checked from the auth context.

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

### Priority 1 — Fix Now
1. **Investigate and fix backend 500/503 errors** for non-admin users on `/dashboard` and `/projects`. This completely blocks non-admin users from using the app. Check the `get_visible_project_ids()` function and related queries for errors when user lacks admin role.
2. **Fix database connection pool health** — add `pool_recycle=3600`, `pool_pre_ping=True` to SQLAlchemy engine config. Ensure async sessions are properly disposed in the `get_db` dependency. Restart the backend server to restore service.

### Priority 2 — Fix Soon
3. **Hide admin-only UI actions** from non-admin users on Settings page (Invite Member, Make Admin, Remove)
4. **Fix member list visibility** for non-admin users — show members read-only or show permission message
5. **Deduplicate API calls** — normalize URL trailing slashes in `lib/api.ts`

### Priority 3 — Improve
6. **Standardize error handling UI** across all pages with consistent component
7. **Fix checkbox consistency** in runs table
8. **Remove redundant subtitle** on projects page
9. **Implement mobile responsive design** per [F-0008] in FEATURES.md
10. **Clarify dashboard counter vs. list scope** for Active Runs mismatch
