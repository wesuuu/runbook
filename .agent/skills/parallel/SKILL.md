---
name: parallel
description: Run code-writing skills in an isolated git worktree with dedicated dev servers on alternate ports. Use when the user wants to work on a task in parallel without disrupting the main dev servers (e.g., "/parallel /feature_impl F-0023", "/parallel /td_fix critical", "work on this in parallel"). Handles worktree setup, dependency installation, alternate-port server startup, and guided merge back to main.
---

# Parallel Isolation

Run any code-writing task in a git worktree with its own dev servers so the main branch stays stable.

**Usage**: `/parallel <inner-skill-or-task>` (e.g., `/parallel /feature_impl F-0023`)

## Phase 1 — Setup

1. **Enter worktree** using `EnterWorktree` with a descriptive name:
   - From a skill: `parallel-f0023`, `parallel-td0012`, `parallel-bug0005`
   - Ad-hoc: `parallel-<short-description>` (e.g., `parallel-refactor-auth`)

2. **Install dependencies** in the worktree (run in parallel):
   ```bash
   # Backend: symlink venv from main repo to avoid full reinstall
   ln -s /home/wesuuu/Code/trellisbio/backend/.venv backend/.venv
   ```
   ```bash
   # Frontend: must install (node_modules not in git)
   cd frontend && npm install
   ```

3. **Start dev servers on alternate ports** (run in background):
   ```bash
   # Backend on port 8010
   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8010
   ```
   ```bash
   # Frontend on port 5183, pointing at backend :8010
   cd frontend && VITE_API_PORT=8010 npx vite dev --port 5183
   ```
   **IMPORTANT**: The frontend `config.ts` hardcodes port 8000. Before starting the frontend, temporarily patch it:
   ```typescript
   // frontend/src/lib/config.ts — change to:
   export const API_BASE = `http://${import.meta.env.VITE_API_HOST || 'localhost'}:${import.meta.env.VITE_API_PORT || '8000'}`;
   ```
   This change stays local to the worktree branch. Revert it before merging (Phase 3).

4. **Confirm servers are healthy**:
   ```bash
   curl -s http://localhost:8010/health   # backend
   curl -s http://localhost:5183          # frontend
   ```

5. **Tell the user** the worktree is ready:
   > Parallel environment ready:
   > - Worktree: `.claude/worktrees/<name>`
   > - Backend: http://localhost:8010
   > - Frontend: http://localhost:5183
   > - Branch: `<worktree-branch-name>`
   >
   > Main dev servers (:8000/:5173) are unaffected. Proceeding with `<inner task>`.

## Phase 2 — Execute Inner Task

Run the inner skill or task **exactly as normal**. The worktree is now the working directory, so all file reads/writes, git operations, and test runs happen in isolation.

**Key differences the inner skill should know:**
- Tests should run against port `8010` (backend) / `5183` (frontend)
- Browser verification URLs use `:5183` instead of `:5173`
- E2E tests: `cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:5183 npx playwright test`
- Git commits land on the worktree branch, not `main`

**Do NOT run /ship at the end** — Phase 3 handles the merge.

## Phase 3 — Merge & Cleanup

After the inner task is complete and the user has verified the work:

1. **Revert the config.ts port patch** (if applied):
   ```typescript
   // Restore to original:
   export const API_BASE = `http://${import.meta.env.VITE_API_HOST || 'localhost'}:8000`;
   ```
   Commit this revert separately: `chore: revert parallel port config`

2. **Stop the worktree dev servers** (kill the background processes on :8010/:5183).

3. **Show the user what will be merged**:
   ```bash
   git log main..<worktree-branch> --oneline   # commits
   git diff main...<worktree-branch> --stat     # file changes
   ```

4. **Ask the user** how to proceed — present these options:
   > Parallel work is ready to merge. Options:
   > 1. **Squash merge** into main (single commit, clean history)
   > 2. **Merge commit** into main (preserves individual commits)
   > 3. **Keep branch** for later (exit worktree, branch stays)
   > 4. **Discard** (remove worktree and branch)

5. **Execute the chosen option**:

   **Squash merge:**
   ```bash
   git checkout main
   git merge --squash <worktree-branch>
   git commit  # use descriptive message from inner task
   ```
   Then `ExitWorktree` with action `remove`.

   **Merge commit:**
   ```bash
   git checkout main
   git merge <worktree-branch> --no-ff
   ```
   Then `ExitWorktree` with action `remove`.

   **Keep branch:**
   `ExitWorktree` with action `keep`. Tell user how to return:
   > Branch `<name>` preserved. To resume: `cd .claude/worktrees/<name>`

   **Discard:**
   `ExitWorktree` with action `remove`, `discard_changes: true` (confirm with user first).

## Port Allocation

If the default parallel ports (8010/5183) are already in use (e.g., multiple parallel tasks), increment:

| Slot | Backend | Frontend |
|------|---------|----------|
| Main | 8000 | 5173 |
| Parallel 1 | 8010 | 5183 |
| Parallel 2 | 8020 | 5193 |

Check with `lsof -i :8010` before starting. Use the next available slot.

## Troubleshooting

- **Venv symlink issues**: If backend fails to start, create a real venv instead:
  ```bash
  cd backend && python3.13 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
  ```
- **Port conflicts**: Use `lsof -i :<port>` to find and resolve conflicts.
- **Merge conflicts**: If squash/merge fails, show the conflicts to the user and resolve together. Never force-resolve without user input.
- **Database**: Worktrees share the same PostgreSQL database (`batchrite`). If the task includes migrations, warn the user that migrations will affect the main branch's database too. Consider using `batchrite_parallel` as an alternate DB if schema changes are involved.
