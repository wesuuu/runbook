# F-0015 Onboarding Tour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a user-controlled, segmented driver.js onboarding tour covering Projects, Protocol Editor, and Runner — with a seeded "My First Project" per new org, on-demand sample protocol (kept) and sample run (auto-deleted on tour end), plus pulsing hint dots on untoured pages and empty-state CTAs that route into the tour.

**Architecture:** Backend persists `User.tour_state` (JSONB) and adds `is_tour_sample` to `Protocol` / `Run`; six endpoints under `/api/onboarding/` manage state and sample artifacts. Frontend mounts a Svelte 5 rune store `tourStore.svelte.ts` (hydrated on login) that drives three driver.js tour configs, a reusable two-button modal, a pulsing dot, and a help menu. Empty states get a secondary "Take the tour" CTA that routes to the same welcome modal.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async, asyncpg) + Alembic; Svelte 5 (runes) + SvelteKit + shadcn-svelte/bits-ui + driver.js 1.x + Tailwind 4 + Vitest + Playwright.

**Spec:** `docs/superpowers/specs/2026-04-17-f-0015-onboarding-tour-design.md`

**Task ID:** F-0015

---

## Phase 1 — Backend foundation (schema, services, endpoints)

### Task 1: Add `tour_state` JSONB column to `User` model

**Files:**
- Modify: `backend/app/models/iam.py:131`

- [ ] **Step 1: Add the column**

In `backend/app/models/iam.py`, find the `preferences` column (around line 131) and add a sibling `tour_state` column immediately below it:

```python
    tour_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/iam.py
git commit -m "feat(backend): add User.tour_state JSONB column [F-0015]"
```

---

### Task 2: Add `is_tour_sample` to `Protocol` and `Run`

**Files:**
- Modify: `backend/app/models/science.py:110` and `backend/app/models/science.py:184`

- [ ] **Step 1: Add the column to `Protocol`**

In `backend/app/models/science.py`, after the `version_number` column (around line 109), add:

```python
    is_tour_sample: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
```

- [ ] **Step 2: Add the column to `Run`**

After the `experiment_id` column (around line 184), add:

```python
    is_tour_sample: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
```

- [ ] **Step 3: Ensure `Boolean` is imported**

Confirm `Boolean` is in the SQLAlchemy imports at the top of `backend/app/models/science.py`. If not, add it:

```python
from sqlalchemy import Boolean
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/science.py
git commit -m "feat(backend): add is_tour_sample to Protocol and Run [F-0015]"
```

---

### Task 3: Generate and apply Alembic migration

**Files:**
- Create: `backend/alembic/versions/<hash>_add_tour_state_and_tour_sample_flags.py`

- [ ] **Step 1: Generate migration**

From `backend/` with venv activated:

```bash
cd backend && source .venv/bin/activate
alembic revision --autogenerate -m "add tour_state and is_tour_sample flags [F-0015]"
```

- [ ] **Step 2: Review the generated file**

Open the new file in `backend/alembic/versions/`. Verify three upgrades are present (order may vary):

```python
op.add_column(
    "users",
    sa.Column(
        "tour_state",
        postgresql.JSONB(astext_type=sa.Text()),
        server_default="{}",
        nullable=False,
    ),
)
op.add_column(
    "protocols",
    sa.Column(
        "is_tour_sample",
        sa.Boolean(),
        server_default="false",
        nullable=False,
    ),
)
op.create_index(
    op.f("ix_protocols_is_tour_sample"), "protocols",
    ["is_tour_sample"], unique=False,
)
op.add_column(
    "runs",
    sa.Column(
        "is_tour_sample",
        sa.Boolean(),
        server_default="false",
        nullable=False,
    ),
)
op.create_index(
    op.f("ix_runs_is_tour_sample"), "runs",
    ["is_tour_sample"], unique=False,
)
```

If any are missing, add them manually. Verify the `downgrade()` drops all three columns + indexes.

- [ ] **Step 3: Apply migration**

```bash
alembic upgrade head
```

Expected: "Running upgrade ..." with no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(backend): migration for tour_state and is_tour_sample [F-0015]"
```

---

### Task 4: Define Pydantic schemas for onboarding

**Files:**
- Create: `backend/app/schemas/onboarding.py`

- [ ] **Step 1: Write schemas**

```python
"""Pydantic schemas for the onboarding tour."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

TourSegment = Literal["project", "protocol", "run"]
TourStatus = Literal["completed", "dismissed"]


class TourStateResponse(BaseModel):
    completed: list[TourSegment] = []
    dismissed: list[TourSegment] = []
    model_config = ConfigDict(from_attributes=True)


class TourStateUpdate(BaseModel):
    segment: TourSegment
    status: TourStatus


class TourProjectStartResponse(BaseModel):
    project_id: UUID


class TourProtocolStartResponse(BaseModel):
    project_id: UUID
    protocol_id: UUID


class TourRunStartResponse(BaseModel):
    run_id: UUID
    protocol_id: UUID
    project_id: UUID
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/onboarding.py
git commit -m "feat(backend): onboarding pydantic schemas [F-0015]"
```

---

### Task 5: Write failing unit tests for the onboarding service

**Files:**
- Create: `backend/tests/unit/test_onboarding_service.py`

- [ ] **Step 1: Write the tests**

```python
"""Unit tests for app.services.onboarding."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.science import Project, Protocol, Run
from app.services.onboarding import (
    delete_sample_run,
    find_or_create_sample_project,
    find_or_create_sample_protocol,
    find_or_create_sample_run,
    get_sample_protocol_graph,
)


@pytest_asyncio.fixture
async def org_and_user(db: AsyncSession):
    org = Organization(name="Acme")
    db.add(org)
    await db.flush()
    user = User(
        email="sample@example.com",
        hashed_password="x",
        selected_org_id=org.id,
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    return org, user


@pytest.mark.asyncio
async def test_get_sample_protocol_graph_returns_prepopulated_nodes():
    graph = get_sample_protocol_graph()
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) >= 3
    assert len(graph["edges"]) >= 2


@pytest.mark.asyncio
async def test_find_or_create_sample_project_creates_when_none(db, org_and_user):
    org, user = org_and_user
    project = await find_or_create_sample_project(db, user, org)
    assert project.id is not None
    assert project.organization_id == org.id


@pytest.mark.asyncio
async def test_find_or_create_sample_project_reuses_existing_active(db, org_and_user):
    org, user = org_and_user
    existing = Project(name="Existing", organization_id=org.id)
    db.add(existing)
    await db.commit()

    project = await find_or_create_sample_project(db, user, org)
    assert project.id == existing.id


@pytest.mark.asyncio
async def test_find_or_create_sample_protocol_marks_flag(db, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db, user, org)
    assert protocol.is_tour_sample is True
    assert protocol.project_id is not None
    assert len(protocol.graph.get("nodes", [])) >= 3


