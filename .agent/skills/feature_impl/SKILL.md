---
name: feature_impl
description: Pick up and implement features from the ClickUp FEATURES list. Use when the user asks to "implement a feature", "build F-XXXX", "work on a feature", "pick up a feature", or runs /feature_impl. Optionally pass a specific feature ID (e.g., /feature_impl F-0008) or priority level (e.g., /feature_impl P1).
---

# Implement Feature

Implement features from the **ClickUp FEATURES list** (list ID: `901712289454`), verify with tests, and mark them complete in ClickUp.

## Process

1. **Fetch tasks from ClickUp** using `clickup_filter_tasks` on list `901712289454` to get the feature list and statuses.
2. **Select feature to implement**:
   - If the user specified a feature ID (e.g., `F-0008`), search for that task in ClickUp.
   - If the user specified a priority (e.g., `P1`, `high`), filter for high-priority tasks with open status.
   - If no argument given, show the user a summary of open features grouped by priority and ask which to implement.
3. **Research the feature** — read the task description in ClickUp and the source files mentioned. Understand the existing code, affected components, and any dependencies before writing code.
4. **Create and present a plan** before writing any code:
   - List every file that will be created or modified
   - Describe the specific changes for each file
   - Map each change to the acceptance criteria it satisfies
   - Note any risks, trade-offs, or open questions
   - Estimate if this can be done in one session or needs to be broken into phases
   - **Present the plan to the user and wait for approval.** Do NOT proceed until the user confirms.
   - If the user requests changes to the plan, revise and re-present.
5. **Write failing tests first (Red phase)** — TDD Red-Green-Refactor:
   - Translate each acceptance criterion into one or more concrete test cases
   - Backend: create test files in `backend/tests/` (unit or integration as appropriate)
   - Frontend — choose the right tier based on what you're testing:
     - **Vitest** (`frontend/src/**/*.test.ts`): For utilities, validation logic, API client, pure functions, and simple components that work in jsdom. Do NOT use for `@xyflow/svelte` graph components or anything requiring real layout/rendering. Write these by default for any testable logic.
     - **Playwright E2E** (`frontend/e2e/`): For user workflow tests, graph editor interactions, and any feature that needs a real browser. Requires dev servers running. **Before writing Playwright tests, ask the user if they want them for this feature.** E2E tests are token-intensive to develop and may not be worth it for every feature. Present which workflows you'd test and let the user decide.
     - At minimum, verify `npm run check` passes with any new types/interfaces.
   - Run the tests to confirm they **fail** for the right reasons (missing endpoint, missing component, unimplemented logic). This validates the tests are meaningful.
   - If a test passes before implementation, it's not testing the new feature — revisit it.
6. **Implement the feature (Green phase)** following project conventions (see CLAUDE.md):
   - Work through the plan file by file, writing the minimum code to make each failing test pass
   - For backend changes: follow FastAPI async patterns, add Pydantic schemas, create Alembic migrations if needed
   - For frontend changes: use Svelte 5 runes, shadcn-svelte components, TailwindCSS
   - For full-stack changes: implement backend first, then frontend
   - Re-run tests after each major piece of implementation to track progress
7. **Refactor if needed (Refactor phase)**:
   - Once all tests pass, review the implementation for duplication, unclear naming, or unnecessary complexity
   - Clean up without changing behavior — tests must still pass after refactoring
   - Keep refactoring minimal and scoped to the new feature code
8. **Run full test suite** to confirm nothing is broken:
   - Backend: `cd backend && source .venv/bin/activate && pytest tests/ -x -q`
   - Frontend: `cd frontend && npm run check && npm run test`
   - Playwright E2E (if you wrote E2E tests): `cd frontend && npm run test:e2e`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
