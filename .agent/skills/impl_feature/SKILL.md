---
name: impl_feature
description: Pick up and implement features from the FEATURES.md backlog. Use when the user asks to "implement a feature", "build F-XXXX", "work on a feature", "pick up a feature", or runs /impl_feature. Optionally pass a specific feature ID (e.g., /impl_feature F-0008) or priority level (e.g., /impl_feature P1).
---

# Implement Feature

Implement features from the `FEATURES.md` backlog, verify with tests, check off acceptance criteria, and mark them complete.

## Process

1. **Read `FEATURES.md`** to get the full feature list and current statuses.
2. **Select feature to implement**:
   - If the user specified a feature ID (e.g., `F-0008`), implement that one.
   - If the user specified a priority (e.g., `P1`, `critical`), pick the highest-priority feature with status `Proposed` or `Approved`.
   - If no argument given, show the user a summary of open features grouped by priority and ask which to implement.
3. **Research the feature** — read the source files mentioned in the Implementation Notes. Understand the existing code, affected components, and any dependencies before writing code.
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
   - Frontend: if the feature adds new logic or components, write tests or at minimum verify `npm run check` passes with any new types/interfaces
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
   - Frontend: `cd frontend && npm run check`
   - If tests fail, fix the issue and re-run. Do not skip failing tests.
9. **Update `FEATURES.md`** — check off completed acceptance criteria and update status:
   - Change `- **Status**: Proposed` to `- **Status**: Done`
   - Check off each completed acceptance criterion: `- [ ]` to `- [x]`
   - Add a `- **Resolution**:` line summarizing what was implemented
10. **Print a summary** of what was implemented, which acceptance criteria were met, and what tests were run.

## Rules

- **Tests first (TDD).** Always write failing tests before implementation. This is non-negotiable — it ensures acceptance criteria are concrete and testable before any code is written.
- **Tests must pass.** Do not mark a feature as Done if tests are failing. If an existing test breaks due to your change, fix the test or the implementation.
- **One feature at a time.** Focus on a single feature per invocation unless the user asks to batch related features.
- **Don't break other things.** Run the full relevant test suite, not just new tests. If you changed backend code, run `pytest`. If you changed frontend code, run `npm run check`.
- **Follow the spec.** Implement what the acceptance criteria describe. If the spec is wrong or incomplete, flag it to the user before diverging.
- **Minimal scope.** Implement the specified feature without refactoring unrelated code. If you discover tech debt while working, note it but don't fix it in the same pass.
- **Update FEATURES.md last.** Only mark Done after tests pass. This is the source of truth for feature status.
- **Check dependencies first.** If the feature has dependencies on other F-XXXX items, verify those are Done before starting.

## Feature Selection Display

When no specific feature is provided, show the user a table like:

```
Open Features (8 total):
  P0 Critical (0): —
  P1 High (2):     F-0002, F-0008
  P2 Medium (4):   F-0001, F-0003, F-0005, F-0007
  P3 Low (2):      F-0004, F-0006

Suggested next: F-0008 (P1, Frontend) — Mobile-Friendly Responsive Design

Which feature would you like to implement? (e.g., F-0008 or "next P1")
```

When suggesting, prefer features at the **highest priority** that have **no unmet dependencies**.

## FEATURES.md Update Format

When marking a feature as done, update the status, check off criteria, and add a resolution:

**Before:**
```markdown
### [F-0008] Mobile-Friendly Responsive Design
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Frontend
- **Acceptance Criteria**:
  - [ ] Navigation bar collapses to a hamburger menu on screens <768px
  - [ ] All data tables switch to card-based layout on screens <640px
```

**After:**
```markdown
### [F-0008] Mobile-Friendly Responsive Design
- **Status**: Done
- **Priority**: P1 (High)
- **Scope**: Frontend
- **Acceptance Criteria**:
  - [x] Navigation bar collapses to a hamburger menu on screens <768px
  - [x] All data tables switch to card-based layout on screens <640px
- **Resolution**: Added responsive nav with hamburger menu via shadcn Sheet component. Created ResponsiveTable.svelte for card-based mobile layouts. Verified with `npm run check`.
```

## Handling Large Features

For features that can't be completed in one session:
- Break the feature into phases and discuss the plan with the user
- Complete one phase at a time
- Change status to `In Progress` and note which acceptance criteria are done
- Check off completed criteria as you go
- Only change to `Done` when ALL acceptance criteria are met

## Handling Blocked Features

If a feature can't be implemented (e.g., missing dependency, needs product decision, spec is unclear):
- Change status to `Blocked` instead of `Done`
- Add a `- **Blocked By**:` line explaining what's preventing implementation
- Inform the user and suggest next steps

## Handling Partial Implementation

If some acceptance criteria are met but others can't be completed:
- Change status to `In Progress`
- Check off the completed criteria
- Add a `- **Remaining**:` line listing what's left and why
- Inform the user