@pytest.mark.asyncio
async def test_find_or_create_sample_protocol_reuses_by_flag(db, org_and_user):
    org, user = org_and_user
    first = await find_or_create_sample_protocol(db, user, org)
    second = await find_or_create_sample_protocol(db, user, org)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_find_or_create_sample_run_cleans_orphans(db, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db, user, org)
    first = await find_or_create_sample_run(db, user, protocol)
    second = await find_or_create_sample_run(db, user, protocol)

    # Second call should have deleted the first and created a new one
    assert first.id != second.id
    result = await db.get(Run, first.id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_sample_run_is_idempotent(db, org_and_user):
    org, user = org_and_user
    protocol = await find_or_create_sample_protocol(db, user, org)
    run = await find_or_create_sample_run(db, user, protocol)

    await delete_sample_run(db, user)
    await delete_sample_run(db, user)  # second call is no-op

    result = await db.get(Run, run.id)
    assert result is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/test_onboarding_service.py -v
```

Expected: All tests fail with `ModuleNotFoundError: No module named 'app.services.onboarding'`.

---

### Task 6: Implement the onboarding service

**Files:**
- Create: `backend/app/services/onboarding.py`

- [ ] **Step 1: Write the service module**

```python
"""Onboarding tour artifact helpers.

Find-or-create sample projects, protocols, and runs used during the guided
tour. Sample protocol/run are flagged with is_tour_sample=True; sample
project is a normal project that the user can rename or delete freely.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import Organization, User
from app.models.science import Project, Protocol, Run, RunStatus

SAMPLE_PROJECT_NAME = "My First Project"
SAMPLE_PROTOCOL_NAME = "Sample Protocol"
SAMPLE_RUN_NAME = "Sample Run"


def get_sample_protocol_graph() -> dict[str, Any]:
    """Return the pre-populated graph for the sample protocol.

    Three unit-op nodes in a linear chain, illustrating typical media-prep
    through seeding. Spotlight targets are CSS selectors on editor chrome,
    not node IDs, so the tour stays stable if the user edits this graph.
    """
    return {
        "nodes": [
            {
                "id": "sample-buffer",
                "type": "unitOp",
                "position": {"x": 100, "y": 150},
                "data": {
                    "label": "Buffer Prep",
                    "category": "Media Prep",
                    "duration_min": 30,
                    "params": {"buffer_name": "PBS", "volume_L": 10},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "buffer_name": {"type": "string", "default": "PBS"},
                            "volume_L": {"type": "number", "default": 10},
                        },
                    },
                },
            },
            {
                "id": "sample-media",
                "type": "unitOp",
                "position": {"x": 400, "y": 150},
                "data": {
                    "label": "Media Prep",
                    "category": "Media Prep",
                    "duration_min": 45,
                    "params": {"media_name": "DMEM", "volume_L": 5},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "media_name": {"type": "string", "default": "DMEM"},
                            "volume_L": {"type": "number", "default": 5},
                        },
                    },
                },
            },
            {
                "id": "sample-seed",
                "type": "unitOp",
                "position": {"x": 700, "y": 150},
                "data": {
                    "label": "Seeding",
                    "category": "Cell Culture",
                    "duration_min": 60,
                    "params": {"cell_density": 1e6},
                    "paramSchema": {
                        "type": "object",
                        "properties": {
                            "cell_density": {"type": "number", "default": 1e6},
                        },
                    },
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "sample-buffer", "target": "sample-media"},
            {"id": "e2", "source": "sample-media", "target": "sample-seed"},
        ],
        "layout": "horizontal",
        "handleOrientation": "horizontal",
        "timeEnabled": False,
        "startTime": "08:00",
        "pixelsPerHour": 200,
    }


async def find_or_create_sample_project(
    db: AsyncSession, user: User, org: Organization
) -> Project:
    """Return any active project for the org; create one if none exists.

    The project returned is just a normal project (no is_tour_sample
    flag) — sample projects are indistinguishable from user projects
    after creation.
    """
    stmt = (
        select(Project)
        .where(Project.organization_id == org.id)
        .limit(1)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if project is not None:
        return project

    project = Project(
        name=SAMPLE_PROJECT_NAME,
        description="Seeded by the onboarding tour.",
        organization_id=org.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def find_or_create_sample_protocol(
    db: AsyncSession, user: User, org: Organization
) -> Protocol:
    """Return the user's org's sample protocol; create with a pre-populated graph if missing.

    Sample protocols are nested under a project (so project_id is set); we match
    by is_tour_sample=True joined to a project in the given org.
    """
    result = await db.execute(
        select(Protocol)
        .join(Project, Project.id == Protocol.project_id)
        .where(
            Protocol.is_tour_sample.is_(True),
            Project.organization_id == org.id,
        )
        .limit(1)
    )
    protocol = result.scalar_one_or_none()
    if protocol is not None:
        return protocol

    project = await find_or_create_sample_project(db, user, org)
    protocol = Protocol(
        name=SAMPLE_PROTOCOL_NAME,
        description="A pre-built sample to illustrate the protocol editor.",
        project_id=project.id,
        status="DRAFT",
        graph=get_sample_protocol_graph(),
        is_tour_sample=True,
    )
    db.add(protocol)
    await db.commit()
    await db.refresh(protocol)
    return protocol


async def find_or_create_sample_run(
    db: AsyncSession, user: User, protocol: Protocol
) -> Run:
    """Delete any prior sample run for this user, then create a fresh one."""
    # Clean up orphans (belt-and-suspenders for closed browsers)
    await delete_sample_run(db, user)

    run = Run(
        name=SAMPLE_RUN_NAME,
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        status=RunStatus.PLANNED,
        graph=protocol.graph,
        started_by_id=user.id,
        is_tour_sample=True,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def delete_sample_run(db: AsyncSession, user: User) -> None:
    """Delete this user's sample run, if any. Idempotent."""
    stmt = (
        select(Run)
        .where(
            Run.is_tour_sample.is_(True),
            Run.started_by_id == user.id,
        )
    )
    result = await db.execute(stmt)
    for run in result.scalars().all():
        await db.delete(run)
    await db.commit()
```

- [ ] **Step 2: Run tests to verify pass**

```bash
pytest tests/unit/test_onboarding_service.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/onboarding.py backend/tests/unit/test_onboarding_service.py
git commit -m "feat(backend): onboarding service with find-or-create helpers [F-0015]"
```

---

### Task 7: Write failing integration tests for onboarding endpoints

**Files:**
- Create: `backend/tests/integration/test_onboarding_api.py`

- [ ] **Step 1: Write the tests**

```python
"""Integration tests for /onboarding endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_state_requires_auth(client: AsyncClient):
    resp = await client.get("/onboarding/state")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_state_returns_empty_for_new_user(auth_client: AsyncClient):
    resp = await auth_client.get("/onboarding/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"completed": [], "dismissed": []}


@pytest.mark.asyncio
async def test_patch_state_marks_segment_completed(auth_client: AsyncClient):
    resp = await auth_client.patch(
        "/onboarding/state",
        json={"segment": "project", "status": "completed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] == ["project"]
    assert data["dismissed"] == []


@pytest.mark.asyncio
async def test_patch_state_marks_segment_dismissed(auth_client: AsyncClient):
    resp = await auth_client.patch(
        "/onboarding/state",
        json={"segment": "run", "status": "dismissed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dismissed"] == ["run"]


@pytest.mark.asyncio
async def test_patch_state_rejects_bad_segment(auth_client: AsyncClient):
    resp = await auth_client.patch(
        "/onboarding/state",
        json={"segment": "bogus", "status": "completed"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tour_project_start_returns_project_id(auth_client: AsyncClient):
    resp = await auth_client.post("/onboarding/tour/project/start")
    assert resp.status_code == 200
    assert "project_id" in resp.json()


@pytest.mark.asyncio
async def test_tour_protocol_start_returns_ids(auth_client: AsyncClient):
    resp = await auth_client.post("/onboarding/tour/protocol/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "project_id" in data
    assert "protocol_id" in data


@pytest.mark.asyncio
async def test_tour_run_start_returns_run(auth_client: AsyncClient):
    resp = await auth_client.post("/onboarding/tour/run/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data


@pytest.mark.asyncio
async def test_tour_run_end_is_idempotent(auth_client: AsyncClient):
    # Call twice — both should succeed regardless of prior state
    resp1 = await auth_client.post("/onboarding/tour/run/end")
    assert resp1.status_code == 200
    resp2 = await auth_client.post("/onboarding/tour/run/end")
    assert resp2.status_code == 200
```

- [ ] **Step 2: Confirm the `auth_client` fixture**

If `backend/tests/conftest.py` does not already provide `auth_client` (authenticated `httpx.AsyncClient`), look for it in `backend/tests/integration/conftest.py`. If missing, we'll wire one up — but most integration tests here already depend on one. Skip this step if `auth_client` exists.

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/integration/test_onboarding_api.py -v
```

Expected: all fail with 404 Not Found (endpoints don't exist yet).

---

### Task 8: Implement the onboarding endpoints

**Files:**
- Create: `backend/app/api/endpoints/onboarding.py`
- Modify: `backend/app/main.py` (router registration)

- [ ] **Step 1: Write the router**

```python
"""Onboarding tour API — state and sample artifact lifecycle."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.iam import Organization, User
from app.schemas.onboarding import (
    TourProjectStartResponse,
    TourProtocolStartResponse,
    TourRunStartResponse,
    TourStateResponse,
    TourStateUpdate,
)
from app.services.onboarding import (
    delete_sample_run,
    find_or_create_sample_project,
    find_or_create_sample_protocol,
    find_or_create_sample_run,
)

router = APIRouter()


async def _get_current_org(db: AsyncSession, user: User) -> Organization:
    if user.selected_org_id is None:
        raise HTTPException(status_code=400, detail="No org selected")
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    return org


@router.get("/state", response_model=TourStateResponse)
async def get_tour_state(
    user: User = Depends(get_current_user),
):
    state = user.tour_state or {}
    return TourStateResponse(
        completed=state.get("completed", []),
        dismissed=state.get("dismissed", []),
    )


@router.patch("/state", response_model=TourStateResponse)
async def patch_tour_state(
    body: TourStateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    state = dict(user.tour_state or {})
    completed = list(state.get("completed", []))
    dismissed = list(state.get("dismissed", []))

    # Remove from both lists first (idempotent); then add to the target list.
    completed = [s for s in completed if s != body.segment]
    dismissed = [s for s in dismissed if s != body.segment]
    if body.status == "completed":
        completed.append(body.segment)
    else:
        dismissed.append(body.segment)

    user.tour_state = {"completed": completed, "dismissed": dismissed}
    await db.commit()
    await db.refresh(user)
    return TourStateResponse(completed=completed, dismissed=dismissed)


@router.post(
    "/tour/project/start", response_model=TourProjectStartResponse
)
async def tour_project_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_current_org(db, user)
    project = await find_or_create_sample_project(db, user, org)
    return TourProjectStartResponse(project_id=project.id)


@router.post(
    "/tour/protocol/start", response_model=TourProtocolStartResponse
)
async def tour_protocol_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_current_org(db, user)
    protocol = await find_or_create_sample_protocol(db, user, org)
    return TourProtocolStartResponse(
        project_id=protocol.project_id,
        protocol_id=protocol.id,
    )


@router.post("/tour/run/start", response_model=TourRunStartResponse)
async def tour_run_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await _get_current_org(db, user)
    protocol = await find_or_create_sample_protocol(db, user, org)
    run = await find_or_create_sample_run(db, user, protocol)
    return TourRunStartResponse(
        run_id=run.id,
        protocol_id=protocol.id,
        project_id=run.project_id,
    )


@router.post("/tour/run/end")
async def tour_run_end(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_sample_run(db, user)
    return {"ok": True}
```

- [ ] **Step 2: Register the router**

In `backend/app/main.py`, find the line:

```python
from app.api.endpoints import auth, ...
```

Add `onboarding` to the import list. Then find where routers are included (around `app.include_router(auth.router, prefix="/auth", tags=["auth"])`) and add:

```python
app.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
```

- [ ] **Step 3: Run integration tests**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_onboarding_api.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/endpoints/onboarding.py backend/app/main.py backend/tests/integration/test_onboarding_api.py
git commit -m "feat(backend): onboarding endpoints (state + sample lifecycle) [F-0015]"
```

---

### Task 9: Seed "My First Project" on org registration

**Files:**
- Modify: `backend/app/api/endpoints/auth.py:178` (the `register` function)
- Modify: `backend/tests/integration/test_auth_api.py` (or equivalent)

- [ ] **Step 1: Write a failing test**

In `backend/tests/integration/test_auth_api.py`, add:

```python
@pytest.mark.asyncio
async def test_register_seeds_first_project(client: AsyncClient, db):
    from app.models.iam import Organization
    from app.models.science import Project
    from sqlalchemy import select

    with patch("app.api.endpoints.auth.get_email_provider") as mock_provider:
        mock_provider.return_value = AsyncMock()
        resp = await client.post(
            "/auth/register",
            json={
                "email": "seeded@example.com",
                "password": "securepass",
                "full_name": "Seeded User",
            },
        )
    assert resp.status_code == 200

    org_res = await db.execute(
        select(Organization).where(Organization.name == "Seeded User's Organization")
    )
    org = org_res.scalar_one()
    proj_res = await db.execute(
        select(Project).where(Project.organization_id == org.id)
    )
    projects = proj_res.scalars().all()
    assert len(projects) == 1
    assert projects[0].name == "My First Project"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_auth_api.py::test_register_seeds_first_project -v
```

Expected: FAIL — no project is created yet.

- [ ] **Step 3: Update the register endpoint**

In `backend/app/api/endpoints/auth.py`, after the `OrganizationMember` `db.add(...)` call (around line 182), add the project seeding:

```python
    from app.models.science import Project

    db.add(Project(
        name="My First Project",
        description="Created for you — rename or delete as you like.",
        organization_id=org.id,
    ))
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/integration/test_auth_api.py::test_register_seeds_first_project -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_auth_api.py
git commit -m "feat(backend): seed 'My First Project' on org registration [F-0015]"
```

---

### Task 10: Add a fresh demo user for tour testing

This adds a verified-but-empty seed user so you can log in and see the welcome modal pop up. The user has an empty `tour_state` (default), their own org, and a single "My First Project" — so the first-login experience is indistinguishable from a real new signup.

**Files:**
- Modify: `backend/app/db/seed.py`

- [ ] **Step 1: Add the user UUID constants**

In `backend/app/db/seed.py`, after the existing `USER_VIEWER` UUID constant (around line 42), add:

```python
USER_NEWBIE = uuid.UUID("20000000-0000-0000-0000-0000000000ff")
ORG_ID_NEWBIE = uuid.UUID("10000000-0000-0000-0000-0000000000ff")
PROJECT_NEWBIE = uuid.UUID("40000000-0000-0000-0000-0000000000ff")
```

- [ ] **Step 2: Add a new seed function**

After the existing `seed_projects` function (or wherever the order makes sense — before `main`), add:

```python
async def seed_newbie_user(db: AsyncSession):
    """Create a fresh, email-verified user with an empty tour_state.

    Used for manually testing the F-0015 onboarding tour. The user has
    their own org and a single "My First Project" — matching what a real
    new signup looks like, so the welcome modal auto-opens on login.
    """
    # Fresh org just for this user
    await _upsert(
        db, Organization, ORG_ID_NEWBIE, name="Newbie's Organization"
    )

    user = await _upsert(
        db, User, USER_NEWBIE,
        email="newbie@bioprocess.com",
        hashed_password=DEFAULT_PASSWORD,
        full_name="Newbie Tester",
        selected_org_id=ORG_ID_NEWBIE,
        email_verified=True,
    )
    # Always reset tour_state so repeated seeds give a clean test experience
    user.tour_state = {}

    # Org membership (ADMIN)
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == USER_NEWBIE,
            OrganizationMember.organization_id == ORG_ID_NEWBIE,
        )
    )
    if result.scalar_one_or_none() is None:
        db.add(OrganizationMember(
            user_id=USER_NEWBIE,
            organization_id=ORG_ID_NEWBIE,
            role="ADMIN",
        ))

    # Seed a single starter project (mirrors what auth/register does)
    await _upsert(
        db, Project, PROJECT_NEWBIE,
        name="My First Project",
        description="Created for you — rename or delete as you like.",
        organization_id=ORG_ID_NEWBIE,
    )

    await db.flush()
```

- [ ] **Step 3: Call it from `main()`**

Find the `main()` coroutine at the bottom of `seed.py`. Inside its transaction block (after the existing seed function calls like `seed_users`, `seed_org`, etc.), add:

```python
        await seed_newbie_user(db)
```

- [ ] **Step 4: Re-seed the database**

```bash
cd backend && source .venv/bin/activate
python -m app.db.seed
```

Expected: existing seed data is untouched, plus a new `newbie@bioprocess.com` user exists with an empty `tour_state`.

Alternative: if you prefer a clean slate, use `../scripts/reset-db.sh` which wipes user data and re-seeds.

- [ ] **Step 5: Test manually**

1. Log in at `http://localhost:5173` as `newbie@bioprocess.com` / `password123`.
2. Dashboard should load and the welcome modal should auto-open.
3. Clicking "Check out how projects are laid out" should navigate to `/projects/<uuid>?tour=project` and start the driver.js walkthrough.
4. Clicking "Dismiss" should close the modal and suppress it on refresh.

(Obviously steps 2–4 won't work until the frontend Phase 3 tasks are done. But you can verify the user + org + project exist in the DB now.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/seed.py
git commit -m "chore(seed): add newbie user for F-0015 tour testing [F-0015]"
```

---

### Task 11: Bypass archival guard when deleting sample protocols

**Files:**
- Modify: `backend/app/api/endpoints/protocols.py:366-437`
- Modify: `backend/tests/integration/test_protocols_api.py` (or add a new test file)

- [ ] **Step 1: Write a failing test**

In `backend/tests/integration/test_protocols_api.py`, add:

```python
@pytest.mark.asyncio
async def test_delete_sample_protocol_hard_deletes(auth_client, db, user, org):
    from app.models.science import Project, Protocol
    from sqlalchemy import select

    project = Project(name="P", organization_id=org.id)
    db.add(project)
    await db.flush()

    proto = Protocol(
        name="Sample",
        project_id=project.id,
        status="APPROVED",    # Would normally be blocked from hard-delete
        is_tour_sample=True,
    )
    db.add(proto)
    await db.commit()

    resp = await auth_client.delete(f"/science/protocols/{proto.id}")
    assert resp.status_code == 200
    assert resp.json()["action"] == "deleted"

    result = await db.execute(select(Protocol).where(Protocol.id == proto.id))
    assert result.scalar_one_or_none() is None
```

(Check `backend/tests/integration/conftest.py` for the shape of `user` / `org` fixtures. If they don't exist, adapt to match the existing auth_client setup.)

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_protocols_api.py::test_delete_sample_protocol_hard_deletes -v
```

Expected: FAIL — protocol gets archived, not deleted.

- [ ] **Step 3: Patch the delete endpoint**

In `backend/app/api/endpoints/protocols.py`, inside `delete_or_archive_protocol`, immediately after permission checks and before the `PENDING_APPROVAL` guard (around line 389), add:

```python
    # Sample/tour protocols always hard-delete, bypassing status guards.
    if protocol.is_tour_sample:
        await log_audit(
            db, user.id, "DELETE", "Protocol",
            protocol.id,
            {"name": protocol.name, "action": "hard_delete_sample"},
        )
        await db.delete(protocol)
        await db.commit()
        return {"action": "deleted", "protocol_id": str(protocol_id)}
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/integration/test_protocols_api.py::test_delete_sample_protocol_hard_deletes -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocols.py backend/tests/integration/test_protocols_api.py
git commit -m "feat(backend): bypass archival guard for is_tour_sample protocols [F-0015]"
```

---

### Task 12: Expose `is_tour_sample` in Protocol API responses

**Files:**
- Modify: `backend/app/schemas/science.py` (ProtocolResponse)

- [ ] **Step 1: Locate the ProtocolResponse schema**

```bash
grep -n "class ProtocolResponse" backend/app/schemas/science.py
```

- [ ] **Step 2: Add the field**

Add `is_tour_sample: bool = False` to the `ProtocolResponse` class body. Match the style of the other boolean / flag fields in that schema.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/science.py
git commit -m "feat(backend): expose is_tour_sample in ProtocolResponse [F-0015]"
```

---

## Phase 2 — Frontend foundation

### Task 13: Install driver.js

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Install**

```bash
cd frontend && npm install driver.js@^1.3.1
```

- [ ] **Step 2: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add driver.js [F-0015]"
```

---

### Task 14: Write failing tests for tour state store

**Files:**
- Create: `frontend/src/lib/onboarding/tourStore.test.ts`

- [ ] **Step 1: Write tests**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as api from '$lib/api';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        patch: vi.fn(),
    },
}));

