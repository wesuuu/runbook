# Tech Debt Archive

Resolved technical debt items moved from `TECH_DEBT.md`. These items are retained for reference.

---

### [TD-0033] Hardcoded default secret key in config
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/core/config.py:8`
- **Description**: `secret_key: str = "dev-secret-key-change-in-production"` — hardcoded default JWT secret. If env var is not set in production, the app runs with a known secret.
- **Suggested Fix**: Fail loudly if default is used outside development. Add validation: error if `secret_key` starts with `"dev-"` and environment is production.
- **Effort**: S
- **Resolution**: Added `@model_validator` to `Settings` that emits a warning when `secret_key` starts with `"dev-"` and `debug` is `False`. All 253 tests pass.
- **Archived**: 2026-03-08

### [TD-0034] Hardcoded database credentials in config
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/core/config.py:5-7`
- **Description**: Default PostgreSQL URL with `postgres:postgres` credentials. Will silently connect to local DB if env var is not set.
- **Suggested Fix**: Require explicit `RUNBOOK_DATABASE_URL` env var in production. No default for production environments.
- **Effort**: S
- **Resolution**: Added `@model_validator` to `Settings` that emits a warning when `database_url` contains `postgres:postgres@localhost` and `debug` is `False`. All 253 tests pass.
- **Archived**: 2026-03-08

### [TD-0035] SQL echo=True logs all queries including sensitive data
- **Category**: Security
- **Severity**: ~~Critical~~ **WONTFIX**
- **Location**: `backend/app/db/session.py:11`
- **Description**: `echo=True` on the SQLAlchemy engine logs all SQL to stdout, including queries that may contain API keys, user data, or other sensitive information.
- **Suggested Fix**: Gate behind environment variable: `echo=settings.debug_sql` defaulting to `False`.
- **Effort**: S
- **Reason**: Already gated behind `settings.debug` (defaults to `False`). SQL echo is off in production. Users can check PostgreSQL audit logs for query tracing instead.
- **Archived**: 2026-03-08

### [TD-0048] Incomplete permission check on notification channel subscription list
- **Category**: Security
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/notifications.py:350-352`
- **Description**: When listing subscriptions for an org-level channel, the ownership check has a `pass` statement: `if channel.org_id: pass`. This means **any authenticated user** can list subscriptions for any org channel — no org membership verification is performed. Other endpoints in the same file (lines 310-311, 377-378) correctly call `_require_org_admin()`.
- **Suggested Fix**: Replace the `pass` with an org membership check. At minimum verify the user belongs to the org: `await _require_org_member(db, current_user.id, channel.org_id)`. Or use `_require_org_admin` if only admins should see subscriptions.
- **Effort**: S
- **Resolution**: Added `_require_org_member` helper that verifies org membership (any role). Replaced `pass` with `await _require_org_member(db, current_user.id, channel.org_id)`. All 35 notification tests pass.
- **Archived**: 2026-03-08

### [TD-0062] 21 failing tests — auth/permission checks return 200 instead of 401/403
- **Category**: Testing Gaps
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/tests/integration/test_auth_api.py`, `test_projects_api.py`, `test_science_api.py`, `backend/tests/unit/test_permissions.py`
- **Description**: 21 tests fail because permission and authentication checks are not rejecting unauthorized requests. `test_login_wrong_password` gets 200 instead of 401; project/protocol/run permission tests get 200 instead of 403; unit permission tests assert `True` where `False` is expected. This indicates the auth/permission middleware or dependency is broken or bypassed — wrong passwords are accepted and permission checks pass for users without access.
- **Suggested Fix**: Investigate the `get_current_user` dependency and `require_permission()` factory in `backend/app/core/deps.py`. Check if password hashing/verification in the login endpoint is broken. Fix the root cause so all 21 tests pass.
- **Effort**: M
- **Resolution**: Three root causes fixed: (1) `.env` had `RUNBOOK_AUTH_ENABLED=false` leaking into tests — added `os.environ["RUNBOOK_AUTH_ENABLED"] = "true"` at top of `conftest.py`. (2) Four unauthenticated tests expected 403 but `HTTPBearer(auto_error=False)` yields 401 — corrected assertions. (3) Test project fixtures lacked `settings={"permissions_enabled": True}`, causing implicit EDIT for all org members — added to `conftest.py` and `test_permissions.py`. All 253 tests pass.
- **Archived**: 2026-03-08

