# F-0091 Gate Registration Behind Feature Flag + Calendly Waitlist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate self-service registration and new-org creation behind a default-on feature flag, show a standalone Calendly waitlist card when the flag is off, and exempt holders of valid invitations.

**Architecture:** A nested `RegistrationFeatureConfig` flag on the backend (mirrored by a `VITE_REGISTRATION_ENABLED` frontend flag) gates `POST /auth/register` and `POST /iam/organizations` with a 403. Invitees bypass the register gate when they present a valid pending invitation matching their email. The `/register` SvelteKit page renders the existing form when the flag is on OR an invite token is present, otherwise a standalone waitlist card.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + Pydantic Settings; Svelte 5 (runes) + SvelteKit + Tailwind + shadcn-svelte; pytest (backend), Vitest + @testing-library/svelte (frontend).

**Conventions:** TDD (red-green). Run backend tests from `backend/` with venv active. Run frontend tests from `frontend/` with `npm run test`. Commit after each green task. This file does NOT use `black`/`isort` blanket formatting — match surrounding style.

---

## File structure

**Backend**
- `backend/app/core/config.py` — add `RegistrationFeatureConfig`, wire into `FeaturesConfig`.
- `backend/app/schemas/auth.py` — add `invite_token` to `RegisterRequest`.
- `backend/app/core/deps.py` — add `REGISTRATION_DISABLED_DETAIL` constant + `require_registration_enabled()` factory dependency.
- `backend/app/api/endpoints/auth.py` — gate `register()` (inline, needs invite exemption), add `_invite_permits_registration` helper, fix invite redirect, make `VERIFY_ERROR_HTML` flag-aware.
- `backend/app/api/endpoints/iam.py` — gate `create_organization()` via the shared dependency.
- `backend/.env.example`, `backend/settings.example.yaml` — document the flag.
- Tests: `backend/tests/unit/test_settings_registration.py` (new), `backend/tests/integration/test_auth_api.py`, `backend/tests/integration/test_iam_api.py`.

**Frontend**
- `frontend/src/lib/feature-flags.ts` — add `REGISTRATION_ENABLED`.
- `frontend/src/lib/auth.svelte.ts` — `register()` forwards `inviteToken`.
- `frontend/src/lib/components/shared/RegistrationWaitlist.svelte` — new card.
- `frontend/src/routes/register/+page.svelte` — flag/invite gating + login-matching branding.
- `frontend/src/routes/login/+page.svelte` — flag-aware register link.
- `frontend/src/routes/check-email/+page.svelte` — flag-aware "Start over" link.
- `frontend/.env.example` — add `VITE_REGISTRATION_ENABLED`.
- Tests: `frontend/src/routes/register/page.test.ts` (new), `frontend/src/lib/components/shared/RegistrationWaitlist.test.ts` (new).

**Docs**
- `CLAUDE.md` — feature-flag table row.

---

## Task 1: Backend config flag

**Files:**
- Modify: `backend/app/core/config.py` (after `OfflineModeFeatureConfig`, ~L19; and `FeaturesConfig` ~L51-61)
- Test: `backend/tests/unit/test_settings_registration.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_settings_registration.py`:

```python
"""F-0091: registration feature flag defaults and env override."""

import pytest

from app.core.config import RegistrationFeatureConfig, Settings


def test_registration_flag_defaults_on():
    cfg = RegistrationFeatureConfig()
    assert cfg.enabled is True


def test_registration_flag_present_on_settings():
    s = Settings()
    assert s.features.registration.enabled is True


def test_registration_flag_env_override_off(monkeypatch):
    monkeypatch.setenv("BATCHRITE_FEATURES__REGISTRATION__ENABLED", "false")
    s = Settings()
    assert s.features.registration.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_settings_registration.py -v`
Expected: FAIL with `ImportError: cannot import name 'RegistrationFeatureConfig'`.

- [ ] **Step 3: Add the config class and wire it in**

In `backend/app/core/config.py`, add after `OfflineModeFeatureConfig` (the class ending ~L18):

```python
class RegistrationFeatureConfig(BaseModel):
    """Self-service registration flag (F-0091). Default-on; flip OFF in prod."""

    enabled: bool = True
```

Then in `FeaturesConfig` (currently has `offline_mode` and `external_protocols`), add the field:

