---
name: implement-task
description: Use when the user wants to implement, work on, pick up, or fix a ClickUp task. Triggers on "implement", "work on", "pick up", "fix", "build" followed by a task reference, or /implement_task.
---

# Implement Task

Pick up a ClickUp task, design with subagent review, implement in an isolated worktree, verify, and close it out.

**REQUIRED SUB-SKILL:** `superpowers:brainstorming` — before any spec is written.
**REQUIRED SUB-SKILL:** `superpowers:writing-plans` — after brainstorming converges.

## When to Use

- User provides a ClickUp task ID and wants it implemented
- User says "pick up", "work on", "fix", "build" referencing a tracked task

**Don't use when:** User wants to create a new task (use `/add_task`), update an existing task without implementation (use `/task_update`), or ship already-written code (use `/ship`).

## ClickUp status flow

This skill drives the task through these statuses in order. Each transition is a `clickup_update_task` call at the marked step — non-optional, since the status is what tells anyone watching ClickUp where the task actually is.

| Step | Trigger | Status |
| --- | --- | --- |
| 1 | Task fetched | (leave as-is) |
| 2 | Brainstorming starts | `planning` |
| 3 | User accepts plan | `planning complete` |
| 4 | Execution mode chosen + worktree up | `in progress` |
| 5 | Implementation handed to review + qa | `verification` |
| 6 | User confirms feature works | `complete` |

## Process

### 1. Fetch and claim

`clickup_get_task` with the provided ID. Read description, acceptance criteria, priority, linked tasks. If no ID given, ask.

**Rename the session** with `/rename` to `<TASK-ID> <task title>` so it's easy to find and resume later. Example: `/rename TD-0067 Frontend component reuse audit`.

Do **not** create a worktree yet — brainstorming and planning happen in the main workspace.

### 2. Brainstorm, spec, plan — with subagent review at each gate

`clickup_update_task` status → **`planning`**.

2a. Invoke `superpowers:brainstorming` with the task description and codebase context.

2b. After the approach converges, write a design spec at `docs/superpowers/specs/<YYYY-MM-DD>-<task-slug>-design.md`.

2c. **Spec review panel.** Dispatch the relevant reviewers in **parallel** (single message, multiple `Agent` calls) against the spec:
- `adversarial-risk-auditor` — always
- `dry-reuse-auditor` — always
- `coupling-impact-analyzer` — always
- `db-scalability-reviewer` — if schema, migration, or query changes
- `production-ops-reviewer` — if new endpoint, background job, or external dep
- `uiux-design-reviewer` — if user-facing UI

Triage findings with the user, apply accepted ones to the spec, commit as `docs(<TASK>): harden spec after review panel`.

2d. Invoke `superpowers:writing-plans` to produce an implementation plan at `docs/superpowers/plans/<YYYY-MM-DD>-<task-slug>.md`.

2e. **Plan review panel.** Same fan-out against the plan. Apply accepted findings, commit as `docs(<TASK>): harden plan after review panel`.

2f. Present the hardened plan to the user. **Wait for explicit approval.** Iterate on any reshaping here, in the main workspace — never spin up a worktree to "explore."

### 3. Plan accepted — choose execution mode

`clickup_update_task` status → **`planning complete`**.

Ask the user which execution mode they want:
- **Subagent-driven** — parallel implementation via `superpowers:subagent-driven-development`. Better when the plan has independent slices.
- **Inline TDD** — sequential, you implement in this session. Better when changes are tightly coupled or small.

Wait for the answer before proceeding.

### 4. Stand up the isolated dev environment

`clickup_update_task` status → **`in progress`**.

4a. **Create the worktree.** `EnterWorktree` with a name derived from the task ID (e.g. `td-0091a-notification-bugfixes`). Branches from `origin/main` and switches the session into the worktree.

4b. **Install deps** — worktrees carry no `node_modules/` or `.venv/`:
- `cd frontend && npm install`
- `cd backend && python -m venv .venv && source .venv/bin/activate && pip install poetry && poetry install --no-root`

4c. **Claim a slot.** Find the lowest `<N>` (1–9) whose backend port `80<N>0` is free (`lsof -i :80<N>0`). Claim it atomically by creating the dev DB: `psql -U postgres -h localhost -c 'CREATE DATABASE batchrite_wt<N>'`. On an "already exists" error, try `<N>+1`. If none is free by 9, stop and fail loudly. If `psql` can't connect, fix Postgres — never fall back to the shared `batchrite`.

4d. **Wire the slot's DBs.** `.env` and `settings.yaml` are gitignored, so the worktree lacks them. Copy both from the main workspace's `backend/` into `<worktree>/backend/`. In the copied `.env`, replace-or-append:

```
BATCHRITE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite_wt<N>
```

This file is the source of truth for the slot — cleanup reads `<N>` back from it. Then create the test DB: `psql -U postgres -h localhost -c 'CREATE DATABASE batchrite_wt<N>_test'`. `conftest.py` derives the test DB name from `BATCHRITE_DATABASE_URL` and builds its schema from ORM metadata.

4e. **Migrate and seed.** From `<worktree>/backend/` with the venv active: `alembic upgrade head`, then `python -m app.db.seed` (not `reset.sh` — it aborts without a TTY).

4f. **Start dev servers** (background both):
- Backend: `uvicorn app.main:app --reload --port 80<N>0`
- Frontend: `VITE_API_PORT=80<N>0 npm run dev -- --port <5173 + 10*N>`

4g. Bring spec/plan artifacts from step 2 into the worktree if they live outside it.

### 5. Implement

Work the approved plan in the worktree using the chosen mode:
- **Subagent-driven:** invoke `superpowers:subagent-driven-development` and dispatch tasks per the plan.
- **Inline TDD:** Red-Green-Refactor per `superpowers:test-driven-development`.

