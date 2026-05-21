# F-0091 — GitHub-style frontend routes (`/:org/:object/:slug`)

**Status:** Design approved · **Date:** 2026-05-19 · **Effort:** XL

## Problem

Frontend URLs expose raw UUIDs (`/protocols/<uuid>`, `/runs/<uuid>`, `/projects/<uuid>`).
They are ugly, not memorable, and not shareable. Restructure to a GitHub-style
hierarchy: `/<org-slug>/<object>/<name-slug>` — e.g. `/acme/protocols/buffer-prep`.

## Scope

Five routed objects gain a stored, slug-addressable URL:

- Protocol
- Run
- Experiment
- Project
- Library document

**Org slug is derived, not stored.** Equipment and Site are out of scope.

## Key design decisions

### 1. Org slug is derived; object slugs are stored

Every authenticated request already resolves the organization from the JWT
(`get_current_user` → `user.selected_org_id`). The org segment of the URL is
therefore **never used to identify the org** — it is cosmetic, validated only as a
guard. Consequences:

- `Organization` needs **no `slug` column**, no unique index, no backfill. The org
  slug is computed live as `slugify(org.name)` wherever a URL is rendered.
- Two distinct orgs may both render the prefix `koch-inc`; each user only ever sees
  their own tenant's data because every query is scoped by `selected_org_id`.

Object slugs **must** be stored, because the JWT identifies the org but not *which*
object. Two protocols named "Buffer Prep" inside one org are identical on every
queryable column; only a stored, persisted slug can address each unambiguously.

### 2. Reject on collision (not suffix)

