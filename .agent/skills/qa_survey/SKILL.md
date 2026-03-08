---
name: qa_survey
description: Use Chrome browser automation to survey the running app, test features as different users/roles, and produce a QA recommendations document. Use when the user asks to "survey the app", "QA the app", "test the app in the browser", "do a walkthrough", or runs /qa_survey. Requires Chrome browser tools and a running local dev environment.
---

# QA Survey Skill

Perform an interactive browser-based survey of the Runbook app, testing features across multiple user roles, and produce a structured QA report with recommendations.

## Prerequisites Check (MUST DO FIRST)

**Before doing anything else, verify browser tools are available:**

1. Call `mcp__claude-in-chrome__tabs_context_mcp` immediately.
2. If the call fails or the tool is not available, STOP and tell the user:
   > "The QA survey skill requires Chrome browser automation (claude-in-chrome). Please ensure the Chrome extension is running and try again."
3. Do NOT proceed with any other steps if Chrome is unavailable.

**Then verify the app is running:**

4. Try navigating to `http://localhost:5173` — if it fails, tell the user to start the frontend (`/frontend_dev`).
5. Try fetching `http://localhost:8000/docs` — if it fails, tell the user to start the backend (`/backend_dev`).

## Getting Test Users

Query PostgreSQL directly to get available users and their roles:

```bash
PGPASSWORD=postgres psql -h localhost -U postgres -d runbook -c "
SELECT u.email, u.full_name, u.is_active,
       COALESCE(string_agg(DISTINCT t.name, ', '), 'No team') as teams
FROM users u
LEFT JOIN team_members tm ON u.id = tm.user_id
LEFT JOIN teams t ON tm.team_id = t.id
GROUP BY u.id, u.email, u.full_name, u.is_active
ORDER BY u.email;
"
```

Use the returned email addresses for login testing. **Password does not matter** — the backend's `auth_enabled` may be set to `False`, in which case any password works. If auth IS enabled, use `password123` as the password for all seed users.

## Login Procedure

For each user you test:

1. Navigate to `http://localhost:5173/login`
2. Enter the user's email in the email field
3. Enter `password123` in the password field
4. Click "Sign In"
5. If login fails, try with any other password (auth may be disabled)
6. Verify redirect to home page and that the user's name/email appears in the UI

## Test Plan

Survey the app as **at least 3 different users** with different permission levels (admin, team owner/editor, viewer). For each user, test the following areas and note any issues:

### 1. Authentication & Navigation
- Login flow (success and error states)
- Navigation between pages (sidebar, breadcrumbs)
- Logout and re-login
- Route protection (can unauthenticated users access protected pages?)

### 2. Projects Page (`/projects`)
- Project list loads and displays correctly
- Projects visible match user's permissions
- Create new project (if user has permission)
- Click into a project detail page

### 3. Project Detail (`/projects/[id]`)
- Tabs load correctly (Protocols, Runs, Activity, Settings)
- Protocol list displays
- Run list displays
- Activity feed loads
- Settings tab (if user has admin access)
- Permission-appropriate actions visible (edit vs view-only)

### 4. Protocol Editor (`/protocols/[id]`)
- Graph canvas renders
- Unit operation sidebar loads with available ops
- Drag and drop works (if editor)
- Node selection and Inspector panel
- Save functionality
- Version management (if applicable)
- Read-only behavior for viewers

### 5. Runs (`/runs/[id]`)
- Run details load
- Role assignments visible
- Execution state displays correctly
- PDF export buttons work
- Role wizard interaction (if applicable)

### 6. Settings (`/settings`)
- Organization settings load
- Team management visible
- Member list displays
- Appropriate admin-only features hidden for non-admins

### 7. Export (`/export`)
- Export page loads
- Data preview renders
- Download functionality

### 8. Cross-Cutting Concerns
- Responsive layout (resize browser window to tablet/mobile widths)
- Loading states (are spinners/skeletons shown during data fetches?)
- Error states (what happens with bad data or failed requests?)
- Empty states (what do pages show when there's no data?)
- Console errors (check for JavaScript errors in browser console)
- Network errors (check for failed API calls)

## Recording

When testing multi-step workflows, use `mcp__claude-in-chrome__gif_creator` to record the interaction for the user to review. Name GIFs descriptively (e.g., `qa_login_flow.gif`, `qa_protocol_editor.gif`).

## Console & Network Monitoring

After visiting each major page:
1. Use `mcp__claude-in-chrome__read_console_messages` to check for JavaScript errors
2. Use `mcp__claude-in-chrome__read_network_requests` to check for failed API calls (4xx/5xx)
3. Log any errors found in the report

## Output

Write all findings to `QA_SURVEY.md` in the project root. Use this format:

```markdown
# QA Survey Report

> Automated browser survey of the Runbook app
> Date: YYYY-MM-DD
> Users tested: (list emails)

## Summary
- Total issues found: X
- Critical: X | High: X | Medium: X | Low: X

## Issues

### [QA-XXXX] Short description
- **Severity**: Critical | High | Medium | Low
- **Category**: UI/UX | Functionality | Performance | Accessibility | Security | Data
- **Page**: /path/to/page
- **User**: email@example.com (role)
- **Steps to Reproduce**:
  1. Step one
  2. Step two
- **Expected**: What should happen
- **Actual**: What actually happened
- **Screenshot/GIF**: (filename if captured)
- **Console Errors**: (any relevant errors)
- **Recommendation**: How to fix it

## Recommendations
(Prioritized list of improvements)
```

## Severity Guidelines

- **Critical**: App crashes, data loss, security bypass, feature completely broken
- **High**: Feature partially broken, wrong data displayed, permission issue
- **Medium**: UI glitch, confusing UX, missing loading/error state, console errors
- **Low**: Minor styling, nice-to-have improvement, accessibility suggestion

## Important Notes

- Do NOT trigger JavaScript alerts or confirm dialogs — they block the extension
- If a page seems stuck, check console for errors before retrying
- Take screenshots of significant issues
- Test with the browser resized to ~768px width to simulate tablet usage
- Be thorough but efficient — spend 2-3 minutes per page maximum
- If you encounter a blocking error on one page, note it and move on to the next