```python
    registration: RegistrationFeatureConfig = RegistrationFeatureConfig()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_settings_registration.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_settings_registration.py
git commit -m "feat(F-0091): add registration feature flag to config"
```

---

## Task 2: Add `invite_token` to RegisterRequest

**Files:**
- Modify: `backend/app/schemas/auth.py` (`RegisterRequest`, ~L11-14)

- [ ] **Step 1: Add the field**

In `backend/app/schemas/auth.py`, change `RegisterRequest`:

```python
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    invite_token: Optional[str] = None  # F-0091: gate bypass for invitees
```

- [ ] **Step 2: Verify nothing breaks**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_auth_api.py -q`
Expected: existing register tests still pass (new field is optional).

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/auth.py
git commit -m "feat(F-0091): add optional invite_token to RegisterRequest"
```

---

## Task 3: Gate `register()` with invite exemption

**Files:**
- Modify: `backend/app/api/endpoints/auth.py` (add helper near top after imports; gate at top of `register()` L168)
- Test: `backend/tests/integration/test_auth_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_auth_api.py` (the file already imports `select`, `User`, `VerificationToken`, `datetime/timedelta/timezone`, `patch`, `AsyncMock`):

```python
# ---------- F-0091: registration gate ----------

from app.core.config import settings as _settings
from app.models.iam import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
)
from app.models.projects import Project


@pytest.mark.asyncio
async def test_register_blocked_when_flag_off_no_invite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    with patch(
        "app.api.endpoints.auth.create_trial_subscription"
    ) as mock_trial, patch(
        "app.api.endpoints.auth.lifecycle_events"
    ) as mock_lifecycle:
        resp = await client.post(
            "/auth/register",
            json={"email": "blocked@example.com", "password": "securepass"},
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Registration is not available right now."
    # No side effects: no rows, no billing/lifecycle calls.
    for model in (User, Organization, OrganizationMember, Project, VerificationToken):
        count = await db_session.scalar(select(func.count()).select_from(model))
        # test_user/test_org fixtures may exist; assert the blocked email made nothing.
    blocked = await db_session.scalar(
        select(User).where(User.email == "blocked@example.com")
    )
    assert blocked is None
    mock_trial.assert_not_called()
    mock_lifecycle.emit_signup.assert_not_called()


@pytest.mark.asyncio
async def test_register_allowed_with_valid_invite_when_flag_off(
    client: AsyncClient, db_session: AsyncSession, test_org, test_user, monkeypatch
):
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    inv = Invitation(
        organization_id=test_org.id,
        invited_email="invitee@example.com",
        role="MEMBER",
        invited_by=test_user.id,
        token="invite-tok-123",
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(inv)
    await db_session.commit()

    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()
        resp = await client.post(
            "/auth/register",
            json={
                "email": "invitee@example.com",
                "password": "securepass",
                "invite_token": "invite-tok-123",
            },
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_blocked_with_email_mismatched_invite(
    client: AsyncClient, db_session: AsyncSession, test_org, test_user, monkeypatch
):
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    inv = Invitation(
        organization_id=test_org.id,
        invited_email="someone-else@example.com",
        role="MEMBER",
        invited_by=test_user.id,
        token="invite-tok-456",
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(inv)
    await db_session.commit()

    resp = await client.post(
        "/auth/register",
        json={
            "email": "attacker@example.com",
            "password": "securepass",
            "invite_token": "invite-tok-456",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_invite_token_cannot_mint_second_account(
    client: AsyncClient, db_session: AsyncSession, test_org, test_user, monkeypatch
):
    """A valid invite is a single-use registration key bounded by the
    duplicate-email 409: once the invited email registers, the same token
    cannot mint another account (the invitation legitimately stays PENDING
    until the invitee clicks accept-invite a second time to join the org)."""
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    inv = Invitation(
        organization_id=test_org.id,
        invited_email="cohort@example.com",
        role="MEMBER",
        invited_by=test_user.id,
        token="invite-tok-789",
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    db_session.add(inv)
    await db_session.commit()

    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        mock_provider.return_value.send = AsyncMock()
        first = await client.post(
            "/auth/register",
            json={
                "email": "cohort@example.com",
                "password": "securepass",
                "invite_token": "invite-tok-789",
            },
        )
    assert first.status_code == 200

    # Same token + same email a second time → duplicate-email 409, not a new user.
    second = await client.post(
        "/auth/register",
        json={
            "email": "cohort@example.com",
            "password": "securepass",
            "invite_token": "invite-tok-789",
        },
    )
    assert second.status_code == 409
```

