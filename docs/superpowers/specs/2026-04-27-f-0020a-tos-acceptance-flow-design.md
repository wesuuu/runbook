# F-0020a — Terms of Service & Legal Acceptance Flow

**Status:** Approved
**Date:** 2026-04-27
**Author:** Wesley Uykimpang (with Claude)
**ClickUp:** [F-0020a](https://app.clickup.com/t/86e0ja7bv)

## Summary

Add a clickwrap Terms of Service / Privacy Policy acceptance flow that gates app usage on first authenticated load and on subsequent ToS version changes. Versioned ToS and Privacy Policy content lives in the backend (`backend/app/legal/versions/<date>/{terms,privacy}.md`) and is served via public endpoints. The User row records the version and timestamp accepted; durable history goes to the existing `audit_logs` table. Two bypass knobs accommodate enterprise/on-prem deployments: a deployment-level env var and an organization-level override flag.

## Goals

- Block authenticated, email-verified users from using the app until they accept the current ToS version.
- Re-prompt for acceptance whenever the ToS version changes (deploy-controlled).
- Maintain a durable record of every acceptance event suitable for clickwrap defensibility.
- Provide publicly viewable ToS and Privacy Policy pages so prospective users have notice before signing up.
- Make versioned content easy to add and review in PRs (one directory per version, markdown files inside).
- Support enterprise/on-prem deployments where a separately-negotiated agreement supersedes the click-through.
- Keep the implementation consistent with existing auth gates (`email_verified`) and existing audit infrastructure.

## Non-goals

- Backend enforcement of ToS state on API endpoints. Only the frontend layout enforces the gate. Documented as a known limitation; revisit if/when API-direct usage by external customers begins.
- A dedicated `tos_acceptances` table. We reuse `audit_logs`. Migrate later if a lawyer asks for it.
- Admin UI for editing ToS content or for toggling `Organization.legal_terms_overridden`. Versions are bumped via code/markdown changes in the repo; the override flag is set via DB write or a future admin tool.
- Legal review by counsel. Documents are drafted in good faith but flagged in source for counsel review before signing first paid contract or accepting any regulated data.
- E2E (Playwright) test for the gate flow. Component + layout vitest coverage is sufficient; mirror existing email-verification gating coverage.
- A cloud SaaS path that lets a user re-accept the previous version (downgrade). Re-acceptance always lands on `get_current_version()`.

## Architecture

### Backend

**Model changes** (`backend/app/models/iam.py`):

```python
class User(Base, UUIDMixin, TimestampMixin):
    # ... existing fields ...
    tos_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
```

**Versioned content (single source of truth, backend-served):**

```
backend/app/legal/
├── __init__.py
├── service.py          # get_current_version(), get_document(version, doc), list_versions()
└── versions/
    ├── __init__.py     # VERSIONS = ["2026-04-27", ...]  (chronological order)
    └── 2026-04-27/
        ├── terms.md
        └── privacy.md
```

`get_current_version()` returns `VERSIONS[-1]`. Bumping the version = drop a new dated directory with `terms.md` and `privacy.md`, append the version string to `VERSIONS`. Reviewed atomically in one PR with the new content.

`get_document(version, doc)` reads the file at module load time (cached) and returns `{ markdown: str, version: str, effective_date: str }`. `doc ∈ {"terms", "privacy"}`. Raises 404 if either the version directory or the file is missing.

**Configuration** (`backend/app/core/config.py`):

```python
legal_gate_enabled: bool = True  # env: BATCHRITE_LEGAL_GATE_ENABLED
```

When `false`, the gate is bypassed globally — `tos_current` always returns `true`. Intended for fully on-prem deployments where every user is covered by a separately-negotiated MSA.

**Org-level override** (`backend/app/models/iam.py`):

```python
class Organization(Base, UUIDMixin, TimestampMixin):
    # ... existing fields ...
    legal_terms_overridden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
```

When `true` for the user's `selected_organization`, the gate is bypassed for that user — `tos_current` returns `true` regardless of `tos_version`. Intended for enterprise customers governed by a signed MSA. No admin UI in this task; set via DB or a follow-up admin tool.

**Endpoints:**

- `GET /legal/current` — public; returns `{ version, effective_date }`.
- `GET /legal/versions/{version}/terms` — public; returns `{ markdown, version, effective_date }`. 404 if version unknown.
- `GET /legal/versions/{version}/privacy` — public; same shape.
- `POST /auth/accept-tos` — auth required:
  - No request body. Reads `request.client.host` for `ip_address` and `request.headers.get("user-agent")` for `user_agent`.
  - Sets `current_user.tos_accepted_at = func.now()`, `current_user.tos_version = get_current_version()`.
  - Writes one `AuditLog` row: `entity_type="user"`, `entity_id=current_user.id`, `actor_id=current_user.id`, `action="ACCEPT_TOS"`, `changes={"version": ..., "ip_address": ..., "user_agent": ...}`.
  - Commits and returns the updated user (same shape as `GET /auth/me`).
  - Idempotent: accepting twice rewrites the timestamp and writes a second AuditLog row.

**`/auth/me` response** gains:

- `tos_accepted_at: datetime | null`
- `tos_version: str | null`
- `tos_current: bool` — computed in the schema layer as:
  ```
  tos_current = (
      not settings.legal_gate_enabled
      or (selected_organization and selected_organization.legal_terms_overridden)
      or tos_version == get_current_version()
  )
  ```

`UserResponse` schema in `backend/app/schemas/iam.py` updated; `tos_current` is a `@computed_field` that takes the gate flag and current version into account.

**Migration** (Alembic, autogenerated then reviewed):

- `users.tos_accepted_at` (TIMESTAMP WITH TIME ZONE, nullable, default `null`).
- `users.tos_version` (VARCHAR, nullable, default `null`).
- `organizations.legal_terms_overridden` (BOOLEAN, NOT NULL, default `false`, server_default `'false'`).
- Existing user rows get `NULL` for both ToS columns. On next login they hit `tos_current = false` and get gated. Correct behavior.
- Existing org rows get `false` for the override (no surprise bypasses).

### Frontend

**Routes** (under `frontend/src/routes/legal/`):

- `terms/+page.svelte` — public; renders ToS markdown.
- `privacy/+page.svelte` — public; renders Privacy Policy markdown.
- `accept/+page.svelte` — auth required; renders both documents (tabs) plus the clickwrap form.

**Components** (under `frontend/src/lib/components/legal/` — new domain bucket):

- `LegalDocument.svelte` — props: `{ title: string; markdown: string; version: string; effectiveDate: string }`. Renders markdown by reusing whichever markdown rendering approach is already used in the chat panel (e.g., `marked` + sanitization). Implementation note: identify the existing renderer during the first task; if no shared component exists yet, either extract one from chat into `lib/components/shared/` or render inline within `LegalDocument.svelte` using the same library chat uses. Do not add a new markdown dependency. Top of the document shows title, version, and effective date.
- `AcceptForm.svelte` — two checkboxes ("I have read and agree to the Terms of Service" / "...Privacy Policy"), Accept button (disabled until both checked), error display, calls `acceptTos()` from `auth.svelte.ts` on submit. Reuses `Button`, `Checkbox` from `lib/components/ui/`.

**Markdown content lives in the backend** (see "Versioned content" above). The frontend has no markdown files and no version constant — it fetches everything from the backend on demand.

Each markdown file begins with an HTML comment:
```
<!-- TODO: Have counsel review before signing first paid contract or accepting any regulated data. Last drafted: 2026-04-27 by Wesley + Claude. -->
```

`/legal/terms`, `/legal/privacy`, and `/legal/accept` each call `GET /legal/current` to discover the current version, then `GET /legal/versions/{version}/terms` and `/privacy` for the content. The settings-page "you accepted version X" link uses the same endpoints to render the *historical* version the user accepted, which may differ from current.

**Auth state** (`frontend/src/lib/auth.svelte.ts`):

- Add to user shape: `tos_accepted_at`, `tos_version`, `tos_current`.
- Add `isTosCurrent()` getter.
- Add `acceptTos()` action: posts to `/auth/accept-tos`, updates the local user state with the response.

**Layout gating** (`frontend/src/routes/+layout.svelte`):

- Add `/legal/terms`, `/legal/privacy` to `publicRoutes`.
- In `onMount` after the `isEmailVerified` check, before the field-mode branch:
  ```ts
  if (
      isAuthenticated() &&
      isEmailVerified() &&
      !isTosCurrent() &&
      $page.url.pathname !== '/legal/accept'
  ) {
      goto('/legal/accept');
  }
  ```
- Mirror in `beforeNavigate`.
- `showNav` evaluates to `false` on `/legal/accept` (clean reading surface).
- Already-accepted user landing on `/legal/accept` is redirected to `/` from within that page's own onMount.

**Login & register pages** (`frontend/src/routes/login/+page.svelte`, `register/+page.svelte`):

- Below the form, add: "By continuing, you agree to our [Terms of Service](/legal/terms) and [Privacy Policy](/legal/privacy)."

**Settings page**:

- Add a "Legal" section/row under settings showing: "You accepted Terms of Service version `<version>` on `<formatted date>`" with links to view both documents. No re-accept button.

### Data flow

**First-time / new user:**
1. User registers → email verification → first authenticated load.
2. `/auth/me` returns `tos_current: false` (because `tos_version` is null).
3. Layout redirects to `/legal/accept`.
4. User reads, checks both boxes, clicks Accept.
5. Frontend POSTs `/auth/accept-tos`. Backend writes user fields and AuditLog.
6. Frontend updates auth state, navigates to `/`.

**Re-acceptance after version bump:**
1. Deploy includes a new directory under `backend/app/legal/versions/` (e.g., `2026-08-01/terms.md`, `privacy.md`) and appends `"2026-08-01"` to `versions/__init__.py::VERSIONS`.
2. Next `/auth/me` returns `tos_current: false` for users with stale versions (unless their org has `legal_terms_overridden=true` or `legal_gate_enabled=false`).
3. Layout redirects to `/legal/accept`.
4. Frontend fetches `GET /legal/current` then the new version's markdown and renders it.
5. New AuditLog row records the re-acceptance; old row is preserved.

**Public viewing:**
- Anyone (logged out, logged in, mid-acceptance) can read `/legal/terms` and `/legal/privacy`. Logged-in users see the standard nav; others see a minimal layout.

**Field mode:**
- ToS gate runs before the field-mode branch in the layout. Field-mode users get the same `/legal/accept` page (responsive — works on tablets).

**Mid-session version bump:**
- Cached user state is stale until next layout init or next user-state refresh. Acceptable. No polling.

## Content

### Terms of Service (sections)

1. Acceptance — clickwrap binding; effective on date of acceptance.
2. Description of service — laboratory execution system; protocol authoring; run execution; data storage; AI-assisted features.
3. **Research Use Only (RUO) designation** — explicit statement that Batchrite is for research use only; not a medical device under 21 CFR 820, not validated for cGMP/GLP/GxP regulated workflows; customer responsible for any qualification/validation if used in a regulated context.
4. **Prohibition on Protected Health Information** — customer represents and warrants no PHI as defined under HIPAA 45 CFR 160.103 will be uploaded; we are not a Business Associate; no BAA implied; immediate suspension if PHI detected.
5. Account & eligibility — 18+, business/research use, accurate info.
6. License grant — limited, non-exclusive, non-transferable license.
7. Customer data ownership & license to us — customer retains all rights; grants license to host/process/display to deliver service. **AI training use forbidden without separate consent.**
8. Acceptable use — no illegal use, no reverse engineering, no scraping, no PHI, no resale.
9. Intellectual property — our IP stays ours; customer IP stays theirs.
10. Confidentiality — mutual; customer data is confidential information.
11. Fees & payment — Stripe-mediated; no refunds for partial periods.
12. Term & termination — month-to-month default; either party may terminate; data export window; deletion after window.
13. Warranty disclaimer — service "as is"; no warranty of fitness for regulated use.
14. Limitation of liability — capped at fees paid in prior 12 months; no consequential damages.
15. Indemnification — mutual, capped.
16. Governing law & dispute resolution — California governing law; informal dispute first; arbitration in San Francisco under AAA rules; no class action.
17. Changes to terms — material changes trigger re-acceptance via clickwrap.
18. Contact — `legal@batchrite.com`.
19. Effective date / version — `Version: 2026-04-27`.

### Privacy Policy (sections)

1. Scope — applies to use of Batchrite; not third-party sites.
2. Information we collect — account info, content, usage telemetry, AI prompts/responses, billing info via Stripe, OAuth provider data.
3. How we use it — deliver service, support, billing, security, product improvement (aggregated/de-identified only).
4. AI processing disclosure — when AI features are used, prompts/data may be sent to third-party LLM providers (OpenAI, Anthropic, etc.); under our config, providers do not retain or train on customer data; org admins can disable AI. **We do not use customer data to train models.**
5. Sharing — sub-processors (cloud host, Stripe, LLM providers); legal requirements; no sale of data.
6. Cookies & local storage — session token, preferences, offline cache; no third-party advertising cookies.
7. Retention — content retained for life of account + 30-day grace; backups up to 90 days; audit logs longer for compliance.
8. Security — encryption in transit and at rest, RBAC, audit logs.
9. Your rights — access, export, deletion (CCPA/GDPR-aligned); contact for requests.
10. Children — service not directed to under 18.
11. International transfers — data hosted in US; international users consent to transfer.
12. Changes — material changes trigger re-acceptance.
13. Contact — `privacy@batchrite.com`.
14. Effective date / version — `Version: 2026-04-27`.

## Testing strategy

### Backend (pytest, TDD)

`tests/unit/test_legal_service.py`:
- `get_current_version()` returns the last entry in `VERSIONS`.
- `get_document(current, "terms")` returns markdown content + version + effective_date.
- `get_document(current, "privacy")` returns markdown content + version + effective_date.
- `get_document("does-not-exist", "terms")` raises a 404-equivalent error.
- `get_document(current, "bogus-doc")` raises a 404-equivalent error.

`tests/integration/test_legal_endpoints.py`:
- `GET /legal/current` returns `{ version, effective_date }` (no auth required).
- `GET /legal/versions/{version}/terms` returns markdown for known version (no auth required).
- `GET /legal/versions/{version}/privacy` returns markdown for known version (no auth required).
- `GET /legal/versions/unknown-version/terms` returns 404.

`tests/integration/test_auth_tos.py`:
- `POST /auth/accept-tos` requires authentication (401 without token).
- `POST /auth/accept-tos` sets `tos_accepted_at` to ~now and `tos_version` to `get_current_version()` on the calling user.
- `POST /auth/accept-tos` writes one `AuditLog` row with the documented `entity_type`, `entity_id`, `action`, and `changes` fields including `version`, `ip_address`, `user_agent`.
- Calling twice writes two AuditLog rows but only one user record (idempotent overwrite).
- `GET /auth/me` returns `tos_accepted_at`, `tos_version`, `tos_current` correctly across the three states: never accepted, accepted current, accepted older version.

Gate-bypass tests (`tests/integration/test_auth_tos_bypass.py`):
- When `settings.legal_gate_enabled = false`, `tos_current` returns `true` for a user with `tos_version = null`.
- When the user's `selected_organization.legal_terms_overridden = true`, `tos_current` returns `true` for a user with `tos_version = null`.
- When the user has no `selected_organization`, the org-override path is a no-op and the version comparison still applies.

Migration:
- Apply on a DB seeded with users → `users` has `tos_accepted_at` and `tos_version` columns, both nullable, default `null`. `organizations` has `legal_terms_overridden` column, default `false`.

### Frontend (vitest)

`auth.svelte.test.ts`:
- `isTosCurrent()` returns `true` when user payload has `tos_current: true`, `false` otherwise.
- `acceptTos()` posts to `/auth/accept-tos` and refreshes user state on success.

`legal-api.test.ts`:
- `fetchCurrentLegalVersion()` calls `GET /legal/current` and returns `{ version, effective_date }`.
- `fetchLegalDocument(version, "terms")` calls `GET /legal/versions/{version}/terms`.
- `fetchLegalDocument(version, "privacy")` calls `GET /legal/versions/{version}/privacy`.

`LegalDocument.svelte` test:
- Renders provided markdown; shows title, version, effective date.

`AcceptForm.svelte` test:
- Accept button is disabled until both checkboxes are checked.
- Clicking Accept calls `acceptTos()` and navigates on success.

Layout gating test (mocking auth state):
- When authenticated + email verified + `!tos_current` + pathname not `/legal/accept` → redirect to `/legal/accept`.
- Public routes `/legal/terms` and `/legal/privacy` accessible without auth.
- Already-accepted user visiting `/legal/accept` is redirected to `/`.
- When `tos_current` is `true` because the gate is disabled or the org has overridden, the user is *not* redirected.

### E2E

Skipped. Component + layout vitest coverage is sufficient.

## Open questions / known limitations

- **Backend ToS enforcement on API:** Out of scope. The clickwrap is enforced via the frontend layout only. Acceptable for current product stage (no external API customers). Revisit before opening API access.
- **Mid-session staleness on version bump:** Users who are mid-session when a deploy bumps the version don't get gated until next layout init. Acceptable; we don't poll.
- **Counsel review:** Documents are drafted as best-effort and flagged in source. Trigger for actual review: first paid contract, first regulated-data customer, first enterprise MSA, or priced funding round — whichever comes first.
- **On-prem deployments:** Pure on-prem instances should set `BATCHRITE_LEGAL_GATE_ENABLED=false`; the entire instance is one customer governed by a separately-negotiated agreement, and the click-through is redundant. Updates to the on-prem agreement happen via contract renewal, not in-app prompts.
- **Enterprise customers on cloud:** Set `Organization.legal_terms_overridden = true` (manual DB write or a future admin tool) when an org signs an MSA. All members of that org bypass the click-through. No admin UI for this in this task.
- **Multi-org users with mixed override status:** A user whose `selected_organization` has `legal_terms_overridden=true` will bypass the gate — but if they switch to an org that doesn't have it, the gate kicks back in on next page load. Acceptable; the bypass is per-current-org, which matches the legal reality (the agreement covers them only while acting in that org's context).

## Acceptance criteria (mapping back to ClickUp task)

- [x] User model fields `tos_accepted_at` and `tos_version`.
- [x] Acceptance gate route at `/legal/accept`.
- [x] Full ToS content with RUO and PHI sections.
- [x] Privacy Policy.
- [x] Consent record keeping (via `audit_logs`).
- [x] Re-acceptance on version change.
- [x] Versioned content directory `backend/app/legal/versions/<date>/` (single source of truth).
- [x] Deployment-level bypass via `BATCHRITE_LEGAL_GATE_ENABLED`.
- [x] Org-level bypass via `Organization.legal_terms_overridden`.
