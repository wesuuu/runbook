# F-0075 — Unit Operation Library Abstraction

**Date:** 2026-04-27
**Scope:** Backend + Frontend
**Effort:** L+ (~8-12h, two phases)
**Status:** Approved — moving to implementation plan

## Phasing

- **Phase 1 (Backend):** library JSON catalog, registry service, schema migration, endpoint rewrites, seed updates, backfill script, tests. Frontend response shape gains `library_slug`.
- **Phase 2 (Frontend):** protocol editor sidebar restructured to group ops by library → category → op, with custom org/project ops under a "Custom" group.

Phase 2 is self-contained and depends only on Phase 1's response shape change.

## Goal

Replace today's flat list of 16 globally-scoped unit operations with a JSON-defined catalog system. Built-in libraries live as versioned JSON in the repo. The DB holds three things: org subscriptions to libraries, per-org overrides of library ops, and org/project custom ops. `GET /science/unit-ops` returns the union for the requesting org's context.

## Why

- Hardcoding 16 cell-biology ops as "global" rows locks the product into one domain.
- Adding a new domain (small molecule, analytical chem, molecular bio) should be a code-only change — no migration, no DB seeding.
- Orgs need to control which catalogs they work from. Subscriptions are the abstraction. Frontend UX for managing them is F-0062's problem; this task only delivers the backend.

## Library Inventory

This task ships **one** library: `core`. It contains 12 domain-agnostic operations. The 16 existing seed ops are deleted; their content does not need to be preserved (per Q&A — dev DBs reset).

Future domain libraries (e.g., `cell_biology`, `analytical_chemistry`, `small_molecule_synthesis`) are added by dropping a new JSON file under `backend/app/data/unit_op_libraries/`. They are not part of this task.

### `core` — 12 ops

| Slug | Name | Category | Notes |
|------|------|----------|-------|
| `solution_preparation` | Solution Preparation | Preparation | Generalized from "Buffer Preparation". Buffer, reagent stock, mobile phase — same op. Keep the rich param schema from today's Buffer Preparation. |
| `weigh_solid` | Weigh Solid | Preparation | New. 3 params: `material`, `target_mass_g`, `balance_id`. |
| `dispense_liquid` | Dispense Liquid | Preparation | New. 3 params: `liquid`, `volume_ml`, `instrument`. |
| `aliquot_transfer` | Aliquot / Transfer | Preparation | New. 3 params: `source_vessel`, `destination_vessel`, `volume_ml`. |
| `mixing` | Mixing | Process | Keep current 3 params: `speed_rpm`, `duration_min`, `temperature_C`. |
| `ph_adjustment` | pH Adjustment | Process | Keep current 2 params: `target_pH`, `acid_or_base`. |
| `centrifugation` | Centrifugation | Process | Keep current 3 params: `rcf_g`, `duration_min`, `temperature_C`. |
| `filtration` | Filtration | Process | Keep current 3 params: `filter_size_um`, `filter_type`, `volume_L`. |
| `temperature_hold` | Temperature Hold | Process | New. 3 params: `temperature_C`, `duration_min`, `vessel`. (Distinct from cell-culture incubation, which is bio-specific and not in core.) |
| `sample_collection` | Sample Collection | Analytics | Keep current 3 params: `volume_mL`, `container_type`, `storage_temp_C`. |
| `visual_inspection` | Visual Inspection | QC | Keep current 2 params: `inspection_type`, `acceptance_criteria`. |
| `storage` | Storage | Logistics | New. 3 params: `material`, `storage_temp_C`, `container`. |

Library JSON has `is_default: true`, so every new org auto-subscribes.

## JSON Schema (Library File Format)

`backend/app/data/unit_op_libraries/core.json`:

```json
{
  "slug": "core",
  "name": "Core",
  "domain": "general",
  "description": "Cross-domain unit operations applicable to any wet lab.",
  "is_default": true,
  "version": "1.0.0",
  "unit_ops": [
    {
      "slug": "solution_preparation",
      "name": "Solution Preparation",
      "category": "Preparation",
      "description": "...",
      "param_schema": { "type": "object", "properties": { ... } },
      "result_schema": {}
    },
    ...
  ]
}
```

Validated on load with Pydantic models — any malformed library file raises at startup so the deployment fails fast.

## Database Changes

