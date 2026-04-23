# OAuth 2.0 / OIDC Integration Design

**Date:** 2026-04-18  
**Task:** F-0052 OAuth / SSO Login  
**Scope:** Phase 1 (Google + Microsoft Entra ID)  
**Status:** Design Approved

## Overview

Add OAuth 2.0 / OpenID Connect (OIDC) login support for enterprise biotech adoption. Users can sign in with Google or Microsoft Entra ID as an alternative to email/password. Each email is locked to a single login method (OAuth provider or password) — no account linking or method switching.

**Target Users:**
- Startup biotech (Google): 15-20% of market
- Enterprise biotech (Entra ID): 70-80% of market

**Why Phase 1 (not broader)?** Authlib's generic OIDC support handles any provider. Phase 2 (Okta, SAML) is config-driven additions with no core refactoring needed.

---

## Architecture

### Tech Stack

- **OIDC Library:** authlib — handles code exchange, PKCE, JWT validation, discovery
- **Providers:** Google, Microsoft Entra ID (config-driven)
- **Flow:** Authorization Code + PKCE (industry standard for SPAs)
- **Compliance:** Audit logging for all auth events (GxP-ready, no step-up auth needed)

### Authentication Flow

```
User clicks "Sign in with Google"
  ↓
Backend: GET /auth/oauth/{provider}/authorize
  → Generate PKCE code_challenge + state
  → Redirect to provider's authorization URL
  ↓
User logs in at Google/Microsoft
  ↓
Provider redirects back to: GET /auth/oauth/{provider}/callback?code=X&state=Y
  ↓
Backend exchanges code for token
  → Validates state + code_challenge
  → Fetches user info (email, subject, email_verified)
  ↓
User Resolution (database lookup):
  IF user exists with oauth_provider + oauth_subject:
    → Log them in (return JWT)
  ELSE IF user exists with same email but different method:
    → Reject ("Email already registered with email/password")
  ELSE (new user):
    → Create User record (oauth_provider, oauth_subject, email)
    → Auto-verify email (trust IdP)
    → Log them in (return JWT)
  ↓
Frontend receives JWT → store in localStorage → redirect to dashboard
```

### Primary Auth Method (Locked)

Once a user logs in with a method (Google OAuth or email/password), that's their method forever:

| Scenario | Action |
|----------|--------|
| New user logs in with Google | Create with `oauth_provider="google"`, `hashed_password=null` |
| Existing Google user logs in again | Verify oauth_subject matches, return JWT |
| New user logs in with email/password | Create with `oauth_provider=null`, `hashed_password=hash` |
| Existing email/password user logs in again | Verify password, return JWT |
| User tries to switch methods (e.g., OAuth with existing email/password account) | Reject: "Email already registered with email/password. Use that method to sign in." |

**No account linking endpoints** — by design. Simplifies UX, eliminates verification friction for switching.

---

## Data Model Changes

### User Model (backend/app/models/iam.py)

Add three fields to `User`:

```python
oauth_provider: Mapped[Optional[str]] = mapped_column(
    String, nullable=True, index=True
)
# Values: "google", "microsoft", or null for email/password users
# Example: "google"

oauth_subject: Mapped[Optional[str]] = mapped_column(
    String, nullable=True
)
# Provider's unique user ID (e.g., Google's "sub" claim)
# Example: "118364435989640432716"

oauth_email_verified: Mapped[bool] = mapped_column(
    Boolean, default=False, server_default="false"
)
# Trust the IdP's email verification. True if oauth_provider is set.
```

### Constraints

```python
# Unique constraint: each OAuth provider/subject pair maps to exactly one user
__table_args__ = (
    UniqueConstraint("oauth_provider", "oauth_subject", name="uq_oauth_provider_subject"),
)
```

### hashed_password Becomes Nullable

Change `hashed_password` from `nullable=False` to `nullable=True`:
- OAuth-only users: `hashed_password=null`
- Email/password users: `hashed_password=<bcrypt_hash>`

**Validation in service layer:** When validating login, check the auth method:
- If `oauth_provider` is set → reject password login attempts
- If `oauth_provider` is null → require password

---

## Backend Implementation

### Configuration (app/core/config.py)

