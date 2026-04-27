# Reset Script: Uploads Cleanup + Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `scripts/reset-db.sh` → `scripts/reset.sh` and add a post-reset bash step that deletes everything in `backend/uploads/` except `system/`.

**Architecture:** Pure-bash edit to the dev-only reset wrapper. No changes to `app/db/reset.py` or its tests. The cleanup runs only after `python -m app.db.reset` exits 0 (relies on `set -e`), so any abort/failure leaves uploads untouched.

**Tech Stack:** bash, `find`. The python reset module is unchanged.

**Spec:** [docs/superpowers/specs/2026-04-27-reset-script-uploads-cleanup-design.md](../specs/2026-04-27-reset-script-uploads-cleanup-design.md)

---

## File Map

- **Rename:** `scripts/reset-db.sh` → `scripts/reset.sh` (preserve `chmod +x`)
- **Rewrite contents of:** `scripts/reset.sh` (~18 LOC)
- **Modify:** `CLAUDE.md` line 19 (Backend dev commands block)
- **Modify:** `backend/app/db/reset.py` line 4 (module docstring)

No new files. No test files. Verification is a manual smoke test (Task 3).

---

### Task 1: Rename script and add uploads cleanup

**Files:**
- Rename: `scripts/reset-db.sh` → `scripts/reset.sh`
- Rewrite: `scripts/reset.sh`

- [ ] **Step 1: Rename the script using `git mv`**

Run from repo root:

```bash
git mv scripts/reset-db.sh scripts/reset.sh
```

- [ ] **Step 2: Verify the rename preserved the executable bit**

Run:

```bash
ls -l scripts/reset.sh
```

Expected: line begins with `-rwxr-xr-x` (or similar — the `x` bits must be set). If not, run `chmod +x scripts/reset.sh`.

- [ ] **Step 3: Replace the contents of `scripts/reset.sh`**

Overwrite the file with exactly:

```bash
#!/usr/bin/env bash
# Reset local dev: wipe DB user data, re-seed baseline, and clear
# org-scoped uploads (preserving uploads/system/).
# Guarded to only run against localhost/batchrite by app.db.reset.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root/backend"

if [[ -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

python -m app.db.reset

uploads_dir="$repo_root/backend/uploads"
if [[ -d "$uploads_dir" ]]; then
    find "$uploads_dir" -mindepth 1 -maxdepth 1 ! -name system -exec rm -rf {} +
    echo "[reset] Cleared org-scoped uploads (kept uploads/system/)."
fi
```

Key differences from the prior version:
- `exec python ...` is now plain `python ...` so the cleanup step can run after.
- New post-step deletes every direct child of `uploads/` except `system/`.

- [ ] **Step 4: Commit the rename + cleanup**

```bash
git add scripts/reset.sh
git commit -m "feat(reset): rename to reset.sh and clear org-scoped uploads"
```

(`git mv` already staged the deletion of the old name; the rewrite is the modification side of the rename.)

---

### Task 2: Update references to the script name

**Files:**
- Modify: `CLAUDE.md` line 19
- Modify: `backend/app/db/reset.py` line 4

- [ ] **Step 1: Update `CLAUDE.md`**

Find this line (around line 19, in the Backend commands block):

```
../scripts/reset-db.sh                               # wipe user data, re-seed baseline (local only)
```

Replace with:

```
../scripts/reset.sh                                  # wipe DB user data, re-seed, clear org uploads (local only)
```

- [ ] **Step 2: Update `backend/app/db/reset.py` docstring**

Find this line in the module docstring (around line 4):

```
Or: scripts/reset-db.sh (from repo root)
```

Replace with:

```
Or: scripts/reset.sh (from repo root)
```

- [ ] **Step 3: Verify no other current-code references to the old name remain**

Run from repo root:

```bash
grep -rn "reset-db\.sh" --include="*.md" --include="*.py" --include="*.sh" --include="*.ts" --include="*.svelte" --include="*.json" . 2>/dev/null | grep -v __pycache__ | grep -v node_modules | grep -v "\.venv/" | grep -v "docs/superpowers/plans/" | grep -v "docs/superpowers/specs/2026-04-17-"
```

Expected: no output. (Historical plan/spec docs from `2026-04-17-td-0077-...` are intentionally left untouched and are filtered out above; the new spec/plan from today are also filtered out via the `docs/superpowers/` paths since they reference `reset.sh`, not `reset-db.sh`.)

If any other line appears, update it to `reset.sh` and re-run.

- [ ] **Step 4: Commit the reference updates**

```bash
git add CLAUDE.md backend/app/db/reset.py
git commit -m "docs(reset): update references to scripts/reset.sh"
```

---

### Task 3: Manual smoke test

**Files:** none (verification only)

This task confirms both the success path (uploads cleared) and the safety path (abort leaves uploads intact). The DB reset itself is covered by existing tests in `backend/tests/`.

- [ ] **Step 1: Snapshot current `uploads/` contents**

Run from repo root:

```bash
ls backend/uploads/ | sort > /tmp/uploads-before.txt
wc -l /tmp/uploads-before.txt
```

Note the line count for comparison.

- [ ] **Step 2: Verify abort path — uploads must NOT be cleared**

Run from repo root:

```bash
echo n | scripts/reset.sh
echo "exit=$?"
```

Expected: prints `[reset-db] Aborted. No changes made.` (or similar from the python module), then `exit=1`. The `find` cleanup line should NOT appear.

Verify uploads are unchanged:

```bash
ls backend/uploads/ | sort > /tmp/uploads-after-abort.txt
diff /tmp/uploads-before.txt /tmp/uploads-after-abort.txt
```

Expected: no output (files identical).

- [ ] **Step 3: Verify success path — uploads cleared except `system/`**

Run from repo root and confirm `y` at the prompt:

```bash
scripts/reset.sh
```

Expected output ends with `[reset] Cleared org-scoped uploads (kept uploads/system/).`

Verify only `system/` remains:

```bash
ls backend/uploads/
```

Expected: exactly `system` (one entry).

- [ ] **Step 4: Verify the app re-creates org dirs on use (sanity)**

Start the backend:

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
```

In another shell, log in via the frontend or trigger any avatar/document/image upload. Confirm `backend/uploads/{org_id}/...` appears. Stop the server.

This isn't strictly required (the existing `FileStorageService` has its own tests for directory creation), but it closes the loop on the dev workflow.

- [ ] **Step 5: No commit** — this task is verification only.

---

## Self-Review

**Spec coverage:**
- Rename script → Task 1 Step 1.
- Drop `exec`, add cleanup → Task 1 Step 3.
- Update `CLAUDE.md` reference → Task 2 Step 1.
- Update `reset.py` docstring → Task 2 Step 2.
- Acceptance criterion "uploads/ contains only system/ after success" → Task 3 Step 3.
- Acceptance criterion "abort leaves uploads unchanged" → Task 3 Step 2.

**Placeholders:** none — every step has the literal commands/file contents.

**Type/name consistency:** the script's variable names (`repo_root`, `uploads_dir`) and the cleanup command are identical between the spec, Task 1 Step 3, and Task 3.
