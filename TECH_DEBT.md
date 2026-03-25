# Technical Debt Register

> This document tracks known technical debt in the trellisbio codebase.
> Run `/tech_debt` to scan the codebase and append new findings.
>
> **Severity**: Critical > High > Medium > Low
> **Effort**: S (< 1hr) | M (1-4hr) | L (4-8hr) | XL (> 1 day)

---

## Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Smells | 0 | 4 | 6 | 0 | 10 |
| Missing Implementation | 0 | 0 | 1 | 0 | 1 |
| Type Safety | 0 | 4 | 1 | 0 | 5 |
| Testing Gaps | 2 | 4 | 0 | 0 | 6 |
| Security | 0 | 0 | 0 | 0 | 0 |
| Architecture | 2 | 5 | 6 | 0 | 13 |
| Dependencies & Tooling | 0 | 0 | 1 | 0 | 1 |
| **Total** | **4** | **17** | **15** | **0** | **36** |

*Last updated: 2026-03-20*

---

## Findings

<!-- New findings are appended below this line -->

### [TD-0005] Frontend runs page is 1400+ lines
- **Category**: Code Smells
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/src/routes/runs/[id]/+page.svelte`
- **Description**: Mixed concerns: run state, role assignments, execution tracking, role wizard UI, PDF exports. Both `onMount()` and `$effect()` trigger `loadData()` redundantly.
- **Suggested Fix**: Extract role assignment logic and execution tracking into separate components. Remove redundant `onMount()`.
- **Effort**: L
- **Resolution**: Extracted 5 components into `lib/components/run/`: `RunDocuments.svelte` (document downloads, was duplicated 4x), `RoleAssignmentPanel.svelte` (PLANNED state role assignment form), `RunResultsSummary.svelte` (step results for COMPLETED/EDITED with edit annotation support), `RunEditMode.svelte` (edit mode sub-view, was duplicated 2x), `RunObserverView.svelte` (non-assigned user status view). Main page reduced from 1641 to 952 lines (42%). Redundant `onMount()` was already removed. Verified with `npm run check`.

### [TD-0006] Frontend Inspector.svelte is 1000+ lines
- **Category**: Code Smells
- **Severity**: High
- **Location**: `frontend/src/lib/components/Inspector.svelte`
- **Description**: Handles node parameter editing, equipment selection, schema modification, timeline positioning, and save-as-new functionality all in one component.
- **Suggested Fix**: Split into `NodeParameterEditor.svelte`, `EquipmentSelector.svelte`, `SchemaBuilder.svelte`.
- **Effort**: L

### [TD-0007] Backend export.py has duplicated format builders
- **Category**: Code Smells
- **Severity**: High
- **Location**: `backend/app/services/export.py:291` and `export.py:359`
- **Description**: `_build_long_format` (68 lines) and `_build_wide_format` (77 lines) share ~80% similar code for data extraction and row building.
- **Suggested Fix**: Extract common data extraction logic to a shared helper, with format-specific output assembly.
- **Effort**: M

### [TD-0008] Duplicated blob/download functions in api.ts
- **Category**: Code Smells
- **Severity**: High
- **Location**: `frontend/src/lib/api.ts:65-173`
- **Description**: `downloadBlob()`, `fetchBlobUrl()`, `postBlobUrl()`, `postDownloadBlob()` contain nearly identical auth/fetch/blob handling logic.
- **Suggested Fix**: Extract common fetch+blob logic to `_fetchBlob()` helper. Consolidate to 2-3 functions.
- **Effort**: M

### [TD-0010] Frontend PdfPreviewDrawer.svelte is 900+ lines
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `frontend/src/lib/components/PdfPreviewDrawer.svelte`
- **Description**: Large drawer managing PDF format customization (colors, fonts, spacing), tab switching, preview loading, and save logic.
- **Suggested Fix**: Extract color controls and format controls into separate sub-components.
- **Effort**: M

### [TD-0011] Frontend RoleWizard.svelte is 740+ lines
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `frontend/src/lib/components/RoleWizard.svelte`
- **Description**: Complex wizard managing step navigation, result validation, image capture, AI analysis, and field editing.
- **Suggested Fix**: Extract `StepNavigator.svelte`, `ResultsForm.svelte`, `ImageCapture.svelte`.
- **Effort**: M

### [TD-0012] Backend seed.py approaching 500 lines
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `backend/app/db/seed.py`
- **Description**: Large seed script with fixed UUIDs and repetitive patterns. Difficult to maintain.
- **Suggested Fix**: Extract into per-domain seed modules (users, orgs, projects). Use factory functions.
- **Effort**: M

### [TD-0013] Backend _get_ollama_model_name uses long if/elif chain
- **Category**: Code Smells
- **Severity**: ~~Medium~~ **WONTFIX**
- **Location**: `backend/app/services/ai_vision.py:169`
- **Description**: 159-line function with many if/elif branches for Ollama model name resolution. Could be a mapping dict.
- **Suggested Fix**: Replace with a dictionary lookup: `MODEL_MAP = {"name": "ollama_name", ...}`.
- **Effort**: S
- **Reason**: The function `_get_ollama_model_name` is already a clean 7-line implementation (extracts model name from provider or string). No if/elif chain exists — the item description does not match the current code.

### [TD-0019] No error boundary component in frontend
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `frontend/src/` (project-wide)
- **Description**: No global error boundary exists. Unhandled promise rejections or component errors could crash the app with no recovery UI.
- **Suggested Fix**: Create `ErrorBoundary.svelte` wrapper and apply to route pages.
- **Effort**: M

### [TD-0022] Pervasive use of `any` for API responses in frontend
- **Category**: Type Safety
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:36`, `projects/[id]/+page.svelte:24-27`, `runs/[id]/+page.svelte:12-22`, `settings/+page.svelte:19-31`, `export/+page.svelte:18`
- **Description**: All major route files declare state as `$state<any>(null)` for API response data: `protocol`, `project`, `run`, `members`, `rows`, etc. Zero type safety on core domain objects.
- **Suggested Fix**: Create TypeScript interfaces for all domain objects (`Protocol`, `Project`, `Run`, `Member`, etc.) in a shared `lib/types.ts`. Use them in state declarations.
- **Effort**: M

