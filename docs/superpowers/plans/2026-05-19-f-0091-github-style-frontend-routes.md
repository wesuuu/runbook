# F-0091 GitHub-style Frontend Routes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace UUID-based frontend URLs (`/protocols/<uuid>`) with a GitHub-style hierarchy (`/<org-slug>/protocols/<name-slug>`), with runs and experiments nested under their project.

**Architecture:** Two phases. **Phase 1 (backend, ships independently):** add a stored `slug` column to Protocol, Run, Experiment, Project, and Document; expose by-slug read endpoints; expose a derived `slug` on the organization. The frontend keeps working on UUIDs throughout Phase 1. **Phase 2 (frontend cutover):** restructure SvelteKit routes under `[org]/`, resolve objects by slug, migrate every navigation call site, and hard-delete the old UUID routes.

**Tech Stack:** FastAPI (async) + SQLAlchemy 2.0 (async/asyncpg) + Alembic + PostgreSQL JSONB; SvelteKit 2.x (SPA, `ssr = false`) + Svelte 5 runes + Vitest + Playwright.

**Authoritative decisions** (this plan supersedes the design spec's older flat-routing text where they differ; see ClickUp F-0091):
- Five routed objects: Protocol, Run, Experiment, Project, Library document.
- Runs/Experiments **nest under their project**: `/[org]/projects/[projectSlug]/runs/[slug]`. Slug unique `UNIQUE(project_id, slug)`. **No `organization_id` is denormalized onto Run/Experiment** — the project-nested URL already carries org scoping through the project lookup.
- Protocols and Projects are flat at org level. Protocol gains a denormalized, always-populated `owner_org_id` (because `ck_protocol_scope` leaves `organization_id` NULL for project-scoped protocols); `ck_protocol_scope` is untouched.
- Org slug is **derived** (`slugify(org.name)`), exposed as a computed field on `OrganizationResponse`. No `Organization.slug` column. No TypeScript `slugify` mirror — the frontend reads `org.slug` and object `slug` straight off API responses.
- Collisions are **rejected** at create/rename with HTTP `422` + `detail={"code": "SLUG_CONFLICT", ...}`. Suffixing (`-2`, `-3`) happens **once**, in the migration backfill, to disambiguate pre-existing duplicates (oldest row keeps the bare slug).
- Hard break: old UUID URLs return a SvelteKit `404`; no redirect layer.
- Validation tier **T1** — backend-only; the frontend surfaces `422 SLUG_CONFLICT` as an inline error on the name field, no preflight.

---

## File Structure

**Backend — new files:**
- `backend/app/core/slug.py` — pure `slugify()` + `dedupe_slugs()` (no DB, importable by Alembic).
- `backend/app/services/slugs.py` — `assign_slug()` (DB uniqueness check).
- `backend/alembic/versions/f0091_url_slugs.py` — migration.
- `backend/tests/unit/core/test_slug.py`, `backend/tests/unit/services/test_slugs.py`, `backend/tests/integration/test_slug_routes.py`.

**Backend — modified:**
- `backend/app/models/protocols.py` — `slug` + `owner_org_id` on Protocol; `__table_args__`.
- `backend/app/models/runs.py` — `slug` on Run and Experiment; `__table_args__`.
- `backend/app/models/projects.py` — `slug` on Project; `__table_args__`.
- `backend/app/models/library.py` — `slug` on Document.
- `backend/app/schemas/protocols.py` — `slug` on `ProtocolResponse`.
- `backend/app/schemas/runs.py` — `slug` on `RunResponse`/`ExperimentResponse`; `project_slug` on both.
- `backend/app/schemas/project.py` — `slug` on `ProjectResponse`.
- `backend/app/schemas/library.py` — `slug` on `DocumentResponse`.
- `backend/app/schemas/iam.py` — computed `slug` on `OrganizationResponse`.
- `backend/app/api/endpoints/protocols.py`, `runs.py`, `experiments.py`, `projects.py`, `library.py` — slug assignment + by-slug endpoints.
- `backend/app/services/protocols/creation.py` — slug-on-rename in `update_protocol_metadata`.

**Frontend — new files:**
- `frontend/src/lib/paths.ts` — URL builders + Vitest test.
- `frontend/src/lib/org-routing.ts` — `resolveOrgSlug()` + Vitest test.
- `frontend/src/routes/[org]/+layout.ts` — org guard / auto-switch load.
- `frontend/src/routes/+error.svelte` — 404 page.
- `frontend/e2e/helpers/slug-urls.ts` — e2e slug-URL builders (Task 24).
- `frontend/e2e/slug-routes.spec.ts` — new slug-navigation e2e spec (Task 25).

**Frontend — moved (route restructure):**
- `routes/protocols/[id]/` → `routes/[org]/protocols/[slug]/`
- `routes/projects/` → `routes/[org]/projects/` ; `routes/projects/[id]/` → `routes/[org]/projects/[projectSlug]/`
- `routes/runs/[id]/` → `routes/[org]/projects/[projectSlug]/runs/[slug]/`
- `routes/experiments/[id]/` → `routes/[org]/projects/[projectSlug]/experiments/[slug]/`
- `routes/library/` → `routes/[org]/library/` ; `routes/library/[id]/` → `routes/[org]/library/[slug]/` ; `routes/library/documents/[id]/refine/` → `routes/[org]/library/documents/[slug]/refine/`

**Frontend — modified:** `frontend/src/lib/auth.svelte.ts` (add `Org.slug`, `ensureInitialized()`); `frontend/src/routes/+layout.svelte` (URL regexes, nav links); ~40 files with navigation call sites (Task 20); 3 Vitest suites updated for slug navigation (Task 22); 15 existing Playwright specs migrated to slug routes (Task 24).

---

# PHASE 1 — BACKEND SLUG INFRASTRUCTURE

Phase 1 is independently deployable: slug columns are populated, by-slug endpoints are live, the org exposes a slug — and the frontend still uses UUID URLs unchanged.

## Task 1: Pure slug utilities

**Files:**
- Create: `backend/app/core/slug.py`
- Test: `backend/tests/unit/core/test_slug.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/core/test_slug.py
"""Unit tests for the pure slug utilities."""

from app.core.slug import SLUG_MAX_LENGTH, dedupe_slugs, slugify


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Buffer Prep") == "buffer-prep"


def test_slugify_strips_accents():
    assert slugify("Crème Brûlée") == "creme-brulee"


def test_slugify_drops_symbols_and_collapses_separators():
    assert slugify("Koch, Inc. ---  (R&D)!!") == "koch-inc-r-d"


def test_slugify_trims_leading_and_trailing_separators():
    assert slugify("  --Hello--  ") == "hello"


def test_slugify_caps_at_64_chars_without_trailing_hyphen():
    out = slugify("x " * 100)
    assert len(out) <= SLUG_MAX_LENGTH
    assert not out.endswith("-")


def test_slugify_returns_empty_for_no_alphanumeric_content():
    assert slugify("🎉🎉🎉") == ""
    assert slugify("") == ""


def test_dedupe_oldest_keeps_bare_slug_later_get_suffixes():
    # items are (row_id, base_slug), passed oldest-first.
    out = dedupe_slugs([("a", "buffer-prep"), ("b", "buffer-prep"), ("c", "buffer-prep")])
    assert out == {"a": "buffer-prep", "b": "buffer-prep-2", "c": "buffer-prep-3"}


def test_dedupe_avoids_colliding_with_a_real_suffixed_name():
    # A row literally slugified to "mix-2" must not be overwritten.
    out = dedupe_slugs([("a", "mix"), ("b", "mix-2"), ("c", "mix")])
    assert out == {"a": "mix", "b": "mix-2", "c": "mix-3"}


def test_dedupe_supplies_fallback_for_empty_base():
    out = dedupe_slugs([("a", "")])
    assert out["a"].startswith("untitled-")
    assert len(out["a"]) == len("untitled-") + 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/core/test_slug.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.slug'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/core/slug.py
"""URL-slug generation. Pure functions only — safe to import from Alembic."""

import re
import secrets
import unicodedata

SLUG_MAX_LENGTH = 64

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_EDGE_HYPHENS = re.compile(r"^-+|-+$")


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug.

    Lowercase -> strip accents -> drop non-alphanumerics -> collapse
    separator runs to a single '-' -> trim -> cap at 64 chars. Returns
    "" when the input has no alphanumeric content; the caller supplies a
    fallback (see `dedupe_slugs` / `assign_slug`).
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    collapsed = _NON_ALNUM.sub("-", ascii_only.lower())
    trimmed = _EDGE_HYPHENS.sub("", collapsed)
    return trimmed[:SLUG_MAX_LENGTH].rstrip("-")


def _fallback_slug() -> str:
    """Slug for a name with no alphanumeric content. Effectively unique."""
    return f"untitled-{secrets.token_hex(3)}"


def dedupe_slugs(items: list[tuple[object, str]]) -> dict[object, str]:
    """Assign collision-free slugs to a batch of rows sharing one scope.

    `items` is (row_id, base_slug) ordered oldest-first. The first row to
    claim a base keeps it; later rows get '-2', '-3', ... A base that is
    empty gets an 'untitled-<hex>' fallback. Used only by the migration
    backfill — the live path rejects collisions instead.
    """
    result: dict[object, str] = {}
    used: set[str] = set()
    for row_id, base in items:
        base = base or _fallback_slug()
        candidate = base
        n = 1
        while candidate in used:
            n += 1
            suffix = f"-{n}"
            candidate = base[: SLUG_MAX_LENGTH - len(suffix)].rstrip("-") + suffix
        used.add(candidate)
        result[row_id] = candidate
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/core/test_slug.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/slug.py backend/tests/unit/core/test_slug.py
git commit -m "feat(F-0091): add pure slug utilities (slugify, dedupe_slugs)"
```

---

## Task 2: Add slug columns to the five models

**Files:**
- Modify: `backend/app/models/protocols.py` (`class Protocol` ~33), `backend/app/models/runs.py` (`class Run` ~42, `class Experiment` ~151), `backend/app/models/projects.py` (`class Project` ~19)
- Modify: `backend/app/models/library.py` (Document ~112-179)

No test in this task — model definitions are exercised by the migration (Task 3) and endpoint tests (Tasks 5-9).

- [ ] **Step 1: Add `slug` + `owner_org_id` to Protocol**

In `models/protocols.py`, inside `class Protocol`, add two columns near `organization_id`:

```python
    owner_org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
```

Append a `UniqueConstraint` to the existing `__table_args__` tuple (which already holds `ck_protocol_scope`):

```python
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL AND organization_id IS NULL) OR "
            "(project_id IS NULL AND organization_id IS NOT NULL)",
            name="ck_protocol_scope",
        ),
        UniqueConstraint("owner_org_id", "slug", name="uq_protocols_owner_org_slug"),
    )
```

- [ ] **Step 2: Add `slug` to Run**

In `class Run`, add:

```python
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
```

Replace the existing `__table_args__` (currently `(Index("ix_runs_outcome", "outcome"),)`) with:

```python
    __table_args__ = (
        Index("ix_runs_outcome", "outcome"),
        UniqueConstraint("project_id", "slug", name="uq_runs_project_slug"),
    )
```

Ensure `Run.project` relationship is loaded eagerly so `RunResponse.project_slug` (Task 7) resolves without an async lazy-load. Find the `project` relationship on `Run` and set `lazy="selectin"`:

```python
    project: Mapped["Project"] = relationship(back_populates="runs", lazy="selectin")
```

(If no `project` relationship exists, add one with `back_populates` matching `Project.runs`.)

Add a property below the columns so the response schema can read it:

```python
    @property
    def project_slug(self) -> str:
        """Slug of the owning project — for building nested run URLs."""
        return self.project.slug
```

- [ ] **Step 3: Add `slug` to Experiment**

In `class Experiment` (which has no `__table_args__` today), add:

```python
    slug: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_experiments_project_slug"),
    )
```

Set the `project` relationship `lazy="selectin"` (same as Run) and add the property:

```python
    @property
    def project_slug(self) -> str:
        """Slug of the owning project — for building nested experiment URLs."""
        return self.project.slug
```

- [ ] **Step 4: Add `slug` to Project**

In `class Project` (no `__table_args__` today), add:

```python
    slug: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_projects_org_slug"),
    )
```

- [ ] **Step 5: Add `slug` to Document**

In `library.py`, `class Document` (no `__table_args__` on `Document` itself today), add:

```python
    slug: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_documents_org_slug"),
    )
```

Confirm `UniqueConstraint` and `Index` are imported from `sqlalchemy` at the top of each modified model file (`protocols.py`, `runs.py`, `projects.py`, `library.py`); add to the import if missing.

- [ ] **Step 6: Verify the models import**

Run: `cd backend && source .venv/bin/activate && python -c "from app.models.protocols import Protocol; from app.models.runs import Run, Experiment; from app.models.projects import Project; from app.models.library import Document; print('ok')"`
Expected: prints `ok` with no `ImportError` / `ArgumentError`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/protocols.py backend/app/models/runs.py backend/app/models/projects.py backend/app/models/library.py
git commit -m "feat(F-0091): add slug columns and owner_org_id to routed models"
```

---

## Task 3: Alembic migration with backfill

**Files:**
- Create: `backend/alembic/versions/f0091_url_slugs.py`

Migration revision id `f0091_url_slugs`, `down_revision = "f0087_qau_org_role"` (the current head). It adds every column nullable, backfills, then alters to `NOT NULL` and adds the unique indexes.

- [ ] **Step 1: Write the migration**

```python
# backend/alembic/versions/f0091_url_slugs.py
"""F-0091 — add URL slug columns to routed entities.

Revision ID: f0091_url_slugs
Revises: f0087_qau_org_role
"""

from collections import defaultdict

import sqlalchemy as sa
from alembic import op

from app.core.slug import dedupe_slugs, slugify

revision = "f0091_url_slugs"
down_revision = "f0087_qau_org_role"
branch_labels = None
depends_on = None


# (table, name_column, scope_column, unique_index_name)
_TABLES = [
    ("protocols", "name", "owner_org_id", "uq_protocols_owner_org_slug"),
    ("projects", "name", "organization_id", "uq_projects_org_slug"),
    ("runs", "name", "project_id", "uq_runs_project_slug"),
    ("experiments", "name", "project_id", "uq_experiments_project_slug"),
    ("documents", "title", "org_id", "uq_documents_org_slug"),
]


def _backfill_slugs(bind, table, name_column, scope_column):
    """Generate collision-free slugs for every existing row in `table`."""
    rows = bind.execute(
        sa.text(
            f"SELECT id, {name_column} AS nm, {scope_column} AS scope "
            f"FROM {table} ORDER BY created_at ASC, id ASC"
        )
    ).fetchall()
    by_scope = defaultdict(list)
    for row in rows:
        by_scope[row.scope].append((str(row.id), slugify(row.nm or "")))
    for items in by_scope.values():
        for row_id, final_slug in dedupe_slugs(items).items():
            bind.execute(
                sa.text(f"UPDATE {table} SET slug = :slug WHERE id = :id"),
                {"slug": final_slug, "id": row_id},
            )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add columns nullable so existing rows are not rejected.
    op.add_column(
        "protocols", sa.Column("owner_org_id", sa.UUID(as_uuid=True), nullable=True)
    )
    for table, _name, _scope, _idx in _TABLES:
        op.add_column(table, sa.Column("slug", sa.String(length=64), nullable=True))

    # 2. Backfill protocols.owner_org_id (org-scoped row uses its own
    #    organization_id; project-scoped row inherits the project's org).
    op.execute(
        """
        UPDATE protocols p
        SET owner_org_id = COALESCE(
            p.organization_id,
            (SELECT pr.organization_id FROM projects pr WHERE pr.id = p.project_id)
        )
        """
    )

    # 3. Backfill slugs (Python loop — slugify cannot run in pure SQL).
    for table, name_column, scope_column, _idx in _TABLES:
        _backfill_slugs(bind, table, name_column, scope_column)

    # 4. Lock columns down: NOT NULL + FK + unique indexes.
    op.alter_column("protocols", "owner_org_id", nullable=False)
    op.create_foreign_key(
        "fk_protocols_owner_org_id", "protocols", "organizations",
        ["owner_org_id"], ["id"],
    )
    for table, _name, scope_column, idx in _TABLES:
        op.alter_column(table, "slug", nullable=False)
        op.create_unique_constraint(idx, table, [scope_column, "slug"])


def downgrade() -> None:
    for table, _name, _scope, idx in _TABLES:
        op.drop_constraint(idx, table, type_="unique")
        op.drop_column(table, "slug")
    op.drop_constraint("fk_protocols_owner_org_id", "protocols", type_="foreignkey")
    op.drop_column("protocols", "owner_org_id")
```

- [ ] **Step 2: Apply the migration to the dev DB**

Run: `cd backend && source .venv/bin/activate && alembic upgrade head`
Expected: completes without error; `alembic current` shows `f0091_url_slugs`.

- [ ] **Step 3: Verify uniqueness and completeness of the backfill**

Run:
```bash
cd backend && source .venv/bin/activate && python -c "
import asyncio
from sqlalchemy import text
from app.core.database import async_session_maker
async def main():
    async with async_session_maker() as s:
        for tbl, scope in [('protocols','owner_org_id'),('projects','organization_id'),
                           ('runs','project_id'),('experiments','project_id'),
                           ('documents','org_id')]:
            nulls = (await s.execute(text(f'SELECT count(*) FROM {tbl} WHERE slug IS NULL'))).scalar()
            dups = (await s.execute(text(
                f'SELECT count(*) FROM (SELECT {scope}, slug FROM {tbl} '
                f'GROUP BY {scope}, slug HAVING count(*) > 1) d'))).scalar()
            print(tbl, 'null_slugs=', nulls, 'dup_groups=', dups)
            assert nulls == 0 and dups == 0
    print('OK')
asyncio.run(main())
"
```
Expected: every table prints `null_slugs= 0 dup_groups= 0` then `OK`. (Adjust the session import to match the project's actual session factory in `app/core/database.py`.)

- [ ] **Step 4: Verify downgrade/upgrade round-trips**

Run: `cd backend && source .venv/bin/activate && alembic downgrade -1 && alembic upgrade head`
Expected: both complete without error; Step 3 query still passes afterward.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/f0091_url_slugs.py
git commit -m "feat(F-0091): migration adding slug columns with backfill"
```

---

## Task 4: `assign_slug` DB helper

**Files:**
- Create: `backend/app/services/slugs.py`
- Test: `backend/tests/unit/services/test_slugs.py`

- [ ] **Step 1: Write the failing test**

This is an integration-style test that uses the DB fixture. It exercises `assign_slug` against the `Project` model (a representative scope). Use the project's existing async-DB test fixture — replace `db_session` / `org_factory` / `project_factory` below with the fixtures actually defined in `backend/tests/conftest.py`.

```python
# backend/tests/unit/services/test_slugs.py
"""Tests for the assign_slug DB uniqueness helper."""

import pytest

from app.models.projects import Project
from app.services.slugs import assign_slug


@pytest.mark.asyncio
async def test_assign_slug_returns_slugified_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_raises_on_collision(db_session, org_factory, project_factory):
    org = await org_factory()
    await project_factory(organization_id=org.id, name="Buffer Prep", slug="buffer-prep")
    with pytest.raises(ValueError, match="SLUG_CONFLICT"):
        await assign_slug(
            db_session, Project, Project.organization_id, org.id, "buffer prep"
        )


@pytest.mark.asyncio
async def test_assign_slug_allows_same_name_in_a_different_scope(
    db_session, org_factory, project_factory
):
    org_a = await org_factory()
    org_b = await org_factory()
    await project_factory(organization_id=org_a.id, name="Buffer Prep", slug="buffer-prep")
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org_b.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_excludes_self_on_rename(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    proj = await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    # Renaming to a slug it already owns must not raise.
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "Buffer Prep",
        exclude_id=proj.id,
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_falls_back_for_degenerate_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "🎉🎉"
    )
    assert slug.startswith("untitled-")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/services/test_slugs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.slugs'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/slugs.py
"""Slug assignment with per-scope uniqueness enforcement (F-0091)."""

import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import slugify


async def assign_slug(
    db: AsyncSession,
    model: type,
    scope_attr,
    scope_value,
    name: str,
    exclude_id: Optional[object] = None,
) -> str:
    """Return a unique slug for `name` within a scope, or raise.

    `scope_attr` is the mapped column the slug is unique against
    (e.g. `Project.organization_id`, `Run.project_id`). On rename, pass
    `exclude_id` so the row does not collide with itself.

    Raises `ValueError("SLUG_CONFLICT")` when the slugified name is
    already taken by another row in the same scope.
    """
    base = slugify(name) or f"untitled-{secrets.token_hex(3)}"
    stmt = select(model.id).where(scope_attr == scope_value, model.slug == base)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if (await db.execute(stmt)).first() is not None:
        raise ValueError("SLUG_CONFLICT")
    return base
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/services/test_slugs.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/slugs.py backend/tests/unit/services/test_slugs.py
git commit -m "feat(F-0091): add assign_slug uniqueness helper"
```

---

## Task 5: Protocol — slug wiring + by-slug endpoint

**Files:**
- Modify: `backend/app/api/endpoints/protocols.py` (create ~82-186, get-by-id ~387-442, update ~735-995)
- Modify: `backend/app/services/protocols/creation.py` (`update_protocol_metadata` ~207)
- Modify: `backend/app/schemas/protocols.py` (`ProtocolResponse` ~116)
- Test: `backend/tests/integration/test_slug_routes.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_slug_routes.py`. Replace `client` / `auth_headers` / factory fixtures with the project's actual integration-test fixtures (`backend/tests/conftest.py`).

```python
# backend/tests/integration/test_slug_routes.py
"""Integration tests for F-0091 slug assignment and by-slug lookup."""

import pytest


@pytest.mark.asyncio
async def test_create_protocol_assigns_slug(client, auth_headers, org):
    resp = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(org.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "buffer-prep"


@pytest.mark.asyncio
async def test_duplicate_protocol_name_is_rejected(client, auth_headers, org):
    body = {"name": "Buffer Prep", "organization_id": str(org.id)}
    first = await client.post("/protocols", json=body, headers=auth_headers)
    assert first.status_code == 201
    dup = await client.post(
        "/protocols",
        json={"name": "buffer  prep", "organization_id": str(org.id)},
        headers=auth_headers,
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_protocol_by_slug(client, auth_headers, org):
    created = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(org.id)},
        headers=auth_headers,
    )
    pid = created.json()["id"]
    resp = await client.get("/protocols/by-slug/buffer-prep", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


@pytest.mark.asyncio
async def test_get_protocol_by_slug_unknown_returns_404(client, auth_headers):
    resp = await client.get("/protocols/by-slug/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_protocol_rename_reslugs(client, auth_headers, org):
    created = await client.post(
        "/protocols",
        json={"name": "Buffer Prep", "organization_id": str(org.id)},
        headers=auth_headers,
    )
    pid = created.json()["id"]
    renamed = await client.put(
        f"/protocols/{pid}", json={"name": "Wash Buffer"}, headers=auth_headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "wash-buffer"
    assert (await client.get(
        "/protocols/by-slug/wash-buffer", headers=auth_headers
    )).status_code == 200
```

- [ ] **Step 2: Run the protocol tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k protocol -v`
Expected: FAIL — `slug` missing from the response / `by-slug` route returns 404 for everything.

- [ ] **Step 3: Add `slug` to `ProtocolResponse`**

In `backend/app/schemas/protocols.py`, `class ProtocolResponse`, add a field next to `id`:

```python
    slug: str
```

- [ ] **Step 4: Assign a slug on protocol create**

In `protocols.py` `create_protocol`, just before `db.add(...)` of the new `Protocol`, resolve the owning org and assign the slug. Add imports at the top: `from app.services.slugs import assign_slug` and ensure `Project` and `Protocol` are imported.

```python
    # F-0091: resolve the always-populated owning org, then assign a slug.
    if new_protocol.organization_id is not None:
        new_protocol.owner_org_id = new_protocol.organization_id
    else:
        owning_project = await db.get(Project, new_protocol.project_id)
        new_protocol.owner_org_id = owning_project.organization_id
    try:
        new_protocol.slug = await assign_slug(
            db, Protocol, Protocol.owner_org_id,
            new_protocol.owner_org_id, new_protocol.name,
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SLUG_CONFLICT",
                    "message": f"A protocol named '{new_protocol.name}' "
                    "already exists in this organization.",
                },
            )
        raise
