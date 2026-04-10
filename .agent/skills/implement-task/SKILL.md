---
name: implement-task
description: Use when the user wants to implement, work on, pick up, or fix a ClickUp task. Triggers on "implement", "work on", "pick up", "fix", "build" followed by a task reference, or /implement_task.
---

# Implement Task

Pick up a ClickUp task, design the approach, implement with TDD, and close it out.

**REQUIRED SUB-SKILL:** `superpowers:brainstorming` — invoked before any code is written.
**REQUIRED SUB-SKILL:** `superpowers:writing-plans` — invoked after brainstorming converges.

## When to Use

- User provides a ClickUp task ID and wants it implemented
- User says "pick up", "work on", "fix", "build" referencing a tracked task

**Don't use when:** User wants to create a new task (use `/add_task`), update an existing task without implementation (use `/task_update`), or ship already-written code (use `/ship`).

## Process

### 1. Fetch and claim

`clickup_get_task` with the provided ID. Read description, acceptance criteria, priority, linked tasks. If no ID given, ask. Immediately `clickup_update_task` to set status `in progress`.

### 2. Brainstorm and plan

Invoke `superpowers:brainstorming` with the task description and codebase context. After the approach converges, invoke `superpowers:writing-plans` for a concrete plan. **Wait for user approval before proceeding.**

### 3. Implement

Follow the approved plan with TDD (Red-Green-Refactor). Run the full test suite after implementation (see CLAUDE.md for commands).

### 4. Browser verification (if frontend changed)

Open the app in Chrome via `mcp__claude-in-chrome__*` tools:
- Test happy path and edge cases on affected pages
- For bugs: confirm the original scenario is fixed
- Check for visual regressions

Dev DB credentials: `localhost:5432`, user `postgres`, password `postgres`, database `batchrite`. Any password works in dev. Clean up test data via `psql` after verification.

### 5. User verification

Present summary: what was done, acceptance criteria met, tests added. **Ask user to verify.** Iterate until they confirm.

### 6. Close the task

Only after explicit user confirmation:

1. `clickup_create_task_comment` with summary of changes, files modified, and tests added
2. `clickup_update_task` to set status `complete`

## Common Mistakes

- **Skipping brainstorming**: Jumping straight to code without exploring the design space. The brainstorming step prevents rework.
- **Not claiming the task first**: Forgetting to move to "in progress" before starting work. Another agent or developer might pick it up.
- **Scope creep**: Fixing unrelated issues discovered during implementation. Log them via `/add_task` instead.
- **Closing without user sign-off**: Marking complete because tests pass. Tests verify correctness, not completeness -- the user decides when it's done.
- **Skipping browser verification**: Tests pass but the UI is broken. If frontend code changed, verify in the browser.

## Rules

- **User confirms completion.** Never mark complete without explicit sign-off.
- **Tests must pass.** Do not close a task with failing tests.
- **Minimal scope.** Implement what the task describes. Unrelated issues go to `/add_task`.
- **One task at a time.** Focus on the single task unless told otherwise.
