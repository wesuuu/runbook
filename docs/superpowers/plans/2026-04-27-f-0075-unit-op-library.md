# F-0075 Unit Operation Library Abstraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace today's flat list of 16 globally-scoped unit operations with a JSON-defined catalog system. Built-in libraries live as versioned JSON in the repo. The DB holds org subscriptions to libraries, per-org overrides of library ops, and org/project custom ops. `GET /science/unit-ops` returns the union for the requesting org.

**Architecture:** A `LibraryRegistry` service loads `Library` Pydantic models from one or more `LibrarySource` implementations (today: bundled JSON; tomorrow: remote catalog). The DB gains a `unit_op_library_subscriptions` table and two override-pointer columns on `unit_op_definitions`. The listing endpoint merges JSON ops + DB rows. Override on a JSON op is copy-on-write: PUT inserts a new DB row whose `id` equals the JSON op's synthetic UUID.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest-asyncio. Frontend: Svelte 5 runes, @xyflow/svelte, Zod, shadcn-svelte.

---

## Spec Reference

`docs/superpowers/specs/2026-04-27-f-0075-unit-op-library-design.md` is authoritative. This plan is the execution sequence.

## Phasing

- **Phase 1 (Backend)** — Tasks 1–14. Self-contained backend feature complete with passing tests after Task 14.
- **Phase 2 (Frontend)** — Tasks 15–18. Depends only on Phase 1's response shape addition (`library_slug`).

---

# Phase 1 — Backend

## Task 1: Create the `core` library JSON file

**Files:**
- Create: `backend/app/data/unit_op_libraries/core.json`

The file holds all 12 ops with full param schemas. We migrate the 6 schemas that already exist in `backend/app/db/seed.py` for ops that survive the cut, generalize `Buffer Preparation` → `Solution Preparation`, and write minimal schemas for the 5 new ops.

- [ ] **Step 1: Create the directory**

```bash
mkdir -p backend/app/data/unit_op_libraries
```