### [TD-0023] Untyped API responses across all frontend routes
- **Category**: Type Safety
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:649,718,724,768,833,887`, `export/+page.svelte:67`
- **Description**: API call results are cast to `any` (`const data: any = await api.get(...)`). No runtime validation of response shape.
- **Suggested Fix**: Add generic typing to API client and Zod validation at response boundaries.
- **Effort**: L

### [TD-0025] No Zod validation on API response boundaries
- **Category**: Type Safety
- **Severity**: High
- **Location**: `frontend/src/lib/api.ts` (project-wide)
- **Description**: `validation.ts` only exports `buildResultValidator()` for unit op results. No other API responses are validated. Backend schema changes could silently break the frontend.
- **Suggested Fix**: Create Zod schemas matching backend Pydantic schemas for all API endpoints. Validate in `api.ts` wrapper functions.
- **Effort**: L

### [TD-0026] Node/Edge data accessed without type safety
- **Category**: Type Safety
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte` (multiple locations)
- **Description**: Node and Edge data objects are accessed assuming specific structure with no TypeScript interfaces. `node.data.label`, `node.data.params`, `node.data.paramSchema` are all untyped.
- **Suggested Fix**: Create `UnitOpNodeData`, `SwimLaneNodeData`, `ProcessStartNodeData` interfaces.
- **Effort**: M

### [TD-0029] No unit tests for pdf.py (1200+ lines)
- **Category**: Testing Gaps
- **Severity**: Critical
- **Location**: `backend/app/services/pdf.py`
- **Description**: 1204-line module generating SOPs and batch records has zero test coverage. Font sizing, text wrapping, table rendering, role-based vs process-based logic are all untested. High regression risk.
- **Suggested Fix**: Create `tests/unit/test_pdf.py` covering `generate_sop_pdf`, `generate_batch_record_pdf`, `_draw_multi_param_row`, `_format_value`.
- **Effort**: L

### [TD-0030] No unit tests for export.py (450+ lines)
- **Category**: Testing Gaps
- **Severity**: Critical
- **Location**: `backend/app/services/export.py`
- **Description**: Export service with `_build_long_format` and `_build_wide_format` has no test coverage. Data transformation bugs would go undetected.
- **Suggested Fix**: Create `tests/unit/test_export.py` covering both format builders and edge cases (empty data, missing fields).
- **Effort**: M