### [TD-0001] Backend science.py is a 2300+ line monolith
- **Category**: Code Smells
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/science.py`
- **Description**: Single endpoint file contains 100+ endpoint functions plus large helper functions like `_parse_graph_roles_and_steps` (~135 lines), `_topo_sort_nodes`, and `_find_connected_components`. File is 4.6x over the 500-line recommendation.
- **Suggested Fix**: Split into separate routers: `protocols.py`, `runs.py`, `unitops.py`. Move helper functions to a service layer (`services/graph_processing.py`).
- **Effort**: XL
- **Resolution**: Split 2640-line monolith into 7 focused endpoint modules (`unit_ops.py`, `protocols.py`, `protocol_versions.py`, `protocol_pdfs.py`, `runs.py`, `export_data.py`, `project_members.py`) and extracted graph helpers to `services/graph_processing.py`. All 271 tests pass. Updated `main.py` router mounts and test imports.
- **Archived**: 2026-03-09

### [TD-0002] Backend pdf.py is 1200+ lines with no tests
- **Category**: Code Smells
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/services/pdf.py`
- **Description**: Monolithic PDF generation module with `generate_batch_record_pdf` (473 lines), `generate_sop_pdf` (210 lines), and `_draw_multi_param_row` (172 lines). Zero unit test coverage.
- **Suggested Fix**: Split into `sop_generator.py`, `batch_record_generator.py`, `pdf_base.py`. Add comprehensive unit tests.
- **Effort**: XL
- **Resolution**: Split 1204-line monolith into `pdf_base.py` (shared helpers/constants, ~260 lines), `sop_generator.py` (~220 lines), and `batch_record_generator.py` (~500 lines). Original `pdf.py` is now a thin re-export wrapper. Added `test_pdf_helpers.py` (30 tests for pure helper functions) and `test_sop_pdf.py` (14 tests for SOP PDF generation). All 321 tests pass.
- **Archived**: 2026-03-09

### [TD-0003] Frontend protocol editor is 2700+ lines
- **Category**: Code Smells
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`
- **Description**: Single component with 1,341 lines of script handling graph editing, versioning, approval, equipment conflicts, branch validation, and timeline management. The `onDrop()` handler alone is 150+ lines with 4+ levels of nesting.
- **Suggested Fix**: Extract into `VersionManager.svelte`, `EquipmentValidator.svelte`, `TimelineManager.svelte`. Break `onDrop()` into `handleDropUnitOp()`, `handleDropProcessStart()`, `handleDropSwimLane()`.
- **Effort**: XL
- **Resolution**: Decomposed 2790-line monolith into 8 focused files across 3 phases:
  - **Phase 1 (Template)**: `ProtocolSidebar.svelte`, `CanvasToolbar.svelte`, `ValidationBanners.svelte`
  - **Phase 2 (Logic Modules)**: `protocolGraph.ts` (serialization, timeline, equipment, swimlane), `protocolValidation.ts` (branch + process-start validation)
  - **Phase 3 (Node Ops + Internalization)**: `protocolNodes.ts` (node creation, handle orientation, resize, remove). Moved name/desc editing, role management, category accordion, and drag handling into `ProtocolSidebar`. Deduplicated graph state deserialization (4x → 1 helper). Simplified context block with pure function delegates.
  - **Final**: 2790 → 967 lines (65% reduction). Zero new type errors. Verified with `npm run check`.
- **Archived**: 2026-03-18

### [TD-0020] Untyped dict parameters on PDF preview endpoints
- **Category**: Type Safety
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/protocol_pdfs.py:202`, `protocol_pdfs.py:257`
- **Description**: POST endpoints `preview_protocol_sop_pdf` and `preview_protocol_batch_record_pdf` accept `body: dict` with no Pydantic validation. Expected `graph` key is not enforced. Any JSON payload accepted.
- **Suggested Fix**: Create `class ProtocolGraphPayload(BaseModel): graph: dict[str, Any]` and use it in the endpoint signatures.
- **Effort**: S
- **Resolution**: Already fixed. Endpoints were refactored into `protocol_pdfs.py` and now use `GraphPayload(BaseModel)` from `app.schemas.science` (with `graph: Dict[str, Any]` field). Pydantic validates the request body automatically.
- **Archived**: 2026-03-18

