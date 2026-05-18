# F-0086 · Designate Run as Lot Producer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `produces_lot` designation to runs, with a server-side auto-generation helper, a soft duplicate-warning check, a Runs-list filter, post-creation editing, and conditional rendering of the lot row in the batch-record template.

**Architecture:** SQLAlchemy column + Alembic migration + Pydantic schema fields on the `Run` model; two new endpoints (`POST /science/runs/suggest-lot-number`, `GET /science/runs/check-lot-number`) for the auto-generator and duplicate check; client-side filter chip in `RunsTab.svelte` (no parent refactor) plus a backend `?produces_lot=` query param for API consumers; new `Switch` primitive that wraps `bits-ui` to match shadcn-svelte; `produces_lot` exposed in the docx Jinja context and the batch-record template's lot row wrapped in `{%tr if produces_lot %}`.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic + Pydantic v2 (backend); Svelte 5 runes + shadcn-svelte + bits-ui + Zod + Vitest (frontend); docxtpl Jinja `.docx` templates.

**Spec:** `docs/superpowers/specs/2026-05-18-f0086-run-lot-producer-design.md` (commit `b755ca8`).
**Mockup:** `docs/superpowers/specs/mockups/f0086-lot-producer.html`.

**Dev commands (from CLAUDE.md):**
- Backend tests: `cd backend && source .venv/bin/activate && pytest tests/unit/test_run_produces_lot.py -v`
- Backend lint: `cd backend && source .venv/bin/activate && black app tests && isort app tests`
- Migration: `cd backend && source .venv/bin/activate && alembic upgrade head`
- Frontend tests: `cd frontend && npm run test -- --run path/to/test`
- Frontend type check: `cd frontend && npm run check`

**File map (created vs. modified):**

```
CREATE  backend/alembic/versions/f0043_add_run_produces_lot.py
CREATE  backend/tests/unit/test_run_produces_lot.py
CREATE  backend/tests/unit/test_template_engine_produces_lot.py
CREATE  frontend/src/lib/components/ui/switch/index.ts
CREATE  frontend/src/lib/components/ui/switch/switch.svelte
CREATE  frontend/src/lib/components/project/RunsTab.test.ts

MODIFY  backend/app/models/science.py                                          (add produces_lot column)
MODIFY  backend/app/schemas/science.py                                         (Run{Create,Update,Response})
MODIFY  backend/app/api/endpoints/runs.py                                      (validation + list filter + 2 endpoints)
MODIFY  backend/app/services/protocols/template_engine.py                      (KNOWN_VARIABLES + context)
MODIFY  backend/app/services/documents/templates/batch_record_default.docx     (bind to lot_number + tr-if)
MODIFY  backend/uploads/system/document_templates/batch_record_default.docx    (mirror above)
MODIFY  frontend/src/lib/schemas/runs.ts                                       (produces_lot in zod schemas)
MODIFY  frontend/src/lib/components/run/RunCreatorNameStep.svelte
MODIFY  frontend/src/lib/components/run/RunCreatorNameStep.test.ts
MODIFY  frontend/src/lib/components/project/RunsTab.svelte                     (chip + lot column)
MODIFY  frontend/src/routes/runs/[id]/+page.svelte                             (inline Lot output card)
```

---

## Task 1 · Alembic migration: add `produces_lot` column + `lot_number` index

**Files:**
- Create: `backend/alembic/versions/f0043_add_run_produces_lot.py`

The current Alembic head is `292437ab60e0`. We name this migration `f0043_*` to match the human-readable convention used by `f0042_add_heartbeat_columns.py`.

- [ ] **Step 1: Create the migration file**

```python
# backend/alembic/versions/f0043_add_run_produces_lot.py
"""add produces_lot column and lot_number index (F-0086)

Revision ID: f0043
Revises: 292437ab60e0
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f0043"
down_revision: Union[str, Sequence[str], None] = "292437ab60e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "produces_lot",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_runs_produces_lot",
        "runs",
        ["produces_lot"],
    )
    op.create_index(
        "ix_runs_lot_number",
        "runs",
        ["lot_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_runs_lot_number", table_name="runs")
    op.drop_index("ix_runs_produces_lot", table_name="runs")
    op.drop_column("runs", "produces_lot")
```

- [ ] **Step 2: Apply locally and confirm clean upgrade/downgrade**

```bash
cd backend && source .venv/bin/activate
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: each command prints `Running upgrade …` / `Running downgrade …` with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/f0043_add_run_produces_lot.py
git commit -m "feat(F-0086): migrate runs.produces_lot column and lot_number index"
```

---

## Task 2 · Run model: add `produces_lot`

**Files:**
- Modify: `backend/app/models/science.py:242-245` (the lot/batch metadata block)

- [ ] **Step 1: Write the failing test** — `backend/tests/unit/test_run_produces_lot.py`

```python
"""Unit tests for F-0086 Run produces_lot designation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Run, RunStatus


@pytest.mark.asyncio
async def test_run_produces_lot_defaults_false(
    db_session: AsyncSession, test_project
):
    r = Run(
        name="not-a-lot-producer",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.produces_lot is False


@pytest.mark.asyncio
async def test_run_produces_lot_can_be_set_true(
    db_session: AsyncSession, test_project
):
    r = Run(
        name="lot-producer",
        project_id=test_project.id,
        status=RunStatus.PLANNED,
        graph={},
        execution_data={},
        notes=[],
        attachments=[],
        produces_lot=True,
        lot_number="LOT-000001",
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.refresh(r)
    assert r.produces_lot is True
    assert r.lot_number == "LOT-000001"
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/test_run_produces_lot.py::test_run_produces_lot_defaults_false -v
```

Expected: `AttributeError: 'Run' object has no attribute 'produces_lot'` (or `TypeError` on the keyword).

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/science.py`, locate the GxP metadata block (around line 242-245) and add the column directly above `lot_number`:

```python
    # F-0086: explicit designation that this run produces a manufacturing lot.
    # Drives validation (lot_number required when true) and the runs-list filter.
    produces_lot: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )

    # Production metadata (QA-0008): lot/batch identifiers for GxP traceability.
    # Nullable because experiment-style runs may not have a manufacturing lot.
    lot_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    batch_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
```

(`Boolean` is already imported in this file — verify with a quick `grep "^from sqlalchemy" backend/app/models/science.py`. If not, add `Boolean` to the imports.)

- [ ] **Step 4: Run the tests, confirm both pass**

```bash
pytest tests/unit/test_run_produces_lot.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/science.py backend/tests/unit/test_run_produces_lot.py
git commit -m "feat(F-0086): add Run.produces_lot column"
```

---

## Task 3 · Pydantic schemas: `produces_lot` on Create/Update/Response

**Files:**
- Modify: `backend/app/schemas/science.py:374-414`

- [ ] **Step 1: Write the failing schema tests** — append to `backend/tests/unit/test_run_produces_lot.py`

```python
from app.schemas.science import RunCreate, RunResponse, RunUpdate


def test_run_create_default_produces_lot_false():
    payload = RunCreate(name="r", project_id="00000000-0000-0000-0000-000000000001")
    assert payload.produces_lot is False


def test_run_create_accepts_produces_lot_true():
    payload = RunCreate(
        name="r",
        project_id="00000000-0000-0000-0000-000000000001",
        produces_lot=True,
        lot_number="LOT-000001",
    )
    assert payload.produces_lot is True


def test_run_update_produces_lot_optional():
    payload = RunUpdate(produces_lot=True)
    assert payload.produces_lot is True
    payload2 = RunUpdate()
    assert payload2.produces_lot is None
