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
| Code Smells | 0 | 3 | 6 | 0 | 9 |
| Type Safety | 0 | 4 | 1 | 0 | 5 |
| Testing Gaps | 2 | 2 | 0 | 0 | 4 |
| Architecture | 2 | 4 | 2 | 0 | 8 |
| **Total** | **4** | **13** | **9** | **0** | **26** |

*Last updated: 2026-03-25*

---

## Findings

<!-- New findings are appended below this line -->

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

### [TD-0051] Backend iam.py is 784 lines with mixed concerns
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `backend/app/api/endpoints/iam.py`
- **Description**: Single file handles organization CRUD, team CRUD, member management, permission checking, and user profile operations. Approaching the 500-line threshold significantly.
- **Suggested Fix**: Split into `organizations.py`, `teams.py`, `members.py`. Share permission helpers via `services/iam_service.py`.
- **Effort**: L

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

### [TD-0059] Equipment conflict detection uses O(n²) algorithm
- **Category**: Code Smells
- **Severity**: Medium
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte` (detectEquipmentConflicts function)
- **Description**: Equipment conflict detection iterates over all node pairs for each edge, making it O(n²). Also calls `nodes.some((n: any) => n.parentId != null)` on every change. This runs on every `nodes`/`edges` reactive update, including viewport-only changes.
- **Suggested Fix**: Use a `Set` or `Map` for O(1) lookups. Only recalculate when node/edge/equipment data actually changes (not on position-only moves). Debounce the effect.
- **Effort**: M

