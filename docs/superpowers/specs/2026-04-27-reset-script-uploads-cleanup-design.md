# Reset Script: Uploads Cleanup + Rename

**Date:** 2026-04-27
**Scope:** Dev-only convenience script. No production code paths affected.

## Problem

`scripts/reset-db.sh` wipes user-generated DB rows and re-seeds the baseline, but leaves files in `backend/uploads/` on disk. After many dev sessions, hundreds of stale org-scoped UUID directories accumulate (currently ~170 entries) — DB rows reference paths that no longer correspond to existing orgs, and the dir is harder to inspect.

The script's name (`reset-db.sh`) also undersells what it does now that it covers more than the DB.

## Goals

1. After a successful DB reset, delete every top-level entry under `backend/uploads/` **except `system/`**.
2. Rename the script `scripts/reset-db.sh` → `scripts/reset.sh` to reflect the broader scope.
3. Keep the change to a pure-bash edit — no changes to `app/db/reset.py` or its tests.

## Non-Goals

- No archival, dry-run, or `--keep-files` flag. Destructive intent is explicit; opt-in flags would be premature.
- No new tests. This is a 3-line shell change to a dev-only script; the python reset module retains its existing test coverage.
- Not changing the `[reset-db]` log prefixes inside `app/db/reset.py` — they're internal labels.
- Not touching historical plan/spec docs under `docs/superpowers/` that mention the old script name.

## Background: uploads layout

`FileStorageService` writes files at `{storage_root}/{org_id}/{base_dir}/...`. Verified callers:

- Avatars → `{org_id}/avatars/{user_id}.{ext}` (`backend/app/api/endpoints/auth.py:586`)
- Documents → `{org_id}/documents/...` (`backend/app/api/endpoints/library.py:168`)
- Run images → `{org_id}/images/...` (`backend/app/api/endpoints/sync.py:185`, `ai.py:265`)
- URL imports → `{org_id}/documents/...` (`backend/app/services/protocols/url_importer.py:172`)

System-wide files (e.g., bundled document templates) live under `uploads/system/`.

The top-level `uploads/avatars/`, `uploads/documents/`, and `uploads/images/` directories on disk today are **legacy** — no current code path writes to them. They may be removed by the cleanup along with all UUID-named org dirs.

**Policy:** Anything under `uploads/` that is not `system/` is org-scoped or legacy and may be wiped on reset.

## Design

### File renames

- `scripts/reset-db.sh` → `scripts/reset.sh` (preserve `chmod +x`).

### Reference updates

- `CLAUDE.md` (Backend dev commands block, line ~19): update path.
- `backend/app/db/reset.py` (module docstring, line ~4): update path.

Historical docs under `docs/superpowers/plans/` and `docs/superpowers/specs/` are left untouched — they document the prior state.

### `scripts/reset.sh` (final contents)

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

### Key correctness properties

- **`exec` dropped.** The previous script ended with `exec python -m app.db.reset`, which replaced the shell process and would have prevented any post-step. Removed so the cleanup step can run.
- **Safety via `set -e`.** If the python reset exits non-zero (user aborts at confirmation, prod-guard trips, wipe fails), the script exits before the cleanup step — files are preserved on any failure path.
- **Scoped deletion.** `find -mindepth 1 -maxdepth 1 ! -name system -exec rm -rf {} +` deletes only direct children of `uploads/`, never recurses into `system/`, and never escapes the `uploads/` directory.
- **Idempotent.** The outer `if [[ -d "$uploads_dir" ]]` no-ops if the directory doesn't yet exist.

## Acceptance Criteria

| Criterion | How to verify |
|---|---|
| `scripts/reset.sh` exists, executable, callable from repo root | `ls -l scripts/reset.sh` shows `x` bit |
| Old `scripts/reset-db.sh` no longer exists | `ls scripts/reset-db.sh` returns "No such file" |
| `CLAUDE.md` references `scripts/reset.sh` | `grep reset CLAUDE.md` |
| `backend/app/db/reset.py` docstring references `scripts/reset.sh` | `grep reset.sh backend/app/db/reset.py` |
| After running, `uploads/` contains only `system/` (when reset succeeds) | `ls backend/uploads/` shows only `system` |
| When the python reset is aborted (e.g., `echo n \| scripts/reset.sh`), uploads are unchanged | snapshot `ls backend/uploads/` before/after, diff is empty |

## Risks

- **Wrong-directory deletion.** Mitigated by anchoring `uploads_dir` to `$repo_root/backend/uploads` (computed from the script's own location), the `[[ -d ]]` guard, and the prod-guard already enforced by `app.db.reset` (script aborts on non-localhost DBs before reaching cleanup).
- **Drift from the python module.** Future changes to `FileStorageService` paths could re-introduce non-`system/` system-wide directories. Acceptable: the cleanup is dev-only and any such addition would be visible immediately.
