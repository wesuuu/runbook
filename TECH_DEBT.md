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
| Code Smells | 4 | 6 | 7 | 3 | 20 |
| Missing Implementation | 0 | 1 | 4 | 0 | 5 |
| Type Safety | 2 | 5 | 3 | 0 | 10 |
| Testing Gaps | 3 | 2 | 0 | 0 | 5 |
| Security | 4 | 1 | 2 | 0 | 7 |
| Architecture | 2 | 5 | 7 | 1 | 15 |
| Dependencies & Tooling | 0 | 0 | 1 | 0 | 1 |
| **Total** | **15** | **20** | **24** | **4** | **63** |

*Last updated: 2026-03-08*

---

## Findings

<!-- New findings are appended below this line -->

### [TD-0001] Backend science.py is a 2300+ line monolith
- **Category**: Code Smells
- **Severity**: Critical
- **Location**: `backend/app/api/endpoints/science.py`
- **Description**: Single endpoint file contains 100+ endpoint functions plus large helper functions like `_parse_graph_roles_and_steps` (~135 lines), `_topo_sort_nodes`, and `_find_connected_components`. File is 4.6x over the 500-line recommendation.
- **Suggested Fix**: Split into separate routers: `protocols.py`, `runs.py`, `unitops.py`. Move helper functions to a service layer (`services/graph_processing.py`).
- **Effort**: XL

### [TD-0002] Backend pdf.py is 1200+ lines with no tests
- **Category**: Code Smells
- **Severity**: Critical
- **Location**: `backend/app/services/pdf.py`
- **Description**: Monolithic PDF generation module with `generate_batch_record_pdf` (473 lines), `generate_sop_pdf` (210 lines), and `_draw_multi_param_row` (172 lines). Zero unit test coverage.
- **Suggested Fix**: Split into `sop_generator.py`, `batch_record_generator.py`, `pdf_base.py`. Add comprehensive unit tests.
- **Effort**: XL

### [TD-0003] Frontend protocol editor is 2700+ lines
- **Category**: Code Smells
- **Severity**: Critical
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`
- **Description**: Single component with 1,341 lines of script handling graph editing, versioning, approval, equipment conflicts, branch validation, and timeline management. The `onDrop()` handler alone is 150+ lines with 4+ levels of nesting.
- **Suggested Fix**: Extract into `VersionManager.svelte`, `EquipmentValidator.svelte`, `TimelineManager.svelte`. Break `onDrop()` into `handleDropUnitOp()`, `handleDropProcessStart()`, `handleDropSwimLane()`.
- **Effort**: XL

### [TD-0004] Frontend project detail is 1700+ lines
- **Category**: Code Smells
- **Severity**: Critical
- **Location**: `frontend/src/routes/projects/[id]/+page.svelte`
- **Description**: Mixes data loading, tab management, protocol/run CRUD, activity filtering, and settings management in one component (619 script lines).
- **Suggested Fix**: Extract into `ProtocolsTab.svelte`, `RunsTab.svelte`, `ActivityTab.svelte`, `SettingsTab.svelte`.
- **Effort**: L

### [TD-0005] Frontend runs page is 1400+ lines
- **Category**: Code Smells
- **Severity**: High
- **Location**: `frontend/src/routes/runs/[id]/+page.svelte`
- **Description**: Mixed concerns: run state, role assignments, execution tracking, role wizard UI, PDF exports. Both `onMount()` and `$effect()` trigger `loadData()` redundantly.
- **Suggested Fix**: Extract role assignment logic and execution tracking into separate components. Remove redundant `onMount()`.
- **Effort**: L

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

### [TD-0009] Tab state management duplicated across routes
- **Category**: Code Smells
- **Severity**: High
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`, `frontend/src/routes/projects/[id]/+page.svelte`
- **Description**: Both files re-implement tab switching with URL params identically without sharing code.
- **Suggested Fix**: Extract shared logic to a `createTabState()` utility function.
- **Effort**: S

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
- **Severity**: Medium
- **Location**: `backend/app/services/ai_vision.py:169`
- **Description**: 159-line function with many if/elif branches for Ollama model name resolution. Could be a mapping dict.
- **Suggested Fix**: Replace with a dictionary lookup: `MODEL_MAP = {"name": "ollama_name", ...}`.
- **Effort**: S