Run the full test suite when done (see CLAUDE.md for commands).

### 6. Verification

`clickup_update_task` status → **`verification`**.

6a. **Code-diff review panel.** Same fan-out as 2c/2e, this time against the diff (`git diff main...HEAD`). Triage with the user, apply accepted findings, commit as `fix(<TASK>): reconcile code-diff review-panel findings`.

6b. **Browser verification** (if frontend changed). Launch the `qa-verify` agent. Pass it:
- How to log in: `admin@bioprocess.com` / `password123` (any password works in dev)
- What feature was implemented and which pages are affected
- Acceptance criteria and edge cases
- **The worktree's frontend URL** (`http://localhost:<5173 + 10*N>`) so it tests this slot, not main

qa-verify must fix any FAIL or POLISH issues before returning.

6c. **Hand off to the user.** Tell them, explicitly:
- What was implemented and which acceptance criteria are met
- The worktree's frontend URL and login credentials
- Which pages and flows to walk through
- Tests added

Ask them to verify and confirm. Iterate until sign-off. If scope grew materially during implementation, re-invoke `superpowers:writing-plans` to update the plan and re-run the plan review panel before continuing.

### 7. Refresh project rules

Before closing, sync `.claude/rules/*.md` and root `CLAUDE.md` with what actually changed. **Edit existing files in place** — do not create new ones unless a genuinely new domain appeared.

What to touch:
- New convention, pattern, or constraint → add to the most relevant existing rules file
- Obsoleted convention → delete or rewrite the stale lines (don't leave both)
- New feature flag, env var, command, or service surface → update `CLAUDE.md`
- File/directory renames referenced in rules → update the path
- Nothing relevant changed → skip this step entirely

**Prune stale content — required, not optional:**
- Code paths, files, functions, or commands no longer present (`grep` to confirm before deleting)
- Feature flags, env vars, or migrations that have been removed or fully rolled out
- "TODO", "WIP", "soon" notes for shipped or abandoned work
- Workarounds for bugs that have since been fixed
- Old conventions the new change contradicts — delete the old line
- Dated language ("as of <date>", "recently…", "we now…") — rewrite in timeless present

**Succinctness:**
- Rewrite an existing line rather than appending. Three near-duplicate bullets become one.
- Drop hedges, restated context, and any sentence that explains *what* the code does. Keep *why* / *when* / non-obvious constraints.
- If a section grows past ~20 lines, refactor: collapse, drop dead examples, or split into a sub-file referenced from the parent.
- If the file ends up longer than before, ask what to cut to net out shorter or even.

Commit these in the worktree.

### 8. Close out and tear down

Only after explicit user sign-off:

8a. `clickup_update_task` status → **`complete`**.
8b. `clickup_create_task_comment` with summary of changes, files modified, tests added.
8c. **Tear down the environment** — do this *while still in the worktree* so `<worktree>/backend/.env` is readable for the slot `<N>`:
- Stop both dev servers (kill by PID/port)
- `psql -U postgres -h localhost -c 'DROP DATABASE IF EXISTS batchrite_wt<N> WITH (FORCE)'`
- `psql -U postgres -h localhost -c 'DROP DATABASE IF EXISTS batchrite_wt<N>_test WITH (FORCE)'`
8d. `ExitWorktree` action `keep` (preserves commits). Use `remove` only if the work was abandoned.

Commits remain on the worktree branch. Merging into `main` follows the project's integration process and is outside this skill's scope.

## Common Mistakes

- **Skipping the review panel.** Brainstorming converges on the *shape*; the panel catches what brainstorming missed. Run it on the spec, the plan, and the diff — three gates.
- **Creating the worktree before plan approval.** Worktree is for executing an approved plan, not prototyping. Brainstorm and plan in main.
- **Sharing the main `batchrite` DB.** If `psql` fails when claiming a slot, fix Postgres. Never fall back to the shared DB — it corrupts the main workspace.
- **Dropping DBs after `ExitWorktree`.** `.env` is gone, the slot `<N>` is unknown. Drop while still in the worktree.
- **Pushing the branch on cleanup.** The user pushes themselves.
- **Closing without sign-off.** Tests verify correctness, not completeness — the user decides done.
- **Scope creep.** Unrelated issues go to `/add_task`, not this task.

## Rules

- **Plan before worktree.** Steps 1–3 happen in the main workspace. Worktree is created at step 4.
- **Review panel at three gates.** Spec, plan, diff. Each fan-out is a single message with multiple `Agent` calls so the reviewers run in parallel.
- **Status drives the flow.** Each transition (`planning` → `planning complete` → `in progress` → `verification` → `complete`) is non-optional.
- **No feature branches, no PRs.** Worktree + direct merge to local `main` only. Don't invoke `/ship` or `git checkout -b`.
- **User confirms completion.** Never mark `complete` without explicit sign-off.
- **One task at a time.**

## Red Flags — Worktree Discipline

If you catch yourself thinking any of these, you're about to violate the flow:

- "I'll spin up the worktree first so brainstorming is isolated" — No. Worktree comes after plan approval and the user picks the execution mode.
- "I'll start coding before the plan is approved" — No. If you're writing code, you should be in the worktree and the status should be `in progress`.
- "The task is too small for a worktree" — Size doesn't matter; the worktree enforces DB isolation.
- "I'll skip the review panel for this small change" — No. Run a trimmed panel (e.g. just `adversarial-risk-auditor` + `dry-reuse-auditor`) but never zero reviewers.
- "I'll use the shared `batchrite` DB just for this slot" — No. Slot-numbered DB or fail loudly.
- "I'll drop the DBs after `ExitWorktree`" — No. Drop first, exit second.
