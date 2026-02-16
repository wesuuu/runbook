# Runbook Development Plan

## Phase 1: Project Initialization
- [x] Initialize project structure (backend, frontend directories)
- [x] Configure `alembic.ini` and `pyproject.toml`
- [x] Setup SvelteKit project skeleton
- [x] Configure TailwindCSS with "Scientific Precision" theme (Slate/Teal)
- [x] Setup Gitignore

## Phase 2: Backend Core Setup
- [x] Create Python 3.13 virtual environment (`.venv`)
- [x] Initialize FastAPI app structure (main.py, config, standard routes)
- [x] Setup Async SQLAlchemy with local PostgreSQL connection
- [x] Top-Level Base Models (`Base`, `UUIDMixin`, `TimestampMixin`)
- [x] Implement IAM Models (`Organization`, `Team`, `User`, `TeamMember`)
- [x] Implement Scientific Models (`Project`, `Experiment`)
- [x] Implement Process Models (`Protocol`, `UnitOp`)
- [x] Implement Execution Models (`RunSheet`, `AuditLog`)
- [x] Generate Initial Alembic Migration (`alembic revision --autogenerate`)
- [x] Apply Migrations (`alembic upgrade head`)

## Phase 3: Frontend Re-Initialization (SPA)
- [x] Remove SvelteKit `frontend` directory
- [x] Initialize Vite + Svelte 5 + TypeScript project (`npm create vite@latest frontend -- --template svelte-ts`)
- [x] Setup Client-side Routing (e.g. `wouter` installed)
- [x] Re-configure TailwindCSS with "Scientific Precision" theme
- [x] Create basic App Shell (Layout, Navigation)

## Phase 4: Core Features - Graph & AI
- [x] **Infrastructure**: Create `AuditLogger` service
- [x] **Backend**: Implement `Project` CRUD endpoints with Audit Logging
- [x] **Frontend**: Create `api.ts` client wrapper
- [x] **Frontend**: Implement `Projects` list page
- [x] **Frontend**: Implement `ProjectDetail` create/edit form
## Phase 5: Experiments & Graph Engine
- [ ] **Infrastructure**: Install `@xyflow/svelte` and configure SvelteFlow
- [ ] **Backend**: Create `UnitOpDefinition`, `Protocol`, `Experiment` models
- [ ] **Backend**: Implement `UnitOp` seeder (default library of ops)
- [ ] **Backend**: Implement CRUD for `Protocols` and `Experiments`
- [ ] **Frontend**: Create `ProtocolEditor` (Canvas + Sidebar)
- [ ] **Frontend**: Create `ExperimentRunner` (Status view + Data Entry)
- [ ] **Verification**: E2E test of creating a protocol and running an experiment

## Phase 5: MVP UI & Voice
- [ ] Implement "Run Sheet" view component
- [ ] Add Voice Command interface (Web Speech API) basic integration
- [ ] Polish UI for Tablet usage
