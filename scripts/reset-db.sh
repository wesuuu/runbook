#!/usr/bin/env bash
# Reset local dev DB: wipe user-generated data and re-seed baseline.
# Guarded to only run against localhost/batchrite by app.db.reset.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root/backend"

if [[ -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

exec python -m app.db.reset