### New table: `unit_op_library_subscriptions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | UUIDMixin |
| `organization_id` | UUID FK → `organizations.id` | NOT NULL, ondelete CASCADE |
| `library_slug` | String | NOT NULL |
| `subscribed_at` | timestamptz | server_default `now()` |
| `created_at`, `updated_at` | timestamptz | TimestampMixin |

Constraints:
- `UniqueConstraint(organization_id, library_slug)` — an org subscribes once.
- No FK on `library_slug` — libraries live in JSON, not DB.

### `unit_op_definitions` — new columns

| Column | Type | Purpose |
|--------|------|---------|
| `source_library_slug` | String, nullable | Set when this row overrides a JSON op. |
| `source_op_slug` | String, nullable | Slug of the JSON op being overridden. |

New CHECK constraint: `(source_library_slug IS NULL AND source_op_slug IS NULL) OR (source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)`.

When override fields are set, the row's `id` equals the synthetic UUID of the JSON op so existing graph references continue to resolve.

### Existing scope check stays

`(project_id IS NULL OR organization_id IS NOT NULL)` — unchanged. Override rows always have `organization_id` set.

## LibraryRegistry Service

Module: `backend/app/services/science/library_registry.py`.

### Source abstraction

Libraries can come from multiple sources. Today only one source ships (bundled JSON in the repo); future enterprise / on-prem deployments may add a remote-catalog source pulling from a hosted store. The registry is source-agnostic.

```python
class LibrarySource(Protocol):
    async def load(self) -> list[Library]:
        """Return all libraries this source provides."""
        ...

class BundledJSONSource:
    """Reads *.json from app/data/unit_op_libraries/. Validates with Pydantic."""
    def __init__(self, directory: Path): ...
    async def load(self) -> list[Library]: ...

# Future, NOT shipped now:
# class RemoteCatalogSource:
#     def __init__(self, base_url: str, api_key: str | None = None): ...
#     async def load(self) -> list[Library]: ...
```

### Cache

State: a module-level `dict[str, Library]` populated by reading every registered `LibrarySource` and merging the results. Last-source-wins on slug collision (so a future remote source could shadow a bundled one — useful for staged rollouts of library updates).

After the initial load, the cache is read-only until `reload_libraries()` is called explicitly. That keeps the request-time path lock-free and zero-overhead in production.

### API

```python
def register_source(source: LibrarySource) -> None:
    """Register a source. Called during app startup, before reload_libraries()."""

async def reload_libraries() -> None:
    """Re-read every registered source and atomically replace the cache.
    Called from FastAPI lifespan startup, the admin reload endpoint, and tests.
    Atomic swap: builds the new dict, then assigns. Raises on validation failure
    without disturbing the existing cache."""

def list_libraries() -> list[Library]: ...
def get_library(slug: str) -> Library | None: ...
def get_op(library_slug: str, op_slug: str) -> UnitOp | None: ...
def synthetic_uuid(library_slug: str, op_slug: str) -> uuid.UUID:
    """uuid5(NAMESPACE, f'{library_slug}/{op_slug}')."""

def default_library_slugs() -> list[str]:
    """All libraries with is_default=true."""

async def subscribe_default_libraries(db: AsyncSession, org_id: UUID) -> None:
    """Insert subscription rows for every default library. Idempotent
    (skips if a subscription already exists)."""
```

### Invalidation strategy

| Trigger | Mechanism |
|---|---|
| Process startup (cloud + on-prem) | `reload_libraries()` from lifespan startup |
| New JSON shipped via deploy | Process restart on deploy → lifespan reload |
| On-prem operator drops a JSON file at runtime | `POST /admin/libraries/reload` (admin endpoint) |
| Dev edits a JSON file | uvicorn reload watches `*.json` (config-only) |

Explicitly **not** in this task: periodic auto-refresh, file-system watchers, mtime/checksum probing per request. The reload endpoint is the deliberate trigger. Auto-refresh becomes meaningful only when a `RemoteCatalogSource` ships and is added in the same task as that source.

### Other

`NAMESPACE` = a fixed `uuid.UUID` constant defined in this module — pinned in code so synthetic UUIDs are stable across deployments and across sources.

Pydantic models (`Library`, `UnitOp`) live in the same module since they're library-format-specific.

## API Changes

### `GET /science/unit-ops` — union assembly

Pseudocode:

