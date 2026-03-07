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

## Phase 6: AI Image Capture & Data Extraction

### Phase 6a: AI Configuration Layer (DB-persisted, runtime-configurable) ✅
- [x] **Backend**: Add `AiProviderConfig` model to `models/ai.py`
  - Table: `ai_provider_configs`
  - Fields: id (UUID), capability (str, unique — "vision"/"audio"/"text"), provider (str — "ollama"/"anthropic"/"google"/"openai"), model_name (str), api_key (str, nullable), base_url (str, nullable — for self-hosted Ollama etc.), is_enabled (bool), created_at, updated_at
  - One row per capability. Adding a new capability = inserting a row, no code changes.
  - API keys stored plaintext v1 (TODO: encrypt at rest). GET responses mask keys.
- [x] **Backend**: Add bootstrap env var fallbacks to `core/config.py`
  - `image_storage_path: str = "./uploads/images"` — where images go on disk
  - Env vars (`RUNBOOK_AI_VISION_PROVIDER`, etc.) only used for initial seed/fallback before DB is configured
- [x] **Backend**: Create `services/ai_config.py` — model factory
  - `get_model(capability: str) -> str` returns pydantic-ai model identifier
  - Resolution order: DB row -> env var fallback -> hardcoded default
  - In-memory cache with 30s TTL, invalidated on settings update
  - Validates provider/key combinations (cloud providers require API key)
- [x] **Backend**: Create `api/endpoints/ai.py` settings endpoints
  - `GET  /ai/settings` — list all capability configs (keys masked)
  - `PUT  /ai/settings/{capability}` — create or update a capability config (invalidates cache)
  - `POST /ai/settings/{capability}/test` — test connectivity to the configured provider
- [x] **Backend**: Generate Alembic migration for `ai_provider_configs` table
- [ ] **Backend**: Add seed/bootstrap logic — insert default rows on first startup if table is empty
- [ ] **Frontend**: Create AI Settings page (admin-only)
  - Card per capability (vision, audio, text)
  - Provider dropdown, model name input, API key input (masked), base URL input
  - Enable/disable toggle per capability
  - "Test Connection" button per capability
  - Save persists to DB via PUT, no backend restart needed
- [x] **Test**: `tests/unit/test_ai_config.py` — 16 unit tests (model factory, masking, cache, resolution)
- [x] **Test**: `tests/integration/test_ai_settings_api.py` — 16 integration tests (CRUD, validation, cache)

### Phase 6b: Image Upload & Storage Infrastructure ✅
- [x] **Backend**: Add `RunImage` model to `models/ai.py`
  - Fields: id, run_id (FK), step_id, file_path, original_filename, mime_type, file_size_bytes, uploaded_by_id (FK), created_at, updated_at
  - Images stored at configurable path (default: `./uploads/images/{run_id}/{step_id}/{uuid}.ext`)
  - Retention: permanent (no auto-cleanup)
- [x] **Backend**: Add `ImageConversation` model to `models/ai.py`
- [x] **Backend**: Create Pydantic schemas in `schemas/ai.py`
- [x] **Backend**: Generate and apply Alembic migration for run_images + image_conversations tables
- [x] **Backend**: Mount static file serving for `/uploads/images/` in main.py
- [x] **Frontend**: Add `uploadFile()` multipart helper to `lib/api.ts`
- [x] **Test**: `tests/integration/test_ai_image_upload.py` — 14 integration tests (upload, validation, list, get)
- [x] **Test fixtures**: `test_run`, `tmp_image_storage`, `TINY_JPEG` in test files

### Phase 6c: AI Vision Service ✅
- [x] **Backend**: Create `services/ai_vision.py` — pydantic-ai vision agent
  - Structured output: ExtractedValue (field_key, field_label, value, unit, confidence)
  - System prompt receives step's paramSchema so AI knows what fields to extract
  - Multi-turn: full conversation history replayed each call (stateless backend)
  - `analyze_image(image_path, step_name, param_schema) -> AnalysisResponse`
  - `continue_conversation(messages, image_path, param_schema) -> AnalysisResponse`
  - `model_override` parameter for testing with `TestModel(custom_output_args=...)`
