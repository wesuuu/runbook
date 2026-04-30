---
name: Worktree 2 CORS configuration
description: The backend at :8000 must include :5193 in CORS origins for the td-0072 worktree frontend to work in the browser — this is already in the worktree's main.py
type: project
---

The worktree at `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0072-empty-state` runs its frontend at `:5193`. The main backend at `:8000` must include `http://localhost:5193` in its CORS origins list for browser-based testing to work.

The worktree's `backend/app/main.py` already includes this. But the main workspace's `main.py` does NOT — this discrepancy means QA playwright scripts run from the worktree frontend can't authenticate because `/auth/me` CORS preflight fails.

**Why:** Browser-based Playwright testing hits real CORS checks (unlike server-side API calls). Each worktree port needs its own CORS entry.

**How to apply:** When writing QA driver scripts for worktree 2 (:5193), temporarily add `:5193` to the main workspace's `backend/app/main.py` CORS list, or run the script from within the worktree node_modules context pointing to a backend that already allows the origin. Revert the main workspace change when done (the worktree's own main.py is authoritative).