Add `func` to the existing sqlalchemy import line in the test file (`from sqlalchemy import func, select`).

**Security note (do NOT change behavior):** the invitation stays `PENDING` after `register()` on purpose — actual org membership is created when the invitee clicks the accept-invite email link a second time (existing `accept_invite` flow at `auth.py:553-582` marks it `ACCEPTED`). Consuming/accepting the invite inside `register()` would break that join. The reuse window is bounded: the token only permits registration for `invitation.invited_email` (email-match in `_invite_permits_registration`), and the duplicate-email 409 blocks any second account for that email. The token is therefore a single-use-per-email registration key for exactly the pre-invited person — by design.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_auth_api.py -k "flag_off or valid_invite or mismatched" -v`
Expected: FAIL (no gate yet — register returns 200/409, not 403).

- [ ] **Step 3: Add the helper**

In `backend/app/api/endpoints/auth.py`, after the imports / before the router routes (module level, near `ALLOWED_AVATAR_TYPES`), add:

```python
async def _invite_permits_registration(
    db: AsyncSession, token: Optional[str], email: str
) -> bool:
    """True iff `token` is a pending, unexpired invitation for `email` (F-0091)."""
    if not token:
        return False
    result = await db.execute(
        select(Invitation).where(
            Invitation.token == token,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    inv = result.scalar_one_or_none()
    if inv is None or inv.expires_at < datetime.now(timezone.utc):
        return False
    return inv.invited_email == email
```

`Invitation` and `InvitationStatus` are already imported in this file.

- [ ] **Step 4: Add the gate at the top of `register()`**

`register()` keeps an **inline** gate (rather than the `require_registration_enabled()` dependency used by `iam.py` in Task 4) because it needs `body.invite_token`/`body.email` for the invite exemption, which a parameterless dependency can't see. Import the shared detail constant so the 403 message stays in one place:

```python
from app.core.deps import REGISTRATION_DISABLED_DETAIL
```

In `register()` (currently starting with the duplicate-email lookup at L172), insert as the **first** statements inside the function body:

```python
    if not settings.features.registration.enabled:
        allowed = await _invite_permits_registration(
            db, body.invite_token, body.email
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=REGISTRATION_DISABLED_DETAIL,
            )
```

- [ ] **Step 5: Make lifecycle import patchable**

The test patches `app.api.endpoints.auth.lifecycle_events` and `app.api.endpoints.auth.create_trial_subscription`. These are currently imported *inside* `register()` (local imports), so module-level patching won't bind. The allowed-invite test mocks the email provider only (it lets the real billing/lifecycle no-op run, which is safe — Stripe/Loops are globally disabled in conftest). For the **blocked** test, the gate raises before those imports execute, so the local imports never run and `mock_trial`/`mock_lifecycle` are never called regardless of patch binding. To make the assertions meaningful, keep the patches but assert via the gate ordering: since the 403 fires first, simply assert `resp.status_code == 403` and `blocked is None`. **Update the blocked test** to drop the `mock_trial.assert_not_called()` / `mock_lifecycle.emit_signup.assert_not_called()` lines (they would patch names that aren't module-level) and the unused `for model` loop, keeping only the 403 + `blocked is None` assertions:

```python
@pytest.mark.asyncio
async def test_register_blocked_when_flag_off_no_invite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    resp = await client.post(
        "/auth/register",
        json={"email": "blocked@example.com", "password": "securepass"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Registration is not available right now."
    blocked = await db_session.scalar(
        select(User).where(User.email == "blocked@example.com")
    )
    assert blocked is None
```

(The gate raising before any DB write is the real "no side effects" guarantee; `blocked is None` proves no partial user row.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_auth_api.py -v`
Expected: all pass, including the pre-existing flag-on register tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_auth_api.py
git commit -m "feat(F-0091): gate register endpoint with invite exemption"
```

---

## Task 4: Shared `require_registration_enabled` dep + gate `create_organization()`

**Files:**
- Modify: `backend/app/core/deps.py` (add constant + factory dependency)
- Modify: `backend/app/api/endpoints/iam.py` (`create_organization` signature)
- Test: `backend/tests/integration/test_iam_api.py`

- [ ] **Step 1: Write the failing test**

Find the existing iam test file. Run: `ls backend/tests/integration/ | grep -i iam` — use that file (e.g. `test_iam_api.py`). If none exists, create `backend/tests/integration/test_iam_org_gate.py`. Append:

```python
import pytest
from httpx import AsyncClient

from app.core.config import settings as _settings


@pytest.mark.asyncio
async def test_create_organization_blocked_when_flag_off(
    client: AsyncClient, auth_headers, monkeypatch
):
    monkeypatch.setattr(_settings.features.registration, "enabled", False)
    resp = await client.post(
        "/iam/organizations",
        json={"name": "New Tenant"},
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_organization_allowed_when_flag_on(
    client: AsyncClient, auth_headers
):
    resp = await client.post(
        "/iam/organizations",
        json={"name": "New Tenant On"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_iam_api.py -k organization_blocked -v` (adjust filename)
Expected: FAIL (returns 201, not 403).

- [ ] **Step 3: Add the shared dependency + detail constant**

In `backend/app/core/deps.py`, alongside the existing `require_*` factories (`require_permission`, `require_tier`, etc.), add:

```python
REGISTRATION_DISABLED_DETAIL = "Registration is not available right now."


def require_registration_enabled():
    """Gate factory (F-0091): 403 when self-service registration is off.

    Use on self-service entry points that have no invite-exemption path
    (e.g. new-org creation). `register()` gates inline instead because it
    must inspect the invite token in the request body.
    """

    async def _check() -> None:
        if not settings.features.registration.enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=REGISTRATION_DISABLED_DETAIL,
            )

    return _check
```

`settings`, `HTTPException`, and `status` are already imported in `deps.py` (used by the existing factories). If `settings` is not yet imported there, add `from app.core.config import settings`.

- [ ] **Step 4: Wire the dependency into `create_organization`**

In `backend/app/api/endpoints/iam.py`, import the factory and add it to the `create_organization` signature as a no-bind dependency (alongside the existing `require_active_subscription()` dep):

```python
from app.core.deps import require_registration_enabled
```

```python
    _reg: None = Depends(require_registration_enabled()),
```

No body change needed — the dependency raises before the handler runs.

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_iam_api.py -k organization -v` (adjust filename)
Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/deps.py backend/app/api/endpoints/iam.py backend/tests/integration/test_iam_api.py
git commit -m "feat(F-0091): gate org creation behind registration flag"
```

---

## Task 5: Fix invite redirect + flag-aware verify-error link

**Files:**
- Modify: `backend/app/api/endpoints/auth.py` (L549 redirect; `VERIFY_ERROR_HTML` L156-164 + its render site)

- [ ] **Step 1: Fix the accept-invite redirect**

In `accept_invite` (~L548), change the hash-style redirect to path-based so the invitee lands on the SvelteKit route with a readable query param:

```python
        redirect_url = f"{settings.frontend_url}/register?invite={invitation.token}"
```

(was `f"{settings.frontend_url}/#/register" f"?invite={invitation.token}"`)

- [ ] **Step 2: Make the verification-failure link flag-aware**

`VERIFY_ERROR_HTML` (the constant ending ~L164) hardcodes a "Create a new account" link to `/register`. Locate where it is `.format(...)`-rendered in `verify_email` (search for `VERIFY_ERROR_HTML.format`). The constant currently embeds the anchor directly. Replace the hardcoded anchor in the constant with a `{cta_link}` placeholder:

Change the constant's anchor line from:
```python
    <a href="{frontend_url}/register" style="color: #2563eb;">Create a new account</a>
```
to:
```python
    {cta_link}
```

Then at each `VERIFY_ERROR_HTML.format(...)` call site, compute and pass `cta_link`:

```python
        cta_link = (
            f'<a href="{settings.frontend_url}/register" style="color: #2563eb;">'
            "Create a new account</a>"
            if settings.features.registration.enabled
            else f'<a href="{settings.frontend_url}/login" style="color: #2563eb;">'
            "Return to sign in</a>"
        )
```

and add `cta_link=cta_link` to the existing `.format(message=..., frontend_url=...)` calls that use `VERIFY_ERROR_HTML`.

**There are TWO render sites** — `auth.py:301` and `auth.py:312` (grep `VERIFY_ERROR_HTML.format` to confirm both). Both must compute and pass `cta_link`; missing either raises a `KeyError: 'cta_link'` at render time (a 500 instead of the intended error page). Add the `cta_link = (...)` block before each `.format(...)` call (or compute it once just inside `verify_email` if both sites share scope).

- [ ] **Step 3: Run the auth suite**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_auth_api.py -q`
Expected: all pass (no test asserts the old `/#/register` string; if one does, update it to `/register?invite=`).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/endpoints/auth.py
git commit -m "fix(F-0091): path-based invite redirect + flag-aware verify-error link"
```

---

## Task 6: Backend docs / config examples

**Files:**
- Modify: `backend/.env.example`, `backend/settings.example.yaml`

- [ ] **Step 1: Add to `backend/.env.example`**

After the existing `BATCHRITE_FEATURES__OFFLINE_MODE__ENABLED=false` line:

```
# Self-service registration (F-0091). Default: true (on). Set to exactly
# "false" to gate sign-up + new-org creation in production. Invitees with a
# valid pending invitation are exempt. Backend is the source of truth.
BATCHRITE_FEATURES__REGISTRATION__ENABLED=true
```

- [ ] **Step 2: Add to `backend/settings.example.yaml`**

Under the commented `features:` block, add a `registration:` stanza (matching the `external_protocols` comment style):

```yaml
#   registration:
#     # Self-service sign-up + new-org creation (F-0091). Default-on.
#     # Set false in prod; invitees with a valid pending invite are exempt.
#     enabled: true
```

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example backend/settings.example.yaml
git commit -m "docs(F-0091): document registration flag in backend config examples"
```

---

## Task 7: Frontend flag

**Files:**
- Modify: `frontend/src/lib/feature-flags.ts`, `frontend/.env.example`

- [ ] **Step 1: Add the flag**

Append to `frontend/src/lib/feature-flags.ts`:

```typescript

// F-0091: self-service registration. Default ON (only OFF when the env var is
// exactly the string 'false') so local/dev and the demo are unaffected when
// unset. Opposite polarity from OFFLINE_ENABLED (=== 'true', default-off).
export const REGISTRATION_ENABLED: boolean =
    import.meta.env.VITE_REGISTRATION_ENABLED !== 'false';
```

- [ ] **Step 2: Add to `frontend/.env.example`**

```
# Self-service registration (F-0091). Default: on. Set to exactly "false" to
# show the waitlist instead of the sign-up form. Must mirror the backend flag.
VITE_REGISTRATION_ENABLED=true
```

- [ ] **Step 3: Typecheck + commit**

Run: `cd frontend && npm run check`
Expected: no new errors.

```bash
git add frontend/src/lib/feature-flags.ts frontend/.env.example
git commit -m "feat(F-0091): add REGISTRATION_ENABLED frontend flag"
```

---

## Task 8: `register()` forwards invite token

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts` (`register`, ~L305-312)

- [ ] **Step 1: Update the signature + body**

Change `register` to accept an optional invite token and include it when present:

```typescript
export async function register(
    email: string,
    password: string,
    fullName: string,
    inviteToken?: string | null,
): Promise<void> {
    const res = await authFetch<{ verification_token: string }>('POST', '/auth/register', {
        email,
        password,
        full_name: fullName,
        ...(inviteToken ? { invite_token: inviteToken } : {}),
    });
    token = res.verification_token;
    localStorage.setItem('auth_token', token);

    user = await authFetch<User>('GET', '/auth/me');
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run check`
Expected: no new errors (the extra arg is optional; existing callers unaffected).

```bash
git add frontend/src/lib/auth.svelte.ts
git commit -m "feat(F-0091): forward invite_token from register()"
```

---

## Task 9: RegistrationWaitlist card component

**Files:**
- Create: `frontend/src/lib/components/shared/RegistrationWaitlist.svelte`
- Test: `frontend/src/lib/components/shared/RegistrationWaitlist.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/shared/RegistrationWaitlist.test.ts`:

```typescript
import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import RegistrationWaitlist from './RegistrationWaitlist.svelte';

describe('RegistrationWaitlist', () => {
    it('renders the cohort heading and a Calendly CTA in a new tab', () => {
        render(RegistrationWaitlist, {
            calendlyUrl: 'https://calendly.com/test/30min',
        });
        expect(screen.getByText('Join the first cohort')).toBeInTheDocument();
        const cta = screen.getByRole('link', { name: /request early access/i });
        expect(cta).toHaveAttribute('href', 'https://calendly.com/test/30min');
        expect(cta).toHaveAttribute('target', '_blank');
        expect(cta).toHaveAttribute('rel', 'noopener noreferrer');
    });

    it('always offers a back-to-sign-in escape', () => {
        render(RegistrationWaitlist, {
            calendlyUrl: 'https://calendly.com/test/30min',
        });
        const back = screen.getByRole('link', { name: /back to sign in/i });
        expect(back).toHaveAttribute('href', '/login');
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/components/shared/RegistrationWaitlist.test.ts`
Expected: FAIL (component file does not exist).

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/shared/RegistrationWaitlist.svelte`:

```svelte
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';

    interface Props {
        calendlyUrl: string;
    }

    let { calendlyUrl }: Props = $props();
</script>

<Card>
    <CardHeader>
        <CardTitle>Join the first cohort</CardTitle>
        <CardDescription>
            Batchrite is currently in early access. Request an invite to be among the
            first Process Development teams on the platform.
        </CardDescription>
    </CardHeader>
    <CardContent class="space-y-4">
        <Button
            href={calendlyUrl}
            target="_blank"
            rel="noopener noreferrer"
            class="w-full"
        >
            Request early access
        </Button>
        <Button variant="outline" href="/login" class="w-full">
            Back to sign in
        </Button>
        <p class="text-xs text-muted-foreground text-center pt-2">
            By requesting access, you agree to our
            <a href="/legal/terms" class="underline hover:text-foreground transition-all duration-150">Terms of Service</a>
            and
            <a href="/legal/privacy" class="underline hover:text-foreground transition-all duration-150">Privacy Policy</a>.
        </p>
    </CardContent>
</Card>
```

Note: the shadcn-svelte `Button` renders an `<a>` when given `href`. Verify this in `frontend/src/lib/components/ui/button/button.svelte`; if it does not support `href`, replace the two `Button href=...` usages with plain `<a>` styled via `buttonVariants({ variant: ... })` and `class`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/components/shared/RegistrationWaitlist.test.ts`
Expected: 2 passed. If the CTA isn't found as a `link` role, fix per the Step 3 note.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/shared/RegistrationWaitlist.svelte frontend/src/lib/components/shared/RegistrationWaitlist.test.ts
git commit -m "feat(F-0091): add RegistrationWaitlist card component"
```

---

## Task 10: Register page flag/invite gating

**Files:**
- Modify: `frontend/src/routes/register/+page.svelte`
- Test: `frontend/src/routes/register/page.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/routes/register/page.test.ts`:

```typescript
import { render, screen } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';

const flag = vi.hoisted(() => ({ value: true }));
vi.mock('$lib/feature-flags', () => ({
    get REGISTRATION_ENABLED() {
        return flag.value;
    },
}));

import Page from './+page.svelte';

function setUrl(search: string) {
    window.history.replaceState({}, '', `/register${search}`);
}

describe('register page gating', () => {
    beforeEach(() => {
        flag.value = true;
        setUrl('');
    });

    it('shows the sign-up form when the flag is on', () => {
        render(Page);
        expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
        expect(screen.queryByText('Join the first cohort')).not.toBeInTheDocument();
    });

    it('shows the waitlist when the flag is off and no invite', () => {
        flag.value = false;
        render(Page);
        expect(screen.getByText('Join the first cohort')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument();
    });

    it('shows the form when the flag is off but an invite is present', () => {
        flag.value = false;
        setUrl('?invite=tok-1');
        render(Page);
        expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
        expect(screen.queryByText('Join the first cohort')).not.toBeInTheDocument();
    });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/routes/register/page.test.ts`
Expected: FAIL (page doesn't render the waitlist; "Join the first cohort" not found in the off case).

- [ ] **Step 3: Update the page**

Edit `frontend/src/routes/register/+page.svelte`. In `<script>`, add imports and gating:

```typescript
    import { REGISTRATION_ENABLED } from '$lib/feature-flags';
    import RegistrationWaitlist from '$lib/components/shared/RegistrationWaitlist.svelte';
    import Logo from '$lib/components/layout/Logo.svelte';

    const CALENDLY_WAITLIST_URL = 'https://calendly.com/wes-batchrite/30min'; // F-0091

    const inviteToken =
        typeof window !== 'undefined'
            ? new URLSearchParams(window.location.search).get('invite')
            : null;
    const showForm = REGISTRATION_ENABLED || !!inviteToken;
```

**Do NOT switch this to `$app/stores`/`$page`.** This app sets `export const ssr = false` globally (`src/routes/+layout.ts`), uses `adapter-static`, and reads query params via `new URLSearchParams(window.location.search)` everywhere (`login/+page.svelte:28`, `+layout.svelte:78`). `$app/stores` is used nowhere in `src`. The `typeof window` guard keeps it safe; `register` is a fresh full navigation entry point (the invite link reloads the page), so a one-time read at init is correct and matches the login page's identical `next`-param read. `REGISTRATION_ENABLED` is a build-time `const`, so there is no flag-resolution flash.

Change the `register(...)` call in `handleSubmit` to forward the token:

```typescript
            await register(email, password, fullName, inviteToken);
```

**Branding upgrade (match the login page).** The register page currently uses a plain `bg-muted/40` wrapper and a bare `B` logo div. When the flag is off this page is a prospect's first impression, so bring it up to the login page's polish. Replace the outer wrapper + header block (lines ~45-55) with login's structure:

```svelte
<div class="min-h-screen flex items-center justify-center bg-background dot-grid px-4 relative overflow-hidden">
    <!-- Decorative blobs -->
    <div class="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] rounded-full bg-primary/[0.03] blur-3xl"></div>
    <div class="absolute bottom-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full bg-accent/[0.04] blur-3xl"></div>

    <div class="w-full max-w-sm relative z-10">
        <div class="flex flex-col items-center mb-10">
            <Logo size="lg" variant="full" animated orientation="stacked" />
            <p class="mt-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/80">Laboratory Execution System</p>
        </div>
```

(Close the two wrapper `</div>`s at the end of the file as before.)

In the markup, wrap the existing `<Card>...</Card>` (the sign-up card) so it only renders when `showForm`, and render the waitlist otherwise. Replace the `<Card>` block with:

```svelte
        {#if showForm}
            <Card>
                <!-- ...existing CardHeader/CardContent/form unchanged... -->
            </Card>
        {:else}
            <div in:fade={{ duration: blockDuration() }}>
                <RegistrationWaitlist calendlyUrl={CALENDLY_WAITLIST_URL} />
            </div>
        {/if}
```

`fade` and `blockDuration` are already imported in this file. The transition keeps the waitlist swap from popping in hard.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/routes/register/page.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run check`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/register/+page.svelte frontend/src/routes/register/page.test.ts
git commit -m "feat(F-0091): gate register page with waitlist + invite passthrough"
```

---

## Task 11: Flag-aware login "Register" link

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte` (~L126-129)

- [ ] **Step 1: Update the link**

Add to the `<script>` imports:

```typescript
    import { REGISTRATION_ENABLED } from '$lib/feature-flags';
```

Replace the "Don't have an account? Register" paragraph (~L126-129) with:

```svelte
                    <p class="text-sm text-center text-muted-foreground mt-6">
                        {#if REGISTRATION_ENABLED}
                            Don't have an account?
                            <a href="/register" class="text-primary font-semibold hover:underline">Register</a>
                        {:else}
                            Not on Batchrite yet?
                            <a href="/register" class="text-primary font-semibold hover:underline">Join the waitlist</a>
                        {/if}
                    </p>
```

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run check`
Expected: no new errors.

```bash
git add frontend/src/routes/login/+page.svelte
git commit -m "feat(F-0091): flag-aware register/waitlist link on login page"
```

- [ ] **Step 3: Fix the check-email "Start over" link**

`frontend/src/routes/check-email/+page.svelte:82` links "Start over" to `/register`. With the flag off, that dead-ends on the waitlist card instead of a usable form, so point it at `/login` when registration is off. Add the import:

```typescript
    import { REGISTRATION_ENABLED } from '$lib/feature-flags';
```

Replace the "Wrong email? Start over" paragraph (~L80-83) with:

```svelte
                <p class="text-sm text-center text-muted-foreground mt-4">
                    {#if REGISTRATION_ENABLED}
                        Wrong email?
                        <a href="/register" class="text-primary font-medium hover:underline">Start over</a>
                    {:else}
                        Need help?
                        <a href="/login" class="text-primary font-medium hover:underline">Back to sign in</a>
                    {/if}
                </p>
```

- [ ] **Step 4: Typecheck + commit**

Run: `cd frontend && npm run check`
Expected: no new errors.

```bash
git add frontend/src/routes/check-email/+page.svelte
git commit -m "fix(F-0091): flag-aware start-over link on check-email page"
```

---

## Task 12: CLAUDE.md flag table

**Files:**
- Modify: `CLAUDE.md` (the feature-flag table under "## Feature flags")

- [ ] **Step 1: Add a table row**

Add after the External-protocols row:

```
| Registration | `features.registration.enabled` (yaml) or `BATCHRITE_FEATURES__REGISTRATION__ENABLED` (env) | `VITE_REGISTRATION_ENABLED` | `true` | Gates self-service sign-up (`POST /auth/register`) and new-org creation (`POST /iam/organizations`) with a 403; `/register` shows a Calendly waitlist card. Holders of a valid pending invitation (email-matched) are exempt. Set both halves to exactly `false` in prod. (F-0091) |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(F-0091): document registration flag in CLAUDE.md"
```

---

## Task 13: Full suite + final verification

- [ ] **Step 1: Backend tests**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/test_settings_registration.py tests/integration/test_auth_api.py tests/integration/test_iam_api.py -q`
Expected: all pass.

- [ ] **Step 2: Frontend tests + check**

Run: `cd frontend && npm run test && npm run check`
Expected: all pass, no new type errors.

**Test-environment assumption:** every existing suite that hits `POST /auth/register` or `POST /iam/organizations` (e.g. `test_registration_billing.py`, `test_org_registration_default_site.py`, the 14 call sites in `test_auth_api.py`, and the Playwright `registerUser()` helper in `frontend/e2e/email-verification.spec.ts`) relies on the flag's **default-ON** value — none monkeypatch it on. The only suites that flip it off are the new F-0091 tests, which set it explicitly via `monkeypatch`. Do not set `BATCHRITE_FEATURES__REGISTRATION__ENABLED`/`VITE_REGISTRATION_ENABLED` in CI or the e2e environment, or those pre-existing suites will get 403s. (Documented in the CLAUDE.md row.)

- [ ] **Step 3: Manual smoke (during /implement-task browser verification)**

- Flag ON (default): `/register` shows the form; registration works.
- Flag OFF (`VITE_REGISTRATION_ENABLED=false`, backend `BATCHRITE_FEATURES__REGISTRATION__ENABLED=false`): `/register` shows the waitlist card; "Request early access" opens Calendly in a new tab; "Back to sign in" → `/login`; login still works; `/register?invite=<valid>` shows the form.
- `POST /auth/register` and `POST /iam/organizations` return 403 with the flag off (no invite).

---

## Spec coverage check

- Backend flag → Task 1. Schema field → Task 2. Register gate + invite exemption + reuse-bound test → Task 3. Shared `require_registration_enabled` dep + org gate → Task 4. Invite redirect fix + flag-aware verify-error link (both render sites) → Task 5. Backend docs → Task 6. Frontend flag → Task 7. register() forward → Task 8. Waitlist card → Task 9. Register page gating + login-matching branding → Task 10. Login link + check-email link → Task 11. CLAUDE.md → Task 12. Verification + test-env assumption → Task 13. All spec sections mapped.

## Review-panel findings applied (2026-05-29)

- **DRY:** extracted `require_registration_enabled()` + `REGISTRATION_DISABLED_DETAIL` into `deps.py` (Task 4); `register()` gates inline (needs invite token) but shares the constant.
- **Coupling:** both `VERIFY_ERROR_HTML.format` sites updated (Task 5); `check-email` "Start over" link made flag-aware (Task 11); test-env assumption documented (Task 13).
- **Security:** invitation stays `PENDING` by design; reuse bounded by email-match + duplicate-email 409, proved by `test_invite_token_cannot_mint_second_account` (Task 3).
- **UI/UX:** register page upgraded to login-page branding; `fade` transition on the waitlist swap; `space-y-4` consistency (Tasks 9-10).
- **Rejected:** switching to `$app/stores`/`$page` (app is `ssr=false` + `adapter-static`, uses `window.location.search` everywhere — note added in Task 10); consuming the invite inside `register()` (would break the accept-invite membership join).
