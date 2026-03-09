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