```

- [ ] **Step 2: Run the new tests, confirm they fail**

```bash
pytest tests/unit/test_run_produces_lot.py -v -k "produces_lot"
```

Expected: validation errors / `unexpected keyword argument 'produces_lot'`.

- [ ] **Step 3: Add `produces_lot` to the three schemas**

In `backend/app/schemas/science.py`:

```python
class RunCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None
    protocol_version_number: Optional[int] = None
    experiment_id: Optional[UUID] = None
    overrides: Optional["RunOverrides"] = None
    # F-0086
    produces_lot: bool = False
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None


class RunUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[RunStatus] = None
    graph: Optional[Dict[str, Any]] = None
    execution_data: Optional[Dict[str, Any]] = None
    # F-0086
    produces_lot: Optional[bool] = None
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None


class RunResponse(RunBase):
    id: UUID
    project_id: UUID
    protocol_id: Optional[UUID]
    experiment_id: Optional[UUID] = None
    started_by_id: Optional[UUID] = None
    created_by_id: Optional[UUID] = None
    is_strict: bool = False
    notes: list[RunNote] = Field(default_factory=list)
    attachments: list[RunAttachment] = Field(default_factory=list)
    # F-0086
    produces_lot: bool = False
    # QA-0008: GxP execution metadata
    lot_number: Optional[str] = None
    batch_number: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Run the schema tests, confirm pass**

```bash
pytest tests/unit/test_run_produces_lot.py -v -k "produces_lot"
```

Expected: all three new tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/science.py backend/tests/unit/test_run_produces_lot.py
git commit -m "feat(F-0086): expose produces_lot on Run{Create,Update,Response}"
```

---

## Task 4 · Endpoint validation: `produces_lot=true` requires `lot_number`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py` — `create_run` (~line 62-228) and `update_run` (~line 314 onward)

- [ ] **Step 1: Write the failing tests** — `backend/tests/integration/test_run_produces_lot_api.py` (new file)

```python
"""Integration tests for F-0086 produces_lot validation and endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_run_produces_lot_without_lot_number_rejected(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "lot-without-number",
            "project_id": str(test_project.id),
            "produces_lot": True,
        },
    )
    assert resp.status_code == 422
    assert "lot_number" in resp.text


@pytest.mark.asyncio
async def test_create_run_produces_lot_with_lot_number_ok(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "ok-producer",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000001",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["produces_lot"] is True
    assert body["lot_number"] == "LOT-000001"


@pytest.mark.asyncio
async def test_update_run_produces_lot_without_lot_number_rejected(
    client: AsyncClient, auth_headers, test_run
):
    resp = await client.put(
        f"/science/runs/{test_run.id}",
        headers=auth_headers,
        json={"produces_lot": True},
    )
    assert resp.status_code == 422
    assert "lot_number" in resp.text
```

(If `test_run` is not an existing fixture, check `backend/tests/integration/conftest.py` and add one that creates a PLANNED run on `test_project` with `lot_number=None`. Use the same pattern as other integration tests in this directory.)

- [ ] **Step 2: Run the tests, confirm they fail**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_run_produces_lot_api.py -v
```

Expected: all 3 fail (`status_code` would be 201 / 200 because no validation exists yet).

- [ ] **Step 3: Add validation to `create_run`**

In `backend/app/api/endpoints/runs.py`, inside `create_run` immediately after the permission check (around line 80, before the protocol-version lookup), insert:

```python
    # F-0086: a run designated as producing a lot must carry a lot number.
    if run_in.produces_lot and not (run_in.lot_number and run_in.lot_number.strip()):
        raise HTTPException(
            status_code=422,
            detail="lot_number is required when produces_lot is true",
        )
```

Then add `produces_lot=run_in.produces_lot,` to the `Run(...)` constructor right next to `lot_number=`:

```python
    run_obj = Run(
        ...,
        # F-0086
        produces_lot=run_in.produces_lot,
        # QA-0008: GxP execution metadata
        lot_number=run_in.lot_number,
        batch_number=run_in.batch_number,
    )
```

- [ ] **Step 4: Add validation to `update_run`**

The update handler builds a sparse diff via `update_data.model_dump(exclude_unset=True)`. We need to reject a request that sets `produces_lot=true` and *also* leaves `lot_number` empty/unchanged.

Locate `update_run` and, **after** the existing permission checks but **before** the `setattr` loop, add:

```python
    # F-0086: when toggling produces_lot=true, ensure a lot_number is set
    # either in this payload or already on the run.
    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("produces_lot") is True:
        next_lot = update_dict.get("lot_number")
        if next_lot is None:
            next_lot = run_obj.lot_number
        if not (next_lot and next_lot.strip()):
            raise HTTPException(
                status_code=422,
                detail="lot_number is required when produces_lot is true",
            )
```

If the file already defines `update_dict` further down, reuse the existing definition rather than recomputing; just move the validation above the `setattr` loop.

- [ ] **Step 5: Run the integration tests**

```bash
pytest tests/integration/test_run_produces_lot_api.py -v
```

Expected: all 3 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_produces_lot_api.py
git commit -m "feat(F-0086): require lot_number when produces_lot=true"
```

---

## Task 5 · List filter: `GET /science/projects/{id}/runs?produces_lot=`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py:297-311` (`list_project_runs`)

- [ ] **Step 1: Write the failing test** — append to `backend/tests/integration/test_run_produces_lot_api.py`

```python
@pytest.mark.asyncio
async def test_list_project_runs_filter_produces_lot(
    client: AsyncClient, auth_headers, test_project
):
    # Create two runs: one producer, one not.
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "non-producer",
            "project_id": str(test_project.id),
        },
    )
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "producer",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000010",
        },
    )

    resp_true = await client.get(
        f"/science/projects/{test_project.id}/runs?produces_lot=true",
        headers=auth_headers,
    )
    assert resp_true.status_code == 200
    names = {r["name"] for r in resp_true.json()}
    assert names == {"producer"}

    resp_false = await client.get(
        f"/science/projects/{test_project.id}/runs?produces_lot=false",
        headers=auth_headers,
    )
    assert {r["name"] for r in resp_false.json()} == {"non-producer"}

    resp_all = await client.get(
        f"/science/projects/{test_project.id}/runs",
        headers=auth_headers,
    )
    assert {r["name"] for r in resp_all.json()} >= {"producer", "non-producer"}
```

- [ ] **Step 2: Run, confirm it fails**

```bash
pytest tests/integration/test_run_produces_lot_api.py::test_list_project_runs_filter_produces_lot -v
```

Expected: fails because the endpoint ignores the query param (all three sets equal).

- [ ] **Step 3: Add the query parameter**

In `backend/app/api/endpoints/runs.py`, replace `list_project_runs`:

```python
@router.get(
    "/projects/{project_id}/runs",
    response_model=List[RunResponse],
    dependencies=[
        Depends(
            require_permission(ObjectType.PROJECT, "project_id", PermissionLevel.VIEW)
        )
    ],
)
async def list_project_runs(
    project_id: UUID,
    produces_lot: Optional[bool] = Query(
        None,
        description="Filter by lot-producer designation. Omit to return all.",
    ),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Run).where(Run.project_id == project_id)
    if produces_lot is not None:
        stmt = stmt.where(Run.produces_lot == produces_lot)
    result = await db.execute(stmt)
    return result.scalars().all()
```

