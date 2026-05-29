# F-0091 — Gate self-service registration behind a feature flag + Calendly waitlist

**Status:** Design (hardened after spec review panel)
**Date:** 2026-05-29
**Task:** F-0091 (FEATURES, P1) — full stack
**Effort:** M–L (scope grew during review: invite exemption + org-creation gate)

## Problem

For the initial production deployment we are not opening self-service sign-up.
Registration is gated behind a feature flag that is **default-on** (so
local/dev, tests, and the demo are unaffected) and **flipped off in
production**. With the flag off:

- A logged-out visitor landing on `/register` (without an invite) sees a
  **standalone waitlist surface** directing them to book a Calendly meeting to
  join the first cohort, instead of a sign-up form.
- `POST /auth/register` returns **403** so the endpoint cannot be used even if
  the UI is bypassed.
- `POST /iam/organizations` (existing users creating *additional* tenants) also
  returns **403** — no new tenants in prod.

Login, email verification, the demo org, and **invitation-based onboarding** must
keep working with the flag off.

## Decisions (resolved during review)

1. **Invited users are exempt.** A visitor holding a valid pending invitation can
   still register, because cohort onboarding happens via invitations. The gate is
   bypassed only when a valid, pending, non-expired invitation whose
   `invited_email` matches the registering email is supplied.
2. **Scope = accounts *and* new tenants.** Gate both `POST /auth/register`
   (anonymous account+org creation) and `POST /iam/organizations` (authed users
   creating extra orgs). The org-creation path has no UI caller today, so gating
   it is low-risk.
3. **Standalone waitlist card, not a modal.** Because the prod gate is permanent,
   a teasing-but-disabled form reads as a dead-end. When the flag is off and no
   invite is present, render a polished standalone waitlist card *in place of* the
   form — no modal, no blur, no `inert`. (Deviates from the task's "modal"
   wording; user-approved.)

## Non-goals

- No DB migration — config-flag only.
- No change to login, email verification, or OAuth.
- We do **not** make `register()` consume the invite token to auto-join the
  inviting org. That is pre-existing behavior (the invitee re-clicks the invite
  link after creating an account); F-0091 only ensures the gate doesn't block
  account creation for invitees.

## Design

### 1. Backend flag

`backend/app/core/config.py`, following the `OfflineModeFeatureConfig` pattern:

```python
class RegistrationFeatureConfig(BaseModel):
    """Self-service registration flag (F-0091). Default-on; flip OFF in prod."""

    enabled: bool = True


class FeaturesConfig(BaseModel):
    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = ExternalProtocolsFeatureConfig()
    registration: RegistrationFeatureConfig = RegistrationFeatureConfig()
```

Env override: `BATCHRITE_FEATURES__REGISTRATION__ENABLED=false`.

### 2. Register endpoint gate with invite exemption

`backend/app/schemas/auth.py` — add an optional field to `RegisterRequest`:

```python
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    invite_token: Optional[str] = None  # F-0091: gate bypass for invitees
```

`backend/app/api/endpoints/auth.py` — gate at the **very top** of `register()`
(before the duplicate-email lookup and any writes):

```python
if not settings.features.registration.enabled:
    allowed = await _invite_permits_registration(
        db, body.invite_token, body.email
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is not available right now.",
        )
```

New module-level helper in `auth.py`:

```python
async def _invite_permits_registration(
    db: AsyncSession, token: Optional[str], email: str
) -> bool:
    """True iff `token` is a pending, unexpired invitation for `email`."""
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

Email-match is required: it prevents a leaked/valid invite token from being used
to register an arbitrary account, and is consistent with `accept_invite`, which
also matches the invitee by email. When the flag is **on**, `invite_token` is
ignored entirely — behavior is identical to today.

The detail string is generic (no flag/env-var mention) so it leaks nothing
operationally.

### 3. Org-creation gate

`backend/app/api/endpoints/iam.py` `create_organization()` (L138) — add at the
top of the body (after deps resolve):

```python
if not settings.features.registration.enabled:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Registration is not available right now.",
    )