### [TD-0031] Graph processing helpers have no unit tests
- **Category**: Testing Gaps
- **Severity**: High
- **Location**: `backend/app/api/endpoints/science.py` (`_parse_graph_roles_and_steps`, `_topo_sort_nodes`, `_find_connected_components`)
- **Description**: Complex graph algorithms are only tested indirectly through integration tests. No isolated unit tests for topological sort, connected components, or role/step parsing.
- **Suggested Fix**: Move to `services/graph_processing.py` and add dedicated unit tests.
- **Effort**: M

### [TD-0032] No integration tests for PDF and export endpoints
- **Category**: Testing Gaps
- **Severity**: High
- **Location**: `backend/tests/` (missing `test_pdf_api.py`, `test_export_api.py`)
- **Description**: PDF generation and export endpoints have no integration test coverage.
- **Suggested Fix**: Create integration tests hitting the PDF preview and export endpoints with sample protocol data.
- **Effort**: M

### [TD-0037] 50+ direct DB queries in endpoint layer (backend)
- **Category**: Architecture
- **Severity**: Critical
- **Location**: `backend/app/api/endpoints/science.py` (throughout)
- **Description**: Endpoints contain direct `db.execute()` calls mixing permission checking, data fetching, business logic, and response building. No service layer separation. Hard to test and reuse.
- **Suggested Fix**: Create service classes: `ProtocolService`, `RunService`, `UnitOpService`. Move all DB queries from endpoints to services. Endpoints should only orchestrate.
- **Effort**: XL

### [TD-0038] Direct DB queries in AI endpoints
- **Category**: Architecture
- **Severity**: Critical
- **Location**: `backend/app/api/endpoints/ai.py`
- **Description**: Image storage, analysis, and conversation management mixed directly in endpoint handlers.
- **Suggested Fix**: Create `ImageAnalysisService` with clean interfaces. Endpoints delegate to service.
- **Effort**: L

### [TD-0039] Frontend protocol editor mixes all concerns
- **Category**: Architecture
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`
- **Description**: Single component handles data loading, graph state management, 20+ event handlers, AND template rendering with no separation of concerns.
- **Suggested Fix**: Separate data loading into a service/store module. Create presentational sub-components.
- **Effort**: L

### [TD-0040] Frontend data fetching mixed into route components
- **Category**: Architecture
- **Severity**: High
- **Location**: `frontend/src/routes/projects/[id]/+page.svelte`, `runs/[id]/+page.svelte`
- **Description**: Each tab loads data via inline `$effect()` watchers interleaved with UI state management. No separation of data layer from presentation.
- **Suggested Fix**: Extract data loading to dedicated service functions or Svelte stores.
- **Effort**: M

### [TD-0041] Excessive prop drilling in protocol editor
- **Category**: Architecture
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`
- **Description**: Passing `nodes`, `edges`, `unitOps`, `roles`, `orgEquipment`, `equipmentConflicts` and 10+ callbacks to child components.
- **Suggested Fix**: Use Svelte context API for shared state. Reduce props to 2-3 essentials per component.
- **Effort**: M

### [TD-0042] Inspector accepts 8+ props with callbacks
- **Category**: Architecture
- **Severity**: High
- **Location**: `frontend/src/lib/components/Inspector.svelte`
- **Description**: Component accepts equipment list and 3+ callback functions as props. Both edits parameters locally AND saves to API.
- **Suggested Fix**: Use context for shared state. Separate `InspectorForm` (presentation) from `InspectorContainer` (data handling).
- **Effort**: M

### [TD-0043] Inconsistent error handling patterns (backend)
- **Category**: Architecture
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/` (across all endpoint files)
- **Description**: Mix of HTTPException wrapping and bare exception passthrough. Some endpoints catch and wrap errors, others don't. Bare `except Exception` catches obscure expected vs unexpected failures.
- **Suggested Fix**: Establish consistent error handling middleware or utility. Define which exceptions map to which HTTP status codes.
- **Effort**: M

### [TD-0044] Inconsistent frontend error handling
- **Category**: Architecture
- **Severity**: Medium
- **Location**: Multiple route files, `frontend/src/lib/api.ts`
- **Description**: Some catch blocks log to console, others don't. Some set error state, others silently fail. 6+ instances of try-catch with empty catch handlers or `// silent` comments.
- **Suggested Fix**: Standardize with consistent error state management and toast notifications for user-facing errors.
- **Effort**: M