```

(`new_protocol` is the constructed `Protocol`; adapt the variable name to the handler's actual local at protocols.py:150.)

- [ ] **Step 5: Re-slug on rename — graph-save path**

In `protocols.py` `update_protocol`, in the loop that applies `setattr(protocol, key, value)` (~957-958), special-case `name`:

```python
        if key == "name" and value != protocol.name:
            try:
                protocol.slug = await assign_slug(
                    db, Protocol, Protocol.owner_org_id,
                    protocol.owner_org_id, value, exclude_id=protocol.id,
                )
            except ValueError as exc:
                if str(exc) == "SLUG_CONFLICT":
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "SLUG_CONFLICT",
                            "message": f"A protocol named '{value}' "
                            "already exists in this organization.",
                        },
                    )
                raise
        setattr(protocol, key, value)
```

- [ ] **Step 6: Re-slug on rename — metadata fast path**

In `backend/app/services/protocols/creation.py` `update_protocol_metadata`, where `name` is applied to the protocol, add the same `assign_slug` call (with `exclude_id=protocol.id`). The service raises `ValueError("SLUG_CONFLICT")`; the metadata-path `except ValueError` in `protocols.py` (~835-847) must be extended to convert it:

```python
    except ValueError as e:
        msg = str(e)
        if msg == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={"code": "SLUG_CONFLICT",
                        "message": "A protocol with that name already exists "
                        "in this organization."},
            )
        if "published" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