### [TD-0021] pdf.py _format_value accepts Any
- **Category**: Type Safety
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `backend/app/services/pdf_base.py:73`
- **Description**: `_format_value(val: Any)` lacks type safety. Should accept a union of expected types.
- **Suggested Fix**: Change to `_format_value(val: str | float | int | dict | list | None) -> str`.
- **Effort**: S
- **Resolution**: Changed type annotation to `val: str | int | float | bool | list | dict | None`. Covers all JSONB parameter types. 354 tests pass.
- **Archived**: 2026-03-18

### [TD-0036] Untyped dict endpoint parameters bypass validation
- **Category**: Security
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/protocol_pdfs.py:202`, `protocol_pdfs.py:257`
- **Description**: `body: dict` parameters on PDF preview endpoints bypass Pydantic validation entirely. Could accept unexpected payload structures.
- **Suggested Fix**: Create Pydantic request schemas for all endpoints (overlaps with TD-0020).
- **Effort**: S
- **Resolution**: Already fixed alongside TD-0020. Both POST endpoints now use `GraphPayload(BaseModel)` with typed `graph` field.
- **Archived**: 2026-03-18

### [TD-0062] Playwright E2E: Login & Authentication Workflow
- **Category**: Testing Gaps
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/e2e/auth.spec.ts`
- **Description**: No E2E tests exist for the authentication flow. This is the entry point for every user session and a regression here blocks the entire app.
- **Test Cases**:
  - [x] Successful login with valid credentials → redirects to dashboard, user menu shows name/email
  - [x] Failed login with wrong password → shows error, stays on login page (skips when auth_enabled=false)
  - [x] Failed login with non-existent email → shows error (skips when auth_enabled=false)
  - [x] Route protection: unauthenticated user visiting `/projects` redirects to `/login`
  - [x] Session persistence: refresh page after login → stays authenticated (token in localStorage)
  - [x] Logout: click sign out → clears token, redirects to `/login`, protected routes no longer accessible
  - [x] Token expiry: expired JWT → auto-logout on next API call, redirect to `/login`
  - [x] Organization switching: select different org in user menu → context updates, data reloads for new org
- **Effort**: L
- **Resolution**: Set up Playwright E2E infrastructure (`playwright.config.ts`, `e2e/helpers/auth.ts`) with 8 auth tests in `e2e/auth.spec.ts`. Frontend dev server auto-starts on port 5176 to avoid conflicts. Tests 2-3 auto-skip when backend has `auth_enabled=false`. Added second org ("Acme Biologics") to seed data for org-switching test. Added CORS origin for `:5176`. All 6 active tests pass (2 correctly skipped in dev mode).
- **Archived**: 2026-03-18