- [ ] **Step 2: Write `core.json`**

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
      "description": "Prepare {{volume_L}}L of {{solution_name}} by dissolving {{components}} in {{solvent}}. Adjust to pH {{pH_target}} (+/- {{pH_tolerance}}) using {{pH_agent}}. Store at {{storage_temp_c}}°C.",
      "param_schema": {
        "type": "object",
        "properties": {
          "solution_name": {"type": "string", "title": "Solution Name", "default": "PBS"},
          "volume_L": {"type": "number", "title": "Final Volume (L)", "default": 10},
          "components": {"type": "string", "title": "Components", "default": "NaCl, KCl, Na2HPO4, KH2PO4"},
          "concentration_mM": {"type": "number", "title": "Target Concentration (mM)", "default": 137},
          "pH_target": {"type": "number", "title": "Target pH", "default": 7.4},
          "pH_tolerance": {"type": "number", "title": "pH Tolerance (+/-)", "default": 0.1},
          "pH_agent": {"type": "string", "title": "pH Adjustment Agent", "default": "NaOH / HCl"},
          "solvent": {"type": "string", "title": "Solvent", "default": "Water"},
          "storage_temp_c": {"type": "number", "title": "Storage Temperature (C)", "default": 4}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "weigh_solid",
      "name": "Weigh Solid",
      "category": "Preparation",
      "description": "Weigh {{target_mass_g}}g of {{material}} using balance {{balance_id}}.",
      "param_schema": {
        "type": "object",
        "properties": {
          "material": {"type": "string", "title": "Material"},
          "target_mass_g": {"type": "number", "title": "Target Mass (g)"},
          "balance_id": {"type": "string", "title": "Balance ID"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "dispense_liquid",
      "name": "Dispense Liquid",
      "category": "Preparation",
      "description": "Dispense {{volume_ml}}mL of {{liquid}} using {{instrument}}.",
      "param_schema": {
        "type": "object",
        "properties": {
          "liquid": {"type": "string", "title": "Liquid"},
          "volume_ml": {"type": "number", "title": "Volume (mL)"},
          "instrument": {"type": "string", "title": "Instrument"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "aliquot_transfer",
      "name": "Aliquot / Transfer",
      "category": "Preparation",
      "description": "Transfer {{volume_ml}}mL from {{source_vessel}} into {{destination_vessel}}.",
      "param_schema": {
        "type": "object",
        "properties": {
          "source_vessel": {"type": "string", "title": "Source Vessel"},
          "destination_vessel": {"type": "string", "title": "Destination Vessel"},
          "volume_ml": {"type": "number", "title": "Volume (mL)"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "mixing",
      "name": "Mixing",
      "category": "Process",
      "description": "Mix at {{speed_rpm}} RPM for {{duration_min}} minutes at {{temperature_C}}°C.",
      "param_schema": {
        "type": "object",
        "properties": {
          "speed_rpm": {"type": "number"},
          "duration_min": {"type": "number"},
          "temperature_C": {"type": "number"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "ph_adjustment",
      "name": "pH Adjustment",
      "category": "Process",
      "description": "Adjust solution to pH {{target_pH}} using {{acid_or_base}}.",
      "param_schema": {
        "type": "object",
        "properties": {
          "target_pH": {"type": "number"},
          "acid_or_base": {"type": "string"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "centrifugation",
      "name": "Centrifugation",
      "category": "Process",
      "description": "Centrifuge at {{rcf_g}}xg for {{duration_min}} minutes at {{temperature_C}}°C.",
      "param_schema": {
        "type": "object",
        "properties": {
          "rcf_g": {"type": "number"},
          "duration_min": {"type": "number"},
          "temperature_C": {"type": "number"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "filtration",
      "name": "Filtration",
      "category": "Process",
      "description": "Filter {{volume_L}}L through {{filter_type}} membrane ({{filter_size_um}}um pore size).",
      "param_schema": {
        "type": "object",
        "properties": {
          "filter_size_um": {"type": "number"},
          "filter_type": {"type": "string"},
          "volume_L": {"type": "number"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "temperature_hold",
      "name": "Temperature Hold",
      "category": "Process",
      "description": "Hold {{vessel}} at {{temperature_C}}°C for {{duration_min}} minutes.",
      "param_schema": {
        "type": "object",
        "properties": {
          "temperature_C": {"type": "number", "title": "Temperature (C)"},
          "duration_min": {"type": "number", "title": "Duration (min)"},
          "vessel": {"type": "string", "title": "Vessel"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "sample_collection",
      "name": "Sample Collection",
      "category": "Analytics",
      "description": "Collect {{volume_mL}}mL sample into {{container_type}}, store at {{storage_temp_C}}°C.",
      "param_schema": {
        "type": "object",
        "properties": {
          "volume_mL": {"type": "number"},
          "container_type": {"type": "string"},
          "storage_temp_C": {"type": "number"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "visual_inspection",
      "name": "Visual Inspection",
      "category": "QC",
      "description": "Perform {{inspection_type}} visual inspection. Acceptance criteria: {{acceptance_criteria}}.",
      "param_schema": {
        "type": "object",
        "properties": {
          "inspection_type": {"type": "string"},
          "acceptance_criteria": {"type": "string"}
        }
      },
      "result_schema": {}
    },
    {
      "slug": "storage",
      "name": "Storage",
      "category": "Logistics",
      "description": "Store {{material}} in {{container}} at {{storage_temp_C}}°C.",
      "param_schema": {
        "type": "object",
        "properties": {
          "material": {"type": "string", "title": "Material"},
          "storage_temp_C": {"type": "number", "title": "Storage Temperature (C)"},
          "container": {"type": "string", "title": "Container"}
        }
      },
      "result_schema": {}
    }
  ]
}
```

- [ ] **Step 3: Verify JSON parses**

Run: `python -c "import json; json.load(open('backend/app/data/unit_op_libraries/core.json'))"`
Expected: no output (success). Any error → fix the file.

- [ ] **Step 4: Commit**

```bash
git add backend/app/data/unit_op_libraries/core.json
git commit -m "feat(F-0075): add core unit op library JSON catalog"
```

---

## Task 2: Library Pydantic models + Registry skeleton

**Files:**
- Create: `backend/app/services/science/__init__.py`
- Create: `backend/app/services/science/library_registry.py`
- Create: `backend/tests/integration/test_library_registry.py`

This task lays down the registry types, source abstraction, cache, and synthetic-UUID helper. No DB or HTTP yet; pure unit-style tests against the in-process registry.

- [ ] **Step 1: Create the package**

```bash
mkdir -p backend/app/services/science
touch backend/app/services/science/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/integration/test_library_registry.py`:

```python
"""Tests for the unit op library registry (F-0075)."""
import uuid
from pathlib import Path

import pytest

from app.services.science import library_registry as lr


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with an empty registry."""
    lr._reset_for_tests()
    yield
    lr._reset_for_tests()


@pytest.mark.asyncio
async def test_synthetic_uuid_is_deterministic():
    a = lr.synthetic_uuid("core", "mixing")
    b = lr.synthetic_uuid("core", "mixing")
    assert a == b
    assert isinstance(a, uuid.UUID)


@pytest.mark.asyncio
async def test_synthetic_uuid_differs_per_op():
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid("core", "centrifugation")
    assert lr.synthetic_uuid("core", "mixing") != lr.synthetic_uuid("other", "mixing")


@pytest.mark.asyncio
async def test_bundled_source_loads_core_library():
    src = lr.BundledJSONSource(
        Path("backend/app/data/unit_op_libraries").resolve()
    )
    libs = await src.load()
    assert len(libs) == 1
    core = libs[0]
    assert core.slug == "core"
    assert core.is_default is True
    assert core.version == "1.0.0"
    assert len(core.unit_ops) == 12
    slugs = {op.slug for op in core.unit_ops}
    assert "solution_preparation" in slugs
    assert "mixing" in slugs
    assert "storage" in slugs


@pytest.mark.asyncio
async def test_register_and_reload_populates_cache():
    fake = _FakeSource([
        lr.Library(
            slug="alpha", name="Alpha", domain="general",
            description="", is_default=True, version="1.0.0",
            unit_ops=[
                lr.UnitOp(
                    slug="op_one", name="Op One", category="Cat",
                    description="", param_schema={}, result_schema={},
                ),
            ],
        ),
    ])
    lr.register_source(fake)
    await lr.reload_libraries()

    assert [lib.slug for lib in lr.list_libraries()] == ["alpha"]
    assert lr.get_library("alpha") is not None
    assert lr.get_op("alpha", "op_one") is not None
    assert lr.get_op("alpha", "missing") is None
    assert lr.default_library_slugs() == ["alpha"]


@pytest.mark.asyncio
async def test_reload_is_atomic_on_source_failure():
    fake_ok = _FakeSource([
        lr.Library(slug="good", name="Good", domain="general",
                   description="", is_default=False, version="1",
                   unit_ops=[]),
    ])
    lr.register_source(fake_ok)
    await lr.reload_libraries()
    assert lr.get_library("good") is not None

    # Replace with a failing source. Reload must raise but leave cache intact.
    lr._reset_sources_for_tests()
    lr.register_source(_FailingSource())
    with pytest.raises(RuntimeError):
        await lr.reload_libraries()
    assert lr.get_library("good") is not None  # cache unchanged


@pytest.mark.asyncio
async def test_last_source_wins_on_slug_collision():
    earlier = _FakeSource([
        lr.Library(slug="x", name="Earlier", domain="general",
                   description="", is_default=False, version="1",
                   unit_ops=[]),
    ])
    later = _FakeSource([
        lr.Library(slug="x", name="Later", domain="general",
                   description="", is_default=False, version="2",
                   unit_ops=[]),
    ])
    lr.register_source(earlier)
    lr.register_source(later)
    await lr.reload_libraries()
    assert lr.get_library("x").name == "Later"


# --- Helpers ---


class _FakeSource:
    def __init__(self, libs: list):
        self._libs = libs
    async def load(self):
        return self._libs


class _FailingSource:
    async def load(self):
        raise RuntimeError("boom")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_library_registry.py -v`
Expected: ImportError / ModuleNotFoundError on `app.services.science.library_registry`.

- [ ] **Step 4: Implement `library_registry.py`**

Create `backend/app/services/science/library_registry.py`:

```python
"""Unit operation library registry (F-0075).

Loads versioned JSON catalogs of unit operations and serves them to the
rest of the app. Designed so that adding new sources (e.g. a remote
catalog for on-prem deployments) is plumbing rather than architecture.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Stable namespace for synthetic UUIDs. Pinned in code so that
# `synthetic_uuid("core", "mixing")` returns the same value across
# every deployment, every source, every process.
_NAMESPACE: uuid.UUID = uuid.UUID("4e6b6c9a-1f8c-4f4e-8a16-bbcd0750f000")


class UnitOp(BaseModel):
    slug: str
    name: str
    category: str
    description: str = ""
    param_schema: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)


class Library(BaseModel):
    slug: str
    name: str
    domain: str
    description: str = ""
    is_default: bool = False
    version: str
    unit_ops: list[UnitOp]


class LibrarySource(Protocol):
    async def load(self) -> list[Library]:  # pragma: no cover - protocol
        ...


class BundledJSONSource:
    """Loads every *.json file under a directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    async def load(self) -> list[Library]:
        libs: list[Library] = []
        if not self.directory.exists():
            return libs
        for path in sorted(self.directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            libs.append(Library.model_validate(raw))
        return libs


# --- Module-level state ---

_sources: list[LibrarySource] = []
_cache: dict[str, Library] = {}


def register_source(source: LibrarySource) -> None:
    """Register a LibrarySource. Call before reload_libraries()."""
    _sources.append(source)


async def reload_libraries() -> None:
    """Re-read every registered source and atomically replace the cache.

    Builds the new dict first; only swaps if every source loads OK.
    Last-source-wins on slug collisions.
    """
    new_cache: dict[str, Library] = {}
    for source in _sources:
        for lib in await source.load():
            new_cache[lib.slug] = lib
    global _cache
    _cache = new_cache


def list_libraries() -> list[Library]:
    return list(_cache.values())


def get_library(slug: str) -> Optional[Library]:
    return _cache.get(slug)


def get_op(library_slug: str, op_slug: str) -> Optional[UnitOp]:
    lib = _cache.get(library_slug)
    if lib is None:
        return None
    for op in lib.unit_ops:
        if op.slug == op_slug:
            return op
    return None


def synthetic_uuid(library_slug: str, op_slug: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{library_slug}/{op_slug}")


def default_library_slugs() -> list[str]:
    return [lib.slug for lib in _cache.values() if lib.is_default]


async def subscribe_default_libraries(
    db: AsyncSession, org_id: uuid.UUID,
) -> None:
    """Insert subscription rows for every default library. Idempotent.

    Imported lazily to avoid a circular import (model imports the
    registry indirectly via the schemas module).
    """
    from app.models.science import UnitOpLibrarySubscription  # noqa: WPS433

    existing_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    existing = {row[0] for row in existing_q.all()}
    for slug in default_library_slugs():
        if slug in existing:
            continue
        db.add(UnitOpLibrarySubscription(
            organization_id=org_id, library_slug=slug,
        ))
    await db.flush()


# --- Test helpers ---

def _reset_for_tests() -> None:
    """Clear sources and cache. Tests only."""
    _sources.clear()
    _cache.clear()


def _reset_sources_for_tests() -> None:
    """Clear sources but keep cache. Tests only."""
    _sources.clear()
```

- [ ] **Step 5: Run tests; the bundled-source test still fails**

Run: `cd backend && pytest tests/integration/test_library_registry.py -v`
Expected: 5 of 6 tests pass; `test_bundled_source_loads_core_library` may fail because the path is relative — fix in step 6.

- [ ] **Step 6: Verify the bundled-source test path resolution**

If `test_bundled_source_loads_core_library` fails with "no libraries found", adjust the test path:

```python
# Replace
src = lr.BundledJSONSource(
    Path("backend/app/data/unit_op_libraries").resolve()
)
# With (relative to the backend/ dir, which is pytest's cwd)
src = lr.BundledJSONSource(
    Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
)
```

Run: `cd backend && pytest tests/integration/test_library_registry.py -v`
Expected: all 6 tests pass.

- [ ] **Step 7: subscribe_default_libraries test**

The `subscribe_default_libraries` function references a model that doesn't exist yet. We test it once the model lands (Task 3). For now, leave the function implemented but unexercised.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/science backend/tests/integration/test_library_registry.py
git commit -m "feat(F-0075): add library registry, source abstraction, synthetic UUIDs"
```

---

## Task 3: Models — `UnitOpLibrarySubscription` + override columns

**Files:**
- Modify: `backend/app/models/science.py` (around line 233)
- Modify: `backend/app/schemas/science.py` (around line 9)

- [ ] **Step 1: Add subscription model**

Open `backend/app/models/science.py`. Find the `UnitOpDefinition` class (line 233). Add the following ABOVE it:

```python
class UnitOpLibrarySubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_library_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "library_slug",
            name="uq_unit_op_lib_sub",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    library_slug: Mapped[str] = mapped_column(String, nullable=False)
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    organization: Mapped["app.models.iam.Organization"] = relationship(
        "app.models.iam.Organization",
        foreign_keys=[organization_id],
    )
```

If `UniqueConstraint`, `func`, or `DateTime` aren't already imported in `science.py`, add them. Verify by checking imports at the top of the file.

- [ ] **Step 2: Add override columns to `UnitOpDefinition`**

In the same file, modify the `UnitOpDefinition` class. Add a CHECK constraint to `__table_args__` and two new columns:

```python
class UnitOpDefinition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_op_definitions"
    __table_args__ = (
        CheckConstraint(
            "project_id IS NULL OR organization_id IS NOT NULL",
            name="ck_unit_op_scope_valid",
        ),
        CheckConstraint(
            "(source_library_slug IS NULL AND source_op_slug IS NULL) OR "
            "(source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)",
            name="ck_unit_op_source_both_or_neither",
        ),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(
        String, nullable=False, default="General"
    )
    description: Mapped[Optional[str]] = mapped_column(String)

    param_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict
    )
    result_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )

    # Library override pointers (F-0075). Set when this row overrides a
    # JSON op; the row's id equals synthetic_uuid(slug, op_slug).
    source_library_slug: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
    )
    source_op_slug: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
    )

    organization: Mapped[Optional["app.models.iam.Organization"]] = relationship(
        "app.models.iam.Organization", foreign_keys=[organization_id]
    )
    project: Mapped[Optional["Project"]] = relationship(
        foreign_keys=[project_id]
    )
```

- [ ] **Step 3: Add `library_slug` to the response schema**

Open `backend/app/schemas/science.py`. Modify `UnitOpDefinitionResponse`:

```python
class UnitOpDefinitionResponse(UnitOpDefinitionBase):
    id: UUID
    organization_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    library_slug: Optional[str] = None  # F-0075: identifies JSON library origin
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope(self) -> Literal["global", "organization", "project"]:
        if self.project_id is not None:
            return "project"
        elif self.organization_id is not None:
            return "organization"
        return "global"

    class Config:
        from_attributes = True
```

Note: the field is named `library_slug` on the response. Internally, the DB column is `source_library_slug`; the listing endpoint maps between them.

- [ ] **Step 4: Verify the model imports cleanly**

Run: `cd backend && python -c "from app.models.science import UnitOpLibrarySubscription, UnitOpDefinition; print(UnitOpDefinition.source_library_slug)"`
Expected: prints the column. Any import error → fix.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/science.py backend/app/schemas/science.py
git commit -m "feat(F-0075): add UnitOpLibrarySubscription model and override pointer columns"
```

---

## Task 4: Alembic migration

**Files:**
- Create: `backend/alembic/versions/<rev>_unit_op_library_abstraction.py` (alembic generates the rev id)

- [ ] **Step 1: Generate the migration**

Run: `cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "unit op library abstraction"`
Expected: a new file `backend/alembic/versions/<somehex>_unit_op_library_abstraction.py`.

- [ ] **Step 2: Open the file and replace the body**

The autogenerate output handles table/column creation but doesn't include the data deletes/inserts. Replace `upgrade()` and `downgrade()` with:

```python
def upgrade() -> None:
    op.create_table(
        "unit_op_library_subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("library_slug", sa.String(), nullable=False),
        sa.Column(
            "subscribed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "library_slug", name="uq_unit_op_lib_sub",
        ),
    )

    op.add_column(
        "unit_op_definitions",
        sa.Column("source_library_slug", sa.String(), nullable=True),
    )
    op.add_column(
        "unit_op_definitions",
        sa.Column("source_op_slug", sa.String(), nullable=True),
    )

    op.create_check_constraint(
        "ck_unit_op_source_both_or_neither",
        "unit_op_definitions",
        "(source_library_slug IS NULL AND source_op_slug IS NULL) OR "
        "(source_library_slug IS NOT NULL AND source_op_slug IS NOT NULL)",
    )

    # Drop existing global rows. Protocol graphs that reference them
    # become orphan-id references — acceptable per F-0075 spec.
    op.execute(
        "DELETE FROM unit_op_definitions "
        "WHERE organization_id IS NULL AND project_id IS NULL"
    )

    # Backfill subscriptions: every existing org gets the 'core' library.
    op.execute(
        "INSERT INTO unit_op_library_subscriptions "
        "(id, organization_id, library_slug, subscribed_at, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, 'core', now(), now(), now() "
        "FROM organizations"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_unit_op_source_both_or_neither",
        "unit_op_definitions",
        type_="check",
    )
    op.drop_column("unit_op_definitions", "source_op_slug")
    op.drop_column("unit_op_definitions", "source_library_slug")
    op.drop_table("unit_op_library_subscriptions")
```

Keep the `revision`, `down_revision`, `branch_labels`, `depends_on` lines from the autogenerated file as-is.

- [ ] **Step 3: Apply the migration locally**

Run: `cd backend && source .venv/bin/activate && alembic upgrade head`
Expected: "INFO ... Running upgrade ... unit op library abstraction" then no errors.

- [ ] **Step 4: Verify the schema**

Run: `psql -U postgres -d batchrite -c "\d unit_op_library_subscriptions"`
Expected: shows columns `id, organization_id, library_slug, subscribed_at, created_at, updated_at` and unique constraint.

Run: `psql -U postgres -d batchrite -c "\d unit_op_definitions" | grep source`
Expected: shows the two `source_*` columns.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_unit_op_library_abstraction.py
git commit -m "feat(F-0075): alembic migration for library subscriptions and override columns"
```

---

## Task 5: Update conftest fixtures and test `subscribe_default_libraries`

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/integration/test_library_registry.py`

The test DB is built via `Base.metadata.create_all`, not Alembic, so the migration's "subscribe every org to core" doesn't fire in tests. We mirror the production behavior in fixtures.

- [ ] **Step 1: Update `test_org` and `second_org` fixtures**

Open `backend/tests/conftest.py`. After both `test_org` and `second_org` fixtures, add a subscription step. Replace `test_org`:

```python
@pytest_asyncio.fixture
async def test_org(db_session) -> Organization:
    org = Organization(name="Test Org")
    db_session.add(org)
    await db_session.flush()
    # Mirror production: every org auto-subscribes to default libraries.
    from app.services.science import library_registry
    if library_registry.list_libraries():  # registry seeded by app startup
        await library_registry.subscribe_default_libraries(db_session, org.id)
    return org
```

Apply the same change to `second_org`.

- [ ] **Step 2: Add a fixture that ensures the registry is loaded**

Tests don't run app startup. Add an autouse session-scoped fixture in `conftest.py` (top of file, after imports):

```python
@pytest_asyncio.fixture(scope="session", autouse=True)
async def _seed_library_registry():
    """Load bundled libraries once for the test session.

    Mirrors what FastAPI lifespan does in production. Tests that need
    different sources can call library_registry._reset_for_tests() and
    register their own.
    """
    from pathlib import Path
    from app.services.science import library_registry as lr
    lr._reset_for_tests()
    lr.register_source(
        lr.BundledJSONSource(
            Path(__file__).resolve().parents[1] / "app/data/unit_op_libraries"
        )
    )
    await lr.reload_libraries()
    yield
```

- [ ] **Step 3: Add a test for subscribe_default_libraries**

Append to `backend/tests/integration/test_library_registry.py`:

```python
@pytest.mark.asyncio
async def test_subscribe_default_libraries_idempotent(
    db_session, test_org,
):
    """subscribe_default_libraries can be called repeatedly without error."""
    from app.models.science import UnitOpLibrarySubscription
    from sqlalchemy import select, func

    # test_org fixture already subscribed once. Calling again does nothing.
    await lr.subscribe_default_libraries(db_session, test_org.id)
    await lr.subscribe_default_libraries(db_session, test_org.id)

    count = await db_session.execute(
        select(func.count()).select_from(UnitOpLibrarySubscription).where(
            UnitOpLibrarySubscription.organization_id == test_org.id,
        )
    )
    assert count.scalar() == 1  # still just core
```

Note: this test depends on the `_seed_library_registry` autouse session fixture having loaded `core`. The autouse fixture in conftest.py seeds globally, but the `_reset_registry` autouse function fixture in this test file clears it. Update the per-test reset to re-seed instead of fully clearing:

```python
@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with the seeded session-scope registry, plus a
    chance to register additional sources. The test_subscribe test
    relies on the seeded `core` library."""
    from pathlib import Path
    lr._reset_for_tests()
    lr.register_source(
        lr.BundledJSONSource(
            Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
        )
    )
    import asyncio
    asyncio.get_event_loop().run_until_complete(lr.reload_libraries())
    yield
    lr._reset_for_tests()
```

But `asyncio.get_event_loop().run_until_complete` inside a sync fixture isn't safe with pytest-asyncio. Simpler: make the cache management in `library_registry.py` aware that the bundled source is the default, or convert `_reset_registry` to async. Take the async approach:

Replace `_reset_registry` with:

```python
@pytest_asyncio.fixture(autouse=True)
async def _reset_registry():
    from pathlib import Path
    lr._reset_for_tests()
    lr.register_source(
        lr.BundledJSONSource(
            Path(__file__).resolve().parents[2] / "app/data/unit_op_libraries"
        )
    )
    await lr.reload_libraries()
    yield
    lr._reset_for_tests()
```

Tests in this file that need a clean registry (e.g., `test_register_and_reload_populates_cache`) call `lr._reset_for_tests()` themselves at the top.

Update `test_register_and_reload_populates_cache`, `test_reload_is_atomic_on_source_failure`, `test_last_source_wins_on_slug_collision` to begin with `lr._reset_for_tests()` so they start clean.

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/integration/test_library_registry.py -v`
Expected: all tests pass, including `test_subscribe_default_libraries_idempotent`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/integration/test_library_registry.py
git commit -m "test(F-0075): seed library registry in conftest, auto-subscribe test orgs"
```

---

## Task 6: Hook `subscribe_default_libraries` into org creation

**Files:**
- Modify: `backend/app/api/endpoints/auth.py` (around line 126)
- Modify: `backend/app/api/endpoints/iam.py` (around line 89)
- Create: integration test cases in `backend/tests/integration/test_library_registry.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_library_registry.py`:

```python
@pytest.mark.asyncio
async def test_register_endpoint_subscribes_new_org_to_core(
    client, db_session,
):
    """A user signing up gets a new org auto-subscribed to 'core'."""
    from app.models.iam import Organization
    from app.models.science import UnitOpLibrarySubscription
    from sqlalchemy import select

    resp = await client.post("/auth/register", json={
        "email": "newuser@example.com",
        "password": "testpass123",
        "full_name": "New User",
    })
    assert resp.status_code in (200, 201), resp.text

    # Find the org that was just created
    org_q = await db_session.execute(
        select(Organization).where(Organization.name.like("%New User%"))
    )
    org = org_q.scalar_one()

    sub_q = await db_session.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org.id,
        )
    )
    assert "core" in {row[0] for row in sub_q.all()}


@pytest.mark.asyncio
async def test_create_org_endpoint_subscribes_to_core(
    client, auth_headers, db_session,
):
    """POST /iam/organizations subscribes the new org to defaults."""
    from app.models.iam import Organization
    from app.models.science import UnitOpLibrarySubscription
    from sqlalchemy import select

    resp = await client.post(
        "/iam/organizations", json={"name": "Second Workspace"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_org_id = resp.json()["id"]

    sub_q = await db_session.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == new_org_id,
        )
    )
    assert "core" in {row[0] for row in sub_q.all()}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_library_registry.py::test_register_endpoint_subscribes_new_org_to_core tests/integration/test_library_registry.py::test_create_org_endpoint_subscribes_to_core -v`
Expected: FAIL — no subscription rows.

- [ ] **Step 3: Patch `auth.py` register endpoint**

Open `backend/app/api/endpoints/auth.py`. Find line ~126 where `Organization(name=org_name)` is created. Just after `await db.flush()` (which gives the org an id) and *before* the user is created, add:

```python
# F-0075: subscribe new org to default unit op libraries
from app.services.science import library_registry
await library_registry.subscribe_default_libraries(db, org.id)
```

The `subscribe_default_libraries` call uses `db.flush()` internally, which is what we want.

- [ ] **Step 4: Patch `iam.py` create_organization**

Open `backend/app/api/endpoints/iam.py`. Find line ~89 (`Organization(name=body.name)`). After the existing `db.add(org); await db.flush()` and before the membership row is added, insert:

```python
# F-0075: subscribe new org to default unit op libraries
from app.services.science import library_registry
await library_registry.subscribe_default_libraries(db, org.id)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/integration/test_library_registry.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/app/api/endpoints/iam.py backend/tests/integration/test_library_registry.py
git commit -m "feat(F-0075): auto-subscribe new orgs to default libraries on creation"
```

---

## Task 7: Rewrite `GET /science/unit-ops` — union assembly

**Files:**
- Modify: `backend/app/api/endpoints/unit_ops.py`
- Modify: `backend/tests/integration/test_unit_ops_scoping.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_unit_ops_scoping.py` (just before any existing test):

```python
# --- F-0075 union-assembly tests ---


@pytest.mark.asyncio
async def test_list_returns_subscribed_library_ops(
    client: AsyncClient, auth_headers: dict,
):
    """An org subscribed to 'core' sees all 12 core ops."""
    resp = await client.get("/science/unit-ops", headers=auth_headers)
    assert resp.status_code == 200
    ops = resp.json()
    names = {op["name"] for op in ops}
    assert "Solution Preparation" in names
    assert "Mixing" in names
    assert "Storage" in names
    # All core ops carry library_slug
    core_ops = [op for op in ops if op.get("library_slug") == "core"]
    assert len(core_ops) == 12


@pytest.mark.asyncio
async def test_list_excludes_unsubscribed_library_ops(
    client: AsyncClient, db_session, second_org,
):
    """An org NOT subscribed to a library doesn't see its ops.
    second_org's subscription is provided by the fixture; remove it."""
    from app.models.science import UnitOpLibrarySubscription
    from sqlalchemy import delete
    from app.core.security import create_access_token

    await db_session.execute(
        delete(UnitOpLibrarySubscription).where(
            UnitOpLibrarySubscription.organization_id == second_org.id,
        )
    )
    await db_session.flush()

    # Create a user attached to second_org with no library subscription
    from app.models.iam import User, OrganizationMember
    from app.core.security import hash_password
    user = User(
        email="lonely@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Lonely User",
        selected_org_id=second_org.id,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=user.id, organization_id=second_org.id, role="ADMIN",
    ))
    await db_session.flush()

    token = create_access_token(
        user.id, org_id=second_org.id,
        subscription_tier=second_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/science/unit-ops", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []  # no library, no custom ops
```

- [ ] **Step 2: Run tests; expect failures**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py::test_list_returns_subscribed_library_ops -v`
Expected: FAIL — current endpoint doesn't know about libraries.

- [ ] **Step 3: Rewrite the listing endpoint**

Replace the `list_unit_ops` function in `backend/app/api/endpoints/unit_ops.py` (around line 42):

```python
@router.get("/unit-ops", response_model=List[UnitOpDefinitionResponse])
async def list_unit_ops(
    project_id: Optional[UUID] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.science import UnitOpLibrarySubscription
    from app.services.science import library_registry

    org_id = user.selected_org_id
    if org_id is None:
        return []

    # 1. JSON ops from subscribed libraries
    sub_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    subscribed_slugs = {row[0] for row in sub_q.all()}

    by_id: dict[UUID, dict] = {}
    for slug in subscribed_slugs:
        lib = library_registry.get_library(slug)
        if lib is None:
            continue
        for op in lib.unit_ops:
            synth_id = library_registry.synthetic_uuid(slug, op.slug)
            by_id[synth_id] = {
                "id": synth_id,
                "name": op.name,
                "category": op.category,
                "description": op.description,
                "param_schema": op.param_schema,
                "result_schema": op.result_schema,
                "organization_id": None,
                "project_id": None,
                "library_slug": slug,
                "created_at": _LIB_TIMESTAMP,
                "updated_at": _LIB_TIMESTAMP,
            }

    # 2. DB rows for this org (overrides + custom org ops)
    db_q = await db.execute(
        select(UnitOpDefinition).where(
            UnitOpDefinition.organization_id == org_id,
            UnitOpDefinition.project_id.is_(None),
        )
    )
    for row in db_q.scalars():
        by_id[row.id] = _row_to_response_dict(row)

    # 3. Project-scoped ops if requested
    if project_id is not None:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, project_id, PermissionLevel.VIEW,
        )
        if allowed:
            proj_q = await db.execute(
                select(UnitOpDefinition).where(
                    UnitOpDefinition.project_id == project_id,
                )
            )
            for row in proj_q.scalars():
                by_id[row.id] = _row_to_response_dict(row)

    return list(by_id.values())


def _row_to_response_dict(row: UnitOpDefinition) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "param_schema": row.param_schema,
        "result_schema": row.result_schema,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "library_slug": row.source_library_slug,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
```

Add at the top of the file:

```python
from datetime import datetime, timezone

# Synthetic timestamp for JSON-only ops. They have no real created_at;
# pin to epoch so the response shape is consistent.
_LIB_TIMESTAMP = datetime(1970, 1, 1, tzinfo=timezone.utc)
```

- [ ] **Step 4: Run new tests**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py::test_list_returns_subscribed_library_ops tests/integration/test_unit_ops_scoping.py::test_list_excludes_unsubscribed_library_ops -v`
Expected: PASS.

- [ ] **Step 5: Run the full test_unit_ops_scoping.py file**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py -v`
Expected: many existing tests still fail (they assume the old global model). That's fine — Task 9 fixes them.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/unit_ops.py backend/tests/integration/test_unit_ops_scoping.py
git commit -m "feat(F-0075): GET /science/unit-ops returns library + DB union"
```

---

## Task 8: Rewrite `PUT /science/unit-ops/{id}` — copy-on-write

**Files:**
- Modify: `backend/app/api/endpoints/unit_ops.py`
- Modify: `backend/tests/integration/test_unit_ops_scoping.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_unit_ops_scoping.py`:

```python
# --- F-0075 copy-on-write tests ---


@pytest.mark.asyncio
async def test_put_on_library_op_creates_override(
    client: AsyncClient, auth_headers, db_session, test_org,
):
    """PUT on a JSON op id inserts an override row in this org."""
    from app.services.science import library_registry
    from app.models.science import UnitOpDefinition
    from sqlalchemy import select

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    resp = await client.put(
        f"/science/unit-ops/{synth_id}",
        json={"name": "Custom Mixing"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Custom Mixing"
    assert body["library_slug"] == "core"
    assert body["organization_id"] == str(test_org.id)
    assert body["id"] == str(synth_id)

    # DB has the override row with the same id as the synthetic UUID
    row = await db_session.get(UnitOpDefinition, synth_id)
    assert row is not None
    assert row.source_library_slug == "core"
    assert row.source_op_slug == "mixing"
    assert row.organization_id == test_org.id


@pytest.mark.asyncio
async def test_second_put_updates_existing_override(
    client: AsyncClient, auth_headers, db_session,
):
    from app.services.science import library_registry
    from app.models.science import UnitOpDefinition
    from sqlalchemy import select, func

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    await client.put(
        f"/science/unit-ops/{synth_id}",
        json={"name": "First Rename"},
        headers=auth_headers,
    )
    await client.put(
        f"/science/unit-ops/{synth_id}",
        json={"name": "Second Rename"},
        headers=auth_headers,
    )

    count_q = await db_session.execute(
        select(func.count()).select_from(UnitOpDefinition).where(
            UnitOpDefinition.id == synth_id,
        )
    )
    assert count_q.scalar() == 1

    row = await db_session.get(UnitOpDefinition, synth_id)
    assert row.name == "Second Rename"


@pytest.mark.asyncio
async def test_override_isolated_per_org(
    client: AsyncClient, auth_headers, second_auth_headers,
):
    """An override in org A doesn't leak into org B's listing."""
    from app.services.science import library_registry

    synth_id = library_registry.synthetic_uuid("core", "mixing")

    await client.put(
        f"/science/unit-ops/{synth_id}",
        json={"name": "Org-A Mixing"},
        headers=auth_headers,
    )

    resp_b = await client.get("/science/unit-ops", headers=second_auth_headers)
    assert resp_b.status_code == 200
    by_id = {op["id"]: op for op in resp_b.json()}
    # Org B still sees the original Mixing, not "Org-A Mixing"
    assert by_id[str(synth_id)]["name"] == "Mixing"


@pytest.mark.asyncio
async def test_put_on_unknown_uuid_returns_404(
    client: AsyncClient, auth_headers,
):
    import uuid as _uuid
    bogus = _uuid.uuid4()
    resp = await client.put(
        f"/science/unit-ops/{bogus}",
        json={"name": "Whatever"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests; expect failures**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py::test_put_on_library_op_creates_override -v`
Expected: FAIL with 404.

- [ ] **Step 3: Rewrite the PUT endpoint**

Replace `update_unit_op` in `backend/app/api/endpoints/unit_ops.py`:

```python
@router.put(
    "/unit-ops/{unit_op_id}",
    response_model=UnitOpDefinitionResponse,
)
async def update_unit_op(
    unit_op_id: UUID,
    update_data: UnitOpDefinitionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    from app.models.science import UnitOpLibrarySubscription
    from app.services.science import library_registry

    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(400, "No organization selected")

    # 1. Try the DB
    row = await db.execute(
        select(UnitOpDefinition).where(UnitOpDefinition.id == unit_op_id)
    )
    unit_op = row.scalar_one_or_none()

    if unit_op is None:
        # 2. Maybe it's a JSON op — find the (library, op) producing this UUID
        op_match = _find_subscribed_json_op(
            db, org_id, unit_op_id,
        )
        op_match = await op_match  # _find_subscribed_json_op is async
        if op_match is None:
            raise HTTPException(404, "Unit op not found")
        # Copy-on-write: org admin only.
        await _require_org_admin(db, user.id, org_id)
        lib_slug, op = op_match
        unit_op = UnitOpDefinition(
            id=unit_op_id,
            name=op.name,
            category=op.category,
            description=op.description,
            param_schema=op.param_schema,
            result_schema=op.result_schema,
            organization_id=org_id,
            project_id=None,
            source_library_slug=lib_slug,
            source_op_slug=op.slug,
        )
        for key, value in update_data.model_dump(exclude_unset=True).items():
            setattr(unit_op, key, value)
        db.add(unit_op)
        await db.commit()
        await db.refresh(unit_op)
        return _row_to_response_dict(unit_op)

    # 3. Existing DB row — permission depends on scope
    if unit_op.project_id is not None:
        allowed = await check_permission(
            db, user.id, ObjectType.PROJECT, unit_op.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise HTTPException(403, "Insufficient permissions")
    elif unit_op.organization_id is not None:
        await _require_org_admin(db, user.id, unit_op.organization_id)
    else:
        # No NULL/NULL rows should exist post-migration; defensive 403
        raise HTTPException(403, "Read-only unit op")

    changes = update_data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(unit_op, key, value)

    await db.commit()
    await db.refresh(unit_op)
    return _row_to_response_dict(unit_op)


async def _find_subscribed_json_op(
    db: AsyncSession, org_id: UUID, target_id: UUID,
) -> Optional[tuple[str, "library_registry.UnitOp"]]:
    """Walk every subscribed library; return (slug, op) if its synthetic
    UUID equals target_id, else None."""
    from app.models.science import UnitOpLibrarySubscription
    from app.services.science import library_registry

    sub_q = await db.execute(
        select(UnitOpLibrarySubscription.library_slug).where(
            UnitOpLibrarySubscription.organization_id == org_id,
        )
    )
    for (slug,) in sub_q.all():
        lib = library_registry.get_library(slug)
        if lib is None:
            continue
        for op in lib.unit_ops:
            if library_registry.synthetic_uuid(slug, op.slug) == target_id:
                return (slug, op)
    return None
```

Note: `_row_to_response_dict` defined in Task 7. Make sure the PUT endpoint returns through it so the response shape includes `library_slug`.

Also: the `await op_match = _find_subscribed_json_op(...)` line above is awkward. Replace with a clean two-step:

```python
op_match = await _find_subscribed_json_op(db, org_id, unit_op_id)
if op_match is None:
    raise HTTPException(404, "Unit op not found")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py::test_put_on_library_op_creates_override tests/integration/test_unit_ops_scoping.py::test_second_put_updates_existing_override tests/integration/test_unit_ops_scoping.py::test_override_isolated_per_org tests/integration/test_unit_ops_scoping.py::test_put_on_unknown_uuid_returns_404 -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/unit_ops.py backend/tests/integration/test_unit_ops_scoping.py
git commit -m "feat(F-0075): copy-on-write override on PUT to library op id"
```

---

## Task 9: Update existing `test_unit_ops_scoping.py` tests

**Files:**
- Modify: `backend/tests/integration/test_unit_ops_scoping.py`

The existing tests assume the legacy `global` (NULL/NULL) row pattern. Several break under the new model.

- [ ] **Step 1: Remove the `global_unit_op` fixture and tests that relied on it**

Open `backend/tests/integration/test_unit_ops_scoping.py`. Delete the `global_unit_op` fixture. Update / replace these tests:

| Old test | Action |
|---|---|
| `test_list_returns_global_ops` | Replace body: assert "Mixing" (a core lib op) appears in the response — already covered by `test_list_returns_subscribed_library_ops`. **Delete this test** (redundant). |
| `test_list_union_returns_all_scopes` | Keep, but remove the `global_unit_op` fixture from its parameters. The library subscription gives "Mixing" automatically. Replace `assert "Seeding" in names` with `assert "Mixing" in names`. |
| `test_response_includes_scope_field` | Same — remove `global_unit_op` parameter, replace `ops["Seeding"]` with `ops["Mixing"]`. JSON ops report `scope == "global"`. |
| `test_update_global_op_forbidden` | **Delete** — superseded by `test_put_on_library_op_creates_override`. |

Concretely, in the file:

1. Delete the fixture `global_unit_op` (lines ~54-66).
2. Delete `test_list_returns_global_ops` entirely.
3. Edit `test_list_union_returns_all_scopes`:

```python
@pytest.mark.asyncio
async def test_list_union_returns_all_scopes(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    other_org_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """With project_id param, returns library ops + org + project, not other orgs."""
    resp = await client.get(
        f"/science/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [op["name"] for op in resp.json()]
    assert "Mixing" in names  # library op (replaces "Seeding")
    assert "Org Wash Step" in names
    assert "Project Test Step" in names
    assert "Other Org Step" not in names
```

4. Edit `test_response_includes_scope_field`:

```python
@pytest.mark.asyncio
async def test_response_includes_scope_field(
    client: AsyncClient,
    auth_headers: dict,
    org_unit_op: UnitOpDefinition,
    project_unit_op: UnitOpDefinition,
    test_project: Project,
):
    """Response should include computed scope field."""
    resp = await client.get(
        f"/science/unit-ops?project_id={test_project.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    ops = {op["name"]: op for op in resp.json()}
    assert ops["Mixing"]["scope"] == "global"
    assert ops["Org Wash Step"]["scope"] == "organization"
    assert ops["Project Test Step"]["scope"] == "project"
```

5. Delete `test_update_global_op_forbidden` entirely.

- [ ] **Step 2: Run the full test file**

Run: `cd backend && pytest tests/integration/test_unit_ops_scoping.py -v`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_unit_ops_scoping.py
git commit -m "test(F-0075): update unit-ops scoping tests for library-based model"
```

---

## Task 10: `POST /admin/libraries/reload` endpoint

**Files:**
- Create: `backend/app/api/endpoints/admin.py`
- Modify: `backend/app/main.py`
- Append tests to: `backend/tests/integration/test_library_registry.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/integration/test_library_registry.py`:

```python
@pytest.mark.asyncio
async def test_admin_reload_endpoint_as_org_admin(
    client, auth_headers,
):
    resp = await client.post(
        "/admin/libraries/reload", headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "libraries" in body
    slugs = {entry["slug"] for entry in body["libraries"]}
    assert "core" in slugs
    core = next(e for e in body["libraries"] if e["slug"] == "core")
    assert core["op_count"] == 12
    assert core["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_admin_reload_endpoint_as_member_forbidden(
    client, db_session, test_org,
):
    from app.core.security import hash_password, create_access_token
    from app.models.iam import User, OrganizationMember

    member = User(
        email="member-reload@example.com",
        hashed_password=hash_password("testpass"),
        full_name="Member",
        selected_org_id=test_org.id,
        email_verified=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(OrganizationMember(
        user_id=member.id, organization_id=test_org.id, role="MEMBER",
    ))
    await db_session.flush()
    token = create_access_token(
        member.id, org_id=test_org.id,
        subscription_tier=test_org.subscription_tier,
        email_verified=True,
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/admin/libraries/reload", headers=headers)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests; verify they fail**

Run: `cd backend && pytest tests/integration/test_library_registry.py::test_admin_reload_endpoint_as_org_admin -v`
Expected: FAIL with 404 (no such endpoint).

- [ ] **Step 3: Create `admin.py`**

Create `backend/app/api/endpoints/admin.py`:

```python
"""Admin endpoints (F-0075).

Operations gated on org-admin of the caller's selected org. Today this
covers manual reload of the unit op library cache. As more system-level
operator actions accrete here, consider splitting per concern.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.iam import OrganizationMember, OrgRole, User
from app.services.core.audit import log_audit
from app.services.science import library_registry

logger = logging.getLogger(__name__)
router = APIRouter()


async def _require_org_admin(
    db: AsyncSession, user_id: UUID, org_id: UUID,
) -> None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgRole.ADMIN,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(403, "Org admin role required")


@router.post("/libraries/reload", status_code=200)
async def reload_libraries_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-read every registered LibrarySource. Returns the post-reload
    library inventory. Org-admin gated."""
    org_id = user.selected_org_id
    if org_id is None:
        raise HTTPException(400, "No organization selected")
    await _require_org_admin(db, user.id, org_id)

    await library_registry.reload_libraries()

    libs = library_registry.list_libraries()
    await log_audit(
        db,
        actor_id=user.id,
        action="UPDATE",
        entity_type="library_reload",
        entity_id=org_id,
        changes={"library_count": len(libs)},
    )
    await db.commit()

    return {
        "libraries": [
            {
                "slug": lib.slug,
                "name": lib.name,
                "version": lib.version,
                "op_count": len(lib.unit_ops),
            }
            for lib in libs
        ],
    }
```

- [ ] **Step 4: Mount the router**

Open `backend/app/main.py`. Find the block of `app.include_router(...)` lines (around line 369). Add the import near the other endpoint imports and a corresponding `include_router`:

```python
from app.api.endpoints import admin as admin_endpoints
# ... in the include_router block:
app.include_router(admin_endpoints.router, prefix="/admin", tags=["admin"])
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/integration/test_library_registry.py::test_admin_reload_endpoint_as_org_admin tests/integration/test_library_registry.py::test_admin_reload_endpoint_as_member_forbidden -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/admin.py backend/app/main.py backend/tests/integration/test_library_registry.py
git commit -m "feat(F-0075): admin endpoint for manual library cache reload"
```

---

## Task 11: Wire `library_registry` into FastAPI lifespan

**Files:**
- Modify: `backend/app/main.py`

The registry currently has no source registered when the app boots. Add bundled-source registration + initial reload to the lifespan handler.

- [ ] **Step 1: Modify the lifespan function**

Open `backend/app/main.py`. Find the `lifespan` function (around line 290). Add at the start of the function, before any other startup logic:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: recover stalled work and start heartbeat."""
    # F-0075: load unit op libraries
    from pathlib import Path
    from app.services.science import library_registry
    library_registry.register_source(
        library_registry.BundledJSONSource(
            Path(__file__).resolve().parent / "data/unit_op_libraries"
        )
    )
    try:
        await library_registry.reload_libraries()
    except Exception:
        logger.exception("Library registry initial load failed")
        raise

    # ...existing recovery / template seeding code follows...
```

The path is `backend/app/data/unit_op_libraries`, and `__file__` is `backend/app/main.py`, so `Path(__file__).resolve().parent / "data/unit_op_libraries"` resolves correctly.

- [ ] **Step 2: Smoke-run the app**

Run: `cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8001 &`
Expected: starts without errors. Tail logs for "Library registry initial load failed" — must be absent.

```bash
curl http://localhost:8001/health
# expect 200
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(F-0075): register bundled library source in FastAPI lifespan"
```

---

## Task 12: Update `seed.py`

**Files:**
- Modify: `backend/app/db/seed.py`

- [ ] **Step 1: Delete `seed_unit_ops`**

Open `backend/app/db/seed.py`. Find `async def seed_unit_ops(db: AsyncSession):` (line ~217). Delete the entire function body and its inline 16-op `unit_ops` list (through line ~459).

Also remove the call site `await seed_unit_ops(db)` (around line 587).

- [ ] **Step 2: Add `seed_library_subscriptions`**

In the same file, add a new function (place it where `seed_unit_ops` used to be):

```python
async def seed_library_subscriptions(db: AsyncSession):
    """Subscribe every existing organization to every default library."""
    from sqlalchemy import select
    from app.models.iam import Organization
    from app.services.science import library_registry

    org_q = await db.execute(select(Organization))
    for org in org_q.scalars():
        await library_registry.subscribe_default_libraries(db, org.id)
```

- [ ] **Step 3: Wire it into the orchestration**

Find the previous call site of `seed_unit_ops`. Replace with `await seed_library_subscriptions(db)`.

- [ ] **Step 4: Run the reset script and verify**

Run: `./scripts/reset.sh`
Expected: completes without errors.

Run: `psql -U postgres -d batchrite -c "SELECT COUNT(*) FROM unit_op_definitions WHERE organization_id IS NULL;"`
Expected: `0` — no global rows remain.

Run: `psql -U postgres -d batchrite -c "SELECT organization_id, library_slug FROM unit_op_library_subscriptions;"`
Expected: at least one row per seeded org, with `library_slug = 'core'`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/seed.py
git commit -m "feat(F-0075): seed library subscriptions in place of inline unit ops"
```

---

## Task 13: Backfill CLI script

**Files:**
- Create: `backend/scripts/subscribe_orgs_to_default_libraries.py`

- [ ] **Step 1: Write the script**

Create `backend/scripts/subscribe_orgs_to_default_libraries.py`:

```python
"""Backfill: subscribe every existing org to all default libraries.

Use case: a future commit adds a second library with is_default=true.
Run this script once after deploy to enroll existing orgs.
Idempotent: skips orgs that already have the subscription.

Usage (from backend/):
    python scripts/subscribe_orgs_to_default_libraries.py
"""
import asyncio
import logging
import sys
from pathlib import Path

# Make `app` importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.iam import Organization
from app.services.science import library_registry

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    library_registry.register_source(
        library_registry.BundledJSONSource(
            Path(__file__).resolve().parents[1] / "app/data/unit_op_libraries"
        )
    )
    await library_registry.reload_libraries()

    defaults = library_registry.default_library_slugs()
    log.info("Default libraries: %s", defaults)

    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        org_q = await db.execute(select(Organization))
        orgs = list(org_q.scalars())
        log.info("Backfilling %d organizations...", len(orgs))
        for org in orgs:
            await library_registry.subscribe_default_libraries(db, org.id)
        await db.commit()
        log.info("Done.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it (idempotent on a freshly seeded DB)**

Run: `cd backend && source .venv/bin/activate && python scripts/subscribe_orgs_to_default_libraries.py`
Expected: prints "Default libraries: ['core']", "Backfilling N organizations...", "Done." Re-running is a no-op.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/subscribe_orgs_to_default_libraries.py
git commit -m "feat(F-0075): CLI script to backfill default library subscriptions"
```

---

## Task 14: Run full backend test suite

- [ ] **Step 1: Run all tests**

Run: `cd backend && source .venv/bin/activate && pytest`
Expected: all tests pass. If any fail, fix before proceeding to Phase 2.

- [ ] **Step 2: Run lint/format**

Run: `cd backend && black app tests && isort app tests && mypy app`
Expected: no errors. Fix anything reported.

- [ ] **Step 3: Commit any fixups**

```bash
git status
# If tests fixed, lint adjusted, etc.:
git add -p
git commit -m "chore(F-0075): backend lint and test cleanup"
```

---

# Phase 2 — Frontend

## Task 15: Add `library_slug` to frontend Zod schema

**Files:**
- Modify: `frontend/src/lib/schemas/science.ts`

- [ ] **Step 1: Locate the unit op schema**

Run: `grep -n "UnitOpDefinition\|unit.op.definition\|param_schema" frontend/src/lib/schemas/science.ts | head -20`

- [ ] **Step 2: Add the field**

In `frontend/src/lib/schemas/science.ts`, find the unit op response Zod schema. Add `library_slug` as a nullable optional string. Example shape (adapt to actual schema name):

```typescript
export const UnitOpDefinitionSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
    category: z.string(),
    description: z.string().nullable(),
    param_schema: z.record(z.unknown()),
    result_schema: z.record(z.unknown()),
    organization_id: z.string().uuid().nullable(),
    project_id: z.string().uuid().nullable(),
    library_slug: z.string().nullable().optional(),  // F-0075
    scope: z.enum(["global", "organization", "project"]),
    created_at: z.string(),
    updated_at: z.string(),
});
```

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npm run check`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/schemas/science.ts
git commit -m "feat(F-0075): add library_slug to UnitOpDefinition Zod schema"
```

---

## Task 16: Restructure `ProtocolSidebar` — 3-level accordion

**Files:**
- Modify: `frontend/src/lib/components/protocol/ProtocolSidebar.svelte`

- [ ] **Step 1: Add the `LibraryGroup` type and grouping derived**

Open `frontend/src/lib/components/protocol/ProtocolSidebar.svelte`. Replace the existing `categories` `$derived` (around line 175) with a 2-level grouping:

```typescript
type LibraryGroup = {
    key: string;            // "lib:core" or "_custom"
    displayName: string;
    categories: Map<string, any[]>;
};

const LIBRARY_DISPLAY_NAMES: Record<string, string> = {
    core: "Core",
};

function libraryDisplayName(slug: string): string {
    return LIBRARY_DISPLAY_NAMES[slug] ??
        slug.split("_")
            .map(s => s.charAt(0).toUpperCase() + s.slice(1))
            .join(" ");
}

const groups = $derived.by((): LibraryGroup[] => {
    const ops = filteredOps();
    const byLib: Map<string, Map<string, any[]>> = new Map();

    for (const op of ops) {
        const libKey = op.library_slug ? `lib:${op.library_slug}` : "_custom";
        if (!byLib.has(libKey)) byLib.set(libKey, new Map());
        const cats = byLib.get(libKey)!;
        const cat = op.category || "Other";
        if (!cats.has(cat)) cats.set(cat, []);
        cats.get(cat)!.push(op);
    }

    const out: LibraryGroup[] = [];
    for (const [libKey, cats] of byLib) {
        if (cats.size === 0) continue;
        const display = libKey === "_custom"
            ? "Custom (My Org)"
            : libraryDisplayName(libKey.slice(4));
        out.push({ key: libKey, displayName: display, categories: cats });
    }
    // Custom always last; libraries alphabetical otherwise
    out.sort((a, b) => {
        if (a.key === "_custom") return 1;
        if (b.key === "_custom") return -1;
        return a.displayName.localeCompare(b.displayName);
    });
    return out;
});
```

- [ ] **Step 2: Replace the rendering block**

Replace the existing `<!-- Unit Operations -->` block (the `{#each [...categories().entries()]...}` loop, around line 345) with a 2-level nested loop:

```svelte
<!-- Unit Operations -->
<div class="ops-list">
    <div class="section-header-row">
        <span class="section-title">UNIT OPERATIONS</span>
    </div>

    {#if unitOps.length === 0}
        <p class="loading-text">Loading...</p>
    {:else}
        {#each groups as group (group.key)}
            <div class="library-group">
                <Button
                    variant="ghost"
                    class="library-header"
                    onclick={() => toggleGroup(group.key)}
                >
                    <span class="lib-name">{group.displayName}</span>
                    <span
                        class="cat-chevron"
                        class:collapsed={effectiveCollapse.has(group.key)}
                    >&#9662;</span>
                </Button>

                {#if !effectiveCollapse.has(group.key)}
                    {#each [...group.categories.entries()] as [category, ops]}
                        <div class="category-group">
                            <Button
                                variant="ghost"
                                class="category-header"
                                onclick={() => toggleGroup(`${group.key}:${category}`)}
                            >
                                <span class="cat-dot" style:background={getCategoryColor(category)}></span>
                                <span class="cat-name">{category}</span>
                                <span
                                    class="cat-chevron"
                                    class:collapsed={effectiveCollapse.has(`${group.key}:${category}`)}
                                >&#9662;</span>
                                <span
                                    class="cat-add-btn"
                                    role="button"
                                    tabindex="0"
                                    onclick={(e) => { e.stopPropagation(); onOpenCreateModal(category); }}
                                    onkeydown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onOpenCreateModal(category); } }}
                                    title="Add unit op to {category}"
                                >+</span>
                            </Button>

                            {#if !effectiveCollapse.has(`${group.key}:${category}`)}
                                <div class="cat-ops">
                                    {#each ops as op}
                                        <div
                                            role="button"
                                            tabindex="0"
                                            class="op-item"
                                            draggable="true"
                                            ondragstart={(e) => onDragStart(e, op)}
                                        >
                                            <span class="op-icon">{getCategoryIcon(op.category)}</span>
                                            <div class="op-info">
                                                <span class="op-name">
                                                    {op.name}
                                                    {#if op.scope === 'organization'}
                                                        <span class="scope-dot scope-org" title="Organization"></span>
                                                    {:else if op.scope === 'project'}
                                                        <span class="scope-dot scope-project" title="Project"></span>
                                                    {/if}
                                                </span>
                                                {#if op.description}
                                                    <span class="op-desc">{op.description}</span>
                                                {/if}
                                            </div>
                                        </div>
                                    {/each}
                                </div>
                            {/if}
                        </div>
                    {/each}
                {/if}
            </div>
        {/each}
    {/if}
</div>
```

- [ ] **Step 3: Replace `collapsedCategories` with a unified `manualCollapse` set**

Replace the existing state declaration:

```typescript
let manualCollapse = $state<Set<string>>(new Set());

function toggleGroup(key: string) {
    const s = new Set(manualCollapse);
    if (s.has(key)) s.delete(key);
    else s.add(key);
    manualCollapse = s;
}

const effectiveCollapse = $derived(
    searchQuery.trim() ? new Set<string>() : manualCollapse
);
```

Remove the old `collapsedCategories` state and `toggleCategory` function entirely.

- [ ] **Step 4: Add minor styles**

In the `<style>` block, add:

```css
.library-group {
    margin-bottom: 12px;
}

:global(.library-header) {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    height: auto;
    padding: 6px 4px;
    background: transparent;
    border: none;
    font-family: inherit;
    border-radius: 4px;
    justify-content: flex-start;
    font-weight: 600;
}

:global(.library-header:hover) {
    background: #f8fafc;
}

.lib-name {
    flex: 1;
    font-size: 13px;
    font-weight: 700;
    color: #0f172a;
    text-align: left;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
```

- [ ] **Step 5: Verify in browser**

Run dev servers (worktree ports per CLAUDE.md):
```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8010 &
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183 &
```

Open `http://localhost:5183`, log in, open a protocol. Sidebar should show:
- "Core" library header with chevron
- "Preparation", "Process", "Analytics", "QC", "Logistics" categories nested inside
- 12 ops total under Core

Drag an op into the canvas. Should still work.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/ProtocolSidebar.svelte
git commit -m "feat(F-0075): 3-level accordion in protocol sidebar (library > category > op)"
```

---

## Task 17: Search auto-expand + match highlighting

**Files:**
- Modify: `frontend/src/lib/components/protocol/ProtocolSidebar.svelte`

- [ ] **Step 1: Update the matching logic**

Replace `filteredOps`:

```typescript
const filteredOps = $derived(() => {
    if (!searchQuery.trim()) return unitOps;
    const q = searchQuery.toLowerCase();
    return unitOps.filter(
        (op: any) =>
            op.name.toLowerCase().includes(q) ||
            op.category.toLowerCase().includes(q) ||
            (op.library_slug ?? "").toLowerCase().includes(q) ||
            libraryDisplayName(op.library_slug ?? "").toLowerCase().includes(q)
    );
});
```

(Description excluded per spec.)

- [ ] **Step 2: Add highlight helper**

Above the markup, add:

```typescript
function highlightMatch(text: string, query: string): string {
    if (!query.trim()) return escapeHtml(text);
    const q = query.toLowerCase();
    const lower = text.toLowerCase();
    const idx = lower.indexOf(q);
    if (idx < 0) return escapeHtml(text);
    return `${escapeHtml(text.slice(0, idx))}<mark>${escapeHtml(text.slice(idx, idx + q.length))}</mark>${escapeHtml(text.slice(idx + q.length))}`;
}

function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    } as any)[c]);
}
```

- [ ] **Step 3: Apply highlight to op names**

In the `op-name` span, replace `{op.name}` with:

```svelte
<span class="op-name">
    {@html highlightMatch(op.name, searchQuery)}
    {#if op.scope === 'organization'}
        <span class="scope-dot scope-org" title="Organization"></span>
    {:else if op.scope === 'project'}
        <span class="scope-dot scope-project" title="Project"></span>
    {/if}
</span>
```

Apply the same `{@html highlightMatch(...)}` to `lib-name` and `cat-name`.

- [ ] **Step 4: Style `<mark>`**

In `<style>`, add:

```css
:global(.ops-list mark) {
    background: hsla(40, 95%, 60%, 0.4);
    color: inherit;
    padding: 0 1px;
    border-radius: 2px;
}
```

- [ ] **Step 5: Verify**

In the browser, type "cent" — only Centrifugation shows, all parent groups expanded. Type "core" — all 12 ops visible. Clear search — manual collapse state restored.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/ProtocolSidebar.svelte
git commit -m "feat(F-0075): search auto-expands matching groups with highlight"
```

---

## Task 18: Org settings — Reload Libraries button

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Find the Organization tab content**

Run: `grep -n "activeTab === 'organization'\|tab=organization" frontend/src/routes/settings/+page.svelte | head -5`

Locate the block that renders when `activeTab === 'organization'`.

- [ ] **Step 2: Add a Libraries section**

Add this block at the end of the Organization tab's content (still inside the `{#if activeTab === 'organization'}` block, before the closing `{/if}`):

```svelte
{#if isOrgAdmin}
<section class="settings-card">
    <h3>Unit Operation Libraries</h3>
    <p class="settings-description">
        Refresh the catalog of system unit operations after a deployment
        or library file update.
    </p>
    <div class="reload-row">
        <Button onclick={reloadLibraries} disabled={reloading}>
            {reloading ? "Reloading..." : "Reload Libraries"}
        </Button>
        {#if lastReloadedAt}
            <span class="muted">Last reloaded: {formatRelative(lastReloadedAt)}</span>
        {/if}
    </div>
</section>
{/if}
```

- [ ] **Step 3: Add the script logic**

In the `<script>` block, add:

```typescript
let reloading = $state(false);
let lastReloadedAt = $state<Date | null>(null);

async function reloadLibraries() {
    reloading = true;
    try {
        const res = await api.post("/admin/libraries/reload");
        const libs = res.libraries ?? [];
        const opCount = libs.reduce((acc: number, l: any) => acc + (l.op_count ?? 0), 0);
        toast.success(`Libraries reloaded — ${libs.length} libraries, ${opCount} ops`);
        lastReloadedAt = new Date();
    } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : "Reload failed");
    } finally {
        reloading = false;
    }
}

function formatRelative(d: Date): string {
    const seconds = Math.round((Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    return `${Math.round(minutes / 60)}h ago`;
}
```

`isOrgAdmin` and `toast` should already be in scope from the existing settings page (it has admin-gated content already). If they aren't, check the existing tab code for the role check pattern and the existing toast import.

- [ ] **Step 4: Verify**

Open `http://localhost:5183/settings?tab=organization`. The "Unit Operation Libraries" section should appear under existing org content. Click "Reload Libraries" — toast appears: "Libraries reloaded — 1 libraries, 12 ops". Timestamp updates.

Test failure: stop the backend, click again — toast shows the network error.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(F-0075): add Reload Libraries button to org settings"
```

---

## Task 19: Browser verification + qa-verify

- [ ] **Step 1: Restart dev servers fresh**

Kill any running servers, restart backend on :8010 and frontend on :5183.

- [ ] **Step 2: Manually walk the golden path**

1. Log in as `wesu07@gmail.com` (any password works in dev).
2. Open or create a protocol.
3. Sidebar shows "Core" with categories nested below.
4. Drag "Mixing" onto canvas — node appears, params pane works.
5. Type "cent" in search — Centrifugation visible, parent groups expanded, match highlighted.
6. Clear search — accordion returns to manual state.
7. Open a category, click the `+` to add a custom org op. New op appears under "Custom (My Org)".
8. Right-click the new custom op (or however edit is triggered today) — verify it's editable.
9. Navigate to `/settings?tab=organization`. Click "Reload Libraries". Toast shows success. Click again — succeeds again.

- [ ] **Step 3: Run frontend checks**

Run: `cd frontend && npm run check && npm run test`
Expected: green.

- [ ] **Step 4: Final commit if any cleanup**

```bash
git status
# if anything is dirty:
git add -p && git commit -m "chore(F-0075): post-verification cleanup"
```

---

## Self-Review

Spec coverage check (run mentally or as a quick scan):

- ✅ JSON library format + Pydantic validation — Task 1, 2.
- ✅ `core` library with 12 ops — Task 1.
- ✅ `LibraryRegistry` with source abstraction, atomic reload, synthetic UUIDs, default-subscription helper — Task 2.
- ✅ `unit_op_library_subscriptions` table + override columns — Tasks 3, 4.
- ✅ Listing endpoint returns union — Task 7.
- ✅ Override copy-on-write — Task 8.
- ✅ Auto-subscribe on org creation — Task 6.
- ✅ Migration backfills existing orgs + drops globals — Task 4.
- ✅ Backfill CLI script — Task 13.
- ✅ Seed script update — Task 12.
- ✅ Lifespan integration — Task 11.
- ✅ Admin reload endpoint — Task 10.
- ✅ Frontend `library_slug` schema — Task 15.
- ✅ Sidebar 3-level accordion — Task 16.
- ✅ Search auto-expand + highlight — Task 17.
- ✅ Org settings reload button — Task 18.
- ✅ Tests for: library parse, synthetic UUID determinism, auto-subscribe, GET union, override copy-on-write, override isolation, second update, unknown UUID, source abstraction, atomic reload, admin endpoint admin-only — Tasks 2, 5, 6, 7, 8, 10.

No placeholders, no "TODO", no untyped methods called from later tasks.