```

No invite exemption here — invitations are about joining existing orgs, not
creating new ones.

### 4. Fix accept-invite redirect

`backend/app/api/endpoints/auth.py:549` currently redirects new invitees to
`{frontend_url}/#/register?invite={token}` — the only **hash-style** redirect in
the file (every other redirect is path-based). SvelteKit routes are path-based,
so the invitee never reliably lands on the route with a readable query param.
Change to:

```python
redirect_url = f"{settings.frontend_url}/register?invite={invitation.token}"
```

This is a prerequisite for the invite exemption: the invitee must reach
`/register` with `?invite=` readable so the form renders and the token is
forwarded.

### 5. Frontend flag

`frontend/src/lib/feature-flags.ts`, **default-on** (note the comment is
load-bearing — opposite polarity from `OFFLINE_ENABLED`):

```typescript
// F-0091: self-service registration. Default ON (only OFF when the env var is
// exactly the string 'false') so local/dev and the demo are unaffected when
// unset. Opposite polarity from OFFLINE_ENABLED (=== 'true', default-off).
export const REGISTRATION_ENABLED: boolean =
    import.meta.env.VITE_REGISTRATION_ENABLED !== 'false';
```

Backend is the source of truth; the frontend flag is cosmetic (the 403 is the
real boundary). Document the **exact lowercase `false`** requirement in both
`.env.example` comments and the CLAUDE.md row.

### 6. Frontend register page

`frontend/src/routes/register/+page.svelte`:

```typescript
import { page } from '$app/stores';
import { REGISTRATION_ENABLED } from '$lib/feature-flags';

const inviteToken = $derived($page.url.searchParams.get('invite'));
const showForm = $derived(REGISTRATION_ENABLED || !!inviteToken);
```