```python
async def list_unit_ops(project_id, user, db):
    org_id = user.selected_org_id
    result_by_id: dict[UUID, UnitOpResponse] = {}

    # 1. JSON ops from subscribed libraries
    subscribed = await fetch_subscribed_library_slugs(db, org_id)
    for slug in subscribed:
        lib = library_registry.get_library(slug)
        for op in lib.unit_ops:
            synth_id = library_registry.synthetic_uuid(slug, op.slug)
            result_by_id[synth_id] = build_response(op, synth_id, org_id=None)

    # 2. DB rows for this org
    db_rows = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.organization_id == org_id)
    )
    for row in db_rows.scalars():
        if row.source_library_slug is not None:
            # Override: replace the JSON entry with the same synthetic id
            result_by_id[row.id] = response_from_row(row)
        elif row.project_id is None:
            # Custom org-scoped op
            result_by_id[row.id] = response_from_row(row)

    # 3. Project-scoped ops if requested
    if project_id is not None and (await check_permission(...)):
        proj_rows = await db.execute(
            select(UnitOpDefinition).where(UnitOpDefinition.project_id == project_id)
        )
        for row in proj_rows.scalars():
            result_by_id[row.id] = response_from_row(row)

    return list(result_by_id.values())
```

Response shape gains one new field: `library_slug` (Optional[str]). Set for JSON ops and override rows; null for custom org/project ops. The frontend uses this to group ops by library. JSON ops materialize with `organization_id=None`, `project_id=None`, `scope="global"` (computed). Override rows have `organization_id` set, `scope="organization"`.

### `PUT /science/unit-ops/{id}` — copy-on-write

```python
async def update_unit_op(unit_op_id, update_data, user, db):
    org_id = user.selected_org_id

    # Try DB first
    row = await db.get(UnitOpDefinition, unit_op_id)

    if row is None:
        # Maybe it's a JSON op the org is subscribed to
        op_match = find_subscribed_json_op(db, org_id, unit_op_id)
        if op_match is None:
            raise 404
        # Copy-on-write: insert override row with id = unit_op_id
        await require_org_admin(db, user.id, org_id)
        row = UnitOpDefinition(
            id=unit_op_id,
            name=op_match.name,
            category=op_match.category,
            description=op_match.description,
            param_schema=op_match.param_schema,
            result_schema=op_match.result_schema,
            organization_id=org_id,
            project_id=None,
            source_library_slug=op_match.library_slug,
            source_op_slug=op_match.op_slug,
        )
        # Apply update_data on top
        for k, v in update_data.model_dump(exclude_unset=True).items():
            setattr(row, k, v)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    # Existing flow — global rows error path no longer reachable since they're deleted
    # (override rows match the org-admin path; project rows match the project-edit path)
    ...
```

The "global rows are read-only" branch is removed (no global rows survive the migration).

### `POST /science/unit-ops` — unchanged

Custom org/project ops keep `source_library_slug = NULL`. Existing logic stands.

### `POST /admin/libraries/reload` — new

Admin-gated endpoint that re-runs every registered `LibrarySource` and atomically swaps the cache. Use case: on-prem operator drops a new/updated JSON file into the libraries directory and wants the running app to pick it up without restarting; cloud ops gets the same affordance.

```python
@router.post("/admin/libraries/reload", status_code=200)
async def reload_libraries_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(400, "No organization selected")
    await _require_org_admin(db, user.id, org_id)
    await library_registry.reload_libraries()
    return {
        "libraries": [
            {"slug": lib.slug, "name": lib.name, "version": lib.version,
             "op_count": len(lib.unit_ops)}
            for lib in library_registry.list_libraries()
        ],
    }
```

Notes:
- **Permission model**: gated on org admin of the caller's selected org. Acceptable for both cloud (where this is rarely used) and on-prem (where the admin is the customer's own admin). When/if multi-tenant cloud needs a stricter "platform admin only" gate, that's a future tightening, not a blocker today.
- **Failure semantics**: if any source's `load()` raises, the endpoint returns 5xx and the cache is left untouched (atomic swap means we don't half-replace).
- **Audit**: log via existing audit pattern with `entity_type="library_reload"`.
- **Where it's mounted**: `backend/app/api/endpoints/admin.py` (new file) or appended to an existing admin/system endpoint module if one exists. Decide during implementation; default to a new `admin.py`.

## Org Creation Hook