```

- [ ] **Step 7: Add the by-slug endpoint**

In `protocols.py`, add a new route. It resolves the slug to an id within the session org, then reuses the existing `get_protocol_full` service path:

```python
@router.get("/protocols/by-slug/{slug}", response_model=ProtocolResponse)
async def get_protocol_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up a protocol by slug within the caller's current organization."""
    row = await db.execute(
        select(Protocol.id).where(
            Protocol.owner_org_id == user.selected_org_id,
            Protocol.slug == slug,
        )
    )
    protocol_id = row.scalar_one_or_none()
    if protocol_id is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        await get_protocol_full(db, user_id=user.id, protocol_id=protocol_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=403, detail=msg)
    return await get_or_404(db, Protocol, protocol_id)
```

(Mirror the exact return/permission shape of the existing `get_protocol` handler at protocols.py:387-442 — reuse its body verbatim after resolving `protocol_id`.)

- [ ] **Step 7b: Wire slug + `owner_org_id` into the remaining Protocol create paths**

`Protocol` is constructed in four places beyond `create_protocol`. Every one must set `owner_org_id` **and** `slug`, or the `NOT NULL` columns raise `IntegrityError`. At each site, apply the **same `owner_org_id` resolution and `assign_slug` call as Step 4** (all sites are project-scoped, so resolve the org via the owning `Project`). Add `from app.services.slugs import assign_slug` (and import `Project` where needed) to each module.

1. `backend/app/services/protocols/creation.py` — `create_protocol_from_spec` (~104). `project` is already loaded above (~57). After the `Protocol(...)` and before `db.add`: `protocol.owner_org_id = project.organization_id`, then `protocol.slug = await assign_slug(db, Protocol, Protocol.owner_org_id, protocol.owner_org_id, protocol.name)`. This is a service — let `assign_slug` raise `ValueError("SLUG_CONFLICT")`; the calling endpoint converts it (Step 6 extends the metadata-path handler).

2. `backend/app/services/core/onboarding.py` — `find_or_create_sample_protocol` (~169). `project` is in scope (~168). Set `owner_org_id`/`slug` the same way. This is find-or-create (no collision possible); let any `ValueError` propagate.

3. `backend/app/services/ai/workflows/protocol_generator.py` (~114). Load the owning project: `owning_project = await db.get(Project, project_id)`, set `protocol.owner_org_id = owning_project.organization_id`, assign the slug. Let `ValueError` propagate to the chat endpoint's existing error handling.

4. `backend/app/services/protocols/protocol_importer.py` (~806). The constructor sets both `project_id` and `organization_id`; resolve `owner_org_id` with the Step-4 conditional (`organization_id` if non-null, else the owning project's org). Assign the slug; let `ValueError` propagate.

- [ ] **Step 8: Run the protocol tests to verify they pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k protocol -v`
Expected: PASS (5 tests).

Then confirm the secondary create paths: `pytest tests/unit/test_protocols_creation.py tests/unit/test_protocols_lookup.py -q` — all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/endpoints/protocols.py backend/app/services/protocols/creation.py backend/app/services/core/onboarding.py backend/app/services/ai/workflows/protocol_generator.py backend/app/services/protocols/protocol_importer.py backend/app/schemas/protocols.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): protocol slug assignment and by-slug lookup"
```

---

## Task 6: Project — slug wiring + by-slug endpoint

**Files:**
- Modify: `backend/app/api/endpoints/projects.py` (create ~44-99, get-by-id ~120-133, update ~136-187)
- Modify: `backend/app/schemas/project.py` (`ProjectResponse` ~25-33)
- Test: `backend/tests/integration/test_slug_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_slug_routes.py`:

```python
@pytest.mark.asyncio
async def test_create_project_assigns_slug(client, auth_headers):
    resp = await client.post(
        "/projects/", json={"name": "CHO Cell Line Dev"}, headers=auth_headers
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "cho-cell-line-dev"


@pytest.mark.asyncio
async def test_duplicate_project_name_is_rejected(client, auth_headers):
    await client.post("/projects/", json={"name": "CHO Line"}, headers=auth_headers)
    dup = await client.post("/projects/", json={"name": "cho  line"}, headers=auth_headers)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_project_by_slug(client, auth_headers):
    created = await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )
    resp = await client.get("/projects/by-slug/cho-line", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created.json()["id"]


@pytest.mark.asyncio
async def test_project_rename_reslugs(client, auth_headers):
    created = await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )
    pid = created.json()["id"]
    renamed = await client.put(
        f"/projects/{pid}", json={"name": "HEK Line"}, headers=auth_headers
    )
    assert renamed.json()["slug"] == "hek-line"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k project -v`
Expected: FAIL — `slug` missing / `by-slug` 404s.

- [ ] **Step 3: Add `slug` to `ProjectResponse`**

In `backend/app/schemas/project.py`, `class ProjectResponse`, add:

```python
    slug: str
```

- [ ] **Step 4: Assign a slug on project create**

In `projects.py` `create_project`, before `db.add(project)` (~68), add (with `from app.services.slugs import assign_slug` imported):

```python
    try:
        project.slug = await assign_slug(
            db, Project, Project.organization_id,
            user.selected_org_id, project.name,
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={"code": "SLUG_CONFLICT",
                        "message": f"A project named '{project.name}' "
                        "already exists in this organization."},
            )
        raise
```

- [ ] **Step 5: Re-slug on project rename**

In `projects.py` `update_project`, before the `for key, value in changes.items(): setattr(...)` loop (~173-174):

```python
    if "name" in changes and changes["name"] != project.name:
        try:
            project.slug = await assign_slug(
                db, Project, Project.organization_id,
                project.organization_id, changes["name"], exclude_id=project.id,
            )
        except ValueError as exc:
            if str(exc) == "SLUG_CONFLICT":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "SLUG_CONFLICT",
                            "message": f"A project named '{changes['name']}' "
                            "already exists in this organization."},
                )
            raise
