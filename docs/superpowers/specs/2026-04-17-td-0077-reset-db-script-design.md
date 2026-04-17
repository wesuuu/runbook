# TD-0077 — Reset-DB Script Design

**Status:** Approved
**Date:** 2026-04-17
**Ticket:** [TD-0077](https://app.clickup.com/t/86e0z7pqc)
**Effort:** S (<1hr)

## Problem

The local dev DB has accumulated invalid/stale data (partial protocols, orphaned runs, test batch records). Developers need a one-shot reset to return the DB to the exact minimal state defined by `app.db.seed`.

## Scope

- **Preserve** (seed baseline): `users`, `organizations`, `organization_members`, `teams`, `team_members`, `projects`, `object_permissions`, `unit_op_definitions`, `ai_provider_configs` (org-scoped, treated as org config not user data).
- **Wipe** (24 tables): `experiments`, `protocols`, `protocol_roles`, `protocol_versions`, `runs`, `run_role_assignments`, `equipment`, `documents`, `document_chunks`, `document_templates`, `batch_record_imports`, `chat_sessions`, `chat_messages`, `run_images`, `image_conversations`, `audit_logs`, `background_jobs`, `notifications`, `notification_channels`, `notification_subscriptions`, `notification_deliveries`, `revoked_offline_tokens`, `invitations`, `verification_tokens`.

Alembic's `alembic_version` table is left alone (schema migrations are not user-generated data).

## Architecture

### New files

- `backend/app/db/reset.py` — core module + CLI entry point (`python -m app.db.reset`).
- `scripts/reset-db.sh` — executable shell wrapper callable from repo root.

### Modified files

- `CLAUDE.md` — add `scripts/reset-db.sh` line under the Backend dev commands block.

### `reset.py` layout

Public surface kept small; logic is split so the transactional work is callable from tests without the interactive prompt.

```
WIPE_TABLES: tuple[str, ...]           # ordered literal list of 24 tables

def mask_database_url(url: str) -> str
    # regex replaces the password segment with *** for safe display

async def reset_database(session: AsyncSession) -> None
    # 1. TRUNCATE {WIPE_TABLES} RESTART IDENTITY CASCADE (single statement)
    # 2. seed_users, seed_org, seed_teams, seed_projects,
    #    seed_permissions, seed_unit_ops (all idempotent)
    # Caller manages the transaction.

def confirm_reset() -> bool
    # if not sys.stdin.isatty(): abort → return False
    # print masked URL, print wipe list
    # read "y/N" from stdin; only "y" (case-insensitive) proceeds

async def _run() -> int
    # orchestrator: confirm → open AsyncSessionLocal → session.begin() →
    #   reset_database(session) → commit-on-exit
    # returns 0 on success, 1 on abort/error
```

### `reset-db.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root/backend"

if [[ -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

exec python -m app.db.reset
```

Made executable via `chmod +x`.

## Transaction model

One transaction wraps both the wipe and the re-seed:

```python
async with AsyncSessionLocal() as session:
    async with session.begin():
        await reset_database(session)
```

`reset_database()` itself does **not** open a transaction. This makes it test-friendly: tests can call it inside the conftest's per-test SAVEPOINT, where PostgreSQL TRUNCATE is still rolled back at teardown.

`TRUNCATE ... CASCADE` handles FK chains automatically (e.g., `protocol_versions` → `protocols`, `run_role_assignments` → `runs`), so the order of tables in `WIPE_TABLES` does not matter for correctness.

Existing `seed_*` functions are already idempotent (check-before-insert by PK), so re-running them against an empty-or-partial DB is safe.

## Safety

- **Masking**: `mask_database_url` replaces `://user:password@` with `://user:***@` so passwords never print to logs/terminal.
- **TTY gate**: `sys.stdin.isatty()` check prevents `yes | reset-db.sh` and similar accidents.
- **Explicit confirm**: default is N — any input other than `y` (case-insensitive, stripped) aborts.
- **Atomicity**: single transaction → partial failure rolls back everything.

## Tests (TDD)

### Unit — `backend/tests/unit/test_reset_db.py`

- `mask_database_url`:
  - Masks `postgresql+asyncpg://postgres:postgres@localhost:5432/batchrite` → `...://postgres:***@...`
  - Masks a URL with a complex password (special chars).
  - Passes through URLs with no password unchanged.
- `WIPE_TABLES` sanity:
  - Contains all 24 expected names.
  - Contains none of the 9 preserve table names (users, organizations, organization_members, teams, team_members, projects, object_permissions, unit_op_definitions, ai_provider_configs).

### Integration — `backend/tests/integration/test_reset_db.py`

Uses the shared `db_session` fixture (per-test SAVEPOINT):

- **`test_wipe_clears_user_generated_data`**: create a Protocol, a Run, an AuditLog, a Document inside the session → call `reset_database(db_session)` → assert each of those tables is empty.
- **`test_seed_baseline_present_after_reset`**: call `reset_database(db_session)` → assert the 6 seed users, 2 seed orgs, 3 seed teams, 2 seed projects, and ≥1 unit op definition exist with their fixed UUIDs.
- **`test_idempotent_on_empty_db`**: call `reset_database(db_session)` twice in a row → second call succeeds, same baseline state.
- **`test_preserve_tables_untouched`**: snapshot preserve-table row IDs before reset → call `reset_database(db_session)` → assert IDs identical after (no churn on users/orgs/teams/projects/etc.).

Edge case not tested automatically: the TTY gate in `confirm_reset` — hard to simulate cross-platform and not business-critical. Covered by manual `echo y | scripts/reset-db.sh` smoke test (expected to abort).

## Acceptance Criteria mapping

| AC | Where it's satisfied |
|----|---------------------|
| Script exists + executable from repo root | `scripts/reset-db.sh` + `chmod +x` |
| Prints masked DATABASE_URL and DB name | `confirm_reset` calls `mask_database_url(settings.database_url)` |
| Shows wipe table list + y/N confirmation | `confirm_reset` |
| Single-transaction TRUNCATE + re-seed | `_run()` uses `async with session.begin()` around `reset_database()` |
| Post-run DB matches `app.db.seed` | `reset_database` calls the 6 idempotent `seed_*` functions |
| Idempotent on repeat | `test_idempotent_on_empty_db` |
| Safe on empty DB | Same test + TRUNCATE is a no-op on empty tables |
| Preserve tables untouched | `test_preserve_tables_untouched` |
| CLAUDE.md mentions it | Edit to CLAUDE.md dev commands block |

## Out of scope

- Remote/prod database reset safety (script is dev-only; no staging/prod guard beyond the masked URL print which surfaces the target).
- Resetting `alembic_version` — migrations stay applied.
- A non-interactive `--force` flag — ticket explicitly requires interactive confirmation.
