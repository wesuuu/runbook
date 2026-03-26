---
name: bug_fix
description: Pick up and fix bugs from the ClickUp BUGS list. Use when the user asks to "fix a bug", "squash a bug", "resolve BUG-XXXX", "work on bugs", or runs /bug_fix. Optionally pass a specific bug ID (e.g., /bug_fix BUG-0003) or priority level (e.g., /bug_fix critical). Documents the fix in the ClickUp task.
---

# Bug Fix

Fix bugs from the **ClickUp BUGS list** (list ID: `901712289456`), verify with tests, and document the fix in the ClickUp task.

## Process

1. **Fetch tasks from ClickUp** using `clickup_filter_tasks` on list `901712289456` to get the bug list and statuses.
2. **Select bug to fix**:
   - If the user specified a bug ID (e.g., `BUG-0003`), search for that task in ClickUp.
   - If the user specified a severity (e.g., `critical`, `high`), filter for the matching priority with open status.
   - If no argument given, show the user a summary of open bugs grouped by priority and ask which to fix.
3. **Research the bug** — read the task description in ClickUp and the source files in the Location field. Reproduce the bug mentally by tracing the code path. Understand the root cause before making changes.
4. **Create and present a plan** before writing any code:
   - Explain the root cause of the bug
   - List the files that will be modified
   - Describe the specific fix for each file
   - Note any risks or side effects
   - **Present the plan to the user and wait for approval.** Do NOT proceed until the user confirms.
   - If the user requests changes to the plan, revise and re-present.
5. **Write a failing test first** that reproduces the bug:
   - Backend: create/update test in `backend/tests/` that demonstrates the incorrect behavior
   - Frontend: create/update test in `frontend/src/**/*.test.ts` or `frontend/e2e/` as appropriate
   - Run the test to confirm it **fails** — this proves the bug exists and the test catches it
6. **Implement the fix** following project conventions (see CLAUDE.md):
   - Fix the root cause, not just the symptom
   - Keep changes minimal and focused on the bug
   - Don't refactor unrelated code in the same pass
7. **Run tests** to confirm the fix:
   - The previously failing test should now **pass**
   - Run the full relevant test suite to ensure no regressions:
     - Backend: `cd backend && source .venv/bin/activate && pytest tests/ -x -q`
     - Frontend: `cd frontend && npm run check && npm run test`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
8. **Browser verification (if frontend was changed)** — if any frontend component was added or modified, open the app in a Chrome browser using the `mcp__claude-in-chrome__*` tools and visually verify the fix behaves as expected:
   - Navigate to the relevant page(s) affected by the fix
   - Reproduce the original bug scenario — it should no longer occur
   - Interact with the fixed UI elements to confirm correct behavior
   - Check for visual regressions (misaligned elements, missing styles, broken responsiveness)
   - If anything looks wrong, fix it and re-run tests before proceeding
   - **"Leave site?" dialog workaround**: If navigation is blocked by a "Leave site?" dialog (e.g., unsaved changes on a page), open a **new tab** instead and navigate to the login screen from there.
   - **Authentication for testing**: To log in during browser verification, check the PostgreSQL dev database for user emails and roles (see `/local_dev` skill for credentials: `localhost:5432`, user `postgres`, password `postgres`, database `runbook`). Any password will work in the dev environment. Test with different user roles as needed to verify the fix across permission levels.
   - **Clean up test data**: If you created or modified any resources during browser verification (e.g., created sessions, projects, documents, or changed settings), you MUST revert them afterward. Delete created records or restore modified ones to their previous state using `psql` (`psql -h localhost -U postgres -d runbook`) or whatever method is easiest. Do not leave test artifacts in the database.
9. **Present results and request user verification** — print a summary of what was fixed, what the root cause was, and what tests were added. Then **ask the user to verify the fix** and confirm they are satisfied.
   - **Do NOT mark the ClickUp task as complete or document the fix until the user explicitly confirms.**
   - If the user requests changes:
     1. Discuss and plan the requested changes (present a revised plan, wait for approval)
     2. Implement the changes
     3. Re-run tests and browser verification as needed
     4. Present the updated results and ask the user to verify again
   - **Repeat this loop until the user explicitly says the fix is complete / they are satisfied.**
10. **Document the fix in ClickUp** — only after user confirmation. This is critical for traceability:
    - Use `clickup_create_task_comment` to add a detailed fix summary comment:
      ```
      ## Fix Summary

      **Root Cause**: [What was actually causing the bug]

      **Changes Made**:
      - `file/path.ts:line` — [what was changed and why]
      - `file/path.py:line` — [what was changed and why]

      **Tests Added/Updated**:
      - `tests/unit/test_xxx.py::test_name` — [what the test verifies]

      **Verification**: All tests passing. [any additional verification notes]
      ```
    - Use `clickup_update_task` to set the task status to `complete`

## Rules

- **Reproduce first.** Understand the root cause before writing any fix. A fix without understanding risks introducing new bugs.
- **Test the bug.** Write a test that fails before the fix and passes after. This prevents regressions.
- **Tests must pass.** Do not mark a bug as complete if tests are failing.
- **One bug at a time.** Focus on a single bug per invocation unless the user asks to batch related bugs.
- **Don't break other things.** Run the full relevant test suite, not just new tests.
- **Minimal scope.** Fix the described bug without refactoring unrelated code. If you discover tech debt or other bugs while working, log them to the appropriate ClickUp list (TECH_DEBT: `901712289455`, BUGS: `901712289456`) instead of fixing in the same pass.
- **Document in ClickUp.** The fix comment is mandatory — it creates an audit trail for what was changed and why. Future developers should be able to read the comment and understand the fix without reading the code diff.
- **User confirms completion.** Never mark a task as complete in ClickUp without explicit user confirmation. After implementing the fix, present results and ask the user to verify. If they request changes, iterate until they are satisfied. Only then document and close in ClickUp.
- **Update ClickUp last.** Only mark complete and add the fix comment after tests pass AND the user has explicitly confirmed.

## Bug Selection Display

When no specific bug is provided, show the user a table like:

```
Open Bugs (12 total):
  Urgent (2):  BUG-0001, BUG-0005
  High (4):    BUG-0002, BUG-0003, BUG-0008, BUG-0010
  Normal (5):  BUG-0004, BUG-0006, BUG-0007, BUG-0009, BUG-0011
  Low (1):     BUG-0012

Suggested next: BUG-0001 (Urgent) — highest severity

Which bug would you like to fix? (e.g., BUG-0003 or "next urgent")
```

When suggesting, prefer bugs at the **highest priority** — severity drives order for bugs.

## Handling Complex Bugs

For bugs that require extensive investigation or multi-file changes:
- Break the fix into steps and discuss the plan with the user
- Update the ClickUp task status to `in progress` and add a comment with investigation findings
- Only mark `complete` when the fix is verified and documented

## Handling Non-Reproducible Bugs

If a bug can't be reproduced:
- Add a comment to the ClickUp task explaining the investigation and findings
- Note what was checked and why it couldn't be reproduced
- Ask the user whether to close or keep open for monitoring
