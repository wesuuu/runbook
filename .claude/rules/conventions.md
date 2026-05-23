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

### Component placement

New Svelte components under `frontend/src/lib/components/` MUST go in a domain subdirectory, not at the root. Choose the most specific existing bucket before creating a new one.

- `ui/` — shadcn-svelte primitives only (buttons, inputs, dialogs, etc.)
- `edra/` — rich-text editor (edra integration)
- `protocol/` — protocol-editor canvas pieces, nodes, inspector, sidebar
- `project/` — project page tabs and project-scoped dialogs
- `run/` — run execution surfaces (edit mode, attachments, history, role wizard)
- `settings/` — settings page tabs and their modals
- `field-mode/` — tablet/field-mode flows
- `modals/` — heavy dialogs wrapping a form, import, or picker flow (contrast with lightweight confirmation dialogs, which go in `shared/`)
- `media/` — camera, image, PDF, barcode scanning
- `document-refinement/` — library refinement editor surfaces (sidebar, queue, AI panel, Tiptap-backed editor)
- `analytics/` — charts, audit trails, version history
- `ai/` — chat and agent UX
- `layout/` — global app chrome (nav, user menu, logo, banners that live in `+layout.svelte`)
- `sites/` — Sites & Equipment management page surfaces (rail, dialogs, archive wizard, managers panel)
- `equipment/` — equipment table, filter bar, form dialog, attachments list, tags input
- `experiment/` — org-wide experiments index surfaces, run progress bar, experiment create modal
- `shared/` — small cross-cutting presentational pieces (badges, small banners, markdown rendering, generic tables)

If a component is used by only one domain's routes, prefer that domain's bucket over `modals/` or `shared/`.

## Dependency Injection

- DB: `Depends(get_db)` | User: `Depends(get_current_user)`
- Permissions: `Depends(require_permission(ObjectType.X, "id_param", PermissionLevel.Y))`
- Tier: `Depends(require_tier(SubscriptionTier.PRO))`
- Never create your own session in endpoint code.

## Error Handling

401 (middleware) > 403 (deps) > 404 (`get_or_404`) > 422 (Pydantic auto). Services raise `ValueError`; endpoints catch and convert.

## Worktree Dev Servers

Worktrees have independent file trees but **no untracked/ignored files** (`node_modules/`, `.venv/`). Before starting dev servers in a worktree:

1. `cd frontend && npm install` — install frontend dependencies
2. `cd backend && python -m venv .venv && source .venv/bin/activate && pip install poetry && poetry install --no-root` — set up backend venv (project uses `pyproject.toml` via Poetry; there is no `requirements.txt`)

Alternate ports to avoid collisions with main workspace:
- Main: backend :8000, frontend :5173
- Worktree 1: backend :8010, frontend :5183
- Worktree 2: backend :8020, frontend :5193

Check ports with `lsof -i :PORT`. Set `VITE_API_PORT` to match the backend.