```

- [ ] **Step 6: Add the by-slug endpoint**

In `projects.py`:

```python
@router.get("/by-slug/{slug}", response_model=ProjectResponse)
async def get_project_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up a project by slug within the caller's current organization."""
    result = await db.execute(
        select(Project).where(
            Project.organization_id == user.selected_org_id,
            Project.slug == slug,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await check_permission(db, user.id, ObjectType.PROJECT, project.id, PermissionLevel.VIEW)
    return project
```

(Use the project's existing permission helper — `get_project` at projects.py:120-133 uses the `require_permission` route dependency; replicate that VIEW check here in the body via `check_permission`, matching how protocols/runs do body-level checks.)

- [ ] **Step 6b: Wire slug into the remaining Project create paths**

`Project` is constructed in two places beyond `create_project`. Apply the **Step 4 `assign_slug` pattern** (scope = `Project.organization_id`). Add `from app.services.slugs import assign_slug` to each module. Both paths create a project in a brand-new / find-or-create context where no collision is possible — let any `ValueError` propagate rather than wrapping it.

1. `backend/app/services/core/onboarding.py` — `find_or_create_sample_project` (~136). After the `Project(...)` and before `db.add`: `project.slug = await assign_slug(db, Project, Project.organization_id, org.id, project.name)`.

2. `backend/app/api/endpoints/auth.py` — registration seeds "My First Project" (~240). The `Project(...)` is currently passed inline to `db.add(...)`. Refactor to a local variable: build the `Project`, call `assign_slug` (scope value `org.id`), then `db.add(project)`.

- [ ] **Step 7: Run to verify the project tests pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k project -v`
Expected: PASS (4 tests).

Then confirm the secondary create paths: `pytest tests/unit/test_onboarding_service.py -k project -q` — PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/projects.py backend/app/api/endpoints/auth.py backend/app/services/core/onboarding.py backend/app/schemas/project.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): project slug assignment and by-slug lookup"
```

---

## Task 7: Run — slug wiring + nested by-slug endpoint

**Files:**
- Modify: `backend/app/api/endpoints/runs.py` (create ~115-290, get-by-id ~371-387, update ~461-815)
- Modify: `backend/app/schemas/runs.py` (`RunResponse` ~188)
- Test: `backend/tests/integration/test_slug_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_slug_routes.py` (`project_factory`/`run` setup must create a project so runs have a scope):

```python
@pytest.mark.asyncio
async def test_create_run_assigns_slug_and_project_slug(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    resp = await client.post(
        "/runs",
        json={"name": "Seeding 2026-05-12", "project_id": proj["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "seeding-2026-05-12"
    assert body["project_slug"] == "cho-line"


@pytest.mark.asyncio
async def test_duplicate_run_name_in_same_project_is_rejected(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    body = {"name": "Seeding", "project_id": proj["id"]}
    assert (await client.post("/runs", json=body, headers=auth_headers)).status_code == 201
    dup = await client.post("/runs", json=body, headers=auth_headers)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_same_run_name_allowed_in_different_projects(client, auth_headers):
    p1 = (await client.post("/projects/", json={"name": "P1"}, headers=auth_headers)).json()
    p2 = (await client.post("/projects/", json={"name": "P2"}, headers=auth_headers)).json()
    body1 = {"name": "Seeding", "project_id": p1["id"]}
    body2 = {"name": "Seeding", "project_id": p2["id"]}
    assert (await client.post("/runs", json=body1, headers=auth_headers)).status_code == 201
    assert (await client.post("/runs", json=body2, headers=auth_headers)).status_code == 201


@pytest.mark.asyncio
async def test_get_run_by_slug(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    created = (await client.post(
        "/runs", json={"name": "Seeding", "project_id": proj["id"]},
        headers=auth_headers,
    )).json()
    resp = await client.get(
        "/runs/by-slug/cho-line/seeding", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k run -v`
Expected: FAIL.

- [ ] **Step 3: Add `slug` + `project_slug` to `RunResponse`**

In `backend/app/schemas/runs.py`, `class RunResponse`, add:

```python
    slug: str
    project_slug: str
```

`project_slug` resolves via the `Run.project_slug` property added in Task 2 (the `project` relationship is `lazy="selectin"`, so it is always loaded).

- [ ] **Step 4: Assign a slug on run create**

In `runs.py` `create_run`, just after the `Run(...)` is constructed (~238) and before `db.add(...)` / `db.flush()`:

```python
    try:
        run.slug = await assign_slug(
            db, Run, Run.project_id, run.project_id, run.name
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={"code": "SLUG_CONFLICT",
                        "message": f"A run named '{run.name}' already exists "
                        "in this project."},
            )
        raise
```

(`run` = the constructed `Run`; `from app.services.slugs import assign_slug` at the top.)

- [ ] **Step 5: Re-slug on run rename**

In `runs.py` `update_run`, before the blanket `for key, value in changes.items(): setattr(run_obj, key, value)` loop (~797-799):

```python
    if "name" in changes and changes["name"] != run_obj.name:
        try:
            run_obj.slug = await assign_slug(
                db, Run, Run.project_id, run_obj.project_id,
                changes["name"], exclude_id=run_obj.id,
            )
        except ValueError as exc:
            if str(exc) == "SLUG_CONFLICT":
                raise HTTPException(
                    status_code=422,
                    detail={"code": "SLUG_CONFLICT",
                            "message": f"A run named '{changes['name']}' "
                            "already exists in this project."},
                )
            raise
```

- [ ] **Step 6: Add the nested by-slug endpoint**

In `runs.py`:

```python
@router.get("/runs/by-slug/{project_slug}/{slug}", response_model=RunResponse)
async def get_run_by_slug(
    project_slug: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up a run by project slug + run slug within the current org."""
    result = await db.execute(
        select(Run)
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == user.selected_org_id,
            Project.slug == project_slug,
            Run.slug == slug,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await check_permission(db, user.id, ObjectType.RUN, run.id, PermissionLevel.VIEW)
    return run
```

(Match the VIEW-permission style used by the existing `get_run` handler at runs.py:371-387.)

- [ ] **Step 6b: Wire slug into the remaining Run create paths**

`Run` is constructed in three places beyond `create_run`. Apply the **Step 4 `assign_slug` pattern** (scope = `Run.project_id`). Add `from app.services.slugs import assign_slug` to each module.

1. `backend/app/api/endpoints/experiments.py` — run created within an experiment (~315). After the `Run(...)` and the protocol-graph copy, before `db.add`: assign `run.slug` with `assign_slug(db, Run, Run.project_id, run.project_id, run.name)`, wrapped in the Step-4 try/except that raises `HTTPException(422, {"code": "SLUG_CONFLICT", ...})`.

2. `backend/app/api/endpoints/batch_record_import.py` — finalized-import run (~232). After the `Run(...)`, before `db.add`: same `assign_slug` call + 422 wrapper.

3. `backend/app/services/core/onboarding.py` — `find_or_create_sample_run` (~189). After the `Run(...)`, before `db.add`: `run.slug = await assign_slug(db, Run, Run.project_id, run.project_id, run.name)`. Find-or-create — no collision; let any `ValueError` propagate.

- [ ] **Step 7: Run to verify the run tests pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k run -v`
Expected: PASS (4 tests).

Then confirm the secondary create paths: `pytest tests/unit/test_onboarding_service.py -k run tests/integration/test_batch_record_import_api.py -q` — PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/app/api/endpoints/experiments.py backend/app/api/endpoints/batch_record_import.py backend/app/services/core/onboarding.py backend/app/schemas/runs.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): run slug assignment and nested by-slug lookup"
```

---

## Task 8: Experiment — slug wiring + nested by-slug endpoint

**Files:**
- Modify: `backend/app/api/endpoints/experiments.py` (create ~54-94, get-by-id ~132-157, update ~160-214)
- Modify: `backend/app/schemas/runs.py` (`ExperimentResponse` ~254)
- Test: `backend/tests/integration/test_slug_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_slug_routes.py`:

```python
@pytest.mark.asyncio
async def test_create_experiment_assigns_slug_and_project_slug(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    resp = await client.post(
        "/experiments",
        json={"name": "Passage 3", "project_id": proj["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "passage-3"
    assert body["project_slug"] == "cho-line"


@pytest.mark.asyncio
async def test_duplicate_experiment_name_in_project_is_rejected(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    body = {"name": "Passage 3", "project_id": proj["id"]}
    assert (await client.post("/experiments", json=body, headers=auth_headers)).status_code == 201
    dup = await client.post("/experiments", json=body, headers=auth_headers)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_experiment_by_slug(client, auth_headers):
    proj = (await client.post(
        "/projects/", json={"name": "CHO Line"}, headers=auth_headers
    )).json()
    created = (await client.post(
        "/experiments", json={"name": "Passage 3", "project_id": proj["id"]},
        headers=auth_headers,
    )).json()
    resp = await client.get(
        "/experiments/by-slug/cho-line/passage-3", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k experiment -v`
Expected: FAIL.

- [ ] **Step 3: Add `slug` + `project_slug` to `ExperimentResponse`**

In `backend/app/schemas/runs.py`, `class ExperimentResponse`, add:

```python
    slug: str
    project_slug: str
```

- [ ] **Step 4: Assign a slug on experiment create**

In `experiments.py` `create_experiment`, after the `Experiment(...)` is constructed (~71) and before `db.add`:

```python
    try:
        exp.slug = await assign_slug(
            db, Experiment, Experiment.project_id, exp.project_id, exp.name
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={"code": "SLUG_CONFLICT",
                        "message": f"An experiment named '{exp.name}' already "
                        "exists in this project."},
            )
        raise
```

- [ ] **Step 5: Re-slug on experiment rename**

In `experiments.py` `update_experiment`, inside the field loop (~181-187), special-case `name` exactly as in Task 7 Step 5 (substitute `Experiment`, `exp`, and the "experiment" wording).

- [ ] **Step 6: Add the nested by-slug endpoint**

In `experiments.py`:

```python
@router.get(
    "/experiments/by-slug/{project_slug}/{slug}", response_model=ExperimentResponse
)
async def get_experiment_by_slug(
    project_slug: str,
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Look up an experiment by project slug + experiment slug."""
    result = await db.execute(
        select(Experiment)
        .join(Project, Experiment.project_id == Project.id)
        .where(
            Project.organization_id == user.selected_org_id,
            Project.slug == project_slug,
            Experiment.slug == slug,
        )
    )
    exp = result.scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    await check_permission(db, user.id, ObjectType.EXPERIMENT, exp.id, PermissionLevel.VIEW)
    return exp
```

(Match the permission style of the existing `get_experiment` handler at experiments.py:132-157.)

- [ ] **Step 7: Run to verify the experiment tests pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k experiment -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/endpoints/experiments.py backend/app/schemas/runs.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): experiment slug assignment and nested by-slug lookup"
```

---

## Task 9: Library Document — slug wiring + by-slug endpoint

**Files:**
- Modify: `backend/app/api/endpoints/library.py` (upload ~125-244, get-by-id ~306-400)
- Modify: `backend/app/schemas/library.py` (`DocumentResponse` ~8-37)
- Test: `backend/tests/integration/test_slug_routes.py`

Documents have no rename endpoint — the slug is assigned at upload only and is never re-slugged. The slug derives from `title`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_slug_routes.py`. Use the project's existing multipart upload test helper if one exists; otherwise post a small in-memory file:

```python
@pytest.mark.asyncio
async def test_upload_document_assigns_slug(client, auth_headers):
    resp = await client.post(
        "/library/documents",
        data={"title": "SOP Aseptic Technique"},
        files={"file": ("sop.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "sop-aseptic-technique"


@pytest.mark.asyncio
async def test_duplicate_document_title_is_rejected(client, auth_headers):
    args = dict(
        data={"title": "SOP One"},
        files={"file": ("sop.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert (await client.post("/library/documents", **args)).status_code == 201
    dup = await client.post("/library/documents", **args)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_get_document_by_slug(client, auth_headers):
    created = (await client.post(
        "/library/documents",
        data={"title": "SOP One"},
        files={"file": ("sop.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )).json()
    resp = await client.get("/library/documents/by-slug/sop-one", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k document -v`
Expected: FAIL.

- [ ] **Step 3: Add `slug` to `DocumentResponse`**

In `backend/app/schemas/library.py`, `class DocumentResponse`, add:

```python
    slug: str
```

(`DocumentListResponse` and `DocumentDetailResponse` inherit it automatically.)

- [ ] **Step 4: Assign a slug on document upload**

In `library.py` `upload_document`, just before the `Document(...)` constructor (~206) — or set the field on the constructor — assign the slug. `org_id` is the document scope:

```python
    try:
        doc_slug = await assign_slug(
            db, Document, Document.org_id, org_id, title
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise HTTPException(
                status_code=422,
                detail={"code": "SLUG_CONFLICT",
                        "message": f"A document titled '{title}' already "
                        "exists in this organization."},
            )
        raise
```

Then pass `slug=doc_slug` into the `Document(...)` constructor. (`org_id` is whatever local the handler already resolved for the document's org; `from app.services.slugs import assign_slug` at the top.)

- [ ] **Step 5: Add the by-slug endpoint**

In `library.py`:

```python
@router.get("/documents/by-slug/{slug}", response_model=DocumentDetailResponse)
async def get_document_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Look up a library document by slug within the current organization."""
    result = await db.execute(
        select(Document.id).where(
            Document.org_id == current_user.selected_org_id,
            Document.slug == slug,
        )
    )
    document_id = result.scalar_one_or_none()
    if document_id is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return await get_document(document_id=document_id, db=db, current_user=current_user)
```

(Delegates to the existing `get_document` handler at library.py:306-400 so the detailed response — chunks, TOC, progress — is identical.)

- [ ] **Step 5b: Wire slug into the URL-import Document create path**

`Document` is also constructed in `backend/app/services/protocols/url_importer.py` (~184). Before the `Document(...)` constructor, resolve the slug: `doc_slug = await assign_slug(db, Document, Document.org_id, org_id, title)`, then pass `slug=doc_slug` into the constructor. This service runs behind a HITL approval flow — let `assign_slug` raise `ValueError("SLUG_CONFLICT")` and let the caller's existing error handling surface it. Add `from app.services.slugs import assign_slug`.

- [ ] **Step 6: Run to verify the document tests pass**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k document -v`
Expected: PASS (3 tests).

Then confirm the broader library suite: `pytest tests/integration/test_library_api.py -q` — PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/library.py backend/app/services/protocols/url_importer.py backend/app/schemas/library.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): library document slug assignment and by-slug lookup"
```

---

## Task 10: Organization derived slug

**Files:**
- Modify: `backend/app/schemas/iam.py` (`OrganizationResponse` ~28-35)
- Test: `backend/tests/integration/test_slug_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_slug_routes.py`:

```python
@pytest.mark.asyncio
async def test_organizations_list_exposes_derived_slug(client, auth_headers):
    resp = await client.get("/iam/organizations", headers=auth_headers)
    assert resp.status_code == 200
    orgs = resp.json()
    assert orgs, "expected the caller to belong to at least one org"
    for org in orgs:
        assert "slug" in org
        assert org["slug"] == org["slug"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k organizations_list -v`
Expected: FAIL — `slug` not in the org payload.

- [ ] **Step 3: Add the computed field**

In `backend/app/schemas/iam.py`, add the import and a computed field to `class OrganizationResponse`:

```python
from pydantic import computed_field

from app.core.slug import slugify
```

```python
    @computed_field  # type: ignore[prop-decorator]
    @property
    def slug(self) -> str:
        """URL slug derived from the org name. Not an identifier — two
        orgs may share a slug; the session JWT identifies the real org."""
        return slugify(self.name)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && source .venv/bin/activate && pytest tests/integration/test_slug_routes.py -k organizations_list -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend slug suite + lint**

Run: `cd backend && source .venv/bin/activate && pytest tests/unit/core/test_slug.py tests/unit/services/test_slugs.py tests/integration/test_slug_routes.py -v && black app tests && isort app tests`
Expected: all slug tests PASS; formatters report no changes (or apply them).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/iam.py backend/tests/integration/test_slug_routes.py
git commit -m "feat(F-0091): expose derived slug on OrganizationResponse"
```

**Phase 1 complete.** Backend slugs are populated, by-slug endpoints are live, the org exposes a slug. The frontend still uses UUID URLs and is unaffected.

---

# PHASE 2 — FRONTEND ROUTE RESTRUCTURE

## Task 11: Frontend types — `slug` on Org and entity schemas

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts` (`Org` interface)
- Modify: `frontend/src/lib/schemas/{protocols,runs,experiments,projects,documents}.ts`

- [ ] **Step 1: Add `slug` to the `Org` interface**

In `frontend/src/lib/auth.svelte.ts`, add to the `Org` interface:

```ts
interface Org {
  id: string;
  name: string;
  slug: string;
  subscription_tier: string;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Add `slug` (and `project_slug`) to entity Zod schemas**

In the per-domain schema files under `frontend/src/lib/schemas/` (`protocols.ts`, `runs.ts`, `experiments.ts`, `projects.ts`, `documents.ts`), add `slug: z.string()` to the protocol, project, run, experiment, and library-document response schemas. Add `project_slug: z.string()` to the run and experiment schemas. If any entity is consumed without a Zod schema (raw `api.get`), no change is needed there — the field rides along on the JSON.

- [ ] **Step 3: Verify the frontend type-checks**

Run: `cd frontend && npm run check`
Expected: no new type errors. (`org.slug`, `run.project_slug` now resolve.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts frontend/src/lib/schemas/
git commit -m "feat(F-0091): add slug fields to frontend Org and entity schemas"
```

---

## Task 12: Path-builder module

**Files:**
- Create: `frontend/src/lib/paths.ts`
- Test: `frontend/src/lib/paths.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/paths.test.ts
import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
  getCurrentOrg: () => ({ id: 'o1', name: 'Acme', slug: 'acme' }),
}));

import { paths } from './paths';

describe('paths', () => {
  it('builds a protocol path', () => {
    expect(paths.protocol('buffer-prep')).toBe('/acme/protocols/buffer-prep');
  });

  it('builds the projects index path', () => {
    expect(paths.projects()).toBe('/acme/projects');
  });

  it('builds a project path', () => {
    expect(paths.project('cho-line')).toBe('/acme/projects/cho-line');
  });

  it('builds a nested run path', () => {
    expect(paths.run('cho-line', 'seeding')).toBe(
      '/acme/projects/cho-line/runs/seeding',
    );
  });

  it('builds a nested experiment path', () => {
    expect(paths.experiment('cho-line', 'passage-3')).toBe(
      '/acme/projects/cho-line/experiments/passage-3',
    );
  });

  it('builds library paths', () => {
    expect(paths.library()).toBe('/acme/library');
    expect(paths.libraryDoc('sop-one')).toBe('/acme/library/sop-one');
    expect(paths.libraryDocRefine('sop-one')).toBe(
      '/acme/library/documents/sop-one/refine',
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && CI=true npm run test -- paths`
Expected: FAIL — `Cannot find module './paths'`.

- [ ] **Step 3: Write the implementation**

```ts
// frontend/src/lib/paths.ts
/**
 * GitHub-style URL builders (F-0091). Every routed object lives under the
 * current organization's slug; runs and experiments nest under their project.
 * The org slug is read from the auth store, so call sites never pass it.
 */
import { getCurrentOrg } from '$lib/auth.svelte';

function orgSlug(): string {
  const org = getCurrentOrg();
  if (!org) {
    throw new Error('paths: no current organization in the auth store');
  }
  return org.slug;
}

export const paths = {
  home: (): string => '/',
  protocol: (slug: string): string => `/${orgSlug()}/protocols/${slug}`,
  projects: (): string => `/${orgSlug()}/projects`,
  project: (slug: string): string => `/${orgSlug()}/projects/${slug}`,
  run: (projectSlug: string, slug: string): string =>
    `/${orgSlug()}/projects/${projectSlug}/runs/${slug}`,
  experiment: (projectSlug: string, slug: string): string =>
    `/${orgSlug()}/projects/${projectSlug}/experiments/${slug}`,
  library: (): string => `/${orgSlug()}/library`,
  libraryDoc: (slug: string): string => `/${orgSlug()}/library/${slug}`,
  libraryDocRefine: (slug: string): string =>
    `/${orgSlug()}/library/documents/${slug}/refine`,
};
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && CI=true npm run test -- paths`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/paths.ts frontend/src/lib/paths.test.ts
git commit -m "feat(F-0091): add slug-based path builder"
```

---

## Task 13: Org-slug resolver + `ensureInitialized`

**Files:**
- Create: `frontend/src/lib/org-routing.ts`
- Test: `frontend/src/lib/org-routing.test.ts`
- Modify: `frontend/src/lib/auth.svelte.ts` (add `ensureInitialized`, export `getOrgs`/`switchOrg` if not already)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/org-routing.test.ts
import { describe, expect, it } from 'vitest';
import { resolveOrgSlug } from './org-routing';

const acme = { id: 'o1', name: 'Acme', slug: 'acme' };
const koch = { id: 'o2', name: 'Koch', slug: 'koch' };

describe('resolveOrgSlug', () => {
  it('returns current when the URL slug is the active org', () => {
    expect(resolveOrgSlug('acme', acme, [acme, koch])).toEqual({
      kind: 'current',
      org: acme,
    });
  });

  it('returns switch when the URL slug is another membership', () => {
    expect(resolveOrgSlug('koch', acme, [acme, koch])).toEqual({
      kind: 'switch',
      org: koch,
    });
  });

  it('returns notfound when no membership matches', () => {
    expect(resolveOrgSlug('zeta', acme, [acme, koch])).toEqual({ kind: 'notfound' });
  });

  it('returns notfound when there is no current org', () => {
    expect(resolveOrgSlug('acme', null, [])).toEqual({ kind: 'notfound' });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && CI=true npm run test -- org-routing`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the resolver**

```ts
// frontend/src/lib/org-routing.ts
/**
 * Resolves the `[org]` URL segment against the user's memberships (F-0091).
 * The org segment is cosmetic — the session identifies the real org — but a
 * URL pointing at a *different* membership triggers an org switch, and a URL
 * pointing at no membership is a 404.
 */
export interface OrgLike {
  id: string;
  name: string;
  slug: string;
}

export type OrgResolution =
  | { kind: 'current'; org: OrgLike }
  | { kind: 'switch'; org: OrgLike }
  | { kind: 'notfound' };

export function resolveOrgSlug(
  urlSlug: string,
  currentOrg: OrgLike | null,
  orgs: OrgLike[],
): OrgResolution {
  if (currentOrg && currentOrg.slug === urlSlug) {
    return { kind: 'current', org: currentOrg };
  }
  const match = orgs.find((o) => o.slug === urlSlug);
  if (match) {
    return { kind: 'switch', org: match };
  }
  return { kind: 'notfound' };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && CI=true npm run test -- org-routing`
Expected: PASS (4 tests).

- [ ] **Step 5: Add `ensureInitialized` to the auth module**

In `frontend/src/lib/auth.svelte.ts`, add a cached-promise wrapper around the existing `initialize()` so a route load function and the root layout share one init:

```ts
let initPromise: Promise<void> | null = null;

/** Idempotent: runs `initialize()` once, returns the same promise after. */
export function ensureInitialized(): Promise<void> {
  if (!initPromise) {
    initPromise = initialize();
  }
  return initPromise;
}
```

Confirm `getOrgs`, `getCurrentOrg`, and `switchOrg` are exported (research confirms `getOrgs`/`getCurrentOrg` are; export `switchOrg` if it is not already).

- [ ] **Step 6: Use `ensureInitialized` in the root layout**

In `frontend/src/routes/+layout.svelte` `onMount`, replace the existing `await initialize()` call with `await ensureInitialized()`. No other behavior changes.

- [ ] **Step 7: Verify type-check + tests**

Run: `cd frontend && npm run check && CI=true npm run test -- org-routing paths`
Expected: no type errors; all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/org-routing.ts frontend/src/lib/org-routing.test.ts frontend/src/lib/auth.svelte.ts frontend/src/routes/+layout.svelte
git commit -m "feat(F-0091): add org-slug resolver and shared init promise"
```

---

## Task 14: `[org]` layout guard + 404 error page

**Files:**
- Create: `frontend/src/routes/[org]/+layout.ts`
- Create: `frontend/src/routes/[org]/+layout.svelte`
- Create: `frontend/src/routes/+error.svelte`

- [ ] **Step 1: Create the `[org]` layout load**

```ts
// frontend/src/routes/[org]/+layout.ts
import { error } from '@sveltejs/kit';
import {
  ensureInitialized,
  getCurrentOrg,
  getOrgs,
  switchOrg,
} from '$lib/auth.svelte';
import { resolveOrgSlug } from '$lib/org-routing';
import type { LayoutLoad } from './$types';

/**
 * Guards every `/[org]/...` route. Validates the org segment against the
 * user's memberships; switches org if the URL points at a different one;
 * 404s if it points at none. Runs client-side (the app is SPA, ssr=false).
 */
export const load: LayoutLoad = async ({ params }) => {
  await ensureInitialized();
  const resolution = resolveOrgSlug(params.org, getCurrentOrg(), getOrgs());
  if (resolution.kind === 'notfound') {
    throw error(404, 'Organization not found');
  }
  if (resolution.kind === 'switch') {
    await switchOrg(resolution.org.id);
  }
  return { orgSlug: params.org };
};
```

- [ ] **Step 2: Create the `[org]` pass-through layout component**

```svelte
<!-- frontend/src/routes/[org]/+layout.svelte -->
<script lang="ts">
  let { children } = $props();
</script>

{@render children()}
```

- [ ] **Step 3: Create the global error page**

```svelte
<!-- frontend/src/routes/+error.svelte -->
<script lang="ts">
  import { page } from '$app/stores';
</script>

<div class="flex min-h-[60vh] flex-col items-center justify-center gap-2 text-center">
  <p class="text-5xl font-semibold text-muted-foreground">{$page.status}</p>
  <p class="text-lg">
    {$page.error?.message ?? 'Page not found'}
  </p>
  <a href="/" class="mt-2 text-sm text-primary underline">Back to dashboard</a>
</div>
```

- [ ] **Step 4: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no type errors. (Routes under `[org]/` do not exist yet — that is fine; the layout compiles standalone.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/[org]/+layout.ts frontend/src/routes/[org]/+layout.svelte frontend/src/routes/+error.svelte
git commit -m "feat(F-0091): add [org] route guard and 404 error page"
```

---

## Task 15: Move the protocol route

**Files:**
- Move: `frontend/src/routes/protocols/[id]/` → `frontend/src/routes/[org]/protocols/[slug]/`
- Modify: the moved `+page.svelte` (fetch at line ~716; `window.location.href` at ~1139)

- [ ] **Step 1: Move the route folder**

```bash
mkdir -p frontend/src/routes/\[org\]/protocols
git mv frontend/src/routes/protocols/\[id\] frontend/src/routes/\[org\]/protocols/\[slug\]
```

This moves `+page.svelte` and the pass-through `+layout.svelte` together.

- [ ] **Step 2: Switch the data fetch to by-slug**

In `frontend/src/routes/[org]/protocols/[slug]/+page.svelte`, change the param read and fetch. Where it reads `$page.params.id`, read `$page.params.slug`; where it calls `api.get(\`/protocols/${id}\`)` (~line 716), call:

```ts
const protocol = await api.get(`/protocols/by-slug/${$page.params.slug}`);
```

- [ ] **Step 3: Fix the in-page navigations**

This page navigates to its project via `window.location.href = \`/projects/${...}\`` (~1139) and via `goto`. Replace the hard nav with the path helper:

```ts
import { paths } from '$lib/paths';
// ...
window.location.href = paths.project(protocol.project_slug ?? /* fallback */ '');
```

If the protocol page only knows `project_id`, fetch the project (`/projects/{id}`) to obtain `project.slug`, or use `goto(paths.project(slug))`. Resolve every `/protocols/`, `/projects/`, `/runs/` literal in this file via `paths.*` (covered fully in Task 20 — at minimum make this file compile).

- [ ] **Step 4: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors referencing the protocol route.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/routes
git commit -m "refactor(F-0091): move protocol route under [org], fetch by slug"
```

---

## Task 16: Move the project routes

**Files:**
- Move: `frontend/src/routes/projects/+page.svelte` → `frontend/src/routes/[org]/projects/+page.svelte`
- Move: `frontend/src/routes/projects/[id]/` → `frontend/src/routes/[org]/projects/[projectSlug]/`
- Modify: the moved files

The `projects/[id]` page currently doubles as the "new project" form when the param literal is `new`. With slug routing, project creation moves to the projects **index** page (`[org]/projects/+page.svelte`), which already posts to `/projects` — there is no `/projects/new` route in the new structure.

- [ ] **Step 1: Move the folders**

```bash
mkdir -p frontend/src/routes/\[org\]/projects
git mv frontend/src/routes/projects/+page.svelte frontend/src/routes/\[org\]/projects/+page.svelte
git mv frontend/src/routes/projects/\[id\] frontend/src/routes/\[org\]/projects/\[projectSlug\]
rmdir frontend/src/routes/projects 2>/dev/null || true
```

- [ ] **Step 2: Fetch the project by slug**

In `frontend/src/routes/[org]/projects/[projectSlug]/+page.svelte`, read `$page.params.projectSlug` instead of `$page.params.id`, and change the fetch (~line 150) to:

```ts
const project = await api.get(`/projects/by-slug/${$page.params.projectSlug}`);
```

- [ ] **Step 3: Remove the `new`-param branch**

In the moved `[projectSlug]/+page.svelte`, delete the code path that treated `params.id === 'new'` as a creation form. Project creation now lives only on the index page. In `[org]/projects/+page.svelte`, ensure the "New project" action posts to `/projects` and on success navigates with `goto(paths.project(created.slug))`.

- [ ] **Step 4: Update child-entity links on the project page**

The project page lists runs and experiments (via `RunsTab`/`ExperimentsTab`). Their links now need `paths.run(project.slug, run.slug)` / `paths.experiment(project.slug, experiment.slug)`. Make the project page and these tabs compile (full call-site sweep in Task 20).

- [ ] **Step 5: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors referencing the project routes.

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src/routes
git commit -m "refactor(F-0091): move project routes under [org], fetch by slug"
```

---

## Task 17: Move the run route (nested under project)

**Files:**
- Move: `frontend/src/routes/runs/[id]/+page.svelte` → `frontend/src/routes/[org]/projects/[projectSlug]/runs/[slug]/+page.svelte`
- Modify: the moved file

- [ ] **Step 1: Move the folder**

```bash
mkdir -p frontend/src/routes/\[org\]/projects/\[projectSlug\]/runs
git mv frontend/src/routes/runs/\[id\] frontend/src/routes/\[org\]/projects/\[projectSlug\]/runs/\[slug\]
rmdir frontend/src/routes/runs 2>/dev/null || true
```

- [ ] **Step 2: Fetch the run by project slug + run slug**

In the moved `+page.svelte`, read both params and change the fetch (~lines 249, 262) to:

```ts
const { projectSlug, slug } = $page.params;
const run = await api.get(`/runs/by-slug/${projectSlug}/${slug}`);
```

- [ ] **Step 3: Fix the "back to project" links**

The run page has 9 `href="/projects/{run.project_id}?tab=runs"` links. Replace with `paths.project($page.params.projectSlug)` (the project slug is already in the URL):

```svelte
<a href={`${paths.project($page.params.projectSlug)}?tab=runs`}>...</a>
```

- [ ] **Step 4: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors referencing the run route.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/routes
git commit -m "refactor(F-0091): nest run route under project, fetch by slug"
```

---

## Task 18: Move the experiment route (nested under project)

**Files:**
- Move: `frontend/src/routes/experiments/[id]/+page.svelte` → `frontend/src/routes/[org]/projects/[projectSlug]/experiments/[slug]/+page.svelte`
- Modify: the moved file

- [ ] **Step 1: Move the folder**

```bash
mkdir -p frontend/src/routes/\[org\]/projects/\[projectSlug\]/experiments
git mv frontend/src/routes/experiments/\[id\] frontend/src/routes/\[org\]/projects/\[projectSlug\]/experiments/\[slug\]
rmdir frontend/src/routes/experiments 2>/dev/null || true
```

- [ ] **Step 2: Fetch the experiment by project slug + experiment slug**

In the moved `+page.svelte`, change the fetch (~line 74) to:

```ts
const { projectSlug, slug } = $page.params;
const experiment = await api.get(
  `/experiments/by-slug/${projectSlug}/${slug}`,
);
```

- [ ] **Step 3: Fix in-page links**

Replace the 2 `href` links (to the project, to runs) with `paths.project($page.params.projectSlug)` / `paths.run(...)`.

- [ ] **Step 4: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors referencing the experiment route.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/routes
git commit -m "refactor(F-0091): nest experiment route under project, fetch by slug"
```

---

## Task 19: Move the library routes

**Files:**
- Move: `frontend/src/routes/library/+page.svelte` → `frontend/src/routes/[org]/library/+page.svelte`
- Move: `frontend/src/routes/library/[id]/` → `frontend/src/routes/[org]/library/[slug]/`
- Move: `frontend/src/routes/library/documents/[id]/refine/` → `frontend/src/routes/[org]/library/documents/[slug]/refine/`
- Modify: the moved files

- [ ] **Step 1: Move the folders**

```bash
mkdir -p frontend/src/routes/\[org\]/library/documents
git mv frontend/src/routes/library/+page.svelte frontend/src/routes/\[org\]/library/+page.svelte
git mv frontend/src/routes/library/\[id\] frontend/src/routes/\[org\]/library/\[slug\]
git mv frontend/src/routes/library/documents/\[id\] frontend/src/routes/\[org\]/library/documents/\[slug\]
rmdir frontend/src/routes/library/documents frontend/src/routes/library 2>/dev/null || true
```

- [ ] **Step 2: Fetch the document by slug**

In `[org]/library/[slug]/+page.svelte` (~line 269) and `[org]/library/documents/[slug]/refine/+page.svelte` (~line 70), change the fetch to:

```ts
const doc = await api.get(`/library/documents/by-slug/${$page.params.slug}`, {
  schema: DocumentDetailSchema,
});
```

- [ ] **Step 3: Fix the refine-link**

In `[org]/library/[slug]/+page.svelte`, the link to the refine editor becomes `paths.libraryDocRefine(doc.slug)`.

- [ ] **Step 4: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors referencing the library routes.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/routes
git commit -m "refactor(F-0091): move library routes under [org], fetch by slug"
```

---

## Task 20: Migrate all navigation call sites

**Files (research-confirmed audit surface — ~110 call sites across ~40 files):**

`goto(` call sites — `routes/+page.svelte`, `routes/+layout.svelte`, `routes/field/+page.svelte`, `routes/settings/+page.svelte`, `routes/register/+page.svelte`, `routes/login/+page.svelte`, `routes/chat/+page.svelte`, `routes/auth/callback/+page.svelte`, `routes/check-email/+page.svelte`, `routes/legal/accept/+page.svelte`, and the moved `[org]/...` pages; components `lib/components/project/RunsTab.svelte`, `ProtocolsTab.svelte`, `ExperimentsTab.svelte`, `lib/components/layout/ProjectsDropdown.svelte`, `UserMenu.svelte`, `lib/components/run/RunCreatorWizardModal.svelte`, `RunDocuments.svelte`, `lib/components/shared/GoOfflineDialog.svelte`, `lib/components/modals/ProtocolImportModal.svelte`, `lib/api.ts`.

`href=` call sites — `routes/library/+page.svelte` (now `[org]/library`), `routes/+layout.svelte`, the moved detail pages, `lib/components/ai/ChatPanel.svelte`, `lib/components/settings/BillingTab.svelte`, `lib/components/layout/MobileNav.svelte`, `lib/components/shared/PendingApprovalsCard.svelte`, `lib/components/protocol/ProtocolSidebar.svelte`, `lib/components/project/RunsTab.svelte`, `ExperimentsTab.svelte`. (`ai/ApprovalCard.svelte`'s only `href` is the external OpenWetWare `sourceUrl` — not a routed object — so it is excluded.)

- [ ] **Step 1: Replace every routed-object URL literal with a `paths.*` call**

For each file above, import `import { paths } from '$lib/paths';` and replace inline literals. Mapping:

| Old literal | New |
| --- | --- |
| `` `/protocols/${id}` `` | `paths.protocol(protocol.slug)` |
| `'/projects'` | `paths.projects()` |
| `` `/projects/${id}` `` | `paths.project(project.slug)` |
| `'/projects/new'` | `paths.projects()` (creation is a dialog on the index) |
| `` `/runs/${id}` `` | `paths.run(run.project_slug, run.slug)` |
| `` `/experiments/${id}` `` | `paths.experiment(exp.project_slug, exp.slug)` |
| `'/library'` | `paths.library()` |
| `` `/library/${id}` `` | `paths.libraryDoc(doc.slug)` |
| `` `/library/documents/${id}/refine` `` | `paths.libraryDocRefine(doc.slug)` |

Where a call site only holds a UUID (no slug), use the slug from the create/rename API response (`created.slug`, `run.project_slug`) — every response now carries it (Tasks 5-11). Leave **non-routed** URLs untouched: `/`, `/login`, `/register`, `/settings`, `/chat`, `/field`, `/export`, `/legal/*`, `/check-email`, `/organization/sites`, `/auth/callback`, and the `?tab=` query-only `goto`s.

Representative before/after (`lib/components/project/RunsTab.svelte`):

```svelte
<!-- before -->
<a href={`/runs/${run.id}`}>{run.name}</a>
<!-- after -->
<a href={paths.run(run.project_slug, run.slug)}>{run.name}</a>
```

- [ ] **Step 2: Catch any missed literal**

Run: `cd frontend && grep -rnE "(/protocols/|/runs/|/experiments/|/library/|goto\(['\\\`]/projects)" src/ --include=*.svelte --include=*.ts | grep -v paths.ts`
Expected: no remaining hardcoded routed-object URLs (matches should only be inside `paths.ts` or non-route strings). Fix any that remain.

- [ ] **Step 3: Verify type-check + unit tests**

Run: `cd frontend && npm run check && CI=true npm run test`
Expected: no type errors; all Vitest suites PASS.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "refactor(F-0091): route all navigation through the paths helper"
```

---

## Task 21: Update root layout URL logic

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

The root layout has hardcoded URL-shape regexes (`shouldHideChatIcon`: `/^\/protocols\/[^/]+$/`, `/^\/runs\/[^/]+$/`, `/^\/library\/[^/]+$/`) and prefix checks (`showNav`, `isFullBleed`) keyed off the old URL shape.

- [ ] **Step 1: Update the regexes for the slugged, org-prefixed shape**

```ts
// chat icon hidden on full-bleed detail pages — now under /[org]/...
const shouldHideChatIcon = $derived(
  /^\/[^/]+\/protocols\/[^/]+$/.test($page.url.pathname) ||
  /^\/[^/]+\/projects\/[^/]+\/runs\/[^/]+$/.test($page.url.pathname) ||
  /^\/[^/]+\/library\/[^/]+$/.test($page.url.pathname),
);
```

Update `isFullBleed` / `showNav` prefix checks the same way — any check for `/protocols/`, `/runs/`, `/projects/`, `/library/` must account for the leading `/[org]` segment. Update the 4 nav `href`s (logo → `/`, `/library` → `paths.library()`, `/chat`, etc.) — `/chat` stays unprefixed; the library nav link becomes `paths.library()`.

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npm run check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "fix(F-0091): update root layout URL matching for slug routes"
```

---

## Task 22: Update affected frontend unit tests

The navigation rewrite (Tasks 11, 20) breaks three existing Vitest suites. The cause is structural, not incidental:

- `paths.*` builders call `getCurrentOrg()`. A component test that renders a routed link with no organization in the auth store throws `paths: no current organization in the auth store` — the render fails outright.
- Component fixtures for routed objects need `slug` (and `project_slug` for runs/experiments) or the built URL contains `undefined`.
- `DocumentResponseSchema` gains a required `slug` (Task 11), so the fixtures parsed by `schemas/documents.test.ts` fail Zod validation without it.

This task touches **test files only** — no component or schema source. The auth-store mock pattern matches Task 12's `paths.test.ts`.

**Files:**
- Modify: `frontend/src/lib/components/shared/PendingApprovalsCard.test.ts`
- Modify: `frontend/src/lib/components/project/RunsTab.test.ts`
- Modify: `frontend/src/lib/schemas/documents.test.ts`

- [ ] **Step 1: Run the suite to see the failures**

Run: `cd frontend && CI=true npm run test`
Expected: FAIL — at least the `PendingApprovalsCard`, `RunsTab`, and `schemas/documents` suites. Record any other suite that fails for the same three reasons (org-store throw, missing slug fixture, Zod error) — Step 5 sweeps those up.

- [ ] **Step 2: Fix `PendingApprovalsCard.test.ts`**

The card now builds its row link with `paths.protocol(...)`. Add an auth-store mock alongside the existing `$lib/api` mock (top of file):

```ts
vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: () => ({ id: 'o1', name: 'Acme', slug: 'acme' }),
}));
```

Add `protocol_slug: 'buffer-sop'` to the `getAwaitingMyApproval` mock row (next to `protocol_id`), then update the href assertion:

```ts
expect(row.getAttribute('href')).toBe('/acme/protocols/buffer-sop');
```

- [ ] **Step 3: Fix `RunsTab.test.ts`**

`RunsTab` renders each run as `<a href={paths.run(run.project_slug, run.slug)}>`, which calls `getCurrentOrg()`. Add `vi` to the vitest import and mock the auth store above the `RunsTab` import:

```ts
import { describe, it, expect, vi } from 'vitest';
// ...
vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: () => ({ id: 'o1', name: 'Acme', slug: 'acme' }),
}));
```

Give every `RUNS` fixture a `slug` and `project_slug`:

```ts
const RUNS = [
    { id: 'r1', name: 'producer-1', slug: 'producer-1', project_slug: 'cho-line', status: 'COMPLETED', produces_lot: true, lot_number: 'LOT-000001', experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
    { id: 'r2', name: 'non-prod', slug: 'non-prod', project_slug: 'cho-line', status: 'COMPLETED', produces_lot: false, lot_number: null, experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
];
```

- [ ] **Step 4: Fix `schemas/documents.test.ts`**

`DocumentResponseSchema` now requires `slug`. Add a `slug` field to every `raw` object passed to `DocumentResponseSchema.parse(...)` (the fixtures at both `.parse` call sites):

```ts
const raw = { /* ...existing fields... */ slug: 'aseptic-technique-sop' };
```

- [ ] **Step 5: Fix any other suite Step 1 flagged**

For each additional failure: a `no current organization` throw → add the `vi.mock('$lib/auth.svelte', ...)` block; a missing `slug`/`project_slug` on a routed-object fixture → add the field; a Zod error on a schema that gained a required `slug` → add `slug` to that fixture. Stay in test files — no component or schema source changes here.

- [ ] **Step 6: Run the suite to confirm green**

Run: `cd frontend && CI=true npm run test`
Expected: all Vitest suites PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/shared/PendingApprovalsCard.test.ts frontend/src/lib/components/project/RunsTab.test.ts frontend/src/lib/schemas/documents.test.ts
git commit -m "test(F-0091): update unit tests for slug-based navigation"
```

---

## Task 23: Hard break — delete old UUID routes

**Files:**
- Delete: any residual `frontend/src/routes/protocols/`, `runs/`, `experiments/`, `library/`, `projects/` folders

- [ ] **Step 1: Confirm the old folders are gone**

The `git mv` commands in Tasks 15-19 already removed the old folders. Verify nothing remains:

```bash
cd frontend && ls src/routes/protocols src/routes/runs src/routes/experiments src/routes/library src/routes/projects 2>/dev/null
```
Expected: no output (all paths gone). If any remain, `git rm -r` them.

- [ ] **Step 2: Build to confirm the hard break**

Run: `cd frontend && npm run build`
Expected: build succeeds. Old UUID URLs (`/protocols/<uuid>`) no longer match any route — SvelteKit serves `+error.svelte` with a 404.

- [ ] **Step 3: Commit (if anything was removed)**

```bash
git add -A frontend/src/routes
git commit -m "chore(F-0091): drop legacy UUID routes (hard break)"
```

---

## Task 24: Migrate existing Playwright specs to slug routes

The route restructure (Tasks 15-19) and hard break (Task 23) delete the old UUID browser routes. 15 existing e2e specs still `page.goto()` / `toHaveURL()` those dead routes. Object **API** endpoints stay UUID-keyed and are untouched — only browser navigation changes, so the `apiRequest`/`fetch` calls in helpers and specs (`/protocols/...`, `/runs/...`, `/library/documents/...`) need no edits. Migrate the browser-navigation calls through a shared URL-builder helper.

**Files:**
- Create: `frontend/e2e/helpers/slug-urls.ts`
- Modify: `frontend/e2e/{auth,email-verification,protocols,experiments,run-creator,run-creator-scenarios,library,library-markdown,document-refinement}.spec.ts`
- Modify: `frontend/e2e/glp/{run-execution,run-signoff-flow,signoff-reopen-cycle,qau-independence,protocol-approval-flow,protocol-authoring}.spec.ts`

- [ ] **Step 1: Write the slug-URL helper**

```ts
// frontend/e2e/helpers/slug-urls.ts
/**
 * F-0091 slug-based browser-URL builders for e2e specs.
 *
 * Object read/mutation APIs stay UUID-keyed, so each builder fetches the
 * object by id, reads its `slug` (and `project_slug` for nested objects),
 * and assembles the new `/[org]/...` path. The org slug comes from
 * `GET /iam/organizations`.
 */
import { type Page } from '@playwright/test';
import { API_BASE } from './apiBase';

async function authGet(page: Page, path: string): Promise<Record<string, unknown>> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
  const resp = await page.request.fetch(`${API_BASE}${path}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok()) {
    throw new Error(`GET ${path} failed: ${resp.status()}`);
  }
  return resp.json();
}

/** Slug of the test user's current organization. */
export async function orgSlug(page: Page): Promise<string> {
  const orgs = (await authGet(page, '/iam/organizations')) as unknown as Array<{
    slug: string;
  }>;
  if (!orgs.length) {
    throw new Error('slug-urls: test user has no organizations');
  }
  return orgs[0].slug;
}

export async function projectsUrl(page: Page): Promise<string> {
  return `/${await orgSlug(page)}/projects`;
}

export async function libraryUrl(page: Page): Promise<string> {
  return `/${await orgSlug(page)}/library`;
}

export async function protocolUrl(page: Page, protocolId: string): Promise<string> {
  const [org, proto] = await Promise.all([
    orgSlug(page),
    authGet(page, `/protocols/${protocolId}`),
  ]);
  return `/${org}/protocols/${proto.slug}`;
}

export async function projectUrl(page: Page, projectId: string): Promise<string> {
  const [org, proj] = await Promise.all([
    orgSlug(page),
    authGet(page, `/projects/${projectId}`),
  ]);
  return `/${org}/projects/${proj.slug}`;
}

export async function runUrl(page: Page, runId: string): Promise<string> {
  const [org, run] = await Promise.all([
    orgSlug(page),
    authGet(page, `/runs/${runId}`),
  ]);
  return `/${org}/projects/${run.project_slug}/runs/${run.slug}`;
}

export async function experimentUrl(page: Page, experimentId: string): Promise<string> {
  const [org, exp] = await Promise.all([
    orgSlug(page),
    authGet(page, `/experiments/${experimentId}`),
  ]);
  return `/${org}/projects/${exp.project_slug}/experiments/${exp.slug}`;
}

export async function libraryDocUrl(page: Page, documentId: string): Promise<string> {
  const [org, doc] = await Promise.all([
    orgSlug(page),
    authGet(page, `/library/documents/${documentId}`),
  ]);
  return `/${org}/library/${doc.slug}`;
}
```

- [ ] **Step 2: Migrate the unauthenticated-redirect specs**

`auth.spec.ts` and `email-verification.spec.ts` use `page.goto('/projects')` as a stand-in protected route to assert the redirect to `/login` (or `/check-email`). `/projects` is no longer a route. Point them at `/settings`, which stays unprefixed and protected:

- `auth.spec.ts:75` and `auth.spec.ts:118` — `await page.goto('/projects')` → `await page.goto('/settings')`.
- `email-verification.spec.ts:149` — `await page.goto('/projects')` → `await page.goto('/settings')`.

The accompanying `toHaveURL(/.*login/)` / `toHaveURL(/check-email/)` assertions are unchanged.

- [ ] **Step 3: Migrate the protocol specs**

Add `import { protocolUrl, projectUrl } from './helpers/slug-urls';` (use `'../helpers/slug-urls'` for files under `glp/`). `loginViaApi` is exported from `./helpers/auth`; add it to the import wherever a `loginAndNavigate` is expanded and it is not already imported.

```ts
// protocols.spec.ts
- await page.goto(`/projects/${SEED.PROJECT_MAB_ID}`);
+ await page.goto(await projectUrl(page, SEED.PROJECT_MAB_ID));
- await page.goto(`/protocols/${proto.id}`);          // every call site, incl. the `protoId` variant
+ await page.goto(await protocolUrl(page, proto.id));
  // line 69: the page.url() assertion must accept a slug, not a UUID:
+ expect(page.url()).toMatch(/\/protocols\/[a-z0-9-]+$/);

// glp/protocol-authoring.spec.ts  (both call sites)
- await page.goto(`/protocols/${proto.id}`);
+ await page.goto(await protocolUrl(page, proto.id));

// glp/protocol-approval-flow.spec.ts  (both call sites — cannot build the
// slug URL inside loginAndNavigate; the auth token must be set first)
- await loginAndNavigate(page, key, `/protocols/${protocolId}`);
+ await loginViaApi(page, key);
+ await page.goto(await protocolUrl(page, protocolId));
+ await page.waitForLoadState('networkidle');
```

- [ ] **Step 4: Migrate the project / run / experiment specs**

Add `import { projectUrl, runUrl, experimentUrl } from './helpers/slug-urls';` (`'../helpers/slug-urls'` under `glp/`).

```ts
// experiments.spec.ts
- await page.goto(`/projects/${PROJECT_ID}?tab=experiments`);   // and ?tab=runs
+ await page.goto(`${await projectUrl(page, PROJECT_ID)}?tab=experiments`);
- await page.goto(`/experiments/${expId}`);
+ await page.goto(await experimentUrl(page, expId));

// run-creator.spec.ts
- await page.goto(`/projects/${PROJECT_ID}`);
+ await page.goto(await projectUrl(page, PROJECT_ID));
- await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+/);           // both assertions
+ await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);

// run-creator-scenarios.spec.ts
- await page.goto(`/projects/${PROJECT_ID}`);
+ await page.goto(await projectUrl(page, PROJECT_ID));
- await page.goto(`/experiments/${expId}`);
+ await page.goto(await experimentUrl(page, expId));

// glp/run-execution.spec.ts
- await page.goto(`/projects/${SEED.PROJECT_MAB_ID}`);
+ await page.goto(await projectUrl(page, SEED.PROJECT_MAB_ID));
- await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+/);
+ await expect(page).toHaveURL(/\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);

// glp/run-signoff-flow.spec.ts
- await loginAndNavigate(page, 'admin', `/runs/${runId}`);
+ await loginViaApi(page, 'admin');
+ await page.goto(await runUrl(page, runId));
+ await page.waitForLoadState('networkidle');
- await page.goto(`/runs/${runId}`);                            // the standalone call
+ await page.goto(await runUrl(page, runId));

// glp/signoff-reopen-cycle.spec.ts  and  glp/qau-independence.spec.ts
- await page.goto(`/runs/${runId}`);
+ await page.goto(await runUrl(page, runId));
```

- [ ] **Step 5: Migrate the library specs**

Add `import { libraryUrl, libraryDocUrl, orgSlug } from './helpers/slug-urls';`.

```ts
// library.spec.ts  and  library-markdown.spec.ts
- await loginAndNavigate(page, 'admin', '/library');
+ await loginViaApi(page, 'admin');
+ await page.goto(await libraryUrl(page));
+ await page.waitForLoadState('networkidle');
  // library.spec.ts: expect(page.url()).toContain('/library') still holds.

// library-markdown.spec.ts
- await page.goto(`/library/${doc.id}`);
+ await page.goto(await libraryDocUrl(page, doc.id));

// document-refinement.spec.ts — missing-document case; no real doc to
// resolve a slug for, so use a bogus document slug. The existing
// not-found assertion is unchanged.
- await page.goto(`/library/documents/${MISSING_ID}/refine`);
+ await page.goto(`/${await orgSlug(page)}/library/documents/does-not-exist/refine`);
```

- [ ] **Step 6: Run the full e2e suite**

Run: `cd frontend && npm run test:e2e`
Expected: all specs PASS (requires backend + frontend dev servers running on the worktree's slot ports).

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e
git commit -m "test(F-0091): migrate e2e specs to slug-based browser routes"
```

---

## Task 25: End-to-end test + full suite

**Files:**
- Create: `frontend/e2e/slug-routes.spec.ts` (or the project's Playwright test directory)

- [ ] **Step 1: Write the Playwright test**

```ts
// frontend/e2e/slug-routes.spec.ts
import { expect, test } from '@playwright/test';

// Adapt login + seed data to the project's existing e2e helpers.
test('navigates list -> detail through slug URLs', async ({ page }) => {
  await page.goto('/');
  // ... log in via the existing e2e auth helper ...

  // Open a project from the projects list.
  await page.goto('/acme/projects'); // org slug from the seeded org
  await page.getByRole('link', { name: /./ }).first().click();
  await expect(page).toHaveURL(/\/acme\/projects\/[a-z0-9-]+$/);

  // Open a run nested under the project.
  await page.getByRole('link', { name: /run/i }).first().click();
  await expect(page).toHaveURL(/\/acme\/projects\/[a-z0-9-]+\/runs\/[a-z0-9-]+$/);
});

test('an unknown org slug renders the 404 page', async ({ page }) => {
  // ... log in ...
  await page.goto('/no-such-org/protocols/anything');
  await expect(page.getByText('404')).toBeVisible();
});
```

- [ ] **Step 2: Run the e2e test**

Run: `cd frontend && npm run test:e2e -- slug-routes`
Expected: both tests PASS (requires backend + frontend dev servers running).

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && pytest && black app tests && isort app tests && mypy app`
Expected: all tests PASS; lint/type-check clean.

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npm run check && CI=true npm run test && npm run build`
Expected: type-check clean; all Vitest PASS; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/slug-routes.spec.ts
git commit -m "test(F-0091): e2e coverage for slug-based navigation"
```

---

## Self-Review Notes

- **Spec coverage:** all five objects (Tasks 5-9), org slug (Task 10), by-slug endpoints (5-9), migration backfill with one-time suffixing (Task 3), reject-on-collision `422 SLUG_CONFLICT` (5-9), re-slug on rename (5-8; documents have no rename path — Task 9), unit-test fixups for slug navigation (Task 22), hard break (Task 23), route restructure (15-19), navigation audit (20), existing e2e spec migration (Task 24), validation tier T1 (no frontend preflight — Task 20 surfaces the 422 as-is). Notification/email deep links and Lot/Equipment are out of scope per ClickUp F-0091.
- **Deviation from the design spec:** the spec's older text describes flat org-level run/experiment routing and a TS `slugify` mirror. This plan implements the project-nested layout (confirmed authoritative) and drops the TS mirror — the backend exposes `org.slug` and object `slug`, so the frontend never slugifies. Run/Experiment get **no** denormalized `organization_id`; project-nesting makes it unnecessary.
- **Phasing:** Phase 1 (Tasks 1-10) is independently deployable — backend slugs live, frontend untouched. Phase 2 (11-23) is the cutover.
- **Fixture caveat:** test fixture names (`db_session`, `client`, `auth_headers`, `org`, `*_factory`) are placeholders — match them to `backend/tests/conftest.py` during execution.
- **Known limitation:** an organization whose name slugifies to a reserved root segment (`settings`, `login`, `chat`, …) cannot be addressed by URL, because SvelteKit prioritizes static routes over `[org]`. The org slug is cosmetic (the session identifies the real org), so the app still functions; this is an accepted edge case, not handled here.
