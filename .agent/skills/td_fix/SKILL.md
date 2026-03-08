---
name: td_fix
description: Pick up and resolve technical debt items from TECH_DEBT.md. Use when the user asks to "fix tech debt", "tackle TD items", "resolve TD-XXXX", "work on tech debt", or runs /td_fix. Optionally pass a specific item ID (e.g., /td_fix TD-0012) or priority level (e.g., /td_fix critical).
---

# Tech Debt Fix

Resolve technical debt items documented in `TECH_DEBT.md`, verify with tests, and mark them complete.

## Process

1. **Read `TECH_DEBT.md`** to get the full item list and current status.
2. **Select item(s) to fix**:
   - If the user specified an item ID (e.g., `TD-0012`), fix that one.
   - If the user specified a severity (e.g., `critical`, `high`), pick the highest-severity open item with the smallest effort.
   - If no argument given, show the user a summary of open items grouped by severity and ask which to tackle.
3. **Research the item** — read the source files in the `Location` field. Understand the full scope of the debt before making changes.
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
8. **Update `TECH_DEBT.md`** — mark the item as resolved:
   - Change the severity line to include `[RESOLVED]`: e.g., `- **Severity**: ~~High~~ **RESOLVED**`
   - Add a `- **Resolution**:` line describing what was changed
   - Update the Summary table counts if feasible
9. **Print a summary** of what was resolved and what tests were run.

## Rules

- **Tests must pass.** Do not mark an item as resolved if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One item at a time.** Focus on a single TD item per invocation unless the user asks to batch related items.
- **Don't break other things.** Run the full relevant test suite, not just new tests. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Behavior preservation.** For refactors and code smell fixes, the app must behave identically before and after. No sneaking in feature changes.
- **Minimal scope.** Fix the described debt without refactoring unrelated code. If you discover new debt while working, note it but don't fix it in the same pass.
- **Update TECH_DEBT.md last.** Only mark resolved after tests pass. This is the source of truth.

## Item Selection Display

When no specific item is provided, show the user a table like:

```
Open Tech Debt Items (46 total):
  Critical (13): TD-0001, TD-0002, TD-0003, TD-0004, TD-0017, ...
  High (17):     TD-0005, TD-0006, TD-0007, TD-0008, ...
  Medium (14):   TD-0010, TD-0014, TD-0015, ...
  Low (2):       TD-0030, TD-0031

Suggested next: TD-0023 (High, Effort: S) — quickest high-severity win

Which item would you like to tackle? (e.g., TD-0012 or "next high")
```

When suggesting, prefer items with **smaller effort** at the **highest open severity** — quick wins first.

## TECH_DEBT.md Update Format

When marking an item as resolved, transform the severity line and add a resolution:

**Before:**
```markdown
### [TD-0012] Empty catch blocks in frontend settings page
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `frontend/src/routes/settings/+page.svelte:335,349,362`
- **Description**: Three async functions silently swallow errors with empty catch blocks.
- **Suggested Fix**: Add error state variables and display error messages to the user.
- **Effort**: S
```

**After:**
```markdown
### [TD-0012] Empty catch blocks in frontend settings page
- **Category**: Missing Implementation
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/routes/settings/+page.svelte:335,349,362`
- **Description**: Three async functions silently swallow errors with empty catch blocks.
- **Suggested Fix**: Add error state variables and display error messages to the user.
- **Effort**: S
- **Resolution**: Added `membersError` and `teamsError` state variables. Catch blocks now capture and display error messages. Verified with `npm run check`.
```

## Handling Large Items (XL effort)

For XL-effort items that can't be completed in one session:
- Break the item into sub-tasks and discuss the plan with the user
- Complete one sub-task at a time
- Mark the item as `**IN PROGRESS**` with a note on what's done and what remains
- Only mark `**RESOLVED**` when all sub-tasks are complete

## Handling Items That Shouldn't Be Fixed

If an item is no longer relevant or the suggested fix is wrong:
- Mark it as `**WONTFIX**` instead of `**RESOLVED**`
- Add a `- **Reason**:` line explaining why
- Inform the user