import {
    hydrateTourState,
    isCompleted,
    isDismissed,
    shouldShowDot,
    markCompleted,
    markDismissed,
    resetTourState,
} from './tourStore.svelte';

beforeEach(() => {
    resetTourState();
    vi.clearAllMocks();
});

describe('tourStore', () => {
    it('hydrates from /onboarding/state', async () => {
        (api.api.get as any).mockResolvedValue({
            completed: ['project'],
            dismissed: ['run'],
        });
        await hydrateTourState();

        expect(isCompleted('project')).toBe(true);
        expect(isDismissed('run')).toBe(true);
        expect(isDismissed('project')).toBe(false);
    });

    it('shouldShowDot is true only when neither completed nor dismissed', async () => {
        (api.api.get as any).mockResolvedValue({
            completed: ['project'],
            dismissed: ['run'],
        });
        await hydrateTourState();

        expect(shouldShowDot('project')).toBe(false);
        expect(shouldShowDot('run')).toBe(false);
        expect(shouldShowDot('protocol')).toBe(true);
    });

    it('markCompleted sends PATCH and updates local state', async () => {
        (api.api.patch as any).mockResolvedValue({
            completed: ['protocol'],
            dismissed: [],
        });
        await markCompleted('protocol');

        expect(api.api.patch).toHaveBeenCalledWith(
            '/onboarding/state',
            { segment: 'protocol', status: 'completed' },
        );
        expect(isCompleted('protocol')).toBe(true);
    });

    it('markDismissed sends PATCH and updates local state', async () => {
        (api.api.patch as any).mockResolvedValue({
            completed: [],
            dismissed: ['project'],
        });
        await markDismissed('project');

        expect(isDismissed('project')).toBe(true);
    });
});
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && CI=true npm run test -- tourStore
```

Expected: FAIL — module does not exist.

---

### Task 15: Implement tour state store

**Files:**
- Create: `frontend/src/lib/onboarding/tourStore.svelte.ts`

- [ ] **Step 1: Write the store**

```typescript
import { api } from '$lib/api';

