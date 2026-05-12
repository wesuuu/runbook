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

**Rename the session** with `/rename` to `<TASK-ID> <task title>` so it's easy to find and resume later. Example: `/rename TD-0067 Frontend component reuse audit`.

**Do NOT start a worktree yet.** Brainstorming and planning happen in the main workspace so the user can review specs and plans without worktree overhead. The worktree is created only after the plan is approved (step 3).

### 2. Brainstorm and plan

Invoke `superpowers:brainstorming` with the task description and codebase context. After the approach converges, invoke `superpowers:writing-plans` for a concrete plan. **Wait for user approval before proceeding.**

If the user rejects or substantially reshapes the plan, iterate here — do not create a worktree to "explore." The worktree is for implementing an approved plan, not for prototyping.

### 3. Start the worktree

**Only after the user has approved the plan**, start a worktree with `EnterWorktree`. All implementation work happens in the worktree — no feature branches, no PRs, no other git management. When work is done, commit and push directly from the worktree, then exit with `ExitWorktree`.

If the plan references new files or specification artifacts produced in step 2 that live outside the worktree, bring them in (re-save into the worktree path) before implementing.

### 4. Implement

Follow the approved plan with TDD (Red-Green-Refactor). Run the full test suite after implementation (see CLAUDE.md for commands).

### 5. Browser verification (if frontend changed)

Launch the **`qa-verify`** agent to handle browser verification. Pass it:
- How to login
- What feature was implemented and which pages are affected
- The task description / acceptance criteria
- Any edge cases worth testing

The qa-verify agent will test functional correctness AND audit UI/UX quality. It specifically catches layout issues like oversized elements (inputs/buttons stretching too wide), overflow, and spacing inconsistencies. **It must fix any FAIL or POLISH issues it finds before returning.**

Dev DB credentials: `localhost:5432`, user `postgres`, password `postgres`, database `batchrite`. Any password works in dev.

### 6. User verification

Present summary: what was done, acceptance criteria met, tests added. **Ask user to verify.** Iterate until they confirm. If the change(s) is larger than expected, consider invoking `superpowers:writing-plans` again to update the plan and get user approval on the new scope before proceeding.

### 7. Refresh project rules (final cleanup)

Before closing the task, sync `.claude/rules/*.md` and root `CLAUDE.md` with what actually changed. **Edit existing rules files in place — do not create new ones unless a genuinely new domain appeared.**

Decide what to touch:
- New convention, pattern, or constraint introduced → add a line to the most relevant existing rules file
- Old convention obsoleted, replaced, or removed → delete or rewrite the stale lines (do not leave both)
- New feature flag, env var, command, or service surface → update the matching section in `CLAUDE.md`
- File/directory renames or relocations referenced in rules → update the path
- Nothing relevant changed → skip this step entirely (do not pad these files)

**Prune stale content — this is required, not optional:**
Before adding anything, scan the touched files for entries that no longer reflect reality and remove them. Stale signals:
- Code paths, files, functions, or commands referenced in the doc that no longer exist (`grep` to confirm before deleting)
- Feature flags, env vars, or migrations that have been removed, fully rolled out, or made permanent
- "TODO", "WIP", "soon", "in progress" notes for work that has shipped or been abandoned
- Workarounds or caveats for bugs that have since been fixed
- Old conventions that the new change directly contradicts — delete the old line, do not leave both
- Dated language ("as of <date>", "recently…", "we now…") even when the underlying fact is still true — rewrite in timeless present

If the change you just made obsoletes a section, delete the section in the same edit. A doc that lies is worse than a doc that is missing.

**Succinctness rules — apply on every edit:**
- Prefer rewriting an existing line over appending a new one. Three near-duplicate bullets become one.
- Drop hedges, "note that", restated context, and any sentence that explains *what* the code does (the code does that). Keep only *why* / *when* / non-obvious constraints.
- If a section grows past ~20 lines, refactor: collapse bullets, remove examples that no longer earn their space, or split into a focused sub-file referenced from the parent.
- No "as of <date>", "recently added", "we now…" — write in timeless present.
- If the file ends up longer than before, ask yourself what you can cut to net out shorter or even.

After editing, re-read the touched files end-to-end and confirm they read tighter, not just larger. Commit these changes in the same worktree.

### 8. Close the task

Only after explicit user confirmation:

1. **Exit the worktree** with `ExitWorktree` action `keep` (preserves commits) or `remove` (discards; use only if work was abandoned)
2. `clickup_create_task_comment` with summary of changes, files modified, and tests added
3. `clickup_update_task` to set status `complete`

Commits from the worktree remain on the branch you exit from. If the worktree branch is not on main, those commits must be merged or rebased per your project's integration process (but this is outside the scope of implement-task—focus on the task itself).

## Common Mistakes

- **Skipping brainstorming**: Jumping straight to code without exploring the design space. The brainstorming step prevents rework.
- **Creating the worktree too early**: Starting a worktree before brainstorming/planning forces the user to review specs inside an isolated branch and wastes setup if the plan is rejected. Plan first, worktree after approval.
- **Not claiming the task first**: Forgetting to move to "in progress" before starting work. Another agent or developer might pick it up.
- **Scope creep**: Fixing unrelated issues discovered during implementation. Log them via `/add_task` instead.
- **Closing without user sign-off**: Marking complete because tests pass. Tests verify correctness, not completeness -- the user decides when it's done.
- **Skipping browser verification**: Tests pass but the UI is broken. If frontend code changed, verify in the browser.

## Rules

- **Plan before worktree.** Brainstorming and plan-writing happen in the main workspace. The worktree is created only after the user approves the plan.
- **Worktree-only implementation.** Once the plan is approved, all implementation work happens inside the worktree. Exit when done (keep or remove per CLAUDE.md).
- **No feature branches.** Do NOT create feature branches (git checkout -b, git branch, etc.). Work in the worktree instead.
- **No PRs.** Do NOT invoke `/ship`, create pull requests, or use any other PR-based workflow. Worktrees isolate your work; commit directly to main when complete.
- **User confirms completion.** Never mark complete without explicit sign-off.
- **Tests must pass.** Do not close a task with failing tests.
- **Minimal scope.** Implement what the task describes. Unrelated issues go to `/add_task`.
- **One task at a time.** Focus on the single task unless told otherwise.

## Red Flags — Worktree Discipline

If you catch yourself thinking any of these, you're about to violate the worktree rule:

- "I'll spin up the worktree first so brainstorming is isolated" — No. Worktree comes AFTER plan approval. Brainstorm in the main workspace.
- "I'll start coding before the plan is approved, just to test the idea" — No. If you're writing code, the plan should already be approved and you should be in the worktree.
- "I'll just commit directly to main in this session" — No. Once the plan is approved, the worktree enforces isolation. Use it.
- "Feature branch is faster than worktree" — False. Worktrees are faster (parallel, isolated, no merge conflicts).
- "The task is too small for a worktree" — Size doesn't matter. Worktree enforces discipline. Use it.
- "I'll use /ship instead" — No. /ship creates PRs. Forbidden. Use worktree + direct commit.
- "Worktree is overkill for a bug fix" — Worktree applies to all tasks, no exceptions.
- "I can skip the worktree if the change is isolated" — Isolation is exactly why you use worktrees. No exceptions.

**All of these mean: Brainstorm and plan first. Worktree after approval. No workarounds.**