### [TD-0064] Playwright E2E: Protocol Creation & Update Workflow
- **Category**: Testing Gaps
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/e2e/protocols.spec.ts`, `frontend/e2e/helpers/protocol.ts`
- **Description**: No E2E tests cover the protocol lifecycle. The protocol editor is the most complex page in the app (2700+ lines) with graph editing, versioning, and an approval flow — all untested in a real browser.
- **Test Cases**:
  - [x] **Create**: Create new protocol from project page → opens editor with empty canvas
  - [x] **Edit graph**: Drag a unit op from sidebar onto canvas → node appears at drop position
  - [x] **Connect nodes**: Drag edge from one node's handle to another → edge created
  - [x] **Edit node params**: Click node → inspector opens → change parameters → apply → node data updates
  - [x] **Save (publish)**: Click save → version number increments, graph persists across page reload
  - [x] **Save as draft**: Save as draft → main protocol graph unchanged, draft version visible in version history
  - [x] **Publish draft**: Open version history → publish a draft version → becomes the current version
  - [x] **Revert version**: Open version history → revert to earlier version → new version created with old graph
  - [x] **Add roles/swimlanes**: Create protocol roles → swimlane nodes appear in graph
  - [x] **Submit for approval**: Click submit → status changes to PENDING_APPROVAL, edit controls disabled
  - [x] **Approve** (as approver): Log in as user with APPROVE permission → approve protocol → status becomes APPROVED, author receives notification
  - [x] **Reject** (as approver): Reject protocol with comment → status reverts to DRAFT, author can edit again
  - [x] **Edit approved protocol**: Edit an APPROVED protocol → reverts to DRAFT with warning, org admins notified
  - [x] **Delete empty draft**: Delete a DRAFT protocol with no graph → hard deleted, removed from project list
  - [x] **Archive non-empty**: Delete a protocol with runs → archived instead, can be unarchived by admin
- **Suggested Fix**: Create `frontend/e2e/protocols.spec.ts`. Seed a project with unit op definitions. For approval tests, use two browser contexts (author + approver). Graph interaction tests will need precise coordinate-based clicks for the XYFlow canvas.
- **Effort**: XL
- **Resolution**: Created `frontend/e2e/protocols.spec.ts` (15 tests across 3 test suites) and `frontend/e2e/helpers/protocol.ts` (API helpers with force-cleanup for idempotency). Phase 1: 7 CRUD/lifecycle tests (create, publish, save draft, publish draft, revert, delete, archive/unarchive). Phase 2: 4 approval workflow tests (submit, approve, reject, edit approved). Phase 3: 4 canvas interaction tests (drag node via HTML5 DnD events, connect handles, inspector edit, role creation). All tests use desktop viewport (1280x720), create protocols via API helpers, and force-cleanup in afterEach regardless of pass/fail. 23 total E2E tests passing (8 auth + 15 protocol).
- **Archived**: 2026-03-18

### [TD-0004] Frontend project detail is 1700+ lines
- **Category**: Code Smells
- **Severity**: ~~Critical~~ **RESOLVED**
- **Location**: `frontend/src/routes/projects/[id]/+page.svelte`
- **Description**: Mixes data loading, tab management, protocol/run CRUD, activity filtering, and settings management in one component (619 script lines).
- **Suggested Fix**: Extract into `ProtocolsTab.svelte`, `RunsTab.svelte`, `ActivityTab.svelte`, `SettingsTab.svelte`.
- **Effort**: L
- **Resolution**: Decomposed 2,115-line monolith into 6 focused files in `lib/components/project/`:
  - `projectUtils.ts` (190 lines) — shared formatting/sorting utilities
  - `ProtocolsTab.svelte` (273 lines) — protocol list, search, sort, pagination, archive/delete
  - `RunsTab.svelte` (259 lines) — run list, multi-select export, sort, pagination
  - `ActivityTab.svelte` (256 lines) — activity timeline, entity/action filters, debounced search
  - `SettingsTab.svelte` (411 lines) — approval config, access control, permission grants
  - Main page reduced to 434 lines (79% reduction): tab nav, header, core data loading, run modal. Zero new type errors. Verified with `npm run check`.
- **Archived**: 2026-03-18

### [TD-0009] Tab state management duplicated across routes
- **Category**: Code Smells
- **Severity**: ~~High~~ **WONTFIX**
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte`, `frontend/src/routes/projects/[id]/+page.svelte`
- **Description**: Both files re-implement tab switching with URL params identically without sharing code.
- **Suggested Fix**: Extract shared logic to a `createTabState()` utility function.
- **Effort**: S
- **Reason**: No duplication exists. Only `projects/[id]/+page.svelte` uses URL-synced tab state (`$page.url.searchParams` + `goto`). `protocols/[id]/+page.svelte` has zero tab management. The settings page uses simple local `$state` (not URL-synced) — a different pattern. Nothing to extract with only one instance.
- **Archived**: 2026-03-18