export type TourSegment = 'project' | 'protocol' | 'run';
export type TourStatus = 'completed' | 'dismissed';

interface TourStateData {
    completed: TourSegment[];
    dismissed: TourSegment[];
}

let state = $state<TourStateData>({ completed: [], dismissed: [] });
let hydrated = $state(false);

export function resetTourState(): void {
    state = { completed: [], dismissed: [] };
    hydrated = false;
}

export async function hydrateTourState(): Promise<void> {
    const res = await api.get<TourStateData>('/onboarding/state');
    state = {
        completed: res.completed || [],
        dismissed: res.dismissed || [],
    };
    hydrated = true;
}

export function isHydrated(): boolean {
    return hydrated;
}

export function isCompleted(segment: TourSegment): boolean {
    return state.completed.includes(segment);
}

export function isDismissed(segment: TourSegment): boolean {
    return state.dismissed.includes(segment);
}

export function shouldShowDot(segment: TourSegment): boolean {
    return hydrated && !isCompleted(segment) && !isDismissed(segment);
}

export function isWelcomeEmpty(): boolean {
    return (
        hydrated &&
        state.completed.length === 0 &&
        state.dismissed.length === 0
    );
}

async function patchState(segment: TourSegment, status: TourStatus): Promise<void> {
    const res = await api.patch<TourStateData>('/onboarding/state', {
        segment,
        status,
    });
    state = {
        completed: res.completed || [],
        dismissed: res.dismissed || [],
    };
}

