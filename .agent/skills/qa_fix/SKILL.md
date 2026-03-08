---
name: qa_fix
description: Pick up and fix QA issues from QA_SURVEY.md. Use when the user asks to "fix a QA issue", "work on QA items", "tackle QA bugs", "fix QA-XXXX", or runs /qa_fix. Optionally pass a specific issue ID (e.g., /qa_fix QA-0003) or priority level (e.g., /qa_fix critical).
---

# QA Issue Fix

Fix issues documented in `QA_SURVEY.md`, verify with tests, and mark them resolved.

## Process

1. **Read `QA_SURVEY.md`** to get the full issue list and current status.
2. **Select issue(s) to fix**:
   - If the user specified an issue ID (e.g., `QA-0003`), fix that one.
   - If the user specified a priority (e.g., `critical`, `high`), pick the highest-priority unfixed issue.
   - If no argument given, show the user a summary of open issues grouped by severity and ask which to tackle.
3. **Research the issue** — read the relevant source files mentioned in the issue's Recommendation and Steps to Reproduce. Understand the root cause before writing code.
4. **Implement the fix** following project conventions (see CLAUDE.md).
5. **Write or update tests** to cover the fix:
   - Backend fixes: add/update tests in `backend/tests/` (unit or integration as appropriate)
   - Frontend fixes: verify the fix doesn't break `npm run check` from `frontend/`
   - The fix is NOT complete until tests pass.
6. **Run tests** to confirm:
   - Backend: `cd backend && source .venv/bin/activate && pytest tests/ -x -q` (or a targeted test file)
   - Frontend: `cd frontend && npm run check`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
7. **Update `QA_SURVEY.md`** — mark the issue as resolved:
   - Change the severity line to include `[FIXED]`: e.g., `- **Severity**: High → **FIXED**`
   - Add a `- **Resolution**:` line describing what was changed and the commit SHA (if committed)
   - Update the Summary table counts (decrement the severity column, increment a "Fixed" column if present)
8. **Print a summary** of what was fixed and what tests were run.

## Rules

- **Tests must pass.** Do not mark an issue as fixed if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One issue at a time.** Focus on a single QA issue per invocation unless the user asks to batch-fix related issues.
- **Don't break other things.** Run the full relevant test suite, not just the new test. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Minimal changes.** Fix the reported issue without refactoring unrelated code. Follow the project's "avoid over-engineering" principle.
- **Update QA_SURVEY.md last.** Only mark resolved after tests pass. This is the source of truth for QA status.

## Issue Selection Display

When no specific issue is provided, show the user a table like:

```
Open QA Issues:
  Critical (2): QA-0001, QA-0002
  High (3):     QA-0003, QA-0004, QA-0005
  Medium (5):   QA-0006, QA-0007, QA-0008, QA-0009, QA-0010
  Low (3):      QA-0011, QA-0012, QA-0013

Which issue would you like to fix? (e.g., QA-0001 or "next critical")
```

## QA_SURVEY.md Update Format

When marking an issue as fixed, transform the severity line and add a resolution:

**Before:**
```markdown
### [QA-0003] Settings Organization tab shows "No members found" for non-admin users
- **Severity**: High
- **Category**: Functionality
```

**After:**
```markdown
### [QA-0003] Settings Organization tab shows "No members found" for non-admin users
- **Severity**: ~~High~~ **FIXED**
- **Category**: Functionality
...
- **Resolution**: Granted read access to member list for all org members. Added test in `test_iam_api.py`. (commit abc1234)
```

## Handling Unfixable Issues

If an issue cannot be fixed (e.g., requires infrastructure changes, needs product decision):
- Mark it as `**DEFERRED**` instead of `**FIXED**`
- Add a `- **Reason**:` line explaining why
- Inform the user and suggest next steps