### [TD-0014] Unused imports across backend (12+ instances)
- **Category**: Code Smells
- **Severity**: Low
- **Location**: `backend/app/schemas/auth.py:4`, `schemas/iam.py:3`, `schemas/ai.py:6`, `services/ai_config.py:10`, `services/pdf.py:8`, `api/endpoints/iam.py:1,5`, `api/endpoints/ai.py:11`, `models/execution.py:2`, `models/science.py:4`
- **Description**: Unused imports of `EmailStr`, `List`, `Optional`, `and_`, `DEFAULT_CONFIGS`, `date`, `desc`, `SUPPORTED_PROVIDERS`, etc.
- **Suggested Fix**: Run `isort` and remove unused imports.
- **Effort**: S

### [TD-0015] Redundant onMount + $effect pattern in frontend
- **Category**: Code Smells
- **Severity**: Low
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:29-41`, `frontend/src/routes/runs/[id]/+page.svelte:29-41`
- **Description**: Both `onMount()` and `$effect()` call `loadData()`, causing redundant initial loads.
- **Suggested Fix**: Remove `onMount()` calls; `$effect()` already handles initial load.
- **Effort**: S

### [TD-0016] Backend RequirePermission raises NotImplementedError
- **Category**: Missing Implementation
- **Severity**: High
- **Location**: `backend/app/core/deps.py:75-77`
- **Description**: `RequirePermission.__call__` raises `NotImplementedError`. The class exists but cannot be used directly — only the `require_permission()` factory works. Confusing API surface.
- **Suggested Fix**: Either remove the class (use factory only) or implement `__call__`. Document the intended pattern.
- **Effort**: S

### [TD-0017] Silent exception handlers in backend
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/science.py:1084-1087`, `backend/app/services/ai_vision.py:223`, `backend/app/services/ai_vision.py:238-239`
- **Description**: Multiple bare `except Exception: pass` blocks that silently swallow errors. Header color parsing failures are invisible. AI vision extraction errors are silently skipped with no logging.
- **Suggested Fix**: Catch specific exception types, add logging, provide user feedback where appropriate.
- **Effort**: S

### [TD-0018] console.log left in production API client
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `frontend/src/lib/api.ts:36`
- **Description**: `console.log(API_BASE + endpoint, config)` logs every API call to browser console in production. Leaks endpoint paths and request config.
- **Suggested Fix**: Remove or gate behind `import.meta.env.DEV` check.
- **Effort**: S

### [TD-0019] No error boundary component in frontend
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `frontend/src/` (project-wide)
- **Description**: No global error boundary exists. Unhandled promise rejections or component errors could crash the app with no recovery UI.
- **Suggested Fix**: Create `ErrorBoundary.svelte` wrapper and apply to route pages.
- **Effort**: M

### [TD-0020] Untyped dict parameters on PDF preview endpoints
- **Category**: Type Safety
- **Severity**: Critical
- **Location**: `backend/app/api/endpoints/science.py:1231`, `science.py:1287`
- **Description**: POST endpoints `preview_protocol_sop_pdf` and `preview_protocol_batch_record_pdf` accept `body: dict` with no Pydantic validation. Expected `graph` key is not enforced. Any JSON payload accepted.
- **Suggested Fix**: Create `class ProtocolGraphPayload(BaseModel): graph: dict[str, Any]` and use it in the endpoint signatures.
- **Effort**: S

### [TD-0021] pdf.py _format_value accepts Any
- **Category**: Type Safety
- **Severity**: Critical
- **Location**: `backend/app/services/pdf.py:154`
- **Description**: `_format_value(val: Any)` lacks type safety. Should accept a union of expected types.
- **Suggested Fix**: Change to `_format_value(val: str | float | int | dict | list | None) -> str`.
- **Effort**: S

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

### [TD-0024] catch (e: any) pattern throughout frontend
- **Category**: Type Safety
- **Severity**: High
- **Location**: `frontend/src/lib/api.ts:46,49,141`, multiple route files
- **Description**: All error catch blocks use `e: any` instead of `e: unknown` with type guards.
- **Suggested Fix**: Standardize to `catch (e: unknown)` with `e instanceof Error ? e.message : String(e)`.
- **Effort**: S

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

### [TD-0027] Children prop typed as any in Modal
- **Category**: Type Safety
- **Severity**: Medium
- **Location**: `frontend/src/lib/components/Modal.svelte:13`
- **Description**: `children: any` instead of proper Svelte 5 snippet typing.
- **Suggested Fix**: Use `children: Snippet` from Svelte 5 types.
- **Effort**: S