export async function markCompleted(segment: TourSegment): Promise<void> {
    await patchState(segment, 'completed');
}

export async function markDismissed(segment: TourSegment): Promise<void> {
    await patchState(segment, 'dismissed');
}

export async function markAllDismissed(): Promise<void> {
    await markDismissed('project');
    await markDismissed('protocol');
    await markDismissed('run');
}
```

- [ ] **Step 2: Verify `api.patch` exists**

```bash
grep -n "patch" frontend/src/lib/api.ts
```

If `api.patch` isn't exported, add it. The pattern mirrors `api.get`/`api.post`. Minimal addition to `frontend/src/lib/api.ts`:

```typescript
patch<T>(endpoint: string, body?: unknown, options?: RequestOptions<T>): Promise<T> {
    return request<T>('PATCH', endpoint, body, options);
},
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && CI=true npm run test -- tourStore
```

Expected: all 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/onboarding/ frontend/src/lib/api.ts
git commit -m "feat(frontend): tour state store (hydrate + mark) [F-0015]"
```

---

### Task 16: Build reusable `TourModal` component

**Files:**
- Create: `frontend/src/lib/onboarding/TourModal.svelte`
- Create: `frontend/src/lib/onboarding/TourModal.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi } from 'vitest';
import TourModal from './TourModal.svelte';

describe('TourModal', () => {
    it('renders title and both labels', () => {
        render(TourModal, {
            open: true,
            title: 'Welcome',
            primaryLabel: 'Take tour',
            secondaryLabel: 'Dismiss',
            onPrimary: () => {},
            onSecondary: () => {},
        });

        expect(screen.getByText('Welcome')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Take tour' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
    });

    it('fires onPrimary when primary button clicked', async () => {
        const onPrimary = vi.fn();
        render(TourModal, {
            open: true,
            title: 'T',
            primaryLabel: 'Go',
            secondaryLabel: 'No',
            onPrimary,
            onSecondary: () => {},
        });
        await fireEvent.click(screen.getByRole('button', { name: 'Go' }));
        expect(onPrimary).toHaveBeenCalledOnce();
    });

    it('fires onSecondary when secondary button clicked', async () => {
        const onSecondary = vi.fn();
        render(TourModal, {
            open: true,
            title: 'T',
            primaryLabel: 'Go',
            secondaryLabel: 'No',
            onPrimary: () => {},
            onSecondary,
        });
        await fireEvent.click(screen.getByRole('button', { name: 'No' }));
        expect(onSecondary).toHaveBeenCalledOnce();
    });
});
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && CI=true npm run test -- TourModal
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the modal**

```svelte
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        open: boolean;
        title: string;
        description?: string;
        primaryLabel: string;
        secondaryLabel: string;
        onPrimary: () => void;
        onSecondary: () => void;
    }

    let {
        open = $bindable(),
        title,
        description,
        primaryLabel,
        secondaryLabel,
        onPrimary,
        onSecondary,
    }: Props = $props();
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>{title}</Dialog.Title>
            {#if description}
                <Dialog.Description>{description}</Dialog.Description>
            {/if}
        </Dialog.Header>
        <div class="flex justify-end gap-2 mt-4">
            <Button variant="ghost" onclick={onSecondary}>
                {secondaryLabel}
            </Button>
            <Button onclick={onPrimary}>
                {primaryLabel}
            </Button>
        </div>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && CI=true npm run test -- TourModal
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/onboarding/TourModal.svelte frontend/src/lib/onboarding/TourModal.test.ts
git commit -m "feat(frontend): reusable TourModal component [F-0015]"
```

---

### Task 17: Build `HintDot` component

**Files:**
- Create: `frontend/src/lib/onboarding/HintDot.svelte`
- Create: `frontend/src/lib/onboarding/HintDot.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { render, screen, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi } from 'vitest';
import HintDot from './HintDot.svelte';

describe('HintDot', () => {
    it('renders when visible is true', () => {
        render(HintDot, { visible: true, ariaLabel: 'take tour', onClick: () => {} });
        expect(screen.getByLabelText('take tour')).toBeInTheDocument();
    });

    it('renders nothing when visible is false', () => {
        render(HintDot, { visible: false, ariaLabel: 'take tour', onClick: () => {} });
        expect(screen.queryByLabelText('take tour')).toBeNull();
    });

    it('fires onClick when clicked', async () => {
        const onClick = vi.fn();
        render(HintDot, { visible: true, ariaLabel: 'take tour', onClick });
        await fireEvent.click(screen.getByLabelText('take tour'));
        expect(onClick).toHaveBeenCalledOnce();
    });
});
```

- [ ] **Step 2: Implement**

```svelte
<script lang="ts">
    interface Props {
        visible: boolean;
        ariaLabel: string;
        onClick: () => void;
        class?: string;
    }

    let { visible, ariaLabel, onClick, class: className }: Props = $props();
</script>

{#if visible}
    <button
        type="button"
        aria-label={ariaLabel}
        onclick={onClick}
        class={`absolute z-20 inline-flex h-3 w-3 cursor-pointer ${className ?? '-top-1 -right-1'}`}
    >
        <span
            class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-500 opacity-75"
        ></span>
        <span
            class="relative inline-flex h-3 w-3 rounded-full bg-blue-500"
        ></span>
    </button>
{/if}
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && CI=true npm run test -- HintDot
```

Expected: all 3 pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/onboarding/HintDot.svelte frontend/src/lib/onboarding/HintDot.test.ts
git commit -m "feat(frontend): HintDot pulsing hint component [F-0015]"
```

---

### Task 18: Build `HelpMenu` component

**Files:**
- Create: `frontend/src/lib/onboarding/HelpMenu.svelte`

- [ ] **Step 1: Implement**

```svelte
<script lang="ts">
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { HelpCircle } from 'lucide-svelte';
    import HintDot from './HintDot.svelte';

    interface Props {
        dotVisible: boolean;
        onTakeTour: () => void;
    }

    let { dotVisible, onTakeTour }: Props = $props();
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger
        class="relative inline-flex h-8 w-8 items-center justify-center rounded-full border border-input bg-background text-muted-foreground transition-colors hover:bg-muted"
        aria-label="Help and tours"
    >
        <HelpCircle class="h-4 w-4" />
        <HintDot visible={dotVisible} ariaLabel="tour available" onClick={onTakeTour} />
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
        <DropdownMenu.Item onclick={onTakeTour}>Take tour</DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/onboarding/HelpMenu.svelte
git commit -m "feat(frontend): HelpMenu dropdown with tour trigger [F-0015]"
```

---

### Task 19: Write the three driver.js tour configs

**Files:**
- Create: `frontend/src/lib/onboarding/tours/projectTour.ts`
- Create: `frontend/src/lib/onboarding/tours/protocolTour.ts`
- Create: `frontend/src/lib/onboarding/tours/runTour.ts`

- [ ] **Step 1: Write `projectTour.ts`**

```typescript
import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

export function runProjectTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="project-tab-protocols"]',
                popover: {
                    title: 'Protocols',
                    description: 'Protocols are the recipes your team runs.',
                },
            },
            {
                element: '[data-tour="project-tab-experiments"]',
                popover: {
                    title: 'Experiments',
                    description: 'Experiments group related runs and snapshot a protocol at a point in time.',
                },
            },
            {
                element: '[data-tour="project-tab-runs"]',
                popover: {
                    title: 'Runs',
                    description: 'Runs are active or completed executions.',
                },
            },
            {
                element: '[data-tour="project-tab-activity"]',
                popover: {
                    title: 'Activity',
                    description: 'See a feed of everything happening in this project.',
                },
            },
            {
                element: '[data-tour="project-tab-settings"]',
                popover: {
                    title: 'Settings',
                    description: 'Manage project members and templates here.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.getActiveIndex() === d.getSteps().length - 1;
            if (completed) {
                await markCompleted('project');
            } else {
                await markDismissed('project');
            }
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
```

- [ ] **Step 2: Write `protocolTour.ts`**

```typescript
import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

export function runProtocolTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="protocol-sidebar"]',
                popover: {
                    title: 'Unit Ops',
                    description: 'Drag unit operations from here onto the canvas.',
                },
            },
            {
                element: '[data-tour="protocol-canvas"]',
                popover: {
                    title: 'Canvas',
                    description: 'Connect steps with edges to define the workflow.',
                },
            },
            {
                element: '[data-tour="protocol-save"]',
                popover: {
                    title: 'Save',
                    description: 'Save your changes — changes aren\'t persisted until you click here.',
                },
            },
            {
                element: '[data-tour="protocol-inspector"]',
                popover: {
                    title: 'Inspector',
                    description: 'Click a node and edit its parameters in this panel.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.getActiveIndex() === d.getSteps().length - 1;
            if (completed) {
                await markCompleted('protocol');
            } else {
                await markDismissed('protocol');
            }
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
```

- [ ] **Step 3: Write `runTour.ts`**

```typescript
import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { api } from '$lib/api';
import { markCompleted, markDismissed } from '../tourStore.svelte';

async function cleanupSampleRun(): Promise<void> {
    try {
        await api.post('/onboarding/tour/run/end', {});
    } catch {
        // Idempotent on the server; swallow errors.
    }
}

export function runRunTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="run-role-panel"]',
                popover: {
                    title: 'Roles',
                    description: 'Assign team members to the roles this protocol needs.',
                },
            },
            {
                element: '[data-tour="run-step-list"]',
                popover: {
                    title: 'Steps',
                    description: 'Work through the steps in order.',
                },
            },
            {
                element: '[data-tour="run-step-complete"]',
                popover: {
                    title: 'Complete a step',
                    description: 'Check each step off as you go.',
                },
            },
            {
                element: '[data-tour="run-results"]',
                popover: {
                    title: 'Results',
                    description: 'See run status and results summary here.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.getActiveIndex() === d.getSteps().length - 1;
            if (completed) {
                await markCompleted('run');
            } else {
                await markDismissed('run');
            }
            await cleanupSampleRun();
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/onboarding/tours/
git commit -m "feat(frontend): driver.js tour configs for project/protocol/run [F-0015]"
```

---

### Task 20: Add `index.ts` barrel export

**Files:**
- Create: `frontend/src/lib/onboarding/index.ts`

- [ ] **Step 1: Write**

```typescript
export { default as TourModal } from './TourModal.svelte';
export { default as HintDot } from './HintDot.svelte';
export { default as HelpMenu } from './HelpMenu.svelte';
export * from './tourStore.svelte';
export { runProjectTour } from './tours/projectTour';
export { runProtocolTour } from './tours/protocolTour';
export { runRunTour } from './tours/runTour';
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/onboarding/index.ts
git commit -m "feat(frontend): onboarding module barrel export [F-0015]"
```

---

## Phase 3 — Page integrations

### Task 21: Hydrate tour state on login

**Files:**
- Modify: `frontend/src/lib/auth.svelte.ts`

- [ ] **Step 1: Find where `user` is loaded after login**

```bash
grep -n "auth_token\|setUser\|/auth/me" frontend/src/lib/auth.svelte.ts
```

- [ ] **Step 2: Call `hydrateTourState` after user load**

Import `hydrateTourState` at the top of `frontend/src/lib/auth.svelte.ts`:

```typescript
import { hydrateTourState } from './onboarding/tourStore.svelte';
```

After the user is successfully loaded in the login / current-user functions, call:

```typescript
    try {
        await hydrateTourState();
    } catch {
        // non-fatal; tour state can remain un-hydrated
    }
```

Add the same call inside whatever function runs on page hydrate for an already-authenticated user (e.g., `ensureAuthLoaded`, `restoreSession`, or equivalent).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/auth.svelte.ts
git commit -m "feat(frontend): hydrate tour state on login [F-0015]"
```

---

### Task 22: Mount welcome modal on dashboard

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

- [ ] **Step 1: Add state and imports**

At the top of the `<script>` block, import:

```typescript
import { goto } from '$app/navigation';
import TourModal from '$lib/onboarding/TourModal.svelte';
import { isWelcomeEmpty, isHydrated, markAllDismissed } from '$lib/onboarding/tourStore.svelte';
import { api } from '$lib/api';

let welcomeOpen = $state(false);

$effect(() => {
    if (isHydrated() && isWelcomeEmpty()) {
        welcomeOpen = true;
    }
});

async function startProjectTourFromWelcome() {
    welcomeOpen = false;
    const { project_id } = await api.post<{ project_id: string }>(
        '/onboarding/tour/project/start', {},
    );
    goto(`/projects/${project_id}?tour=project`);
}

async function dismissWelcome() {
    welcomeOpen = false;
    await markAllDismissed();
}
```

- [ ] **Step 2: Mount the modal near the end of the template**

Just before the closing tag of the main wrapper (or near the end of the dashboard markup), add:

```svelte
<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>
```

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run check
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat(frontend): welcome modal on dashboard first login [F-0015]"
```

---

### Task 23: Add `data-tour` hooks and tour integration to project detail page

**Files:**
- Modify: `frontend/src/routes/projects/[id]/+page.svelte`

- [ ] **Step 1: Add `data-tour` attributes to the five tab buttons**

In the `{#each validTabs as tab}` loop (around line 387), change the Button to include `data-tour` keyed by tab name:

```svelte
<Button
    variant="tab"
    data-active={activeTab === tab}
    data-tour={`project-tab-${tab}`}
    onclick={() => setTab(tab)}
    class="px-5 py-3 -mb-px"
>
```

- [ ] **Step 2: Add imports + state + auto-start logic in the `<script>` block**

```typescript
import { page as pageStore } from '$app/stores';
import { HelpMenu, TourModal, runProjectTour, shouldShowDot, markDismissed } from '$lib/onboarding';
import { api } from '$lib/api';

let projectTourModalOpen = $state(false);

function openProjectTourModal() {
    projectTourModalOpen = true;
}

function startProjectTour() {
    projectTourModalOpen = false;
    runProjectTour(() => {});
}

async function dismissProjectTour() {
    projectTourModalOpen = false;
    await markDismissed('project');
}

$effect(() => {
    // Auto-start tour if arriving from welcome modal with ?tour=project
    const tour = $pageStore.url.searchParams.get('tour');
    if (tour === 'project' && activeTab === 'protocols') {
        // Defer to let DOM settle
        setTimeout(() => runProjectTour(() => {}), 200);
    }
});
```

- [ ] **Step 3: Mount `HelpMenu` and `TourModal` in the header action area**

In the header action buttons block (around line 346-383), insert after the tab-specific buttons:

```svelte
<HelpMenu dotVisible={shouldShowDot('project')} onTakeTour={openProjectTourModal} />
```

At the end of the file (outside any conditional blocks), mount:

```svelte
<TourModal
    bind:open={projectTourModalOpen}
    title="Tour: how projects are laid out"
    description="A quick 5-step walkthrough of the project tabs."
    primaryLabel="Take tour"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTour}
    onSecondary={dismissProjectTour}
/>
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run check
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/projects/[id]/+page.svelte
git commit -m "feat(frontend): project tour integration + data-tour hooks [F-0015]"
```

---

### Task 24: Add `data-tour` hooks and tour integration to protocol editor

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte`

- [ ] **Step 1: Add `data-tour` attributes to the editor chrome**

Find `<ProtocolSidebar ...>` (around line 22) — wrap it in a `<div data-tour="protocol-sidebar">` OR pass through `data-tour` as an attribute. Easier approach: wrap:

```svelte
<div data-tour="protocol-sidebar" class="contents">
    <ProtocolSidebar ... />
</div>
```

Repeat for:
- Canvas area: wrap the `<SvelteFlow ...>` in `<div data-tour="protocol-canvas">`.
- Toolbar Save button: pass `data-tour="protocol-save"` to the Save button inside `CanvasToolbar.svelte` if possible, otherwise wrap the `<CanvasToolbar>` component.
- Inspector: wrap the `<Inspector>` (line 59) in `<div data-tour="protocol-inspector">`.

**Note:** check whether wrapping breaks existing Tailwind layouts (`contents` class is usually safe). If so, use `display:contents` inline style or pass the attribute through the child component.

- [ ] **Step 2: Add tour state + imports**

```typescript
import { HelpMenu, TourModal, runProtocolTour, shouldShowDot, markDismissed } from '$lib/onboarding';

let protocolTourModalOpen = $state(false);

function openProtocolTourModal() { protocolTourModalOpen = true; }

function startProtocolTour() {
    protocolTourModalOpen = false;
    runProtocolTour(() => {});
}

async function dismissProtocolTour() {
    protocolTourModalOpen = false;
    await markDismissed('protocol');
}
```

- [ ] **Step 3: Mount HelpMenu and TourModal**

Find the toolbar area (where `<CanvasToolbar>` is rendered) and add the HelpMenu in an appropriate corner. Also mount the TourModal at the bottom of the template:

```svelte
<HelpMenu dotVisible={shouldShowDot('protocol')} onTakeTour={openProtocolTourModal} />
```

```svelte
<TourModal
    bind:open={protocolTourModalOpen}
    title="Tour: how to construct a protocol"
    description="A 4-step walkthrough of the protocol editor."
    primaryLabel="Take tour"
    secondaryLabel="Dismiss"
    onPrimary={startProtocolTour}
    onSecondary={dismissProtocolTour}
/>
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run check
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/protocols/[id]/+page.svelte frontend/src/lib/components/protocol/
git commit -m "feat(frontend): protocol tour integration + data-tour hooks [F-0015]"
```

---

### Task 25: Add `data-tour` hooks and tour integration to runner page

**Files:**
- Modify: `frontend/src/routes/runs/[id]/+page.svelte`

- [ ] **Step 1: Add `data-tour` attributes**

Identify and annotate the role panel, step list, a step "complete" button, and results area with:

- `data-tour="run-role-panel"` on the role assignment panel container
- `data-tour="run-step-list"` on the execution step list container
- `data-tour="run-step-complete"` on a step complete/action button
- `data-tour="run-results"` on the results summary panel

Wrap in a `<div>` if child components don't support attribute pass-through.

- [ ] **Step 2: Add tour state + imports**

```typescript
import { HelpMenu, TourModal, runRunTour, shouldShowDot, markDismissed } from '$lib/onboarding';

let runTourModalOpen = $state(false);

function openRunTourModal() { runTourModalOpen = true; }

function startRunTour() {
    runTourModalOpen = false;
    runRunTour(() => {});
}

async function dismissRunTour() {
    runTourModalOpen = false;
    await markDismissed('run');
}
```

- [ ] **Step 3: Mount HelpMenu and TourModal**

```svelte
<HelpMenu dotVisible={shouldShowDot('run')} onTakeTour={openRunTourModal} />
```

```svelte
<TourModal
    bind:open={runTourModalOpen}
    title="Tour: how to run a protocol"
    description="A 4-step walkthrough of the runner."
    primaryLabel="Take tour"
    secondaryLabel="Dismiss"
    onPrimary={startRunTour}
    onSecondary={dismissRunTour}
/>
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run check
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/runs/[id]/+page.svelte
git commit -m "feat(frontend): run tour integration + data-tour hooks [F-0015]"
```

---

## Phase 4 — Empty state CTAs and polish

### Task 26: Extend `EmptyState` component with secondary action

**Files:**
- Modify: `frontend/src/lib/components/ui/empty-state/empty-state.svelte`

- [ ] **Step 1: Add new props**

```svelte
<script lang="ts">
    import type { Snippet } from "svelte";
    import { fade } from "svelte/transition";
    import { cn } from "$lib/utils";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        icon?: Snippet;
        title: string;
        description?: string;
        actionLabel?: string;
        onAction?: () => void;
        secondaryActionLabel?: string;
        secondaryOnAction?: () => void;
        class?: string;
    }

    let {
        icon,
        title,
        description,
        actionLabel,
        onAction,
        secondaryActionLabel,
        secondaryOnAction,
        class: className,
    }: Props = $props();
</script>
```

- [ ] **Step 2: Render secondary button below primary**

Replace the closing of the template (where the primary button is rendered) with:

```svelte
    {#if actionLabel}
        <Button
            variant="outline"
            size="sm"
            class="mt-4"
            onclick={onAction}
        >
            {actionLabel}
        </Button>
    {/if}
    {#if secondaryActionLabel}
        <Button
            variant="ghost"
            size="sm"
            class="mt-2 text-muted-foreground"
            onclick={secondaryOnAction}
        >
            {secondaryActionLabel}
        </Button>
    {/if}
</div>
```

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run check
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/ui/empty-state/empty-state.svelte
git commit -m "feat(frontend): EmptyState gains secondary action prop [F-0015]"
```

---

### Task 27: Wire "Take the tour" secondary CTA on dashboard empty state

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

- [ ] **Step 1: Update the EmptyState usage around line 487**

Locate the `<EmptyState title="No runs yet" ...>` usage and add:

```svelte
<EmptyState
    title="No runs yet"
    description="Create a protocol and start a run."
    actionLabel="View Projects"
    onAction={() => goto('/projects')}
    secondaryActionLabel="Take the tour"
    secondaryOnAction={() => (welcomeOpen = true)}
/>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat(frontend): dashboard empty state links to tour [F-0015]"
```

---

### Task 28: Wire "Take the tour" on projects list empty state

**Files:**
- Modify: `frontend/src/routes/projects/+page.svelte`

- [ ] **Step 1: Add imports + welcome-modal state**

```typescript
import TourModal from '$lib/onboarding/TourModal.svelte';
import { markAllDismissed } from '$lib/onboarding/tourStore.svelte';
import { api } from '$lib/api';
import { goto } from '$app/navigation';

let welcomeOpen = $state(false);

async function startProjectTourFromWelcome() {
    welcomeOpen = false;
    const { project_id } = await api.post<{ project_id: string }>(
        '/onboarding/tour/project/start', {},
    );
    goto(`/projects/${project_id}?tour=project`);
}

async function dismissWelcome() {
    welcomeOpen = false;
    await markAllDismissed();
}
```

- [ ] **Step 2: Update empty state + mount modal**

Replace the existing empty state block (around line 72) with:

```svelte
{#if projects.length === 0}
    <EmptyState
        title="No projects found"
        description="Create one to get started."
        secondaryActionLabel="Take the tour"
        secondaryOnAction={() => (welcomeOpen = true)}
    />
{:else}
    <!-- existing table -->
{/if}
```

And at the bottom of the template:

```svelte
<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/projects/+page.svelte
git commit -m "feat(frontend): projects list empty state links to tour [F-0015]"
```

---

### Task 29: Wire "Take the tour" on protocols-tab empty state inside project detail

**Files:**
- Modify: `frontend/src/lib/components/project/ProtocolsTab.svelte` (or inline if the tab is implemented inline)

- [ ] **Step 1: Locate the protocols-tab empty state**

```bash
grep -rn "No protocols\|protocols.length === 0" frontend/src/
```

- [ ] **Step 2: Extend the EmptyState call with `secondaryActionLabel` + `secondaryOnAction`**

The action should open the welcome modal in the parent (pass a callback prop to `ProtocolsTab.svelte` from `projects/[id]/+page.svelte`, and open `welcomeOpen` state there — reuse the state added in Task 23 or add a new one).

Example call in `ProtocolsTab.svelte`:

```svelte
<EmptyState
    title="No protocols yet"
    description="Create your first protocol to define a workflow."
    actionLabel="New Protocol"
    onAction={onCreateProtocol}
    secondaryActionLabel="Take the tour"
    secondaryOnAction={onOpenTour}
/>
```

With `onOpenTour: () => void` added to `ProtocolsTab` `Props` and passed from the parent:

```svelte
<ProtocolsTab ... onOpenTour={() => (projectTourModalOpen = true)} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/project/ProtocolsTab.svelte frontend/src/routes/projects/[id]/+page.svelte
git commit -m "feat(frontend): protocols-tab empty state links to tour [F-0015]"
```

---

### Task 30: Render "Sample" badge on tour-sample protocols

**Files:**
- Modify: `frontend/src/lib/components/project/ProtocolsTab.svelte` (or wherever the protocol list is rendered)

- [ ] **Step 1: Locate protocol list rendering**

```bash
grep -rn "is_tour_sample\|protocols\b.*map\|#each protocols" frontend/src/
```

- [ ] **Step 2: Add the badge**

Wherever each protocol row is rendered, add adjacent to the name:

```svelte
{#if protocol.is_tour_sample}
    <span class="ml-2 inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
        Sample
    </span>
{/if}
```

Also update the Protocol TypeScript interface in `frontend/src/lib/schemas/` (find via grep for `ProtocolSchema`) to include `is_tour_sample: boolean`.

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run check
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/project/ProtocolsTab.svelte frontend/src/lib/schemas/
git commit -m "feat(frontend): Sample badge on tour-sample protocols [F-0015]"
```

---

## Phase 5 — E2E tests and final polish

### Task 31: Playwright — happy path for each tour segment

**Files:**
- Create: `frontend/tests/e2e/onboarding.spec.ts`

- [ ] **Step 1: Write the E2E test**

```typescript
import { test, expect } from '@playwright/test';

test.describe('Onboarding tour', () => {
    test.beforeEach(async ({ page }) => {
        // Login via test credentials (reuse existing Playwright helper / fixture)
        await page.goto('/login');
        await page.fill('input[name="email"]', process.env.E2E_USER_EMAIL ?? 'qa@example.com');
        await page.fill('input[name="password"]', process.env.E2E_USER_PASSWORD ?? 'password');
        await page.click('button[type="submit"]');
        await page.waitForURL('/');
    });

    test('welcome modal shows on first visit for fresh user', async ({ page }) => {
        // Assumes a fresh user from fixtures. If tour_state is already populated,
        // skip this test or use a dedicated test-only user.
        await expect(page.getByText('Welcome to Batchrite')).toBeVisible({ timeout: 5000 });
    });

    test('dismissing welcome marks all segments dismissed', async ({ page }) => {
        const welcomeVisible = await page.getByText('Welcome to Batchrite').isVisible();
        if (!welcomeVisible) test.skip();

        await page.click('button:has-text("Dismiss")');
        await expect(page.getByText('Welcome to Batchrite')).not.toBeVisible();

        // Navigate to a project and confirm no pulsing dot on help menu
        await page.goto('/projects');
        await page.click('[data-tour="project-row"], tbody tr >> nth=0');
        await expect(page.locator('[aria-label="tour available"]')).toHaveCount(0);
    });

    test('project tour runs 5 steps and marks project as completed', async ({ page }) => {
        await page.click('button:has-text("Check out how projects are laid out")');
        await page.waitForURL(/\/projects\//);

        // Tour popover should appear
        await expect(page.locator('.driver-popover')).toBeVisible();

        // Click "Next" through all 5 steps
        for (let i = 0; i < 4; i++) {
            await page.click('.driver-popover-next-btn');
        }
        await page.click('.driver-popover-done-btn, .driver-popover-close-btn');

        // Confirm dot is gone (segment completed) by reloading
        await page.reload();
        await expect(page.locator('[aria-label="tour available"]')).toHaveCount(0);
    });
});
```

- [ ] **Step 2: Run Playwright**

```bash
cd frontend && npm run test:e2e -- onboarding
```

Note: requires backend + frontend dev servers on the Playwright-configured ports (`:5176` frontend). Start them before running, per `playwright.config.ts`.

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/onboarding.spec.ts
git commit -m "test(frontend): E2E happy paths for onboarding tour [F-0015]"
```

---

### Task 32: Run the full test suite

- [ ] **Step 1: Backend**

```bash
cd backend && source .venv/bin/activate
pytest
```

Expected: all tests pass including the ones added in tasks 5, 7, 9, 10.

- [ ] **Step 2: Frontend unit**

```bash
cd frontend && CI=true npm run test
```

Expected: all tests pass.

- [ ] **Step 3: Frontend type-check**

```bash
cd frontend && npm run check
```

Expected: no errors.

- [ ] **Step 4: Frontend build**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit any fixups**

If anything needed tweaks, commit them with:

```bash
git add -A
git commit -m "fix: post-test-suite fixups [F-0015]"
```

---

### Task 33: Lint and format

- [ ] **Step 1: Backend**

```bash
cd backend && source .venv/bin/activate
black app tests && isort app tests && mypy app
```

Expected: no errors.

- [ ] **Step 2: Commit if formatting changed anything**

```bash
git add -A
git commit -m "style: black/isort post F-0015 [F-0015]"
```

---

## Acceptance Criteria Verification

- [ ] Driver.js-based multi-page guided tour — Tasks 18, 22, 23, 24.
- [ ] Context-specific tours (editor, runner) — Tasks 23, 24.
- [ ] Pulsing hint dots — Tasks 16, 17; mounted on each page in Tasks 22–24.
- [ ] Sample protocol for new orgs — Task 9 seeds project; Task 6 provides find-or-create sample protocol.
- [ ] Empty state CTAs — Tasks 25–28.

---

## Notes for the Implementer

- **Spotlight selectors:** drive.js targets DOM elements via CSS selectors. Keep the `data-tour="…"` values stable — rename/refactor requires updating both the template and the tour config.
- **Auth fixture:** the integration tests assume an `auth_client` fixture exists. If it doesn't, look for the pattern in `backend/tests/integration/conftest.py` and wire a new one up before Task 7.
- **Sample run cleanup:** if the sample run's delete accidentally cascades to running runs, double-check the service tests in Task 5 catch it (we delete only `is_tour_sample=True`).
- **Protocol tour ordering:** the protocol tour assumes an active session on the sample protocol page. Navigating there is the responsibility of the welcome/gate modal logic, not the tour config.