Two call sites currently create organizations:
- `backend/app/api/endpoints/auth.py:126` (registration — first signup)
- `backend/app/api/endpoints/iam.py:89` (create_organization — additional org by existing user)

Both call `library_registry.subscribe_default_libraries(db, org.id)` after `db.flush()` and before commit. Going forward, every new org auto-subscribes to whichever libraries are flagged `is_default: true`.

## Backfill Script

`backend/scripts/subscribe_orgs_to_default_libraries.py` — one-shot CLI for retroactively enrolling existing orgs. Use case: a future PR adds a second `is_default: true` library; the migration ships only schema changes, and this script enrolls every existing org.

Behavior:

```python
# Iterates every org, calls library_registry.subscribe_default_libraries(db, org.id).
# subscribe_default_libraries is idempotent (skips orgs already subscribed),
# so the script is safe to re-run after future default additions.
```

The migration delivered with this task also subscribes existing orgs to `core` inline (so we don't ship the script as a hard requirement to run). The script exists for *future* default additions where we don't want to ship a new migration.

## Seed Script

`backend/app/db/seed.py`:

- Delete `seed_unit_ops` function and its 16-op inline list.
- Add `seed_library_subscriptions(db)`: subscribes the dev seed org to all `is_default=true` libraries via `library_registry.subscribe_default_libraries`.
- Update the orchestration call site to use the new function.

## Alembic Migration

`backend/alembic/versions/<rev>_unit_op_library_abstraction.py` (rev id auto-generated):

```python
def upgrade():
    op.create_table(
        "unit_op_library_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("library_slug", sa.String(), nullable=False),
        sa.Column("subscribed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "library_slug",
                            name="uq_unit_op_lib_sub"),
    )

    op.add_column("unit_op_definitions",
                  sa.Column("source_library_slug", sa.String(), nullable=True))
    op.add_column("unit_op_definitions",
                  sa.Column("source_op_slug", sa.String(), nullable=True))

    op.create_check_constraint(
        "ck_unit_op_source_both_or_neither",
        "unit_op_definitions",
        "(source_library_slug IS NULL AND source_op_slug IS NULL) OR "
        "(source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)",
    )

    # Drop existing global rows. Protocol graphs that reference them get
    # orphan UUIDs in JSONB; that is acceptable per task spec (dev only).
    op.execute(
        "DELETE FROM unit_op_definitions "
        "WHERE organization_id IS NULL AND project_id IS NULL"
    )

    # Auto-subscribe every existing org to default libraries.
    # Hardcoded 'core' here so the migration is self-contained;
    # Python registry not yet importable from a migration cleanly.
    op.execute(
        "INSERT INTO unit_op_library_subscriptions "
        "(id, organization_id, library_slug, subscribed_at, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, 'core', now(), now(), now() FROM organizations"
    )


def downgrade():
    op.drop_constraint("ck_unit_op_source_both_or_neither", "unit_op_definitions")
    op.drop_column("unit_op_definitions", "source_op_slug")
    op.drop_column("unit_op_definitions", "source_library_slug")
    op.drop_table("unit_op_library_subscriptions")
```

The downgrade does not restore the deleted global rows. Acceptable for a one-way migration in a project where dev DBs reset routinely.

## Testing Plan

New file `backend/tests/integration/test_unit_op_libraries.py`:

1. **Library JSON parse**: every shipped JSON file passes Pydantic validation.
2. **Synthetic UUID determinism**: `synthetic_uuid("core", "mixing")` returns the same UUID across calls.
3. **New org auto-subscribes** to default libraries (registration path + `POST /organizations` path).
4. **`GET` returns subscribed JSON ops**: subscribe an org to `core`, GET, expect all 12 ops with synthetic UUIDs.
5. **`GET` excludes unsubscribed library ops**: org with no subscription gets empty list (plus its own custom ops).
6. **`GET` returns custom org ops** alongside JSON ops.
7. **`GET` returns project ops** when `project_id` provided + permission ok.
8. **Override copy-on-write**: PUT on a JSON op id with new name → new DB row exists with `source_library_slug="core"`, GET returns the override (not the original).
9. **Override second update**: PUT again on the same id → updates the existing row (no second insert).
10. **Override scoped to one org**: org A's override does not affect org B's GET response.
11. **PUT on unknown UUID** (not in DB, not a synthetic of any subscribed library): 404.
12. **Source abstraction**: registering an in-memory fake source loads its libraries; cache contents reflect last-source-wins on slug collision.
13. **`reload_libraries()` is atomic**: a source that raises during reload leaves the previous cache intact.
14. **`POST /admin/libraries/reload` as org admin**: 200, response lists all libraries with op counts; cache reflects any new ops.
15. **`POST /admin/libraries/reload` as non-admin**: 403.

Existing `test_unit_ops_scoping.py` updates:

- `global_unit_op` fixture replaced with `core_library_op` — picks one of the 12 synthetic UUIDs and asserts it's in the response.
- `test_update_global_op_forbidden` reframed as `test_put_on_library_op_creates_override` — expects 200 and an override row.
- All other org/project tests untouched (logic for those scopes is unchanged).

## Phase 2 — Frontend (Protocol Editor Sidebar)

### Goal

Restructure the unit-ops list in the protocol editor sidebar to surface library context. Today the sidebar groups ops by category only. With multiple libraries shipping over time, users need to see which library an op comes from, and the layout has to keep working as the catalog grows.

### Chosen pattern: 3-level accordion (Library → Category → Op)

```
[ Search ops... ]

▼ PROCESS
  ▶ Process Start

▼ Core
  ▼ Preparation (4)
    Solution Preparation     ●
    Weigh Solid              ●
    Dispense Liquid          ●
    Aliquot / Transfer       ●
  ▼ Process (5)
    Mixing                   ●
    pH Adjustment            ●
    ...
  ▶ Analytics (1)
  ▶ QC (1)
  ▶ Logistics (1)

▶ Custom (My Org)         ← only shown when org/project custom ops exist
```

Both library and category levels are independently collapsible. Default state on first load: all expanded. Collapse state is local to the component instance (no persistence in this task).

Ops keep their existing visual treatment (icon by category, scope dot, drag handle).

### Data shape

`UnitOpDefinitionResponse` from the backend now carries `library_slug`:
- Library ops: `library_slug = "core"` etc.
- Override rows: `library_slug = "core"` (still grouped under the library, since they override a library op).
- Custom org ops: `library_slug = null`, `organization_id` set.
- Custom project ops: `library_slug = null`, `project_id` set.

The frontend Zod schema in `lib/schemas/science.ts` adds the field as `library_slug: z.string().nullable().optional()`.

### Sidebar grouping logic

In `ProtocolSidebar.svelte`, replace the current `categories` derived map (flat: category → ops) with a two-level structure:

```ts
type LibraryGroup = {
  slug: string | "_custom";
  displayName: string;     // "Core", "Cell Biology", "Custom (My Org)"
  categories: Map<string, UnitOp[]>;  // existing per-category grouping inside
};

const groups: LibraryGroup[] = $derived(...);
```

Library display names come from a small lookup (one-time hardcoded map in the frontend, or fetched once from a future endpoint — fetched is YAGNI for now). Initial map:

```ts
const LIBRARY_DISPLAY_NAMES: Record<string, string> = {
  core: "Core",
};
// Fallback: title-case the slug.
```

Custom ops with `library_slug=null` collapse into a single virtual `"_custom"` group titled "Custom (My Org)". Project ops also fall into this group when `project_id` matches the current protocol's project — they don't need a separate visual section per the existing behavior.

### Search behavior

Search filters across all libraries and categories. While a query is active:

- **Match fields:** op `name`, `category`, library `display_name`, library `slug`. Op `description` is excluded (too long, creates noisy matches). Substring match, case-insensitive (same as today).
- **Auto-expand:** any library and category containing at least one match auto-expands. The user's manual collapse state is preserved separately and restored when the query is cleared.
- **Hide empties:** libraries and categories with zero matches are hidden, not shown collapsed-empty (consistent with current category-empty behavior).
- **Highlight:** matched substring is wrapped in `<mark>` in the op name (and library/category headers when the match is on those fields). Cheap, accessible, no extra deps.

Implementation sketch:

```ts
let searchQuery = $state('');
let manualCollapse = $state<Set<string>>(new Set());  // user-toggled, e.g. "lib:core" or "cat:core/Process"

const effectiveCollapse = $derived(
  searchQuery.trim() ? new Set<string>() : manualCollapse  // search trumps manual
);

const groups = $derived.by(() => {
  const q = searchQuery.trim().toLowerCase();
  // Build the Library → Category → Op tree, dropping rows that don't match q.
  // Drop empty categories. Drop empty libraries.
});
```

When the query is empty the structure rebuilds against the full op list and `effectiveCollapse` falls back to `manualCollapse`.

No changes to `UnitOpNode.svelte`, `Inspector.svelte`, drag-drop, or any other surface — the existing op object shape stays the same; only the sidebar's grouping logic changes.

### Frontend Tests

- Existing sidebar Vitest tests (if any) updated.
- Manual browser verification (qa-verify) covers: library expand/collapse, drag op into canvas, search filters across libraries, custom ops appear in Custom group, override op appears under its library.

### Org settings — Reload Libraries button

In `frontend/src/routes/settings/+page.svelte`, on the **Organization** tab, add a small administrative section:

```
Unit Operation Libraries
────────────────────────
Refresh the catalog of system unit operations after a deployment
or library file update.

[ Reload Libraries ]      Last reloaded: 2 minutes ago
```

Behavior:
- Visible to org admins only (gate via existing role check that already lives on this tab).
- On click: `POST /admin/libraries/reload`. Show inline spinner; on success, toast "Libraries reloaded — N libraries, M ops". On failure, toast the error.
- "Last reloaded" timestamp is local UI state (when the user last clicked); doesn't need backend persistence in this task.

### Files Touched (Phase 2)

| File | Action |
|------|--------|
| `frontend/src/lib/schemas/science.ts` | add `library_slug` field |
| `frontend/src/lib/components/protocol/ProtocolSidebar.svelte` | restructure grouping into 3-level accordion + auto-expand search |
| `frontend/src/routes/settings/+page.svelte` | add "Reload Libraries" admin section to Organization tab |

### YAGNI for Phase 2

- No persisted collapse state.
- No library-level search filter (search hits everything).
- No library badges on op tiles.
- No subscription management UI.
- No reordering libraries.
- No persisted "last reloaded" timestamp on the backend.

## File Inventory (consolidated)

### Phase 1 — Backend

| File | Action |
|------|--------|
| `backend/app/data/unit_op_libraries/core.json` | new |
| `backend/app/services/science/__init__.py` | new |
| `backend/app/services/science/library_registry.py` | new |
| `backend/app/models/science.py` | add `library_slug` + `source_op_slug` columns + `UnitOpLibrarySubscription` model |
| `backend/app/schemas/science.py` | add `library_slug` to `UnitOpDefinitionResponse` |
| `backend/app/api/endpoints/unit_ops.py` | rewrite list + put |
| `backend/app/api/endpoints/admin.py` | new (POST /admin/libraries/reload) |
| `backend/app/api/router.py` | mount admin router |
| `backend/app/api/endpoints/auth.py` | call subscribe_default_libraries on register |
| `backend/app/api/endpoints/iam.py` | call subscribe_default_libraries on create_organization |
| `backend/app/db/seed.py` | drop seed_unit_ops, add seed_library_subscriptions |
| `backend/app/main.py` | call library_registry.load_libraries() in lifespan |
| `backend/alembic/versions/<rev>_unit_op_library_abstraction.py` | new |
| `backend/scripts/subscribe_orgs_to_default_libraries.py` | new (backfill CLI) |
| `backend/tests/integration/test_unit_op_libraries.py` | new |
| `backend/tests/integration/test_unit_ops_scoping.py` | update fixtures + 1 test |

### Phase 2 — Frontend

| File | Action |
|------|--------|
| `frontend/src/lib/schemas/science.ts` | add `library_slug` field |
| `frontend/src/lib/components/protocol/ProtocolSidebar.svelte` | restructure grouping into 3-level accordion + auto-expand search |
| `frontend/src/routes/settings/+page.svelte` | add "Reload Libraries" admin section to Organization tab |

## Out of Scope (YAGNI)

- Admin UI for subscriptions (F-0062).
- Library version negotiation / upgrade flow.
- Any second domain library (cell_biology, analytical_chemistry, etc.).
- Endpoint to list available libraries.
- `unit_op_definitions` cleanup of stale orphan-id references inside protocol graphs.

## Follow-up Tasks (Out of Scope)

- Library subscription management UI (covered by F-0062).
- Per-user persisted collapse state on the sidebar.
- Library badges / icons on op tiles for at-a-glance attribution.
