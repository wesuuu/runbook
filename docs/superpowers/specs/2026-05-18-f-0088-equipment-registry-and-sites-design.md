# F-0088 — Equipment Registry with First-Class Sites

**Status:** Draft (revised post-grill 2026-05-18)
**Author:** Wesley Uykimpang (with Claude)
**Date:** 2026-05-18
**ClickUp:** [F-0088](https://app.clickup.com/t/86e1ef0zn)

## Summary

PD organizations operate from one or more physical sites (buildings/facilities) and
need a system of record for the equipment housed at each. This spec promotes **Site**
to a first-class flat entity scoped to an organization, extends the existing
`Equipment` model with the regulated-data fields F-0088 calls for (calibration dates,
status, serial, manufacturer/model, tags, attachments, soft-delete), adds an additive
**`SITE_MANAGER`** org role that gates the regulated-data edits and Site management,
ships REST endpoints under `/sites` and `/equipment`, and adds a management UI at
`/organization/sites`.

> **Scope departures from the ticket.** The ticket scoped building as a free-text
> field and listed first-class buildings as out of scope. Brainstorming reversed
> that to a first-class `Site` entity (flat, not hierarchical). The ticket's
> `BUILDING_MANAGER` role became `SITE_MANAGER` with a narrower scope — calibration
> data and Site CRUD only, not general equipment edits. Free-text Room is preserved
> as a string on Equipment, not its own entity. Calibration scheduling, usage logs,
> barcodes, and protocol/run linking remain out of scope.

## Decision log (from brainstorming + grill)

| # | Decision | Why |
|---|----------|-----|
| 1 | Extend the existing `Equipment` model in place; keep `location` as a free-text "spot description" (e.g. "Bench 4, north wall") | Existing model is wired into the protocol editor and run flows; preserves the 📍 chip in `EquipmentPickerModal` |
| 2 | `Site` is a **flat** entity per org (no `parent_id`, no nesting, no moves) | Sites are physical buildings; in real labs they don't reorganize. Drops a tree-UI, cycle-detection, and move semantics that would otherwise be required |
| 3 | `Equipment.site_id` is required (`nullable=False`) | Cleaner data; migration creates a Default Site per org and backfills |
| 4 | `room` is a free-text column on `Equipment` (not an entity) | Filtering/grouping by Room is client-side; modeling Rooms as entities would add CRUD/picker overhead with negligible benefit at v1 |
| 5 | Archiving a Site with non-archived Equipment **requires a move-to target**; the request fails without one | Keeps the `site_id` invariant honest; matches the user's mental model ("we're shutting down Site A — where does its stuff go?") |
| 6 | Default Site is **renamable but non-archivable**; no hard-delete API | Always-available fallback target for moves; FK constraint prevents accidental row deletion at the SQL level too |
| 7 | `SITE_MANAGER` is an **additive** org role (same shape as `PROTOCOL_APPROVER`); ADMIN must be explicitly listed in `require_any_org_role` checks | Existing additive pattern; `_RANK` in `require_org_role` is hierarchy-only and stays untouched |
| 8 | **Field-level permission split**: any member creates Equipment + edits *open fields* (`name`, `equipment_type`, `room`, `location`, `description`, `tags`). `SITE_MANAGER` / `ADMIN` gate *restricted fields* (`manufacturer`, `model`, `serial_number`, `status`, `install_date`, `last_calibration_date`, `next_calibration_due`), all Site CRUD/archive, Equipment archive, and attachments | Calibration data is GLP-relevant — lab-manager call, not benchwork. Equipment creation is daily science — open. |
| 9 | One `PATCH /equipment/{id}` endpoint with a payload-aware gate (reject if a non-`SITE_MANAGER` touches a restricted field) | Avoids endpoint sprawl; UX is one form; explicit error code `EQUIPMENT_FIELD_RESTRICTED` lists offending fields |
| 10 | Drop redundant fields the ticket invented: `notes` (use existing `description`), `bench_or_position` (use existing `location`) | Two text fields for the same job is a UX smell; the existing columns work |
| 11 | URL prefix uses plural, matching codebase convention: `/sites`, `/equipment` (not `/site/*`) | Existing routers: `/projects`, `/protocols`, `/runs`. One-off namespace `/site/*` would need explaining for every new contributor |
| 12 | Tags get type-ahead from existing org tags + server-side normalization; `GET /equipment/tags` powers the dropdown | Free-text-only would drift fast; curated tag CRUD is too heavyweight |
| 13 | No subscription-tier gate; `require_active_subscription()` only | Foundational refactor of an existing feature; no product pricing decision made |
| 14 | Single atomic Alembic revision (no zero-downtime split) | Codebase precedent; product is pre-GA with small data; lock window negligible |
| 15 | Attachments allow PDF + Office docs + common images, 25 MB cap | Matches what manufacturers actually distribute (PDF manuals, scanned certs) |

## Goals

1. Flat, org-scoped Site entity (`sites` table) with auto-provisioned "Default Site" per org.
2. Extend `Equipment` with manufacturer, model, serial_number, status (enum), install_date, last_calibration_date, next_calibration_due, room, tags, soft-delete, attachments, created_by_id; require `site_id`.
3. Additive `SITE_MANAGER` org role with field-level permission split on Equipment.
4. REST endpoints under `/sites` and `/equipment` (replace the existing `/iam/...` equipment routes).
5. Management UI at `/organization/sites` (top-level route group).
6. Migration backfills existing Equipment rows to per-org Default Sites.

## Non-goals

- Hierarchical sites (Site → Building → Room nested entities).
- Hard-delete API for Sites; soft archive only.
- Calibration reminder notifications.
- Linking equipment to protocols/runs (already wired via `equipment_context.py`).
- Equipment usage / maintenance history beyond date fields.
- Barcode/QR labels.
- Cross-org shared sites.

## Architecture

### Data model

```
organizations
   └── sites (1:N, flat)
         └── equipment (1:N, site_id required)
                └── equipment_attachments (1:N)
```

#### `sites` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK (UUIDMixin) |
| organization_id | UUID FK orgs.id | NOT NULL, indexed |
| name | String | NOT NULL |
| description | String | NULL |
| archived_at | timestamptz | soft-delete |
| archived_by_id | UUID FK users.id | NULL |
| created_by_id | UUID FK users.id | NULL on system-created Default Site |
| created_at / updated_at | timestamptz | TimestampMixin |

Indexes:
- `ix_sites_org` on `(organization_id)`
- `uq_sites_org_name` on `(organization_id, name)` — partial unique where `archived_at IS NULL` (prevents duplicate active names per org; allows reusing the name after archive)

#### `equipment` table (extend existing)

Existing columns retained: `id`, `organization_id`, `name`, `description`, `equipment_type`, `location` (semantic: "spot description" — free-text bench/position).

New columns:

| Column | Type | Notes |
|--------|------|-------|
| site_id | UUID FK sites.id | **NOT NULL** after migration backfill |
| created_by_id | UUID FK users.id | NULL on legacy rows |
| manufacturer | String | NULL |
| model | String | NULL |
| serial_number | String | NULL |
| status | String (enum) | default `'ACTIVE'`, server_default `'ACTIVE'`, `EquipmentStatus.{ACTIVE,MAINTENANCE,RETIRED}` |
| install_date | Date | NULL |
| last_calibration_date | Date | NULL |
| next_calibration_due | Date | NULL |
| room | String | NULL — free-text room name (e.g. "Lab 204") |
| tags | `ARRAY(String)` | default `[]`, server_default `ARRAY[]::varchar[]`, normalized server-side |
| archived_at | timestamptz | soft-delete |
| archived_by_id | UUID FK users.id | NULL |

Indexes (new):
- `ix_equipment_site` on `(site_id)`
- `ix_equipment_org_status` on `(organization_id, status)`

The existing index on `organization_id` is retained.

#### `equipment_attachments` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| equipment_id | UUID FK equipment.id ON DELETE CASCADE | NOT NULL |
| file_path | String | relative path returned by `FileStorageService` |
| original_filename | String | NOT NULL |
| mime_type | String | NOT NULL |
| size_bytes | Integer | NOT NULL |
| uploaded_by_id | UUID FK users.id | NOT NULL |
| created_at / updated_at | timestamptz | TimestampMixin |

Attachment validation:
- Allowed MIME: `application/pdf`, `image/jpeg`, `image/png`, `image/webp`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.ms-excel`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Max size: 25 MB
- Stored under `FileStorageService(base_dir="equipment", org_id=...)`

#### `OrgRole` enum + CHECK constraint

Add `SITE_MANAGER = "SITE_MANAGER"`. Update the `OrganizationMember` CHECK constraint to include it. Update `_ALLOWED_ORG_ROLES` and `_LEGACY_ROLE_RANK` (`schemas/iam.py`) — rank `SITE_MANAGER` at 2 (same as `PROTOCOL_APPROVER`); ties are fine since `ADMIN`/`BILLING` still dominate the legacy display field.

### Permission model

| Action | Who |
|---|---|
| GET `/sites`, `/sites/{id}` | Any org member |
| GET `/equipment`, `/equipment/{id}`, `/equipment/{id}/attachments`, `/equipment/tags` | Any org member |
| POST `/equipment` (create) | Any org member |
| PATCH `/equipment/{id}` open-fields only (`name`, `equipment_type`, `room`, `location`, `description`, `tags`) | Any org member |
| PATCH `/equipment/{id}` touching any restricted field (`manufacturer`, `model`, `serial_number`, `status`, `install_date`, `last_calibration_date`, `next_calibration_due`) | `SITE_MANAGER` ∨ `ADMIN` |
| DELETE `/equipment/{id}` (archive) | `SITE_MANAGER` ∨ `ADMIN` |
| POST/DELETE `/equipment/{id}/attachments`, `DELETE /equipment/attachments/{id}` | `SITE_MANAGER` ∨ `ADMIN` |
| POST/PATCH/DELETE `/sites/...` | `SITE_MANAGER` ∨ `ADMIN` |

New dependency factory `require_any_org_role(roles: list[OrgRole]) -> User` in `app/core/deps.py` (additive — any of the listed roles satisfies). ADMIN must be explicitly listed in the role argument; it does not implicitly satisfy via hierarchy.

The field-level gate on `PATCH /equipment/{id}` is enforced inside the handler:

```python
RESTRICTED_EQUIPMENT_FIELDS = frozenset({
    "manufacturer", "model", "serial_number", "status",
    "install_date", "last_calibration_date", "next_calibration_due",
})

# In the handler:
touched = set(payload.model_dump(exclude_unset=True).keys())
restricted_touched = touched & RESTRICTED_EQUIPMENT_FIELDS
if restricted_touched and not member_has_any_role(member, [ADMIN, SITE_MANAGER]):
    raise HTTPException(403, {
        "code": "EQUIPMENT_FIELD_RESTRICTED",
        "fields": sorted(restricted_touched),
    })
```

Validation tier (per `conventions.md`): **T2** — backend authoritative, frontend preflights via disabled inputs + tooltips.

Stable error codes: `EQUIPMENT_FIELD_RESTRICTED`, `EQUIPMENT_SITE_REQUIRED`, `EQUIPMENT_SITE_CROSS_ORG`, `SITE_ARCHIVE_NEEDS_MOVE_TO`, `SITE_ARCHIVE_DEFAULT_FORBIDDEN`, `SITE_NAME_CONFLICT`.

### Service layer

`app/services/sites/` (new module, module-function style per `conventions.md`):

- `crud.py`
  - `list_sites(db, org_id, *, include_archived=False) -> list[Site]`
  - `get_site(db, site_id) -> Site`
  - `create_site(db, *, org_id, payload, actor_id) -> Site` (audit)
  - `update_site(db, site, *, payload, actor_id) -> Site` (audit; name-conflict guard)
  - `archive_site(db, site, *, move_equipment_to: UUID, actor_id) -> Site`
    - Refuses if `site.name == "Default Site"` (or generally if the site is the org's default — see `defaults.is_default_site`).
    - Bulk-updates all non-archived equipment under `site` to point at `move_equipment_to`.
    - Validates `move_equipment_to` is in the same org and is not archived and is not the site being archived.
    - Sets `archived_at`, `archived_by_id`. One audit row for the site archive + one consolidated audit row for the equipment move (`changes={"moved_equipment_count": N, "from_site_id": ..., "to_site_id": ...}`) plus per-equipment audit rows (`UPDATE`, `changes={"site_id": [old, new]}`) for full traceability.
- `defaults.py`
  - `DEFAULT_SITE_NAME = "Default Site"`
  - `ensure_default_site(db, org_id, actor_id) -> Site` — idempotent; called by org-registration code and by the data migration.
  - `is_default_site(site) -> bool` — `site.name == DEFAULT_SITE_NAME` (simple; could be tightened later via a boolean column if rename collides).

`app/services/equipment/` (new module):

- `registry.py`
  - `list_equipment(db, org_id, *, site_id=None, status=None, q=None, tag=None, include_archived=False) -> list[Equipment]`
  - `get_equipment(db, equipment_id) -> Equipment`
  - `create_equipment(db, *, org_id, payload, actor_id) -> Equipment` (audit; validates `site_id` in same org and not archived; normalizes `tags`)
  - `update_equipment(db, equipment, *, payload, actor_id) -> Equipment` (audit diff; normalizes `tags`; permission check happens in endpoint before calling)
  - `archive_equipment(db, equipment, *, actor_id) -> Equipment` (sets `archived_at`; audit)
- `tags.py`
  - `normalize_tag(raw: str) -> str` — trim, lowercase, collapse whitespace to `-`, strip disallowed chars to `-`, truncate to 40 chars.
  - `normalize_tags(raw: list[str]) -> list[str]` — apply `normalize_tag`, dedupe, cap at 20.
  - `list_distinct_tags(db, org_id) -> list[str]` — `SELECT DISTINCT unnest(tags)` from non-archived equipment, sorted alpha.
- `attachments.py`
  - `add_attachment(db, equipment, file, *, actor_id) -> EquipmentAttachment` (uses `FileStorageService.store_file(base_dir="equipment", org_id=..., allowed_types=ALLOWED_MIMES, max_size_bytes=25*1024*1024)`)
  - `remove_attachment(db, attachment, *, actor_id)`

### Endpoints

Two new router files mounted in `api/router.py`:

`app/api/endpoints/sites.py` (prefix `/sites`):

```
GET    /sites                          ?include_archived=  any org member
POST   /sites                          SITE_MANAGER ∨ ADMIN
GET    /sites/{id}                     any org member
PATCH  /sites/{id}                     SITE_MANAGER ∨ ADMIN
DELETE /sites/{id}?move_to={site_id}   SITE_MANAGER ∨ ADMIN (forced move-to)
```

`app/api/endpoints/equipment.py` (prefix `/equipment`, replaces the existing endpoints in `iam.py`):

```
GET    /equipment                      ?site_id=&status=&q=&tag=&include_archived=  any org member
POST   /equipment                      any org member
GET    /equipment/tags                                                              any org member
GET    /equipment/{id}                                                              any org member
PATCH  /equipment/{id}                 any org member (field-level gate inside)
DELETE /equipment/{id}                 SITE_MANAGER ∨ ADMIN (soft archive)

GET    /equipment/{id}/attachments                                                  any org member
POST   /equipment/{id}/attachments     multipart                                    SITE_MANAGER ∨ ADMIN
DELETE /equipment/attachments/{att_id}                                              SITE_MANAGER ∨ ADMIN
```

Org scoping uses `user.selected_org_id` (existing pattern). The previous URLs at `/iam/organizations/{org_id}/equipment` and `/iam/equipment/{id}` are **deleted** along with the helper code in `iam.py`. Frontend callers migrate to `/equipment`.

All mutating endpoints emit `log_audit(db, actor_id=user.id, action='CREATE'|'UPDATE'|'ARCHIVE', entity_type='site'|'equipment'|'equipment_attachment', entity_id=..., changes={...})`.

### Org registration hook

In `POST /organizations` (`app/api/endpoints/iam.py`), after the initial `OrganizationMember` is flushed, call `ensure_default_site(db, org.id, actor_id=user.id)`. The Default Site is inserted with `name="Default Site"` and a `description` explaining its purpose; `created_by_id` is the registering user.

### Migration

Single Alembic revision `add_sites_and_extend_equipment`:

1. Create `sites` table with indexes.
2. Create `equipment_attachments` table.
3. Add new `equipment` columns (all nullable initially).
4. **Data migration (raw SQL):**
   - For each existing org without a Default Site, insert one with `name='Default Site'`, NULL `created_by_id`.
   - `UPDATE equipment SET site_id = sites.id FROM sites WHERE sites.organization_id = equipment.organization_id AND sites.name = 'Default Site' AND equipment.site_id IS NULL`.
5. `ALTER COLUMN equipment.site_id SET NOT NULL`.
6. `ALTER COLUMN equipment.status SET DEFAULT 'ACTIVE'` (and explicit `UPDATE equipment SET status = 'ACTIVE' WHERE status IS NULL`).
7. Update the `OrganizationMember` CHECK constraint to include `'SITE_MANAGER'`.

`equipment.tags` is created with `server_default ARRAY[]::varchar[]` so legacy rows populate automatically.

### Frontend

#### Schemas (`lib/schemas/`)

- New file `sites.ts`:
  - `SiteSchema` (id, organization_id, name, description, archived_at, created_at, updated_at)
  - `SiteCreateSchema`, `SiteUpdateSchema`, `SiteListSchema`
- Extend existing `science.ts::EquipmentSchema` with: `site_id`, `manufacturer`, `model`, `serial_number`, `status`, `install_date`, `last_calibration_date`, `next_calibration_due`, `room`, `tags`, `archived_at`, `created_by_id`. Add `EquipmentStatusSchema = z.enum(['ACTIVE', 'MAINTENANCE', 'RETIRED'])`, `EquipmentCreateSchema`, `EquipmentUpdateSchema`, `EquipmentListSchema`, `EquipmentAttachmentSchema`.

#### Routes

New route group `frontend/src/routes/organization/`:

- `+layout.svelte` — Organization shell (sidebar nav with Sites tab; future: Facility, Locations submenu)
- `sites/+page.svelte` — list view: site list + selected-site equipment table
- `sites/+page.ts` — load sites + equipment

Layout: a `Tabs` or left-rail layout with the Sites list as primary navigation. Selecting a Site filters the equipment table to that Site's equipment. An "All Sites" pseudo-entry shows the entire org's equipment.

#### Components (new `lib/components/sites/` bucket)

| Component | Purpose |
|-----------|---------|
| `SiteList.svelte` | Vertical list (not tree) of sites + active-selection highlight |
| `SiteFormDialog.svelte` | Add/edit Site (name, description) |
| `SitePicker.svelte` | `<Select>` dropdown used in Equipment form and Site archive dialog |
| `SiteArchiveDialog.svelte` | Confirm dialog with mandatory "Move equipment to:" SitePicker + warning summary ("12 active items will move to <X>") |
| `SiteEmptyState.svelte` | First-run prompt for empty-list state |

#### Components (new `lib/components/equipment/` bucket)

| Component | Purpose |
|-----------|---------|
| `EquipmentTable.svelte` | shadcn `Table`; columns: name, type, site, room, status, next calibration, actions. Restricted-field columns visible to all; edit-button per row honors role |
| `EquipmentFilterBar.svelte` | Status select, search input, tag combobox, include-archived toggle |
| `EquipmentFormDialog.svelte` | Add/edit form. Restricted inputs disabled-with-tooltip when user lacks SITE_MANAGER/ADMIN. Embedded `SitePicker` (required), `TagsInput` (type-ahead from `/equipment/tags`) |
| `TagsInput.svelte` | Combobox: type-ahead from `/equipment/tags`, free-create allowed, server normalizes |
| `EquipmentAttachmentsList.svelte` | List, upload, delete (upload/delete hidden when not SITE_MANAGER/ADMIN) |
| `EquipmentEmptyState.svelte` | First-run prompt |

#### Existing component touch-ups

- `MemberRolesPicker.svelte`: add `SITE_MANAGER` chip with description "Manages facility sites and equipment calibration records."
- `EquipmentPickerModal.svelte`: inline-create form gains a required `SitePicker` (defaults to Default Site or last-used). The free-text "location" input stays (it's still the on-bench spot description). Site name shown alongside the existing 📍 chip. Inline-create remains available to **any member** (no role gate, per (8)).
- `RunEditorModal.svelte`, `RunCreatorWizardModal.svelte`, `protocols/[id]/+page.svelte`: update URLs `/iam/organizations/{org_id}/equipment` → `/equipment` and add `site_id` to inline-create payloads.

#### Permission affordances (T2 preflight)

Auth store exposes `currentOrgRoles: string[]`. New derived:

```ts
export const canManageEquipmentLifecycle = $derived(
    currentOrgRoles?.some((r) => r === 'ADMIN' || r === 'SITE_MANAGER') ?? false
);
```

- Restricted fields in `EquipmentFormDialog` are disabled with tooltip when `false`.
- Archive button on rows hidden when `false`.
- Attachment upload/delete hidden when `false`.
- Backend re-validates (belt-and-suspenders); `EQUIPMENT_FIELD_RESTRICTED` errors are toasted with the offending fields enumerated.

## Testing

### Backend (TDD per CLAUDE.md, target >80% on new code)

Unit (`tests/unit/`):
- `test_sites_crud.py` — create, update, archive (with move-to), Default Site is non-archivable, name conflict, cross-org parent rejection.
- `test_sites_defaults.py` — `ensure_default_site` idempotency.
- `test_equipment_registry.py` — list filters (site, status, search, tag, include_archived), create requires site_id, archive sets archived_at, audit emission.
- `test_equipment_tags.py` — `normalize_tag`, `normalize_tags` (dedupe, cap-at-20, strip disallowed chars), `list_distinct_tags`.
- `test_equipment_attachments.py` — add/remove, FileStorageService integration.

Integration (`tests/integration/`):
- `test_sites_api.py` — full CRUD via HTTP; role gates (MEMBER reads OK, MEMBER writes 403, SITE_MANAGER writes OK, ADMIN writes OK); archive without `move_to` returns `SITE_ARCHIVE_NEEDS_MOVE_TO`; archive of Default Site returns `SITE_ARCHIVE_DEFAULT_FORBIDDEN`.
- `test_equipment_api.py` — full CRUD; field-level permission (MEMBER touching restricted field returns `EQUIPMENT_FIELD_RESTRICTED` with the field list; SITE_MANAGER touching same field returns 200); `?site_id=` filter; multipart attachment upload with MIME/size enforcement; OrgRole CHECK constraint accepts `SITE_MANAGER`.
- `test_org_registration_default_site.py` — registering a new org auto-creates the Default Site; user is admin of the new org; default site is renamable but archive endpoint returns `SITE_ARCHIVE_DEFAULT_FORBIDDEN`.
- `test_migration_backfill.py` — fixture pre-populates legacy equipment rows; after upgrade, every row has `site_id` pointing at its org's Default Site, and the column is `NOT NULL`.

### Frontend (Vitest)

- `EquipmentTable.test.ts` — renders rows, sort, restricted actions hidden when no write role.
- `EquipmentFormDialog.test.ts` — restricted inputs disabled for MEMBER, enabled for SITE_MANAGER; site_id required; edit pre-fill; submit payload omits unchanged fields.
- `EquipmentFilterBar.test.ts` — filter callbacks (status, search, tag, include_archived).
- `TagsInput.test.ts` — type-ahead suggestions from API, free-create, normalization preview.
- `SiteList.test.ts` — selection, archived sites hidden by default, archive option hidden on Default Site.
- `SiteArchiveDialog.test.ts` — refuses submit without move-to selection; SitePicker excludes the site being archived.
- `SitePicker.test.ts` — sorts, defaults to Default Site when no selection.

### Browser verification (`qa-verify` after dev server)

- Log in as ADMIN. Visit `/organization/sites`. Add a Site, edit it, attempt to archive the Default Site (blocked), archive the new Site (forced move-to dialog).
- Add equipment under the new Site. Confirm tags type-ahead. Upload a PDF attachment, attempt a .exe (rejected).
- Switch to a non-admin MEMBER. Confirm:
  - Read-only Sites UI (no Add/Edit/Archive buttons).
  - Can create equipment.
  - Can edit name/equipment_type/room/location/description/tags.
  - Calibration/serial/status fields disabled with tooltip.
  - Archive equipment hidden.
- Grant the MEMBER `SITE_MANAGER` via `/settings?tab=organization`. Confirm restricted fields enable.
- Inside protocol editor, open `EquipmentPickerModal`, run inline-create with the new SitePicker. Confirm equipment shows under the selected Site in `/organization/sites`.

## Rollout

Single PR. Migration is atomic. No feature flag — the new `/organization/sites` route is additive; the old `/iam/.../equipment` endpoints are deleted in the same PR with frontend callers migrated together.

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Existing Equipment callers break when `/iam/.../equipment` is removed | Migrate the 3 frontend files in the same PR; integration test hits `/equipment`. |
| Migration backfill skips an org with zero equipment but no Default Site exists | `ensure_default_site` runs for every org regardless of equipment count. |
| `SITE_MANAGER` not in `_RANK` breaks `require_org_role` callers | `require_org_role` is hierarchy-only and is not used for equipment/sites. New `require_any_org_role` handles the additive case. |
| User archives the only non-Default Site, leaving Default Site as the only target | Allowed; equipment moves to Default Site. Acceptable end state. |
| Tag normalization deletes a user's intended tag formatting | Normalization preview in `TagsInput` UI shows what the server will store (e.g. user types `Cell Culture` → preview `cell-culture`) so it's not a surprise. |
| `member_has_any_role` check duplicated between dep and field-level gate inside handler | Extract `member_has_any_role(member, roles)` helper in `services/iam/membership.py`; both call sites use it. |

## Open questions

None. All defaults from the brainstorming + grill are applied.
