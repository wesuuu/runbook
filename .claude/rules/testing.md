---
paths:
  - "backend/tests/**"
  - "frontend/src/**/*.test.ts"
  - "frontend/e2e/**"
  - "frontend/vitest.config.*"
  - "frontend/playwright.config.*"
---

# Testing Patterns

## Backend (pytest-asyncio)

### Fixture Hierarchy

- `test_engine` (session scope): creates test DB, drops/recreates schema between runs
- `db_session` (function scope): per-test SAVEPOINT transaction, auto-rollback
- `client` (function scope): httpx AsyncClient with ASGI transport
- `test_org`, `test_user`, `auth_headers`: pre-built org/user/JWT for authenticated tests

### Key Conventions

- All tests are `async def` with `@pytest.mark.asyncio` (auto mode, no decorator needed)
- Use `await db_session.flush()` (not commit) to work within SAVEPOINT
- DB extensions (`vector`, `tsvector`) are created in conftest
- `NullPool` avoids connection pooling issues in tests
- Cross-org isolation: `second_org`/`second_user` fixtures test that orgs can't see each other's data

### Integration Test Pattern

```python
async def test_create_project(client: AsyncClient, auth_headers: dict, test_org: Organization):
    resp = await client.post("/projects/", json={...}, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Project"
```

### Mocking Strategy

- Patch at the service layer: `patch("app.services.chat_service._call_llm")`
- Email: `patch("app.api.endpoints.auth.get_email_provider")`
- Module-level `autouse=True` fixtures for test-wide mocks
- Return realistic data structures matching service signatures

## Frontend Unit Tests (vitest)

### Config

- `frontend/vitest.config.ts` with `$lib` alias
- jsdom environment
- Files: `frontend/src/**/*.test.ts`

### Patterns

```typescript
describe('api validation', () => {
    it('throws in dev mode on schema mismatch', () => {
        expect(() => _validateResponse(data, MySchema)).toThrow();
    });
    it('warns in prod mode', () => {
        vi.spyOn(console, 'warn');
        // override import.meta.env.DEV
    });
});
```

- `vi.mock()` for module mocks
- `vi.spyOn()` for console/side-effect assertions
- Test both dev and prod code paths for validation behavior

## Frontend E2E (Playwright)

### Auth Helper

```typescript
// API login -- bypasses UI form
const token = await loginViaApi(page, 'admin');
// Token injected via localStorage on a public route
```

### Auth Detection

Tests dynamically detect if auth is enabled:
```typescript
const authOn = await isAuthEnabled(page);
test.skip(!authOn, 'Backend has auth_enabled=false');
```

### Cleanup

```typescript
test.afterEach(async () => {
    for (const id of createdIds) {
        await forceCleanup(page, id);  // idempotent
    }
});
```

### Config

- Chromium only, 1280x720 viewport
- Vite dev server auto-started on port 5176
- Trace on first retry, screenshots on failure
- Workers: 1 in CI, parallel locally
