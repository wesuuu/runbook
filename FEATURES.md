# Feature Backlog

Planned features for the Runbook AI Co-Pilot. Each entry is a specification that can be picked up for implementation.

---

### [F-0010] Export Pipeline Improvements
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Source**: GAP-002
- **Description**: Export works (multi-run, multi-format, column selection, preview grid) but it's one-shot: scientists reconfigure every time, can't copy to clipboard, and output formatting may need cleanup before Prism/SAS can use it. Since export-to-analysis-tools is the core value proposition, this pipeline must be frictionless.
- **Acceptance Criteria**:
  - [ ] **Export presets**: Users can save named export configurations (column selection, format, layout) per project
  - [ ] Presets stored in project settings JSONB or a new `export_presets` table
  - [ ] Preset picker dropdown on the export page — select a preset to auto-populate settings
  - [ ] "Save as Preset" button after configuring export options, with name input
  - [ ] "Delete Preset" option on saved presets
  - [ ] **Clipboard copy**: "Copy to Clipboard" button on the export preview — copies tab-separated values for direct paste into Excel/Prism
  - [ ] Clipboard copy shows a brief toast confirmation ("Copied N rows to clipboard")
  - [ ] **Last-used memory**: Export page remembers last-used settings per user (stored in localStorage or user preferences)
  - [ ] **Prism-friendly format**: Optional "Prism Layout" preset that outputs parameter-per-column with run labels as row headers
  - [ ] **SAS-friendly format**: Optional "SAS Layout" preset that outputs long/normalized format with proper column naming (no spaces, uppercase)
- **Implementation Notes**:
  - **Backend**: Add `export_presets` JSONB field to Project model (or a separate table). CRUD endpoints: `POST /projects/{id}/export-presets`, `GET /projects/{id}/export-presets`, `DELETE /projects/{id}/export-presets/{preset_id}`
  - **Frontend export page** (`frontend/src/routes/export/+page.svelte`): Add preset dropdown, save/delete buttons, clipboard copy button. Use `navigator.clipboard.writeText()` for copy
  - **Tab-separated copy**: Convert preview grid data to TSV string with headers
  - **localStorage**: Store `lastExportSettings` keyed by user ID
- **Dependencies**: None

### [F-0011] Full-Text Search Across Entities
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Source**: GAP-003
- **Description**: Only basic name filtering exists on list pages. No global search across protocols, runs, audit entries, or graph content. Scientists accumulate protocols and runs quickly and need to find things — "which runs used pH above 7.0" or "find all protocols mentioning centrifugation." Critical once users have 20+ protocols.
- **Acceptance Criteria**:
  - [ ] PostgreSQL full-text search (tsvector/tsquery) enabled on Protocol.name, Protocol.description, Run.name, Project.name, Project.description
  - [ ] JSONB graph content indexed: node labels and parameter values extracted into a tsvector column
  - [ ] `GET /search?q=...` global search endpoint returns results across protocols, runs, and projects
  - [ ] Results are faceted by entity type (protocols, runs, projects) with counts per facet
  - [ ] Results include relevance ranking (ts_rank) and highlighted snippets (ts_headline)
  - [ ] Global search bar in the app header (visible on all pages)
  - [ ] Search results page with tabs for each entity type and click-through to detail pages
  - [ ] Search is debounced (300ms) with instant results as user types
  - [ ] Empty state with helpful text when no results found
  - [ ] Search respects user permissions — only returns entities the user has VIEW access to
- **Implementation Notes**:
  - **Migration**: Add `search_vector` tsvector column to protocols, runs, projects tables. Create GIN index. Add trigger to auto-update on INSERT/UPDATE
  - **JSONB indexing**: Create a database function that extracts node labels and param values from graph JSONB into text for tsvector
  - **Backend endpoint** (`backend/app/api/endpoints/search.py`): New router with `GET /search` accepting `q`, `entity_type` (optional filter), `limit`, `offset`. Query each table's search_vector, union results, rank and paginate
  - **Frontend**: Add search input to nav bar (`+layout.svelte`). New `/search` route with results page. Use debounced fetch on input
- **Dependencies**: None

### [F-0012] Commenting & Annotation System
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Source**: GAP-004
- **Description**: No commenting anywhere in the app. Scientists cannot leave notes, ask questions, or flag issues on protocols, runs, or steps. All discussion happens outside the app (email, Slack), losing context. Research is collaborative — PD teams discuss protocols, flag observations during runs, and document decisions. Comments are where institutional knowledge lives.
- **Acceptance Criteria**:
  - [ ] `Comment` model: `id`, `entity_type` (protocol/run/step/image), `entity_id`, `parent_id` (for threading), `author_id`, `body` (text), `mentions` (JSONB array of user IDs), `created_at`, `updated_at`
  - [ ] API endpoints: `POST /comments`, `GET /comments?entity_type=...&entity_id=...`, `PUT /comments/{id}`, `DELETE /comments/{id}`
  - [ ] Comments are paginated (default 20 per page) with newest-first ordering
  - [ ] Threaded replies: comments can have a `parent_id` pointing to another comment, displayed as nested threads
  - [ ] Comment panel/sidebar on protocol editor (comments on the protocol)
  - [ ] Comment section on run detail page (comments on the run, and per-step comments)
  - [ ] @mention autocomplete: typing `@` in comment body shows a dropdown of project members to mention
  - [ ] Mentioned users receive a notification (`COMMENT_MENTION` event type)
  - [ ] Comment authors can edit and delete their own comments
  - [ ] Comment count badge shown on entities that have comments
  - [ ] Markdown support in comment body (bold, italic, code, links)
- **Implementation Notes**:
  - **Backend model** (`backend/app/models/comments.py`): New `Comment` model with polymorphic entity reference (`entity_type` + `entity_id`). Self-referential FK for `parent_id`
  - **Backend endpoints** (`backend/app/api/endpoints/comments.py`): New router. Permission check: user must have VIEW on the parent entity to read comments, EDIT to create/modify
  - **Notification integration**: Add `COMMENT_ADDED` and `COMMENT_MENTION` to notification event types. Trigger on comment creation
  - **Frontend component**: Create `CommentPanel.svelte` — reusable comment list + input. Embed in protocol editor sidebar and run detail page
  - **@mention**: Frontend autocomplete component that queries project members. Backend parses mentions from body text and populates the `mentions` JSONB field
- **Dependencies**: None

### [F-0014] Instrument Data Import (CSV/Excel)
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Source**: GAP-006
- **Description**: All parameter data enters via manual entry or AI image analysis. No file import capability. Plate readers, chromatography systems, and spectrophotometers all export CSV/Excel. Scientists must manually transcribe values — tedious and error-prone. CSV import eliminates manual entry errors and saves significant time per run.
- **Acceptance Criteria**:
  - [ ] "Import Data" button on run step parameter forms in `RoleWizard.svelte`
  - [ ] Accepts CSV and Excel (.xlsx) file uploads
  - [ ] Column mapping UI: after upload, user sees a preview of the file's columns and maps each CSV column to a step parameter
  - [ ] Auto-mapping suggestion: if CSV column headers match parameter names (case-insensitive), pre-select the mapping
  - [ ] Preview of mapped values before confirming import
  - [ ] Backend endpoint: `POST /runs/{id}/steps/{step_id}/import` accepts file + column mapping, returns parsed values
  - [ ] Imported values populate the parameter form fields (user can review and edit before saving the step)
  - [ ] Support for multi-row imports: if CSV has multiple rows, user selects which row to import (or imports as a batch for multi-sample steps)
  - [ ] Error handling: show clear messages for malformed files, missing columns, or type mismatches
  - [ ] Import history: log which file was imported for audit trail
- **Implementation Notes**:
  - **Backend**: Add `POST /runs/{id}/steps/{step_id}/import` endpoint in `science.py`. Use `pandas` or `openpyxl` for parsing. Accept multipart file upload + JSON body with column mapping
  - **Frontend component**: Create `DataImportDialog.svelte` — file drop zone, column preview table, mapping dropdowns (CSV column → parameter name), value preview, confirm button
  - **Integration**: Add "Import" button next to parameter fields in `RoleWizard.svelte`. On click, open `DataImportDialog`. On confirm, populate form fields with imported values
  - **Audit**: Log import action to audit trail with filename, timestamp, and mapped columns
- **Dependencies**: None

### [F-0015] Site Walkthrough & Guided Onboarding Tour
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Frontend
- **Source**: GAP-007
- **Description**: No first-run experience. New users land on the dashboard with no guidance — no tutorial, no tooltips on complex features, no walkthrough for first protocol creation. With a 30-day trial model, first impressions determine conversion. This feature adds a polished, multi-page guided tour using **Driver.js** (MIT license, ~5KB gzipped, 25k GitHub stars, framework-agnostic) that spotlights key UI elements with smooth CSS-animated transitions. The tour should feel native and slick — not like a clunky overlay from 2015.
- **Acceptance Criteria**:
  - **First-Run Detection & State:**
    - [ ] Track `has_completed_onboarding` flag in user preferences (localStorage + backend `user_preferences` JSONB)
    - [ ] On first login after registration, automatically launch the tour
    - [ ] Cross-device consistency: onboarding state synced to backend so completing on tablet doesn't re-trigger on desktop
  - **Main Site Tour (post-registration):**
    - [ ] Tour sequence: Dashboard overview → Projects list → Create Project → Protocol Editor basics → Run creation → Export page
    - [ ] Each step uses Driver.js spotlight: animated highlight around the target element with a popover (title, description, step counter, next/prev/skip)
    - [ ] Smooth animated transitions between steps (Driver.js CSS transitions between highlighted elements)
    - [ ] Progress indicator showing current step / total steps
    - [ ] "Skip Tour" button visible at every step — exits gracefully and marks onboarding as complete
    - [ ] "Back" button to revisit previous steps
    - [ ] Tour adapts to viewport: mobile/tablet steps may differ from desktop (e.g., skip sidebar steps on mobile, highlight hamburger menu instead)
  - **Protocol Editor Tour (context-specific):**
    - [ ] Triggered on first visit to the protocol editor (separate `has_completed_editor_tour` flag)
    - [ ] Steps: Unit Op sidebar (drag to canvas) → Canvas area (zoom/pan) → Node selection (click to inspect) → Inspector panel (edit parameters) → Swim lanes (role containers) → Handle orientation toggle → Save/Publish buttons → Version history
    - [ ] Highlights actual DOM elements with working interactions — user can try dragging a unit op during the tour step
  - **Experiment Runner Tour (context-specific):**
    - [ ] Triggered on first visit to a run page (separate `has_completed_runner_tour` flag)
    - [ ] Steps: Role assignment → Start run → Step navigation → Parameter entry → Image capture → Complete step → Run completion
  - **Replay & Settings:**
    - [ ] "Restart Tour" button in Settings → Profile tab
    - [ ] Individual tour resets: "Replay Site Tour", "Replay Editor Tour", "Replay Runner Tour"
    - [ ] Help icon (?) in the app header that offers tour replay + links to documentation
  - **Contextual Tooltips (non-tour):**
    - [ ] Pulsing hint dots on non-obvious features (handle orientation toggle, time axis, swimlane resize handles) that appear until the user interacts with them
    - [ ] Tooltip dismissed permanently after first interaction (stored in localStorage)
  - **Sample Content for New Orgs:**
    - [ ] Pre-loaded "Example Cell Culture Protocol" with 5-6 connected nodes, swim lanes, and filled parameters — lets new users explore a populated editor immediately
    - [ ] Sample project with the example protocol so the dashboard isn't empty on first login
  - **Empty State CTAs:**
    - [ ] Project detail with no protocols: "Create your first protocol" card with illustration and CTA button
    - [ ] Project with no runs: "Start your first experiment" card
    - [ ] Dashboard with no activity: welcoming message with quick-start actions