### [TD-0028] Image data stored as generic any[] in RoleWizard
- **Category**: Type Safety
- **Severity**: Medium
- **Location**: `frontend/src/lib/components/RoleWizard.svelte:75`
- **Description**: `stepImages = $state<Record<string, any[]>>({})` stores image metadata without typing.
- **Suggested Fix**: Define `ImageMetadata` interface with url, timestamp, etc.
- **Effort**: S

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

### [TD-0033] Hardcoded default secret key in config
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/core/config.py:8`
- **Description**: `secret_key: str = "dev-secret-key-change-in-production"` — hardcoded default JWT secret. If env var is not set in production, the app runs with a known secret.
- **Suggested Fix**: Fail loudly if default is used outside development. Add validation: error if `secret_key` starts with `"dev-"` and environment is production.
- **Effort**: S
- **Resolution**: Added `@model_validator` to `Settings` that emits a warning when `secret_key` starts with `"dev-"` and `debug` is `False`. All 253 tests pass.

### [TD-0034] Hardcoded database credentials in config
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/core/config.py:5-7`
- **Description**: Default PostgreSQL URL with `postgres:postgres` credentials. Will silently connect to local DB if env var is not set.
- **Suggested Fix**: Require explicit `RUNBOOK_DATABASE_URL` env var in production. No default for production environments.
- **Effort**: S
- **Resolution**: Added `@model_validator` to `Settings` that emits a warning when `database_url` contains `postgres:postgres@localhost` and `debug` is `False`. All 253 tests pass.

### [TD-0035] SQL echo=True logs all queries including sensitive data
- **Category**: Security
- **Severity**: ~~Critical~~ **WONTFIX**
- **Location**: `backend/app/db/session.py:11`
- **Description**: `echo=True` on the SQLAlchemy engine logs all SQL to stdout, including queries that may contain API keys, user data, or other sensitive information.
- **Suggested Fix**: Gate behind environment variable: `echo=settings.debug_sql` defaulting to `False`.
- **Effort**: S
- **Reason**: Already gated behind `settings.debug` (defaults to `False`). SQL echo is off in production. Users can check PostgreSQL audit logs for query tracing instead.

### [TD-0036] Untyped dict endpoint parameters bypass validation
- **Category**: Security
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/science.py:1231`, `science.py:1287`
- **Description**: `body: dict` parameters on PDF preview endpoints bypass Pydantic validation entirely. Could accept unexpected payload structures.
- **Suggested Fix**: Create Pydantic request schemas for all endpoints (overlaps with TD-0020).
- **Effort**: S

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
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/science.py`, `ai.py`, `iam.py`, `projects.py`
- **Description**: `select(...).where(Model.id == id)` + `scalar_one_or_none()` + 404 check is repeated 100+ times with no shared utility.
- **Suggested Fix**: Create a `get_or_404(db, Model, id)` utility function in a shared module.
- **Effort**: S

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

### [TD-0047] Mutable default argument in `log_audit()` — shared dict bug risk
- **Category**: Code Smells
- **Severity**: High
- **Location**: `backend/app/services/audit.py:12`
- **Description**: `changes: Dict[str, Any] = {}` uses a mutable default argument. If any caller accidentally mutates the dict in-place before passing it, the default object is shared across all calls, leading to data leaking between audit entries. Classic Python gotcha.
- **Suggested Fix**: Change to `changes: Dict[str, Any] | None = None` and initialize inside the function: `changes = changes or {}`.
- **Effort**: S

### [TD-0048] Incomplete permission check on notification channel subscription list
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/notifications.py:350-352`
- **Description**: When listing subscriptions for an org-level channel, the ownership check has a `pass` statement: `if channel.org_id: pass`. This means **any authenticated user** can list subscriptions for any org channel — no org membership verification is performed. Other endpoints in the same file (lines 310-311, 377-378) correctly call `_require_org_admin()`.
- **Suggested Fix**: Replace the `pass` with an org membership check. At minimum verify the user belongs to the org: `await _require_org_member(db, current_user.id, channel.org_id)`. Or use `_require_org_admin` if only admins should see subscriptions.
- **Effort**: S
- **Resolution**: Added `_require_org_member` helper that verifies org membership (any role). Replaced `pass` with `await _require_org_member(db, current_user.id, channel.org_id)`. All 35 notification tests pass.

### [TD-0049] AI settings endpoint has no authentication
- **Category**: Security
- **Severity**: High
- **Location**: `backend/app/api/endpoints/ai.py:61-62`
- **Description**: `GET /ai/settings` lists all `AiProviderConfig` rows without any auth dependency. Unauthenticated users can discover AI provider configurations, model names, and capability mappings. Every other endpoint in the file requires `get_current_user`.
- **Suggested Fix**: Add `current_user: User = Depends(get_current_user)` to the endpoint signature. Consider adding org-admin requirement since these are sensitive configs.
- **Effort**: S

### [TD-0050] Image upload accepts unsanitized file extensions
- **Category**: Security
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/ai.py:276`
- **Description**: `os.path.splitext(file.filename or "image.jpg")[1]` extracts the extension directly from the client-supplied filename with no allowlist validation. Arbitrary extensions like `.exe`, `.sh`, `.html` are stored to disk. While the UUID-based filename mitigates direct exploitation, serving these files later could be dangerous.
- **Suggested Fix**: Add an allowlist: `ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}`. Reject or default to `.jpg` if the extension is not in the allowlist.
- **Effort**: S

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

