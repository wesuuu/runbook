# F-0088 Equipment Registry & First-Class Sites — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `Site` to a flat, org-scoped first-class entity; extend `Equipment` with regulated GLP fields (calibration, status, serial, tags, attachments, soft-delete); add the additive `SITE_MANAGER` org role **scoped per-site via a `site_manager_grants` table**; ship `/sites` and `/equipment` REST endpoints; build the management UI at `/organization/sites` including the 3-step archive-site wizard, the per-site Managers panel, and an inline site picker on the member-roles editor.

**Architecture:** Backend-first. New `sites`, `equipment_attachments`, and `site_manager_grants` tables; existing `equipment` table extended with `site_id NOT NULL` after a backfill migration that creates a "Default Site" per org (eagerly — incl. empty orgs). Three new module-style service packages (`services/sites/`, `services/equipment/`, plus `services/sites/grants.py`). Two new routers (`api/endpoints/sites.py`, `api/endpoints/equipment.py`); legacy `/iam/organizations/{org_id}/equipment` routes deleted. Frontend adds a new `/organization/sites` route group with shared `lib/components/sites/` + `lib/components/equipment/` buckets, a managers panel embedded in the master view, an inline site multi-select on `MemberRolesPicker`, and an `EquipmentPickerModal` touch-up with `localStorage` last-site preference. T2 validation tier: backend authoritative; frontend disables/strips restricted inputs.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 async · Alembic · Pydantic · Svelte 5 (runes) · TailwindCSS 4 · shadcn-svelte · pytest · Vitest

**Reference spec:** `docs/superpowers/specs/2026-05-18-f-0088-equipment-registry-and-sites-design.md`
**UI mockups:** `docs/superpowers/specs/mockups/f0088-equipment-and-sites.html` (six views: master, equipment detail, archive wizard, inline picker, **site managers panel**, **member roles inline picker**)

**Revision history:**
- **v2 (2026-05-18, post-grill):** SITE_MANAGER becomes a *capability flag + per-site grants* (new `site_manager_grants` table). Field-level PATCH gate switches from "touched" to "actually changed" (value-compare). POST `/equipment` soft-drops restricted fields when caller lacks the role+grant. `site_id` move gated separately with `SITE_MOVE_FORBIDDEN` (grants on BOTH source AND destination required). Site CRUD scope split: CREATE+ARCHIVE = ADMIN-only; RENAME = SITE_MANAGER-on-that-site + ADMIN. Default Site identified by a `sites.is_default` boolean column (renamable; bit persists). Migration creates Default Site for empty orgs too. Attachment writes blocked on archived equipment via `EQUIPMENT_ARCHIVED`. `EquipmentPickerModal` uses `localStorage` for last-used site. Audit log: primary entry on `site_manager_grant` + shadow on `site` for timeline completeness. Two new mockup views (Site Managers panel · Member roles inline picker).
- **v1 (2026-05-18):** Initial plan; org-wide SITE_MANAGER role bit.

**Worktree:** Per `implement-task`, create the worktree AFTER this plan is approved. Do not start a worktree to begin Phase 1; wait for user sign-off.

---

## File map

### Backend

| Path | Action | Purpose |
|---|---|---|
| `backend/app/models/iam.py` | modify | Add `OrgRole.SITE_MANAGER`; update `_ALLOWED_ORG_ROLES`; update `OrganizationMember` CHECK constraint string |
| `backend/app/schemas/iam.py` | modify | Add `SITE_MANAGER` to `_LEGACY_ROLE_RANK` at rank 2 |
| `backend/app/models/science.py` | modify | Add `Site` model (with `is_default` boolean); extend `Equipment` with new columns; add `EquipmentAttachment` model; add `EquipmentStatus` enum; add `SiteManagerGrant` model |
| `backend/app/schemas/sites.py` | create | `SiteResponse`, `SiteCreate`, `SiteUpdate`, `SiteArchiveRequest`, `SiteManagerGrantResponse`, `SiteManagerGrantCreate` |
| `backend/app/schemas/equipment.py` | create | `EquipmentResponse`, `EquipmentCreate`, `EquipmentUpdate`, `EquipmentAttachmentResponse`, status enum |
| `backend/alembic/versions/f0088_add_sites_and_extend_equipment.py` | create | Single atomic migration: create `sites` (incl. `is_default`), create `equipment_attachments`, create `site_manager_grants`, add `equipment` columns, eager-backfill Default Sites for **every** org, set NOT NULL, update CHECK constraint |
| `backend/app/core/deps.py` | modify | Add `require_any_org_role(roles)` factory + `require_admin_org_role` (alias for ADMIN-only convenience) |
| `backend/app/services/permissions/__init__.py` | create | Re-export |
| `backend/app/services/permissions/equipment.py` | create | `user_can_edit_restricted_equipment(db, user, eq)`, `user_can_move_equipment(db, user, eq, dest_site_id)`, `user_can_rename_site(db, user, site)` — single helper module every endpoint routes through |
| `backend/app/services/sites/__init__.py` | create | Re-exports |
| `backend/app/services/sites/defaults.py` | create | `DEFAULT_SITE_NAME`, `ensure_default_site`, `is_default_site` (reads `is_default` column) |
| `backend/app/services/sites/crud.py` | create | `list_sites`, `get_site`, `create_site`, `update_site`, `archive_site` |
| `backend/app/services/sites/grants.py` | create | `list_grants_for_site`, `list_managed_sites_for_user`, `grant_site_manager`, `revoke_site_manager`, `user_has_grant` |
| `backend/app/services/equipment/__init__.py` | create | Re-exports |
| `backend/app/services/equipment/tags.py` | create | `normalize_tag`, `normalize_tags`, `list_distinct_tags` |
| `backend/app/services/equipment/registry.py` | create | `list_equipment`, `get_equipment`, `create_equipment` (soft-drops restricted fields for non-managers), `update_equipment`, `archive_equipment`, `RESTRICTED_EQUIPMENT_FIELDS` |
| `backend/app/services/equipment/attachments.py` | create | `ALLOWED_MIMES`, `MAX_BYTES`, `add_attachment`, `remove_attachment` (raises `EQUIPMENT_ARCHIVED` when `eq.archived_at IS NOT NULL`) |
| `backend/app/api/endpoints/sites.py` | create | `/sites` router (incl. `/sites/{id}/managers`, `/users/{user_id}/managed-sites` subroutes) |
| `backend/app/api/endpoints/equipment.py` | create | `/equipment` router (replaces the old `iam.py` equipment routes); value-compare gate on PATCH; `SITE_MOVE_FORBIDDEN` branch |
| `backend/app/api/endpoints/iam.py` | modify | Delete equipment routes (lines 1005–1135 range); call `ensure_default_site` after org creation |
| `backend/app/api/router.py` | modify | Mount `sites` and `equipment` routers |
| `backend/tests/unit/test_site_model.py` | create | Model + name-conflict + `is_default` unit tests |
| `backend/tests/unit/test_sites_crud.py` | create | CRUD + archive (with overrides) + Default Site guard |
| `backend/tests/unit/test_sites_defaults.py` | create | `ensure_default_site` idempotency + `is_default_site` column-based |
| `backend/tests/unit/test_sites_grants.py` | create | Grant/revoke + role-bit coupling (last revoke clears bit) + audit shadow writes |
| `backend/tests/unit/test_permissions_equipment.py` | create | `user_can_edit_restricted_equipment`, `user_can_move_equipment`, `user_can_rename_site` |
| `backend/tests/unit/test_equipment_tags.py` | create | Tag normalization + listing |
| `backend/tests/unit/test_equipment_registry.py` | create | List filters, create (soft-drop restricted), update, archive, audit emission |
| `backend/tests/unit/test_equipment_attachments.py` | create | Add/remove, MIME/size enforcement, `EQUIPMENT_ARCHIVED` guard |
| `backend/tests/integration/test_sites_api.py` | create | HTTP CRUD + role gates + archive flow + grants subroutes |
| `backend/tests/integration/test_equipment_api.py` | create | HTTP CRUD + value-compare gate + `SITE_MOVE_FORBIDDEN` + tags + attachments |
| `backend/tests/integration/test_org_registration_default_site.py` | create | Default Site auto-create on org registration |
| `backend/tests/integration/test_migration_backfill.py` | create | Legacy equipment rows get backfilled to Default Site; empty orgs also get one |

### Frontend

| Path | Action | Purpose |
|---|---|---|
| `frontend/src/lib/schemas/sites.ts` | create | `SiteSchema`, `SiteListSchema`, create/update schemas |
| `frontend/src/lib/schemas/science.ts` | modify | Extend `EquipmentSchema`; add `EquipmentStatusSchema`, attachment + list schemas |
| `frontend/src/lib/schemas/index.ts` | modify | Re-export `sites.ts` |
| `frontend/src/lib/auth.svelte.ts` | modify | Track `managedSiteIds`; expose `isOrgAdmin` + `canManageSite(siteId)` accessors |
| `frontend/src/lib/permissions/equipment.ts` | create | `canManageEquipmentLifecycle({roles, managedSiteIds, siteId})`, `canMoveEquipment({…, fromSiteId, toSiteId})` — pure helpers consumed by auth + components |
| `frontend/src/lib/permissions/equipment.test.ts` | create | Vitest — role-bit + per-site grant matrix |
| `frontend/src/lib/components/sites/SitePicker.svelte` | create | `<Select>` of sites; reads/writes `localStorage['f0088:lastSiteId']` when used inline |
| `frontend/src/lib/components/sites/SiteList.svelte` | create | Left rail with active highlight |
| `frontend/src/lib/components/sites/SiteFormDialog.svelte` | create | Add/edit dialog |
| `frontend/src/lib/components/sites/SiteArchiveStepper.svelte` | create | Re-toned step pill chrome |
| `frontend/src/lib/components/sites/SiteArchiveWizardModal.svelte` | create | 3-step archive wizard |
| `frontend/src/lib/components/sites/SiteEmptyState.svelte` | create | First-run prompt |
| `frontend/src/lib/components/sites/SiteManagersPanel.svelte` | create | View 5 — embedded under equipment table on master view; lists grants; opens add-manager picker; ADMIN-only |
| `frontend/src/lib/components/sites/SiteManagerAddPicker.svelte` | create | Member picker popover (search + checkbox list) for granting SITE_MANAGER |
| `frontend/src/lib/components/sites/MemberSitesInlinePicker.svelte` | create | View 6 — inline site multi-select that drops under the SITE_MANAGER chip; consumed by `MemberRolesPicker` |
| `frontend/src/lib/components/equipment/TagsInput.svelte` | create | Type-ahead tags combobox |
| `frontend/src/lib/components/equipment/EquipmentFilterBar.svelte` | create | Search/status/tag/include-archived |
| `frontend/src/lib/components/equipment/EquipmentTable.svelte` | create | Equipment table |
| `frontend/src/lib/components/equipment/EquipmentFormDialog.svelte` | create | Add/edit dialog with field-level disabling |
| `frontend/src/lib/components/equipment/EquipmentAttachmentsList.svelte` | create | Upload/list/delete |
| `frontend/src/lib/components/equipment/EquipmentEmptyState.svelte` | create | First-run prompt |
| `frontend/src/routes/organization/+layout.svelte` | create | Organization shell |
| `frontend/src/routes/organization/sites/+page.svelte` | create | Sites & Equipment master view |
| `frontend/src/routes/organization/sites/+page.ts` | create | Loader |
| `frontend/src/lib/components/settings/MemberRolesPicker.svelte` | modify | Add `SITE_MANAGER` chip + render `MemberSitesInlinePicker` inline when ticked; validation: chip requires ≥1 site |
| `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` | modify | Add `SitePicker` to inline create form; strip restricted fields entirely; default site via `localStorage['f0088:lastSiteId']` (fall back to Default Site) |
| `frontend/src/lib/components/run/RunCreatorWizardModal.svelte` | modify | Migrate URLs `/iam/...` → `/equipment`; add `site_id` to inline-create payload |
| `frontend/src/lib/components/run/RunEditorModal.svelte` | modify | Same URL + payload migration |
| `frontend/src/routes/protocols/[id]/+page.svelte` | modify | Same URL + payload migration |
| `frontend/src/lib/components/sites/SitePicker.test.ts` | create | Vitest |
| `frontend/src/lib/components/sites/SiteList.test.ts` | create | Vitest |
| `frontend/src/lib/components/sites/SiteArchiveWizardModal.test.ts` | create | Vitest |
| `frontend/src/lib/components/sites/SiteManagersPanel.test.ts` | create | Vitest — grant/revoke happy path + ADMIN-only render |
| `frontend/src/lib/components/sites/MemberSitesInlinePicker.test.ts` | create | Vitest — validation: chip cannot save with 0 sites |
| `frontend/src/lib/components/equipment/TagsInput.test.ts` | create | Vitest |
| `frontend/src/lib/components/equipment/EquipmentTable.test.ts` | create | Vitest |
| `frontend/src/lib/components/equipment/EquipmentFormDialog.test.ts` | create | Vitest |
| `frontend/src/lib/components/equipment/EquipmentFilterBar.test.ts` | create | Vitest |

---

## Phase 1 — Foundation: role, models, migration

### Task 1: Add `SITE_MANAGER` to the `OrgRole` enum

