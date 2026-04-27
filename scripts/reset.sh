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