- `showForm` true → render the existing sign-up form (today's behavior). When an
  `inviteToken` is present, forward it: `register(email, password, fullName, inviteToken)`.
- `showForm` false → render `<RegistrationWaitlist />` (the standalone card)
  instead of the form. No modal, no blur, no `inert`.

`frontend/src/lib/auth.svelte.ts` `register()` gains an optional 4th arg and
includes it in the POST body as `invite_token` when present.

### 7. RegistrationWaitlist card (new component)

`frontend/src/lib/components/shared/RegistrationWaitlist.svelte` — a **card**
(not a Dialog), composed from the shared `Card` primitives, matching the login
page branding (`Logo` component, `card-warm`, the same muted/`dot-grid`
backdrop the page provides).

Props:

```typescript
interface Props {
    calendlyUrl: string;
}
```

Content (copy reframed to invite, not reject):

- **Title:** "Join the first cohort"
- **Body:** "Batchrite is currently in early access. Request an invite to be among
  the first Process Development teams on the platform."
- **Primary CTA** (anchor, new tab): "Request early access" →
  `target="_blank" rel="noopener noreferrer"`, href = `calendlyUrl`.
- **Secondary** (full-width `Button variant="outline"`, real `<a href="/login">`):
  "Back to sign in" — always present so no one is trapped.
- **Legal line** below the buttons (`text-xs text-muted-foreground`): ToS /
  Privacy links, so a prospect can see policy before booking.

The Calendly URL is a single module constant in the page:
`https://calendly.com/wes-batchrite/30min` (one `# F-0091` comment marks it for
future grepping; changing it requires a frontend rebuild — acceptable for M
effort).

### 8. Downstream link copy (consumers of /register)

- `frontend/src/routes/login/+page.svelte` "Register" link: when
  `!REGISTRATION_ENABLED`, relabel to "Join the waitlist" (still → `/register`),
  so the login CTA isn't deceptive.
- `backend/app/api/endpoints/auth.py` `VERIFY_ERROR_HTML` (L162): the
  "Create a new account" → `/register` anchor is rendered on verification
  failure. Make it flag-aware — when `settings.features.registration.enabled` is
  false, point to `/login` with neutral text ("Return to sign in"); otherwise
  keep today's text.
- `frontend/src/routes/check-email/+page.svelte` "Start over" → `/register`:
  left as-is. With the flag off it lands on the waitlist card, which is a
  graceful destination (edge case: user registered before the flip).

### 9. Documentation / config examples

- `frontend/.env.example`: `VITE_REGISTRATION_ENABLED=true` (comment: exact
  lowercase `false` to disable).
- `backend/.env.example`: `BATCHRITE_FEATURES__REGISTRATION__ENABLED=true`.
- `backend/settings.example.yaml`: add a `registration:` stanza under the
  commented `features:` block (parity with `external_protocols`), noting
  default-on / set `false` in prod.
- `CLAUDE.md`: new feature-flag table row (both halves must be set off to gate
  end-to-end; prod sets both `false`; invitees are exempt).

## Data flow

```
GET /register
  REGISTRATION_ENABLED OR ?invite present → form renders (invite token forwarded)
  else                                     → standalone waitlist card

POST /auth/register
  flag ON                                  → existing flow (verification token)
  flag OFF + valid pending invite (email)  → existing flow
  flag OFF + no/invalid invite             → 403

POST /iam/organizations
  flag ON   → existing flow (201)
  flag OFF  → 403
```

Two independent switches; production sets both off. Half-set states degrade
safely (UI may show the form, but the API 403s).

## Error handling

- Backend: 403 raised before any DB write in both endpoints → no partial
  org/user/membership/project/verification rows, no Loops/Stripe side effects.
- Frontend: the existing `handleSubmit` catch surfaces the 403 message (relevant
  only in half-set/bypass states).

## Testing

**Backend** (`backend/tests/integration/test_auth_api.py`):
- `test_register_blocked_when_flag_off_no_invite`: monkeypatch flag off → 403;
  assert **no** rows created in User, Organization, OrganizationMember, Project,
  VerificationToken; assert lifecycle (`emit_signup`/`emit_trial_started`) and
  Stripe trial are **not** invoked (mock + assert-not-called).
- `test_register_allowed_with_valid_invite_when_flag_off`: seed a pending
  invitation for the email, flag off → succeeds (201/verification path).
- `test_register_blocked_with_mismatched_or_expired_invite_when_flag_off`:
  wrong email / expired / unknown token → 403.
- Flag-on happy path already covered by existing tests (verify they still pass).

**Backend** (`backend/tests/integration/test_iam_api.py` or the org test file):
- `test_create_organization_blocked_when_flag_off` → 403; works when on.

**Backend** (`backend/tests/unit/`, parity with
`test_settings_external_protocols.py`):
- assert `RegistrationFeatureConfig` default is `True` and env override flips it.

**Frontend** (new `frontend/src/routes/register/page.test.ts`):
- `vi.mock('$lib/feature-flags')` flag off, no invite → waitlist card present,
  form absent.
- flag off, `?invite=` present → form present, no waitlist card.
- flag on → form present, no waitlist card.

## Files touched

| File | Change |
| --- | --- |
| `backend/app/core/config.py` | add `RegistrationFeatureConfig`, wire into `FeaturesConfig` |
| `backend/app/schemas/auth.py` | `invite_token` on `RegisterRequest` |
| `backend/app/api/endpoints/auth.py` | gate + `_invite_permits_registration` helper; fix invite redirect; flag-aware `VERIFY_ERROR_HTML` |
| `backend/app/api/endpoints/iam.py` | gate `create_organization` |
| `backend/.env.example`, `backend/settings.example.yaml` | document the flag |
| `backend/tests/integration/test_auth_api.py` | gate + invite-exemption tests |
| `backend/tests/integration/test_iam_api.py` (or org test file) | org-gate test |
| `backend/tests/unit/test_settings_*.py` | config default/override test |
| `frontend/src/lib/feature-flags.ts` | `REGISTRATION_ENABLED` (default-on) |
| `frontend/src/lib/auth.svelte.ts` | `register()` forwards `invite_token` |
| `frontend/src/lib/components/shared/RegistrationWaitlist.svelte` | new card |
| `frontend/src/routes/register/+page.svelte` | flag/invite gating + waitlist |
| `frontend/src/routes/login/+page.svelte` | flag-aware "Register"/"Join the waitlist" link |
| `frontend/.env.example` | `VITE_REGISTRATION_ENABLED=true` |
| `frontend/src/routes/register/page.test.ts` | new frontend test |
| `CLAUDE.md` | flag-table row |

## Acceptance-criteria deviations (user-approved)

- **Standalone card, not a modal** (decision 3).
- **Scope broadened** to also gate `POST /iam/organizations` (decision 2) and to
  exempt invitees (decision 1) — both beyond the literal task AC but required for
  the feature to be correct in production.