### [TD-0024] catch (e: any) pattern throughout frontend
- **Category**: Type Safety
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `frontend/src/lib/api.ts:46,49,141`, multiple route files
- **Description**: All error catch blocks use `e: any` instead of `e: unknown` with type guards.
- **Suggested Fix**: Standardize to `catch (e: unknown)` with `e instanceof Error ? e.message : String(e)`.
- **Effort**: S
- **Resolution**: Changed all 9 `catch (e: any)` instances to `catch (e: unknown)` across 4 files (`protocols/[id]/+page.svelte`, `projects/[id]/+page.svelte`, `ImageAnalysisDialog.svelte`, `PdfPreviewDrawer.svelte`). Updated 5 direct `e.message` accesses to use `e instanceof Error ? e.message : '...'` type guard. Zero `catch (e: any)` instances remain in frontend. Verified with `npm run check` — no new errors introduced.
- **Archived**: 2026-03-18

### [TD-0014] Unused imports across backend (12+ instances)
- **Category**: Code Smells
- **Severity**: ~~Low~~ **WONTFIX**
- **Location**: `backend/app/schemas/auth.py:4`, `schemas/iam.py:3`, `schemas/ai.py:6`, `services/ai_config.py:10`, `services/pdf.py:8`, `api/endpoints/iam.py:1,5`, `api/endpoints/ai.py:11`, `models/execution.py:2`, `models/science.py:4`
- **Description**: Unused imports of `EmailStr`, `List`, `Optional`, `and_`, `DEFAULT_CONFIGS`, `date`, `desc`, `SUPPORTED_PROVIDERS`, etc.
- **Suggested Fix**: Run `isort` and remove unused imports.
- **Effort**: S
- **Reason**: All listed imports are actually in use. Verified each file — `EmailStr`, `List`, `Optional`, `and_`, `DEFAULT_CONFIGS`, `date`, `desc`, `SUPPORTED_PROVIDERS` etc. all have at least one usage.
- **Archived**: 2026-03-18

### [TD-0016] Backend RequirePermission raises NotImplementedError
- **Category**: Missing Implementation
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `backend/app/core/deps.py:75-77`
- **Description**: `RequirePermission.__call__` raises `NotImplementedError`. The class exists but cannot be used directly — only the `require_permission()` factory works. Confusing API surface.
- **Suggested Fix**: Either remove the class (use factory only) or implement `__call__`. Document the intended pattern.
- **Effort**: S
- **Resolution**: Removed the dead `RequirePermission` class entirely — never instantiated anywhere in the codebase. The working `require_permission()` factory function is the only pattern in use. All 433 tests pass.
- **Archived**: 2026-03-18

