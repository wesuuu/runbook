# QA Survey Archive

Resolved QA issues moved from `QA_SURVEY.md`. These items are retained for reference.

---

### [QA-0001] Dashboard and Projects endpoints return 500/503 for non-admin users
- **Severity**: ~~Critical~~ **FIXED**
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
- **Resolution**: Was caused by backend server degradation after extended uptime (QA-0002). Both endpoints return 200 for admin and non-admin users after server restart. Confirmed via curl with scientist1 and admin tokens.
- **Archived**: 2026-03-08

### [QA-0002] Backend server degrades over time — eventually returns 500 for all users
- **Severity**: ~~Critical~~ **DEFERRED**
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
- **Reason**: Server restart resolved the immediate issue. Root cause (missing `pool_recycle`/`pool_pre_ping` in `db/session.py` engine config) still needs to be addressed but requires load testing to verify. Session disposal in `get_db` looks correct (`async with` + `session.close()`).
- **Archived**: 2026-03-08

### [QA-0003] Settings Organization tab shows "No members found" for non-admin users
- **Severity**: ~~High~~ **FIXED**
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
- **Resolution**: The backend already allows any org member to list members (no admin required). The "No members found" was caused by `loadMembers()` silently catching API errors and setting `members = []`. Fixed frontend to show proper error message on failure (`membersError` state + error display in template). Added 2 backend tests: `test_list_org_members_as_non_admin` (200 with full list) and `test_list_org_members_non_member_forbidden` (403). Also fixed pre-existing broken `Role` import in `tests/conftest.py`.
- **Archived**: 2026-03-08

### [QA-0004] Non-admin users see "Invite Member" button on Organization settings
- **Severity**: ~~High~~ **FIXED**
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
- **Resolution**: Added `isOrgAdmin` derived state (checks current user's role in members list). Gated behind `{#if isOrgAdmin}`: Invite Member button, role dropdown, Remove button, invite dialog, Create Team form, Delete Team button. Non-admins see member list read-only with role labels. Verified with `npm run check` (0 new errors).
- **Archived**: 2026-03-08