- **Implementation Notes**:
  - **Library**: Install `driver.js` via npm. MIT license — no commercial restrictions (unlike Shepherd.js and Intro.js which are AGPL-3.0 and require a commercial license for non-open-source use). ~5KB gzipped, zero dependencies, TypeScript-first. Works with plain DOM selectors — integrates cleanly with Svelte 5 without needing a framework wrapper. See https://driverjs.com
  - **Tour definition files**: Create `frontend/src/lib/tours/` directory with separate tour configs:
    - `siteTour.ts` — main walkthrough steps (dashboard, projects, nav)
    - `editorTour.ts` — protocol editor steps (sidebar, canvas, inspector, swimlanes)
    - `runnerTour.ts` — experiment runner steps (roles, steps, image capture)
    - Each exports an array of `DriveStep` objects: `{ element: '#selector', popover: { title, description, side, align } }`
  - **Tour manager component**: Create `frontend/src/lib/components/TourManager.svelte`:
    - Initializes `driver()` instance with custom theme/styling on mount
    - Checks tour completion state via `shouldShowTour(tourName)` utility
    - Exposes `startTour(tourName)` via Svelte `setContext` so child pages can trigger tours
    - Handles Driver.js callbacks (`onHighlightStarted`, `onDeselected`, `onDestroyed`) for state tracking
    - Custom CSS overrides for Driver.js popover to match shadcn-svelte design system
  - **Driver.js CSS customization**: Override default popover styles to match the app aesthetic:
    ```css
    .driver-popover { border-radius: 0.75rem; box-shadow: 0 25px 50px -12px rgb(0 0 0 / 0.25); }
    .driver-popover-title { font-size: 1.125rem; font-weight: 600; }
    .driver-popover-description { font-size: 0.875rem; color: var(--muted-foreground); }
    ```
  - **Tour state management**: Store completion flags in localStorage (`tour_site_completed`, `tour_editor_completed`, `tour_runner_completed`) and sync to backend `user_preferences` JSONB on the User model
  - **Context-specific triggering**: Mount `TourManager.svelte` in `+layout.svelte`. Protocol editor and run pages check completion flags in `onMount` and call `startTour()` via context
  - **Hint dots component**: Create `HintDot.svelte` — pulsing CSS animation positioned relative to parent, accepts `hintKey` prop, checks localStorage, dismisses on first interaction
  - **Sample protocol seed**: Create `scripts/seed_sample_protocol.py` to generate a demo project + protocol with pre-built graph (nodes, edges, swim lanes) for new orgs
  - **Empty states**: Update project detail page (`/projects/[id]/+page.svelte`) protocol/run tabs and dashboard (`/+page.svelte`) with illustrated empty state cards
  - **Responsive tours**: Use `window.innerWidth` to select step variants — mobile tours highlight `.mobile-nav-trigger` instead of desktop sidebar selectors
  - **Library alternatives considered**: Shepherd.js (13k stars, feature-rich but AGPL license — requires commercial license), Intro.js (24k stars but also AGPL, slower animations), OnboardJS (headless/new — too immature). Driver.js won on license, bundle size, animation quality, and Svelte compatibility
- **Dependencies**: None

### [F-0016] Cloud Storage for Images (S3-Compatible)
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Backend
- **Source**: GAP-010
- **Description**: Images are stored on local disk. This works for development but won't scale for SaaS deployment — data loss risk, no CDN, complicated backups, and multi-server deployments can't share a filesystem. For production SaaS, images need to live in cloud storage (S3, Cloudflare R2, or similar).
- **Acceptance Criteria**:
  - [ ] File storage abstracted behind an interface: `FileStorage` protocol with `upload(key, data) -> url`, `download(key) -> bytes`, `delete(key)`, `get_url(key) -> str`
  - [ ] Two implementations: `LocalFileStorage` (current behavior, for development) and `S3FileStorage` (production)
  - [ ] Storage backend selected via environment variable (`FILE_STORAGE_BACKEND=local|s3`)
  - [ ] S3 configuration via env vars: `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT_URL` (for R2/MinIO compatibility)
  - [ ] Presigned URLs for direct browser upload (bypasses backend for large files) and download
  - [ ] Existing image upload endpoints (`POST /ai/runs/{id}/images`) use the storage abstraction transparently
  - [ ] Image serving endpoint returns presigned URL redirect for S3 backend, or serves file directly for local backend
  - [ ] Migration path: management command to migrate existing local files to S3
  - [ ] Offline mode image uploads: queue locally, upload to S3 on sync (via existing sync endpoint)
- **Implementation Notes**:
  - **Storage abstraction**: Create `backend/app/services/file_storage.py` with `FileStorage` Protocol and `LocalFileStorage` / `S3FileStorage` implementations
  - **S3 client**: Use `boto3` (or `aioboto3` for async). Compatible with AWS S3, Cloudflare R2, MinIO, DigitalOcean Spaces
  - **Presigned URLs**: Generate upload URLs with `generate_presigned_url('put_object', ...)` and download URLs with `generate_presigned_url('get_object', ...)`
  - **Config**: Add storage settings to `backend/app/core/config.py`. Default to `local` for development
  - **Migration script**: `scripts/migrate_images_to_s3.py` — reads all `RunImage` records, uploads files from local disk to S3, updates paths
  - **Dependency injection**: Register storage service in FastAPI dependency injection, inject into image endpoints
- **Dependencies**: None

### [F-0003] Batch Image Processing
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: Allow users to upload multiple images at once for a run step and have them analyzed sequentially by the AI vision model. Currently only single-image upload and analysis is supported. Batch processing saves time when capturing multiple instrument readings.
- **Acceptance Criteria**:
  - [ ] Camera/file input in `RoleWizard.svelte` accepts `multiple` attribute for selecting several images at once
  - [ ] Backend `POST /ai/runs/{run_id}/steps/{step_id}/images` accepts multiple files in a single request (or frontend sends them sequentially)
  - [ ] New endpoint `POST /ai/runs/{run_id}/steps/{step_id}/analyze-batch` triggers analysis on all unanalyzed images for that step
  - [ ] Images are analyzed sequentially (not concurrently) to avoid overloading the AI provider
  - [ ] Progress is reported to the frontend (e.g., "Analyzing image 2 of 5")
  - [ ] Each image gets its own `ImageConversation` with independent extracted values
  - [ ] Users can review and confirm/reject each image's results individually in `ImageAnalysisDialog.svelte`
  - [ ] If one image analysis fails, remaining images continue processing
- **Implementation Notes**:
  - **Backend endpoint** (`backend/app/api/endpoints/ai.py`): Add `analyze-batch` endpoint that iterates over `RunImage` records for the step, calling `ai_vision.analyze_image()` for each.
  - **Frontend upload** (`RoleWizard.svelte`): Change file input to `multiple`, loop over `FileList` and upload each via existing endpoint.
  - **Frontend dialog** (`ImageAnalysisDialog.svelte`): Add batch mode — navigation between images (prev/next), per-image confirm/reject, summary view of all results.
  - **Image gallery** (`ImageGallery.svelte`): Show analysis status per image (pending, analyzing, confirmed, failed).
- **Dependencies**: None

### [F-0004] OCR Preprocessing with Tesseract
- **Status**: Proposed
- **Priority**: P3 (Low)
- **Scope**: Backend
- **Description**: Run Tesseract OCR locally on uploaded images before sending them to the AI vision model. The OCR text is included in the AI prompt as supplemental context, improving accuracy for instrument displays with small text, numeric readouts, and standard labels. This is a preprocessing step, not a replacement for AI vision.
- **Acceptance Criteria**:
  - [ ] `pytesseract` added as a backend dependency with Tesseract binary available in the deployment environment
  - [ ] OCR runs automatically when an image is uploaded (async, non-blocking)
  - [ ] Extracted OCR text is stored on the `RunImage` record (new `ocr_text` column)
  - [ ] When `analyze_image()` is called, OCR text is appended to the system prompt as context (e.g., "OCR detected the following text in the image: ...")
  - [ ] OCR failure does not block image analysis — gracefully falls back to vision-only
  - [ ] OCR text is visible in the frontend image detail view for transparency
  - [ ] Configurable toggle to enable/disable OCR preprocessing (per-org or global setting)
- **Implementation Notes**:
  - **Dependency**: Add `pytesseract` to `backend/pyproject.toml`. Require `tesseract-ocr` system package.
  - **Model** (`backend/app/models/ai.py`): Add `ocr_text: Mapped[Optional[str]]` to `RunImage`.
  - **OCR service**: Create `backend/app/services/ocr.py` — `async def extract_text(image_path: str) -> str` using `pytesseract.image_to_string()` in a thread executor.
  - **Vision service** (`backend/app/services/ai_vision.py`): In `analyze_image()`, prepend OCR text to the system prompt when available.
  - **Upload endpoint** (`backend/app/api/endpoints/ai.py`): After saving image, trigger OCR as background task.
  - **Migration**: Add `ocr_text` nullable text column to `run_images`.