- [x] **Test**: `tests/unit/test_ai_vision.py` — 27 unit tests (prompts, helpers, agent, analyze, converse, validation)

### Phase 6d: API Router
- [ ] **Backend**: Create image + conversation endpoints in `api/endpoints/ai.py`
  - `POST /ai/runs/{run_id}/steps/{step_id}/images` — upload image (multipart)
  - `GET  /ai/runs/{run_id}/images` — list all images for a run
  - `GET  /ai/runs/{run_id}/images/{image_id}` — single image metadata + conversation
  - `POST /ai/runs/{run_id}/images/{image_id}/analyze` — initial AI analysis
  - `POST /ai/runs/{run_id}/images/{image_id}/converse` — multi-turn follow-up
  - `POST /ai/runs/{run_id}/images/{image_id}/confirm` — accept values, write to execution_data
- [ ] **Backend**: Register router in main.py
- [ ] **Backend**: Add audit logging for IMAGE_CAPTURE and IMAGE_CONFIRM events
- [ ] **Test**: `tests/integration/test_ai_api.py` — full flow integration tests
  - **Happy path (end-to-end)**: upload image -> analyze (mocked AI) -> converse -> confirm -> verify execution_data updated
  - Analyze returns AI extraction with correct field mappings from paramSchema
  - Converse appends user message, returns updated AI response
  - Confirm writes extracted values into `run.execution_data[step_id].results`
  - Confirm sets conversation status to "confirmed"
  - Confirm creates IMAGE_CONFIRM audit log with image_id, extracted values, actor_id
  - Upload creates IMAGE_CAPTURE audit log
  - Analyze on non-existent image returns 404
  - Converse on image with no conversation yet returns 404
  - Confirm with empty extracted_values returns 422
  - Run must be ACTIVE to upload/analyze (PLANNED/COMPLETED returns 409)
  - **AI mock fixture**: Override the vision agent dependency so no real AI calls in tests

### Phase 6e: Frontend Integration
- [x] **Frontend**: Add camera capture button to `RoleWizard.svelte`
  - `<input type="file" accept="image/*" capture="environment">` (camera on mobile, file picker on desktop)
  - Upload on capture, auto-trigger analysis
- [x] **Frontend**: Create `ImageAnalysisDialog.svelte`
  - Chat-style multi-turn conversation with AI
  - Shows image thumbnail + AI extracted values with confidence
  - Per-value: Confirm / Edit / Reject actions
  - Text input for user replies to AI clarifying questions
  - On confirm: POST /confirm, populate RoleWizard form fields
- [x] **Frontend**: Create `ImageGallery.svelte` — step image thumbnails (audit trail)
- [ ] **Test**: Manual QA checklist (no frontend test framework currently)
  - Camera capture opens camera on iPad/phone, file picker on desktop
  - Image preview renders after capture
  - Loading state shown during AI analysis
  - AI response displays extracted values with labels/units
  - Multi-turn: user can type reply, AI updates extraction
  - Confirm populates correct RoleWizard form fields
  - Image thumbnail appears in step gallery after upload
  - Error state shown if AI analysis fails
  - Dialog dismissable without confirming (no data written)

## Phase 7: MVP UI & Voice
- [ ] Implement "Run Sheet" view component
- [ ] Add Voice Command interface (Web Speech API) basic integration
- [ ] Polish UI for Tablet usage


## Future Considerations

- Offline/PWA: Service worker + IndexedDB queue for image capture when disconnected, batch sync on reconnect
- Batch image processing: Upload multiple images, analyze sequentially
- OCR preprocessing: Run Tesseract locally before sending to vision model for better accuracy
- Image annotations: Let users draw bounding boxes to guide the AI
- result_schema cleanup: Consider whether to remove the unused result_schema field or repurpose it
- AI capability expansion: embedding models for semantic search, coding models for protocol generation