# CLAUDE.md

## Project Overview

Batchrite — a Laboratory Execution System (LES) for biotech Process Development (PD) scientists. Tablet-first, voice-enabled digital lab notebook. Graph-based, copy-on-write data stored as JSONB in PostgreSQL. Protocols are templates; Experiments snapshot Protocol graphs and track deviations at runtime.

## Commands

### Backend (from `backend/`, venv activated: `source .venv/bin/activate`)

```bash
uvicorn app.main:app --reload                       # dev server :8000
alembic upgrade head                                 # apply migrations
alembic revision --autogenerate -m "description"     # generate migration
pytest                                               # all tests
pytest tests/unit/ | tests/integration/              # by suite
pytest --cov=app --cov-report=html                   # with coverage
black app tests && isort app tests && mypy app       # lint
../scripts/reset.sh                                  # wipe DB user data, re-seed, clear org uploads (local only)
```

### Frontend (from `frontend/`)

```bash
npm run dev                # Vite dev server :5173
npm run build              # production build
npm run check              # svelte-check + tsc
npm run test               # Vitest (single run)
npm run test:e2e           # Playwright (requires dev servers)
```

## Architecture (high-level)

Detailed patterns are in `.claude/rules/` and load automatically when you touch relevant files.

- **Backend**: FastAPI (async), SQLAlchemy 2.0 (async/asyncpg), Alembic. Routers in `api/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.
- **Frontend**: Svelte 5 (Runes), Vite, TailwindCSS 4, shadcn-svelte. API client in `lib/api.ts`, Zod schemas in `lib/schemas/`, state in `.svelte.ts` files, UI components in `lib/components/ui/`.
- **Database**: PostgreSQL localhost:5432, database `batchrite`, user `postgres`/`postgres`. JSONB for graph data and param schemas. Seed scripts in `scripts/`.

## Workflow

- **TDD required**: Red-Green-Refactor. Write failing tests before implementation. Target >80% coverage.
- **ClickUp is source of truth**: Tasks in FEATURES, BUGS, QA, TECH_DEBT lists.
- **Commit format**: `<type>(<scope>): <description>` — types: feat, fix, docs, style, refactor, test, chore
- **CI-aware**: Use `CI=true` prefix for watch-mode tools.

## Code Style

- **Python**: Google style — `snake_case`, 80-char lines, type annotations on public APIs. Formatted with `black` + `isort`.
- **TypeScript**: Google style — `const`/`let` only, named exports, `lowerCamelCase` for variables/functions, `UpperCamelCase` for types/classes, avoid `any`, explicit semicolons, single quotes, triple-equals.

## Feature flags

Some features are gated by env vars so we can ship with them disabled and flip them on later without code changes.

| Flag | Backend | Frontend | Default | Notes |
| --- | --- | --- | --- | --- |
| Offline / PWA | `features.offline_mode.enabled` (yaml) or `BATCHRITE_FEATURES__OFFLINE_MODE__ENABLED` (env) | `VITE_OFFLINE_ENABLED` | `false` | Offline field-mode session, IndexedDB cache, sync queue, "Go Offline" flow. (TD-0082) |

Flags must be set on **both** sides to take effect end-to-end. Flipping only the frontend leaves the UI live but the backend will 404 on `/offline/*` and `/sync/*`; flipping only the backend leaves the routes mounted but unreachable from the UI.