- **Dependencies**: None

### [F-0005] Image Annotations for AI Guidance
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: Let users draw bounding boxes (and optionally labels) on captured images before sending them to the AI vision model. Annotations are included in the prompt to tell the AI which regions of the image to focus on, improving extraction accuracy for complex instrument panels with multiple readings.
- **Acceptance Criteria**:
  - [ ] Annotation canvas overlay on image in `ImageAnalysisDialog.svelte` (or a new `ImageAnnotator.svelte` component)
  - [ ] Users can draw rectangular bounding boxes on the image
  - [ ] Each bounding box can have an optional text label (e.g., "pH reading", "temperature")
  - [ ] Annotations are stored as JSON on the `ImageConversation` or `RunImage` record (`annotations` JSONB column)
  - [ ] Annotation data format: `[{x, y, width, height, label?}]` as percentages of image dimensions
  - [ ] When analysis is triggered, annotations are described in the AI prompt (e.g., "The user has highlighted a region at [coordinates] labeled 'pH reading' — extract the value from this region")
  - [ ] Users can clear or redo annotations before submitting
  - [ ] Annotations are displayed as overlays when reviewing past analysis results
- **Implementation Notes**:
  - **Frontend component**: Create `frontend/src/lib/components/ImageAnnotator.svelte` — HTML5 Canvas overlay on the image, mouse/touch drag to draw rectangles, click to add labels. Use percentage-based coordinates for resolution independence.
  - **Integration**: Embed in `ImageAnalysisDialog.svelte` before the "Analyze" button. Pass annotations array to the analyze API call.
  - **Backend model** (`backend/app/models/ai.py`): Add `annotations: Mapped[Optional[dict]]` JSONB column to `RunImage` or pass as request body to the analyze endpoint.
  - **Vision service** (`backend/app/services/ai_vision.py`): Convert annotation coordinates to natural language descriptions in the system prompt.
  - **Migration**: Add `annotations` JSONB column if storing on the model.
- **Dependencies**: None

### [F-0006] result_schema Cleanup & Repurposing
- **Status**: Proposed
- **Priority**: P3 (Low)
- **Scope**: Backend
- **Description**: The `result_schema` field on `UnitOpDefinition` (added in migration `a62961cc6422`) exists as a JSONB column but is not actively used in any workflow. Decide whether to repurpose it as a validation schema for AI-extracted values (complementing `param_schema` which defines inputs), or remove it to reduce confusion. If repurposed, it should validate the output of image analysis before values are confirmed and written to `execution_data`.
- **Acceptance Criteria**:
  - [ ] Decision documented: repurpose as output validation schema OR remove the field
  - **If repurposed:**
    - [ ] `result_schema` defines expected output fields (name, type, unit, range) for a unit op's measurable results
    - [ ] Vision service validates `extracted_values` against `result_schema` before allowing confirmation
    - [ ] Validation errors are surfaced in `ImageAnalysisDialog.svelte` (e.g., "pH value 14.5 is outside expected range 0-14")
    - [ ] Seed script (`scripts/seed_unit_ops.py`) updated with result schemas for existing unit ops
  - **If removed:**
    - [ ] Column dropped via Alembic migration
    - [ ] Field removed from `UnitOpDefinitionBase` and `UnitOpDefinitionUpdate` schemas
    - [ ] Any references in endpoints cleaned up
- **Implementation Notes**:
  - **Current location**: `backend/app/models/science.py` line ~159 (`result_schema` JSONB on `UnitOpDefinition`), `backend/app/schemas/science.py` (`UnitOpDefinitionBase`, `UnitOpDefinitionUpdate`).
  - **If repurposing**: Add validation in `backend/app/services/ai_vision.py` or in the confirm endpoint (`backend/app/api/endpoints/ai.py` `confirm_image_values`). Use JSON Schema validation (`jsonschema` package) to check extracted values match the result_schema.
  - **If removing**: Generate Alembic migration to drop the column, remove from model/schemas/endpoints.
- **Dependencies**: None

### [F-0007] AI Chat Assistant
- **Status**: In Progress
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: A conversational AI assistant for biotech PD scientists. Users can chat with the AI to ask domain questions (cell biology, genetics, purification), discuss documents from the library (RAG), and generate protocols from conversations or library documents. Built in three phases: (1) Chat engine + UI, (2) RAG integration with document library, (3) Protocol generation from chat.
- **Acceptance Criteria**:
  - **Phase 1 — Chat Engine + UI:**
    - [x] New `chat` capability added to `SUPPORTED_CAPABILITIES` in `backend/app/models/ai.py`
    - [x] `ChatSession` and `ChatMessage` models with CRUD persistence
    - [x] `POST /chat/sessions` creates a new chat session
    - [x] `GET /chat/sessions` lists user's chat sessions (paginated)
    - [x] `GET /chat/sessions/{id}` returns session with full message history
    - [x] `PATCH /chat/sessions/{id}` renames a session
    - [x] `DELETE /chat/sessions/{id}` deletes a session
    - [x] `POST /chat/sessions/{id}/messages` sends a user message and returns AI response
    - [x] Auto-title: session title updates to first message content
    - [x] Multi-turn conversation: message history passed as context to LLM
    - [x] Context window management: truncate to last 50 messages
    - [x] Frontend `/chat` page with session sidebar + message area
    - [x] Optimistic UI: user message appears instantly while AI responds
    - [x] Markdown rendering in AI responses
    - [x] Nav link in desktop and mobile navigation
    - [x] System prompt tailored for biotech PD domain expertise
  - **Phase 2 — RAG Integration with Document Library:**
    - [x] Every user message triggers hybrid search (semantic + keyword) across all org documents
    - [x] Top-K relevant chunks (up to 8, max ~12K chars) injected into system prompt as numbered context
    - [x] Minimum relevance threshold (0.3) filters out irrelevant chunks
    - [x] System prompt instructs LLM to cite sources with inline footnotes [1], [2], etc.
    - [x] Sources returned in API response (`ChatCompletionResponse.sources`)
    - [x] Sources persisted in assistant message `metadata_` for history replay
    - [x] Frontend sources panel (right sidebar) shows document title, page, snippet, relevance score
    - [x] Source links navigate to `/library/{doc_id}?chunk={chunk_index}` for deep-linking
    - [x] Library detail page supports `?chunk=N` query param — auto-scrolls to chunk on load
    - [x] When org has no documents, system prompt explicitly tells AI there are none
    - [x] Clickable "N sources" button on assistant messages to show sources for any past message
    - [x] Graceful fallback: keyword-only search if embedding service unavailable
  - **Phase 3 — Protocol Generation from Chat:**
    - [ ] `POST /ai/chat/sessions/{id}/generate-protocol` generates protocol graph from conversation context
    - [ ] Unit op catalog included in system prompt for accurate mapping
    - [ ] Generated protocol saved as DRAFT with "AI-Generated" metadata
    - [ ] Frontend button in chat to trigger protocol generation
    - [ ] Refinement endpoint for iterative protocol editing via chat
- **Implementation Notes**:
  - **Phase 1 (Done)**: Backend: `models/chat.py`, `schemas/chat.py`, `services/chat_service.py`, `api/endpoints/chat.py`. Migration `4b2e86d86981`. Frontend: `/chat` route with session list + message UI. 29 backend tests (11 unit + 18 integration)
  - **Phase 2 (Done)**: RAG via `retrieve_relevant_chunks()` in `chat_service.py`. Reuses existing hybrid search (pgvector + tsvector). Sources panel in frontend. Deep-link support in library detail page. 7 new tests (5 unit + 2 integration). Total: 535 backend tests passing
  - **Phase 3**: Create `protocol_generator.py` service. Use pydantic-ai structured output. Frontend: generation wizard + refinement chat panel
- **Dependencies**: None (Phase 2 depends on Document Library which is already built)


### [F-0018] Text-to-Protocol Generation from Library
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Description**: Generate protocol graphs (nodes + edges) from natural language descriptions and/or uploaded library documents. Scientists can paste a text protocol from a paper, reference an SOP from the document library, or describe a workflow in plain English, and the system generates a draft protocol in the graph editor with appropriate unit operations, parameters, connections, and swim lanes. This bridges the gap between written procedures and the structured protocol editor — scientists shouldn't have to manually recreate protocols that already exist as text.
- **Acceptance Criteria**:
  - **Protocol Generation Engine:**
    - [ ] `POST /ai/generate-protocol` endpoint accepts: `description` (free text), optional `document_ids` (array of library document IDs to use as source), optional `project_id` (to create the protocol in)
    - [ ] System prompt includes the full `UnitOpDefinition` catalog (names, categories, param_schemas) so the LLM maps text steps to available unit ops
    - [ ] When `document_ids` are provided, relevant chunks are retrieved via RAG and included as context alongside the description
    - [ ] LLM returns structured output matching the protocol graph schema: `{nodes: [{id, type, position, data: {label, unitOpId, category, params, duration_min}}], edges: [{id, source, target}], layout, swimlanes: [{id, label, roleId}]}`
    - [ ] Generated protocol is saved as a new Protocol with `status: DRAFT` and `source: "ai_generated"` metadata
    - [ ] Auto-layout: generated nodes are positioned using a basic DAG layout algorithm (topological sort → layered positioning) so the graph is readable without manual rearrangement
    - [ ] Parameter pre-fill: where the source text specifies values (e.g., "incubate at 37°C for 2 hours"), those values are mapped to the unit op's param_schema fields
    - [ ] Generation includes a confidence/notes field per node explaining why that unit op was chosen
  - **Iterative Refinement:**
    - [ ] `POST /ai/refine-protocol` endpoint accepts a protocol ID + natural language feedback (e.g., "add a wash step between steps 3 and 4", "change the incubation time to 4 hours")
    - [ ] Refinement modifies the existing graph rather than regenerating from scratch
    - [ ] Conversation history maintained per generation session so the LLM has context of prior refinements
  - **Frontend UI:**
    - [ ] "Generate with AI" button on the new protocol creation page (alongside manual creation)
    - [ ] Generation wizard: Step 1 — input source (paste text / select library documents / type description). Step 2 — review generated protocol in a read-only graph preview. Step 3 — "Open in Editor" to begin manual refinement, or "Refine" to give feedback
    - [ ] Library document picker: searchable list of indexed documents from F-0017, multi-select with previews
    - [ ] Loading state with progress indication during generation (streaming status updates)
    - [ ] Generated protocol opens in the standard protocol editor with a banner: "AI-Generated Draft — Review and edit before use"
    - [ ] Refinement chat panel: sidebar in the protocol editor for ongoing AI conversation about the generated protocol
  - **Quality & Safety:**
    - [ ] Generated protocols are clearly marked as AI-generated in the UI and metadata
    - [ ] Audit log entry for each generation event (who triggered, what source, which document IDs)
    - [ ] Unit op matching validation: if the LLM references a unit op not in the catalog, it falls back to a generic "Custom Step" node with a warning
    - [ ] Parameter validation: generated param values are checked against param_schema constraints (type, min/max range)
