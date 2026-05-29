# F-0091 — Gate self-service registration behind a feature flag + Calendly waitlist modal

**Status:** Design
**Date:** 2026-05-29
**Task:** F-0091 (FEATURES, P1) — full stack
**Effort:** M (1–4hr)

## Problem

For the initial production deployment we are not opening self-service sign-up.
Registration must be gated behind a feature flag that is **default-on** (so
local/dev, tests, and the demo are unaffected) and **flipped off in
production**. With the flag off:

- A logged-out visitor landing on `/register` sees a **non-dismissible modal**
  directing them to book a Calendly meeting to join the first cohort, instead of
  a usable sign-up form.
- `POST /auth/register` returns **403** so the endpoint cannot be used even if
  the UI is bypassed.

Login, email verification, and the demo org must keep working unchanged with the
flag off.

## Non-goals

- No DB migration — config-flag only.
- No change to login, verification, OAuth, or invitation flows.
- No backend-served VITE flag plumbing; the frontend reads its own build-time
  env var (mirrors the existing offline/PWA flag split).

## Design

### 1. Backend flag + endpoint gate

Add a nested config block, following the existing `OfflineModeFeatureConfig` /
`ExternalProtocolsFeatureConfig` pattern in `backend/app/core/config.py`:

```python
class RegistrationFeatureConfig(BaseModel):
    """Self-service registration flag (F-0091). Default-on; flip OFF in prod."""

    enabled: bool = True


class FeaturesConfig(BaseModel):
    offline_mode: OfflineModeFeatureConfig = OfflineModeFeatureConfig()
    external_protocols: ExternalProtocolsFeatureConfig = ExternalProtocolsFeatureConfig()
    registration: RegistrationFeatureConfig = RegistrationFeatureConfig()
```

Env override falls out of the nested-delimiter convention:
`BATCHRITE_FEATURES__REGISTRATION__ENABLED=false`.

Gate at the very top of `register()` (`backend/app/api/endpoints/auth.py:167`),
before the duplicate-email lookup and any DB writes:

```python
if not settings.features.registration.enabled:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Registration is not available right now.",
    )
```

The detail string is generic (no mention of the flag/env var) so it leaks
nothing operationally; the env var to flip lives in CLAUDE.md and the deploy
runbook.

### 2. Frontend flag

Add to `frontend/src/lib/feature-flags.ts`, **default-on**:

```typescript
// F-0091: self-service registration. Default ON (only OFF when explicitly
// 'false') so local/dev and the demo are unaffected when the var is unset.
export const REGISTRATION_ENABLED: boolean =
    import.meta.env.VITE_REGISTRATION_ENABLED !== 'false';
```

The polarity differs deliberately from `OFFLINE_ENABLED` (`=== 'true'`,
default-off) because registration must default **on**.

### 3. Waitlist modal (store-less)

New `frontend/src/lib/components/shared/RegistrationWaitlistModal.svelte`,
composed from the shared `Dialog` primitive. **No store** — unlike
`SubscriptionLockoutModal` (which is triggered imperatively from API responses
anywhere), this modal's open state is a pure function of
`(flag OFF && on /register)` and is non-dismissible, so there is no mutable
state to hold. A store would add `open`/`dismiss` functions that never fire.

Props:

```typescript
interface Props {
    open: boolean;
    calendlyUrl: string;
}
```

Behavior:

- `Dialog.Root open={open}` with **no** `onOpenChange` close path — the modal is
  non-dismissible (no X button, no outside-click close, no Escape close). Use the
  Dialog content options that suppress those (`closeOnOutsideClick={false}`,
  `closeOnEscape={false}`, omit the close button) per the bits-ui/shadcn API.
- Title: "Registration is invite-only". Description explains the first-cohort
  waitlist.
- Primary button is an anchor to the Calendly URL:
  `target="_blank" rel="noopener noreferrer"`.
- A secondary "Back to sign in" link to `/login` so the visitor is never
  trapped.

The Calendly URL is hardcoded as a single module constant in the `/register`
page: `https://calendly.com/wes-batchrite/30min`.

### 4. `/register` page changes

