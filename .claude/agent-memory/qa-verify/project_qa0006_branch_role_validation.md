---
name: QA-0006 Branch Role Validation - Environment Notes
description: Dev server environment issues encountered during QA-0006 verification; shared DB schema mismatch blocks browser testing
type: project
---

The shared PostgreSQL database was migrated by TD-0084 (migration `24f2759b7d74`) which renamed `organization_members.role` (VARCHAR) to `organization_members.roles` (VARCHAR[]). However, the QA-0006 branch does not include this migration — it still references the old `role` column. As a result, every authenticated API call that triggers permission checks (`check_permission()` queries `organization_members`) returns 500 on the backend.

**Why:** The worktree was branched before TD-0084 landed. The shared database has progressed.

**How to apply:** When a new QA worktree shows 500 errors on any authenticated endpoint, first check if `organization_members.roles` (plural) exists in the DB while the model/code still references `role` (singular). This is the pattern.

**Fix:** The branch needs to be rebased onto main to pick up the TD-0084 migration before browser QA is feasible.

**Additional env issue:** The dev servers claimed to be running on :5183 (frontend) and :8010 (backend) were from deleted worktree `F-0081-run-param-overrides` — both dead at QA time. A new Vite instance started on :5184 and a worktree uvicorn on :8020, but both still hit the schema mismatch.

**Also:** `frontend/qa-verify-driver.mjs` was accidentally committed to the QA-0006 branch (in commit `1ac6a7a` "Saving notification bell updates") — it should be removed from the branch before merging.