```python
class Settings:
    # Existing
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # New OAuth settings
    oauth_providers: dict[str, dict[str, str]] = {
        "google": {
            "client_id": os.getenv("BATCHRITE_OAUTH_GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("BATCHRITE_OAUTH_GOOGLE_CLIENT_SECRET", ""),
            "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
        },
        "microsoft": {
            "client_id": os.getenv("BATCHRITE_OAUTH_MICROSOFT_CLIENT_ID", ""),
            "client_secret": os.getenv("BATCHRITE_OAUTH_MICROSOFT_CLIENT_SECRET", ""),
            "discovery_url": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
            "tenant": os.getenv("BATCHRITE_OAUTH_MICROSOFT_TENANT", "common"),
        },
    }
    
    backend_url: str  # e.g., "http://localhost:8000"
    frontend_url: str  # e.g., "http://localhost:5173"
```

### OAuth Service (app/services/oauth.py)

```python
class OAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_authorize_url(self, provider: str) -> tuple[str, str, str]:
        """
        Generate authorization URL and PKCE challenge.
        Returns: (authorize_url, state, code_challenge)
        """
        # Use authlib to construct URL with PKCE
        
    async def exchange_code(
        self, provider: str, code: str, code_verifier: str, state: str
    ) -> UserInfo:
        """
        Exchange authorization code for token, fetch user info.
        Returns: UserInfo(email, oauth_subject, email_verified)
        """
        # Use authlib to exchange code
        # Validate state and PKCE
        # Fetch userinfo from provider
        
    async def get_or_create_user(self, provider: str, user_info: UserInfo) -> User:
        """
        Look up user by (provider, oauth_subject).
        If not found, check email conflict and create new user.
        Raises: HTTPException if email conflict (different auth method).
        """
```

### OAuth Endpoints (app/api/endpoints/oauth.py)

**GET /auth/oauth/{provider}/authorize**
- Generate PKCE + state
- Store state, code_challenge in session (or return in URL for SPA to store)
- Return redirect URL or 400 if provider not found

**GET /auth/oauth/{provider}/callback**
- Extract code, state from query params
- Validate state + PKCE
- Exchange code for token
- Fetch user info
- Create/lookup user
- Return JWT (same format as password login)
- Redirect frontend to dashboard with token in query param or as httpOnly cookie

### Audit Logging

Log all OAuth events to `audit_logs` table:
- `login_oauth` — successful OAuth login
- `oauth_email_conflict` — attempted to use OAuth email registered with different method
- `oauth_provider_error` — provider returned error (invalid code, timeout, etc.)

Each entry includes: user_id, oauth_provider, timestamp, request_ip.

### Error Handling

| Error | Response | Log |
|-------|----------|-----|
| Provider not found | 400 Bad Request | (not logged, config error) |
| Invalid/expired code | 400 Bad Request | `oauth_provider_error` |
| Provider down | 503 Service Unavailable | `oauth_provider_error` |
| Email conflict (different method) | 409 Conflict | `oauth_email_conflict` |
| New user creation succeeds | 200 + JWT | `login_oauth` |

---

## Frontend Implementation

### Login Page (frontend/src/routes/login/+page.svelte)

```
┌─────────────────────────────────┐
│   Sign in to Batchrite          │
├─────────────────────────────────┤
│ [Sign in with Google]           │
│ [Sign in with Microsoft]        │
│                                 │
│         ─── or ───              │
│                                 │
│ Email: [____________]           │
│ Password: [____________]         │
│                                 │
│ [Sign in]                       │
│                                 │
│ Don't have an account? Register │
└─────────────────────────────────┘
```

Buttons call `oauthLogin(provider)` → redirects to `/auth/oauth/{provider}/authorize`

### Callback Page (frontend/src/routes/auth/callback/+page.svelte)

Handles redirect from provider:
1. Extract `code`, `state` from URL
2. Verify state matches sessionStorage
3. Call `/auth/oauth/{provider}/callback` with code, code_verifier
4. Receive JWT
5. Store JWT in localStorage
6. Redirect to dashboard

### Auth Store (frontend/src/lib/auth.svelte.ts)

