---
name: qa_fix
description: Pick up and fix QA issues from the ClickUp QA list. Use when the user asks to "fix a QA issue", "work on QA items", "tackle QA bugs", "fix QA-XXXX", or runs /qa_fix. Optionally pass a specific issue ID (e.g., /qa_fix QA-0003) or priority level (e.g., /qa_fix critical).
---

# QA Issue Fix

Fix QA issues from the **ClickUp QA list** (list ID: `901712290772`), verify with tests, and document the fix in the ClickUp task.

## Process

1. **Fetch tasks from ClickUp** using `clickup_filter_tasks` on list `901712290772` to get the issue list and statuses.
2. **Select issue(s) to fix**:
   - If the user specified an issue ID (e.g., `QA-0003`), search for that task in ClickUp.
   - If the user specified a priority (e.g., `critical`, `high`), filter for the matching priority with open status.
   - If no argument given, show the user a summary of open issues grouped by priority and ask which to tackle.
3. **Research the issue** — read the task description in ClickUp and the relevant source files mentioned in the Recommendation and Steps to Reproduce. Understand the root cause before writing code.
4. **Implement the fix** following project conventions (see CLAUDE.md).
5. **Write or update tests** to cover the fix:
   - Backend fixes: add/update tests in `backend/tests/` (unit or integration as appropriate)
   - Frontend fixes: verify the fix doesn't break `npm run check` from `frontend/`
   - The fix is NOT complete until tests pass.
6. **Run tests** to confirm:
   - Backend: `cd backend && source .venv/bin/activate && pytest tests/ -x -q` (or a targeted test file)
   - Frontend: `cd frontend && npm run check`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
7. **Browser verification (if frontend was changed)** — if any frontend component was added or modified, open the app in a Chrome browser using the `mcp__claude-in-chrome__*` tools and visually verify the fix behaves as expected:
   - Navigate to the relevant page(s) affected by the fix
   - Reproduce the original QA issue scenario — it should no longer occur
   - Interact with the fixed UI elements to confirm correct behavior
   - Check for visual regressions (misaligned elements, missing styles, broken responsiveness)
   - If anything looks wrong, fix it and re-run tests before proceeding
   - **"Leave site?" dialog workaround**: If navigation is blocked by a "Leave site?" dialog (e.g., unsaved changes on a page), open a **new tab** instead and navigate to the login screen from there.
   - **Authentication for testing**: To log in during browser verification, check the PostgreSQL dev database for user emails and roles (see `/local_dev` skill for credentials: `localhost:5432`, user `postgres`, password `postgres`, database `batchrite`). Any password will work in the dev environment. Test with different user roles as needed to verify the fix across permission levels.
   - **Clean up test data**: If you created or modified any resources during browser verification (e.g., created sessions, projects, documents, or changed settings), you MUST revert them afterward. Delete created records or restore modified ones to their previous state using `psql` (`psql -h localhost -U postgres -d batchrite`) or whatever method is easiest. Do not leave test artifacts in the database.
8. **Present results and request user verification** — print a summary of what was fixed and what tests were run. Then **ask the user to verify the fix** and confirm they are satisfied.
   - **Do NOT mark the ClickUp task as complete or document the fix until the user explicitly confirms.**
   - If the user requests changes:
     1. Discuss and plan the requested changes
     2. Implement the changes
     3. Re-run tests and browser verification as needed
     4. Present the updated results and ask the user to verify again
   - **Repeat this loop until the user explicitly says the fix is complete / they are satisfied.**
9. **Document the fix in ClickUp** — only after user confirmation:
   - Use `clickup_create_task_comment` to add a fix summary comment:
     ```
     ## Fix Summary

     **Root Cause**: [What was actually causing the issue]

     **Changes Made**:
     - `file/path.ts:line` — [what was changed and why]
     - `file/path.py:line` — [what was changed and why]

     **Tests Added/Updated**:
     - `tests/unit/test_xxx.py::test_name` — [what the test verifies]

     **Verification**: All tests passing.
     ```
   - Use `clickup_update_task` to set the task status to `complete`

## Rules

- **Tests must pass.** Do not mark an issue as complete if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One issue at a time.** Focus on a single QA issue per invocation unless the user asks to batch-fix related issues.
- **Don't break other things.** Run the full relevant test suite, not just the new test. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Minimal changes.** Fix the reported issue without refactoring unrelated code. Follow the project's "avoid over-engineering" principle.
- **Schema naming convention (backend).** Pydantic classes with a `Response` suffix (e.g., `ProjectResponse`) must only be used as API response models (`response_model=` in endpoints). Never use a `*Response` class as an internal/service-layer object or DB-adjacent model. If a schema is shared between the object model and the API response, use a plain name without the `Response` suffix and return it directly — don't create a redundant `*Response` wrapper.
- **User confirms completion.** Never mark a task as complete in ClickUp without explicit user confirmation. After implementing the fix, present results and ask the user to verify. If they request changes, iterate until they are satisfied. Only then document and close in ClickUp.
- **Document in ClickUp.** The fix comment is mandatory — it creates an audit trail. Update ClickUp only after tests pass AND the user has explicitly confirmed.

## Issue Selection Display

When no specific issue is provided, show the user a table like:

```
Open QA Issues:
  Urgent (2):  QA-0001, QA-0002
  High (3):    QA-0003, QA-0004, QA-0005
  Normal (5):  QA-0006, QA-0007, QA-0008, QA-0009, QA-0010
  Low (3):     QA-0011, QA-0012, QA-0013

Which issue would you like to fix? (e.g., QA-0001 or "next urgent")
```

## Handling Unfixable Issues

If an issue cannot be fixed (e.g., requires infrastructure changes, needs product decision):
- Add a comment to the ClickUp task explaining why and suggesting next steps
- Inform the user