`Query` is already imported at the top of the file; `Optional` is too.

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/integration/test_run_produces_lot_api.py::test_list_project_runs_filter_produces_lot -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/tests/integration/test_run_produces_lot_api.py
git commit -m "feat(F-0086): filter project runs by produces_lot query param"
```

---

## Task 6 · New endpoint: `POST /science/runs/suggest-lot-number`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py`

The endpoint returns the next monotonic `LOT-{seq:06}` for the org. Org is derived from the supplied `project_id` (validated against permissions).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/integration/test_run_produces_lot_api.py`

```python
@pytest.mark.asyncio
async def test_suggest_lot_number_empty_org_returns_first(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.status_code == 200
    assert resp.json() == {"lot_number": "LOT-000001"}


@pytest.mark.asyncio
async def test_suggest_lot_number_increments_after_existing(
    client: AsyncClient, auth_headers, test_project
):
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "first",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "LOT-000042",
        },
    )
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.json() == {"lot_number": "LOT-000043"}


@pytest.mark.asyncio
async def test_suggest_lot_number_ignores_non_matching_values(
    client: AsyncClient, auth_headers, test_project
):
    # Manual entry that does not match the LOT-NNNNNN pattern is ignored
    # by the sequence calculation.
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "custom",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "PILOT-A7",
        },
    )
    resp = await client.post(
        "/science/runs/suggest-lot-number",
        headers=auth_headers,
        json={"project_id": str(test_project.id)},
    )
    assert resp.json() == {"lot_number": "LOT-000001"}
```

- [ ] **Step 2: Run, confirm 404**

```bash
pytest tests/integration/test_run_produces_lot_api.py -v -k suggest
```

Expected: 404 (route does not exist).

- [ ] **Step 3: Add the Pydantic body schema**

In `backend/app/schemas/science.py`, near the other run schemas, add:

```python
class SuggestLotNumberRequest(BaseModel):
    project_id: UUID


class SuggestLotNumberResponse(BaseModel):
    lot_number: str