**Files:**
- Modify: `backend/app/models/iam.py:36-43`
- Modify: `backend/app/schemas/iam.py:9-14`
- Test: `backend/tests/unit/test_org_roles.py` (extend existing file if present; otherwise create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_org_roles.py
from app.models.iam import OrgRole, _ALLOWED_ORG_ROLES
from app.schemas.iam import _LEGACY_ROLE_RANK


def test_site_manager_in_enum():
    assert OrgRole.SITE_MANAGER.value == "SITE_MANAGER"


def test_site_manager_allowed():
    assert "SITE_MANAGER" in _ALLOWED_ORG_ROLES


def test_site_manager_legacy_rank():
    assert _LEGACY_ROLE_RANK["SITE_MANAGER"] == 2
    # Same rank as PROTOCOL_APPROVER; ADMIN still highest.
    assert _LEGACY_ROLE_RANK["ADMIN"] > _LEGACY_ROLE_RANK["SITE_MANAGER"]
```

- [ ] **Step 2: Run test — expect FAIL**

`cd backend && pytest tests/unit/test_org_roles.py -v` → AttributeError / KeyError.

- [ ] **Step 3: Modify `OrgRole` and the allowed set**

In `backend/app/models/iam.py`, inside the `OrgRole` enum block:

```python
class OrgRole(str, Enum):
    ADMIN = "ADMIN"
    BILLING = "BILLING"
    MEMBER = "MEMBER"
    PROTOCOL_APPROVER = "PROTOCOL_APPROVER"
    SITE_MANAGER = "SITE_MANAGER"


_ALLOWED_ORG_ROLES = frozenset(r.value for r in OrgRole)
```

In `backend/app/schemas/iam.py`, extend `_LEGACY_ROLE_RANK`:

```python
_LEGACY_ROLE_RANK = {
    "ADMIN": 3,
    "BILLING": 2,
    "PROTOCOL_APPROVER": 2,
    "SITE_MANAGER": 2,
    "MEMBER": 1,
}
```

(Adjust to match the file's existing dict shape — keep the existing other values verbatim, only insert the new key.)

- [ ] **Step 4: Run test — expect PASS**

`cd backend && pytest tests/unit/test_org_roles.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/iam.py backend/app/schemas/iam.py backend/tests/unit/test_org_roles.py
git commit -m "feat(F-0088): add SITE_MANAGER to OrgRole enum"
```

---

### Task 2: Update `OrganizationMember` CHECK constraint string

**Files:**
- Modify: `backend/app/models/iam.py:222-225`

> The actual DB constraint is altered in the migration (Task 5). This task only updates the ORM-level `CheckConstraint` literal so the model declaration stays consistent with the DB.

- [ ] **Step 1: Read the existing CHECK string**

Read `backend/app/models/iam.py` around lines 220-230 to confirm exact format.

- [ ] **Step 2: Update the CHECK string**

Change the literal at `backend/app/models/iam.py:222-225` from:

```python
"roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[]"
```

to:

```python
"roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER','SITE_MANAGER']::varchar[]"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/iam.py
git commit -m "feat(F-0088): include SITE_MANAGER in OrganizationMember CHECK"
```

---

### Task 3: Create `Site` SQLAlchemy model

**Files:**
- Modify: `backend/app/models/science.py` (append `Site` class near the existing `Equipment` model)
- Test: `backend/tests/unit/test_site_model.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_site_model.py
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.science import Site


@pytest.mark.asyncio
async def test_site_minimal_fields(db_session, sample_org):
    site = Site(
        organization_id=sample_org.id,
        name="South Bay HQ",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    assert site.id is not None
    assert site.archived_at is None
    assert site.created_at is not None


@pytest.mark.asyncio
async def test_site_partial_unique_active_name(db_session, sample_org):
    s1 = Site(organization_id=sample_org.id, name="HQ")
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=sample_org.id, name="HQ")
    db_session.add(s2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_site_name_reused_after_archive(db_session, sample_org):
    s1 = Site(organization_id=sample_org.id, name="HQ", archived_at=datetime.now(timezone.utc))
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=sample_org.id, name="HQ")
    db_session.add(s2)
    await db_session.commit()  # should NOT raise
    assert s2.id != s1.id


@pytest.mark.asyncio
async def test_site_is_default_default_false(db_session, sample_org):
    s = Site(organization_id=sample_org.id, name="HQ")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    assert s.is_default is False


@pytest.mark.asyncio
async def test_only_one_default_site_per_org(db_session, sample_org):
    s1 = Site(organization_id=sample_org.id, name="HQ", is_default=True)
    db_session.add(s1)
    await db_session.commit()

    s2 = Site(organization_id=sample_org.id, name="Lab B", is_default=True)
    db_session.add(s2)
    with pytest.raises(IntegrityError):
        await db_session.commit()  # partial unique violation
```

- [ ] **Step 2: Run test — expect FAIL (ImportError)**

`cd backend && pytest tests/unit/test_site_model.py -v` → ImportError: cannot import name 'Site'.

- [ ] **Step 3: Add the `Site` model**

In `backend/app/models/science.py`, append after the existing `Equipment` class:

```python
class Site(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sites"
    __table_args__ = (
        Index("ix_sites_org", "organization_id"),
        Index(
            "uq_sites_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "uq_sites_org_is_default",
            "organization_id",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization", lazy="joined")
    equipment = relationship("Equipment", back_populates="site", lazy="select")
```

Confirm `Boolean` is imported at the top of `science.py` (along with `Text`, `Index`, `text`).

Confirm the imports at the top of the file include `Text`, `Index`, `text` from `sqlalchemy`; add any that are missing.

- [ ] **Step 4: Run test — expect PASS (after Task 5 migration creates the table)**

Test will still fail until the table exists. Mark this task complete and proceed; the test will pass after Task 5.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/science.py backend/tests/unit/test_site_model.py
git commit -m "feat(F-0088): add Site model"
```

---

### Task 4: Extend `Equipment` model + add `EquipmentAttachment`

**Files:**
- Modify: `backend/app/models/science.py` (existing `Equipment` class around line 445)

- [ ] **Step 1: Add the `EquipmentStatus` enum**

In `backend/app/models/science.py`, near the top with other enums:

```python
class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"
```

- [ ] **Step 2: Extend `Equipment` columns**

Inside the existing `Equipment` class, add (keep all existing columns intact):

```python
    site_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EquipmentStatus.ACTIVE.value,
        server_default=EquipmentStatus.ACTIVE.value,
    )
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_calibration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_calibration_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    room: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::varchar[]"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    site = relationship("Site", back_populates="equipment", lazy="joined")
    attachments = relationship(
        "EquipmentAttachment", back_populates="equipment",
        lazy="select", cascade="all, delete-orphan",
    )
```

Add `__table_args__` extension if the existing class already declares it; otherwise add:

```python
    __table_args__ = (
        Index("ix_equipment_site", "site_id"),
        Index("ix_equipment_org_status", "organization_id", "status"),
    )
```

Add missing imports at the file head: `Date`, `ARRAY`, `Text`, `Index`, `text`, `Enum` (Python `enum`), `date` from `datetime`.

- [ ] **Step 3: Add `EquipmentAttachment` model**

Append below `Equipment`:

```python
class EquipmentAttachment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "equipment_attachments"

    equipment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("equipment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    equipment = relationship("Equipment", back_populates="attachments", lazy="joined")
```

- [ ] **Step 3.5: Add `SiteManagerGrant` model**

Append below `EquipmentAttachment`:

```python
class SiteManagerGrant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "site_manager_grants"
    __table_args__ = (
        Index("ix_site_manager_grants_site", "site_id"),
        Index("ix_site_manager_grants_user", "user_id"),
        Index("ix_site_manager_grants_org", "organization_id"),
        Index(
            "uq_site_manager_grants_site_user",
            "site_id", "user_id", unique=True,
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    site_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    granted_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    site = relationship("Site", lazy="joined")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
    granted_by = relationship("User", foreign_keys=[granted_by_id], lazy="select")
```

- [ ] **Step 4: Commit (model only — tests come after migration)**

```bash
git add backend/app/models/science.py
git commit -m "feat(F-0088): extend Equipment model + add EquipmentAttachment + SiteManagerGrant"
```

---

### Task 5: Alembic migration — schema + data backfill

**Files:**
- Create: `backend/alembic/versions/f0088_add_sites_and_extend_equipment.py`

- [ ] **Step 1: Write the integration test that validates the backfill**

```python
# backend/tests/integration/test_migration_backfill.py
import pytest
from sqlalchemy import select, text

from app.models.science import Equipment, Site


@pytest.mark.asyncio
async def test_every_equipment_row_has_site_id(db_session):
    rows = (await db_session.execute(select(Equipment))).scalars().all()
    for row in rows:
        assert row.site_id is not None
        # Site belongs to the same org.
        site = await db_session.get(Site, row.site_id)
        assert site.organization_id == row.organization_id


@pytest.mark.asyncio
async def test_every_org_has_exactly_one_default_site(db_session):
    # Eager backfill: every org — even orgs with no equipment — must own
    # exactly one is_default=true site after the migration.
    org_count = (await db_session.execute(
        text("SELECT COUNT(*) FROM organizations")
    )).scalar_one()
    default_count = (await db_session.execute(
        text("SELECT COUNT(*) FROM sites WHERE is_default = true")
    )).scalar_one()
    assert default_count == org_count

    duplicates = (await db_session.execute(text("""
        SELECT organization_id, COUNT(*) FROM sites
        WHERE is_default = true
        GROUP BY organization_id HAVING COUNT(*) > 1
    """))).all()
    assert duplicates == []


@pytest.mark.asyncio
async def test_equipment_site_id_is_not_null(db_session):
    result = await db_session.execute(text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='equipment' AND column_name='site_id'"
    ))
    nullable = result.scalar_one()
    assert nullable == "NO"


@pytest.mark.asyncio
async def test_site_manager_grants_table_exists(db_session):
    result = await db_session.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'site_manager_grants'"
    ))
    assert result.scalar_one() == 1
```

- [ ] **Step 2: Generate the migration file**

`cd backend && alembic revision -m "f0088 add sites and extend equipment" --rev-id f0088_add_sites_and_extend_equipment`

- [ ] **Step 3: Replace the generated body**

```python
"""f0088 add sites and extend equipment

Revision ID: f0088_add_sites_and_extend_equipment
Revises: <PREVIOUS_HEAD>
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY


revision = "f0088_add_sites_and_extend_equipment"
down_revision = "<PREVIOUS_HEAD>"  # fill in from alembic history
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. sites
    op.create_table(
        "sites",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_default", sa.Boolean(),
                  server_default=sa.text("false"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("archive_reason", sa.Text()),
        sa.Column("created_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sites_org", "sites", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_sites_org_name ON sites (organization_id, name) "
        "WHERE archived_at IS NULL"
    )
    # At most one default site per org. Partial unique index so archived
    # rows do not conflict, and so non-default rows are unconstrained.
    op.execute(
        "CREATE UNIQUE INDEX uq_sites_org_is_default ON sites (organization_id) "
        "WHERE is_default = true AND archived_at IS NULL"
    )

    # 2. equipment new columns (all nullable initially so backfill can run)
    op.add_column("equipment", sa.Column("site_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("sites.id", ondelete="RESTRICT")))
    op.add_column("equipment", sa.Column("created_by_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("equipment", sa.Column("manufacturer", sa.String(120)))
    op.add_column("equipment", sa.Column("model", sa.String(120)))
    op.add_column("equipment", sa.Column("serial_number", sa.String(120)))
    op.add_column("equipment", sa.Column("status", sa.String(20),
                                        server_default="ACTIVE", nullable=False))
    op.add_column("equipment", sa.Column("install_date", sa.Date()))
    op.add_column("equipment", sa.Column("last_calibration_date", sa.Date()))
    op.add_column("equipment", sa.Column("next_calibration_due", sa.Date()))
    op.add_column("equipment", sa.Column("room", sa.String(120)))
    op.add_column("equipment", sa.Column("tags", ARRAY(sa.String()),
                                        server_default=sa.text("ARRAY[]::varchar[]"),
                                        nullable=False))
    op.add_column("equipment", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("equipment", sa.Column("archived_by_id", PG_UUID(as_uuid=True),
                                        sa.ForeignKey("users.id", ondelete="SET NULL")))

    # 3. Backfill: EAGER — every org gets a Default Site (is_default=true),
    #    not just orgs that already have equipment. New orgs created after
    #    this migration get one via `ensure_default_site()` in the org
    #    creation path. Decision 8a-i in the grill: empty orgs need the
    #    Default Site immediately so site-scoped UI never sees an org with
    #    zero sites.
    op.execute("""
        INSERT INTO sites (id, organization_id, name, description,
                           is_default, created_at, updated_at)
        SELECT gen_random_uuid(), o.id, 'Default Site',
               'Auto-created on F-0088 migration', true, NOW(), NOW()
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM sites s
            WHERE s.organization_id = o.id AND s.is_default = true
              AND s.archived_at IS NULL
        )
    """)
    op.execute("""
        UPDATE equipment e
        SET site_id = s.id
        FROM sites s
        WHERE s.organization_id = e.organization_id
          AND s.is_default = true
          AND s.archived_at IS NULL
          AND e.site_id IS NULL
    """)

    # 4. Tighten constraints.
    op.alter_column("equipment", "site_id", nullable=False)
    op.create_index("ix_equipment_site", "equipment", ["site_id"])
    op.create_index("ix_equipment_org_status", "equipment", ["organization_id", "status"])

    # 5. equipment_attachments
    op.create_table(
        "equipment_attachments",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("equipment_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_equipment_attachments_eq", "equipment_attachments", ["equipment_id"])

    # 6. OrganizationMember CHECK constraint: add SITE_MANAGER.
    op.execute("ALTER TABLE organization_members DROP CONSTRAINT IF EXISTS ck_organization_members_roles_valid")
    op.execute(
        "ALTER TABLE organization_members ADD CONSTRAINT ck_organization_members_roles_valid "
        "CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER','SITE_MANAGER']::varchar[])"
    )

    # 7. site_manager_grants — per-site authorization.
    #    Decision 4 in the grill: SITE_MANAGER on OrganizationMember.roles
    #    is a *capability* bit; the grant table is what actually authorizes
    #    a given member to manage a given site. Both must be present.
    op.create_table(
        "site_manager_grants",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("site_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("sites.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("granted_by_id", PG_UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_site_manager_grants_site", "site_manager_grants", ["site_id"])
    op.create_index("ix_site_manager_grants_user", "site_manager_grants", ["user_id"])
    op.create_index("ix_site_manager_grants_org", "site_manager_grants", ["organization_id"])
    op.create_index(
        "uq_site_manager_grants_site_user",
        "site_manager_grants", ["site_id", "user_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_site_manager_grants_site_user", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_org", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_user", "site_manager_grants")
    op.drop_index("ix_site_manager_grants_site", "site_manager_grants")
    op.drop_table("site_manager_grants")

    op.execute("ALTER TABLE organization_members DROP CONSTRAINT IF EXISTS ck_organization_members_roles_valid")
    op.execute(
        "ALTER TABLE organization_members ADD CONSTRAINT ck_organization_members_roles_valid "
        "CHECK (roles <@ ARRAY['ADMIN','BILLING','MEMBER','PROTOCOL_APPROVER']::varchar[])"
    )

    op.drop_index("ix_equipment_attachments_eq", "equipment_attachments")
    op.drop_table("equipment_attachments")

    op.drop_index("ix_equipment_org_status", "equipment")
    op.drop_index("ix_equipment_site", "equipment")
    for col in ("archived_by_id", "archived_at", "tags", "room",
                "next_calibration_due", "last_calibration_date", "install_date",
                "status", "serial_number", "model", "manufacturer",
                "created_by_id", "site_id"):
        op.drop_column("equipment", col)

    op.execute("DROP INDEX IF EXISTS uq_sites_org_is_default")
    op.execute("DROP INDEX IF EXISTS uq_sites_org_name")
    op.drop_index("ix_sites_org", "sites")
    op.drop_table("sites")
```

Replace `<PREVIOUS_HEAD>` with the value returned by `alembic heads`.

- [ ] **Step 4: Apply the migration and run the backfill test**

```bash
cd backend && alembic upgrade head
pytest tests/integration/test_migration_backfill.py -v
pytest tests/unit/test_site_model.py -v
```

Both should PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/f0088_add_sites_and_extend_equipment.py \
        backend/tests/integration/test_migration_backfill.py
git commit -m "feat(F-0088): migration — sites table, equipment extensions, default-site backfill"
```

---

## Phase 2 — Pydantic schemas & permission helper

### Task 6: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/sites.py`
- Create: `backend/app/schemas/equipment.py`

- [ ] **Step 1: Create `schemas/sites.py`**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class SiteArchiveRequest(BaseModel):
    default_move_to: UUID
    overrides: dict[UUID, UUID] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)


class SiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    is_default: bool
    archived_at: datetime | None
    archived_by_id: UUID | None
    archive_reason: str | None
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SiteManagerGrantCreate(BaseModel):
    """Body for POST /sites/{site_id}/managers — single user_id per call.

    Bulk grant flows on the frontend (`MemberSitesInlinePicker`, the site
    detail "+ Add manager" picker) iterate this endpoint client-side; the
    backend stays one-grant-per-row to keep audit entries 1:1 with grants.
    """
    user_id: UUID


class SiteManagerGrantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    site_id: UUID
    user_id: UUID
    granted_by_id: UUID | None
    created_at: datetime


class ManagedSiteResponse(BaseModel):
    """Returned by GET /users/{user_id}/managed-sites — joins grant + site.

    Frontend `MemberSitesInlinePicker` needs both the grant id (for revoke)
    and the site name (for display) in one shot; an embedded SiteResponse
    keeps the picker query off the sites endpoint.
    """
    model_config = ConfigDict(from_attributes=True)

    grant_id: UUID
    site: SiteResponse
```

- [ ] **Step 2: Create `schemas/equipment.py`**

```python
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: UUID
    description: str | None = None
    equipment_type: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    room: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    status: EquipmentStatus = EquipmentStatus.ACTIVE
    install_date: date | None = None
    last_calibration_date: date | None = None
    next_calibration_due: date | None = None


class EquipmentUpdate(BaseModel):
    """All fields optional — endpoint diffs which are touched against
    `RESTRICTED_EQUIPMENT_FIELDS` to enforce role gate."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: UUID | None = None
    description: str | None = None
    equipment_type: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    room: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    manufacturer: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    status: EquipmentStatus | None = None
    install_date: date | None = None
    last_calibration_date: date | None = None
    next_calibration_due: date | None = None


class EquipmentAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    equipment_id: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_by_id: UUID
    created_at: datetime


class EquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    site_id: UUID
    name: str
    description: str | None
    equipment_type: str | None
    location: str | None
    room: str | None
    tags: list[str]
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    status: EquipmentStatus
    install_date: date | None
    last_calibration_date: date | None
    next_calibration_due: date | None
    archived_at: datetime | None
    archived_by_id: UUID | None
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/sites.py backend/app/schemas/equipment.py
git commit -m "feat(F-0088): Pydantic schemas for Site, Equipment, attachments"
```

---

### Task 7: `require_any_org_role` dependency factory

**Files:**
- Modify: `backend/app/core/deps.py` (append near `require_org_role` around line 149)
- Test: `backend/tests/unit/test_require_any_org_role.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_require_any_org_role.py
import pytest
from fastapi import HTTPException

from app.core.deps import require_any_org_role
from app.models.iam import OrgRole


@pytest.mark.asyncio
async def test_member_with_required_role_passes(
    db_session, sample_user, sample_org_membership_with_roles
):
    membership = await sample_org_membership_with_roles(["MEMBER", "SITE_MANAGER"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])
    result = await dep(user=sample_user, db=db_session)
    assert result.id == sample_user.id


@pytest.mark.asyncio
async def test_admin_only_member_rejected_without_admin_in_list(
    db_session, sample_user, sample_org_membership_with_roles
):
    await sample_org_membership_with_roles(["MEMBER"])
    dep = require_any_org_role([OrgRole.SITE_MANAGER])  # ADMIN NOT included
    with pytest.raises(HTTPException) as exc:
        await dep(user=sample_user, db=db_session)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test — expect FAIL**

`pytest tests/unit/test_require_any_org_role.py -v` → ImportError.

- [ ] **Step 3: Implement `require_any_org_role`**

In `backend/app/core/deps.py`, after the existing `require_org_role` function:

```python
def require_any_org_role(roles: list["OrgRole"]):
    """Allow if the user's org membership holds ANY of the given roles.

    Additive — does NOT use the legacy rank hierarchy. ADMIN must be listed
    explicitly to satisfy a `SITE_MANAGER ∨ ADMIN` rule.
    """
    role_values = {r.value for r in roles}

    async def dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        membership = await _get_active_membership(db, user)
        if not membership:
            raise HTTPException(status_code=403, detail="Not a member of this organization")
        if not (set(membership.roles or []) & role_values):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {sorted(role_values)}",
            )
        return user

    return dep
```

Reuse the existing `_get_active_membership` helper from the same file (it's used by `require_org_role`).

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_require_any_org_role.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/deps.py backend/tests/unit/test_require_any_org_role.py
git commit -m "feat(F-0088): require_any_org_role dependency factory"
```

---

## Phase 3 — Sites service

### Task 8: `services/sites/defaults.py`

**Files:**
- Create: `backend/app/services/sites/__init__.py`
- Create: `backend/app/services/sites/defaults.py`
- Test: `backend/tests/unit/test_sites_defaults.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_sites_defaults.py
import pytest

from app.services.sites.defaults import (
    DEFAULT_SITE_NAME,
    ensure_default_site,
    is_default_site,
)


@pytest.mark.asyncio
async def test_ensure_default_site_creates(db_session, sample_org, sample_user):
    site = await ensure_default_site(db_session, sample_org.id, actor_id=sample_user.id)
    assert site.name == DEFAULT_SITE_NAME
    assert site.organization_id == sample_org.id


@pytest.mark.asyncio
async def test_ensure_default_site_idempotent(db_session, sample_org, sample_user):
    s1 = await ensure_default_site(db_session, sample_org.id, actor_id=sample_user.id)
    s2 = await ensure_default_site(db_session, sample_org.id, actor_id=sample_user.id)
    assert s1.id == s2.id


@pytest.mark.asyncio
async def test_is_default_site_reads_column_not_name(
    db_session, sample_org, sample_user
):
    """is_default_site() trusts the is_default column, not the name string.

    Decision 8c-ii in the grill: identity is by column, not by name —
    so a SITE_MANAGER can rename "Default Site" → "HQ" and we still
    treat it as the default for downstream behavior.
    """
    site = await ensure_default_site(
        db_session, sample_org.id, actor_id=sample_user.id
    )
    assert site.is_default is True
    assert is_default_site(site) is True

    site.name = "HQ"  # rename does not affect default identity
    assert is_default_site(site) is True
```

- [ ] **Step 2: Run test — expect FAIL (ImportError)**

`pytest tests/unit/test_sites_defaults.py -v` → ImportError.

- [ ] **Step 3: Implement**

`backend/app/services/sites/__init__.py`:

```python
from app.services.sites import crud, defaults  # noqa: F401
```

`backend/app/services/sites/defaults.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Site

DEFAULT_SITE_NAME = "Default Site"


async def ensure_default_site(
    db: AsyncSession, org_id: UUID, *, actor_id: UUID | None
) -> Site:
    """Return the org's default site, creating it if missing.

    Identity is the `is_default` column — NOT the name. The migration
    eager-creates one row per org with is_default=true; this helper is
    the runtime equivalent for new orgs created post-migration.
    """
    stmt = select(Site).where(
        Site.organization_id == org_id,
        Site.is_default.is_(True),
        Site.archived_at.is_(None),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    site = Site(
        organization_id=org_id,
        name=DEFAULT_SITE_NAME,
        description="Auto-created default site for this organization.",
        is_default=True,
        created_by_id=actor_id,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return site


def is_default_site(site: Site) -> bool:
    """Default identity is the column, not the name. A SITE_MANAGER may
    rename the row to "HQ"; it is still the default until the column flips.
    """
    return bool(site.is_default)
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_sites_defaults.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sites/__init__.py backend/app/services/sites/defaults.py \
        backend/tests/unit/test_sites_defaults.py
git commit -m "feat(F-0088): sites/defaults — ensure_default_site"
```

---

### Task 8b: `services/sites/grants.py` — per-site authorization

Decision 4 in the grill: SITE_MANAGER on the OrganizationMember.roles
array is a *capability bit* (this user is allowed to manage **some**
site). The `site_manager_grants` table answers the second question —
**which** sites. Both must agree: a member with the role bit but no
grants cannot edit any equipment's regulated fields; a member with a
grant but no role bit is a bug (grants are removed when the role bit
is removed — see Task 31).

**Files:**
- Create: `backend/app/services/sites/grants.py`
- Test: `backend/tests/unit/test_sites_grants.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_sites_grants.py
import pytest
from fastapi import HTTPException

from app.services.sites.grants import (
    grant_site_manager,
    list_grants_for_site,
    list_managed_sites_for_user,
    revoke_site_manager,
    user_has_grant,
)


@pytest.mark.asyncio
async def test_grant_and_list_for_site(
    db_session, sample_org, sample_site, sample_user, sample_admin
):
    grant = await grant_site_manager(
        db_session, site=sample_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    grants = await list_grants_for_site(db_session, sample_site.id)
    assert [g.id for g in grants] == [grant.id]


@pytest.mark.asyncio
async def test_grant_is_idempotent(
    db_session, sample_site, sample_user, sample_admin
):
    g1 = await grant_site_manager(
        db_session, site=sample_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    g2 = await grant_site_manager(
        db_session, site=sample_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    assert g1.id == g2.id  # uq_site_manager_grants_site_user blocks duplicates


@pytest.mark.asyncio
async def test_revoke_clears_grant(
    db_session, sample_site, sample_user, sample_admin
):
    await grant_site_manager(
        db_session, site=sample_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    await revoke_site_manager(
        db_session, site_id=sample_site.id, user_id=sample_user.id,
        actor_id=sample_admin.id,
    )
    assert await user_has_grant(db_session, sample_site.id, sample_user.id) is False


@pytest.mark.asyncio
async def test_list_managed_sites_for_user_excludes_archived(
    db_session, sample_user, sample_admin, sample_site, archived_site
):
    await grant_site_manager(
        db_session, site=sample_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    await grant_site_manager(
        db_session, site=archived_site, user_id=sample_user.id,
        granted_by_id=sample_admin.id,
    )
    out = await list_managed_sites_for_user(
        db_session, sample_user.id, include_archived=False,
    )
    assert [m.site.id for m in out] == [sample_site.id]


@pytest.mark.asyncio
async def test_grant_rejects_archived_site(
    db_session, archived_site, sample_user, sample_admin
):
    with pytest.raises(HTTPException) as exc:
        await grant_site_manager(
            db_session, site=archived_site, user_id=sample_user.id,
            granted_by_id=sample_admin.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVED"
```

- [ ] **Step 2: Run test — expect FAIL (ImportError)**

`pytest tests/unit/test_sites_grants.py -v` → ImportError.

- [ ] **Step 3: Implement**

`backend/app/services/sites/grants.py`:

```python
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.science import Site, SiteManagerGrant
from app.services.core.audit import log_audit


async def list_grants_for_site(
    db: AsyncSession, site_id: UUID
) -> list[SiteManagerGrant]:
    stmt = (
        select(SiteManagerGrant)
        .where(SiteManagerGrant.site_id == site_id)
        .options(selectinload(SiteManagerGrant.user))
        .order_by(SiteManagerGrant.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_managed_sites_for_user(
    db: AsyncSession, user_id: UUID, *, include_archived: bool = False
) -> list[SiteManagerGrant]:
    """All grants held by user_id, eager-loading the Site for display.

    Frontend `MemberSitesInlinePicker` consumes this directly to render
    the inline chip tray under the SITE_MANAGER role chip.
    """
    stmt = (
        select(SiteManagerGrant)
        .join(Site, Site.id == SiteManagerGrant.site_id)
        .where(SiteManagerGrant.user_id == user_id)
        .options(selectinload(SiteManagerGrant.site))
    )
    if not include_archived:
        stmt = stmt.where(Site.archived_at.is_(None))
    stmt = stmt.order_by(Site.name)
    return list((await db.execute(stmt)).scalars().all())


async def user_has_grant(
    db: AsyncSession, site_id: UUID, user_id: UUID
) -> bool:
    stmt = select(SiteManagerGrant.id).where(
        SiteManagerGrant.site_id == site_id,
        SiteManagerGrant.user_id == user_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def grant_site_manager(
    db: AsyncSession, *, site: Site, user_id: UUID, granted_by_id: UUID
) -> SiteManagerGrant:
    if site.archived_at is not None:
        raise HTTPException(400, detail={"code": "SITE_ARCHIVED"})

    existing = await db.execute(
        select(SiteManagerGrant).where(
            SiteManagerGrant.site_id == site.id,
            SiteManagerGrant.user_id == user_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found  # idempotent

    grant = SiteManagerGrant(
        organization_id=site.organization_id,
        site_id=site.id,
        user_id=user_id,
        granted_by_id=granted_by_id,
    )
    db.add(grant)
    await db.flush()
    # Primary audit entry on the grant. The site-detail audit feed also
    # gets a "shadow" entry so a SITE_MANAGER reading the site history
    # sees who joined/left without having to know about the grants
    # table. Decision 11 in the grill.
    await log_audit(
        db, actor_id=granted_by_id, action="CREATE",
        entity_type="site_manager_grant", entity_id=grant.id,
        changes={"site_id": str(site.id), "user_id": str(user_id)},
    )
    await log_audit(
        db, actor_id=granted_by_id, action="GRANT_ADDED",
        entity_type="site", entity_id=site.id,
        changes={"user_id": str(user_id), "grant_id": str(grant.id)},
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def revoke_site_manager(
    db: AsyncSession, *, site_id: UUID, user_id: UUID, actor_id: UUID
) -> None:
    grant = (await db.execute(
        select(SiteManagerGrant).where(
            SiteManagerGrant.site_id == site_id,
            SiteManagerGrant.user_id == user_id,
        )
    )).scalar_one_or_none()
    if grant is None:
        raise HTTPException(404, detail={"code": "SITE_GRANT_NOT_FOUND"})

    grant_id = grant.id
    await db.delete(grant)
    await log_audit(
        db, actor_id=actor_id, action="DELETE",
        entity_type="site_manager_grant", entity_id=grant_id,
        changes={"site_id": str(site_id), "user_id": str(user_id)},
    )
    await log_audit(
        db, actor_id=actor_id, action="GRANT_REMOVED",
        entity_type="site", entity_id=site_id,
        changes={"user_id": str(user_id), "grant_id": str(grant_id)},
    )
    await db.commit()
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_sites_grants.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sites/grants.py backend/tests/unit/test_sites_grants.py
git commit -m "feat(F-0088): sites/grants — per-site SITE_MANAGER authorization"
```

---

### Task 8c: `services/permissions/equipment.py` — capability helpers

Wraps the "role bit AND a matching grant" predicate so endpoints don't
re-derive it inline. ADMIN bypasses both. The frontend store
`canManageEquipmentLifecycle` (Task 19) is a thin mirror of these.

**Files:**
- Create: `backend/app/services/permissions/__init__.py`
- Create: `backend/app/services/permissions/equipment.py`
- Test: `backend/tests/unit/test_permissions_equipment.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_permissions_equipment.py
import pytest

from app.services.permissions.equipment import (
    user_can_edit_restricted_equipment,
    user_can_move_equipment,
    user_can_rename_site,
)


@pytest.mark.asyncio
async def test_admin_bypasses_grant_check(
    db_session, sample_admin, sample_site
):
    ok = await user_can_edit_restricted_equipment(
        db_session, user_id=sample_admin.id, org_id=sample_site.organization_id,
        site_id=sample_site.id,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_site_manager_with_grant_can_edit(
    db_session, sample_user, sample_site, granted_membership
):
    """granted_membership fixture: user holds SITE_MANAGER role + a grant
    on sample_site."""
    ok = await user_can_edit_restricted_equipment(
        db_session, user_id=sample_user.id, org_id=sample_site.organization_id,
        site_id=sample_site.id,
    )
    assert ok is True


@pytest.mark.asyncio
async def test_site_manager_without_grant_for_this_site_cannot_edit(
    db_session, sample_user, sample_site, other_site, site_manager_grant_other
):
    """User has role bit + grant on other_site, but not on sample_site."""
    ok = await user_can_edit_restricted_equipment(
        db_session, user_id=sample_user.id, org_id=sample_site.organization_id,
        site_id=sample_site.id,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_move_requires_grants_on_both_sites(
    db_session, sample_user, sample_site, other_site, site_manager_grant_only_source
):
    """Decision 7 in the grill: moving equipment between sites needs
    SITE_MANAGER on BOTH source AND destination (or ADMIN)."""
    ok, missing = await user_can_move_equipment(
        db_session, user_id=sample_user.id, org_id=sample_site.organization_id,
        from_site_id=sample_site.id, to_site_id=other_site.id,
    )
    assert ok is False
    assert other_site.id in missing
```

- [ ] **Step 2: Run test — expect FAIL (ImportError)**

`pytest tests/unit/test_permissions_equipment.py -v` → ImportError.

- [ ] **Step 3: Implement**

`backend/app/services/permissions/__init__.py`:

```python
from app.services.permissions import equipment  # noqa: F401
```

`backend/app/services/permissions/equipment.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import OrganizationMember
from app.models.science import SiteManagerGrant


async def _is_admin(
    db: AsyncSession, *, user_id: UUID, org_id: UUID
) -> bool:
    stmt = select(OrganizationMember.roles).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
        OrganizationMember.deleted_at.is_(None),
    )
    roles = (await db.execute(stmt)).scalar_one_or_none()
    return roles is not None and "ADMIN" in (roles or [])


async def _has_site_manager_role(
    db: AsyncSession, *, user_id: UUID, org_id: UUID
) -> bool:
    stmt = select(OrganizationMember.roles).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
        OrganizationMember.deleted_at.is_(None),
    )
    roles = (await db.execute(stmt)).scalar_one_or_none()
    return roles is not None and "SITE_MANAGER" in (roles or [])


async def _has_grant(
    db: AsyncSession, *, user_id: UUID, site_id: UUID
) -> bool:
    stmt = select(SiteManagerGrant.id).where(
        SiteManagerGrant.user_id == user_id,
        SiteManagerGrant.site_id == site_id,
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def user_can_edit_restricted_equipment(
    db: AsyncSession, *, user_id: UUID, org_id: UUID, site_id: UUID
) -> bool:
    """ADMIN always; otherwise needs SITE_MANAGER role AND a grant on
    the equipment's site. Both predicates required — neither alone
    authorizes regulated-data edits."""
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False
    return await _has_grant(db, user_id=user_id, site_id=site_id)


async def user_can_move_equipment(
    db: AsyncSession, *, user_id: UUID, org_id: UUID,
    from_site_id: UUID, to_site_id: UUID,
) -> tuple[bool, list[UUID]]:
    """Return (ok, missing_grants). Decision 7 in the grill: a site move
    is a regulated edit on the source AND a regulated edit on the
    destination — so the caller needs grants on both. ADMIN bypasses.

    Missing-grants list is returned so the endpoint can surface a
    specific `SITE_MOVE_FORBIDDEN` payload telling the UI which side
    the caller is short on, instead of a generic 403.
    """
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True, []
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False, [from_site_id, to_site_id]
    missing: list[UUID] = []
    if not await _has_grant(db, user_id=user_id, site_id=from_site_id):
        missing.append(from_site_id)
    if not await _has_grant(db, user_id=user_id, site_id=to_site_id):
        missing.append(to_site_id)
    return (not missing), missing


async def user_can_rename_site(
    db: AsyncSession, *, user_id: UUID, org_id: UUID, site_id: UUID
) -> bool:
    """Decision 5c-ii in the grill: SITE_MANAGER can rename the site they
    manage. CREATE/ARCHIVE remain ADMIN-only (enforced in the router)."""
    if await _is_admin(db, user_id=user_id, org_id=org_id):
        return True
    if not await _has_site_manager_role(db, user_id=user_id, org_id=org_id):
        return False
    return await _has_grant(db, user_id=user_id, site_id=site_id)
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_permissions_equipment.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/permissions/__init__.py \
        backend/app/services/permissions/equipment.py \
        backend/tests/unit/test_permissions_equipment.py
git commit -m "feat(F-0088): permissions/equipment — role-bit + grant predicate helpers"
```

---

### Task 9: `services/sites/crud.py` — list, get, create, update

**Files:**
- Create: `backend/app/services/sites/crud.py`
- Test: `backend/tests/unit/test_sites_crud.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_sites_crud.py
import pytest
from fastapi import HTTPException

from app.schemas.sites import SiteCreate, SiteUpdate
from app.services.sites import crud


@pytest.mark.asyncio
async def test_create_site(db_session, sample_org, sample_user):
    site = await crud.create_site(
        db_session, org_id=sample_org.id,
        payload=SiteCreate(name="South Bay HQ"),
        actor_id=sample_user.id,
    )
    assert site.name == "South Bay HQ"
    assert site.created_by_id == sample_user.id


@pytest.mark.asyncio
async def test_create_site_name_conflict(db_session, sample_org, sample_user):
    await crud.create_site(db_session, org_id=sample_org.id,
                           payload=SiteCreate(name="HQ"), actor_id=sample_user.id)
    with pytest.raises(HTTPException) as exc:
        await crud.create_site(db_session, org_id=sample_org.id,
                               payload=SiteCreate(name="HQ"), actor_id=sample_user.id)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SITE_NAME_CONFLICT"


@pytest.mark.asyncio
async def test_list_sites_excludes_archived_by_default(db_session, sample_org, sample_user):
    s = await crud.create_site(db_session, org_id=sample_org.id,
                               payload=SiteCreate(name="Archived"), actor_id=sample_user.id)
    s.archived_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc)
    await db_session.commit()
    listed = await crud.list_sites(db_session, sample_org.id)
    assert all(x.archived_at is None for x in listed)


@pytest.mark.asyncio
async def test_update_site(db_session, sample_org, sample_user):
    s = await crud.create_site(db_session, org_id=sample_org.id,
                               payload=SiteCreate(name="HQ"), actor_id=sample_user.id)
    s2 = await crud.update_site(db_session, s, payload=SiteUpdate(description="hello"),
                                actor_id=sample_user.id)
    assert s2.description == "hello"
```

- [ ] **Step 2: Failing run**

`pytest tests/unit/test_sites_crud.py -v` → ImportError.

- [ ] **Step 3: Implement (list/get/create/update only — archive is Task 10)**

`backend/app/services/sites/crud.py`:

```python
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Site
from app.schemas.sites import SiteCreate, SiteUpdate
from app.services.core.audit import log_audit


async def list_sites(
    db: AsyncSession, org_id: UUID, *, include_archived: bool = False
) -> list[Site]:
    stmt = select(Site).where(Site.organization_id == org_id)
    if not include_archived:
        stmt = stmt.where(Site.archived_at.is_(None))
    stmt = stmt.order_by(Site.name)
    return list((await db.execute(stmt)).scalars().all())


async def get_site(db: AsyncSession, site_id: UUID) -> Site:
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _name_exists(db: AsyncSession, org_id: UUID, name: str, *, exclude_id: UUID | None = None) -> bool:
    stmt = select(Site).where(
        Site.organization_id == org_id,
        Site.name == name,
        Site.archived_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Site.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def create_site(
    db: AsyncSession, *, org_id: UUID, payload: SiteCreate, actor_id: UUID
) -> Site:
    if await _name_exists(db, org_id, payload.name):
        raise HTTPException(
            status_code=409,
            detail={"code": "SITE_NAME_CONFLICT", "name": payload.name},
        )
    site = Site(
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        created_by_id=actor_id,
    )
    db.add(site)
    await db.flush()
    await log_audit(db, actor_id=actor_id, action="CREATE",
                    entity_type="site", entity_id=site.id,
                    changes={"name": payload.name})
    await db.commit()
    await db.refresh(site)
    return site


async def update_site(
    db: AsyncSession, site: Site, *, payload: SiteUpdate, actor_id: UUID
) -> Site:
    diff: dict[str, list] = {}
    if payload.name is not None and payload.name != site.name:
        if await _name_exists(db, site.organization_id, payload.name, exclude_id=site.id):
            raise HTTPException(
                status_code=409,
                detail={"code": "SITE_NAME_CONFLICT", "name": payload.name},
            )
        diff["name"] = [site.name, payload.name]
        site.name = payload.name
    if payload.description is not None and payload.description != site.description:
        diff["description"] = [site.description, payload.description]
        site.description = payload.description
    if diff:
        await log_audit(db, actor_id=actor_id, action="UPDATE",
                        entity_type="site", entity_id=site.id, changes=diff)
    await db.commit()
    await db.refresh(site)
    return site
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_sites_crud.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sites/crud.py backend/tests/unit/test_sites_crud.py
git commit -m "feat(F-0088): sites/crud — list/get/create/update"
```

---

### Task 10: `archive_site` with per-equipment override map

**Files:**
- Modify: `backend/app/services/sites/crud.py` (append `archive_site`)
- Modify: `backend/tests/unit/test_sites_crud.py` (append archive tests)

- [ ] **Step 1: Failing test**

Append to `test_sites_crud.py`:

```python
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.science import Equipment, Site
from app.schemas.sites import SiteArchiveRequest


@pytest.mark.asyncio
async def test_archive_site_moves_equipment_to_default(
    db_session, sample_org, sample_user, make_equipment
):
    src = await crud.create_site(db_session, org_id=sample_org.id,
                                 payload=SiteCreate(name="Old Lab"),
                                 actor_id=sample_user.id)
    dst = await crud.create_site(db_session, org_id=sample_org.id,
                                 payload=SiteCreate(name="New Lab"),
                                 actor_id=sample_user.id)
    e1 = await make_equipment(site_id=src.id)
    e2 = await make_equipment(site_id=src.id)

    await crud.archive_site(
        db_session, src,
        default_move_to=dst.id, overrides={}, reason="consolidate",
        actor_id=sample_user.id,
    )

    await db_session.refresh(e1)
    await db_session.refresh(e2)
    assert e1.site_id == dst.id
    assert e2.site_id == dst.id

    await db_session.refresh(src)
    assert src.archived_at is not None
    assert src.archive_reason == "consolidate"


@pytest.mark.asyncio
async def test_archive_site_honors_overrides(
    db_session, sample_org, sample_user, make_equipment
):
    src = await crud.create_site(db_session, org_id=sample_org.id,
                                 payload=SiteCreate(name="Old Lab"),
                                 actor_id=sample_user.id)
    dst_a = await crud.create_site(db_session, org_id=sample_org.id,
                                   payload=SiteCreate(name="Lab A"),
                                   actor_id=sample_user.id)
    dst_b = await crud.create_site(db_session, org_id=sample_org.id,
                                   payload=SiteCreate(name="Lab B"),
                                   actor_id=sample_user.id)
    e1 = await make_equipment(site_id=src.id)
    e2 = await make_equipment(site_id=src.id)

    await crud.archive_site(
        db_session, src,
        default_move_to=dst_a.id,
        overrides={e2.id: dst_b.id},
        reason="x",
        actor_id=sample_user.id,
    )
    await db_session.refresh(e1)
    await db_session.refresh(e2)
    assert e1.site_id == dst_a.id
    assert e2.site_id == dst_b.id


@pytest.mark.asyncio
async def test_archive_default_site_forbidden(
    db_session, sample_org, sample_user
):
    from app.services.sites.defaults import ensure_default_site
    default = await ensure_default_site(db_session, sample_org.id, actor_id=sample_user.id)
    other = await crud.create_site(db_session, org_id=sample_org.id,
                                   payload=SiteCreate(name="Other"),
                                   actor_id=sample_user.id)
    with pytest.raises(HTTPException) as exc:
        await crud.archive_site(
            db_session, default,
            default_move_to=other.id, overrides={}, reason="x",
            actor_id=sample_user.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVE_DEFAULT_FORBIDDEN"


@pytest.mark.asyncio
async def test_archive_site_rejects_self_as_destination(
    db_session, sample_org, sample_user
):
    s = await crud.create_site(db_session, org_id=sample_org.id,
                               payload=SiteCreate(name="X"),
                               actor_id=sample_user.id)
    with pytest.raises(HTTPException) as exc:
        await crud.archive_site(
            db_session, s,
            default_move_to=s.id, overrides={}, reason="x",
            actor_id=sample_user.id,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SITE_ARCHIVE_SELF_DESTINATION"
```

The `make_equipment` fixture should create an `Equipment` row tied to the given `site_id`; add it to `tests/conftest.py` if it doesn't exist:

```python
@pytest.fixture
def make_equipment(db_session, sample_org):
    async def _factory(*, site_id, name="Eq"):
        from app.models.science import Equipment
        e = Equipment(organization_id=sample_org.id, name=name, site_id=site_id)
        db_session.add(e)
        await db_session.commit()
        await db_session.refresh(e)
        return e
    return _factory
```

- [ ] **Step 2: Run tests — expect FAIL**

`pytest tests/unit/test_sites_crud.py -v -k archive` → FAIL.

- [ ] **Step 3: Implement `archive_site`**

Append to `backend/app/services/sites/crud.py`:

```python
from datetime import datetime, timezone

from app.models.science import Equipment
from app.services.sites.defaults import is_default_site


async def archive_site(
    db: AsyncSession,
    site: Site,
    *,
    default_move_to: UUID,
    overrides: dict[UUID, UUID] | None,
    reason: str,
    actor_id: UUID,
) -> Site:
    overrides = overrides or {}

    if is_default_site(site):
        raise HTTPException(
            status_code=400,
            detail={"code": "SITE_ARCHIVE_DEFAULT_FORBIDDEN", "site_id": str(site.id)},
        )

    if default_move_to == site.id or any(v == site.id for v in overrides.values()):
        raise HTTPException(
            status_code=400,
            detail={"code": "SITE_ARCHIVE_SELF_DESTINATION"},
        )

    # Validate every destination.
    destinations = {default_move_to, *overrides.values()}
    dest_rows = (
        await db.execute(select(Site).where(Site.id.in_(destinations)))
    ).scalars().all()
    found = {d.id: d for d in dest_rows}
    for dest_id in destinations:
        dest = found.get(dest_id)
        if dest is None or dest.organization_id != site.organization_id or dest.archived_at is not None:
            raise HTTPException(
                status_code=400,
                detail={"code": "SITE_ARCHIVE_BAD_DESTINATION", "site_id": str(dest_id)},
            )

    # Validate overrides reference equipment under this site.
    if overrides:
        eq_rows = (
            await db.execute(
                select(Equipment).where(Equipment.id.in_(list(overrides.keys())))
            )
        ).scalars().all()
        eq_by_id = {e.id: e for e in eq_rows}
        for eq_id in overrides.keys():
            e = eq_by_id.get(eq_id)
            if e is None or e.site_id != site.id:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "SITE_ARCHIVE_OVERRIDE_NOT_FOUND",
                            "equipment_id": str(eq_id)},
                )

    # Move equipment.
    all_eq = (
        await db.execute(
            select(Equipment).where(
                Equipment.site_id == site.id, Equipment.archived_at.is_(None)
            )
        )
    ).scalars().all()

    counts_per_dest: dict[UUID, int] = {}
    for e in all_eq:
        target = overrides.get(e.id, default_move_to)
        old = e.site_id
        e.site_id = target
        counts_per_dest[target] = counts_per_dest.get(target, 0) + 1
        await log_audit(db, actor_id=actor_id, action="UPDATE",
                        entity_type="equipment", entity_id=e.id,
                        changes={"site_id": [str(old), str(target)], "reason": reason})

    site.archived_at = datetime.now(timezone.utc)
    site.archived_by_id = actor_id
    site.archive_reason = reason

    await log_audit(db, actor_id=actor_id, action="ARCHIVE",
                    entity_type="site", entity_id=site.id,
                    changes={"reason": reason, "moves": {str(k): v for k, v in counts_per_dest.items()}})

    await db.commit()
    await db.refresh(site)
    return site
```

- [ ] **Step 4: Run all sites tests — expect PASS**

`pytest tests/unit/test_sites_crud.py tests/unit/test_sites_defaults.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sites/crud.py backend/tests/unit/test_sites_crud.py backend/tests/conftest.py
git commit -m "feat(F-0088): sites/crud — archive_site with override map"
```

---

## Phase 4 — Equipment service

### Task 11: `services/equipment/tags.py`

**Files:**
- Create: `backend/app/services/equipment/__init__.py`
- Create: `backend/app/services/equipment/tags.py`
- Test: `backend/tests/unit/test_equipment_tags.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_equipment_tags.py
import pytest
from app.services.equipment.tags import normalize_tag, normalize_tags


def test_normalize_tag_basic():
    assert normalize_tag(" High-Speed ") == "high-speed"


def test_normalize_tag_collapse_whitespace():
    assert normalize_tag("cell culture") == "cell-culture"


def test_normalize_tag_strip_disallowed():
    assert normalize_tag("GLP/QC") == "glp-qc"


def test_normalize_tag_truncates_to_40():
    out = normalize_tag("a" * 80)
    assert len(out) == 40


def test_normalize_tags_dedupes_and_caps_at_20():
    raw = ["GLP", "glp", " glp "] + [f"t{i}" for i in range(25)]
    out = normalize_tags(raw)
    assert out.count("glp") == 1
    assert len(out) <= 20


@pytest.mark.asyncio
async def test_list_distinct_tags(db_session, sample_org, make_equipment):
    from app.services.equipment.tags import list_distinct_tags
    e1 = await make_equipment(site_id=None, name="A")  # supply real site_id from fixture
    # ... fill tags
    e1.tags = ["alpha", "beta"]
    await db_session.commit()
    out = await list_distinct_tags(db_session, sample_org.id)
    assert "alpha" in out and "beta" in out
```

(Adapt `make_equipment` fixture from Task 10; ensure it takes a `tags` kwarg or set after creation.)

- [ ] **Step 2: Failing run**

`pytest tests/unit/test_equipment_tags.py -v` → ImportError.

- [ ] **Step 3: Implement**

`backend/app/services/equipment/__init__.py`:

```python
from app.services.equipment import attachments, registry, tags  # noqa: F401
```

`backend/app/services/equipment/tags.py`:

```python
import re
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment

_DISALLOWED = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN = re.compile(r"-+")
MAX_TAG_LEN = 40
MAX_TAGS_PER_EQUIPMENT = 20


def normalize_tag(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = _DISALLOWED.sub("-", s)
    s = _MULTI_HYPHEN.sub("-", s).strip("-")
    return s[:MAX_TAG_LEN]


def normalize_tags(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for t in raw:
        n = normalize_tag(t)
        if n and n not in seen:
            seen.append(n)
        if len(seen) >= MAX_TAGS_PER_EQUIPMENT:
            break
    return seen


async def list_distinct_tags(db: AsyncSession, org_id: UUID) -> list[str]:
    stmt = (
        select(func.unnest(Equipment.tags))
        .where(Equipment.organization_id == org_id, Equipment.archived_at.is_(None))
        .distinct()
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sorted([r for r in rows if r])
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_equipment_tags.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/equipment/__init__.py backend/app/services/equipment/tags.py \
        backend/tests/unit/test_equipment_tags.py
git commit -m "feat(F-0088): equipment/tags — normalize + list distinct"
```

---

### Task 12: `services/equipment/registry.py`

**Files:**
- Create: `backend/app/services/equipment/registry.py`
- Test: `backend/tests/unit/test_equipment_registry.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_equipment_registry.py
import pytest
from fastapi import HTTPException

from app.schemas.equipment import EquipmentCreate, EquipmentStatus, EquipmentUpdate
from app.services.equipment import registry


@pytest.mark.asyncio
async def test_create_equipment_requires_valid_site(
    db_session, sample_org, sample_user, sample_site
):
    eq = await registry.create_equipment(
        db_session, org_id=sample_org.id,
        payload=EquipmentCreate(name="Balance", site_id=sample_site.id,
                                tags=["GLP", "glp"]),
        actor_id=sample_user.id, can_set_restricted=True,
    )
    assert eq.tags == ["glp"]
    assert eq.status == "ACTIVE"


@pytest.mark.asyncio
async def test_create_equipment_soft_drops_restricted_when_not_authorized(
    db_session, sample_org, sample_user, sample_site
):
    """POST backdoor closed: non-SITE_MANAGER caller silently has
    regulated fields nulled. status falls back to ACTIVE because the
    column is NOT NULL. Decision 2 in the grill (hybrid 1+2)."""
    eq = await registry.create_equipment(
        db_session, org_id=sample_org.id,
        payload=EquipmentCreate(
            name="X", site_id=sample_site.id,
            manufacturer="Mettler", model="ME204",
            serial_number="MT-001",
            last_calibration_date="2026-01-01",
            status=EquipmentStatus.MAINTENANCE,
        ),
        actor_id=sample_user.id, can_set_restricted=False,
    )
    assert eq.manufacturer is None
    assert eq.model is None
    assert eq.serial_number is None
    assert eq.last_calibration_date is None
    assert eq.status == "ACTIVE"  # NOT NULL → defaults to ACTIVE


@pytest.mark.asyncio
async def test_create_equipment_cross_org_site_rejected(
    db_session, sample_org, sample_user, other_org_site
):
    with pytest.raises(HTTPException) as exc:
        await registry.create_equipment(
            db_session, org_id=sample_org.id,
            payload=EquipmentCreate(name="X", site_id=other_org_site.id),
            actor_id=sample_user.id, can_set_restricted=True,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_SITE_CROSS_ORG"


@pytest.mark.asyncio
async def test_list_filters_by_site_status_search_tag(
    db_session, sample_org, sample_user, sample_site
):
    a = await registry.create_equipment(
        db_session, org_id=sample_org.id,
        payload=EquipmentCreate(name="HPLC-1", site_id=sample_site.id, tags=["qc"]),
        actor_id=sample_user.id, can_set_restricted=True,
    )
    b = await registry.create_equipment(
        db_session, org_id=sample_org.id,
        payload=EquipmentCreate(name="Balance", site_id=sample_site.id, tags=["analytical"]),
        actor_id=sample_user.id, can_set_restricted=True,
    )
    out = await registry.list_equipment(db_session, sample_org.id, tag="qc")
    assert [e.id for e in out] == [a.id]

    out = await registry.list_equipment(db_session, sample_org.id, q="balance")
    assert [e.id for e in out] == [b.id]


@pytest.mark.asyncio
async def test_archive_equipment(db_session, sample_org, sample_user, sample_site):
    eq = await registry.create_equipment(
        db_session, org_id=sample_org.id,
        payload=EquipmentCreate(name="X", site_id=sample_site.id),
        actor_id=sample_user.id, can_set_restricted=True,
    )
    await registry.archive_equipment(db_session, eq, actor_id=sample_user.id)
    await db_session.refresh(eq)
    assert eq.archived_at is not None


def test_restricted_fields_set():
    assert "manufacturer" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "model" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "serial_number" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "status" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "install_date" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "last_calibration_date" in registry.RESTRICTED_EQUIPMENT_FIELDS
    assert "next_calibration_due" in registry.RESTRICTED_EQUIPMENT_FIELDS
    # Open fields NOT in set:
    for f in ("name", "equipment_type", "room", "location", "description", "tags"):
        assert f not in registry.RESTRICTED_EQUIPMENT_FIELDS
```

Add `sample_site` and `other_org_site` fixtures to `conftest.py` if missing.

- [ ] **Step 2: Failing run**

`pytest tests/unit/test_equipment_registry.py -v` → ImportError.

- [ ] **Step 3: Implement**

`backend/app/services/equipment/registry.py`:

```python
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment, Site
from app.schemas.equipment import EquipmentCreate, EquipmentUpdate
from app.services.core.audit import log_audit
from app.services.equipment.tags import normalize_tags

RESTRICTED_EQUIPMENT_FIELDS = frozenset({
    "manufacturer", "model", "serial_number", "status",
    "install_date", "last_calibration_date", "next_calibration_due",
})


async def _validate_site(db: AsyncSession, org_id: UUID, site_id: UUID) -> Site:
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_REQUIRED"})
    if site.organization_id != org_id:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_CROSS_ORG"})
    if site.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_SITE_ARCHIVED"})
    return site


async def list_equipment(
    db: AsyncSession, org_id: UUID, *,
    site_id: UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    include_archived: bool = False,
) -> list[Equipment]:
    stmt = select(Equipment).where(Equipment.organization_id == org_id)
    if not include_archived:
        stmt = stmt.where(Equipment.archived_at.is_(None))
    if site_id is not None:
        stmt = stmt.where(Equipment.site_id == site_id)
    if status is not None:
        stmt = stmt.where(Equipment.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            Equipment.name.ilike(like),
            Equipment.serial_number.ilike(like),
            Equipment.equipment_type.ilike(like),
        ))
    if tag:
        stmt = stmt.where(Equipment.tags.any(tag))
    stmt = stmt.order_by(Equipment.name)
    return list((await db.execute(stmt)).scalars().all())


async def get_equipment(db: AsyncSession, equipment_id: UUID) -> Equipment:
    eq = await db.get(Equipment, equipment_id)
    if eq is None:
        raise HTTPException(404, detail="Equipment not found")
    return eq


async def create_equipment(
    db: AsyncSession, *, org_id: UUID, payload: EquipmentCreate,
    actor_id: UUID, can_set_restricted: bool,
) -> Equipment:
    """Create a piece of equipment.

    Soft-drop policy (decision 3 in the grill, decision 2 hybrid): any
    benchwork MEMBER can register a piece of equipment, but only a
    SITE_MANAGER on the target site (or ADMIN) can set regulated
    metadata at creation time. For non-authorized callers we silently
    NULL the restricted fields rather than 403 — the user does not need
    to know the role gate exists. `status` is the one exception: it
    falls back to ACTIVE rather than NULL because the column is NOT NULL.

    The endpoint is responsible for computing `can_set_restricted` from
    the caller's grants + role; this service trusts the boolean.
    """
    await _validate_site(db, org_id, payload.site_id)
    data = payload.model_dump()
    data["tags"] = normalize_tags(data.get("tags") or [])
    data["status"] = (
        data["status"].value
        if hasattr(data.get("status"), "value")
        else data.get("status")
    )

    if not can_set_restricted:
        # Silently strip regulated-data assertions. Track which fields the
        # caller tried to set so we can audit-log the soft-drop — useful
        # for catching frontend bugs that forgot to hide a field.
        dropped: dict[str, str] = {}
        for field in RESTRICTED_EQUIPMENT_FIELDS:
            if field == "status":
                if data.get("status") and data["status"] != "ACTIVE":
                    dropped["status"] = data["status"]
                    data["status"] = "ACTIVE"
                continue
            if data.get(field) is not None:
                dropped[field] = str(data[field])
                data[field] = None
    else:
        dropped = {}

    eq = Equipment(organization_id=org_id, created_by_id=actor_id, **data)
    db.add(eq)
    await db.flush()
    changes: dict = {"name": eq.name, "site_id": str(eq.site_id)}
    if dropped:
        changes["_dropped_restricted_fields"] = dropped
    await log_audit(db, actor_id=actor_id, action="CREATE",
                    entity_type="equipment", entity_id=eq.id,
                    changes=changes)
    await db.commit()
    await db.refresh(eq)
    return eq


async def update_equipment(
    db: AsyncSession, eq: Equipment, *, payload: EquipmentUpdate, actor_id: UUID
) -> Equipment:
    touched = payload.model_dump(exclude_unset=True)
    diff: dict[str, list] = {}

    if "site_id" in touched and touched["site_id"] != eq.site_id:
        await _validate_site(db, eq.organization_id, touched["site_id"])

    if "tags" in touched and touched["tags"] is not None:
        touched["tags"] = normalize_tags(touched["tags"])

    if "status" in touched and hasattr(touched["status"], "value"):
        touched["status"] = touched["status"].value

    for field, new_val in touched.items():
        old_val = getattr(eq, field)
        if old_val != new_val:
            diff[field] = [str(old_val) if old_val is not None else None,
                           str(new_val) if new_val is not None else None]
            setattr(eq, field, new_val)

    if diff:
        await log_audit(db, actor_id=actor_id, action="UPDATE",
                        entity_type="equipment", entity_id=eq.id, changes=diff)
    await db.commit()
    await db.refresh(eq)
    return eq


async def archive_equipment(
    db: AsyncSession, eq: Equipment, *, actor_id: UUID
) -> Equipment:
    eq.archived_at = datetime.now(timezone.utc)
    eq.archived_by_id = actor_id
    await log_audit(db, actor_id=actor_id, action="ARCHIVE",
                    entity_type="equipment", entity_id=eq.id, changes={})
    await db.commit()
    await db.refresh(eq)
    return eq
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_equipment_registry.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/equipment/registry.py backend/tests/unit/test_equipment_registry.py
git commit -m "feat(F-0088): equipment/registry — CRUD + restricted field set"
```

---

### Task 13: `services/equipment/attachments.py`

**Files:**
- Create: `backend/app/services/equipment/attachments.py`
- Test: `backend/tests/unit/test_equipment_attachments.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/test_equipment_attachments.py
import io
import pytest
from fastapi import UploadFile

from app.services.equipment.attachments import (
    ALLOWED_MIMES, MAX_BYTES, add_attachment, remove_attachment,
)


def _upload(name: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content),
                      headers={"content-type": content_type})


@pytest.mark.asyncio
async def test_add_attachment_pdf(db_session, sample_equipment, sample_user):
    f = _upload("manual.pdf", "application/pdf", b"%PDF-1.4 hello")
    att = await add_attachment(db_session, sample_equipment, f, actor_id=sample_user.id)
    assert att.mime_type == "application/pdf"
    assert att.size_bytes > 0


@pytest.mark.asyncio
async def test_add_attachment_rejects_exe(db_session, sample_equipment, sample_user):
    f = _upload("bad.exe", "application/x-msdownload", b"MZ\x90\x00")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await add_attachment(db_session, sample_equipment, f, actor_id=sample_user.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_add_attachment_blocked_when_equipment_archived(
    db_session, sample_equipment, sample_user
):
    """Decision 9a in the grill: archived equipment is read-only. The
    attachment list still renders so QA can audit prior calibration
    PDFs, but no new uploads and no deletes."""
    from datetime import datetime, timezone
    from fastapi import HTTPException
    sample_equipment.archived_at = datetime.now(timezone.utc)
    await db_session.commit()
    f = _upload("manual.pdf", "application/pdf", b"%PDF-1.4")
    with pytest.raises(HTTPException) as exc:
        await add_attachment(
            db_session, sample_equipment, f, actor_id=sample_user.id
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_remove_attachment_blocked_when_equipment_archived(
    db_session, sample_equipment, sample_equipment_attachment, sample_user
):
    from datetime import datetime, timezone
    from fastapi import HTTPException
    sample_equipment.archived_at = datetime.now(timezone.utc)
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await remove_attachment(
            db_session, sample_equipment_attachment, actor_id=sample_user.id
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_ARCHIVED"


def test_max_bytes_is_25mb():
    assert MAX_BYTES == 25 * 1024 * 1024


def test_allowed_mimes_includes_pdf_docx_images():
    for m in ["application/pdf",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "image/png", "image/jpeg"]:
        assert m in ALLOWED_MIMES
```

- [ ] **Step 2: Failing run**

`pytest tests/unit/test_equipment_attachments.py -v` → ImportError.

- [ ] **Step 3: Implement**

```python
# backend/app/services/equipment/attachments.py
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment, EquipmentAttachment
from app.services.core.audit import log_audit
from app.services.core.file_storage import FileStorageService

ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_BYTES = 25 * 1024 * 1024


def _assert_writable(equipment: Equipment) -> None:
    """Archived equipment is read-only — list/read still works, writes 400.

    Decision 9a in the grill: archive freezes the audit surface so a
    retired instrument cannot have new calibration PDFs slipped in
    after the fact.
    """
    if equipment.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_ARCHIVED"})


async def add_attachment(
    db: AsyncSession, equipment: Equipment, file: UploadFile, *, actor_id: UUID
) -> EquipmentAttachment:
    _assert_writable(equipment)
    storage = FileStorageService()
    stored = await storage.store_file(
        file,
        base_dir="equipment",
        org_id=equipment.organization_id,
        path_segments=[str(equipment.id)],
        allowed_types=ALLOWED_MIMES,
        max_size_bytes=MAX_BYTES,
    )
    att = EquipmentAttachment(
        equipment_id=equipment.id,
        file_path=stored.relative_path,
        original_filename=stored.original_filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        uploaded_by_id=actor_id,
    )
    db.add(att)
    await db.flush()
    await log_audit(db, actor_id=actor_id, action="CREATE",
                    entity_type="equipment_attachment", entity_id=att.id,
                    changes={"equipment_id": str(equipment.id),
                             "filename": att.original_filename})
    await db.commit()
    await db.refresh(att)
    return att


async def remove_attachment(
    db: AsyncSession, attachment: EquipmentAttachment, *, actor_id: UUID
) -> None:
    equipment = await db.get(Equipment, attachment.equipment_id)
    if equipment is not None:
        _assert_writable(equipment)
    storage = FileStorageService()
    try:
        storage.delete_file(attachment.file_path)
    except Exception:  # noqa: BLE001 — file may already be gone; row delete still proceeds
        pass
    await db.delete(attachment)
    await log_audit(db, actor_id=actor_id, action="DELETE",
                    entity_type="equipment_attachment", entity_id=attachment.id,
                    changes={})
    await db.commit()
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/unit/test_equipment_attachments.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/equipment/attachments.py backend/tests/unit/test_equipment_attachments.py
git commit -m "feat(F-0088): equipment/attachments — upload/delete + MIME/size enforcement"
```

---

## Phase 5 — Endpoints

### Task 14: Wire `ensure_default_site` into org registration

**Files:**
- Modify: `backend/app/api/endpoints/iam.py` (POST `/organizations` handler)
- Test: `backend/tests/integration/test_org_registration_default_site.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_org_registration_default_site.py
import pytest

from app.services.sites.crud import list_sites
from app.services.sites.defaults import DEFAULT_SITE_NAME


@pytest.mark.asyncio
async def test_default_site_created_on_org_create(authed_client, db_session):
    res = await authed_client.post("/iam/organizations", json={"name": "Acme PD"})
    assert res.status_code == 200
    org_id = res.json()["id"]

    sites = await list_sites(db_session, org_id)
    names = [s.name for s in sites]
    assert DEFAULT_SITE_NAME in names
```

- [ ] **Step 2: Failing run**

`pytest tests/integration/test_org_registration_default_site.py -v` → FAIL.

- [ ] **Step 3: Modify the org-create handler**

In `backend/app/api/endpoints/iam.py`, find the `POST /organizations` handler. After the `Organization` row is added and the initial `OrganizationMember` (with role ADMIN) is flushed, add:

```python
from app.services.sites.defaults import ensure_default_site

await ensure_default_site(db, org.id, actor_id=user.id)
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/integration/test_org_registration_default_site.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/iam.py backend/tests/integration/test_org_registration_default_site.py
git commit -m "feat(F-0088): auto-create Default Site on org registration"
```

---

### Task 15: `/sites` router

**Files:**
- Create: `backend/app/api/endpoints/sites.py`
- Modify: `backend/app/api/router.py` (mount)
- Test: `backend/tests/integration/test_sites_api.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_sites_api.py
import pytest


@pytest.mark.asyncio
async def test_list_sites_any_member(authed_member_client):
    res = await authed_member_client.get("/sites")
    assert res.status_code == 200
    assert any(s["name"] == "Default Site" for s in res.json())


@pytest.mark.asyncio
async def test_create_site_member_403(authed_member_client):
    """Decision 5c-ii: CREATE is ADMIN-only — SITE_MANAGER does NOT
    create sites. Adding a building is an org-level decision."""
    res = await authed_member_client.post("/sites", json={"name": "X"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_site_site_manager_403(authed_site_manager_client):
    res = await authed_site_manager_client.post("/sites", json={"name": "X"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_site_admin_ok(authed_admin_client):
    res = await authed_admin_client.post("/sites", json={"name": "South Bay"})
    assert res.status_code == 200
    assert res.json()["name"] == "South Bay"


@pytest.mark.asyncio
async def test_rename_site_by_site_manager_with_grant(
    authed_site_manager_client, managed_site
):
    """Decision 5c-ii: SITE_MANAGER can rename the site they manage."""
    res = await authed_site_manager_client.patch(
        f"/sites/{managed_site.id}", json={"name": "Renamed"}
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_rename_site_by_site_manager_without_grant(
    authed_site_manager_client, unmanaged_site
):
    res = await authed_site_manager_client.patch(
        f"/sites/{unmanaged_site.id}", json={"name": "Nope"}
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_archive_site_member_403(authed_site_manager_client, managed_site):
    """Decision 5c-ii: ARCHIVE is ADMIN-only — even for a site you manage."""
    res = await authed_site_manager_client.request(
        "DELETE", f"/sites/{managed_site.id}",
        json={"default_move_to": "00000000-0000-0000-0000-000000000000",
              "reason": "test"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_archive_site_default_forbidden(authed_admin_client):
    list_res = await authed_admin_client.get("/sites")
    default_id = next(s["id"] for s in list_res.json() if s["is_default"])
    other = (await authed_admin_client.post("/sites", json={"name": "Other"})).json()
    res = await authed_admin_client.request(
        "DELETE", f"/sites/{default_id}",
        json={"default_move_to": other["id"], "reason": "no"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "SITE_ARCHIVE_DEFAULT_FORBIDDEN"


@pytest.mark.asyncio
async def test_archive_site_needs_move_to(authed_admin_client):
    a = (await authed_admin_client.post("/sites", json={"name": "A"})).json()
    res = await authed_admin_client.request("DELETE", f"/sites/{a['id']}", json={})
    assert res.status_code == 422  # Pydantic missing field


@pytest.mark.asyncio
async def test_list_site_managers_admin_only(
    authed_admin_client, authed_member_client, managed_site
):
    """GET /sites/{id}/managers is ADMIN-only (decision 5d-ii: the panel
    where ADMIN grants/revokes lives in /organization)."""
    res = await authed_admin_client.get(f"/sites/{managed_site.id}/managers")
    assert res.status_code == 200

    res = await authed_member_client.get(f"/sites/{managed_site.id}/managers")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_grant_site_manager_admin_only(
    authed_admin_client, authed_member_client, managed_site, sample_user
):
    res = await authed_member_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(sample_user.id)},
    )
    assert res.status_code == 403

    res = await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(sample_user.id)},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_revoke_site_manager_admin_only(
    authed_admin_client, managed_site, sample_user
):
    await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(sample_user.id)},
    )
    res = await authed_admin_client.delete(
        f"/sites/{managed_site.id}/managers/{sample_user.id}"
    )
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_managed_sites_for_user(
    authed_admin_client, managed_site, sample_user
):
    await authed_admin_client.post(
        f"/sites/{managed_site.id}/managers",
        json={"user_id": str(sample_user.id)},
    )
    res = await authed_admin_client.get(
        f"/users/{sample_user.id}/managed-sites"
    )
    assert res.status_code == 200
    assert any(m["site"]["id"] == str(managed_site.id) for m in res.json())
```

- [ ] **Step 2: Failing run**

`pytest tests/integration/test_sites_api.py -v` → 404.

- [ ] **Step 3: Implement `/sites` router**

```python
# backend/app/api/endpoints/sites.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_org_role, require_any_org_role
from app.models.iam import OrgRole
from app.models.user import User
from app.schemas.sites import (
    ManagedSiteResponse,
    SiteArchiveRequest,
    SiteCreate,
    SiteManagerGrantCreate,
    SiteManagerGrantResponse,
    SiteResponse,
    SiteUpdate,
)
from app.services.permissions.equipment import user_can_rename_site
from app.services.sites import crud, grants

router = APIRouter(tags=["sites"])


@router.get("/sites", response_model=list[SiteResponse])
async def list_sites_endpoint(
    include_archived: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await crud.list_sites(db, user.selected_org_id, include_archived=include_archived)


@router.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site_endpoint(
    site_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return site


@router.post("/sites", response_model=SiteResponse)
async def create_site_endpoint(
    payload: SiteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),  # ADMIN only (decision 5c-ii)
):
    return await crud.create_site(db, org_id=user.selected_org_id,
                                  payload=payload, actor_id=user.id)


@router.patch("/sites/{site_id}", response_model=SiteResponse)
async def update_site_endpoint(
    site_id: UUID,
    payload: SiteUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SITE_MANAGER with a grant on this site, or ADMIN. Decision 5c-ii."""
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    if not await user_can_rename_site(
        db, user_id=user.id, org_id=site.organization_id, site_id=site.id
    ):
        raise HTTPException(403)
    return await crud.update_site(db, site, payload=payload, actor_id=user.id)


@router.delete("/sites/{site_id}", response_model=SiteResponse)
async def archive_site_endpoint(
    site_id: UUID,
    body: SiteArchiveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),  # ADMIN only (decision 5c-ii)
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await crud.archive_site(
        db, site,
        default_move_to=body.default_move_to,
        overrides=body.overrides,
        reason=body.reason,
        actor_id=user.id,
    )


# ── Per-site SITE_MANAGER grants ───────────────────────────────────────
# Decision 4 + 5d-ii: ADMIN is the only role that grants and revokes.

@router.get(
    "/sites/{site_id}/managers",
    response_model=list[SiteManagerGrantResponse],
)
async def list_site_managers_endpoint(
    site_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await grants.list_grants_for_site(db, site_id)


@router.post(
    "/sites/{site_id}/managers",
    response_model=SiteManagerGrantResponse,
)
async def grant_site_manager_endpoint(
    site_id: UUID,
    payload: SiteManagerGrantCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await grants.grant_site_manager(
        db, site=site, user_id=payload.user_id, granted_by_id=user.id,
    )


@router.delete(
    "/sites/{site_id}/managers/{user_id}",
    status_code=204,
)
async def revoke_site_manager_endpoint(
    site_id: UUID,
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    site = await crud.get_site(db, site_id)
    if site.organization_id != user.selected_org_id:
        raise HTTPException(404)
    await grants.revoke_site_manager(
        db, site_id=site_id, user_id=user_id, actor_id=user.id
    )
    return Response(status_code=204)


@router.get(
    "/users/{user_id}/managed-sites",
    response_model=list[ManagedSiteResponse],
)
async def list_managed_sites_endpoint(
    user_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_org_role(OrgRole.ADMIN)),
):
    """ADMIN-only because this surfaces another user's grant data. The
    inline `MemberSitesInlinePicker` in MemberRolesPicker (Task 31)
    consumes this when an ADMIN edits a member's roles."""
    rows = await grants.list_managed_sites_for_user(
        db, user_id, include_archived=False
    )
    return [{"grant_id": g.id, "site": g.site} for g in rows]
```

In `backend/app/api/router.py`, mount it:

```python
from app.api.endpoints import sites as sites_router
api_router.include_router(sites_router.router)
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/integration/test_sites_api.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/sites.py backend/app/api/router.py \
        backend/tests/integration/test_sites_api.py
git commit -m "feat(F-0088): /sites router with role gates"
```

---

### Task 16: `/equipment` router

**Files:**
- Create: `backend/app/api/endpoints/equipment.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/integration/test_equipment_api.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/integration/test_equipment_api.py
import pytest


@pytest.mark.asyncio
async def test_create_equipment_any_member(authed_member_client, default_site_id):
    res = await authed_member_client.post("/equipment", json={
        "name": "Balance", "site_id": default_site_id,
    })
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_member_can_edit_open_fields(authed_member_client, member_owned_equipment_id):
    res = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"description": "updated", "tags": ["x"]},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_member_cannot_edit_restricted_field(
    authed_member_client, member_owned_equipment_id
):
    res = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"last_calibration_date": "2026-01-01"},
    )
    assert res.status_code == 403
    body = res.json()
    assert body["detail"]["code"] == "EQUIPMENT_FIELD_RESTRICTED"
    assert body["detail"]["fields"] == ["last_calibration_date"]


@pytest.mark.asyncio
async def test_patch_noop_on_restricted_field_does_not_403(
    authed_member_client, member_owned_equipment_id
):
    """Decision 2 in the grill: value-compare semantics. Sending a
    restricted field whose value equals the existing value is a no-op
    and must not 403 — otherwise round-tripping the GET response back
    into a PATCH (a common frontend pattern) randomly fails for
    non-SITE_MANAGER members."""
    get_res = await authed_member_client.get(f"/equipment/{member_owned_equipment_id}")
    current = get_res.json()
    res = await authed_member_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={
            "description": "updated",
            "manufacturer": current["manufacturer"],
            "model": current["model"],
        },
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_site_manager_with_grant_can_edit_restricted_field(
    authed_site_manager_client, member_owned_equipment_id
):
    """SITE_MANAGER fixture holds a grant on member_owned_equipment_id's site."""
    res = await authed_site_manager_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"last_calibration_date": "2026-01-01"},
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_site_manager_without_grant_for_site_403(
    authed_site_manager_client, equipment_on_unmanaged_site_id
):
    """Decision 4: role bit alone is insufficient. The user must hold a
    grant on THIS equipment's site."""
    res = await authed_site_manager_client.patch(
        f"/equipment/{equipment_on_unmanaged_site_id}",
        json={"last_calibration_date": "2026-01-01"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_move_equipment_requires_grants_on_both_sites(
    authed_site_manager_client, member_owned_equipment_id, unmanaged_site
):
    """Decision 7: caller has grant on the source site but not the
    destination. SITE_MOVE_FORBIDDEN carries missing_grants payload so
    the UI can name which side the user is short on."""
    res = await authed_site_manager_client.patch(
        f"/equipment/{member_owned_equipment_id}",
        json={"site_id": str(unmanaged_site.id)},
    )
    assert res.status_code == 403
    body = res.json()
    assert body["detail"]["code"] == "SITE_MOVE_FORBIDDEN"
    assert str(unmanaged_site.id) in body["detail"]["missing_grants"]


@pytest.mark.asyncio
async def test_archive_equipment_member_403(
    authed_member_client, member_owned_equipment_id
):
    res = await authed_member_client.delete(f"/equipment/{member_owned_equipment_id}")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_attachment_blocked_on_archived_equipment(
    authed_admin_client, archived_equipment_id
):
    """Decision 9a: archived equipment is read-only."""
    import io
    res = await authed_admin_client.post(
        f"/equipment/{archived_equipment_id}/attachments",
        files={"file": ("manual.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "EQUIPMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_tags_endpoint(authed_member_client, default_site_id):
    await authed_member_client.post("/equipment", json={
        "name": "X", "site_id": default_site_id, "tags": ["alpha", "beta"]
    })
    res = await authed_member_client.get("/equipment/tags")
    assert res.status_code == 200
    body = res.json()
    assert "alpha" in body and "beta" in body
```

Fixtures needed: `default_site_id`, `member_owned_equipment_id`, `authed_site_manager_client` — add to `conftest.py` per existing patterns.

- [ ] **Step 2: Failing run**

`pytest tests/integration/test_equipment_api.py -v` → 404.

- [ ] **Step 3: Implement `/equipment` router**

```python
# backend/app/api/endpoints/equipment.py
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_any_org_role
from app.models.iam import OrgRole
from app.models.science import EquipmentAttachment
from app.models.user import User
from app.schemas.equipment import (
    EquipmentAttachmentResponse, EquipmentCreate, EquipmentResponse, EquipmentUpdate,
)
from app.services.equipment import attachments as attachments_svc
from app.services.equipment import registry, tags as tags_svc
from app.services.equipment.registry import RESTRICTED_EQUIPMENT_FIELDS
from app.services.permissions.equipment import (
    user_can_edit_restricted_equipment,
    user_can_move_equipment,
)

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("", response_model=list[EquipmentResponse])
async def list_equipment_endpoint(
    site_id: UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    include_archived: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await registry.list_equipment(
        db, user.selected_org_id,
        site_id=site_id, status=status, q=q, tag=tag,
        include_archived=include_archived,
    )


@router.get("/tags", response_model=list[str])
async def list_tags_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tags_svc.list_distinct_tags(db, user.selected_org_id)


@router.get("/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await registry.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return eq


@router.post("", response_model=EquipmentResponse)
async def create_equipment_endpoint(
    payload: EquipmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Any member can register equipment. Restricted fields supplied by
    non-SITE_MANAGER callers are silently nulled in the service layer
    (decision 2 hybrid: closes the POST backdoor without 403'ing)."""
    can_set_restricted = await user_can_edit_restricted_equipment(
        db, user_id=user.id, org_id=user.selected_org_id,
        site_id=payload.site_id,
    )
    return await registry.create_equipment(
        db, org_id=user.selected_org_id, payload=payload, actor_id=user.id,
        can_set_restricted=can_set_restricted,
    )


@router.patch("/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment_endpoint(
    equipment_id: UUID,
    payload: EquipmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await registry.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    if eq.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_ARCHIVED"})

    touched_raw = payload.model_dump(exclude_unset=True)

    # Decision 2 (grill): value-compare semantics. A field listed in
    # `touched_raw` only counts as a regulated edit if the value
    # *actually changes*. Round-tripping a GET back into a PATCH must
    # not 403 a benchwork member.
    restricted_touched = set(touched_raw.keys()) & RESTRICTED_EQUIPMENT_FIELDS
    actually_changed = {
        f for f in restricted_touched if touched_raw[f] != getattr(eq, f)
    }
    if actually_changed:
        if not await user_can_edit_restricted_equipment(
            db, user_id=user.id, org_id=eq.organization_id, site_id=eq.site_id
        ):
            raise HTTPException(
                403,
                detail={"code": "EQUIPMENT_FIELD_RESTRICTED",
                        "fields": sorted(actually_changed)},
            )

    # Decision 7 (grill): site moves are gated separately. Grants needed
    # on BOTH source and destination (or ADMIN). The payload carries
    # `missing_grants` so the UI can name which side the user is short on.
    if "site_id" in touched_raw and touched_raw["site_id"] != eq.site_id:
        ok, missing = await user_can_move_equipment(
            db, user_id=user.id, org_id=eq.organization_id,
            from_site_id=eq.site_id, to_site_id=touched_raw["site_id"],
        )
        if not ok:
            raise HTTPException(
                403,
                detail={"code": "SITE_MOVE_FORBIDDEN",
                        "missing_grants": [str(s) for s in missing]},
            )

    return await registry.update_equipment(db, eq, payload=payload, actor_id=user.id)


@router.delete("/{equipment_id}", response_model=EquipmentResponse)
async def archive_equipment_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])),
):
    eq = await registry.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await registry.archive_equipment(db, eq, actor_id=user.id)


@router.get("/{equipment_id}/attachments", response_model=list[EquipmentAttachmentResponse])
async def list_attachments_endpoint(
    equipment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eq = await registry.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return eq.attachments


@router.post("/{equipment_id}/attachments", response_model=EquipmentAttachmentResponse)
async def upload_attachment_endpoint(
    equipment_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])),
):
    eq = await registry.get_equipment(db, equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    return await attachments_svc.add_attachment(db, eq, file, actor_id=user.id)


@router.delete("/attachments/{attachment_id}")
async def delete_attachment_endpoint(
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_any_org_role([OrgRole.SITE_MANAGER, OrgRole.ADMIN])),
):
    att = await db.get(EquipmentAttachment, attachment_id)
    if att is None:
        raise HTTPException(404)
    eq = await registry.get_equipment(db, att.equipment_id)
    if eq.organization_id != user.selected_org_id:
        raise HTTPException(404)
    await attachments_svc.remove_attachment(db, att, actor_id=user.id)
    return {"deleted": True}
```

Mount in `backend/app/api/router.py`:

```python
from app.api.endpoints import equipment as equipment_router
api_router.include_router(equipment_router.router)
```

- [ ] **Step 4: Run tests — expect PASS**

`pytest tests/integration/test_equipment_api.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/equipment.py backend/app/api/router.py \
        backend/tests/integration/test_equipment_api.py
git commit -m "feat(F-0088): /equipment router with field-level permission gate + attachments"
```

---

### Task 17: Delete legacy `/iam/...` equipment routes

**Files:**
- Modify: `backend/app/api/endpoints/iam.py` (lines around 1005–1135)

- [ ] **Step 1: Search for callers in backend**

```bash
cd backend && grep -rn "/iam/organizations/.*equipment\|/iam/equipment" app tests
```

Expected: no remaining backend callers (frontend callers are migrated in Phase 9).

- [ ] **Step 2: Remove the legacy endpoint handlers**

Open `backend/app/api/endpoints/iam.py`, find the `@router.get("/organizations/{org_id}/equipment")`, `POST`, `PUT`, `DELETE`, and `GET /equipment/{id}` handlers (roughly lines 1005–1135 per the spec). Delete them along with any local helpers no longer referenced.

- [ ] **Step 3: Run the full backend suite**

`cd backend && pytest -x`

Fix any tests that referenced the deleted URLs by switching them to `/equipment`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/endpoints/iam.py backend/tests
git commit -m "refactor(F-0088): remove legacy /iam/.../equipment routes"
```

---

## Phase 6 — Frontend schemas & permission affordance

### Task 18: Zod schemas

**Files:**
- Create: `frontend/src/lib/schemas/sites.ts`
- Modify: `frontend/src/lib/schemas/science.ts`
- Modify: `frontend/src/lib/schemas/index.ts`

- [ ] **Step 1: Create `sites.ts`**

```typescript
// frontend/src/lib/schemas/sites.ts
import { z } from 'zod';

export const SiteSchema = z.object({
    id: z.string(),
    organization_id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    archived_at: z.string().nullable().optional(),
    archived_by_id: z.string().nullable().optional(),
    archive_reason: z.string().nullable().optional(),
    created_by_id: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();
export type Site = z.infer<typeof SiteSchema>;

export const SiteListSchema = z.array(SiteSchema);

export const SiteCreateSchema = z.object({
    name: z.string().min(1).max(120),
    description: z.string().max(500).optional(),
});
export type SiteCreate = z.infer<typeof SiteCreateSchema>;

export const SiteUpdateSchema = SiteCreateSchema.partial();
export type SiteUpdate = z.infer<typeof SiteUpdateSchema>;

export const SiteArchiveRequestSchema = z.object({
    default_move_to: z.string(),
    overrides: z.record(z.string(), z.string()).default({}),
    reason: z.string().min(1).max(1000),
});
export type SiteArchiveRequest = z.infer<typeof SiteArchiveRequestSchema>;
```

- [ ] **Step 2: Extend `science.ts::EquipmentSchema`**

In `frontend/src/lib/schemas/science.ts`, replace `EquipmentSchema` with:

```typescript
export const EquipmentStatusSchema = z.enum(['ACTIVE', 'MAINTENANCE', 'RETIRED']);
export type EquipmentStatus = z.infer<typeof EquipmentStatusSchema>;

export const EquipmentSchema = z.object({
    id: z.string(),
    organization_id: z.string(),
    site_id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    equipment_type: z.string().nullable().optional(),
    location: z.string().nullable().optional(),
    room: z.string().nullable().optional(),
    tags: z.array(z.string()).default([]),
    manufacturer: z.string().nullable().optional(),
    model: z.string().nullable().optional(),
    serial_number: z.string().nullable().optional(),
    status: EquipmentStatusSchema,
    install_date: z.string().nullable().optional(),
    last_calibration_date: z.string().nullable().optional(),
    next_calibration_due: z.string().nullable().optional(),
    archived_at: z.string().nullable().optional(),
    archived_by_id: z.string().nullable().optional(),
    created_by_id: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();
export type Equipment = z.infer<typeof EquipmentSchema>;

export const EquipmentListSchema = z.array(EquipmentSchema);

export const EquipmentCreateSchema = z.object({
    name: z.string().min(1).max(255),
    site_id: z.string(),
    description: z.string().optional(),
    equipment_type: z.string().max(120).optional(),
    location: z.string().max(255).optional(),
    room: z.string().max(120).optional(),
    tags: z.array(z.string()).default([]),
    manufacturer: z.string().max(120).optional(),
    model: z.string().max(120).optional(),
    serial_number: z.string().max(120).optional(),
    status: EquipmentStatusSchema.default('ACTIVE'),
    install_date: z.string().optional(),
    last_calibration_date: z.string().optional(),
    next_calibration_due: z.string().optional(),
});
export type EquipmentCreate = z.infer<typeof EquipmentCreateSchema>;

export const EquipmentUpdateSchema = EquipmentCreateSchema.partial();
export type EquipmentUpdate = z.infer<typeof EquipmentUpdateSchema>;

export const EquipmentAttachmentSchema = z.object({
    id: z.string(),
    equipment_id: z.string(),
    original_filename: z.string(),
    mime_type: z.string(),
    size_bytes: z.number(),
    uploaded_by_id: z.string(),
    created_at: z.string(),
}).passthrough();
export type EquipmentAttachment = z.infer<typeof EquipmentAttachmentSchema>;

export const EquipmentAttachmentListSchema = z.array(EquipmentAttachmentSchema);
```

- [ ] **Step 3: Add the barrel re-export**

In `frontend/src/lib/schemas/index.ts`:

```typescript
export * from './sites';
```

- [ ] **Step 4: Type-check**

`cd frontend && npm run check`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schemas/sites.ts frontend/src/lib/schemas/science.ts \
        frontend/src/lib/schemas/index.ts
git commit -m "feat(F-0088): zod schemas for Site + extended Equipment"
```

---

### Task 19: `canManageEquipmentLifecycle` permission helper

Decision 4 in the grill: the role bit on `OrganizationMember.roles` is
*capability*, the grant table is *authorization*. Both are required to
edit regulated metadata, and the helper signature reflects that — it
takes a `siteId` argument. ADMIN bypasses both checks.

A simple "user has SITE_MANAGER role somewhere?" derived is also
exposed, but it must NOT be used to enable buttons on equipment rows
— only to decide whether the UI shows site-management surfaces at all
(e.g. the inline picker in MemberRolesPicker).

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts`
- Create: `frontend/src/lib/permissions/equipment.ts`
- Test: `frontend/src/lib/permissions/equipment.test.ts`

- [ ] **Step 1: Failing test**

```typescript
// frontend/src/lib/permissions/equipment.test.ts
import { describe, expect, it } from 'vitest';
import { canManageEquipmentLifecycle } from './equipment';

const SITE_A = 'aaaaaaaa-0000-0000-0000-000000000001';
const SITE_B = 'bbbbbbbb-0000-0000-0000-000000000002';

describe('canManageEquipmentLifecycle', () => {
    it('admin bypasses grant check', () => {
        expect(
            canManageEquipmentLifecycle({
                roles: ['ADMIN'],
                managedSiteIds: [],
                siteId: SITE_A,
            }),
        ).toBe(true);
    });

    it('site_manager with grant on this site returns true', () => {
        expect(
            canManageEquipmentLifecycle({
                roles: ['MEMBER', 'SITE_MANAGER'],
                managedSiteIds: [SITE_A],
                siteId: SITE_A,
            }),
        ).toBe(true);
    });

    it('site_manager without grant on this site returns false', () => {
        expect(
            canManageEquipmentLifecycle({
                roles: ['MEMBER', 'SITE_MANAGER'],
                managedSiteIds: [SITE_B],
                siteId: SITE_A,
            }),
        ).toBe(false);
    });

    it('member without site_manager bit returns false', () => {
        expect(
            canManageEquipmentLifecycle({
                roles: ['MEMBER'],
                managedSiteIds: [SITE_A],  // shouldn't happen, but defend
                siteId: SITE_A,
            }),
        ).toBe(false);
    });
});
```

- [ ] **Step 2: Run test — expect FAIL (module missing)**

`cd frontend && npm run test -- permissions/equipment` → FAIL.

- [ ] **Step 3: Implement**

`frontend/src/lib/permissions/equipment.ts`:

```typescript
type OrgRole = 'ADMIN' | 'BILLING' | 'MEMBER' | 'PROTOCOL_APPROVER' | 'SITE_MANAGER';

interface CanManageInput {
    roles: OrgRole[];
    managedSiteIds: string[];
    siteId: string;
}

export function canManageEquipmentLifecycle(input: CanManageInput): boolean {
    if (input.roles.includes('ADMIN')) return true;
    if (!input.roles.includes('SITE_MANAGER')) return false;
    return input.managedSiteIds.includes(input.siteId);
}

interface CanMoveInput {
    roles: OrgRole[];
    managedSiteIds: string[];
    fromSiteId: string;
    toSiteId: string;
}

export function canMoveEquipment(input: CanMoveInput): boolean {
    if (input.roles.includes('ADMIN')) return true;
    if (!input.roles.includes('SITE_MANAGER')) return false;
    return (
        input.managedSiteIds.includes(input.fromSiteId)
        && input.managedSiteIds.includes(input.toSiteId)
    );
}
```

- [ ] **Step 4: Wire managedSiteIds into the auth store**

In `frontend/src/lib/auth.svelte.ts`, add a `managedSiteIds: string[]`
field on the auth state and a `canManageSite(siteId: string): boolean`
helper that calls `canManageEquipmentLifecycle` with the current roles.
Populate `managedSiteIds` from `GET /users/me/managed-sites` (add a
self-scoped route, or — for now — load it on org switch). Cache it on
the store; refresh it after the user accepts a grant or after an
ADMIN edits their roles.

```typescript
// inside auth.svelte.ts state
managedSiteIds: $state<string[]>([]);

export async function refreshManagedSites() {
    const res = await api.get<ManagedSiteResponse[]>(`/users/${currentUserId}/managed-sites`);
    auth.managedSiteIds = res.map((m) => m.site.id);
}

export function canManageSite(siteId: string): boolean {
    return canManageEquipmentLifecycle({
        roles: auth.currentOrgRoles,
        managedSiteIds: auth.managedSiteIds,
        siteId,
    });
}
```

Note: `/users/me/managed-sites` requires a small backend change — the
Task 15 endpoint is ADMIN-only by user_id; add a `/users/me/managed-sites`
alias that allows the calling user to read their own grants.

- [ ] **Step 5: Type-check and run**

```bash
cd frontend && npm run check && npm run test -- permissions/equipment
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts frontend/src/lib/permissions/equipment.ts \
        frontend/src/lib/permissions/equipment.test.ts
git commit -m "feat(F-0088): canManageEquipmentLifecycle — role bit + per-site grant"
```

---

## Phase 7 — Frontend components

### Task 20: `SitePicker.svelte`

**Files:**
- Create: `frontend/src/lib/components/sites/SitePicker.svelte`
- Test: `frontend/src/lib/components/sites/SitePicker.test.ts`

- [ ] **Step 1: Failing test**

```typescript
// frontend/src/lib/components/sites/SitePicker.test.ts
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SitePicker from './SitePicker.svelte';

const sites = [
    { id: 'd', name: 'Default Site', archived_at: null },
    { id: 'a', name: 'Alpha', archived_at: null },
    { id: 'arch', name: 'Old', archived_at: '2026-01-01' },
];

describe('SitePicker', () => {
    it('renders only active sites by default', () => {
        const { getByText, queryByText } = render(SitePicker, {
            props: { sites, value: 'd', onChange: vi.fn() },
        });
        expect(getByText('Default Site')).toBeTruthy();
        expect(getByText('Alpha')).toBeTruthy();
        expect(queryByText('Old')).toBeNull();
    });

    it('emits onChange', async () => {
        const onChange = vi.fn();
        const { getByRole } = render(SitePicker, { props: { sites, value: 'd', onChange } });
        await fireEvent.change(getByRole('combobox'), { target: { value: 'a' } });
        expect(onChange).toHaveBeenCalledWith('a');
    });
});
```

- [ ] **Step 2: Run test — expect FAIL**

`cd frontend && npm run test -- SitePicker` → FAIL.

- [ ] **Step 3: Implement**

```svelte
<!-- frontend/src/lib/components/sites/SitePicker.svelte -->
<script lang="ts">
    import type { Site } from '$lib/schemas/sites';

    interface Props {
        sites: Site[];
        value: string | null;
        onChange: (id: string) => void;
        disabled?: boolean;
        excludeId?: string | null;
        includeArchived?: boolean;
    }

    let {
        sites, value, onChange,
        disabled = false, excludeId = null, includeArchived = false,
    }: Props = $props();

    const visible = $derived(
        sites
            .filter((s) => includeArchived || !s.archived_at)
            .filter((s) => !excludeId || s.id !== excludeId)
            .sort((a, b) => a.name.localeCompare(b.name)),
    );
</script>

<select
    role="combobox"
    class="ui-input"
    value={value ?? ''}
    {disabled}
    onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
>
    {#each visible as s (s.id)}
        <option value={s.id}>{s.name}</option>
    {/each}
</select>
```

- [ ] **Step 4: Run test — expect PASS**

`cd frontend && npm run test -- SitePicker` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/sites/SitePicker.svelte frontend/src/lib/components/sites/SitePicker.test.ts
git commit -m "feat(F-0088): SitePicker component"
```

---

### Task 21: `TagsInput.svelte`

**Files:**
- Create: `frontend/src/lib/components/equipment/TagsInput.svelte`
- Test: `frontend/src/lib/components/equipment/TagsInput.test.ts`

- [ ] **Step 1: Failing test**

```typescript
// frontend/src/lib/components/equipment/TagsInput.test.ts
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import TagsInput from './TagsInput.svelte';

describe('TagsInput', () => {
    it('emits onChange with normalized tag on Enter', async () => {
        const onChange = vi.fn();
        const { getByPlaceholderText } = render(TagsInput, {
            props: { value: [], suggestions: [], onChange },
        });
        const input = getByPlaceholderText(/add tag/i);
        await fireEvent.input(input, { target: { value: 'GLP / QC' } });
        await fireEvent.keyDown(input, { key: 'Enter' });
        expect(onChange).toHaveBeenCalledWith(['glp-qc']);
    });

    it('removes a tag', async () => {
        const onChange = vi.fn();
        const { getByLabelText } = render(TagsInput, {
            props: { value: ['glp'], suggestions: [], onChange },
        });
        await fireEvent.click(getByLabelText(/remove glp/i));
        expect(onChange).toHaveBeenCalledWith([]);
    });
});
```

- [ ] **Step 2: Failing run**

`cd frontend && npm run test -- TagsInput` → FAIL.

- [ ] **Step 3: Implement**

```svelte
<!-- frontend/src/lib/components/equipment/TagsInput.svelte -->
<script lang="ts">
    interface Props {
        value: string[];
        suggestions: string[];
        onChange: (next: string[]) => void;
        placeholder?: string;
    }

    let { value, suggestions, onChange, placeholder = 'Add tag…' }: Props = $props();
    let draft = $state('');

    function normalize(raw: string): string {
        return raw.trim().toLowerCase()
            .replace(/\s+/g, '-')
            .replace(/[^a-z0-9-]+/g, '-')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '')
            .slice(0, 40);
    }

    function commit() {
        const n = normalize(draft);
        if (!n || value.includes(n) || value.length >= 20) {
            draft = '';
            return;
        }
        onChange([...value, n]);
        draft = '';
    }

    function remove(tag: string) {
        onChange(value.filter((t) => t !== tag));
    }

    const matchingSuggestions = $derived(
        draft.length === 0
            ? []
            : suggestions.filter((s) => s.includes(normalize(draft)) && !value.includes(s)).slice(0, 6)
    );
</script>

<div class="tags-input">
    <div class="tags-chips">
        {#each value as t (t)}
            <span class="tag-chip">
                {t}
                <button type="button" aria-label="Remove {t}" onclick={() => remove(t)}>×</button>
            </span>
        {/each}
        <input
            class="tag-draft"
            type="text"
            bind:value={draft}
            {placeholder}
            onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
            onblur={() => { if (draft) commit(); }}
        />
    </div>
    {#if matchingSuggestions.length > 0}
        <ul class="tags-suggestions">
            {#each matchingSuggestions as s (s)}
                <li><button type="button" onclick={() => { draft = s; commit(); }}>{s}</button></li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .tags-input { position: relative; }
    .tags-chips { display: flex; flex-wrap: wrap; gap: .3rem; padding: .4rem; border: 1px solid hsl(var(--border)); border-radius: var(--radius-md); background: white; }
    .tag-chip { display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .5rem; background: hsl(205 25% 95%); border: 1px solid hsl(var(--border)); border-radius: 9999px; font-size: .75rem; }
    .tag-chip button { color: hsl(var(--muted-foreground)); cursor: pointer; background: none; border: 0; }
    .tag-draft { flex: 1; min-width: 6rem; border: 0; outline: none; background: transparent; font-size: .875rem; }
    .tags-suggestions { position: absolute; top: 100%; left: 0; right: 0; margin-top: .25rem; background: white; border: 1px solid hsl(var(--border)); border-radius: var(--radius-md); padding: .25rem 0; z-index: 10; }
    .tags-suggestions li button { width: 100%; text-align: left; padding: .35rem .75rem; background: none; border: 0; cursor: pointer; }
    .tags-suggestions li button:hover { background: hsl(205 25% 96%); }
</style>
```

- [ ] **Step 4: Run test — expect PASS**

`cd frontend && npm run test -- TagsInput` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/equipment/TagsInput.svelte frontend/src/lib/components/equipment/TagsInput.test.ts
git commit -m "feat(F-0088): TagsInput with type-ahead + normalization preview"
```

---

### Task 22: `SiteList.svelte`

**Files:**
- Create: `frontend/src/lib/components/sites/SiteList.svelte`
- Test: `frontend/src/lib/components/sites/SiteList.test.ts`

- [ ] **Step 1: Failing test**

```typescript
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteList from './SiteList.svelte';

const sites = [
    { id: 'd', name: 'Default Site', archived_at: null, equipment_count: 5 },
    { id: 'a', name: 'Alpha', archived_at: null, equipment_count: 2 },
];

describe('SiteList', () => {
    it('renders sites and highlights active', () => {
        const { getByText } = render(SiteList, {
            props: { sites, activeId: 'd', canEdit: false, onSelect: vi.fn(), onAdd: vi.fn() },
        });
        const active = getByText('Default Site').closest('.site-rail-item');
        expect(active?.classList.contains('active')).toBe(true);
    });

    it('hides + New button when canEdit=false', () => {
        const { queryByText } = render(SiteList, {
            props: { sites, activeId: 'd', canEdit: false, onSelect: vi.fn(), onAdd: vi.fn() },
        });
        expect(queryByText(/\+ New/i)).toBeNull();
    });
});
```

- [ ] **Step 2: Failing run**

`cd frontend && npm run test -- SiteList` → FAIL.

- [ ] **Step 3: Implement**

```svelte
<!-- frontend/src/lib/components/sites/SiteList.svelte -->
<script lang="ts">
    import type { Site } from '$lib/schemas/sites';

    interface Props {
        sites: (Site & { equipment_count?: number })[];
        activeId: string | null;
        canEdit: boolean;
        onSelect: (id: string) => void;
        onAdd: () => void;
    }

    let { sites, activeId, canEdit, onSelect, onAdd }: Props = $props();
</script>

<aside class="site-rail">
    <header>
        <span class="ui-label">Sites</span>
        {#if canEdit}
            <button class="btn btn-ghost btn-sm cursor-pointer transition-all duration-150" onclick={onAdd}>+ New</button>
        {/if}
    </header>
    <ul>
        {#each sites as s (s.id)}
            <li
                role="button"
                tabindex="0"
                class="site-rail-item cursor-pointer transition-all duration-150"
                class:active={s.id === activeId}
                onclick={() => onSelect(s.id)}
                onkeydown={(e) => { if (e.key === 'Enter') onSelect(s.id); }}
            >
                <span class="site-rail-pin"></span>
                <div class="flex-1">
                    <div class="site-name">{s.name}</div>
                    <div class="ui-hint">{s.equipment_count ?? 0} equipment{s.archived_at ? ' · archived' : ''}</div>
                </div>
            </li>
        {/each}
    </ul>
</aside>

<style>
    /* Mirrors lab-glass mockup; rely on global utility classes for chrome. */
    .site-rail { border-right: 1px solid hsl(var(--border)); background: hsl(205 25% 98%); }
    .site-rail header { display: flex; align-items: center; justify-content: space-between; padding: .8rem 1rem; border-bottom: 1px solid hsl(var(--border)); }
    .site-rail ul { list-style: none; padding: .5rem; margin: 0; }
    .site-rail-item { display: flex; align-items: center; gap: .65rem; padding: .6rem .85rem; border-radius: .5rem; }
    .site-rail-item:hover { background: hsl(var(--muted)); }
    .site-rail-item.active { background: hsl(195 85% 22% / 0.08); }
    .site-rail-item.active .site-name { color: hsl(var(--primary)); font-weight: 600; }
    .site-rail-pin { width: .5rem; height: .5rem; border-radius: 9999px; background: hsl(var(--border)); }
    .site-rail-item.active .site-rail-pin { background: hsl(var(--primary)); }
</style>
```

- [ ] **Step 4: PASS**

`cd frontend && npm run test -- SiteList` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/sites/SiteList.svelte frontend/src/lib/components/sites/SiteList.test.ts
git commit -m "feat(F-0088): SiteList rail component"
```

---

### Task 23: `SiteFormDialog.svelte`

**Files:**
- Create: `frontend/src/lib/components/sites/SiteFormDialog.svelte`

- [ ] **Step 1: Implement** — dialog with Name + Description fields; calls `onSubmit(payload)` after `validate(SiteCreateSchema, …)`.

Structure: shadcn `Dialog.Root` + `Dialog.Content`; two `<Input>` fields; primary "Save" / outline "Cancel" buttons. Use `validate` from `$lib/validation`.

```svelte
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { SiteCreateSchema, type SiteCreate, type Site } from '$lib/schemas/sites';
    import { validate, firstError } from '$lib/validation';

    interface Props {
        open: boolean;
        initial?: Site | null;
        onClose: () => void;
        onSubmit: (payload: SiteCreate) => Promise<void>;
    }

    let { open, initial = null, onClose, onSubmit }: Props = $props();
    let name = $state(initial?.name ?? '');
    let description = $state(initial?.description ?? '');
    let saving = $state(false);
    let errors = $state<Record<string, string[]>>({});

    $effect(() => {
        if (open) {
            name = initial?.name ?? '';
            description = initial?.description ?? '';
            errors = {};
        }
    });

    async function submit() {
        const result = validate(SiteCreateSchema, { name, description: description || undefined });
        if (!result.success) { errors = result.errors; return; }
        saving = true;
        try {
            await onSubmit(result.data);
            onClose();
        } finally { saving = false; }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header><Dialog.Title>{initial ? 'Edit site' : 'New site'}</Dialog.Title></Dialog.Header>
        <div class="space-y-3 py-2">
            <div>
                <label class="ui-label">Name</label>
                <Input bind:value={name} placeholder="e.g. South Bay HQ" />
                {#if firstError(errors, 'name')}<p class="text-xs text-destructive">{firstError(errors, 'name')}</p>{/if}
            </div>
            <div>
                <label class="ui-label">Description</label>
                <Input bind:value={description} placeholder="optional" />
            </div>
        </div>
        <Dialog.Footer>
            <Button variant="outline" onclick={onClose}>Cancel</Button>
            <Button onclick={submit} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/components/sites/SiteFormDialog.svelte
git commit -m "feat(F-0088): SiteFormDialog (add/edit)"
```

---

### Task 24: `SiteArchiveStepper.svelte`

**Files:**
- Create: `frontend/src/lib/components/sites/SiteArchiveStepper.svelte`

- [ ] **Step 1: Implement**

```svelte
<!-- frontend/src/lib/components/sites/SiteArchiveStepper.svelte -->
<script lang="ts">
    type StepNum = 1 | 2 | 3;
    interface Props {
        currentStep: StepNum;
        highestVisited: StepNum;
        onJump: (step: StepNum) => void;
    }

    let { currentStep, highestVisited, onJump }: Props = $props();
    const steps = [
        { n: 1 as const, label: 'Destination' },
        { n: 2 as const, label: 'Review moves' },
        { n: 3 as const, label: 'Confirm & archive' },
    ];
</script>

<nav class="stepper" aria-label="Archive site steps">
    {#each steps as s, i (s.n)}
        <button
            type="button"
            class="step-pill cursor-pointer transition-all duration-150"
            class:active={s.n === currentStep}
            class:visited={s.n < currentStep}
            disabled={s.n > highestVisited}
            onclick={() => { if (s.n <= highestVisited) onJump(s.n); }}
        >
            <span class="step-num">{s.n < currentStep ? '✓' : s.n}</span>
            <span class="step-label">{s.label}</span>
        </button>
        {#if i < steps.length - 1}
            <span class="step-sep" aria-hidden="true">›</span>
        {/if}
    {/each}
</nav>

<style>
    .stepper { display: flex; align-items: center; gap: .25rem; font-size: .875rem; }
    .step-pill { display: inline-flex; align-items: center; gap: .5rem; padding: .375rem .75rem; border-radius: .375rem; color: hsl(215 15% 50%); border: 1px solid transparent; background: transparent; }
    .step-pill:hover:not(:disabled) { background: hsl(var(--muted)); }
    .step-pill:disabled { opacity: .4; cursor: not-allowed; }
    .step-pill.visited { color: hsl(215 25% 27%); }
    .step-pill.active { background: hsl(195 85% 22% / .08); border-color: hsl(195 85% 22% / .30); color: hsl(var(--primary)); }
    .step-num { display: inline-flex; align-items: center; justify-content: center; width: 1.25rem; height: 1.25rem; border-radius: 9999px; background: hsl(205 22% 87%); color: hsl(215 25% 35%); font-size: .75rem; font-weight: 600; }
    .step-pill.active .step-num { background: hsl(var(--primary)); color: white; }
    .step-pill.visited:not(.active) .step-num { background: hsl(var(--accent)); color: white; }
    .step-sep { color: hsl(205 22% 75%); padding: 0 .125rem; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/components/sites/SiteArchiveStepper.svelte
git commit -m "feat(F-0088): SiteArchiveStepper chrome (lab-glass-toned)"
```

---

### Task 25: `SiteArchiveWizardModal.svelte`

**Files:**
- Create: `frontend/src/lib/components/sites/SiteArchiveWizardModal.svelte`
- Test: `frontend/src/lib/components/sites/SiteArchiveWizardModal.test.ts`

This is one larger component but cohesive — 3 steps in one file (mirrors `RunCreatorWizardModal` keeping all step state local).

- [ ] **Step 1: Failing test**

```typescript
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteArchiveWizardModal from './SiteArchiveWizardModal.svelte';

const site = { id: 'src', name: 'Old Lab', archived_at: null };
const otherSites = [
    { id: 'dst-a', name: 'Lab A', archived_at: null },
    { id: 'dst-b', name: 'Lab B', archived_at: null },
];
const equipment = [
    { id: 'e1', name: 'Bioreactor', site_id: 'src', room: 'Lab A' },
    { id: 'e2', name: 'Cytometer', site_id: 'src', room: 'Lab A' },
];

describe('SiteArchiveWizardModal', () => {
    it('starts on step 1; next is disabled until destination is picked', async () => {
        const { getByText } = render(SiteArchiveWizardModal, {
            props: {
                open: true, site, otherSites, equipment,
                onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        expect(getByText(/Step 1/i)).toBeTruthy();
    });

    it('submits payload with reason and per-item overrides', async () => {
        const onSubmit = vi.fn().mockResolvedValue(undefined);
        const { getByText, getByPlaceholderText } = render(SiteArchiveWizardModal, {
            props: {
                open: true, site, otherSites, equipment,
                onClose: vi.fn(), onSubmit,
            },
        });
        // Step 1 → 2
        await fireEvent.click(getByText(/Next: Review/i));
        // Step 2 → 3
        await fireEvent.click(getByText(/Next: Confirm/i));
        await fireEvent.input(getByPlaceholderText(/Hayward lease|reason/i),
            { target: { value: 'consolidate' } });
        await fireEvent.click(getByText(/Archive site/i));
        expect(onSubmit).toHaveBeenCalled();
        const payload = onSubmit.mock.calls[0][0];
        expect(payload.reason).toBe('consolidate');
        expect(payload.default_move_to).toBe('dst-a');  // first other
    });
});
```

- [ ] **Step 2: Failing run**

`cd frontend && npm run test -- SiteArchiveWizardModal` → FAIL.

- [ ] **Step 3: Implement (steps 1 + 2 + 3 in one component)**

```svelte
<!-- frontend/src/lib/components/sites/SiteArchiveWizardModal.svelte -->
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import SitePicker from './SitePicker.svelte';
    import SiteArchiveStepper from './SiteArchiveStepper.svelte';
    import type { Site, SiteArchiveRequest } from '$lib/schemas/sites';
    import type { Equipment } from '$lib/schemas/science';

    interface Props {
        open: boolean;
        site: Site;
        otherSites: Site[];          // candidate destinations (already filtered: same org, not archived, not `site` itself)
        equipment: Equipment[];      // equipment currently under `site`
        onClose: () => void;
        onSubmit: (payload: SiteArchiveRequest) => Promise<void>;
    }

    let { open, site, otherSites, equipment, onClose, onSubmit }: Props = $props();

    type StepNum = 1 | 2 | 3;
    let step = $state<StepNum>(1);
    let highest = $state<StepNum>(1);

    let defaultTo = $state<string>(otherSites[0]?.id ?? '');
    let overrides = $state<Record<string, string>>({});  // equipment_id → site_id
    let filter = $state('');
    let reason = $state('');
    let ack = $state(false);
    let submitting = $state(false);

    function jump(n: StepNum) { step = n; }
    function next() { step = (step + 1) as StepNum; highest = (Math.max(highest, step) as StepNum); }
    function back() { step = (step - 1) as StepNum; }

    const filtered = $derived(equipment.filter((e) =>
        !filter || e.name.toLowerCase().includes(filter.toLowerCase())
                || (e.room ?? '').toLowerCase().includes(filter.toLowerCase())
    ));

    const overrideCount = $derived(Object.keys(overrides).length);
    const countsByDest = $derived.by(() => {
        const out: Record<string, number> = {};
        for (const e of equipment) {
            const dest = overrides[e.id] ?? defaultTo;
            out[dest] = (out[dest] ?? 0) + 1;
        }
        return out;
    });

    function siteName(id: string): string {
        return otherSites.find((s) => s.id === id)?.name ?? id;
    }

    async function submit() {
        if (!ack || !reason.trim()) return;
        submitting = true;
        try {
            await onSubmit({ default_move_to: defaultTo, overrides, reason });
            onClose();
        } finally { submitting = false; }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-3xl p-0">
        <header class="px-6 py-4 border-b border-border">
            <h3 class="text-base font-semibold">Archive site</h3>
            <p class="text-xs text-muted-foreground">
                <strong>{site.name}</strong> · {equipment.length} equipment
            </p>
        </header>

        <div class="px-6 py-3 border-b border-border bg-muted/50">
            <SiteArchiveStepper currentStep={step} highestVisited={highest} onJump={jump} />
        </div>

        {#if step === 1}
            <div class="px-6 py-5 space-y-4">
                <div class="anno anno-warn"><strong>{equipment.length}</strong> pieces of equipment will move. Override per-item in step 2 if needed.</div>
                <div>
                    <label class="ui-label">Default destination site</label>
                    <SitePicker sites={otherSites} value={defaultTo} onChange={(v) => defaultTo = v} />
                </div>
            </div>
        {:else if step === 2}
            <div class="px-6 py-4 space-y-3">
                <div class="flex items-center justify-between">
                    <p class="text-sm">Default: <strong>{siteName(defaultTo)}</strong></p>
                    <input class="ui-input max-w-xs" placeholder="Filter by name or room…" bind:value={filter} />
                </div>
                <div class="ui-card max-h-60 overflow-auto">
                    {#each filtered as e (e.id)}
                        <div class="move-row">
                            <div>
                                <div class="text-sm font-medium">{e.name}</div>
                                <div class="text-xs text-muted-foreground">{e.room ?? '—'}{e.location ? ' · ' + e.location : ''}</div>
                            </div>
                            <SitePicker
                                sites={otherSites}
                                value={overrides[e.id] ?? defaultTo}
                                onChange={(v) => {
                                    if (v === defaultTo) { const { [e.id]: _, ...rest } = overrides; overrides = rest; }
                                    else overrides = { ...overrides, [e.id]: v };
                                }}
                            />
                            <span class="badge badge-soft-{overrides[e.id] ? 'primary' : 'muted'}">
                                {overrides[e.id] ? 'overridden' : 'default'}
                            </span>
                        </div>
                    {/each}
                </div>
                <p class="text-xs text-muted-foreground">{overrideCount} override(s) · {equipment.length - overrideCount} follow default</p>
            </div>
        {:else}
            <div class="px-6 py-5 space-y-4">
                <div class="grid grid-cols-2 gap-3">
                    <div class="ui-card p-3 bg-muted/50">
                        <div class="ui-label mb-1">Moves per destination</div>
                        <ul class="text-sm space-y-1">
                            {#each Object.entries(countsByDest) as [id, count]}
                                <li class="flex justify-between"><span>→ {siteName(id)}</span><span class="mono">{count}</span></li>
                            {/each}
                        </ul>
                    </div>
                    <div class="ui-card p-3 bg-muted/50">
                        <div class="ui-label mb-1">Side effects</div>
                        <ul class="text-xs space-y-1 text-muted-foreground">
                            <li>· Rooms &amp; bench notes preserved</li>
                            <li>· Site hidden from pickers</li>
                            <li>· Past runs keep their site reference</li>
                            <li>· Audit entry per item</li>
                        </ul>
                    </div>
                </div>
                <div>
                    <label class="ui-label">Reason <span class="text-destructive">*</span></label>
                    <input class="ui-input" bind:value={reason}
                           placeholder="e.g. Hayward lease ended 2026-05-15 — consolidate to HQ" />
                </div>
                <label class="flex items-start gap-2 text-sm">
                    <input type="checkbox" bind:checked={ack} class="mt-1" />
                    <span>I understand this site will no longer accept new equipment. Past runs that reference it remain intact.</span>
                </label>
            </div>
        {/if}

        <footer class="px-6 py-3 border-t border-border flex items-center justify-between bg-muted/50">
            <Button variant="ghost" onclick={onClose}>Cancel</Button>
            <div class="flex gap-2">
                {#if step > 1}<Button variant="outline" onclick={back}>← Back</Button>{/if}
                {#if step < 3}
                    <Button onclick={next} disabled={step === 1 && !defaultTo}>
                        {step === 1 ? 'Next: Review moves →' : 'Next: Confirm →'}
                    </Button>
                {:else}
                    <Button variant="destructive" onclick={submit}
                            disabled={!ack || !reason.trim() || submitting}>
                        Archive site &amp; move {equipment.length} item{equipment.length === 1 ? '' : 's'}
                    </Button>
                {/if}
            </div>
        </footer>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 4: Run test — expect PASS**

`cd frontend && npm run test -- SiteArchiveWizardModal` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/sites/SiteArchiveWizardModal.svelte \
        frontend/src/lib/components/sites/SiteArchiveWizardModal.test.ts
git commit -m "feat(F-0088): SiteArchiveWizardModal — 3-step move+archive flow"
```

---

### Task 26: `EquipmentFilterBar.svelte`

**Files:**
- Create: `frontend/src/lib/components/equipment/EquipmentFilterBar.svelte`
- Test: `frontend/src/lib/components/equipment/EquipmentFilterBar.test.ts`

- [ ] **Step 1: Failing test**

```typescript
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentFilterBar from './EquipmentFilterBar.svelte';

describe('EquipmentFilterBar', () => {
    it('emits filter changes', async () => {
        const onChange = vi.fn();
        const { getByPlaceholderText, getByLabelText } = render(EquipmentFilterBar, {
            props: { value: { q: '', status: null, tag: null, includeArchived: false }, onChange, tags: ['glp', 'qc'] },
        });
        await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'pH' } });
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'pH' }));
    });
});
```

- [ ] **Step 2 + 3: Implement**

```svelte
<script lang="ts">
    interface FilterState {
        q: string;
        status: string | null;
        tag: string | null;
        includeArchived: boolean;
    }
    interface Props {
        value: FilterState;
        tags: string[];
        onChange: (next: FilterState) => void;
    }
    let { value, tags, onChange }: Props = $props();
    function update<K extends keyof FilterState>(key: K, v: FilterState[K]) {
        onChange({ ...value, [key]: v });
    }
</script>

<div class="flex items-center gap-2 flex-wrap">
    <input class="ui-input max-w-xs" placeholder="Search by name, serial, type…"
           value={value.q} oninput={(e) => update('q', (e.currentTarget as HTMLInputElement).value)} />
    <select class="ui-input max-w-[10rem]"
            value={value.status ?? ''}
            onchange={(e) => update('status', (e.currentTarget as HTMLSelectElement).value || null)}>
        <option value="">All status</option>
        <option value="ACTIVE">Active</option>
        <option value="MAINTENANCE">Maintenance</option>
        <option value="RETIRED">Retired</option>
    </select>
    <select class="ui-input max-w-[10rem]"
            value={value.tag ?? ''}
            onchange={(e) => update('tag', (e.currentTarget as HTMLSelectElement).value || null)}>
        <option value="">All tags</option>
        {#each tags as t (t)}<option value={t}>{t}</option>{/each}
    </select>
    <label class="flex items-center gap-1.5 text-sm">
        <input type="checkbox" checked={value.includeArchived}
               onchange={(e) => update('includeArchived', (e.currentTarget as HTMLInputElement).checked)} />
        Include archived
    </label>
</div>
```

- [ ] **Step 4 + 5: PASS + commit**

```bash
cd frontend && npm run test -- EquipmentFilterBar
git add frontend/src/lib/components/equipment/EquipmentFilterBar.svelte frontend/src/lib/components/equipment/EquipmentFilterBar.test.ts
git commit -m "feat(F-0088): EquipmentFilterBar"
```

---

### Task 27: `EquipmentTable.svelte`

**Files:**
- Create: `frontend/src/lib/components/equipment/EquipmentTable.svelte`
- Test: `frontend/src/lib/components/equipment/EquipmentTable.test.ts`

- [ ] **Step 1: Failing test**

```typescript
import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentTable from './EquipmentTable.svelte';

const rows = [
    { id: '1', name: 'HPLC-1', status: 'ACTIVE', next_calibration_due: '2026-08-12',
      room: 'QC Bay', location: 'Bench 2', tags: ['qc'], equipment_type: 'HPLC' },
];

describe('EquipmentTable', () => {
    it('renders rows', () => {
        const { getByText } = render(EquipmentTable, {
            props: { rows, canManage: false, onEdit: vi.fn(), onArchive: vi.fn() },
        });
        expect(getByText('HPLC-1')).toBeTruthy();
    });

    it('hides archive button when canManage is false', () => {
        const { queryByText } = render(EquipmentTable, {
            props: { rows, canManage: false, onEdit: vi.fn(), onArchive: vi.fn() },
        });
        expect(queryByText(/archive/i)).toBeNull();
    });
});
```

- [ ] **Step 2 + 3: Implement**

```svelte
<script lang="ts">
    import type { Equipment } from '$lib/schemas/science';

    interface Props {
        rows: Equipment[];
        canManage: boolean;
        onEdit: (row: Equipment) => void;
        onArchive: (row: Equipment) => void;
    }
    let { rows, canManage, onEdit, onArchive }: Props = $props();

    function calPill(due: string | null | undefined): { cls: string; text: string } {
        if (!due) return { cls: 'cal-na', text: '—' };
        const days = Math.floor((new Date(due).getTime() - Date.now()) / 86_400_000);
        if (days < 0) return { cls: 'cal-expired', text: `⚠ Expired ${Math.abs(days)}d` };
        if (days < 30) return { cls: 'cal-warn', text: `⏰ ${days}d` };
        return { cls: 'cal-ok', text: `✓ ${due}` };
    }
</script>

<table class="table w-full">
    <thead>
        <tr>
            <th>Name</th><th>Type</th><th>Room · Bench</th>
            <th>Status</th><th>Calibration</th><th>Tags</th><th></th>
        </tr>
    </thead>
    <tbody>
        {#each rows as r (r.id)}
            {@const pill = calPill(r.next_calibration_due)}
            <tr class="cursor-pointer hover:bg-muted/50 transition-all duration-150"
                onclick={() => onEdit(r)}>
                <td>
                    <div class="font-medium">{r.name}</div>
                    {#if r.serial_number}<div class="text-xs mono text-muted-foreground">SN: {r.serial_number}</div>{/if}
                </td>
                <td>{r.equipment_type ?? '—'}</td>
                <td>
                    <div>{r.room ?? '—'}</div>
                    {#if r.location}<div class="text-xs text-muted-foreground">{r.location}</div>{/if}
                </td>
                <td>{r.status}</td>
                <td><span class="cal-pill {pill.cls}">{pill.text}</span></td>
                <td>
                    {#each r.tags as t (t)}<span class="tag-chip mr-1">{t}</span>{/each}
                </td>
                <td>
                    {#if canManage}
                        <button class="btn btn-ghost btn-sm cursor-pointer transition-all duration-150"
                                onclick={(e) => { e.stopPropagation(); onArchive(r); }}>Archive</button>
                    {/if}
                </td>
            </tr>
        {/each}
    </tbody>
</table>
```

- [ ] **Step 4 + 5: PASS + commit**

```bash
cd frontend && npm run test -- EquipmentTable
git add frontend/src/lib/components/equipment/EquipmentTable.svelte frontend/src/lib/components/equipment/EquipmentTable.test.ts
git commit -m "feat(F-0088): EquipmentTable"
```

---

### Task 28: `EquipmentFormDialog.svelte`

**Files:**
- Create: `frontend/src/lib/components/equipment/EquipmentFormDialog.svelte`
- Test: `frontend/src/lib/components/equipment/EquipmentFormDialog.test.ts`

- [ ] **Step 1: Failing test**

```typescript
import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentFormDialog from './EquipmentFormDialog.svelte';

const sites = [{ id: 'd', name: 'Default', archived_at: null }];

describe('EquipmentFormDialog', () => {
    it('disables restricted fields when canManage=false', () => {
        const { getByLabelText } = render(EquipmentFormDialog, {
            props: {
                open: true, initial: null, sites, canManage: false,
                tags: [], onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        const cal = getByLabelText(/Last calibration/i) as HTMLInputElement;
        expect(cal.disabled).toBe(true);
    });

    it('enables restricted fields when canManage=true', () => {
        const { getByLabelText } = render(EquipmentFormDialog, {
            props: {
                open: true, initial: null, sites, canManage: true,
                tags: [], onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        const cal = getByLabelText(/Last calibration/i) as HTMLInputElement;
        expect(cal.disabled).toBe(false);
    });
});
```

- [ ] **Step 2 + 3: Implement**

```svelte
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import SitePicker from '$lib/components/sites/SitePicker.svelte';
    import TagsInput from './TagsInput.svelte';
    import type { Site } from '$lib/schemas/sites';
    import type { Equipment, EquipmentCreate } from '$lib/schemas/science';

    interface Props {
        open: boolean;
        initial: Equipment | null;
        sites: Site[];
        tags: string[];
        canManage: boolean;
        onClose: () => void;
        onSubmit: (payload: Partial<EquipmentCreate>) => Promise<void>;
    }
    let { open, initial, sites, tags, canManage, onClose, onSubmit }: Props = $props();

    let name = $state(initial?.name ?? '');
    let site_id = $state(initial?.site_id ?? sites[0]?.id ?? '');
    let equipment_type = $state(initial?.equipment_type ?? '');
    let room = $state(initial?.room ?? '');
    let location = $state(initial?.location ?? '');
    let description = $state(initial?.description ?? '');
    let tagsValue = $state<string[]>(initial?.tags ?? []);
    let manufacturer = $state(initial?.manufacturer ?? '');
    let model = $state(initial?.model ?? '');
    let serial_number = $state(initial?.serial_number ?? '');
    let status = $state(initial?.status ?? 'ACTIVE');
    let install_date = $state(initial?.install_date ?? '');
    let last_calibration_date = $state(initial?.last_calibration_date ?? '');
    let next_calibration_due = $state(initial?.next_calibration_due ?? '');
    let saving = $state(false);

    async function submit() {
        saving = true;
        try {
            await onSubmit({
                name, site_id, equipment_type, room, location, description,
                tags: tagsValue,
                ...(canManage ? {
                    manufacturer, model, serial_number, status,
                    install_date: install_date || undefined,
                    last_calibration_date: last_calibration_date || undefined,
                    next_calibration_due: next_calibration_due || undefined,
                } : {}),
            });
            onClose();
        } finally { saving = false; }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-xl">
        <Dialog.Header><Dialog.Title>{initial ? 'Edit equipment' : 'New equipment'}</Dialog.Title></Dialog.Header>

        <div class="space-y-3 py-2">
            <div><label class="ui-label">Name *</label><Input bind:value={name} /></div>
            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class="ui-label">Site *</label>
                    <SitePicker {sites} value={site_id} onChange={(v) => site_id = v} />
                </div>
                <div><label class="ui-label">Type</label><Input bind:value={equipment_type} /></div>
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div><label class="ui-label">Room</label><Input bind:value={room} /></div>
                <div><label class="ui-label">Bench / Spot</label><Input bind:value={location} /></div>
            </div>
            <div><label class="ui-label">Description</label><Input bind:value={description} /></div>
            <div>
                <label class="ui-label">Tags</label>
                <TagsInput value={tagsValue} suggestions={tags} onChange={(v) => tagsValue = v} />
            </div>

            <hr class="border-dashed" />

            <div class:opacity-60={!canManage}>
                <div class="flex items-center justify-between">
                    <span class="ui-label">{canManage ? 'Regulated fields' : '🔒 Regulated fields'}</span>
                    {#if !canManage}<span class="text-xs text-muted-foreground">SITE_MANAGER or ADMIN only</span>{/if}
                </div>
                <div class="grid grid-cols-2 gap-3 mt-2">
                    <div><label class="ui-label">Manufacturer</label><Input bind:value={manufacturer} disabled={!canManage} /></div>
                    <div><label class="ui-label">Model</label><Input bind:value={model} disabled={!canManage} /></div>
                    <div><label class="ui-label">Serial</label><Input bind:value={serial_number} disabled={!canManage} /></div>
                    <div>
                        <label class="ui-label">Status</label>
                        <select class="ui-input" bind:value={status} disabled={!canManage}>
                            <option value="ACTIVE">Active</option>
                            <option value="MAINTENANCE">Maintenance</option>
                            <option value="RETIRED">Retired</option>
                        </select>
                    </div>
                    <div><label class="ui-label">Install date</label><input class="ui-input mono" type="date" bind:value={install_date} disabled={!canManage} /></div>
                    <div><label class="ui-label">Last calibration</label><input class="ui-input mono" type="date" aria-label="Last calibration" bind:value={last_calibration_date} disabled={!canManage} /></div>
                    <div><label class="ui-label">Next calibration</label><input class="ui-input mono" type="date" bind:value={next_calibration_due} disabled={!canManage} /></div>
                </div>
            </div>
        </div>

        <Dialog.Footer>
            <Button variant="outline" onclick={onClose}>Cancel</Button>
            <Button onclick={submit} disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 4 + 5: PASS + commit**

```bash
cd frontend && npm run test -- EquipmentFormDialog
git add frontend/src/lib/components/equipment/EquipmentFormDialog.svelte frontend/src/lib/components/equipment/EquipmentFormDialog.test.ts
git commit -m "feat(F-0088): EquipmentFormDialog with field-level disabling"
```

---

### Task 29: `EquipmentAttachmentsList.svelte` + empty-states

**Files:**
- Create: `frontend/src/lib/components/equipment/EquipmentAttachmentsList.svelte`
- Create: `frontend/src/lib/components/equipment/EquipmentEmptyState.svelte`
- Create: `frontend/src/lib/components/sites/SiteEmptyState.svelte`

- [ ] **Step 1: Implement attachments list**

```svelte
<!-- EquipmentAttachmentsList.svelte -->
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import type { EquipmentAttachment } from '$lib/schemas/science';

    interface Props {
        attachments: EquipmentAttachment[];
        canManage: boolean;
        onUpload: (file: File) => Promise<void>;
        onDelete: (id: string) => Promise<void>;
    }
    let { attachments, canManage, onUpload, onDelete }: Props = $props();
    let fileInput: HTMLInputElement | null = $state(null);
    let uploading = $state(false);

    async function pick(e: Event) {
        const f = (e.currentTarget as HTMLInputElement).files?.[0];
        if (!f) return;
        uploading = true;
        try { await onUpload(f); } finally { uploading = false; if (fileInput) fileInput.value = ''; }
    }
</script>

<div class="space-y-2">
    <ul class="space-y-1">
        {#each attachments as a (a.id)}
            <li class="flex items-center justify-between text-sm">
                <span>{a.original_filename} <span class="text-xs text-muted-foreground mono">({Math.round(a.size_bytes / 1024)} KB)</span></span>
                {#if canManage}
                    <button class="btn btn-ghost btn-sm" onclick={() => onDelete(a.id)}>Delete</button>
                {/if}
            </li>
        {/each}
    </ul>
    {#if canManage}
        <input bind:this={fileInput} type="file" class="hidden" onchange={pick}
               accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx" />
        <Button onclick={() => fileInput?.click()} disabled={uploading}>
            {uploading ? 'Uploading…' : '+ Upload (PDF, Office, image — 25 MB)'}
        </Button>
    {/if}
</div>
```

- [ ] **Step 2: Implement empty states** (small components — one each)

```svelte
<!-- SiteEmptyState.svelte -->
<script lang="ts">
    interface Props { onAdd?: () => void; canEdit: boolean; }
    let { onAdd, canEdit }: Props = $props();
</script>
<div class="empty-card text-center py-8">
    <p>No sites yet.</p>
    {#if canEdit}<button class="btn btn-primary mt-2" onclick={() => onAdd?.()}>+ Add a site</button>{/if}
</div>
```

```svelte
<!-- EquipmentEmptyState.svelte -->
<script lang="ts">
    interface Props { onAdd?: () => void; }
    let { onAdd }: Props = $props();
</script>
<div class="empty-card text-center py-8">
    <p>No equipment at this site.</p>
    <button class="btn btn-primary mt-2" onclick={() => onAdd?.()}>+ Add equipment</button>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/equipment/EquipmentAttachmentsList.svelte \
        frontend/src/lib/components/equipment/EquipmentEmptyState.svelte \
        frontend/src/lib/components/sites/SiteEmptyState.svelte
git commit -m "feat(F-0088): EquipmentAttachmentsList + empty states"
```

---

### Task 29b: `SiteManagersPanel.svelte` + `SiteManagerAddPicker.svelte`

Decision 5d-ii: ADMIN manages per-site grants in two surfaces — the
site-detail page (this panel) and the member-detail dialog (Task 31).
This task builds the site-detail surface. Reference the mockup at
`docs/superpowers/specs/mockups/f0088-equipment-and-sites.html`
("View 5 — Site managers panel") for chrome, hover-reveal × remove,
avatar treatment, and the picker popover. The panel is only rendered
to ADMIN viewers (gated in Task 30); the component itself does not
re-check permission — it trusts the caller.

**Files:**
- Create: `frontend/src/lib/components/sites/SiteManagersPanel.svelte`
- Create: `frontend/src/lib/components/sites/SiteManagerAddPicker.svelte`
- Test: `frontend/src/lib/components/sites/SiteManagersPanel.test.ts`

- [ ] **Step 1: Failing test**

```typescript
// frontend/src/lib/components/sites/SiteManagersPanel.test.ts
import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteManagersPanel from './SiteManagersPanel.svelte';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn().mockResolvedValue([
            { id: 'g1', user_id: 'u1', site_id: 's1', granted_by_id: 'admin',
              created_at: '2026-05-01T00:00:00Z',
              user: { id: 'u1', name: 'Alice Chen', email: 'alice@trellis.bio' } },
        ]),
        post: vi.fn(),
        delete: vi.fn(),
    },
}));

describe('SiteManagersPanel', () => {
    it('renders the grants returned by the API', async () => {
        const { findByText } = render(SiteManagersPanel, { props: { siteId: 's1' } });
        expect(await findByText('Alice Chen')).toBeTruthy();
    });

    it('shows empty state when no grants', async () => {
        const { api } = await import('$lib/api');
        (api.get as any).mockResolvedValueOnce([]);
        const { findByText } = render(SiteManagersPanel, { props: { siteId: 's1' } });
        expect(await findByText(/no site managers/i)).toBeTruthy();
    });
});
```

- [ ] **Step 2: Run test — expect FAIL**

`cd frontend && npm run test -- SiteManagersPanel` → FAIL.

- [ ] **Step 3: Implement `SiteManagersPanel.svelte`**

Match the mockup `View 5` chrome: card with header ("Site managers"
+ count + "+ Add manager" trigger), list of manager rows
(`.mgr-row`), each row showing avatar (initials), name, email,
metadata ("granted by … on …"), and a hover-reveal × button.

Behavior:
- Load via `GET /sites/{siteId}/managers`
- "+ Add manager" opens `<SiteManagerAddPicker>` (popover, multi-select,
  excludes already-granted, ADMIN-only org members eligible). On
  confirm, POST one grant per selected user in parallel.
- × button on a row opens a one-line confirm: "Remove {name} as a
  site manager?" — on confirm, DELETE the grant. If this was the
  user's last grant AND the user does not hold the SITE_MANAGER role
  on any other site, surface a follow-up info toast: "Note: {name}
  still holds the SITE_MANAGER role with zero grants — visit the
  member's profile to clear the role bit if no longer needed."
  (The backend does NOT auto-clear the role bit on last-grant-removal;
  decision 5b in the grill keeps revoke-grants and revoke-role as
  independent ADMIN ops.)

- [ ] **Step 4: Implement `SiteManagerAddPicker.svelte`**

Per mockup `View 5 / picker popover`. Inputs: `siteId`,
`alreadyGrantedUserIds`. Loads org members from
`GET /organizations/{orgId}/members`, filters out already-granted
rows (disabled with "Already granted" hint), supports search +
multi-select. Emits `onConfirm(userIds: string[])`. Footer shows
selection count + Cancel/Add buttons; Add is disabled when 0
selected.

- [ ] **Step 5: Run test — expect PASS**

`cd frontend && npm run test -- SiteManagersPanel` → PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/sites/SiteManagersPanel.svelte \
        frontend/src/lib/components/sites/SiteManagerAddPicker.svelte \
        frontend/src/lib/components/sites/SiteManagersPanel.test.ts
git commit -m "feat(F-0088): SiteManagersPanel — ADMIN grant/revoke UI on site detail"
```

---

## Phase 8 — Routes & touch-ups

### Task 30: `/organization` route group

**Files:**
- Create: `frontend/src/routes/organization/+layout.svelte`
- Create: `frontend/src/routes/organization/sites/+page.svelte`
- Create: `frontend/src/routes/organization/sites/+page.ts`

- [ ] **Step 1: `+layout.svelte`** — minimal shell with a left nav (just "Sites" for v1) and `{@render children?.()}`

```svelte
<script lang="ts">
    import { page } from '$app/stores';
    let { children } = $props();
</script>

<div class="grid grid-cols-12 min-h-screen">
    <aside class="col-span-2 border-r border-border bg-muted/30 p-4">
        <h2 class="ui-label mb-3">Organization</h2>
        <nav>
            <a href="/organization/sites" class="block px-2 py-1.5 rounded hover:bg-muted cursor-pointer transition-all duration-150"
               class:bg-muted={$page.url.pathname.startsWith('/organization/sites')}>
                Sites &amp; Equipment
            </a>
        </nav>
    </aside>
    <main class="col-span-10">
        {@render children?.()}
    </main>
</div>
```

- [ ] **Step 2: `+page.ts` loader**

```typescript
import { api } from '$lib/api';
import { SiteListSchema, type Site } from '$lib/schemas/sites';
import { EquipmentListSchema, type Equipment } from '$lib/schemas/science';

export const load = async (): Promise<{ sites: Site[]; equipment: Equipment[]; tags: string[] }> => {
    const [sites, equipment, tags] = await Promise.all([
        api.get('/sites', { schema: SiteListSchema }),
        api.get('/equipment', { schema: EquipmentListSchema }),
        api.get('/equipment/tags', { schema: { parse: (v: unknown) => v as string[] } as any }),
    ]);
    return { sites, equipment, tags };
};
```

- [ ] **Step 3: `+page.svelte`** — assemble the views from the components

```svelte
<script lang="ts">
    import { fade } from 'svelte/transition';
    import { api } from '$lib/api';
    import { auth, canManageSite, isOrgAdmin } from '$lib/auth.svelte';
    import SiteList from '$lib/components/sites/SiteList.svelte';
    import SiteFormDialog from '$lib/components/sites/SiteFormDialog.svelte';
    import SiteArchiveWizardModal from '$lib/components/sites/SiteArchiveWizardModal.svelte';
    import SiteEmptyState from '$lib/components/sites/SiteEmptyState.svelte';
    import SiteManagersPanel from '$lib/components/sites/SiteManagersPanel.svelte';
    import EquipmentFilterBar from '$lib/components/equipment/EquipmentFilterBar.svelte';
    import EquipmentTable from '$lib/components/equipment/EquipmentTable.svelte';
    import EquipmentFormDialog from '$lib/components/equipment/EquipmentFormDialog.svelte';
    import EquipmentEmptyState from '$lib/components/equipment/EquipmentEmptyState.svelte';
    import {
        EquipmentListSchema, EquipmentSchema, type Equipment,
    } from '$lib/schemas/science';
    import { SiteListSchema, SiteSchema, type Site } from '$lib/schemas/sites';

    let { data } = $props();
    let sites = $state<Site[]>(data.sites);
    let equipment = $state<Equipment[]>(data.equipment);
    let tags = $state<string[]>(data.tags);
    let activeId = $state<string | null>(sites[0]?.id ?? null);

    let siteFormOpen = $state(false);
    let siteFormInitial = $state<Site | null>(null);
    let archiveOpen = $state(false);
    let equipmentFormOpen = $state(false);
    let equipmentFormInitial = $state<Equipment | null>(null);
    let filter = $state({ q: '', status: null as string | null, tag: null as string | null, includeArchived: false });

    const activeSite = $derived(sites.find((s) => s.id === activeId) ?? null);
    const visibleEquipment = $derived(equipment
        .filter((e) => activeId ? e.site_id === activeId : true)
        .filter((e) => !filter.q || e.name.toLowerCase().includes(filter.q.toLowerCase()))
        .filter((e) => !filter.status || e.status === filter.status)
        .filter((e) => !filter.tag || e.tags?.includes(filter.tag))
        .filter((e) => filter.includeArchived || !e.archived_at)
    );

    async function reloadAll() {
        const [s, e, t] = await Promise.all([
            api.get('/sites', { schema: SiteListSchema }),
            api.get('/equipment', { schema: EquipmentListSchema }),
            api.get<string[]>('/equipment/tags'),
        ]);
        sites = s; equipment = e; tags = t;
    }

    async function saveSite(payload) {
        if (siteFormInitial) {
            await api.patch(`/sites/${siteFormInitial.id}`, payload, { schema: SiteSchema });
        } else {
            await api.post('/sites', payload, { schema: SiteSchema });
        }
        await reloadAll();
    }
    async function submitArchive(payload) {
        if (!activeSite) return;
        await api.request(`DELETE`, `/sites/${activeSite.id}`, { body: payload });
        await reloadAll();
        activeId = sites.find((s) => s.id !== activeSite.id)?.id ?? null;
    }
    async function saveEquipment(payload) {
        if (equipmentFormInitial) {
            await api.patch(`/equipment/${equipmentFormInitial.id}`, payload, { schema: EquipmentSchema });
        } else {
            await api.post('/equipment', { ...payload, site_id: payload.site_id ?? activeId }, { schema: EquipmentSchema });
        }
        await reloadAll();
    }
    async function archiveEquipment(row: Equipment) {
        await api.delete(`/equipment/${row.id}`);
        await reloadAll();
    }
</script>

<div class="grid grid-cols-12 min-h-[80vh]" in:fade={{ duration: 120 }}>
    <SiteList
        sites={sites.map((s) => ({ ...s, equipment_count: equipment.filter((e) => e.site_id === s.id && !e.archived_at).length }))}
        activeId={activeId}
        canCreateSite={isOrgAdmin}
        onSelect={(id) => activeId = id}
        onAdd={() => { siteFormInitial = null; siteFormOpen = true; }}
    />

    <div class="col-span-9">
        {#if !activeSite}
            <SiteEmptyState canCreate={isOrgAdmin}
                            onAdd={() => { siteFormInitial = null; siteFormOpen = true; }} />
        {:else}
            <header class="px-6 py-4 flex items-center justify-between border-b border-border">
                <div>
                    <h3 class="text-base font-semibold">{activeSite.name}</h3>
                    <p class="text-xs text-muted-foreground">{visibleEquipment.length} equipment</p>
                </div>
                <div class="flex items-center gap-2">
                    {#if isOrgAdmin}
                        <!-- Decision 5c-ii: archive is ADMIN-only. -->
                        <button class="btn btn-outline btn-sm cursor-pointer transition-all duration-150"
                                disabled={activeSite.is_default}
                                title={activeSite.is_default ? 'Default site cannot be archived' : ''}
                                onclick={() => archiveOpen = true}>Archive</button>
                    {/if}
                    {#if canManageSite(activeSite.id)}
                        <!-- Decision 5c-ii: SITE_MANAGER (with grant) or ADMIN can rename. -->
                        <button class="btn btn-outline btn-sm cursor-pointer transition-all duration-150"
                                onclick={() => { siteFormInitial = activeSite; siteFormOpen = true; }}>Rename</button>
                    {/if}
                    <button class="btn btn-primary btn-sm cursor-pointer transition-all duration-150"
                            onclick={() => { equipmentFormInitial = null; equipmentFormOpen = true; }}>+ Add equipment</button>
                </div>
            </header>

            <div class="px-6 py-3 border-b border-border bg-muted/30">
                <EquipmentFilterBar value={filter} {tags} onChange={(v) => filter = v} />
            </div>

            {#if visibleEquipment.length === 0}
                <EquipmentEmptyState onAdd={() => { equipmentFormInitial = null; equipmentFormOpen = true; }} />
            {:else}
                <EquipmentTable rows={visibleEquipment}
                                canManageSite={canManageSite}
                                onEdit={(r) => { equipmentFormInitial = r; equipmentFormOpen = true; }}
                                onArchive={archiveEquipment} />
            {/if}

            {#if isOrgAdmin}
                <!-- Decision 5d-ii: ADMIN sees the per-site managers panel
                     directly under the equipment table. SITE_MANAGER does
                     NOT see this — granting/revoking is an org-level op. -->
                <div class="px-6 py-6 border-t border-border">
                    <SiteManagersPanel siteId={activeSite.id} />
                </div>
            {/if}
        {/if}
    </div>
</div>

{#if siteFormOpen}
    <SiteFormDialog open initial={siteFormInitial}
                    onClose={() => siteFormOpen = false}
                    onSubmit={saveSite} />
{/if}
{#if archiveOpen && activeSite}
    <SiteArchiveWizardModal open site={activeSite}
        otherSites={sites.filter((s) => s.id !== activeSite.id && !s.archived_at)}
        equipment={equipment.filter((e) => e.site_id === activeSite.id && !e.archived_at)}
        onClose={() => archiveOpen = false}
        onSubmit={submitArchive} />
{/if}
{#if equipmentFormOpen}
    <EquipmentFormDialog open initial={equipmentFormInitial}
        sites={sites.filter((s) => !s.archived_at)}
        tags={tags}
        canManageSite={canManageSite}
        onClose={() => equipmentFormOpen = false}
        onSubmit={saveEquipment} />
{/if}
```

Note on identity: archive-disable uses `activeSite.is_default` (the
column), not a name comparison. Decision 8c-ii in the grill — a
SITE_MANAGER may have renamed the default to "HQ", and the archive
guard must still fire.

- [ ] **Step 4: Type-check + run dev server smoke**

```bash
cd frontend && npm run check
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/organization
git commit -m "feat(F-0088): /organization/sites master view"
```

---

### Task 31: `MemberRolesPicker` — SITE_MANAGER chip + inline site picker

Decision 5b in the grill: SITE_MANAGER **cannot** exist as a role bit
with zero grants. Ticking the chip must immediately reveal an inline
site picker; saving with the chip on but no sites selected is a
validation error and disables the save button. Unticking the chip
clears all grants for that member. Removing the last grant unticks
the chip. Decision 5d-ii: this picker is the second of the two UX
surfaces (the other is `SiteManagersPanel` on the site detail page).

Reference the mockup at `docs/superpowers/specs/mockups/f0088-equipment-and-sites.html`
("View 6 — Member roles inline picker") for the exact theme, tray
geometry, and 4-state behavior (chip off, chip on, picker open,
validation error).

**Files:**
- Create: `frontend/src/lib/components/settings/MemberSitesInlinePicker.svelte`
- Modify: `frontend/src/lib/components/settings/MemberRolesPicker.svelte`
- Test: `frontend/src/lib/components/settings/MemberSitesInlinePicker.test.ts`

- [ ] **Step 1: Failing test for inline picker**

```typescript
// frontend/src/lib/components/settings/MemberSitesInlinePicker.test.ts
import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import MemberSitesInlinePicker from './MemberSitesInlinePicker.svelte';

const sites = [
    { id: 's1', name: 'San Diego HQ', archived_at: null },
    { id: 's2', name: 'Boston Lab', archived_at: null },
    { id: 's3', name: 'Old Site', archived_at: '2026-01-01' },
];

describe('MemberSitesInlinePicker', () => {
    it('renders selected sites as removable chips', () => {
        const { getByText } = render(MemberSitesInlinePicker, {
            props: {
                allSites: sites,
                selectedSiteIds: ['s1'],
                onChange: vi.fn(),
            },
        });
        expect(getByText('San Diego HQ')).toBeTruthy();
    });

    it('flags 0-site state as invalid when SITE_MANAGER is on', () => {
        const { getByText } = render(MemberSitesInlinePicker, {
            props: {
                allSites: sites,
                selectedSiteIds: [],
                onChange: vi.fn(),
                hasSiteManagerRole: true,
            },
        });
        expect(getByText(/select at least one site/i)).toBeTruthy();
    });

    it('excludes archived sites from picker options', async () => {
        const { getByText, queryByText } = render(MemberSitesInlinePicker, {
            props: {
                allSites: sites,
                selectedSiteIds: [],
                onChange: vi.fn(),
            },
        });
        await fireEvent.click(getByText(/add site/i));
        expect(queryByText('Old Site')).toBeNull();
    });

    it('emits onChange with new selection when chip removed', async () => {
        const onChange = vi.fn();
        const { container } = render(MemberSitesInlinePicker, {
            props: {
                allSites: sites,
                selectedSiteIds: ['s1', 's2'],
                onChange,
            },
        });
        const removeBtn = container.querySelector(
            'button[aria-label="Remove San Diego HQ"]',
        );
        await fireEvent.click(removeBtn!);
        expect(onChange).toHaveBeenCalledWith(['s2']);
    });
});
```

- [ ] **Step 2: Run test — expect FAIL (component missing)**

`cd frontend && npm run test -- MemberSitesInlinePicker` → FAIL.

- [ ] **Step 3: Implement `MemberSitesInlinePicker.svelte`**

Build the chip tray + picker popover per the mockup
("View 6 — State B / C / D"). Active sites only in the picker
(`archived_at === null`); already-selected rows show a checkmark and
are disabled. The component owns its own popover open/close state and
debounced search input.

The component is purely presentational — it does NOT call the API.
The parent `MemberRolesPicker` owns the grant CRUD: on `onChange` it
computes the diff against the previous `selectedSiteIds`, calls
`POST /sites/{added}/managers` for each added id and
`DELETE /sites/{removed}/managers/{userId}` for each removed id,
batched in `Promise.all`. The chip tick is `selectedSiteIds.length > 0`.

```svelte
<script lang="ts">
    import type { Site } from '$lib/schemas/sites';
    import { Badge } from '$lib/components/ui/badge';

    interface Props {
        allSites: Site[];
        selectedSiteIds: string[];
        onChange: (next: string[]) => void;
        hasSiteManagerRole?: boolean;
    }
    let {
        allSites,
        selectedSiteIds = $bindable([]),
        onChange,
        hasSiteManagerRole = true,
    }: Props = $props();

    let pickerOpen = $state(false);
    let search = $state('');

    const activeSites = $derived(allSites.filter((s) => !s.archived_at));
    const selectedSites = $derived(
        selectedSiteIds
            .map((id) => allSites.find((s) => s.id === id))
            .filter((s): s is Site => s !== undefined)
            .sort((a, b) => a.name.localeCompare(b.name)),
    );
    const candidates = $derived(
        activeSites.filter(
            (s) =>
                !selectedSiteIds.includes(s.id)
                && s.name.toLowerCase().includes(search.toLowerCase()),
        ),
    );
    const isInvalid = $derived(
        hasSiteManagerRole && selectedSiteIds.length === 0,
    );

    function remove(id: string) {
        onChange(selectedSiteIds.filter((s) => s !== id));
    }
    function add(id: string) {
        onChange([...selectedSiteIds, id]);
        search = '';
    }
</script>

<!-- chip tray + picker popover; styling matches the mockup. -->
```

- [ ] **Step 4: Wire into `MemberRolesPicker`**

In `MemberRolesPicker.svelte`:

1. Add SITE_MANAGER to the role options list (as below).
2. When ADMIN ticks the SITE_MANAGER chip:
   - Show `<MemberSitesInlinePicker>` below the chip row, inside a
     left-rail accent tray (see mockup `.grant-tray`).
   - Disable the dialog's Save button while `selectedSiteIds.length === 0`.
3. When ADMIN unticks the SITE_MANAGER chip:
   - Confirm with a one-line `ConfirmDialog`: "Revoke
     {selectedSiteIds.length} site grant(s) for {member.name}?"
   - On confirm, DELETE each grant in parallel, then PATCH roles.
4. The diff between previous and next `selectedSiteIds` translates to
   POST `/sites/{added_id}/managers` and DELETE
   `/sites/{site_id}/managers/{user_id}` calls. Run them inside the
   existing dialog save handler; on any failure roll back the optimistic
   state and surface the error toast.

```typescript
// role options list addition
{
    value: 'SITE_MANAGER',
    label: 'Site manager',
    description: 'Manages facility sites and equipment calibration records.',
},
```

- [ ] **Step 5: Run frontend test suite**

```bash
cd frontend && npm run check && npm run test -- settings/MemberSitesInlinePicker
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/settings/MemberRolesPicker.svelte \
        frontend/src/lib/components/settings/MemberSitesInlinePicker.svelte \
        frontend/src/lib/components/settings/MemberSitesInlinePicker.test.ts
git commit -m "feat(F-0088): SITE_MANAGER chip + inline site grant picker"
```

---

### Task 32: `EquipmentPickerModal` — add SitePicker + localStorage default

Decision 10 in the grill: defaulting the inline-create Site field is a
client-side UX problem, not a server-side one. We persist the user's
last-used site id in `localStorage` under the key `f0088:lastSiteId`
and prefer it over the org's `is_default` site. If the cached id is
missing, archived, or not in the user's `sites` list, fall back to the
org's default site (with an outline pulse on the picker to nudge the
user to confirm). Decision 5b also constrains the inline-create form:
restricted fields stripped from the create form because non-SITE_MANAGER
members can register equipment but cannot set regulated metadata at
creation time (the backend silently drops anyway, but the form should
not show the fields to begin with — see decision 2 add-on).

**Files:**
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.svelte`
- Test: `frontend/src/lib/components/modals/EquipmentPickerModal.test.ts`

- [ ] **Step 1: Failing test for localStorage default**

```typescript
// frontend/src/lib/components/modals/EquipmentPickerModal.test.ts
import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EquipmentPickerModal from './EquipmentPickerModal.svelte';

const sites = [
    { id: 'default', name: 'Default Site', is_default: true, archived_at: null },
    { id: 'cached', name: 'San Diego HQ', is_default: false, archived_at: null },
    { id: 'archived-cached', name: 'Old Lab', is_default: false, archived_at: '2026-01-01' },
];

describe('EquipmentPickerModal site default', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('uses localStorage site id when present and active', () => {
        localStorage.setItem('f0088:lastSiteId', 'cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('cached');
    });

    it('falls back to is_default when cached site is archived', () => {
        localStorage.setItem('f0088:lastSiteId', 'archived-cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('default');
    });

    it('falls back to is_default when cached site not in list', () => {
        localStorage.setItem('f0088:lastSiteId', 'unknown');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('default');
    });
});
```

- [ ] **Step 2: Run test — expect FAIL**

`cd frontend && npm run test -- EquipmentPickerModal` → FAIL.

- [ ] **Step 3: Extend props**

Change the `Props` interface to include `sites: Site[]`. Drop the
`defaultSiteId` prop — the modal resolves its own default now.

- [ ] **Step 4: Resolve initial site id**

In the script block, near the other `newEquipment*` state, add:

```typescript
const STORAGE_KEY = 'f0088:lastSiteId';

function resolveInitialSiteId(): string {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
        const match = sites.find((s) => s.id === cached && !s.archived_at);
        if (match) return match.id;
    }
    const orgDefault = sites.find((s) => s.is_default && !s.archived_at);
    return orgDefault?.id ?? sites[0]?.id ?? '';
}

let newSiteId = $state<string>(resolveInitialSiteId());

$effect(() => {
    if (newSiteId) localStorage.setItem(STORAGE_KEY, newSiteId);
});
```

After the existing "Equipment Type" group in the create form, add a new group:

```svelte
<div class="form-group">
    <label for="eq-site">Site *</label>
    <SitePicker {sites} value={newSiteId} onChange={(v) => newSiteId = v} />
</div>
```

In `handleCreate`, include `site_id: newSiteId` in the payload, and
validate `newSiteId` is non-empty alongside `newEquipmentName`.

Rename the existing "Location" field label to "Bench / Spot" and add
a new Room field above it (free-text, plain `<input>`) bound to
`newEquipmentRoom` state. Pass `room` in the create payload. Do NOT
expose Manufacturer / Model / Serial / Calibration / Status in the
inline-create form — these are post-creation regulated edits and
backend strips them anyway for non-SITE_MANAGER callers.

- [ ] **Step 5: Update callers**

Every place that opens `<EquipmentPickerModal>` (in `RunEditorModal`,
`RunCreatorWizardModal`, `protocols/[id]/+page.svelte`) must pass
`sites`. Load sites from `/sites` near where `orgEquipment` is loaded.
Remove any explicit `defaultSiteId` props.

- [ ] **Step 6: Run frontend test suite**

```bash
cd frontend && npm run test -- EquipmentPickerModal
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/modals/EquipmentPickerModal.svelte \
        frontend/src/lib/components/modals/EquipmentPickerModal.test.ts \
        frontend/src/lib/components/run frontend/src/routes/protocols
git commit -m "feat(F-0088): EquipmentPickerModal — SitePicker + localStorage default"
```

---

### Task 33: Migrate URLs `/iam/...` → `/equipment` in run + protocol pages

**Files:**
- Modify: `frontend/src/lib/components/run/RunCreatorWizardModal.svelte`
- Modify: `frontend/src/lib/components/run/RunEditorModal.svelte`
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Find every reference**

```bash
cd frontend && grep -rn "/iam/organizations/.*equipment\|/iam/equipment" src
```

- [ ] **Step 2: Rewrite each call**

Replace `/iam/organizations/${orgId}/equipment` and `/iam/equipment/${id}` with `/equipment` and `/equipment/${id}` respectively. Add `EquipmentSchema` / `EquipmentListSchema` to the existing call site if it wasn't already passing a schema.

For inline-create POST bodies, ensure `site_id` is present (Task 32 wired the modal; this task threads the value through the caller).

- [ ] **Step 3: Re-run frontend tests + type-check**

```bash
cd frontend && npm run check && npm run test
```

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "refactor(F-0088): migrate run + protocol pages to /equipment URLs"
```

---

## Phase 9 — QA & rule refresh

### Task 34: Run full backend + frontend suites

- [ ] **Step 1: Backend**

```bash
cd backend && pytest --cov=app --cov-report=term-missing
```

Expected: all green; coverage on `services/sites/`, `services/equipment/`, `endpoints/sites.py`, `endpoints/equipment.py` ≥ 80%.

- [ ] **Step 2: Frontend**

```bash
cd frontend && npm run check && npm run test
```

Expected: type-check clean, all Vitest suites pass.

- [ ] **Step 3: Lint**

```bash
cd backend && source .venv/bin/activate && black app tests && isort app tests && mypy app
```

- [ ] **Step 4: Commit any formatter changes**

```bash
git add -A
git commit -m "chore(F-0088): apply black/isort"
```

---

### Task 35: Browser verification via qa-verify

Per the `implement-task` skill, launch the qa-verify subagent with this brief:

> **Feature:** F-0088 Equipment Registry & Sites.
> **Pages:** `/organization/sites`. Also exercise the protocol editor's `EquipmentPickerModal` inline-create.
> **Login:** dev DB (`postgres`/`postgres`); any password works for dev users.
> **Acceptance:**
> - As ADMIN: see Default Site; add a new Site; rename it; attempt to archive Default Site (button disabled, tooltip visible); archive the new Site via the 3-step wizard (verify per-row override badge changes; reason required; final destructive button submits).
> - Add equipment under the new Site; verify Tags type-ahead suggests after one character; upload a PDF attachment; reject an attempted .exe upload (toast + no DB row).
> - Switch to a MEMBER (no SITE_MANAGER role): Sites rail "+ New" hidden; site-header Archive/Rename hidden; equipment-table "Archive" hidden; equipment-form regulated fields disabled with lock icon.
> - Grant the MEMBER `SITE_MANAGER` via `/settings?tab=organization`. Reload; restricted fields become editable.
> - Open the protocol editor's `EquipmentPickerModal`; run inline-create with the new SitePicker; confirm new row appears under the selected Site in `/organization/sites`.
> **UX audit:** confirm calibration pills (✓ / ⏰ / ⚠), step-pill states (active/visited/disabled) match the run-creator chrome, Default Site badge present in left rail.

Fix any FAIL / POLISH items the agent surfaces before returning.

- [ ] **Step 1: Launch qa-verify**

(Skill auto-invokes; nothing to commit here unless fixes follow.)

- [ ] **Step 2: Commit any qa fixes**

```bash
git add -A
git commit -m "fix(F-0088): qa-verify polish items"
```

---

### Task 36: Refresh `.claude/rules/*.md` + CLAUDE.md

Per the `implement-task` skill's "Refresh project rules" step.

- [ ] **Step 1: Scan touched rules files**

Candidates: `.claude/rules/backend-endpoints.md`, `.claude/rules/backend-services.md`, `.claude/rules/frontend-api.md`, `.claude/rules/conventions.md`. Look for stale references to `/iam/organizations/{org_id}/equipment` URLs — remove them.

- [ ] **Step 2: Add SITE_MANAGER to the role list anywhere roles are enumerated**

In `.claude/rules/conventions.md` (if it lists roles) and `backend-endpoints.md` (`require_org_role` / `require_any_org_role` examples).

- [ ] **Step 3: Document `lib/components/sites/` and `lib/components/equipment/` buckets**

In `.claude/rules/conventions.md` under "Component placement," add:

```
- `sites/` — Sites & Equipment management page surfaces (rail, dialogs, archive wizard)
- `equipment/` — Equipment table, filter bar, form, attachments, tags input
```

- [ ] **Step 4: Commit**

```bash
git add .claude/rules
git commit -m "docs(F-0088): refresh rules — new component buckets + URL changes"
```

---

## Self-review

- **Spec coverage:** Each spec section has at least one task:
  - Decision log items 1–15 → embedded in Tasks 3 (extend in place), 5 (migration backfill), 8 (Default Site), 10 (archive flow), 16 (field gate + PATCH), 21 (tags), 32 (inline create site picker).
  - Data model (`sites`, extended `equipment`, `equipment_attachments`) → Tasks 3, 4, 5.
  - Permission model (`require_any_org_role`, `RESTRICTED_EQUIPMENT_FIELDS`) → Tasks 7, 12, 16.
  - Services (`sites/defaults`, `sites/crud`, `equipment/tags`, `equipment/registry`, `equipment/attachments`) → Tasks 8–13.
  - Org-registration hook → Task 14.
  - Endpoints (`/sites`, `/equipment`, attachments) → Tasks 15, 16; legacy removal → Task 17.
  - Frontend schemas → Task 18. Auth derived → Task 19.
  - Components (SitePicker, TagsInput, SiteList, SiteFormDialog, SiteArchiveStepper, SiteArchiveWizardModal, EquipmentFilterBar, EquipmentTable, EquipmentFormDialog, EquipmentAttachmentsList, empty states) → Tasks 20–29.
  - Routes (`/organization/+layout`, `/organization/sites/+page`) → Task 30.
  - Touch-ups (MemberRolesPicker, EquipmentPickerModal, URL migration) → Tasks 31–33.
  - QA → Tasks 34, 35. Rules refresh → Task 36.
- **Placeholder scan:** No "TBD", "TODO later", or naked "Similar to Task N" references. Every step has either a concrete code block, a concrete command, or an explicit edit instruction.
- **Type consistency:** `RESTRICTED_EQUIPMENT_FIELDS` defined in Task 12 (`equipment/registry.py`) is imported and used in Task 16 (endpoint). `SiteArchiveRequest` defined in Task 6 is consumed in Task 15 endpoint. `EquipmentCreate.site_id: UUID` is required in Task 6 and validated in Task 12 `create_equipment`.
- **One gap intentionally not duplicated:** `services/equipment/__init__.py` re-exports both `registry` and `tags` in Task 11; Task 13 adds `attachments` to the same file. Engineers extending in Task 13 should keep the import list.

---

## Execution choice

**Plan complete and saved to `docs/superpowers/plans/2026-05-18-f-0088-equipment-registry-and-sites.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