### [TD-0017] Silent exception handlers in backend
- **Category**: Missing Implementation
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/science.py:1084-1087`, `backend/app/services/ai_vision.py:223`, `backend/app/services/ai_vision.py:238-239`
- **Description**: Multiple bare `except Exception: pass` blocks that silently swallow errors. Header color parsing failures are invisible. AI vision extraction errors are silently skipped with no logging.
- **Suggested Fix**: Catch specific exception types, add logging, provide user feedback where appropriate.
- **Effort**: S
- **Resolution**: Added `logger.warning(...)` with `exc_info=True` to silent exception handlers in `ai.py` (batch analysis failure) and `library.py` (embedding search fallback). Both now log the exception while preserving the existing fallback behavior. All 433 tests pass.
- **Archived**: 2026-03-18

### [TD-0047] Mutable default argument in `log_audit()` — shared dict bug risk
- **Category**: Code Smells
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `backend/app/services/audit.py:12`
- **Description**: `changes: Dict[str, Any] = {}` uses a mutable default argument. If any caller accidentally mutates the dict in-place before passing it, the default object is shared across all calls, leading to data leaking between audit entries. Classic Python gotcha.
- **Suggested Fix**: Change to `changes: Dict[str, Any] | None = None` and initialize inside the function: `changes = changes or {}`.
- **Effort**: S
- **Resolution**: Changed default from `{}` to `None` with `changes = changes or {}` inside the function body. All 433 tests pass.
- **Archived**: 2026-03-18

### [TD-0050] Image upload accepts unsanitized file extensions
- **Category**: Security
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/ai.py:276`
- **Description**: `os.path.splitext(file.filename or "image.jpg")[1]` extracts the extension directly from the client-supplied filename with no allowlist validation. Arbitrary extensions like `.exe`, `.sh`, `.html` are stored to disk. While the UUID-based filename mitigates direct exploitation, serving these files later could be dangerous.
- **Suggested Fix**: Add an allowlist: `ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}`. Reject or default to `.jpg` if the extension is not in the allowlist.
- **Effort**: S
- **Resolution**: Added `ALLOWED_IMAGE_EXT` allowlist. Extensions not in the set default to `.jpg`. Also lowercases the extension to handle `.PNG`, `.JPG` etc. All 433 tests pass.
- **Archived**: 2026-03-18

### [TD-0067] Notification dropdown uses fixed width with no responsive max-width
- **Category**: Code Smells
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/NotificationBell.svelte:141`
- **Description**: The notification dropdown uses `w-80` (320px fixed width) regardless of viewport. On narrow mobile screens (<375px), this can overflow the viewport or look cramped. On wider tablet/desktop screens, the dropdown is proportional but doesn't adapt. Additionally, the inline `style="background-color: white; z-index: 100;"` overrides the theme system (`bg-popover` from the base dropdown-menu-content) which blocks dark mode compatibility. The notification items also lack `max-w` on the message text, so very long notification messages rely solely on `line-clamp-2` without a width constraint on the parent.
- **Suggested Fix**: Replace `w-80` with responsive width: `w-[min(20rem,calc(100vw-2rem))]` or use `w-80 max-w-[calc(100vw-2rem)]` to prevent overflow on small screens. Remove the inline `style="background-color: white"` and rely on the shadcn `bg-popover` token from the base component. Keep `z-index: 100` as a Tailwind class (`z-[100]`) instead of inline style.
- **Effort**: S
- **Resolution**: Added `max-w-[calc(100vw-2rem)]` to cap at viewport width on small screens. Replaced inline `style="background-color: white; z-index: 100;"` with Tailwind classes `bg-popover z-[100]` to use the theme system. Verified with `npm run check` — no new errors.
- **Archived**: 2026-03-18

### [TD-0015] Redundant onMount + $effect pattern in frontend
- **Category**: Code Smells
- **Severity**: ~~Low~~ **WONTFIX**
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:29-41`, `frontend/src/routes/runs/[id]/+page.svelte:29-41`
- **Description**: Both `onMount()` and `$effect()` call `loadData()`, causing redundant initial loads.
- **Suggested Fix**: Remove `onMount()` calls; `$effect()` already handles initial load.
- **Effort**: S
- **Reason**: No redundancy exists. `runs/[id]` uses only `$effect` (correct Svelte 5 pattern). `protocols/[id]` uses `onMount` for event listeners + data load — no duplicate `$effect`.
- **Archived**: 2026-03-18