### [TD-0045] Repeated select-by-id + 404 pattern across all endpoints
- **Category**: Architecture
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/science.py`, `ai.py`, `iam.py`, `projects.py`
- **Description**: `select(...).where(Model.id == id)` + `scalar_one_or_none()` + 404 check is repeated 100+ times with no shared utility.
- **Suggested Fix**: Create a `get_or_404(db, Model, id)` utility function in a shared module.
- **Effort**: S
- **Resolution**: Created `get_or_404(db, model, id, *, detail, options)` in `app/core/deps.py`. Replaced 18 occurrences across `projects.py` (4), `iam.py` (3), `protocols.py` (5), `runs.py` (6), and `ai.py` (1). Supports `selectinload` via `options` param. Unit tests in `tests/unit/test_deps.py`. All 456 tests pass.

### [TD-0046] Dark mode blocked by hardcoded Tailwind colors — normalize to CSS variables
- **Category**: Architecture
- **Severity**: Medium
- **Location**: All `.svelte` route and component files
- **Description**: Every page uses hardcoded Tailwind color utilities (`bg-white`, `text-slate-900`, `bg-slate-50`, `border-slate-200`, etc.) instead of semantic CSS variables. The shadcn-svelte components already use `--background`, `--foreground`, etc. and would swap cleanly, but all custom page markup bypasses these variables. This makes dark mode impractical without a full audit of every file.
- **Suggested Fix**:
  1. Define semantic color variables in `app.css` (e.g., `--color-surface`, `--color-surface-raised`, `--color-text-primary`, `--color-text-secondary`, `--color-border`)
  2. Create matching Tailwind utility classes or extend the theme
  3. Replace all hardcoded color classes across every `.svelte` file with semantic equivalents
  4. Add `.dark` variant on `<html>` that swaps the CSS variable values
  5. Wire user preference toggle to apply the class
- **Affected files**: `runs/[id]/+page.svelte` (~1400 lines), `projects/[id]/+page.svelte` (~1700 lines), `protocols/[id]/+page.svelte` (~2700 lines), `+page.svelte` (dashboard), `export/+page.svelte`, `settings/+page.svelte`, all custom `lib/components/*.svelte`
- **Effort**: XL

### [TD-0051] Backend iam.py is 784 lines with mixed concerns
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/iam.py`
- **Description**: Single file handles organization CRUD, team CRUD, member management, permission checking, and user profile operations. Approaching the 500-line threshold significantly.
- **Suggested Fix**: Split into `organizations.py`, `teams.py`, `members.py`. Share permission helpers via `services/iam_service.py`.
- **Effort**: L

### [TD-0052] No structured request/response logging in backend
- **Category**: Architecture
- **Severity**: High
- **Location**: `backend/app/` (project-wide)
- **Description**: Only ~8 `logger` statements exist across the entire backend. No middleware for request/response logging, no correlation IDs, no structured log format. Makes production debugging and incident investigation extremely difficult.
- **Suggested Fix**: Add FastAPI middleware for structured request logging (method, path, status, duration). Use `structlog` or Python's stdlib logging with JSON format. Add correlation IDs via middleware.
- **Effort**: M

### [TD-0053] Backend graph JSONB data accessed without schema validation
- **Category**: Type Safety
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/science.py:713-714`, `backend/app/services/pdf.py`, `backend/app/services/export.py`
- **Description**: Protocol/experiment graph JSONB is accessed via `.get()` chains with no validation: `n.get("type") == "unitOp"`, `n.get("position", {}).get("x", 0)`. If graph structure changes or is malformed, failures are silent or produce incorrect results. No Pydantic model validates graph shape on load.
- **Suggested Fix**: Create `ProtocolGraph`, `GraphNode`, `GraphEdge` Pydantic models. Validate graph JSONB against these models when loading from DB. Use the typed models in all downstream code.
- **Effort**: L

### [TD-0054] Frontend EquipmentPickerModal.svelte is 570 lines
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `frontend/src/lib/components/EquipmentPickerModal.svelte`
- **Description**: Equipment picker handles search, filtering, selection, inline creation form, and validation all in one component. Over the 500-line threshold.
- **Suggested Fix**: Extract the "Create New Equipment" form into a separate `CreateEquipmentForm.svelte` component.
- **Effort**: M

### [TD-0057] No optimistic updates — full data reload after every mutation
- **Category**: Architecture
- **Severity**: Medium
- **Location**: `frontend/src/routes/settings/+page.svelte`, `frontend/src/routes/projects/[id]/+page.svelte`
- **Description**: After every mutation (toggle channel, delete subscription, update member role), the entire list is re-fetched from the API. This causes unnecessary network requests, loading flickers, and poor perceived performance. Pattern repeats across settings and project pages.
- **Suggested Fix**: Implement optimistic UI updates: update local state immediately, revert on API error. Only full-reload when the data shape might have changed from another user.
- **Effort**: M

### [TD-0058] No ESLint or Prettier configuration in frontend
- **Category**: Dependencies & Tooling
- **Severity**: Medium
- **Location**: `frontend/` (project-wide)
- **Description**: No ESLint config (`.eslintrc`, `eslint.config.js`) or Prettier config (`.prettierrc`) exists. TypeScript strict mode is enabled but no additional linting rules enforce code quality, unused variable detection, or consistent formatting. Backend has `black` + `isort` but frontend has no equivalent.
- **Suggested Fix**: Add `eslint` with `eslint-plugin-svelte` and `prettier` with `prettier-plugin-svelte`. Run initial `--fix` pass. Add to CI checks.
- **Effort**: M

### [TD-0059] Equipment conflict detection uses O(n²) algorithm
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte` (detectEquipmentConflicts function)
- **Description**: Equipment conflict detection iterates over all node pairs for each edge, making it O(n²). Also calls `nodes.some((n: any) => n.parentId != null)` on every change. This runs on every `nodes`/`edges` reactive update, including viewport-only changes.
- **Suggested Fix**: Use a `Set` or `Map` for O(1) lookups. Only recalculate when node/edge/equipment data actually changes (not on position-only moves). Debounce the effect.
- **Effort**: M

### [TD-0060] Modal component lacks focus trap and keyboard navigation
- **Category**: Architecture
- **Severity**: ~~Low~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/Modal.svelte`
- **Description**: Custom `Modal.svelte` does not trap focus inside the modal when open. Users can Tab out of the modal into background content. No Escape key handler to close. Does not meet WCAG 2.1 dialog accessibility requirements.
- **Suggested Fix**: Use `bits-ui` Dialog primitive (already a dependency) which includes focus trapping, Escape handling, and ARIA attributes. Or add a focus-trap library.
- **Effort**: M
- **Resolution**: Subsumed by TD-0070. `Modal.svelte` was deleted entirely. All former users migrated to shadcn Dialog (bits-ui) which includes focus trapping, Escape handling, and full ARIA compliance.

### [TD-0061] No pagination on settings member and subscription lists
- **Category**: Architecture
- **Severity**: Medium
- **Location**: `frontend/src/routes/settings/+page.svelte:140,362`
- **Description**: Organization members and channel subscriptions are loaded as complete lists with no pagination or virtual scrolling. In orgs with hundreds of members, this will cause slow initial loads and high memory usage.
- **Suggested Fix**: Add server-side pagination (limit/offset) to the member and subscription list endpoints. Add pagination controls to the settings UI.
- **Effort**: M

### [TD-0063] Playwright E2E: Organization Roles & Permissions Workflow
- **Category**: Testing Gaps
- **Severity**: High
- **Location**: `frontend/e2e/` (to be created)
- **Description**: No E2E tests verify that role-based access control works end-to-end. Permission bugs can silently grant unauthorized access or block legitimate users.
- **Test Cases**:
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
- **Suggested Fix**: Create `frontend/e2e/permissions.spec.ts`. Seed multiple test users with different roles (org admin, org member, project viewer, project editor, project approver) in `globalSetup`. Use Playwright's `browser.newContext()` to run parallel sessions as different users.
- **Effort**: XL

### [TD-0065] Playwright E2E: Run Creation & Execution Workflow
- **Category**: Testing Gaps
- **Severity**: High
- **Location**: `frontend/e2e/` (to be created)
- **Description**: No E2E tests cover run execution, which is the core user-facing workflow (scientists recording lab results). Includes role assignments, multi-user execution, step completion, and GMP edit mode — all untested.
- **Test Cases**:
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
- **Suggested Fix**: Create `frontend/e2e/runs.spec.ts`. Seed a project with an approved protocol containing multiple swimlanes and unit ops. Use multiple browser contexts for multi-user scenarios. For notification checks, verify toast/notification UI elements appear rather than checking the database directly.
- **Effort**: XL

### [TD-0066] Stale ROLE_ASSIGNED notifications persist after role reassignment
- **Category**: Architecture
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/runs.py:720-800`
- **Description**: When a user is initially assigned to a run role via `ROLE_ASSIGNED` notification and then the role is reassigned to a different user, the original user's `ROLE_ASSIGNED` notification remains in their notification list. The reassignment creates a new `ROLE_REASSIGNED` notification for both users, but the old `ROLE_ASSIGNED` notification is never removed or invalidated. This means the original user sees both "You were assigned to role X" and "Role X was reassigned" — the first message is misleading since they are no longer assigned.
- **Suggested Fix**: When a role reassignment occurs in `create_run_role_assignment`, delete or mark as read/dismissed any existing `ROLE_ASSIGNED` notifications for the old user on that run+role. This requires either: (a) querying and deleting matching notifications by `entity_id` + `event_type` + `recipient`, or (b) adding a `dismiss_notifications` helper to the notifications service that invalidates stale assignment notifications when the assignment changes.
- **Effort**: M

### [TD-0069] Playwright E2E: Document Library — search, URL import, retry, and processing flows
- **Category**: Testing Gaps
- **Severity**: High
- **Location**: `frontend/e2e/library.spec.ts` (extend existing file)
- **Description**: The library has 6 basic E2E tests covering navigation, empty state, file upload, detail view, delete, and invalid file rejection. But the core value-proposition workflows are untested: search/discovery, URL import, retry of failed processing, processing status polling, and org-scoped access control. These are the flows scientists will use most — finding information in uploaded documents and importing references from the web.
- **Test Cases**:
  - [ ] **Search — keyword match**: Upload a document with known content → search for a term → results appear with highlighted matches and correct document title
  - [ ] **Search — no results**: Search for a nonsensical term → empty state message displayed
  - [ ] **Search — click through**: Search → click a result → navigates to document detail page at the right section
  - [ ] **URL import**: Import a document from a public URL (e.g., a raw text file on GitHub) → document appears in list with source URL displayed
  - [ ] **URL import — invalid URL**: Try to import from a private IP or non-http URL → error message displayed
  - [ ] **Retry failed processing**: Upload a document → simulate failure (or use a corrupt file) → verify "Failed" status badge → click retry → status resets to processing
  - [ ] **Processing status polling**: Upload a document → verify status transitions from "Processing" to "Ready" (or poll until indexed)
  - [ ] **Document reader — chunk navigation**: Open a multi-page document → verify chunks render with page numbers → use in-document search to find text
  - [ ] **Org scoping**: Upload as user in Org A → log in as user in Org B → verify document is NOT visible in Org B's library
  - [ ] **File size validation**: Attempt upload of oversized file → error message before request is sent
- **Suggested Fix**: Extend `frontend/e2e/library.spec.ts` with new test suites. For search tests, upload via API helper first and wait for INDEXED status (poll `GET /library/documents/{id}` until `status === "INDEXED"`). For URL import, use a stable public text file. For org scoping, use the existing second user/org fixtures from the auth E2E helpers. Add a `waitForDocumentIndexed(page, id)` helper to `frontend/e2e/helpers/library.ts`.
- **Effort**: L

### [TD-0068] Stale Tailwind v3 config causes arbitrary value classes to fail
- **Category**: Dependencies & Tooling
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/tailwind.config.js`, `frontend/src/app.css`, `frontend/postcss.config.js`
- **Description**: The frontend uses Tailwind CSS v4 (`@import "tailwindcss"` with `@theme` in `app.css`) but still has a Tailwind v3-style `tailwind.config.js` with `content`, `theme.extend`, `darkMode`, etc. Tailwind v4 uses automatic content detection and CSS-based configuration — the v3 config file is ignored or partially applied, causing subtle bugs. Arbitrary value classes like `w-[15px]` silently fail to generate, producing unsized elements (e.g., a 15px search icon SVG rendering at full viewport size). The `@theme` block in `app.css` and the `theme.extend` in `tailwind.config.js` define overlapping/conflicting design tokens.
- **Suggested Fix**:
  1. Migrate all v3 `tailwind.config.js` settings into the v4 CSS-based config (`@theme` block in `app.css`)
  2. Move `content` paths to v4's `@source` directive if automatic detection isn't sufficient
  3. Move `darkMode: ["class"]` to v4's `@variant dark (&:where(.dark, .dark *))` syntax
  4. Move shadcn-svelte color tokens from `theme.extend.colors` to `@theme` CSS variables (some are already there — deduplicate)
  5. Delete `tailwind.config.js`
  6. Audit all arbitrary value classes (`w-[Xpx]`, `h-[Xpx]`, `text-[Xpx]`, etc.) across the codebase — replace with standard Tailwind classes where possible
  7. Remove inline style workarounds added to bypass broken arbitrary classes (e.g., `dialog-content.svelte` uses `style="top: 50%; left: 50%; transform: translate(-50%, -50%)"` because the Tailwind classes failed) — replace with pure Tailwind once v4 config is unified
  8. Browser-test every component that had inline style workarounds or custom CSS overrides after migration to confirm no visual regressions — dialogs, popovers, dropdowns, and any positioned overlays are especially fragile
- **Effort**: M
- **Resolution**: Deleted stale `tailwind.config.js` (was completely ignored by v4 — no `@config` directive). Migrated border-radius overrides (`--radius-lg/md/sm`) into v4 `@theme` block in `app.css`. Replaced inline style centering workaround in `dialog-content.svelte` with Tailwind classes (`top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2`). Replaced custom CSS in protocol editor page (`.editor-wrapper`, `.canvas-wrapper`, `.canvas-loading`, `.spinner`) with inline Tailwind utilities. Removed redundant `:global(body)` reset from runs page. Audited arbitrary value classes — all working correctly under v4. Dark mode config and content paths were dead code (dark mode unused, v4 auto-detects content). Browser-verified login, project, and protocol editor pages — no visual regressions.

### [TD-0070] 4+ competing modal implementations with inconsistent behavior
- **Category**: Architecture
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/Modal.svelte`, `frontend/src/lib/components/ui/dialog/`, `frontend/src/lib/components/GoOfflineDialog.svelte`, `frontend/src/lib/components/ImageAnalysisDialog.svelte`, `frontend/src/routes/runs/[id]/+page.svelte`, `frontend/src/lib/components/BarcodeScanner.svelte`, `frontend/src/lib/components/RoleWizard.svelte`, `frontend/src/lib/components/FieldModeRoleWizard.svelte`
- **Description**: The frontend has 4+ distinct modal/dialog implementations that each behave differently:
  1. **Custom `Modal.svelte`** — CSS keyframe animations, z-9999, click-to-close backdrop, Escape key, no focus trap. Used by EquipmentPickerModal and CreateUnitOpModal.
  2. **shadcn-svelte `Dialog`** (bits-ui) — Tailwind data-driven animations, z-50, portal rendering, focus trap, full a11y. Used only by DocumentUploadDialog.
  3. **Inline `fixed inset-0` divs** — No animation, no Escape key, no backdrop click-to-close, no a11y attributes. Used in runs page confirmation modals (Start Run, Complete Run).
  4. **Custom inline modal chrome** — Each component (GoOfflineDialog, ImageAnalysisDialog, BarcodeScanner, RoleWizard tag selector) builds its own backdrop + panel from scratch with different subsets of features.
  This fragmentation means users get different experiences depending on which modal they trigger: some close on Escape, some don't; some close on backdrop click, some don't; some animate, some don't; z-index layering conflicts between z-50 and z-9999.
- **Suggested Fix**: (see below)
- **Effort**: L
- **Resolution**: Standardized all modals on shadcn-svelte Dialog (bits-ui). Created `ConfirmDialog.svelte` convenience wrapper. Migrated 7 components to shadcn Dialog: GoOfflineDialog, ImageAnalysisDialog, CreateUnitOpModal, EquipmentPickerModal, BarcodeScanner, runs page confirmations (Start/Complete), projects page New Run modal. Deleted `Modal.svelte`. Standardized all z-index values to z-50. All modals now have focus trapping, Escape key, backdrop click-to-close, animations, and ARIA compliance. Also resolves TD-0060 (Modal.svelte focus trap). Verified with `npm run check`.

### [TD-0071] Runs page confirmation modals are raw inline divs with no a11y or UX features
- **Category**: Architecture
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/routes/runs/[id]/+page.svelte:468-494,636-672`
- **Description**: The "Start Run?" and "Complete Run?" confirmation modals are bare `{#if showFlag}<div class="fixed inset-0 bg-black/50 ...">` blocks with none of the expected modal behaviors: no Escape key handler, no backdrop click-to-close, no focus trapping, no `role="dialog"`, no animations, no close (X) button. Users must click one of the two buttons — there's no other way to dismiss. These are the most frequently-used modals in the app (every run goes through them) and they feel noticeably cheaper than the rest of the UI.
- **Suggested Fix**: Replace with a shared `ConfirmDialog.svelte` component (or direct shadcn Dialog usage) that provides consistent behavior. Props: `open`, `title`, `message`, `confirmLabel`, `confirmVariant` (primary/danger/warning), `onConfirm`, `onCancel`, `loading`.
- **Effort**: S
- **Resolution**: Replaced both inline modals with the new `ConfirmDialog` component. Start Run uses default (primary) variant; Complete Run uses `success` variant with a warning snippet for unanalyzed images. Both now have Escape, backdrop click, focus trap, and animations.

### [TD-0072] GoOfflineDialog and ImageAnalysisDialog build custom modal chrome instead of using shared component
- **Category**: Code Smells
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/GoOfflineDialog.svelte`, `frontend/src/lib/components/ImageAnalysisDialog.svelte`
- **Description**: Both components build their own modal infrastructure from scratch (backdrop div, positioning, keyboard handling) instead of wrapping their content in either `Modal.svelte` or the shadcn `Dialog`. GoOfflineDialog has no backdrop click-to-close and no animation. ImageAnalysisDialog has its own custom `slideUp` animation that partially duplicates `Modal.svelte`'s animation. Each handles Escape key differently. This adds ~60 lines of boilerplate per component that a shared modal component would eliminate.
- **Suggested Fix**: Wrap each component's content in the shadcn `Dialog` component. GoOfflineDialog content goes inside `Dialog.Content` with `sm:max-w-md`. ImageAnalysisDialog content goes inside `Dialog.Content` with `sm:max-w-2xl`. Remove custom backdrop, positioning, and keyboard handling code from both.
- **Effort**: M
- **Resolution**: Wrapped GoOfflineDialog in `Dialog.Root`/`Dialog.Content` (`sm:max-w-md`). Wrapped ImageAnalysisDialog in `Dialog.Root`/`Dialog.Content` (`sm:max-w-2xl`). Removed custom backdrop divs, keyboard handlers (`handleBackdropClick`, `handleEscape`), custom CSS animations. Both now inherit focus trapping, Escape, backdrop click, and animations from bits-ui.

### [TD-0073] Inconsistent z-index layering across modal and overlay components
- **Category**: Architecture
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/Modal.svelte` (z-9999), `frontend/src/lib/components/ui/dialog/dialog-content.svelte` (z-50), `frontend/src/routes/runs/[id]/+page.svelte` (z-50), `frontend/src/lib/components/GoOfflineDialog.svelte` (z-9999), `frontend/src/lib/components/ImageAnalysisDialog.svelte` (z-9999), `frontend/src/lib/components/RoleWizard.svelte` (z-9998), `frontend/src/lib/components/FieldModeLockScreen.svelte` (z-9999), `frontend/src/lib/components/ExpiryWarningBanner.svelte` (z-9998), `frontend/src/lib/components/MobileNav.svelte` (z-50)
- **Description**: Modal z-index values are split between two camps: z-50 (shadcn Dialog, runs page, MobileNav) and z-[9999] (custom Modal, GoOffline, ImageAnalysis, FieldModeLockScreen). FieldModeRoleWizard and ExpiryWarningBanner use z-[9998]. If a z-50 modal opens while a z-9999 component is active, layering breaks. Conversely, the shadcn Dialog's built-in overlay at z-50 would be hidden behind any z-9999 element.
- **Suggested Fix**: Define a z-index scale in CSS variables (e.g., `--z-dropdown: 40`, `--z-modal: 50`, `--z-lock-screen: 60`) and apply consistently. All standard modals should use the same z-index. Only truly top-level overlays (lock screen, critical warnings) should use a higher tier.
- **Effort**: S
- **Resolution**: Replaced all z-[9999] and z-[9998] values with z-50 across FieldModeLockScreen, ExpiryWarningBanner, FieldModeRoleWizard, RoleWizard, and field page. Modal.svelte (z-9999) deleted. All remaining overlay components now use z-50 consistently.

