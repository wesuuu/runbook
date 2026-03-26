---
name: td_fix
description: Pick up and resolve technical debt items from the ClickUp TECH_DEBT list. Use when the user asks to "fix tech debt", "tackle TD items", "resolve TD-XXXX", "work on tech debt", or runs /td_fix. Optionally pass a specific item ID (e.g., /td_fix TD-0012) or priority level (e.g., /td_fix critical).
---

# Tech Debt Fix

Resolve technical debt items from the **ClickUp TECH_DEBT list** (list ID: `901712289455`), verify with tests, and mark them complete in ClickUp.

## Process

1. **Fetch tasks from ClickUp** using `clickup_filter_tasks` on list `901712289455` to get the item list and statuses.
2. **Select item(s) to fix**:
   - If the user specified an item ID (e.g., `TD-0012`), search for that task in ClickUp.
   - If the user specified a severity (e.g., `critical`, `high`), filter for the matching priority with open status.
   - If no argument given, show the user a summary of open items grouped by priority and ask which to tackle.
3. **Research the item** — read the task description in ClickUp and the source files in the Location field. Understand the full scope of the debt before making changes.
4. **Create and present a plan** before writing any code:
   - List the files that will be modified or created
   - Describe the specific changes for each file
   - Note any risks or trade-offs (e.g., breaking changes, migration needed)
   - Estimate if this is straightforward or has hidden complexity
   - **Present the plan to the user and wait for approval.** Do NOT proceed until the user confirms.
   - If the user requests changes to the plan, revise and re-present.
5. **Implement the fix** following project conventions (see CLAUDE.md):
   - For refactors: ensure behavior is preserved. Don't change functionality while refactoring.
   - For missing tests: write tests that cover the described gap.
   - For type safety: add types without changing runtime behavior.
   - For security fixes: fix the vulnerability and add a test proving it's resolved.
6. **Write or update tests** to cover the change:
   - Backend changes: add/update tests in `backend/tests/` (unit or integration as appropriate)
   - Frontend changes: verify the fix doesn't break `npm run check` from `frontend/`
   - The item is NOT complete until tests pass.
7. **Run tests** to confirm:
   - Backend: `cd backend && source .venv/bin/activate && pytest tests/ -x -q` (or a targeted test file)
   - Frontend: `cd frontend && npm run check`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
8. **Browser verification (if frontend was changed)** — if any frontend component was added or modified, open the app in a Chrome browser using the `mcp__claude-in-chrome__*` tools and visually verify the changes behave as expected:
   - Navigate to the relevant page(s) affected by the change
   - Interact with the new/updated UI elements (click buttons, fill forms, check layout)
   - Verify the change works correctly from a user's perspective
   - Check for visual regressions (misaligned elements, missing styles, broken responsiveness)
   - If anything looks wrong, fix it and re-run tests before proceeding
   - **"Leave site?" dialog workaround**: If navigation is blocked by a "Leave site?" dialog (e.g., unsaved changes on a page), open a **new tab** instead and navigate to the login screen from there.
   - **Authentication for testing**: To log in during browser verification, check the PostgreSQL dev database for user emails and roles (see `/local_dev` skill for credentials: `localhost:5432`, user `postgres`, password `postgres`, database `runbook`). Any password will work in the dev environment. Test with different user roles as needed to verify the change across permission levels.
   - **Clean up test data**: If you created or modified any resources during browser verification (e.g., created sessions, projects, documents, or changed settings), you MUST revert them afterward. Delete created records or restore modified ones to their previous state using `psql` (`psql -h localhost -U postgres -d runbook`) or whatever method is easiest. Do not leave test artifacts in the database.
9. **Present results and request user verification** — print a summary of what was resolved and what tests were run. Then **ask the user to verify the fix** and confirm they are satisfied.
   - **Do NOT mark the ClickUp task as complete until the user explicitly confirms.**
   - If the user requests changes:
     1. Discuss and plan the requested changes (present a revised plan, wait for approval)
     2. Implement the changes
     3. Re-run tests and browser verification as needed
     4. Present the updated results and ask the user to verify again
   - **Repeat this loop until the user explicitly says the task is complete / they are satisfied.**
10. **Update ClickUp task** — only after user confirmation:
    - Use `clickup_update_task` to set the task status to `complete`
    - Add a comment via `clickup_create_task_comment` summarizing what was changed and which tests were added/updated

## Rules

- **Tests must pass.** Do not mark an item as complete if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One item at a time.** Focus on a single TD item per invocation unless the user asks to batch related items.
- **Don't break other things.** Run the full relevant test suite, not just new tests. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Behavior preservation.** For refactors and code smell fixes, the app must behave identically before and after. No sneaking in feature changes.
- **Minimal scope.** Fix the described debt without refactoring unrelated code. If you discover new debt while working, note it but don't fix it in the same pass.
- **User confirms completion.** Never mark a task as complete in ClickUp without explicit user confirmation. After implementation, present results and ask the user to verify. If they request changes, iterate until they are satisfied. Only then update ClickUp.
- **Update ClickUp last.** Only mark complete after tests pass AND the user has explicitly confirmed. ClickUp is the source of truth.

## Item Selection Display

When no specific item is provided, show the user a table like:

```
Open Tech Debt Items (26 total):
  Urgent (4):  TD-0029, TD-0030, TD-0037, TD-0038
  High (9):    TD-0006, TD-0007, TD-0008, TD-0022, ...
  Normal (13): TD-0010, TD-0011, TD-0012, ...
  Low (0):     —

Suggested next: TD-0030 (Urgent, Effort: M) — quickest high-severity win

Which item would you like to tackle? (e.g., TD-0012 or "next urgent")
```

When suggesting, prefer items with **smaller effort** at the **highest open priority** — quick wins first.

## Handling Large Items (XL effort)

For XL-effort items that can't be completed in one session:
- Break the item into sub-tasks and discuss the plan with the user
- Complete one sub-task at a time
- Update the ClickUp task status to `in progress` and add a comment on what's done and what remains
- Only mark `complete` when all sub-tasks are finished

## Handling Items That Shouldn't Be Fixed

If an item is no longer relevant or the suggested fix is wrong:
- Add a comment to the ClickUp task explaining why
- Update the task status to `complete` (or close it)
- Inform the user