9. **Browser verification (if frontend was changed)** — if any frontend component was added or modified, open the app in a Chrome browser using the `mcp__claude-in-chrome__*` tools and visually verify the changes behave as expected:
   - Navigate to the relevant page(s) affected by the change
   - Interact with the new/updated UI elements (click buttons, fill forms, check layout)
   - Verify the feature works end-to-end from a user's perspective
   - Check for visual regressions (misaligned elements, missing styles, broken responsiveness)
   - If anything looks wrong, fix it and re-run tests before proceeding
   - **"Leave site?" dialog workaround**: If navigation is blocked by a "Leave site?" dialog (e.g., unsaved changes on a page), open a **new tab** instead and navigate to the login screen from there.
   - **Authentication for testing**: To log in during browser verification, check the PostgreSQL dev database for user emails and roles (see `/local_dev` skill for credentials: `localhost:5432`, user `postgres`, password `postgres`, database `runbook`). Any password will work in the dev environment. Test with different user roles as needed to verify the feature across permission levels.
   - **Clean up test data**: If you created or modified any resources during browser verification (e.g., created sessions, projects, documents, or changed settings), you MUST revert them afterward. Delete created records or restore modified ones to their previous state using `psql` (`psql -h localhost -U postgres -d runbook`) or whatever method is easiest. Do not leave test artifacts in the database.
10. **Present results and request user verification** — print a summary of what was implemented, which acceptance criteria were met, and what tests were run. Then **ask the user to verify the implementation** and confirm they are satisfied.
    - **Do NOT mark the ClickUp task as complete until the user explicitly confirms.**
    - If the user requests changes:
      1. Discuss and plan the requested changes (present a revised plan, wait for approval)
      2. Implement the changes
      3. Re-run tests and browser verification as needed
      4. Present the updated results and ask the user to verify again
    - **Repeat this loop until the user explicitly says the task is complete / they are satisfied.**
11. **Update ClickUp task** — only after user confirmation:
    - Use `clickup_update_task` to set the task status to `complete`
    - Add a comment via `clickup_create_task_comment` summarizing what was implemented and which tests were added

## Rules

- **Tests first (TDD).** Always write failing tests before implementation. This is non-negotiable — it ensures acceptance criteria are concrete and testable before any code is written.
- **Tests must pass.** Do not mark a feature as complete if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One feature at a time.** Focus on a single feature per invocation unless the user asks to batch related features.
- **Don't break other things.** Run the full relevant test suite, not just new tests. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Follow the spec.** Implement what the acceptance criteria describe. If the spec is wrong or incomplete, flag it to the user before diverging.
- **Minimal scope.** Implement the specified feature without refactoring unrelated code. If you discover tangential tech debt while working, don't fix it in the same pass — but don't forget it either. Check the ClickUp TECH_DEBT list (list ID: `901712289455`) to see if the item is already tracked. If it isn't, create a new task in that list so it doesn't get lost.
- **User confirms completion.** Never mark a task as complete in ClickUp without explicit user confirmation. After implementation, present results and ask the user to verify. If they request changes, iterate until they are satisfied. Only then update ClickUp.
- **Update ClickUp last.** Only mark complete after tests pass AND the user has explicitly confirmed. ClickUp is the source of truth for feature status.
- **Check dependencies first.** If the feature has dependencies on other F-XXXX items, verify those are complete in ClickUp before starting.

## Feature Selection Display

When no specific feature is provided, show the user a table like:

```
Open Features (8 total):
  Urgent (0): —
  High (2):   F-0002, F-0008
  Normal (4): F-0001, F-0003, F-0005, F-0007
  Low (2):    F-0004, F-0006

Suggested next: F-0008 (High, Frontend) — Mobile-Friendly Responsive Design

Which feature would you like to implement? (e.g., F-0008 or "next high")
```

When suggesting, prefer features at the **highest priority** that have **no unmet dependencies**.

## Handling Large Features

For features that can't be completed in one session:
- Break the feature into phases and discuss the plan with the user
- Complete one phase at a time
- Update the ClickUp task status to `in progress` and add a comment noting which acceptance criteria are done
- Only mark `complete` when ALL acceptance criteria are met

## Handling Blocked Features

If a feature can't be implemented (e.g., missing dependency, needs product decision, spec is unclear):
- Update the ClickUp task with a comment explaining the blocker
- Inform the user and suggest next steps

## Handling Partial Implementation

If some acceptance criteria are met but others can't be completed:
- Update the ClickUp task status to `in progress`
- Add a comment listing what's done and what remains
- Inform the user
