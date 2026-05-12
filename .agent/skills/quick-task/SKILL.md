---
name: quick-task
description: Use when the user wants to implement a small, well-scoped ClickUp task that fits existing patterns -- no new abstractions, no architectural decisions. Triggers on "/quick_task", "quick task", "quickly implement", "knock out", or "small fix" referencing a tracked task ID. Pairs with /add_task as the lightweight counterpart to /implement_task.
---

# Quick Task

Pick up a small ClickUp task, make the edits inside the existing software framework, ship it. **No brainstorming, no plan doc, no new abstractions.** If the task wants more than that, this skill bails out and asks the user to switch to `/implement_task`.

**REQUIRED SUB-SKILL:** `superpowers:using-git-worktrees` — invoked before any code is touched.

## When to Use

Use this skill when ALL of these hold:

- Task is tagged S or M effort (or clearly fits in <1 hour of edits)
- The change is **mechanical extension of existing patterns** — adding a field to a model + schema + endpoint, fixing a typo'd query, wiring an existing component into a new page, bumping a constant, adding a missing test
- You can already point to a sibling file/function that shows how the change is done elsewhere in the codebase
- No new module, service, route group, table, or dependency is introduced

**Don't use when** ANY of these hold — escalate to `/implement_task` instead:

- Task asks for a new abstraction, service, or architectural pattern
- Task needs design discussion (multiple viable approaches, tradeoffs to weigh)
- Task touches a domain you don't have an existing template for
- Task is L or XL effort
- User wants to create a task (`/add_task`), update one (`/task_update`), or push code (`/ship`)

## Process

### 1. Fetch and claim

`clickup_get_task` with the provided ID. If no ID was given, ask. Read the description, acceptance criteria, and effort tag.

**Scope check (do this BEFORE the worktree):** Confirm the task is genuinely a quick task. Look at the acceptance criteria and at the codebase. If you can't already name the existing file(s) you'll edit and the existing pattern you're mirroring, this is not a quick task — see "Scope Escalation" below.

If the scope check passes, `clickup_update_task` to set status `in progress`.

### 2. Worktree

Invoke `superpowers:using-git-worktrees` to set up an isolated workspace. Use the native `EnterWorktree` action — it handles directory placement, branch, and cleanup. **Do not create feature branches or use `git worktree add` directly.**

### 3. Edit, mirroring an existing pattern

Find the closest sibling in the codebase (a file, function, or test that already does what you're being asked to do) and **mirror its shape**. Quick tasks are about consistency, not creativity.

Write a focused test for the new behavior first when the change has observable behavior (TDD per CLAUDE.md). For pure refactors or string/constant changes where TDD is theatre, skip straight to the edit and rely on the existing suite.

Run the relevant test command (`pytest tests/<area>` or `npm run test -- <pattern>`) — not the whole suite — until the change is green. Run lints if you touched code in a domain that has them (`black app tests && isort app tests && mypy app` for backend; `npm run check` for frontend).

### 4. Browser sanity check (only if frontend changed)

Open the affected page in the browser and confirm the change renders. **Do not invoke the `qa-verify` agent for quick tasks** — that's for full features. Just eyeball the golden path.

If the change is backend-only or pure refactor, skip this step.

### 5. Commit and exit

Commit in the worktree with a conventional message (`<type>(<scope>): <description>` per CLAUDE.md). Reference the task ID in the body, not the subject.

Exit the worktree with `ExitWorktree` action `keep`. The commit lives on the worktree branch — merging or rebasing into main is the user's call and outside this skill's scope (do not push, do not open a PR).

### 6. Close the task

Only after the user confirms the change works:

1. `clickup_create_task_comment` with a one-paragraph summary: what changed, files touched, any deviations
2. `clickup_update_task` to set status `complete`

Skip the rules-refresh step from `/implement_task` — quick tasks shouldn't be introducing new conventions. If you find yourself wanting to update `.claude/rules/*.md` or `CLAUDE.md`, that's a signal the task wasn't actually a quick task.

## Scope Escalation

**If at any point you discover the task needs MORE than mechanical extension of an existing pattern, stop immediately and ask the user:**

> "This task is bigger than a quick edit — it wants <new abstraction / new pattern / multiple viable approaches>. Want to switch to `/implement_task` so we can brainstorm and write a plan?"

Wait for the user's answer. Do not proceed with a half-baked design under the quick-task banner.

Triggers for escalation (any one is enough):

- You're about to create a new file in a directory that doesn't have a clear matching sibling
- You're about to add a new dependency
- You're weighing two non-trivial approaches and can't pick on obvious-correctness alone
- The acceptance criteria turn out to imply a multi-layer change (e.g., new table + new endpoint + new UI surface + new role/permission)
- The "small fix" is a symptom of a deeper bug that needs root-cause work
- You're tempted to invoke `superpowers:brainstorming` or `superpowers:writing-plans` — that's the signal

## Quick Reference

| Step | Action | Tool / Command |
|---|---|---|
| 1 | Fetch task | `clickup_get_task` |
| 1 | Claim | `clickup_update_task` → `in progress` |
| 2 | Worktree | `EnterWorktree` (via `superpowers:using-git-worktrees`) |
| 3 | Edit | Mirror existing pattern, scoped tests |
| 4 | Sanity check | Browser eyeball (frontend only) |
| 5 | Commit + exit | `git commit` in worktree, `ExitWorktree keep` |
| 6 | Close | `clickup_create_task_comment` + `clickup_update_task` → `complete` |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Treating "quick" as "skip the worktree" | Worktree is non-negotiable. Use `EnterWorktree`. |
| Building a new abstraction inside a quick task | Stop. Escalate to `/implement_task`. |
| Running the full test suite when one file's tests would do | Scope the test command to the area you touched. The full suite is for `/ship`. |
| Skipping the browser eyeball on a frontend change | Tests can pass while the UI is broken. Open the page. |
| Refreshing `.claude/rules/*.md` from a quick task | Quick tasks shouldn't change conventions. If you want to, escalate. |
| Closing without user confirmation | The user signs off. Tests don't. |
| Logging unrelated issues into the same task | New finding → `/add_task` → separate ticket. |

## Red Flags — Stop and Escalate

If you catch yourself thinking any of these, the task isn't a quick task:

- "I just need to spin up a new service for this"
- "Let me sketch a quick design before I start"
- "I'll add a small abstraction so this is reusable later"
- "This is more like two changes than one"
- "I should brainstorm the approach"
- "I need a plan doc for this"
- "I'll update the architecture rules to match"

**All of these mean: switch to `/implement_task`.** Don't smuggle a real feature through under "quick".

## Rules

- **Worktree-only.** Use `EnterWorktree`. No feature branches, no in-place edits on main.
- **Mirror, don't invent.** Quick tasks extend existing patterns. New patterns escalate.
- **No PRs, no `/ship`.** Commit in the worktree, exit with `keep`.
- **User confirms completion.** Tests pass ≠ task done.
- **One task per session.** Side findings go to `/add_task`.
- **Escalate fast.** First sign of expanded scope, ask the user before continuing.