Add:
```typescript
export async function oauthLogin(provider: 'google' | 'microsoft'): Promise<void> {
    // 1. Generate PKCE code_verifier
    const codeVerifier = generateCodeVerifier();
    sessionStorage.setItem(`oauth_code_verifier_${provider}`, codeVerifier);
    
    // 2. Get authorize URL from backend
    const response = await fetch(`/auth/oauth/${provider}/authorize`);
    const { authorize_url, state } = await response.json();
    
    // 3. Store state
    sessionStorage.setItem(`oauth_state_${provider}`, state);
    
    // 4. Redirect to provider
    window.location.href = authorize_url;
}

export async function handleOAuthCallback(provider: string, code: string): Promise<void> {
    // 1. Retrieve state + code_verifier from sessionStorage
    const state = sessionStorage.getItem(`oauth_state_${provider}`);
    const codeVerifier = sessionStorage.getItem(`oauth_code_verifier_${provider}`);
    
    // 2. Exchange code for JWT
    const response = await fetch(`/auth/oauth/${provider}/callback`, {
        method: 'GET',
        query: { code, state, provider }
    });
    const { access_token } = await response.json();
    
    // 3. Store JWT
    localStorage.setItem('access_token', access_token);
    
    // 4. Redirect to dashboard
    window.location.href = '/dashboard';
}
```

### Settings Page

Show: "Signed in with Google" (read-only badge, no unlink option)

---

## Security

### PKCE (S256)
- All OAuth flows use PKCE (Proof Key for Code Exchange)
- Mitigates authorization code interception attacks

### State Token
- Generated for each authorize request
- Validated in callback
- Stored in sessionStorage to prevent CSRF

### JWT Validation
- Validate `iss` (issuer) claim matches expected provider
- Validate `aud` (audience) claim matches our client_id
- Validate `exp` (expiration)
- Validate signature using provider's public key (via discovery)

### Rate Limiting
- Rate-limit `/auth/oauth/{provider}/callback` to prevent brute force
- E.g., 10 requests per IP per minute

### No Client-Side Secrets
- Client ID is public (can appear in frontend code)
- Client secret stays in backend only (env var)
- Frontend never handles OAuth tokens directly

---

## Testing Strategy

### Unit Tests (Mocked)
- Mock OAuth provider responses
- Test code exchange logic
- Test user creation (new user, email conflict)
- Test JWT generation
- Test error handling (invalid code, provider down)

### Integration Tests (Local + Real Providers)
- **Local (mock):** Run in CI/CD, fast
- **Manual (real providers):** Test with actual Google + Microsoft accounts before release
- Use test accounts from:
  - **Google:** Any Google account (free)
  - **Microsoft:** Microsoft 365 Developer Program (free, provides test tenant + 25 test users)

### Coverage Target
>80% on oauth.py service and endpoints

---

## Phase 2+ Extensibility

Adding new providers (Okta, SAML, GitHub) requires:
1. Add config to `Settings.oauth_providers`
2. Add provider-specific logic to `OAuthService` (if needed)
3. Test with mock + real provider

No changes to user model, endpoints, or frontend.

---

## Out of Scope

- SSO enforcement per organization
- Account linking / method switching
- Step-up re-authentication (not needed, no 21 CFR Part 11)
- OAuth-only user password reset
- Okta, SAML, GitHub (Phase 2+)

---

## Testing Account Setup (Documentation)

After implementation, create docs for:
- **Google:** Google Cloud Console setup (client ID/secret)
- **Microsoft:** Microsoft 365 Developer Program signup + Azure app registration
- Local testing with `http://localhost:5173/auth/callback`

---

## Migration Path

**Alembic migration** adds three columns to `users` table:
```sql
ALTER TABLE users
ADD COLUMN oauth_provider VARCHAR(50) NULLABLE,
ADD COLUMN oauth_subject VARCHAR(255) NULLABLE,
ADD COLUMN oauth_email_verified BOOLEAN DEFAULT FALSE,
ALTER COLUMN hashed_password DROP NOT NULL,
ADD CONSTRAINT uq_oauth_provider_subject UNIQUE (oauth_provider, oauth_subject);
```

Existing users unaffected (all have `oauth_provider=null`, `hashed_password=<hash>`).
