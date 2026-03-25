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
8. **Document the fix in ClickUp** — this is critical for traceability:
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
9. **Print a summary** of what was fixed, what the root cause was, and what tests were added.

## Rules

- **Reproduce first.** Understand the root cause before writing any fix. A fix without understanding risks introducing new bugs.
- **Test the bug.** Write a test that fails before the fix and passes after. This prevents regressions.
- **Tests must pass.** Do not mark a bug as complete if tests are failing.
- **One bug at a time.** Focus on a single bug per invocation unless the user asks to batch related bugs.
- **Don't break other things.** Run the full relevant test suite, not just new tests.
- **Minimal scope.** Fix the described bug without refactoring unrelated code. If you discover tech debt or other bugs while working, log them to the appropriate ClickUp list (TECH_DEBT: `901712289455`, BUGS: `901712289456`) instead of fixing in the same pass.
- **Document in ClickUp.** The fix comment is mandatory — it creates an audit trail for what was changed and why. Future developers should be able to read the comment and understand the fix without reading the code diff.
- **Update ClickUp last.** Only mark complete and add the fix comment after tests pass.

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