```

- [ ] **Step 4: Implement the endpoint**

In `backend/app/api/endpoints/runs.py`, add (before the existing list/detail handlers is fine):

```python
@router.post(
    "/runs/suggest-lot-number",
    response_model=SuggestLotNumberResponse,
)
async def suggest_lot_number(
    body: SuggestLotNumberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Suggest the next monotonic lot number for the project's organization.

    Pattern: LOT-{seq:06}. Sequence is org-scoped and computed over runs whose
    lot_number matches the canonical pattern. Manually entered values that do
    not match are ignored (they don't anchor or break the sequence).
    """
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, body.project_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_or_404(db, Project, body.project_id)

    # Pull all canonical-pattern lot_numbers for runs in this org. Cheap given
    # the index on lot_number; the JOIN scopes to the org without denormalizing.
    stmt = (
        select(Run.lot_number)
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == project.organization_id,
            Run.lot_number.regexp_match(r"^LOT-[0-9]{6}$"),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()

    max_seq = 0
    for value in rows:
        try:
            n = int(value.split("-", 1)[1])
            if n > max_seq:
                max_seq = n
        except (ValueError, IndexError):
            continue
    next_seq = max_seq + 1
    return SuggestLotNumberResponse(lot_number=f"LOT-{next_seq:06d}")
```

Add the import at the top of the file:

```python
from app.schemas.science import (..., SuggestLotNumberRequest,
                                 SuggestLotNumberResponse)
```

Note: `Run.lot_number.regexp_match(...)` produces PostgreSQL `~`. Confirmed safe — SQLAlchemy 2 supports it on async drivers. If a test failure indicates the dialect lacks regexp, fall back to `Run.lot_number.like("LOT-______")` (`_` matches one char in SQL LIKE) plus a Python-side regex filter — but try `regexp_match` first.

- [ ] **Step 5: Run the suggest tests**

```bash
pytest tests/integration/test_run_produces_lot_api.py -v -k suggest
```

Expected: all three pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/app/schemas/science.py backend/tests/integration/test_run_produces_lot_api.py
git commit -m "feat(F-0086): add /runs/suggest-lot-number endpoint"
```

---

## Task 7 · New endpoint: `GET /science/runs/check-lot-number`

**Files:**
- Modify: `backend/app/api/endpoints/runs.py`

This is the soft duplicate-check used by the UI on input blur. Org-scoped via the supplied `project_id`.

- [ ] **Step 1: Write the failing tests** — append to the integration test file

```python
@pytest.mark.asyncio
async def test_check_lot_number_not_exists(
    client: AsyncClient, auth_headers, test_project
):
    resp = await client.get(
        "/science/runs/check-lot-number",
        headers=auth_headers,
        params={"project_id": str(test_project.id), "lot_number": "NEW-1"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"exists": False, "count": 0}


@pytest.mark.asyncio
async def test_check_lot_number_exists_within_org(
    client: AsyncClient, auth_headers, test_project
):
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "dup-1",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "DUP-1",
        },
    )
    await client.post(
        "/science/runs",
        headers=auth_headers,
        json={
            "name": "dup-2",
            "project_id": str(test_project.id),
            "produces_lot": True,
            "lot_number": "DUP-1",
        },
    )
    resp = await client.get(
        "/science/runs/check-lot-number",
        headers=auth_headers,
        params={"project_id": str(test_project.id), "lot_number": "DUP-1"},
    )
    body = resp.json()
    assert body == {"exists": True, "count": 2}
```

- [ ] **Step 2: Run, confirm 404**

```bash
pytest tests/integration/test_run_produces_lot_api.py -v -k check_lot
```

- [ ] **Step 3: Add schemas**

In `backend/app/schemas/science.py`:

```python
class CheckLotNumberResponse(BaseModel):
    exists: bool
    count: int
```

- [ ] **Step 4: Implement the endpoint**

In `runs.py`:

```python
@router.get(
    "/runs/check-lot-number",
    response_model=CheckLotNumberResponse,
)
async def check_lot_number(
    project_id: UUID = Query(...),
    lot_number: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Org-scoped duplicate-existence check for soft warnings in the UI."""
    allowed = await check_permission(
        db, user.id, ObjectType.PROJECT, project_id, PermissionLevel.VIEW
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    project = await get_or_404(db, Project, project_id)

    stmt = (
        select(func.count(Run.id))
        .join(Project, Run.project_id == Project.id)
        .where(
            Project.organization_id == project.organization_id,
            Run.lot_number == lot_number,
        )
    )
    count = int((await db.execute(stmt)).scalar() or 0)
    return CheckLotNumberResponse(exists=count > 0, count=count)
```

Add `CheckLotNumberResponse` to the schema imports at the top of `runs.py`. `func` is already imported via `from sqlalchemy import and_, func, select`.

- [ ] **Step 5: Run, confirm pass**

```bash
pytest tests/integration/test_run_produces_lot_api.py -v -k check_lot
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/runs.py backend/app/schemas/science.py backend/tests/integration/test_run_produces_lot_api.py
git commit -m "feat(F-0086): add /runs/check-lot-number org-scoped duplicate check"
```

---

## Task 8 · Template engine: expose `produces_lot` to Jinja docx context

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:170-198` (KNOWN_VARIABLES) and `:880-895` (context dict)
- Create: `backend/tests/unit/test_template_engine_produces_lot.py`

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for F-0086 produces_lot exposure in the docx Jinja context."""

import pytest

from app.services.protocols.template_engine import KNOWN_VARIABLES


def test_produces_lot_is_a_known_template_variable():
    assert "produces_lot" in KNOWN_VARIABLES
```

We also want an end-to-end check that the context dict carries the value through. Look at `backend/tests/integration/test_default_template_render.py` for the fixture/pattern, and add at the end of the new unit test file:

```python
@pytest.mark.asyncio
async def test_build_context_passes_produces_lot_through(monkeypatch):
    """The rendered context exposes produces_lot as a bool."""
    # If build_context has a callable signature that needs DB state, the
    # easiest check is the public `build_run_render_context` wrapper.
    # Locate the wrapper actually invoked from runs.py / protocol_pdfs.py and
    # call it with a minimal run + protocol; assert the returned context dict
    # contains `produces_lot` matching the run's value.
    #
    # If no clean wrapper exists, this test can be deferred; the integration
    # render test in Task 9 will catch a missing context key.
    pytest.skip("covered by integration template render test in Task 9")
```

(Removing the skip when a clean wrapper is identified is preferable; if you find a callable for building the docx render context directly, write the real assertion.)

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/unit/test_template_engine_produces_lot.py -v
```

Expected: `assert "produces_lot" in KNOWN_VARIABLES` fails.

- [ ] **Step 3: Update `KNOWN_VARIABLES`**

In `backend/app/services/protocols/template_engine.py`, locate the `# Run identifiers` block (around line 187):

```python
    # Run identifiers
    "produces_lot",      # F-0086
    "lot_number",
    "batch_number",
```

- [ ] **Step 4: Add `produces_lot` to the rendered context**

Locate the block (~line 882) where existing optional strings are funneled into the context:

```python
    for _k in (
        "doc_number",
        "effective_date",
        "supersedes_date",
        "purpose",
        "scope",
        "references",
        "definitions",
        "lot_number",
        "batch_number",
    ):
        context[_k] = locals()[_k] or ""
```

`produces_lot` is a bool, not a string, so add it on its own line (outside this loop) immediately after the loop:

```python
    # F-0086: explicit boolean — the batch-record template uses {%tr if produces_lot %}.
    context["produces_lot"] = bool(produces_lot)
```

For this to work, `build_context(...)` (or whichever function this block lives in) must accept `produces_lot` as a parameter. Find the function signature (search backward from line 880 for the `def` and `async def`); add `produces_lot: bool = False,` to its kwargs.

Then find every caller of that function (e.g., in `backend/app/api/endpoints/runs.py` and `backend/app/api/endpoints/protocol_pdfs.py`). At each call site that has a `run_obj` in scope, pass `produces_lot=run_obj.produces_lot`. Other call sites (protocol-only renders without a run) can pass `produces_lot=False` or omit the kwarg (default applies).

Use ripgrep to locate the callers:

```bash
rg "build_context\(" backend/app
```

- [ ] **Step 5: Run, confirm pass**

```bash
pytest tests/unit/test_template_engine_produces_lot.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/test_template_engine_produces_lot.py backend/app/api/endpoints/runs.py backend/app/api/endpoints/protocol_pdfs.py
git commit -m "feat(F-0086): expose produces_lot in docx Jinja context"
```

---

## Task 9 · Batch-record template: bind to `lot_number` and conditionally hide the row

**Files:**
- Modify: `backend/app/services/documents/templates/batch_record_default.docx`
- Modify: `backend/uploads/system/document_templates/batch_record_default.docx`

The header table currently has `R1 C1 = {{ run_name }}` for "Batch / Lot Number" — that is a misbinding. We fix the binding and wrap the row in `{%tr if produces_lot %}` so the row vanishes for non-producers. **Both .docx files must change in lockstep.**

- [ ] **Step 1: Write a failing render test** — `backend/tests/integration/test_batch_record_produces_lot.py`

Use the same fixture pattern as `tests/integration/test_default_template_render.py`. Pseudocode:

```python
"""Integration test: batch_record template honors produces_lot."""

import io

import pytest
from docx import Document

# Whichever public render function the codebase already exposes (cf.
# `backend/app/api/endpoints/protocol_pdfs.py` and
# `backend/app/services/protocols/template_engine.py`).
from app.services.protocols.template_engine import render_to_docx_bytes  # adjust import


@pytest.mark.asyncio
async def test_batch_record_includes_lot_row_when_produces_lot(
    db_session, test_org, test_project, test_protocol_version, test_user
):
    run = await _make_run(
        db_session,
        project=test_project,
        produces_lot=True,
        lot_number="LOT-000099",
    )
    pdf_or_docx_bytes = await render_to_docx_bytes(
        db_session, protocol_version=test_protocol_version, run=run
    )
    doc = Document(io.BytesIO(pdf_or_docx_bytes))
    body_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "LOT-000099" in body_text
    assert "Lot Number" in body_text or "Batch / Lot Number" in body_text


@pytest.mark.asyncio
async def test_batch_record_hides_lot_row_when_not_producer(
    db_session, test_org, test_project, test_protocol_version, test_user
):
    run = await _make_run(
        db_session,
        project=test_project,
        produces_lot=False,
        lot_number=None,
    )
    pdf_or_docx_bytes = await render_to_docx_bytes(
        db_session, protocol_version=test_protocol_version, run=run
    )
    doc = Document(io.BytesIO(pdf_or_docx_bytes))
    body_text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    # The row label and value should both be absent when produces_lot=false.
    assert "Lot Number" not in body_text and "Batch / Lot Number" not in body_text
```

Use the existing `_make_run` helper from `test_default_template_render.py` if present, or replicate its shape. The exact import path of the docx render function depends on what's exported — check `template_engine.py` for `render_to_docx`, `render_to_docx_bytes`, or similar; if only `render_to_pdf` is exported, use that and rasterize from the PDF, OR add a tiny `render_to_docx_bytes` helper alongside it.

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/integration/test_batch_record_produces_lot.py -v
```

- [ ] **Step 3: Edit the two docx files**

Both files have the same structure (Table 0, Row 1, Cell 1 = `{{ run_name }}`). Replace the **row** with a `{%tr if produces_lot %}`-wrapped row that binds to `{{ lot_number }}`.

The cleanest way is a one-shot Python edit script run via the existing venv. Save the script as `/tmp/patch_batch_record.py`:

```python
"""Patch batch_record_default.docx: F-0086 lot row.

- Table 0, Row 1: replace {{ run_name }} with {{ lot_number }}.
- Wrap the row in docxtpl row-scope conditionals: {%tr if produces_lot %} … {%tr endif %}.

docxtpl uses these row tags inside the *first* paragraph of any cell in
the target row to control row visibility. We add the {%tr if ...%}
opening to row 1's first cell and the {%tr endif %} closing to row 1's
last cell (both within the same row, so the entire row is gated).
"""

from pathlib import Path

from docx import Document

PATHS = [
    Path("backend/app/services/documents/templates/batch_record_default.docx"),
    Path("backend/uploads/system/document_templates/batch_record_default.docx"),
]

for path in PATHS:
    doc = Document(str(path))
    t0 = doc.tables[0]
    row = t0.rows[1]
    label_cell = row.cells[0]
    value_cell = row.cells[1]

    # Replace value binding.
    for p in value_cell.paragraphs:
        if "{{ run_name }}" in p.text:
            # Clear runs and rewrite cleanly.
            for r in list(p.runs):
                r.text = ""
            p.runs[0].text = "{{ lot_number }}" if p.runs else None
            if not p.runs:
                p.add_run("{{ lot_number }}")
            break

    # Prepend {%tr if produces_lot %} to the label cell's first paragraph.
    lp = label_cell.paragraphs[0]
    lp.insert_paragraph_before("{%tr if produces_lot %}")

    # Append {%tr endif %} to the value cell's last paragraph.
    vp = value_cell.paragraphs[-1]
    vp.add_run("\n{%tr endif %}")

    doc.save(str(path))
    print(f"patched {path}")
```

Then run it:

```bash
cd /home/wesuuu/Code/trellisbio
backend/.venv/bin/python /tmp/patch_batch_record.py
```

Expected output: `patched backend/app/services/documents/templates/batch_record_default.docx` and `patched backend/uploads/system/document_templates/batch_record_default.docx`.

Verify the change with:

```bash
backend/.venv/bin/python -c "
from docx import Document
for p in [
    'backend/app/services/documents/templates/batch_record_default.docx',
    'backend/uploads/system/document_templates/batch_record_default.docx',
]:
    d = Document(p)
    t0 = d.tables[0]
    for ri, r in enumerate(t0.rows):
        for ci, c in enumerate(r.cells):
            print(f'{p} T0 R{ri} C{ci}: {c.text!r}')
    print()
"
```

Expected: Row 1 cells now contain `'{%tr if produces_lot %}\nBatch / Lot Number'` and `'{{ lot_number }}\n{%tr endif %}'` (or shaped equivalently — content order may differ but the four tags must all be present in the row).

⚠️ If `docx` strips Jinja tags from text runs (it shouldn't — docxtpl works at the XML level), inspect the underlying XML:

```bash
backend/.venv/bin/python -c "
import zipfile
with zipfile.ZipFile('backend/app/services/documents/templates/batch_record_default.docx') as z:
    print(z.read('word/document.xml').decode()[:4000])
" | grep -E "produces_lot|lot_number|run_name"
```

If the docxtpl tags didn't survive (e.g., split across runs), open the .docx in LibreOffice and place the Jinja tags by hand, then re-save. The Python script is the preferred path; manual fallback is documented for completeness.

- [ ] **Step 4: Run the render tests**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_batch_record_produces_lot.py -v
```

Expected: both pass.

- [ ] **Step 5: Smoke-test the existing template suite still passes**

```bash
pytest tests/integration/test_default_template_render.py tests/integration/test_br_template_smoke.py -v
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/documents/templates/batch_record_default.docx \
        backend/uploads/system/document_templates/batch_record_default.docx \
        backend/tests/integration/test_batch_record_produces_lot.py
git commit -m "feat(F-0086): bind batch record lot row to lot_number and gate on produces_lot"
```

---

## Task 10 · Frontend: shadcn-svelte `Switch` primitive

**Files:**
- Create: `frontend/src/lib/components/ui/switch/switch.svelte`
- Create: `frontend/src/lib/components/ui/switch/index.ts`

The repo uses shadcn-svelte primitives but does not yet have `Switch`. We add a minimal wrapper over `bits-ui` `Switch` matching the styling of other primitives (see `Button` in `frontend/src/lib/components/ui/button/` and `Card` for the cn-import pattern).

- [ ] **Step 1: Confirm `bits-ui` is installed**

```bash
cd frontend && cat package.json | grep bits-ui
```

Expected: `"bits-ui": "..."` is present (it powers existing primitives in this repo).

- [ ] **Step 2: Create the primitive**

```svelte
<!-- frontend/src/lib/components/ui/switch/switch.svelte -->
<script lang="ts">
    import { Switch as SwitchPrimitive } from 'bits-ui';
    import { cn } from '$lib/utils';

    interface Props {
        checked?: boolean;
        onCheckedChange?: (next: boolean) => void;
        disabled?: boolean;
        id?: string;
        class?: string;
    }

    let {
        checked = $bindable(false),
        onCheckedChange,
        disabled,
        id,
        class: className = '',
    }: Props = $props();
</script>

<SwitchPrimitive.Root
    bind:checked
    {onCheckedChange}
    {disabled}
    {id}
    class={cn(
        'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        className,
    )}
>
    <SwitchPrimitive.Thumb
        class={cn(
            'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
            'data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0',
        )}
    />
</SwitchPrimitive.Root>
```

- [ ] **Step 3: Add the barrel export**

```ts
// frontend/src/lib/components/ui/switch/index.ts
export { default as Switch } from './switch.svelte';
```

- [ ] **Step 4: Confirm types compile**

```bash
cd frontend && npm run check
```

Expected: no new errors related to `switch.svelte`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/ui/switch
git commit -m "feat(F-0086): add shadcn-svelte Switch primitive"
```

---

## Task 11 · Frontend Zod schema: add `produces_lot`

**Files:**
- Modify: `frontend/src/lib/schemas/runs.ts:41-59` (RunSchema) and `:102-111` (RunCreatePayloadSchema)

- [ ] **Step 1: Update the schemas**

In `frontend/src/lib/schemas/runs.ts`:

Inside `RunSchema`, immediately before `lot_number`:

```ts
    produces_lot: z.boolean().default(false),
    lot_number: z.string().nullable().optional(),
    batch_number: z.string().nullable().optional(),
```

Inside `RunCreatePayloadSchema`, alongside `lot_number`:

```ts
    produces_lot: z.boolean().optional(),
    lot_number: z.string().optional(),
    batch_number: z.string().optional(),
```

- [ ] **Step 2: Confirm types compile**

```bash
cd frontend && npm run check
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/schemas/runs.ts
git commit -m "feat(F-0086): add produces_lot to Run zod schemas"
```

---

## Task 12 · Frontend: Run creator toggle + auto-generate + duplicate warning

**Files:**
- Modify: `frontend/src/lib/components/run/RunCreatorNameStep.svelte`
- Modify: `frontend/src/lib/components/run/RunCreatorNameStep.test.ts`
- Modify: every parent that passes props to `RunCreatorNameStep` (search with `rg RunCreatorNameStep frontend/src` — typically one wizard component).

### 12a · Component changes

- [ ] **Step 1: Update the prop signature and add the toggle UI**

Replace the existing component body with the version below. The structure mirrors the mockup (`docs/superpowers/specs/mockups/f0086-lot-producer.html`, frame 1).

```svelte
<script lang="ts">
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import { Switch } from '$lib/components/ui/switch';

    interface ExperimentOption {
        id: string;
        name: string;
        status?: string;
    }

    interface Props {
        name: string;
        experimentId: string | null;
        experiments: ExperimentOption[];
        lockedExperiment: { id: string; name: string } | null;
        producesLot?: boolean;
        lotNumber?: string;
        batchNumber?: string;
        projectId: string;
        onChange: (next: {
            name: string;
            experimentId: string | null;
            producesLot: boolean;
            lotNumber: string;
            batchNumber: string;
        }) => void;
        onValidate: (valid: boolean) => void;
    }

    let {
        name,
        experimentId,
        experiments,
        lockedExperiment,
        producesLot = false,
        lotNumber = '',
        batchNumber = '',
        projectId,
        onChange,
        onValidate,
    }: Props = $props();

    let duplicateCount = $state<number>(0);
    let autoGenerating = $state(false);

    const visibleExperiments = $derived(
        experiments.filter((e) => (e.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    $effect(() => {
        const baseValid = name.trim().length > 0;
        const lotValid = !producesLot || lotNumber.trim().length > 0;
        onValidate(baseValid && lotValid);
    });

    function emit(partial: Partial<{
        name: string;
        experimentId: string | null;
        producesLot: boolean;
        lotNumber: string;
        batchNumber: string;
    }>) {
        onChange({
            name,
            experimentId,
            producesLot,
            lotNumber,
            batchNumber,
            ...partial,
        });
    }

    function setName(v: string) { emit({ name: v }); }
    function setExperimentId(v: string) { emit({ experimentId: v === '' ? null : v }); }
    function setProducesLot(v: boolean) {
        if (!v) {
            // Clear lot value so a hidden, stale string can't leak through on submit.
            emit({ producesLot: false, lotNumber: '' });
            duplicateCount = 0;
        } else {
            emit({ producesLot: true });
        }
    }
    function setLotNumber(v: string) { emit({ lotNumber: v }); }
    function setBatchNumber(v: string) { emit({ batchNumber: v }); }

    async function autoGenerate() {
        autoGenerating = true;
        try {
            const res = await api.post<{ lot_number: string }>(
                '/science/runs/suggest-lot-number',
                { project_id: projectId },
            );
            setLotNumber(res.lot_number);
            duplicateCount = 0;
        } finally {
            autoGenerating = false;
        }
    }

    async function checkDuplicate() {
        if (!producesLot) { duplicateCount = 0; return; }
        const trimmed = lotNumber.trim();
        if (!trimmed) { duplicateCount = 0; return; }
        const res = await api.get<{ exists: boolean; count: number }>(
            `/science/runs/check-lot-number?project_id=${encodeURIComponent(projectId)}&lot_number=${encodeURIComponent(trimmed)}`,
        );
        // Subtract this run's own pending entry if needed — for a creator
        // flow the run doesn't exist yet, so the raw count is correct.
        duplicateCount = res.exists ? res.count : 0;
    }
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 1 · Name your run</h2>
        <p class="step-help">Pick a name you'll recognize on the runs list.</p>
    </header>

    <div class="field">
        <label for="run-name" class="field-label">Name</label>
        <input
            id="run-name"
            type="text"
            value={name}
            oninput={(e) => setName((e.target as HTMLInputElement).value)}
            placeholder="e.g. CHO-DG44 Run 1"
            class="input-field"
            autocomplete="off"
        />
    </div>

    <div class="field">
        <label for="run-experiment" class="field-label">
            Experiment <span class="optional">(optional)</span>
        </label>
        <select
            id="run-experiment"
            value={experimentId ?? ''}
            onchange={(e) => setExperimentId((e.target as HTMLSelectElement).value)}
            disabled={!!lockedExperiment}
            class="input-field"
        >
            {#if lockedExperiment}
                <option value={lockedExperiment.id}>{lockedExperiment.name}</option>
            {:else}
                <option value="">No experiment</option>
                {#each visibleExperiments as exp (exp.id)}
                    <option value={exp.id}>{exp.name}</option>
                {/each}
            {/if}
        </select>
        {#if lockedExperiment}
            <p class="hint">This run will belong to {lockedExperiment.name}.</p>
        {/if}
    </div>

    <div class="rounded-lg border border-border bg-card p-4 space-y-3">
        <div class="flex items-start justify-between gap-4">
            <div>
                <span class="text-sm font-medium text-foreground">This run produces a lot</span>
                <p class="text-xs text-muted-foreground mt-1">
                    Designate this run as the producer of a manufacturing lot.
                </p>
            </div>
            <Switch
                id="run-produces-lot"
                checked={producesLot}
                onCheckedChange={setProducesLot}
            />
        </div>

        {#if producesLot}
            <div class="field pt-1">
                <label for="run-lot" class="field-label flex items-center justify-between">
                    <span>Lot number</span>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onclick={autoGenerate}
                        disabled={autoGenerating}
                    >
                        {autoGenerating ? 'Generating…' : 'Auto-generate'}
                    </Button>
                </label>
                <input
                    id="run-lot"
                    type="text"
                    value={lotNumber}
                    oninput={(e) => setLotNumber((e.target as HTMLInputElement).value)}
                    onblur={checkDuplicate}
                    placeholder="LOT-000001"
                    class="input-field font-mono"
                    autocomplete="off"
                />
            </div>

            {#if duplicateCount > 0}
                <div
                    role="status"
                    class="flex items-start gap-3 rounded-md border-l-4 border-l-amber-400 bg-amber-50 px-4 py-3"
                    data-testid="lot-duplicate-warning"
                >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="mt-0.5 shrink-0 text-amber-600"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <p class="text-sm text-amber-900">
                        This lot number already exists in your org ({duplicateCount} run{duplicateCount !== 1 ? 's' : ''}). Lots may be re-entered intentionally — confirm or change.
                    </p>
                </div>
            {/if}
        {/if}
    </div>

    <div class="field">
        <label for="run-batch" class="field-label">
            Batch number <span class="optional">(optional)</span>
        </label>
        <input
            id="run-batch"
            type="text"
            value={batchNumber}
            oninput={(e) => setBatchNumber((e.target as HTMLInputElement).value)}
            placeholder="e.g. BATCH-42"
            class="input-field"
            autocomplete="off"
        />
    </div>
</section>

<style>
    /* Unchanged from current component — see file before edit for original block. */
    .step-body { max-width: 36rem; display: flex; flex-direction: column; gap: 1.25rem; }
    .step-header h2 { font-size: 1.25rem; font-weight: 600; color: rgb(15 23 42); }
    .step-help { font-size: 0.875rem; color: rgb(71 85 105); margin-top: 0.25rem; }
    .field { display: flex; flex-direction: column; gap: 0.375rem; }
    .field-label { font-size: 0.875rem; font-weight: 500; color: rgb(51 65 85); }
    .optional { color: rgb(148 163 184); font-weight: 400; }
    .input-field { width: 100%; padding: 0.5rem 0.75rem; border: 1px solid rgb(209 213 219); border-radius: 0.5rem; font-size: 0.875rem; background-color: white; }
    .input-field:focus { outline: none; border-color: transparent; box-shadow: 0 0 0 2px rgb(20 184 166); }
    .input-field:disabled { background-color: rgb(249 250 251); color: rgb(100 116 139); cursor: not-allowed; }
    .hint { font-size: 0.75rem; color: rgb(100 116 139); }
</style>
```

- [ ] **Step 2: Update parent caller(s)**

Search:

```bash
rg "RunCreatorNameStep" frontend/src
```

Open every caller. Update the `onChange` consumer to destructure `producesLot` and add `projectId={projectId}` to the props passed in. Each parent should already have a `projectId` in scope (it's a run-creation wizard); if not, plumb it through from the route param.

Typical edit pattern in the caller:

```svelte
<RunCreatorNameStep
    {name}
    {experimentId}
    {experiments}
    {lockedExperiment}
    {producesLot}
    {lotNumber}
    {batchNumber}
    projectId={projectIdFromRoute}
    onChange={(next) => {
        name = next.name;
        experimentId = next.experimentId;
        producesLot = next.producesLot;
        lotNumber = next.lotNumber;
        batchNumber = next.batchNumber;
    }}
    onValidate={(v) => { step1Valid = v; }}
/>
```

The component that ultimately posts `RunCreate` to the API must include `produces_lot: producesLot` in the body.

### 12b · Tests

- [ ] **Step 3: Update `RunCreatorNameStep.test.ts`**

Add three new tests (preserving the existing test):

```ts
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorNameStep from './RunCreatorNameStep.svelte';

const EXPERIMENTS = [{ id: 'e1', name: 'Exp 1' }];

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        post: vi.fn(),
    },
}));

import { api } from '$lib/api';

describe('RunCreatorNameStep · produces_lot', () => {
    it('hides lot input when toggle is off', () => {
        const { queryByLabelText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        expect(queryByLabelText(/Lot number/)).toBeNull();
    });

    it('shows lot input when producesLot is true', () => {
        const { getByLabelText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        expect(getByLabelText(/Lot number/)).toBeTruthy();
    });

    it('clicking Auto-generate populates the lot input via onChange', async () => {
        (api.post as any).mockResolvedValueOnce({ lot_number: 'LOT-000042' });
        let latest: any = null;
        const { getByText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: (next: any) => { latest = next; },
            onValidate: () => {},
        });
        await fireEvent.click(getByText('Auto-generate'));
        expect(api.post).toHaveBeenCalledWith(
            '/science/runs/suggest-lot-number',
            { project_id: 'p1' },
        );
        expect(latest.lotNumber).toBe('LOT-000042');
    });

    it('renders duplicate warning when check-lot-number returns exists=true', async () => {
        (api.get as any).mockResolvedValueOnce({ exists: true, count: 2 });
        const { getByLabelText, findByTestId } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: 'DUP-1',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        const input = getByLabelText(/Lot number/) as HTMLInputElement;
        await fireEvent.blur(input);
        const warning = await findByTestId('lot-duplicate-warning');
        expect(warning.textContent).toMatch(/already exists/);
    });
});
```

- [ ] **Step 4: Run the tests**

```bash
cd frontend && npm run test -- --run src/lib/components/run/RunCreatorNameStep.test.ts
```

Expected: all five tests (existing + new four) pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/run/RunCreatorNameStep.svelte \
        frontend/src/lib/components/run/RunCreatorNameStep.test.ts \
        <parent files modified in step 2>
git commit -m "feat(F-0086): run creator produces_lot toggle, auto-generate, duplicate warning"
```

---

## Task 13 · Frontend: RunsTab filter chip + Lot column

**Files:**
- Modify: `frontend/src/lib/components/project/RunsTab.svelte`
- Create: `frontend/src/lib/components/project/RunsTab.test.ts`

Implement the filter client-side over the `runs` prop. The backend filter (Task 5) is available for direct API consumers; the UI keeps the existing parent-loads-then-passes pattern.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/components/project/RunsTab.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunsTab from './RunsTab.svelte';

const RUNS = [
    { id: 'r1', name: 'producer-1', status: 'COMPLETED', produces_lot: true, lot_number: 'LOT-000001', experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
    { id: 'r2', name: 'non-prod', status: 'COMPLETED', produces_lot: false, lot_number: null, experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
];

describe('RunsTab · produces_lot filter', () => {
    it('filter chip hides non-producing runs when active', async () => {
        const { getByTestId, queryByText, getByText } = render(RunsTab, {
            runs: RUNS,
            protocols: [],
            experiments: [],
        });
        expect(getByText('producer-1')).toBeTruthy();
        expect(getByText('non-prod')).toBeTruthy();
        await fireEvent.click(getByTestId('lot-producer-filter'));
        expect(queryByText('non-prod')).toBeNull();
        expect(getByText('producer-1')).toBeTruthy();
    });

    it('Lot # column appears only when filter is active', async () => {
        const { getByTestId, queryByText } = render(RunsTab, {
            runs: RUNS,
            protocols: [],
            experiments: [],
        });
        expect(queryByText('Lot #')).toBeNull();
        await fireEvent.click(getByTestId('lot-producer-filter'));
        expect(queryByText('Lot #')).toBeTruthy();
    });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && npm run test -- --run src/lib/components/project/RunsTab.test.ts
```

- [ ] **Step 3: Add filter state, chip, and conditional column**

In `RunsTab.svelte`:

Inside `<script>`, after `let selectedRunIds = $state<Set<string>>(new Set());`:

```ts
    let lotProducerFilter = $state(false);

    const visibleRuns = $derived(
        lotProducerFilter ? enrichedRuns.filter((r: any) => r.produces_lot) : enrichedRuns
    );
```

Update the `columns` derivation so the Lot column appears between `name` and `experiment_name` when the filter is active:

```ts
    const columns = $derived.by(() => {
        const cols: any[] = [
            { key: 'id', label: 'ID', hideBelow: 'lg' as const },
            { key: 'name', label: 'Run Name', sortable: true },
        ];
        if (lotProducerFilter) {
            cols.push({ key: 'lot_number', label: 'Lot #', sortable: true });
        }
        if (!hideExperimentColumn) {
            cols.push({ key: 'experiment_name', label: 'Experiment', sortable: true, hideBelow: 'md' as const });
        }
        cols.push(
            { key: 'protocol_name', label: 'Protocol', sortable: true, hideBelow: 'md' as const },
            { key: 'status', label: 'Status', sortable: true },
            { key: 'updated_at', label: 'Last Modified', sortable: true, align: 'right' as const },
        );
        if (!hideExportColumn) {
            cols.push({ key: '_export', label: 'Export', align: 'right' as const });
        }
        return cols;
    });
```

Replace `items={enrichedRuns}` in `<ProjectDataTable>` with `items={visibleRuns}`.

Inside the `{#snippet toolbar()}` block, append the chip control (before the export button, or as a sibling):

```svelte
        <button
            type="button"
            data-testid="lot-producer-filter"
            onclick={() => { lotProducerFilter = !lotProducerFilter; }}
            class={lotProducerFilter
                ? 'inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2.5 py-1 text-xs font-medium'
                : 'inline-flex items-center gap-1 rounded-full border border-border text-foreground/70 hover:bg-muted px-2.5 py-1 text-xs font-medium'}
        >
            Lot producer only
            {#if lotProducerFilter}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
            {/if}
        </button>
```

Also render a Lot # cell inside the `{#snippet cells(r)}` block. Find the existing `cells` snippet and insert, right after the Name cell:

```svelte
        {#if lotProducerFilter}
            <td class="py-3 px-4 font-mono text-xs text-primary whitespace-nowrap">{r.lot_number ?? ''}</td>
        {/if}
```

(Match the existing `<td>` styling already in the file — peek the surrounding `cells` snippet for the exact class strings used in this codebase.)

- [ ] **Step 4: Run, confirm pass**

```bash
cd frontend && npm run test -- --run src/lib/components/project/RunsTab.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/project/RunsTab.svelte \
        frontend/src/lib/components/project/RunsTab.test.ts
git commit -m "feat(F-0086): RunsTab filter chip and lot column"
```

---

## Task 14 · Frontend: inline Lot output card on run detail page

**Files:**
- Modify: `frontend/src/routes/runs/[id]/+page.svelte`

Add a small card visible in all run statuses that lets the user toggle `produces_lot`, edit `lot_number`, auto-generate, and Save. Save dispatches a PUT to `/science/runs/{id}` with `{produces_lot, lot_number}`.

- [ ] **Step 1: Locate the right-column section of the run detail page**

Open `frontend/src/routes/runs/[id]/+page.svelte`. Find the right-column grid where attachments/notes/history live (around the tab bar near line 384 or wherever the run-overview/right-sidebar lives). The Lot output card sits in this column.

- [ ] **Step 2: Add component state**

Inside `<script>`:

```ts
    import { Switch } from '$lib/components/ui/switch';
    import { Button } from '$lib/components/ui/button';
    // ... existing imports

    // F-0086: editable lot fields. Drafted locally; committed via Save.
    let lotDraftProducesLot = $state(false);
    let lotDraftLotNumber = $state('');
    let lotDuplicateCount = $state(0);
    let lotSaving = $state(false);

    $effect(() => {
        // Re-seed from run whenever the loaded run changes.
        if (run) {
            lotDraftProducesLot = run.produces_lot ?? false;
            lotDraftLotNumber = run.lot_number ?? '';
            lotDuplicateCount = 0;
        }
    });

    const lotDraftDirty = $derived(
        run && (lotDraftProducesLot !== (run.produces_lot ?? false)
            || lotDraftLotNumber !== (run.lot_number ?? ''))
    );

    async function lotAutoGenerate() {
        if (!run) return;
        const res = await api.post<{ lot_number: string }>(
            '/science/runs/suggest-lot-number',
            { project_id: run.project_id },
        );
        lotDraftLotNumber = res.lot_number;
        lotDuplicateCount = 0;
    }

    async function lotCheckDuplicate() {
        if (!run || !lotDraftProducesLot || !lotDraftLotNumber.trim()) {
            lotDuplicateCount = 0;
            return;
        }
        const res = await api.get<{ exists: boolean; count: number }>(
            `/science/runs/check-lot-number?project_id=${encodeURIComponent(run.project_id)}&lot_number=${encodeURIComponent(lotDraftLotNumber.trim())}`,
        );
        // Subtract this run's own row if its current lot_number matches.
        const ownCount = run.lot_number === lotDraftLotNumber.trim() ? 1 : 0;
        lotDuplicateCount = res.exists ? Math.max(0, res.count - ownCount) : 0;
    }

    async function lotSave() {
        if (!run) return;
        lotSaving = true;
        try {
            const updated = await api.put(`/science/runs/${run.id}`, {
                produces_lot: lotDraftProducesLot,
                lot_number: lotDraftProducesLot ? lotDraftLotNumber.trim() : null,
            });
            run = updated as any;
        } finally {
            lotSaving = false;
        }
    }

    function lotDiscard() {
        if (!run) return;
        lotDraftProducesLot = run.produces_lot ?? false;
        lotDraftLotNumber = run.lot_number ?? '';
        lotDuplicateCount = 0;
    }
```

(If the page already loads `run` differently — e.g., into a store — adapt the variable references accordingly. The shape is: read current values from the source of truth, hold a local draft, dispatch PUT on Save, refresh the source of truth.)

- [ ] **Step 3: Add the card to the right column**

Insert beside the existing cards in the right column:

```svelte
<div class="rounded-xl border border-border bg-card text-card-foreground shadow-sm p-5 space-y-4">
    <div class="flex items-start justify-between gap-4">
        <div>
            <p class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Lot output</p>
            <p class="text-sm mt-1 text-muted-foreground">This run produces a manufacturing lot.</p>
        </div>
        <Switch
            checked={lotDraftProducesLot}
            onCheckedChange={(v) => { lotDraftProducesLot = v; if (!v) lotDraftLotNumber = ''; lotDuplicateCount = 0; }}
        />
    </div>

    {#if lotDraftProducesLot}
        <div class="space-y-1.5">
            <label class="text-sm font-medium flex items-center justify-between" for="run-detail-lot">
                <span>Lot number</span>
                <Button type="button" variant="ghost" size="sm" onclick={lotAutoGenerate}>
                    Auto-generate
                </Button>
            </label>
            <input
                id="run-detail-lot"
                class="w-full font-mono px-3 py-2 text-sm rounded-md border border-input bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                bind:value={lotDraftLotNumber}
                onblur={lotCheckDuplicate}
                placeholder="LOT-000001"
            />
            <p class="text-xs text-muted-foreground">Edits write to the run audit log.</p>
        </div>

        {#if lotDuplicateCount > 0}
            <div
                role="status"
                class="flex items-start gap-3 rounded-md border-l-4 border-l-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900"
                data-testid="lot-duplicate-warning"
            >
                <span class="font-medium">{lotDuplicateCount} other run{lotDuplicateCount !== 1 ? 's' : ''}</span>
                <span>in this org already use this lot number.</span>
            </div>
        {/if}
    {/if}

    <div class="flex items-center justify-end gap-2 pt-1">
        <Button variant="ghost" size="sm" onclick={lotDiscard} disabled={!lotDraftDirty || lotSaving}>
            Discard
        </Button>
        <Button size="sm" onclick={lotSave} disabled={!lotDraftDirty || lotSaving || (lotDraftProducesLot && !lotDraftLotNumber.trim())}>
            {lotSaving ? 'Saving…' : 'Save'}
        </Button>
    </div>
</div>
```

- [ ] **Step 4: Smoke-check the page renders**

```bash
cd frontend && npm run check
```

Then manual smoke test in the browser:

```bash
# (in two terminals or background)
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload
cd frontend && npm run dev
```

Open a run detail page; toggle Lot output on; click Auto-generate; click Save; reload the page; confirm the value persists. Toggle off; Save; reload; confirm `produces_lot` is false and the field hides.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/runs/[id]/+page.svelte
git commit -m "feat(F-0086): inline Lot output editor on run detail page"
```

---

## Task 15 · Full-suite sanity + lint

- [ ] **Step 1: Backend full suite**

```bash
cd backend && source .venv/bin/activate
pytest -q
```

Expected: green. Focus on `tests/unit/test_run_produces_lot.py`, `tests/unit/test_template_engine_produces_lot.py`, `tests/integration/test_run_produces_lot_api.py`, `tests/integration/test_batch_record_produces_lot.py`, plus the existing `test_default_template_render.py`, `test_br_template_smoke.py`, `test_run_production_metadata.py`.

- [ ] **Step 2: Backend lint**

```bash
black app tests && isort app tests
```

If `black`/`isort` reformat anything, amend with a follow-up `chore:` commit rather than amending feature commits.

- [ ] **Step 3: Frontend type-check and tests**

```bash
cd frontend && npm run check && npm run test -- --run
```

Expected: green.

- [ ] **Step 4: Commit any lint follow-ups (only if needed)**

```bash
git add -A
git commit -m "chore(F-0086): apply black/isort formatting"
```

---

## Self-Review Checklist (post-write)

1. **Spec coverage:**
   - Add `produces_lot` column + migration → Task 1, 2 ✓
   - Schemas → Task 3 ✓
   - Validation in POST/PUT → Task 4 ✓
   - List filter `?produces_lot=` → Task 5 ✓
   - `POST /suggest-lot-number` → Task 6 ✓
   - `GET /check-lot-number` → Task 7 ✓
   - Template engine `KNOWN_VARIABLES` + context → Task 8 ✓
   - Batch-record template binding + `{%tr if produces_lot %}` → Task 9 ✓
   - Switch primitive → Task 10 ✓
   - Frontend Zod → Task 11 ✓
   - Run creator UI + tests → Task 12 ✓
   - Runs table filter chip + lot column + tests → Task 13 ✓
   - Run detail inline editor → Task 14 ✓
   - Audit via existing `log_audit()` → no new task needed; PUT /runs/{id} already wraps with `log_audit("UPDATE", ...)` capturing `model_dump(exclude_unset=True)`.

2. **Placeholders:** the docx-render test in Task 9 names a render function (`render_to_docx_bytes`) that may or may not already exist — the task instruction explicitly says check what's exported and use `render_to_pdf` or add a small helper. That is a real branch with a clear default; not a TBD. The template-engine "skip" test in Task 8 is an explicit skip pending discovery of the right wrapper, with the integration render test in Task 9 acting as backup coverage. Acceptable.

3. **Type consistency:**
   - Schema field name `produces_lot` consistent backend/frontend.
   - Endpoint paths `/science/runs/suggest-lot-number` and `/science/runs/check-lot-number` used in tasks 6, 7, 12, 14.
   - Migration revision `f0043` referenced only in Task 1; downstream tasks rely on `alembic upgrade head` instead of the revision id.
   - `LOT-{seq:06d}` format consistent across spec, suggest endpoint, regex, tests.

4. **Frequent commits:** every task ends with a commit step; no >1 task per commit.
