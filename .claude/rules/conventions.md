# Architectural Conventions

## Service Abstraction

- **Class** when: multiple methods share state (e.g., `FileStorageService` holds `storage_root`).
- **Module functions** when: stateless and independent (e.g., `check_permission()`, `log_audit()`). Most common pattern.
- **Inline** when: small, single-use, unlikely to be reused.
- If 3+ arguments repeat across related functions, consider a class. If functions only need `db` + domain args, keep them as functions.

## Configuration

All settings in `backend/app/core/config.py` on the `Settings` class. Access: `from app.core.config import settings`.

- Env prefix: `BATCHRITE_`
- Sensible defaults required. Never read `os.environ` directly in service code.

## AI Provider Resolution

All AI capabilities resolve via `get_model(capability, db, org_id)` from `ai_config.py`:
1. Org DB config (`AiProviderConfig`) > 2. Platform env vars (`BATCHRITE_AI_{CAP}_*`, Pro+) > 3. `DEFAULT_CONFIGS` (Pro+)

Never hardcode provider/model strings.

## DRY

- Check for existing utilities before implementing. Flag 3+ repetitions for abstraction.
- Prefer extending existing services over creating new ones.
- **Frontend components**: Reuse shared UI from `lib/components/ui/` (buttons, dialogs, cards, dropdowns, tables). Never build a custom modal, table, or button from scratch -- compose from the existing shadcn-svelte primitives. If a pattern appears on 2+ pages (e.g., a confirmation dialog, a data table with sorting), extract it into a shared component in `lib/components/`.

## Dependency Injection

- DB: `Depends(get_db)` | User: `Depends(get_current_user)`
- Permissions: `Depends(require_permission(ObjectType.X, "id_param", PermissionLevel.Y))`
- Tier: `Depends(require_tier(SubscriptionTier.PRO))`
- Never create your own session in endpoint code.

## Error Handling

401 (middleware) > 403 (deps) > 404 (`get_or_404`) > 422 (Pydantic auto). Services raise `ValueError`; endpoints catch and convert.

## Worktree Dev Servers

Alternate ports to avoid collisions with main workspace:
- Main: backend :8000, frontend :5173
- Worktree 1: backend :8010, frontend :5183
- Worktree 2: backend :8020, frontend :5193

Check ports with `lsof -i :PORT`. Set `VITE_API_PORT` to match the backend.