### [TD-0055] Silent `// silent` catch blocks swallow errors on user actions
- **Category**: Missing Implementation
- **Severity**: Medium
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:562,589`, `frontend/src/routes/+page.svelte:94`
- **Description**: Catch blocks with `// silent` comments swallow errors on user-initiated actions (renaming protocol, updating description, loading activity). Users get no feedback when these operations fail — the UI just doesn't update.
- **Suggested Fix**: Replace with `toast.error()` calls (once F-0009 toast system is implemented) or at minimum set an error state variable.
- **Effort**: S

### [TD-0056] Duplicate `timeAgo` utility function
- **Category**: Code Smells
- **Severity**: Low
- **Location**: `frontend/src/routes/+page.svelte:105`, `frontend/src/lib/components/VersionHistoryDrawer.svelte:25`
- **Description**: The `timeAgo()` relative timestamp formatter is implemented twice in separate files with the same logic.
- **Suggested Fix**: Extract to `frontend/src/lib/utils.ts` and import from both locations.
- **Effort**: S

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
- **Severity**: Low
- **Location**: `frontend/src/lib/components/Modal.svelte`
- **Description**: Custom `Modal.svelte` does not trap focus inside the modal when open. Users can Tab out of the modal into background content. No Escape key handler to close. Does not meet WCAG 2.1 dialog accessibility requirements.
- **Suggested Fix**: Use `bits-ui` Dialog primitive (already a dependency) which includes focus trapping, Escape handling, and ARIA attributes. Or add a focus-trap library.
- **Effort**: M

### [TD-0061] No pagination on settings member and subscription lists
- **Category**: Architecture
- **Severity**: Medium
- **Location**: `frontend/src/routes/settings/+page.svelte:140,362`
- **Description**: Organization members and channel subscriptions are loaded as complete lists with no pagination or virtual scrolling. In orgs with hundreds of members, this will cause slow initial loads and high memory usage.
- **Suggested Fix**: Add server-side pagination (limit/offset) to the member and subscription list endpoints. Add pagination controls to the settings UI.
- **Effort**: M

### [TD-0062] 21 failing tests — auth/permission checks return 200 instead of 401/403
- **Category**: Testing Gaps
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/tests/integration/test_auth_api.py`, `test_projects_api.py`, `test_science_api.py`, `backend/tests/unit/test_permissions.py`
- **Description**: 21 tests fail because permission and authentication checks are not rejecting unauthorized requests. `test_login_wrong_password` gets 200 instead of 401; project/protocol/run permission tests get 200 instead of 403; unit permission tests assert `True` where `False` is expected. This indicates the auth/permission middleware or dependency is broken or bypassed — wrong passwords are accepted and permission checks pass for users without access.
- **Suggested Fix**: Investigate the `get_current_user` dependency and `require_permission()` factory in `backend/app/core/deps.py`. Check if password hashing/verification in the login endpoint is broken. Fix the root cause so all 21 tests pass.
- **Effort**: M
- **Resolution**: Three root causes fixed: (1) `.env` had `RUNBOOK_AUTH_ENABLED=false` leaking into tests — added `os.environ["RUNBOOK_AUTH_ENABLED"] = "true"` at top of `conftest.py`. (2) Four unauthenticated tests expected 403 but `HTTPBearer(auto_error=False)` yields 401 — corrected assertions. (3) Test project fixtures lacked `settings={"permissions_enabled": True}`, causing implicit EDIT for all org members — added to `conftest.py` and `test_permissions.py`. All 253 tests pass.
