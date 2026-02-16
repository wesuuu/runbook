# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Runbook AI Co-Pilot — a tablet-first, voice-enabled digital lab notebook for biotech Process Development (PD) scientists. Core architecture uses graph-based, copy-on-write data stored as JSONB in PostgreSQL. Protocols are templates; Experiments snapshot Protocol graphs and track deviations at runtime.

## Commands

### Backend (from `backend/` directory, with venv activated)

```bash
source .venv/bin/activate

# Run dev server
uvicorn app.main:app --reload          # serves on :8000

# Database migrations
alembic upgrade head                    # apply all migrations
alembic revision --autogenerate -m "description"  # generate migration

# Tests
pytest                                  # all tests
pytest tests/unit/                      # unit tests only
pytest tests/integration/               # integration tests only
pytest tests/unit/test_audit.py         # single test file
pytest --cov=app --cov-report=html      # with coverage

# Linting
black app tests
isort app tests
mypy app
```

### Frontend (from `frontend/` directory)

```bash
npm run dev        # Vite dev server on :5173
npm run build      # production build
npm run check      # svelte-check + tsc type checking
```

## Architecture

### Backend (`backend/app/`)

- **Framework**: FastAPI (async), SQLAlchemy 2.0 (async with asyncpg), Alembic migrations
- **API routers** in `api/endpoints/`: `projects.py`, `science.py` (protocols, experiments, unit ops), `iam.py`
- **Models** in `models/`: `iam.py` (Org/Team/User), `science.py` (Project/Protocol/Experiment/UnitOpDefinition/ProtocolRole), `execution.py` (AuditLog)
- **Schemas** in `schemas/`: Pydantic request/response models
- **Mixins** (`models/mixins.py`): `UUIDMixin` (UUID PKs), `TimestampMixin` (created_at/updated_at)
- **DB session**: async session factory in `db/session.py`, injected via `get_db` dependency
- **Testing**: pytest-asyncio with `asyncio_mode = "auto"`. Tests use a separate `runbook_test` database. `conftest.py` provides `test_engine`, `db_session`, and `client` fixtures with per-test rollback.

### Frontend (`frontend/src/`)

- **Framework**: Svelte 5 (Runes syntax), Vite, TailwindCSS 4, shadcn-svelte
- **Routing**: Hash-based client-side routing via custom `Router.svelte`/`Route.svelte` components
- **Key pages**: `ProtocolEditor.svelte` (XYFlow graph editor), `ExperimentRunner.svelte`, `Projects.svelte`, `ProjectDetail.svelte`
- **Graph editor**: `@xyflow/svelte` with custom node types — `UnitOpNode.svelte` (operations) and `SwimLaneNode.svelte` (roles/phases). Inspector panel for node properties, time axis, horizontal/vertical layout switching.
- **API client**: `lib/api.ts` — wrapper around fetch with error handling, hardcoded to `http://localhost:8000`
- **UI components**: shadcn-svelte components live in `lib/components/ui/`
- **Path alias**: `$lib` → `src/lib`

### Database

- PostgreSQL on localhost:5432, database `runbook`, user `postgres`/`postgres`
- JSONB columns store graph data (Protocol.graph, Experiment.graph, UnitOpDefinition.param_schema)
- Seed scripts in `scripts/` — `seed_unit_ops.py` populates the UnitOp library

## Workflow & Conventions

- **TDD required**: Red-Green-Refactor cycle. Write failing tests before implementation. Target >80% coverage.
- **plan.md is source of truth**: Tasks tracked there. Mark `[ ]` → `[~]` → `[x]` with commit SHA. Attach git notes to task commits.
- **Tech stack changes**: Must update `tech-stack.md` before implementing.
- **Commit format**: `<type>(<scope>): <description>` — types: feat, fix, docs, style, refactor, test, chore
- **CI-aware commands**: Use `CI=true` prefix for watch-mode tools to ensure single execution.

## Code Style

- **Python**: Google style — `snake_case`, 80-char lines, type annotations on public APIs, `"""triple-quote"""` docstrings with Args/Returns/Raises. Formatted with `black` + `isort`.
- **TypeScript**: Google style — `const`/`let` only (no `var`), named exports (no default exports), `lowerCamelCase` for variables/functions, `UpperCamelCase` for types/classes, avoid `any` (prefer `unknown`), explicit semicolons, single quotes, triple-equals.