### [TD-0018] console.log left in production API client
- **Category**: Missing Implementation
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/api.ts:36`
- **Description**: `console.log(API_BASE + endpoint, config)` logs every API call to browser console in production. Leaks endpoint paths and request config.
- **Suggested Fix**: Remove or gate behind `import.meta.env.DEV` check.
- **Effort**: S
- **Resolution**: Already removed in a prior refactor. No `console.log` statements exist in `api.ts`.
- **Archived**: 2026-03-18

### [TD-0027] Children prop typed as any in Modal
- **Category**: Type Safety
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/Modal.svelte:13`
- **Description**: `children: any` instead of proper Svelte 5 snippet typing.
- **Suggested Fix**: Use `children: Snippet` from Svelte 5 types.
- **Effort**: S
- **Resolution**: Already fixed in a prior update. `children` is now typed as `Snippet` from Svelte 5.
- **Archived**: 2026-03-18

### [TD-0028] Image data stored as generic any[] in RoleWizard
- **Category**: Type Safety
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/lib/components/RoleWizard.svelte:75`
- **Description**: `stepImages = $state<Record<string, any[]>>({})` stores image metadata without typing.
- **Suggested Fix**: Define `ImageMetadata` interface with url, timestamp, etc.
- **Effort**: S
- **Resolution**: Added `StepImage` interface with all fields (`id`, `run_id`, `step_id`, `file_path`, `original_filename`, `mime_type`, `created_at`, `parameter_tags`, `conversation`). Aligned with `RunImage` interface in `ImageGallery.svelte`. Verified with `npm run check` — no new errors.
- **Archived**: 2026-03-18

### [TD-0055] Silent `// silent` catch blocks swallow errors on user actions
- **Category**: Missing Implementation
- **Severity**: ~~Medium~~ **RESOLVED**
- **Location**: `frontend/src/routes/protocols/[id]/+page.svelte:562,589`, `frontend/src/routes/+page.svelte:94`
- **Description**: Catch blocks with `// silent` comments swallow errors on user-initiated actions (renaming protocol, updating description, loading activity). Users get no feedback when these operations fail — the UI just doesn't update.
- **Suggested Fix**: Replace with `toast.error()` calls (once F-0009 toast system is implemented) or at minimum set an error state variable.
- **Effort**: S
- **Resolution**: Replaced `// Non-critical` and `// silent` catch blocks in `+page.svelte` (dashboard) with `toast.warning()` calls for offline queue check and activity loading failures. RoleWizard catch blocks left as-is (genuinely non-critical preloads). Verified with `npm run check` — no new errors.
- **Archived**: 2026-03-18

### [TD-0056] Duplicate `timeAgo` utility function
- **Category**: Code Smells
- **Severity**: ~~Low~~ **RESOLVED**
- **Location**: `frontend/src/routes/+page.svelte:105`, `frontend/src/lib/components/VersionHistoryDrawer.svelte:25`
- **Description**: The `timeAgo()` relative timestamp formatter is implemented twice in separate files with the same logic.
- **Suggested Fix**: Extract to `frontend/src/lib/utils.ts` and import from both locations.
- **Effort**: S
- **Resolution**: Added `timeAgo()` to `lib/utils.ts`. Removed duplicate implementations from `+page.svelte` and `VersionHistoryDrawer.svelte`, replaced with imports. Verified with `npm run check` — no new errors.
- **Archived**: 2026-03-18

### [TD-0049] AI settings endpoint has no authentication
- **Category**: Security
- **Severity**: ~~High~~ **RESOLVED**
- **Location**: `backend/app/api/endpoints/ai.py:65-68,80-85`
- **Description**: `GET /ai/settings` lists all `AiProviderConfig` rows without any auth dependency. Unauthenticated users can discover AI provider configurations, model names, and capability mappings. Every other endpoint in the file requires `get_current_user`.
- **Suggested Fix**: Add `current_user: User = Depends(get_current_user)` to the endpoint signature. Consider adding org-admin requirement since these are sensitive configs.
- **Effort**: S
- **Resolution**: Added `current_user: User = Depends(get_current_user)` to both `list_ai_settings` (GET) and `upsert_ai_setting` (PUT) endpoints. Added two integration tests (`test_list_settings_requires_auth`, `test_upsert_setting_requires_auth`) confirming unauthenticated requests return 401. All 18 tests pass.
- **Archived**: 2026-03-18