In `frontend/src/routes/register/+page.svelte`:

- Import `REGISTRATION_ENABLED` and `RegistrationWaitlistModal`.
- Render `<RegistrationWaitlistModal open={!REGISTRATION_ENABLED} calendlyUrl={CALENDLY_WAITLIST_URL} />`.
- When the flag is OFF, wrap the existing form container with
  `class="blur-sm pointer-events-none select-none"` **and** the `inert`
  attribute. `inert` removes the form from the accessibility tree and blocks all
  interaction; the blur + non-dismissible modal give the intended visual. This
  reuses the existing form markup (no duplicated decorative copy — a DRY win) and
  satisfies the AC's "form is not usable / not submittable". The backend 403 is
  the real enforcement boundary; the inert form is presentation only.

No change to `PUBLIC_ROUTES` in `lib/auth-gate.ts` — `/register` is already
listed, so the gated page/modal is reachable while logged out.

### 5. Documentation / env examples

- `frontend/.env.example`: `VITE_REGISTRATION_ENABLED=true` with a comment.
- `backend/.env.example`: `BATCHRITE_FEATURES__REGISTRATION__ENABLED=true` with
  a comment.
- New row in the CLAUDE.md feature-flag table (flag, backend key, frontend key,
  default `true`, note: both halves must be set off to gate end-to-end; prod
  deploy sets both to `false`).

## Data flow

```
Visitor → GET /register (SvelteKit)
  REGISTRATION_ENABLED == true   → form renders normally, modal closed
  REGISTRATION_ENABLED == false  → form inert+blurred, non-dismissible modal open
                                   → Calendly (new tab) or /login

Any client → POST /auth/register
  settings.features.registration.enabled == true   → existing flow (201/verification)
  settings.features.registration.enabled == false  → 403 "Registration is not available right now."
```

The two halves are independent switches; production sets **both** off. A
half-set state (backend off, frontend on) degrades safely: the UI shows the form
but submission 403s with the generic message.

## Error handling

- Backend: 403 raised before DB work; no partial org/user creation possible.
- Frontend: the 403 is already surfaced by the existing `handleSubmit` catch as
  the error message — relevant only in the half-set/bypass case, since the inert
  form normally can't submit.

## Testing

- **Backend** (`backend/tests/integration/test_auth_api.py`):
  - `test_register_blocked_when_flag_off`: monkeypatch
    `settings.features.registration.enabled = False`, assert `POST /auth/register`
    → 403 and that no `User`/`Organization` row was created.
  - Add an explicit flag-**on** assertion (existing happy-path tests already
    exercise the 200/verification path with the default-on flag).
- **Frontend** (new `frontend/src/routes/register/page.test.ts` or co-located
  `*.test.ts`):
  - `vi.mock('$lib/feature-flags', ...)` flag **off** → waitlist modal present,
    form `inert`/non-interactive.
  - flag **on** → form present, modal absent.

## Files touched

| File | Change |
| --- | --- |
| `backend/app/core/config.py` | add `RegistrationFeatureConfig`, wire into `FeaturesConfig` |
| `backend/app/api/endpoints/auth.py` | 403 gate at top of `register()` |
| `backend/.env.example` | `BATCHRITE_FEATURES__REGISTRATION__ENABLED=true` |
| `backend/tests/integration/test_auth_api.py` | flag-off 403 test |
| `frontend/src/lib/feature-flags.ts` | `REGISTRATION_ENABLED` (default-on) |
| `frontend/src/lib/components/shared/RegistrationWaitlistModal.svelte` | new modal |
| `frontend/src/routes/register/+page.svelte` | flag-gated modal + inert form |
| `frontend/.env.example` | `VITE_REGISTRATION_ENABLED=true` |
| `frontend/src/routes/register/*.test.ts` | new frontend test |
| `CLAUDE.md` | flag-table row |

## Acceptance criteria mapping

All AC from the task are satisfied; the only deliberate deviation is **store-less
modal** (user-approved): the AC suggested mirroring the lockout store, but a
non-dismissible flag-derived modal has no mutable state, so a store is omitted as
YAGNI.