- **Implementation Notes**:
  - **Generation service** (`backend/app/services/protocol_generator.py`): Core generation logic using `pydantic-ai` with structured output. System prompt includes: (1) unit op catalog as JSON, (2) protocol graph schema definition, (3) RAG context from library documents if provided. Uses the `text` or `coding` capability from AI config
  - **Graph layout** (`backend/app/services/graph_layout.py`): Simple layered DAG layout — topological sort nodes, assign layers, space evenly. Positions in the same format as @xyflow/svelte expects (`{x, y}`)
  - **Structured output schema**: Define a Pydantic model matching the protocol graph format. `pydantic-ai` will enforce the schema during generation. Include `confidence: float` and `reasoning: str` fields per node
  - **RAG integration**: When `document_ids` are provided, use the search service from F-0017 to retrieve relevant chunks. Concatenate into a context block with source citations. Limit context to ~8K tokens to leave room for the unit op catalog and generation instructions
  - **Refinement**: Store generation conversation in a new `ProtocolGenerationSession` model (or reuse the `ImageConversation` pattern). Each refinement appends to the conversation and returns an updated graph diff
  - **Frontend wizard** (`frontend/src/lib/components/ProtocolGenerationWizard.svelte`): Multi-step dialog. Step 1 uses a textarea + document picker (from F-0017's library UI). Step 2 renders a read-only `SvelteFlow` instance with the generated graph. Step 3 navigates to the protocol editor
  - **Protocol editor integration**: Add "Refine with AI" button to the protocol editor toolbar (only shown for AI-generated protocols). Opens a chat sidebar component similar to `ImageAnalysisDialog` conversation pattern
  - **API router**: Add `generate-protocol` and `refine-protocol` endpoints to `backend/app/api/endpoints/ai.py` (or a new `protocol_gen.py` router)
  - **Unit op catalog fetch**: `GET /science/unit-op-definitions` already exists — the generation service queries this internally to build the system prompt
- **Dependencies**: F-0017 (Document Library — required for the library document picker and RAG context retrieval. Can be built without F-0017 using paste/type input only, but library integration is the key differentiator)

### [F-0019] Payment Gateway & Billing System (Stripe)
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Description**: Add a subscription billing system using Stripe so organizations can subscribe to paid plans after a free trial. Stripe's **test mode** (with test API keys and test card numbers like `4242 4242 4242 4242`) enables full local development and testing without real payments or credit card entry. The implementation covers: plan management, Stripe Checkout for payment collection, subscription lifecycle (create/upgrade/downgrade/cancel), invoice history, and usage-based quota enforcement. The existing `OrgRole.BILLING` enum (already defined but unused) gates who can manage billing within an organization.
- **Acceptance Criteria**:
  - **Phase 1 — Backend Billing Infrastructure**
    - [ ] `RUNBOOK_STRIPE_SECRET_KEY` and `RUNBOOK_STRIPE_WEBHOOK_SECRET` added to `config.py` Settings; app boots without them (billing features disabled gracefully)
    - [ ] `Plan` enum or table defined with tiers: `FREE` (3 active runs, 1 project, 5 protocols), `STARTER` ($49/mo — 10 runs, 5 projects, unlimited protocols), `TEAM` ($149/mo — unlimited runs, unlimited projects, AI analysis), `ENTERPRISE` (custom)
    - [ ] `stripe_customer_id`, `subscription_plan`, `subscription_status` (active/trialing/past_due/canceled), `trial_ends_at`, and `plan_limits` JSONB fields added to `Organization` model via Alembic migration
    - [ ] `POST /billing/checkout-session` creates a Stripe Checkout Session and returns the session URL — user is redirected to Stripe's hosted payment page (no credit card form in our app)
    - [ ] `POST /billing/webhook` endpoint receives Stripe webhook events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`
    - [ ] Webhook handler updates `Organization.subscription_plan` and `subscription_status` based on Stripe events
    - [ ] `GET /billing/subscription` returns current plan, status, usage counts, and next billing date for the org
    - [ ] `GET /billing/invoices` returns paginated invoice history from Stripe API
    - [ ] `POST /billing/portal-session` creates a Stripe Customer Portal session URL for self-service plan changes, payment method updates, and cancellation
    - [ ] Quota enforcement middleware: check org plan limits before creating runs, projects, or protocols — return 402 with clear message when limit reached
    - [ ] All billing endpoints require `OrgRole.ADMIN` or `OrgRole.BILLING` role
    - [ ] Billing events logged to `audit_logs` (plan changes, payment received, subscription canceled)
  - **Phase 2 — Frontend Billing UI**
    - [ ] New "Billing" tab added to Settings page (visible only to ADMIN and BILLING role users)
    - [ ] Billing tab shows: current plan name, status badge (Active/Trialing/Past Due), usage meters (runs used / limit, projects / limit), trial countdown if applicable
    - [ ] "Upgrade Plan" button opens a plan comparison card layout showing all tiers with feature lists and pricing
    - [ ] Selecting a plan triggers `POST /billing/checkout-session` and redirects to Stripe Checkout (hosted page — no card form in our app)
    - [ ] "Manage Subscription" button opens Stripe Customer Portal (hosted by Stripe — handles card updates, cancellation, plan changes)
    - [ ] Invoice history table with date, amount, status, and "Download PDF" link (from Stripe's hosted invoice URL)
    - [ ] Quota warning banners: amber at 80% usage ("You've used 8 of 10 active runs"), red at 100% ("Run limit reached — upgrade to create more")
    - [ ] Quota banners appear on dashboard and on the relevant creation pages (new run, new project, new protocol)
    - [ ] Trial expiry banner: "Your trial ends in N days — upgrade to keep your data" with CTA
  - **Phase 3 — Local Test Mode**
    - [ ] When `RUNBOOK_STRIPE_SECRET_KEY` starts with `sk_test_`, app operates in Stripe test mode automatically (Stripe handles this natively)
    - [ ] Seed script creates a test Stripe customer and attaches a test subscription so local dev starts with an active plan
    - [ ] Documentation in README: test card numbers (`4242 4242 4242 4242` for success, `4000 0000 0000 0002` for decline), Stripe CLI for webhook forwarding (`stripe listen --forward-to localhost:8000/billing/webhook`)
    - [ ] `RUNBOOK_BILLING_ENABLED=false` env var completely disables billing checks and hides the Billing tab — default for local dev so billing is opt-in
    - [ ] When billing is disabled, all quota checks return unlimited — no features are gated
- **Implementation Notes**:
  - **Stripe library**: Add `stripe` Python package to `backend/pyproject.toml`. Use `stripe.checkout.Session.create()` for Checkout, `stripe.billing_portal.Session.create()` for Customer Portal, `stripe.Webhook.construct_event()` for webhook verification
  - **Why Stripe Checkout + Customer Portal (not embedded card forms)**: Stripe handles PCI compliance, 3D Secure, payment method storage, and localization. We never touch card numbers. This is the simplest, most secure approach and eliminates PCI scope entirely. Users are redirected to Stripe's hosted pages for payment and subscription management
  - **Backend model** (`backend/app/models/billing.py`): Add billing fields to `Organization`. Optionally create a local `Invoice` cache table for offline access, but primary source of truth is Stripe
  - **Backend router** (`backend/app/api/endpoints/billing.py`): New router mounted at `/billing`. Endpoints: `checkout-session`, `webhook`, `subscription`, `invoices`, `portal-session`
  - **Webhook security**: Verify Stripe signature using `RUNBOOK_STRIPE_WEBHOOK_SECRET`. Return 400 for invalid signatures. Idempotent handling (check if event already processed via Stripe event ID)
  - **Quota enforcement** (`backend/app/core/deps.py` or `backend/app/services/billing.py`): Create `check_quota(org_id, resource_type)` dependency that queries org plan limits vs current counts. Inject into run/project/protocol creation endpoints
  - **Frontend billing tab** (`frontend/src/routes/settings/+page.svelte`): Add `'billing'` to the `activeTab` union type. New section renders plan card, usage meters, invoice table. Gate visibility on `isOrgAdmin || isBillingRole`
  - **Plan comparison component** (`frontend/src/lib/components/PlanComparison.svelte`): Card grid showing tier features, pricing, and "Select Plan" buttons
  - **Stripe test mode**: Stripe's API keys come in `sk_test_*` / `pk_test_*` pairs. Test mode uses fake card numbers, no real charges, instant webhook delivery. Stripe CLI (`stripe listen`) forwards webhooks to localhost during development
  - **Config** (`backend/app/core/config.py`): Add `stripe_secret_key: str = ""`, `stripe_webhook_secret: str = ""`, `billing_enabled: bool = False`. When `billing_enabled` is False, skip all quota checks and hide billing UI
- **Dependencies**: None

### [F-0020] Terms of Service & Legal Acceptance Flow
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Description**: Add a Terms of Service (ToS) page, Privacy Policy page, and a clickwrap acceptance flow that gates app usage. The ToS must include a **Research Use Only (RUO) designation** and explicitly **prohibit users from entering Protected Health Information (PHI)** as defined by HIPAA. Users must accept the ToS before accessing the app (enforced on first login and when ToS is materially updated). The ToS content is tailored to a biotech SaaS lab notebook and aligns with existing `BUSINESS_STRATEGY.md` commitments on data ownership, retention, and privacy.

  **Why this matters**: Trellis targets gene & cell therapy PD teams where some workflows (e.g., human platelet lysate preparation, autologous CAR-T) may involve donor-linked data. The system has 14+ free-text vectors where PHI could accidentally enter (step notes, custom params, run names, image conversations, AI-extracted values). A clear ToS with PHI prohibition (a) sets user expectations, (b) shifts liability for misuse, (c) reinforces the RUO posture required by FDA guidance, and (d) is a prerequisite for enterprise sales. This is cheaper and more appropriate than full HIPAA compliance for the research-use Phase 1.

- **Acceptance Criteria**:

  **Backend — User Model & API**
  - [ ] Add `tos_accepted_at` (nullable DateTime) and `tos_version` (nullable String) fields to the `User` model via Alembic migration
  - [ ] Add `POST /auth/accept-tos` endpoint that sets `tos_accepted_at = utcnow()` and `tos_version = <current_version>` for the authenticated user. Returns updated user object
  - [ ] Add `GET /legal/tos` endpoint that returns the current ToS content (markdown or HTML) and version string. Public (no auth required)
  - [ ] Add `GET /legal/privacy` endpoint that returns the current Privacy Policy content and version. Public (no auth required)
  - [ ] `tos_accepted_at` and `tos_version` included in `UserResponse` schema so the frontend can check acceptance status
  - [ ] Audit log entry created when a user accepts the ToS (action: `TOS_ACCEPTED`, changes include version)

  **Frontend — Acceptance Gate**
  - [ ] After login/register, if `user.tos_accepted_at` is null OR `user.tos_version` !== current ToS version, redirect to `/terms/accept` before allowing access to any protected route
  - [ ] `/terms/accept` page displays the full ToS in a scrollable container with an unchecked checkbox: "I have read and agree to the Terms of Service and Privacy Policy" (with hyperlinks to each)
  - [ ] "Accept" button is disabled until checkbox is checked
  - [ ] On accept, calls `POST /auth/accept-tos`, updates local user state, and redirects to the originally requested route (or dashboard)
  - [ ] Route guard in `+layout.svelte` enforces the gate — no protected route is accessible without ToS acceptance

  **Frontend — Static Legal Pages**
  - [ ] `/terms` page renders the full Terms of Service (publicly accessible, no auth required)
  - [ ] `/privacy` page renders the full Privacy Policy (publicly accessible, no auth required)
  - [ ] Footer links to Terms of Service and Privacy Policy on all pages (including login/register)
  - [ ] Registration page includes text: "By creating an account, you agree to our Terms of Service and Privacy Policy" with hyperlinks (informational — formal acceptance is the clickwrap gate)

  **ToS Content — Required Sections**
  - [ ] **Definitions**: Service, Customer, User, Customer Data, Usage Data, AI Features, AI Input/Output, Offline Sessions
  - [ ] **Service Description & RUO Disclaimer**: "The Service is provided for Research Use Only. It is not validated for Good Manufacturing Practice (GMP) use, clinical use, diagnostic procedures, or therapeutic applications. The Service has not been reviewed, cleared, or approved by the FDA or any other regulatory body."
  - [ ] **Account Registration & Eligibility**: 18+ age requirement, accurate information, no shared credentials, admin responsibilities
  - [ ] **License Grant & Restrictions**: Non-exclusive, non-transferable license for internal research purposes. No reverse engineering, competing products, or circumventing security
  - [ ] **Acceptable Use Policy**: Prohibited uses include GMP/clinical/diagnostic use, storing/transmitting PHI, exceeding usage limits, accessing other customers' data
  - [ ] **PHI Prohibition** (dedicated section): "The Service is not designed to process, store, or transmit Protected Health Information (PHI) as defined by HIPAA. Trellis does not enter into Business Associate Agreements (BAAs). Customer agrees not to upload, enter, or transmit any PHI through the Service. Use coded identifiers for donor/sample tracking." Customer indemnifies Trellis for PHI uploaded in violation
  - [ ] **Data Ownership & IP**: Customer retains all rights to Customer Data. Trellis will not sell, share, or use Customer Data for AI training. Customer may export all data at any time (CSV, JSON, Excel). Trellis retains IP in the Service itself. Usage Data (anonymized, aggregated) may be used for product improvement
  - [ ] **AI Features Terms**: Multi-provider architecture disclosure (Anthropic, OpenAI, Google). Third-party providers contractually prohibited from training on Customer data. Customer owns AI input/output. Accuracy disclaimer: AI outputs are provided as-is, customer must validate. BYOK option disclosed
  - [ ] **Offline Mode Terms**: Data encrypted locally (AES-256). Customer responsible for device physical security. Trellis not responsible for data loss from device failure/theft while offline
  - [ ] **Subscription & Billing**: Tier descriptions (or reference to pricing page), auto-renewal, cancellation at end of billing period, AI overage charges, price change notice (30 days). Online cancellation available
  - [ ] **Free Trial Terms**: Free until 3 completed runs (no time limit), full feature access, no credit card required, data preserved after trial limit
  - [ ] **Data Retention & Deletion**: Data preserved 90 days after cancellation in read-only/export mode, then permanently deleted. Customer may request immediate deletion. If Trellis ceases operations: 90-day notice with full data export
  - [ ] **Security & Confidentiality**: Encryption at rest and in transit, multi-tenant logical isolation, role-based access controls, 72-hour breach notification, list of subprocessors
  - [ ] **Warranty Disclaimer**: AS-IS/AS-AVAILABLE, no warranty for regulatory/clinical/GMP suitability, no warranty on AI accuracy. ALL CAPS per UCC 2-316
  - [ ] **Limitation of Liability**: Exclude indirect/consequential damages. Cap at 12 months of fees paid. Carve-outs for security breach and confidentiality obligations
  - [ ] **Indemnification**: Mutual. Trellis indemnifies for IP infringement. Customer indemnifies for data (including PHI violations), ToS violations, and illegal use
  - [ ] **Term & Termination**: Auto-renewal, termination for convenience with notice, immediate termination for AUP violations, survival clause for key sections
  - [ ] **Dispute Resolution**: Governing law (state of incorporation), 30-day informal resolution, binding arbitration (JAMS/AAA), class action waiver with 30-day opt-out, small claims exception
  - [ ] **Modifications**: 30 days notice for material changes via email/in-app. Continued use = acceptance. Archive of prior versions
  - [ ] **General Provisions**: Severability, entire agreement, waiver, assignment, notices, independent contractors, no third-party beneficiaries, export compliance
  - [ ] **Contact Information**: Legal notices, support, privacy inquiries, last modified date

  **Privacy Policy Content — Required Sections**
  - [ ] Personal information collected (name, email, org affiliation, usage data)
  - [ ] How it is used (account management, support, product improvement)
  - [ ] What is NOT collected (PHI, financial data beyond payment processing)
  - [ ] Third-party processors (payment processor, AI providers, infrastructure providers)
  - [ ] Cookie policy (if applicable)
  - [ ] CCPA/CPRA rights for California residents (right to know, delete, opt-out of sale)
  - [ ] Data retention for personal information
  - [ ] Contact information for privacy inquiries

  **Consent Record Keeping**
  - [ ] Store ToS acceptance as a durable record: user ID, timestamp, ToS version, IP address (if available), user agent
  - [ ] When ToS version changes, existing users must re-accept on next login before proceeding

- **Implementation Notes**:
  - **Backend model change** (`backend/app/models/iam.py`): Add `tos_accepted_at: Mapped[Optional[datetime]]` and `tos_version: Mapped[Optional[str]]` to `User`. Generate Alembic migration
  - **Backend schema** (`backend/app/schemas/auth.py`): Add `tos_accepted_at` and `tos_version` to `UserResponse`
  - **Backend endpoint** (`backend/app/api/endpoints/auth.py`): Add `POST /auth/accept-tos` that validates auth, sets fields, logs audit entry. Add `GET /legal/tos` and `GET /legal/privacy` public endpoints that return content from static files or a `legal/` directory
  - **Legal content storage**: Store ToS and Privacy Policy as markdown files in `backend/app/legal/tos_v1.md` and `backend/app/legal/privacy_v1.md`. Version in filename. Endpoints serve the current version. This keeps legal text version-controlled and diffable
  - **Frontend route guard** (`frontend/src/routes/+layout.svelte`): Extend the existing auth guard — after confirming auth, check `user.tos_accepted_at` and `user.tos_version`. If missing or outdated, redirect to `/terms/accept`. Add `/terms`, `/privacy`, and `/terms/accept` to the public routes list
  - **Frontend pages**: Create `frontend/src/routes/terms/+page.svelte` (public ToS display), `frontend/src/routes/privacy/+page.svelte` (public Privacy Policy display), `frontend/src/routes/terms/accept/+page.svelte` (acceptance gate with scrollable ToS, checkbox, and accept button)
  - **Frontend auth** (`frontend/src/lib/auth.svelte.ts`): Add `tos_accepted_at` and `tos_version` to User interface. Add `acceptTos()` function that calls the endpoint and updates local state
  - **Footer component**: Add ToS and Privacy Policy links to the app shell footer (visible on all pages)
  - **Registration page** (`frontend/src/routes/register/+page.svelte`): Add informational text with links (not a binding gate — the clickwrap on `/terms/accept` is the binding mechanism, per enforceability best practices)
  - **ToS versioning**: Use semantic versioning (e.g., `1.0.0`). Store current version in backend config. On material update, bump version, all users see acceptance gate on next login
  - **Important legal note**: The ToS content in this spec is a framework, not legal advice. Have an attorney review before launch, particularly the RUO disclaimer (FDA implications), PHI prohibition (HIPAA liability), limitation of liability, and arbitration clause
- **Dependencies**: None

---

### [F-0019] Platform Knowledge Library
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Description**: A Trellis-curated, originally-authored knowledge base of standard Process Development methods covering cell culture, purification, and analytics. This is distinct from user-uploaded documents (F-0017 Document Library) — F-0019 is platform content authored or licensed by Trellis, providing a baseline reference for PD scientists. Content strategy TBD: original authoring, CC-licensed sources, or licensed content from established publishers.
- **Acceptance Criteria**:
  - [ ] Curated library of standard PD methods accessible to all users
  - [ ] Content covers core PD domains: cell culture, purification, analytics
  - [ ] Content is clearly distinguished from user-uploaded documents
  - [ ] Search and browse by topic/category
  - [ ] Content versioning and update tracking
- **Implementation Notes**: Content strategy and sourcing must be determined before implementation. Separate data model from user documents to allow different access controls and update workflows.
- **Dependencies**: F-0017 (Document Library — shared reader view infrastructure)

---

### [F-0020] Per-Organization AI Provider Configuration
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Backend
- **Description**: AI provider configuration (models, API keys, base URLs) is currently global — one config per capability shared across all organizations. This doesn't work for multi-tenant deployments where each org may have their own OpenAI/Anthropic API keys, preferred models, or private Ollama instances. Embedding model selection is the immediate pain point (some orgs want OpenAI `text-embedding-3-small`, others want local Ollama `nomic-embed-text`), but the same problem applies to vision, audio, and text capabilities.
- **Acceptance Criteria**:
  - [ ] `AiProviderConfig` scoped to organization via `org_id` foreign key (nullable — null = platform default)
  - [ ] Resolution chain: org-specific config → platform default config → env var fallback → hardcoded default
  - [ ] Org admins can configure their org's AI providers via Settings page (existing UI pattern, scoped to org)
  - [ ] Platform admins can set platform-wide defaults (null org_id rows)
  - [ ] API key isolation: org A's API key is never visible to or used by org B
  - [ ] Embedding provider is org-configurable (immediate use case for Document Library search)
  - [ ] Unique constraint updated: `(org_id, capability)` instead of just `(capability)`
  - [ ] Cache invalidation updated to be org-aware
- **Implementation Notes**:
  - **Migration**: Add nullable `org_id` FK to `ai_provider_configs`, drop `uq_ai_capability`, add `uq_ai_org_capability` on `(org_id, capability)`. Existing rows become platform defaults (org_id=NULL)
  - **ai_config.py**: Update `get_model()`, `get_full_config()`, `get_api_key()` to accept `org_id` parameter. Resolution: query with org_id first, fall back to org_id=NULL, then env vars, then defaults
  - **Cache key**: Change from `capability` to `(org_id, capability)` tuple
  - **Endpoints**: Update `PUT /ai/settings/{capability}` to accept optional `organization_id` body field. Org admins can only configure their own org. Add `GET /ai/settings?organization_id=X` to list org-specific configs
  - **Frontend Settings page**: Add org-scoped AI settings section under org admin settings
  - **Embedding service**: Pass `org_id` through from document upload context so each org's documents are embedded with their configured provider
- **Dependencies**: None

### [F-0022] LLM Management Console — Admin Model Configuration, Tiered Feature Gating & API Key Encryption
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Full Stack
- **Description**: The platform uses LLM technology across 5 capabilities (vision, embedding, document structure, chat, and audio). Currently, model configuration is managed via env vars or raw API calls to `/ai/settings` — there is no admin UI, no tiered access control, and API keys are stored as plaintext in the database. This feature creates a full admin settings experience for LLM configuration, introduces **tier-based feature gating** aligned with the platform's subscription tiers (Essentials / Pro / Enterprise), and encrypts all API keys at rest.
- **AI Tier Model** (mirrors platform subscription tiers):
  | Tier | AI Access | What the Org Gets | Config Experience |
  |---|---|---|---|
  | **Essentials** | BYOK only | All platform features available. All AI features work (chat, vision, document analysis, embeddings, audio), but org must supply their own API keys (OpenAI, Anthropic, Google, or self-hosted Ollama). No Trellis-managed AI included. | Admin configures each capability with their own provider + key |
  | **Pro** | Trellis-managed AI included + BYOK override | Trellis provides pre-configured, high-quality models out of the box — AI works immediately with no setup. Org can still override with their own keys per capability. Usage metered for billing. Also includes white-labeling. | "Trellis Managed" is the default; admin can override per capability |
  | **Enterprise** | Trellis-managed AI included + BYOK override + on-prem | Same AI as Pro. Also supports on-premise deployment (org runs their own LLM infrastructure), stronger SLA guarantees, custom model selection, dedicated support, and platform customization. | Same as Pro, plus on-prem LLM endpoint configuration and custom rate limits |
- **LLM Features Inventory** (current state):
  | Capability | Service File | What It Does | Default Model |
  |---|---|---|---|
  | **Vision** | `services/ai_vision.py` | Extracts measurement values from lab instrument photos; multi-turn conversation for clarification | `ollama/llama3.2-vision` |
  | **Embedding** | `services/embedding.py` | Generates vector embeddings for document chunks; powers hybrid vector+keyword search in Library | `ollama/nomic-embed-text` (768 dim) |
  | **Document Structure** | `services/document_structure.py` | Analyzes uploaded documents to identify headings, TOC, front matter, page roles; enriches chunked content | `ollama/llama3.2-vision` |
  | **Chat** | `services/chat_service.py` | "Trellis AI" assistant for biotech PD questions — cell biology, protocols, scientific concepts | `ollama/llama3.2` (resolves via `text` capability) |
  | **Audio** | (placeholder) | Speech-to-text for voice notes during runs | `ollama/whisper` |
  All capabilities route through `services/ai_config.py` which resolves provider/model/key via: DB (`ai_provider_configs` table) → env var fallback (`RUNBOOK_ai_{cap}_{field}`) → hardcoded Ollama defaults. Supported providers: `ollama`, `openai`, `anthropic`, `google`.
- **Acceptance Criteria**:
  - **Tier-Based Feature Gating:**
    - [ ] New `subscription_tier` field on the Organization model — enum values: `essentials`, `pro`, `enterprise` (default: `essentials`)
    - [ ] `subscription_tier` is set via billing/subscription flow (F-0019) or manually by platform admin
    - [ ] `GET /orgs/{id}` response includes `subscription_tier` so the frontend can gate UI accordingly
    - [ ] **Essentials tier**: "Trellis Managed" provider option is hidden in the admin UI. Org must configure their own provider + API key for each capability they want to use. AI features that have no configured provider show a "Configure AI" prompt instead of silently failing
    - [ ] **Pro tier**: "Trellis Managed" is available and pre-selected as default for all capabilities. Org can override any capability with their own provider/key. Trellis-managed calls are metered for billing. White-label options available in org settings
    - [ ] **Enterprise tier**: Same AI as Pro, plus configurable rate limits per capability, on-premise LLM endpoint configuration, custom model selection, and priority queue flag on LLM requests
    - [ ] Backend enforcement: `ai_config.py` resolution chain checks `org.subscription_tier` before allowing `trellis` provider — returns 403 if Essentials-tier org attempts to use Trellis-managed models
    - [ ] Frontend enforcement: AI settings UI adapts based on tier — Essentials orgs see BYOK-only UI with an upsell banner ("Upgrade to Pro for Trellis-managed AI"); Pro/Enterprise orgs see full provider selection including "Trellis Managed"
    - [ ] Graceful degradation: If an Essentials org has not configured any provider for a capability, AI-dependent features (chat, vision, document analysis) show a clear "AI not configured" state rather than errors — with a link to Settings > AI Models
  - **Admin UI — AI Settings Page:**
    - [ ] Org admins see an "AI Models" section in Settings with a card for each capability (Vision, Embedding, Document Structure, Chat, Audio)
    - [ ] Each capability card shows: current provider, model name, status (connected/error/not configured), and a "Configure" button
    - [ ] Configure form per capability: provider dropdown (filtered by tier — see gating above), model name input, API key input (masked), base URL input (for Ollama/custom endpoints)
    - [ ] "Test Connection" button per capability — calls `POST /ai/settings/{capability}/test` and shows success/error result inline
    - [ ] "Reset to Default" option: on Essentials tier, clears config (capability becomes unconfigured); on Pro/Enterprise, reverts to Trellis Managed
    - [ ] Changes saved via `PUT /ai/settings/{capability}` with org context
    - [ ] **Tier-aware status summary** at top of AI settings page: shows current tier badge (Essentials/Pro/Enterprise), number of configured capabilities, and for Pro/Enterprise shows current billing-period usage (tokens consumed)
  - **Trellis-Managed Models (Pro & Enterprise only):**
    - [ ] Platform-level `ai_provider_configs` rows (org_id=NULL) store Trellis API keys — never exposed to tenants
    - [ ] Pre-selected models per capability (e.g., `gpt-4o-mini` for vision, `text-embedding-3-small` for embedding, `claude-sonnet` for chat)
    - [ ] Trellis-managed usage is metered: each LLM call logs `org_id`, `capability`, `model`, `input_tokens`, `output_tokens`, `timestamp` to a `llm_usage_log` table
    - [ ] Usage limits per tier: Pro gets a monthly token budget (configurable in platform settings); Enterprise gets higher/custom limits
    - [ ] When an org approaches their token budget (80%), show a warning banner in the AI settings page. At 100%, Trellis-managed calls are rejected with a clear error and suggestion to add own API keys or upgrade
  - **API Key Encryption at Rest:**
    - [ ] All API keys in `ai_provider_configs.api_key` column are encrypted using AES-256-GCM before storage
    - [ ] Encryption key derived from a `RUNBOOK_ENCRYPTION_KEY` env var (required for production; generates warning on startup if missing)
    - [ ] Key rotation support: store a `key_version` alongside the encrypted value so old keys can be decrypted during rotation
    - [ ] `GET /ai/settings` responses continue to show only a masked hint (first 4 + last 4 chars), never the full key
    - [ ] Existing plaintext keys are migrated to encrypted format via a one-time Alembic data migration
  - **Per-Org Scoping** (subsumes F-0020):
    - [ ] `ai_provider_configs` scoped by `org_id` FK (nullable — null = platform default)
    - [ ] Resolution chain: org BYOK config → Trellis-managed (if tier allows) → env var fallback → hardcoded Ollama default
    - [ ] Org A's config is invisible to Org B
    - [ ] Cache key updated to `(org_id, capability)` tuple
  - **Observability:**
    - [ ] Admin UI shows last test result timestamp and any connection errors per capability
    - [ ] Platform admin (superuser) can view and edit platform-default configs and override any org's tier
    - [ ] Platform admin dashboard: aggregate usage across orgs, top consumers, error rates per provider
- **Implementation Notes**:
  - **Tier infrastructure**: Add `subscription_tier` enum column to `organizations` table (Alembic migration). Create `SubscriptionTier` enum in `models/iam.py` with values `essentials`, `pro`, `enterprise`. Default to `essentials`. Expose in `OrganizationResponse` schema. Platform admin endpoint `PATCH /admin/orgs/{id}/subscription-tier` to manually set tier (for bootstrapping before billing integration)
  - **Tier gating middleware**: Create `backend/app/core/ai_gating.py` with `check_subscription_tier(org, capability, provider)` — raises 403 if Essentials-tier org requests `trellis` provider. Called from `ai_config.py` resolution and from `PUT /ai/settings` validation
  - **Encryption module** (`backend/app/core/encryption.py`): Create `encrypt_value(plaintext, key) -> str` and `decrypt_value(ciphertext, key) -> str` using `cryptography` library's Fernet or AES-256-GCM. Store as `v1:<base64-ciphertext>` to support versioned key rotation. Add `cryptography` to `pyproject.toml`
  - **Migration**: Add `org_id` FK (nullable) to `ai_provider_configs`. Add `key_version` column (default 1). Add `subscription_tier` to `organizations`. Data migration to encrypt existing plaintext API keys. Update unique constraint to `(org_id, capability)`
  - **ai_config.py**: Update resolution to: (1) check org BYOK config, (2) if none and tier is `pro` or `enterprise`, use Trellis-managed, (3) env var fallback, (4) Ollama default. Encrypt on write, decrypt on read. Cache key `(org_id, capability)`
  - **Usage budgets**: Add `ai_token_budget` (nullable int) and `ai_tokens_used` (int, default 0) fields to organizations, or a separate `ai_usage_periods` table keyed by `(org_id, period_start)`. Reset monthly via cron or on first request of new period. Check budget before Trellis-managed calls
  - **LLM usage logging**: Create `llm_usage_log` table (id, org_id, user_id, capability, provider, model, input_tokens, output_tokens, latency_ms, created_at). Add `log_llm_usage()` calls in ai_vision.py, embedding.py, document_structure.py, chat_service.py after each LLM call
  - **AI settings endpoints** (`api/endpoints/ai.py`): Scope existing `GET/PUT /ai/settings` by org. Include tier in response. Add `GET /ai/settings/usage-summary` for admin dashboard. Validate provider selection against tier on PUT
  - **Frontend Settings page** (`frontend/src/routes/settings/+page.svelte`): Add "AI Models" tab/section for org admins. Create `AiSettingsTab.svelte` component with capability cards, configure forms, test buttons. Conditionally render "Trellis Managed" option based on `org.subscription_tier`. Show upsell banner for Essentials orgs. Show usage meters for Pro/Enterprise
  - **Frontend gating**: Create `frontend/src/lib/tierGating.ts` utility — `canUseTrellis(org): boolean`, `getAvailableProviders(org): Provider[]`, `isAiConfigured(org, capability): boolean`, `canWhiteLabel(org): boolean`. Use throughout UI to show/hide tier-gated features and prompt configuration/upgrade
  - **Key files affected**: `models/iam.py` (subscription_tier), `models/ai.py`, `services/ai_config.py`, `core/ai_gating.py` (new), `core/encryption.py` (new), `services/ai_vision.py`, `services/embedding.py`, `services/document_structure.py`, `services/chat_service.py`, `api/endpoints/ai.py`, `core/config.py`, `schemas/ai.py`, `schemas/iam.py`, `frontend/src/routes/settings/+page.svelte`, `frontend/src/lib/tierGating.ts` (new)
- **Dependencies**: F-0019 (Billing — needed for automated tier assignment via subscription, but tiers can be manually set by platform admin before billing is built). F-0020 (subsumed — per-org scoping is included in this feature's acceptance criteria)

### [F-0023] Global AI Chat Panel — Persistent Floating Assistant Across All Views
- **Status**: Proposed
- **Priority**: P1 (High)
- **Scope**: Frontend
- **Description**: The AI Chat assistant (F-0007) currently lives on a dedicated `/chat` route, requiring users to navigate away from their work. This feature refactors the chat into a persistent floating panel anchored to the lower-left corner of the viewport, accessible from every authenticated view (protocols, runs, projects, library, settings, export). Users can open/collapse the panel, start new conversations, and resume previous sessions — all without leaving their current context. This transforms the AI from a destination into an always-available co-pilot.
- **Acceptance Criteria**:
  - **Panel Shell & Positioning:**
    - [ ] Floating chat panel anchored to the lower-left corner of the viewport, rendered at the layout level (`+layout.svelte`) so it persists across all authenticated routes
    - [ ] Panel has three visual states: **collapsed** (only the toggle button visible), **open** (chat panel expanded, ~350px wide × ~500px tall), and **maximized** (larger panel, ~500px wide × 70vh tall)
    - [ ] Toggle button shows an AI/chat icon with an unread indicator badge when the assistant has responded while the panel is collapsed
    - [ ] Panel opens/closes with a smooth CSS transition (slide-up or scale animation, ~200ms)
    - [ ] Panel is draggable to reposition within the viewport (optional stretch goal)
    - [ ] Panel does not overlap or interfere with the main navigation header or critical page controls
    - [ ] Panel respects responsive breakpoints: on tablet (≤1024px), panel opens as a bottom sheet; on mobile (≤640px), panel opens full-screen overlay
  - **Chat Functionality (reuse from F-0007):**
    - [ ] All existing chat features work within the panel: send messages, receive AI responses, markdown rendering, source references, optimistic UI
    - [ ] "New Chat" button creates a fresh session within the panel
    - [ ] Session list/picker allows switching between previous chat sessions (dropdown or collapsible sidebar within the panel)
    - [ ] Current session title displayed in the panel header, editable inline
    - [ ] Delete session option available from the session picker
    - [ ] Message history loads when resuming a previous session, scrolled to the most recent message
    - [ ] Auto-scroll to bottom on new messages, with a "scroll to bottom" button if user has scrolled up
  - **State Persistence:**
    - [ ] Panel open/collapsed state persists across page navigations (stored in Svelte context or a lightweight store)
    - [ ] Active session ID persists across navigations so the user returns to the same conversation
    - [ ] Panel state (open/collapsed, active session) survives full page reloads (localStorage)
  - **Keyboard & Accessibility:**
    - [ ] Keyboard shortcut to toggle panel open/closed (e.g., `Ctrl+Shift+L` or configurable)
    - [ ] Focus trapped within panel when open (tab cycles through panel controls)
    - [ ] Escape key collapses the panel
    - [ ] ARIA attributes: `role="dialog"`, `aria-label="AI Chat Assistant"`, proper focus management
  - **Integration with Current Context:**
    - [ ] Panel is aware of the current route/page (e.g., if on a protocol editor, the panel header could show "Chat — Protocol: [name]")
    - [ ] Future-ready hook: `setContext("chatPanelActions", ...)` so pages can programmatically open the panel or inject context (e.g., "Ask AI about this unit op")
  - **Migration from /chat route:**
    - [ ] The dedicated `/chat` route continues to work as a full-screen fallback (no breaking change)
    - [ ] "Open in full screen" link in the panel header navigates to `/chat` with the current session pre-selected
    - [ ] Nav link updated: clicking "AI Chat" in the header toggles the floating panel instead of navigating to `/chat`
- **Implementation Notes**:
  - **New component**: Create `frontend/src/lib/components/ChatPanel.svelte` — the floating panel shell (positioning, open/close state, resize, header bar with session picker and controls)
  - **Extract chat logic**: Refactor the chat message list, input box, and source references from `frontend/src/routes/chat/+page.svelte` into a reusable `ChatConversation.svelte` component that both the panel and the full `/chat` page can render
  - **Layout integration**: Mount `<ChatPanel />` inside `frontend/src/routes/+layout.svelte` within the authenticated section (after the `{#if !isPublicRoute}` guard), positioned with `fixed` CSS
  - **State store**: Create `frontend/src/lib/stores/chatPanel.ts` using Svelte 5 runes (`$state`) or a simple writable store — tracks `isOpen`, `activeSessionId`, `unreadCount`. Sync to `localStorage` for persistence across reloads
  - **Session picker**: Compact dropdown in the panel header that calls `GET /chat/sessions` (already exists). Show session title + created date. Truncate long titles
  - **Unread badge**: When panel is collapsed and a new assistant message arrives, increment `unreadCount` in the store. Clear on panel open
  - **CSS**: Use `z-index: 50` (above page content, below modals at z-60+). Tailwind classes for positioning: `fixed bottom-4 left-4`. Transition with `transition-all duration-200`
  - **Keyboard shortcut**: Register in `+layout.svelte` via `window.addEventListener('keydown', ...)`. Check for `Ctrl+Shift+L` (avoid conflicts with browser shortcuts)
  - **Key files affected**: `frontend/src/routes/+layout.svelte`, new `frontend/src/lib/components/ChatPanel.svelte`, new `frontend/src/lib/components/ChatConversation.svelte`, `frontend/src/routes/chat/+page.svelte` (refactor to use ChatConversation), new `frontend/src/lib/stores/chatPanel.ts`
- **Dependencies**: F-0007 (AI Chat Assistant — Phase 1 and Phase 2 must be complete, which they are)

### [F-0024] Frontend Error Boundary Component
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0019
- **Description**: No global error boundary exists. Unhandled promise rejections or component errors could crash the app with no recovery UI.
- **Acceptance Criteria**:
  - [ ] `ErrorBoundary.svelte` component created that catches rendering errors in child components
  - [ ] Error boundary wraps all route pages in `+layout.svelte`
  - [ ] Recovery UI shows a friendly error message with a "Reload" button
  - [ ] Error details logged to console in development mode
- **Implementation Notes**:
  - Create `ErrorBoundary.svelte` wrapper and apply to route pages
- **Dependencies**: None

### [F-0025] Dark Mode Support — CSS Variable Normalization
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0046
- **Description**: Every page uses hardcoded Tailwind color utilities (`bg-white`, `text-slate-900`, `bg-slate-50`, `border-slate-200`, etc.) instead of semantic CSS variables. The shadcn-svelte components already use `--background`, `--foreground`, etc. and would swap cleanly, but all custom page markup bypasses these variables. This makes dark mode impractical without a full audit of every file.
- **Acceptance Criteria**:
  - [ ] Semantic color variables defined in `app.css` (e.g., `--color-surface`, `--color-surface-raised`, `--color-text-primary`, `--color-text-secondary`, `--color-border`)
  - [ ] Matching Tailwind utility classes created or theme extended
  - [ ] All hardcoded color classes across every `.svelte` file replaced with semantic equivalents
  - [ ] `.dark` variant on `<html>` that swaps CSS variable values
  - [ ] User preference toggle to switch between light and dark mode
- **Affected files**: `runs/[id]/+page.svelte`, `projects/[id]/+page.svelte`, `protocols/[id]/+page.svelte`, `+page.svelte` (dashboard), `export/+page.svelte`, `settings/+page.svelte`, all custom `lib/components/*.svelte`
- **Implementation Notes**:
  - Replace all hardcoded Tailwind color classes with semantic CSS variable equivalents
  - Add `.dark` variant, wire user preference toggle
- **Dependencies**: None

### [F-0026] Structured Request/Response Logging
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Backend
- **Source**: TD-0052
- **Description**: Only ~8 `logger` statements exist across the entire backend. No middleware for request/response logging, no correlation IDs, no structured log format. Makes production debugging and incident investigation extremely difficult.
- **Acceptance Criteria**:
  - [ ] FastAPI middleware logs every request: method, path, status code, duration
  - [ ] Structured JSON log format (via `structlog` or stdlib logging)
  - [ ] Correlation IDs added via middleware, propagated through request lifecycle
  - [ ] Sensitive data (passwords, tokens) excluded from logs
- **Implementation Notes**:
  - Add FastAPI middleware for structured request logging. Use `structlog` or Python's stdlib logging with JSON format. Add correlation IDs via middleware.
- **Dependencies**: None

### [F-0027] Optimistic UI Updates for Mutations
- **Status**: Proposed
- **Priority**: P3 (Low)
- **Scope**: Frontend
- **Source**: TD-0057
- **Description**: After every mutation (toggle channel, delete subscription, update member role), the entire list is re-fetched from the API. This causes unnecessary network requests, loading flickers, and poor perceived performance. Pattern repeats across settings and project pages.
- **Acceptance Criteria**:
  - [ ] Settings page mutations (toggle channel, delete subscription, update role) update local state immediately
  - [ ] Project page mutations follow the same pattern
  - [ ] On API error, local state reverts to pre-mutation value with a toast notification
  - [ ] Full reload only triggered when data shape may have changed from another user
- **Implementation Notes**:
  - Implement optimistic UI updates: update local state immediately, revert on API error
- **Dependencies**: None

### [F-0028] Frontend Linting & Formatting Setup (ESLint + Prettier)
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0058
- **Description**: No ESLint config or Prettier config exists in the frontend. TypeScript strict mode is enabled but no additional linting rules enforce code quality, unused variable detection, or consistent formatting. Backend has `black` + `isort` but frontend has no equivalent.
- **Acceptance Criteria**:
  - [ ] `eslint` with `eslint-plugin-svelte` configured
  - [ ] `prettier` with `prettier-plugin-svelte` configured
  - [ ] Initial `--fix` pass run across the codebase
  - [ ] Lint and format checks added to CI pipeline
- **Implementation Notes**:
  - Add configs, run initial fix pass, add to CI checks
- **Dependencies**: None

### [F-0029] Pagination for Settings Member & Subscription Lists
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Full Stack
- **Source**: TD-0061
- **Description**: Organization members and channel subscriptions are loaded as complete lists with no pagination or virtual scrolling. In orgs with hundreds of members, this will cause slow initial loads and high memory usage.
- **Acceptance Criteria**:
  - [ ] Server-side pagination (limit/offset) on member list endpoint
  - [ ] Server-side pagination on subscription list endpoint
  - [ ] Pagination controls in settings UI for both lists
  - [ ] Default page size of 20 with configurable limit
- **Implementation Notes**:
  - Add server-side pagination to endpoints and pagination controls to the settings UI
- **Dependencies**: None

### [F-0030] Playwright E2E: Organization Roles & Permissions Workflow
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0063
- **Description**: No E2E tests verify that role-based access control works end-to-end. Permission bugs can silently grant unauthorized access or block legitimate users.
- **Acceptance Criteria**:
  - [ ] **Org admin capabilities**: Admin can add a new member to the org via settings page
  - [ ] **Org admin capabilities**: Admin can change a member's role (MEMBER → ADMIN, ADMIN → MEMBER)
  - [ ] **Org admin capabilities**: Admin can create and delete teams
  - [ ] **Org admin capabilities**: Admin can create projects
  - [ ] **Org member restrictions**: Non-admin member cannot see "Add Member" controls on settings page
  - [ ] **Org member restrictions**: Non-admin cannot change other members' roles
  - [ ] **Project permissions (strict mode)**: User with VIEW permission can see project but cannot create protocols or runs
  - [ ] **Project permissions (strict mode)**: User with EDIT permission can create protocols and runs
  - [ ] **Project permissions (strict mode)**: User with APPROVE permission can approve/reject protocols
  - [ ] **Project permissions (open mode)**: When `permissions_enabled=false`, all org members get implicit EDIT access
  - [ ] **Permission denied UX**: Attempting a forbidden action shows a clear error, doesn't silently fail or crash
- **Implementation Notes**:
  - Create `frontend/e2e/permissions.spec.ts`. Seed multiple test users with different roles in `globalSetup`. Use Playwright's `browser.newContext()` for parallel sessions.
- **Dependencies**: None

### [F-0031] Playwright E2E: Run Creation & Execution Workflow
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0065
- **Description**: No E2E tests cover run execution, which is the core user-facing workflow (scientists recording lab results). Includes role assignments, multi-user execution, step completion, and GMP edit mode — all untested.
- **Acceptance Criteria**:
  - [ ] **Create run from protocol**: Create run from an existing protocol → run page shows protocol graph with execution controls
  - [ ] **Role assignment**: Assign users to swimlane roles in the run setup phase
  - [ ] **Start validation — missing assignments**: Try to start run with unassigned swimlanes → blocked with validation error
  - [ ] **Start run**: Assign all roles → start run → status transitions to ACTIVE, assigned users receive RUN_STARTED notification
  - [ ] **Record step data**: As assigned user, fill in step parameters and mark step as completed
  - [ ] **Role-locked execution**: User can only complete steps in their assigned swimlane (not others')
  - [ ] **Complete run**: Complete all steps → mark run as COMPLETED, assigned users receive RUN_COMPLETED notification
  - [ ] **GMP edit mode**: After completion, transition to EDITED status → modify a recorded value → original value preserved in audit trail
  - [ ] **Reassign role mid-run**: Change a role assignment on an active run → old user notified of removal, new user notified of assignment
  - [ ] **Multi-user execution**: Two browser contexts logged in as different assigned users → each can only act on their own lanes
  - [ ] **Run from ad-hoc (no protocol)**: Create a run without a protocol → empty graph, manual step creation
- **Implementation Notes**:
  - Create `frontend/e2e/runs.spec.ts`. Seed a project with an approved protocol containing multiple swimlanes and unit ops. Use multiple browser contexts for multi-user scenarios.
- **Dependencies**: None

### [F-0032] Fix Stale Notifications After Role Reassignment
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Backend
- **Source**: TD-0066
- **Description**: When a user is initially assigned to a run role via `ROLE_ASSIGNED` notification and then the role is reassigned to a different user, the original user's `ROLE_ASSIGNED` notification remains in their notification list. The reassignment creates a new `ROLE_REASSIGNED` notification for both users, but the old `ROLE_ASSIGNED` notification is never removed or invalidated. This means the original user sees both "You were assigned to role X" and "Role X was reassigned" — the first message is misleading since they are no longer assigned.
- **Acceptance Criteria**:
  - [ ] When a role reassignment occurs, existing `ROLE_ASSIGNED` notifications for the old user on that run+role are dismissed or deleted
  - [ ] The old user only sees the `ROLE_REASSIGNED` notification after reassignment
  - [ ] New user's `ROLE_ASSIGNED` notification is unaffected
- **Implementation Notes**:
  - In `create_run_role_assignment` (`backend/app/api/endpoints/runs.py`), query and delete/dismiss matching notifications by `entity_id` + `event_type` + `recipient`. Or add a `dismiss_notifications` helper to the notifications service.
- **Dependencies**: None

### [F-0033] Playwright E2E: Document Library — Search, URL Import, Retry & Processing Flows
- **Status**: Proposed
- **Priority**: P2 (Medium)
- **Scope**: Frontend
- **Source**: TD-0069
- **Description**: The library has 6 basic E2E tests covering navigation, empty state, file upload, detail view, delete, and invalid file rejection. But the core value-proposition workflows are untested: search/discovery, URL import, retry of failed processing, processing status polling, and org-scoped access control.
- **Acceptance Criteria**:
  - [ ] **Search — keyword match**: Upload a document with known content → search for a term → results appear with highlighted matches and correct document title
  - [ ] **Search — no results**: Search for a nonsensical term → empty state message displayed
  - [ ] **Search — click through**: Search → click a result → navigates to document detail page at the right section
  - [ ] **URL import**: Import a document from a public URL → document appears in list with source URL displayed
  - [ ] **URL import — invalid URL**: Try to import from a private IP or non-http URL → error message displayed
  - [ ] **Retry failed processing**: Upload a document → simulate failure → verify "Failed" status badge → click retry → status resets to processing
  - [ ] **Processing status polling**: Upload a document → verify status transitions from "Processing" to "Ready"
  - [ ] **Document reader — chunk navigation**: Open a multi-page document → verify chunks render with page numbers
  - [ ] **Org scoping**: Upload as user in Org A → log in as user in Org B → verify document is NOT visible
  - [ ] **File size validation**: Attempt upload of oversized file → error message before request is sent
- **Implementation Notes**:
  - Extend `frontend/e2e/library.spec.ts` with new test suites. Add `waitForDocumentIndexed(page, id)` helper.
- **Dependencies**: None