Within an organization, no two objects of the same type may share a slugified name.
A collision on the live create/rename path is **rejected** with HTTP `422` and the
stable error code `SLUG_CONFLICT` ("a protocol named 'Buffer Prep' already exists in
this org"). Across orgs there is no constraint.

This **overrides the ticket AC**, which specified server-side suffix resolution
(`-2`, `-3`, …). The ticket text should be updated to match. Suffix logic still runs
**once**, in the migration backfill, to disambiguate pre-existing duplicate names so
the unique index can be applied to legacy data.

### 3. Re-slug on rename

The slug regenerates from the new name on every rename. The URL always reflects the
current name. Old shared links to a renamed object die — acceptable, since the
feature already mandates a hard break with no redirect layer.

### 4. Hard break, no redirects

Old UUID URLs return a native SvelteKit `404`. No redirect/compatibility layer.

## Slug semantics

`slugify(name)`:

1. Lowercase.
2. Strip accents (NFKD normalize, drop combining marks).
3. Drop non-alphanumeric characters.
4. Collapse runs of separators to a single `-`.
5. Trim leading/trailing `-`.
6. Cap at 64 characters.

A name that slugifies to empty (e.g. all-emoji) falls back to
`untitled-<first 6 hex of row id>` — stored, guaranteed unique. This is the only
degenerate case.

The rule is implemented once in Python and mirrored once in TypeScript. It is **not**
reimplemented as a SQL function: uniqueness is enforced by a plain unique index on
the stored column, never a functional `UNIQUE(slugify(name))` index.

## Backend

### Shared helper

`backend/app/core/slug.py` → `slugify(name: str) -> str`. Stateless module function.

### Models

Add to Protocol, Run, Experiment, Project, LibraryDocument:

- `slug` — `String(64)`, `NOT NULL`, indexed.
- `UNIQUE(organization_id, slug)` per table.

`organization_id` availability:

- Project, LibraryDocument — already have it.
- Protocol — has a nullable `organization_id` (set only when org-scoped); ensure it
  is **always populated** (backfilled from the project when project-scoped).
- Run, Experiment — have only `project_id`. Add a denormalized, immutable
  `organization_id`, copied from the project at create time.

### Service layer

`assign_slug(db, Model, org_id, name, exclude_id=None)`:

- Slugifies `name`.
- Checks `UNIQUE(organization_id, slug)` for that table (excluding `exclude_id` on
  rename).
- Raises `ValueError("SLUG_CONFLICT")` if taken.

Called inside the existing create and name-update service functions. Endpoints catch
`ValueError` and convert to `422`.

### By-slug read endpoints

```
GET /protocols/by-slug/{slug}
GET /runs/by-slug/{project_slug}/{slug}
GET /experiments/by-slug/{project_slug}/{slug}
GET /projects/by-slug/{slug}
GET /library/documents/by-slug/{slug}
```

- Org resolved from session.
- Return the **same response schema** as the corresponding UUID endpoint.
- `404` when no match exists in the session org.
- Mutation endpoints (UUID-keyed) are **untouched** — the object is loaded
  client-side and carries its `id`.

### Response schemas

Add `slug` to the detail and list response schemas for the five objects, so the
frontend can build URLs after fetch / create / rename.

## Frontend

### `[org]/` route group

`frontend/src/routes/[org]/+layout.ts` (load):

- Reads the authenticated user from parent layout data.
- Computes `slugify(user.selected_organization.name)`.
- Compares to `params.org`; mismatch → `error(404)`.
- Exposes the org slug to descendant routes (org store / layout data).

### Routes moved under `[org]/`

```
[org]/protocols/[slug]/+page.svelte   (+ +layout.svelte)
[org]/runs/[slug]/+page.svelte
[org]/experiments/[slug]/+page.svelte
[org]/projects/+page.svelte
[org]/projects/[slug]/+page.svelte
[org]/library/+page.svelte
[org]/library/[slug]/+page.svelte
[org]/library/documents/[slug]/refine/+page.svelte
```

Unprefixed (unchanged): auth routes, `/settings`, `/chat`, `/field`, `/export`,
`/organization/*`, home `/`.

### Data loading

Page components read `params.slug` and fetch via new API-client functions
(`getProtocolBySlug(slug)`, etc.) — matching the existing client-side fetch pattern.
Only the `[org]` layout uses a load function.

### Path helper

`frontend/src/lib/paths.ts`:

- `protocolPath(slug)`, `runPath(slug)`, `experimentPath(slug)`, `projectPath(slug)`,
  `libraryDocPath(slug)`, … reading the current org slug from the org store.
- TS `slugify` mirror (used by the `[org]` layout's org-slug comparison).

Every `goto(` and `<a href=` navigation call site (~89) is updated to use these
helpers. After a create or rename, the API response carries the object's `slug` to
navigate with.

### Hard break

Old `/protocols/[id]` route files are deleted; SvelteKit returns `404` natively.

## Migration & backfill

One Alembic migration:

1. Add nullable `slug` columns; add `organization_id` to Run and Experiment.
2. Data migration (imports `app.core.slug.slugify`):
   - Backfill `organization_id` on Run/Experiment (and ensure Protocol's is set)
     from the owning project.
   - Generate slugs per table, per org.
   - Resolve **pre-existing duplicate names** with one-time `-2`, `-3`, … suffixes.
3. `ALTER` `slug` → `NOT NULL`; add `UNIQUE(organization_id, slug)` index.

## Validation tier

The duplicate-name rule is **T1 (backend-only)**. Mirroring it as a frontend
preflight would require the full per-org name list; instead the backend returns
`422 SLUG_CONFLICT` and the frontend surfaces it as an inline error on the name
field.

## Testing

- **Unit** — Python `slugify` (accents, symbols, 64-char cap, empty→fallback,
  separator collapse); TS `slugify` parity test; `assign_slug` (collision raises,
  rename to a free slug, exclude-self).
- **Integration** — by-slug endpoints: happy path, `404` not-found, `404` wrong-org,
  slug reflects a rename, duplicate-name create → `422 SLUG_CONFLICT`.
- **Playwright** — navigate list → detail through slug URLs; bad org slug → `404`.
- **Migration** — backfill yields unique slugs including pre-existing duplicates.

## Out of scope

- Equipment and Site slugs / detail pages.
- Notification & email deep-link URL generation — `FormattedMessage.url` is
  currently unused, so there is nothing to "update."
- Redirects from old UUID URLs (hard break).
- Multi-org-per-user URL disambiguation (single org from session).

## Implementation note

The implementation worktree branches from `main`. TD-0083 (the science-module
split) has already merged to `main`, so slug columns are added to the per-domain
model files it produced: `models/protocols.py` (Protocol), `models/runs.py` (Run
and Experiment), `models/projects.py` (Project), and `models/library.py`
(Document). API paths are unprefixed (`/protocols`, `/runs`, `/experiments`) —
the legacy `/science/` namespace was removed by TD-0083.
