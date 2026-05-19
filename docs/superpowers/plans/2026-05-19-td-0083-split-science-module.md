# Split the backend "science" module — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the `science` umbrella (models, schemas, services, `/science/` API prefix) into six domain modules with no behavior change.

**Architecture:** Mechanical refactor in eight stages. Stages 1–3 create domain modules while leaving a transitional re-export shim so the suite stays green; stage 4 codemods all 189+ backend import sites (`app/` **and** `tests/`) off the umbrella; stage 5 deletes the now-unused umbrella files; stage 6 drops the `/science/` API prefix; stage 7 updates frontend URLs; stage 8 splits the legacy `test_science_api.py` grab-bag into per-domain integration files. The existing test suite is the correctness backstop — no behavior assertions change.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic, Alembic (backend); Svelte 5 + Vite (frontend); `pytest`, `mypy`, `black`, `isort`, `svelte-check`.

---

## Reference: symbol → module mapping

**Models** (`models/science.py` → 6 new files):

| Module | Classes |
| --- | --- |
| `models/protocols.py` | `Protocol`, `ProtocolRole`, `ProtocolVersion`, `UnitOpDefinition`, `UnitOpLibrarySubscription` |
| `models/runs.py` | `Run`, `RunStatus`, `RunRoleAssignment`, `RunOutcome`, `Experiment`, `ExperimentStatus` |
| `models/projects.py` | `Project` |
| `models/equipment.py` | `Equipment`, `EquipmentAttachment`, `EquipmentStatus` |
| `models/sites.py` | `Site`, `SiteManagerGrant` |
| `models/signoffs.py` | `GlpSignoff`, `GlpSignoffRequest`, `GlpRole`, `GlpSignoffAction`, `GlpSignoffRequestStatus` |

**Schemas** (`schemas/science.py` → 3 new files; `schemas/equipment.py`, `sites.py`, `project.py` already exist):

| Module | Classes |
| --- | --- |
| `schemas/protocols.py` | `UnitOpDefinitionBase/Create/Update/Response`, `ProtocolRoleBase/Create/Update/Response`, `ProtocolBase/Create/Update/Response`, `ProtocolVersionListItem`, `ProtocolVersionResponse`, `PublishDraftRequest`, `DesignateApprovalRequest`, `SubmitForApprovalRequest`, `ApproveProtocolRequest`, `RejectProtocolRequest`, `ApprovalActorRef`, `AwaitingApprovalItem`, `GraphPayload`, `StepProposalSchema`, `ProtocolImportProposalResponse`, `ProtocolRefineRequest`, `ProtocolImportFinalizeRequest` |
| `schemas/runs.py` | `ExperimentStatus`, `ExperimentNote/Create/ListResponse`, `ExperimentCreate`, `ExperimentUpdate`, `ExperimentResponse`, `RunStatus`, `RunNote/Create/ListResponse`, `RunAttachment`, `RunAttachmentListResponse`, `RunBase/Create/Update`, `RunStateUpdate`, `RunStepStateUpdate`, `RunResponse`, `NodeOverrides`, `RunOverrides`, `SuggestLotNumberRequest/Response`, `CheckLotNumberResponse`, `RunRoleAssignmentBase/Create/Response/ListResponse`, `RunCompleteRequest`, `RunReopenRequest` |
| `schemas/signoffs.py` | `GlpSignoffCreate`, `GlpSignoffResponse` |
| **deleted (dead)** | `EquipmentBase`, `EquipmentCreate`, `EquipmentUpdate`, `EquipmentResponse` — zero importers; do **not** move |

---

## Task 1: Split `models/science.py` into 6 domain modules

**Files:**
- Create: `backend/app/models/protocols.py`, `runs.py`, `projects.py`, `equipment.py`, `sites.py`, `signoffs.py`
- Modify: `backend/app/models/science.py` (becomes a shim)

- [ ] **Step 1: Create the 6 domain modules**

For each module, create the file with a one-line docstring, the import block it needs, then **cut the listed class definitions verbatim** from `models/science.py` (locate each with `grep -n "^class <Name>" backend/app/models/science.py`). Move classes in the order shown in the mapping table so enums precede the models that reference them.

Each module starts from this import block (copied verbatim from `models/science.py` lines 17–43); drop lines a given module does not use (e.g. a module with no enum drops `from enum import Enum`):

```python
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import (
    ARRAY, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, desc, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.mixins import TimestampMixin, UUIDMixin
```

Do **not** delete the moved classes from `science.py` yet — Step 2 replaces the whole file.

- [ ] **Step 2: Replace `models/science.py` with a transitional shim**

Overwrite the entire file with:

```python
"""Transitional shim (TD-0083) — re-exports the split `science` models.

Deleted once all imports migrate to the domain modules. Import from
`app.models.protocols` / `.runs` / `.projects` / `.equipment` / `.sites` /
`.signoffs` instead.
"""

from app.models.equipment import Equipment, EquipmentAttachment, EquipmentStatus
from app.models.projects import Project
from app.models.protocols import (
    Protocol, ProtocolRole, ProtocolVersion, UnitOpDefinition,
    UnitOpLibrarySubscription,
)
from app.models.runs import (
    Experiment, ExperimentStatus, Run, RunOutcome, RunRoleAssignment, RunStatus,
)
from app.models.signoffs import (
    GlpRole, GlpSignoff, GlpSignoffAction, GlpSignoffRequest,
    GlpSignoffRequestStatus,
)
from app.models.sites import Site, SiteManagerGrant

__all__ = [
    "Equipment", "EquipmentAttachment", "EquipmentStatus", "Project",
    "Protocol", "ProtocolRole", "ProtocolVersion", "UnitOpDefinition",
    "UnitOpLibrarySubscription", "Experiment", "ExperimentStatus", "Run",
    "RunOutcome", "RunRoleAssignment", "RunStatus", "GlpRole", "GlpSignoff",
    "GlpSignoffAction", "GlpSignoffRequest", "GlpSignoffRequestStatus",
    "Site", "SiteManagerGrant",
]
```

- [ ] **Step 3: Resolve cross-module type annotations**

Run: `cd backend && source .venv/bin/activate && mypy app/models`
For every `Mapped["X"]` annotation that mypy reports as undefined (e.g. `Protocol` referencing `Run`), add a `TYPE_CHECKING` block to that module:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.runs import Run
```

Repeat until `mypy app/models` is clean. Runtime `relationship("Run", ...)` strings and `ForeignKey("runs.id")` strings need no change — SQLAlchemy resolves them via the shared registry.

- [ ] **Step 4: Run the full suite**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: PASS (same pass/fail counts as before the task — every site still imports via the shim).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/
git commit -m "refactor(TD-0083): split science models into domain modules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Split `schemas/science.py` into 3 domain modules

**Files:**
- Create: `backend/app/schemas/protocols.py`, `runs.py`, `signoffs.py`
- Modify: `backend/app/schemas/science.py` (becomes a shim)

- [ ] **Step 1: Create the 3 schema modules**

For each, create the file with a one-line docstring, the import block it needs, then cut the listed classes verbatim from `schemas/science.py` (mapping table above). Start from this block (from `schemas/science.py`), dropping unused names:

```python
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, computed_field, field_validator,
)
```

`GlpSignoffResponse` (→ `schemas/signoffs.py`) contains a computed field returning `f"/science/signoffs/{self.id}/signature"`. **Move it verbatim, keeping the `/science/` URL unchanged** — Task 6 fixes all hardcoded URLs together with the routing change.

- [ ] **Step 2: Delete the dead Equipment schemas**

Do not move `EquipmentBase`, `EquipmentCreate`, `EquipmentUpdate`, `EquipmentResponse` — they have zero importers (confirmed: `grep -rn "schemas.science import" backend | grep Equipment` returns nothing) and are superseded by `schemas/equipment.py`. They simply vanish when `science.py` is overwritten in Step 3.

- [ ] **Step 3: Replace `schemas/science.py` with a transitional shim**

Overwrite the entire file with:

```python
"""Transitional shim (TD-0083) — re-exports the split `science` schemas.

Deleted once all imports migrate to the domain modules. Import from
`app.schemas.protocols` / `.runs` / `.signoffs` instead.
"""

from app.schemas.protocols import (
    ApprovalActorRef, ApproveProtocolRequest, AwaitingApprovalItem,
    DesignateApprovalRequest, GraphPayload, ProtocolBase, ProtocolCreate,
    ProtocolImportFinalizeRequest, ProtocolImportProposalResponse,
    ProtocolRefineRequest, ProtocolResponse, ProtocolRoleBase,
    ProtocolRoleCreate, ProtocolRoleResponse, ProtocolRoleUpdate,
    ProtocolUpdate, ProtocolVersionListItem, ProtocolVersionResponse,
    PublishDraftRequest, RejectProtocolRequest, StepProposalSchema,
    SubmitForApprovalRequest, UnitOpDefinitionBase, UnitOpDefinitionCreate,
    UnitOpDefinitionResponse, UnitOpDefinitionUpdate,
)
from app.schemas.runs import (
    CheckLotNumberResponse, ExperimentCreate, ExperimentNote,
    ExperimentNoteCreate, ExperimentNoteListResponse, ExperimentResponse,
    ExperimentStatus, ExperimentUpdate, NodeOverrides, RunAttachment,
    RunAttachmentListResponse, RunBase, RunCompleteRequest, RunCreate,
    RunNote, RunNoteCreate, RunNoteListResponse, RunOverrides,
    RunReopenRequest, RunResponse, RunRoleAssignmentBase,
    RunRoleAssignmentCreate, RunRoleAssignmentListResponse,
    RunRoleAssignmentResponse, RunStateUpdate, RunStatus, RunStepStateUpdate,
    RunUpdate, SuggestLotNumberRequest, SuggestLotNumberResponse,
)
from app.schemas.signoffs import GlpSignoffCreate, GlpSignoffResponse
```

- [ ] **Step 4: Run the full suite**

Run: `cd backend && source .venv/bin/activate && pytest -q && mypy app`
Expected: PASS (unchanged pass/fail counts).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/
git commit -m "refactor(TD-0083): split science schemas into domain modules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Move `library_registry.py` to `services/protocols/`

**Files:**
- Move: `backend/app/services/science/library_registry.py` → `backend/app/services/protocols/library_registry.py`
- Modify: `backend/app/services/science/__init__.py` (becomes a shim)

- [ ] **Step 1: Move the module, preserving git history**

```bash
git mv backend/app/services/science/library_registry.py backend/app/services/protocols/library_registry.py
```

Then delete the 3-line `# DEPRECATED (TD-0083): ...` comment block at the top of the moved file (it referred to the old `services/science/` location).

- [ ] **Step 2: Make `services/science/__init__.py` a shim**

Overwrite `backend/app/services/science/__init__.py` with:

```python
"""Transitional shim (TD-0083) — re-exports the moved library_registry.

Deleted once all imports migrate to `app.services.protocols`.
"""

from app.services.protocols import library_registry  # noqa: F401
```

- [ ] **Step 3: Run the suite**

Run: `cd backend && source .venv/bin/activate && pytest -q tests/integration/test_library_registry.py tests/integration/test_unit_ops_scoping.py`
Expected: PASS (these exercise `library_registry` directly via the shim).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/
git commit -m "refactor(TD-0083): move library_registry to services/protocols

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Codemod every backend import off the umbrella

**Files:**
- Create: `backend/scripts/split_science_imports.py` (one-shot tool; deleted in Task 9)
- Modify: every `backend/` file importing the umbrella — `backend/app/` (~75 sites) **and** `backend/tests/` including `conftest.py`, `fixtures/`, and `benchmarks/` (~114 sites). The codemod's `rglob` walks all of `backend/`, so test code is migrated by the same pass.

- [ ] **Step 1: Write the codemod**

Create `backend/scripts/split_science_imports.py`:

```python
"""One-shot codemod (TD-0083): rewrite imports off the `science` umbrella.

Run from backend/:  python scripts/split_science_imports.py
Deleted once TD-0083 lands.
"""
from __future__ import annotations

import ast
from pathlib import Path

MODELS = {
    "Protocol": "protocols", "ProtocolRole": "protocols",
    "ProtocolVersion": "protocols", "UnitOpDefinition": "protocols",
    "UnitOpLibrarySubscription": "protocols",
    "Run": "runs", "RunStatus": "runs", "RunRoleAssignment": "runs",
    "RunOutcome": "runs", "Experiment": "runs", "ExperimentStatus": "runs",
    "Project": "projects",
    "Equipment": "equipment", "EquipmentAttachment": "equipment",
    "EquipmentStatus": "equipment",
    "Site": "sites", "SiteManagerGrant": "sites",
    "GlpSignoff": "signoffs", "GlpSignoffRequest": "signoffs",
    "GlpRole": "signoffs", "GlpSignoffAction": "signoffs",
    "GlpSignoffRequestStatus": "signoffs",
}
SCHEMAS = {
    **{n: "protocols" for n in (
        "UnitOpDefinitionBase", "UnitOpDefinitionCreate",
        "UnitOpDefinitionUpdate", "UnitOpDefinitionResponse",
        "ProtocolRoleBase", "ProtocolRoleCreate", "ProtocolRoleUpdate",
        "ProtocolRoleResponse", "ProtocolBase", "ProtocolCreate",
        "ProtocolUpdate", "ProtocolResponse", "ProtocolVersionListItem",
        "ProtocolVersionResponse", "PublishDraftRequest",
        "DesignateApprovalRequest", "SubmitForApprovalRequest",
        "ApproveProtocolRequest", "RejectProtocolRequest", "ApprovalActorRef",
        "AwaitingApprovalItem", "GraphPayload", "StepProposalSchema",
        "ProtocolImportProposalResponse", "ProtocolRefineRequest",
        "ProtocolImportFinalizeRequest",
    )},
    **{n: "runs" for n in (
        "ExperimentStatus", "ExperimentNote", "ExperimentNoteCreate",
        "ExperimentNoteListResponse", "ExperimentCreate", "ExperimentUpdate",
        "ExperimentResponse", "RunStatus", "RunNote", "RunNoteCreate",
        "RunNoteListResponse", "RunAttachment", "RunAttachmentListResponse",
        "RunBase", "RunCreate", "RunUpdate", "RunStateUpdate",
        "RunStepStateUpdate", "RunResponse", "NodeOverrides", "RunOverrides",
        "SuggestLotNumberRequest", "SuggestLotNumberResponse",
        "CheckLotNumberResponse", "RunRoleAssignmentBase",
        "RunRoleAssignmentCreate", "RunRoleAssignmentResponse",
        "RunRoleAssignmentListResponse", "RunCompleteRequest",
        "RunReopenRequest",
    )},
    **{n: "signoffs" for n in ("GlpSignoffCreate", "GlpSignoffResponse")},
}
MAPS = {
    "app.models.science": ("app.models", MODELS),
    "app.schemas.science": ("app.schemas", SCHEMAS),
}
ROOT = Path(__file__).resolve().parent.parent  # backend/


def rewrite(path: Path) -> bool:
    src = path.read_text()
    if "science" not in src:
        return False
    lines = src.splitlines(keepends=True)
    edits = []  # (start_idx, end_idx, replacement)
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        indent = " " * node.col_offset
        if node.module.startswith("app.services.science"):
            new_mod = node.module.replace(
                "app.services.science", "app.services.protocols", 1)
            names = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "")
                for a in node.names)
            edits.append((node.lineno - 1, node.end_lineno,
                           f"{indent}from {new_mod} import {names}\n"))
        elif node.module in MAPS:
            base, table = MAPS[node.module]
            groups: dict[str, list[str]] = {}
            for a in node.names:
                if a.name not in table:
                    raise SystemExit(
                        f"{path}:{node.lineno}: unmapped symbol "
                        f"{a.name!r} from {node.module}")
                spec = a.name + (f" as {a.asname}" if a.asname else "")
                groups.setdefault(table[a.name], []).append(spec)
            edits.append((node.lineno - 1, node.end_lineno, "".join(
                f"{indent}from {base}.{mod} import {', '.join(sorted(s))}\n"
                for mod, s in sorted(groups.items()))))
    if not edits:
        return False
    for start, end, repl in sorted(edits, reverse=True):
        lines[start:end] = [repl]
    path.write_text("".join(lines))
    return True


def main() -> None:
    changed = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(p in path.parts for p in (".venv", "__pycache__")):
            continue
        if path.name == "split_science_imports.py":
            continue
        if rewrite(path):
            changed += 1
            print(f"rewrote {path.relative_to(ROOT)}")
    print(f"\n{changed} files changed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the codemod**

Run: `cd backend && python scripts/split_science_imports.py`
Expected: prints ~190+ `rewrote ...` lines and a total. If it exits with `unmapped symbol`, a class was added to the umbrella after this plan was written and is missing from the maps. Recover with: `git checkout -- backend/` to reset, add the symbol to the correct map (`MODELS` or `SCHEMAS`) plus the matching shim/module, then re-run.

- [ ] **Step 3: Format**

Run: `cd backend && source .venv/bin/activate && isort app tests scripts && black app tests scripts`

- [ ] **Step 4: Verify nothing imports the umbrella**

Run: `grep -rn "app\.models\.science\|app\.schemas\.science\|app\.services\.science" backend --include="*.py" | grep -v "scripts/split_science_imports.py"`
Expected: no output. If anything remains (e.g. a `from app.models import science` form the codemod does not handle), fix it by hand.

- [ ] **Step 5: Run the suite**

Run: `cd backend && source .venv/bin/activate && pytest -q && mypy app`
Expected: PASS (unchanged pass/fail counts).

- [ ] **Step 6: Commit**

```bash
git add backend/
git commit -m "refactor(TD-0083): migrate all backend imports off science umbrella

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Delete the umbrella files

**Files:**
- Delete: `backend/app/models/science.py`, `backend/app/schemas/science.py`, `backend/app/services/science/` (whole directory)

- [ ] **Step 1: Delete**

```bash
git rm backend/app/models/science.py backend/app/schemas/science.py
git rm -r backend/app/services/science/
```

- [ ] **Step 2: Run the suite**

Run: `cd backend && source .venv/bin/activate && pytest -q && mypy app`
Expected: PASS — the umbrella is unreferenced after Task 4, so deletion changes nothing.

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor(TD-0083): delete the science umbrella modules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Drop the `/science/` API prefix

**Files:**
- Modify: `backend/app/main.py` (lines ~437–461 — the `include_router` block)
- Modify: `backend/app/schemas/signoffs.py` (the `GlpSignoffResponse` URL)
- Modify: `backend/app/services/protocols/template_converter.py:171,175`
- Modify: backend test files containing `/science/` URL strings (~305 occurrences)

- [ ] **Step 1: Remove the prefix from the 10 routers in `main.py`**

For each `include_router` call currently using `prefix="/science"`, drop the prefix and set a domain tag:

```python
# before
app.include_router(unit_ops.router, prefix="/science", tags=["science"])
# after
app.include_router(unit_ops.router, tags=["unit-ops"])
```

Apply to all ten: `unit_ops` → `["unit-ops"]`, `protocol_versions` → `["protocol-versions"]`, `protocols` → `["protocols"]`, `protocol_pdfs` → `["protocol-pdfs"]`, `runs` → `["runs"]`, `experiments` → `["experiments"]`, `batch_record_import` → `["batch-record-import"]`, `export_data` → `["export"]`, `project_members` → `["project-members"]`, `template_convert` → drop only the prefix (tag is already `["template-convert"]`). Route decorators inside the routers are **not** changed.

- [ ] **Step 2: Fix the 3 hardcoded `/science/` URL strings**

- `backend/app/schemas/signoffs.py` — `GlpSignoffResponse`: `f"/science/signoffs/{self.id}/signature"` → `f"/signoffs/{self.id}/signature"`
- `backend/app/services/protocols/template_converter.py:171` — `f"/science/templates/conversions/"` → `f"/templates/conversions/"`
- `backend/app/services/protocols/template_converter.py:175` — same change

- [ ] **Step 3: Update backend test URL strings**

```bash
cd backend && grep -rl "/science/" tests --include="*.py" | xargs sed -i 's#/science/#/#g'
```

Then verify: `grep -rn "/science" backend/tests --include="*.py"` → no output. Fix any straggler (e.g. a `"/science"` with no trailing slash) by hand.

- [ ] **Step 4: Run the suite**

Run: `cd backend && source .venv/bin/activate && pytest -q`
Expected: PASS. Failures here mean a test URL or hardcoded URL was missed — fix and re-run.

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "refactor(TD-0083): drop the /science API prefix

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Update frontend `/science/` URL references

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/lib/api.test.ts`, and ~21 components/routes containing `/science/` (115 occurrences)

- [ ] **Step 1: Rewrite the URLs**

```bash
cd frontend && grep -rl "/science/" src --include="*.ts" --include="*.svelte" | xargs sed -i 's#/science/#/#g'
```

Then verify: `grep -rn "/science" frontend/src --include="*.ts" --include="*.svelte"` → no output. Fix any straggler (e.g. a `'/science'` base-path constant) by hand.

- [ ] **Step 2: Type-check and unit-test**

Run: `cd frontend && npm run check && CI=true npm run test`
Expected: PASS — `api.test.ts` URL expectations were updated by the same `sed`.

- [ ] **Step 3: Commit**

```bash
git add frontend/
git commit -m "refactor(TD-0083): drop /science from frontend API URLs

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Split `test_science_api.py` into per-domain integration files

The umbrella integration test (`tests/integration/test_science_api.py`, 47
tests across 6 domains) is the test-layer twin of the `science.py` grab-bag.
Splitting it by domain finishes the refactor: every domain's API tests live in
that domain's file. This is a pure move — **no test body changes** (the URLs
inside were already rewritten by Task 6's `sed`). Two target files already
exist and are appended to; five are new.

**Files:**
- Create: `backend/tests/integration/test_unit_ops_api.py`, `test_protocol_roles_api.py`, `test_protocol_versions_api.py`, `test_runs_api.py`, `test_run_role_assignments_api.py`
- Modify (append): `backend/tests/integration/test_protocols_api.py`, `test_projects_api.py`
- Delete: `backend/tests/integration/test_science_api.py`

`test_science_api.py` has **no module-level fixtures, helpers, or constants** —
only `async def test_*` functions and `# ---` section comments (verified). So
each step below is a verbatim function move; nothing shared needs relocating.

Post-Task-4 the file's header reads:

```python
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import (
    ObjectPermission, ObjectType, Organization, OrganizationMember,
    PermissionLevel, PrincipalType, User,
)
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Run
```

Call that **HEADER** below. `isort` (Step 10) re-wraps it; copy it whole and
let the formatter normalize.

- [ ] **Step 1: Baseline the test count**

Run: `cd backend && source .venv/bin/activate && pytest --collect-only -q tests/integration/test_science_api.py | tail -3`
Expected: `47 tests collected`. Record this — Step 10 reconciles against it.

- [ ] **Step 2: Create `test_unit_ops_api.py` (3 tests)**

New file. Header is the minimal subset (these tests use only `client` /
`auth_headers`):

```python
import pytest
from httpx import AsyncClient
```

Cut these functions verbatim from `test_science_api.py` (with their
`@pytest.mark.asyncio` decorators) into the new file:

- `test_list_unit_ops_authenticated`
- `test_list_unit_ops_unauthenticated`
- `test_create_unit_op`

(`tests/integration/test_unit_ops_scoping.py` already exists but covers
library-scoping, a different concern — keep these as a separate API file.)

- [ ] **Step 3: Create `test_protocol_roles_api.py` (4 tests)**

New file. Header = **HEADER**. Cut these functions verbatim:

- `test_list_protocol_roles`
- `test_create_protocol_role`
- `test_update_protocol_role`
- `test_delete_protocol_role`

- [ ] **Step 4: Create `test_protocol_versions_api.py` (10 tests)**

New file. Header = **HEADER**. Cut these functions verbatim — the protocol
publish / draft-version / version-listing tests, including the ones currently
under the `# --- Protocol Publishing ---` section comment:

- `test_publish_protocol_success`
- `test_save_as_draft_creates_draft_version`
- `test_publish_draft_not_found`
- `test_save_draft_always_creates_version`
- `test_save_as_draft_syncs_live_graph_for_unpublished_protocol`
- `test_save_as_draft_preserves_live_graph_for_published_protocol`
- `test_list_versions_returns_description`
- `test_publish_draft_persists_description`
- `test_publish_draft_persists_change_summary`
- `test_publish_draft_without_body_still_works`

- [ ] **Step 5: Create `test_runs_api.py` (11 tests)**

New file. Header = **HEADER**. Cut these functions verbatim — run CRUD plus
the run-start lifecycle tests:

- `test_create_run`
- `test_create_run_no_project_perm`
- `test_get_run_with_perm`
- `test_get_run_without_perm`
- `test_update_run_with_edit_perm`
- `test_list_runs_for_project`
- `test_start_run_without_assignments_fails`
- `test_start_run_with_swimlanes_requires_all_assigned`
- `test_start_run_succeeds_with_one_assignment_no_swimlanes`
- `test_start_run_succeeds_with_all_swimlanes_assigned`
- `test_started_by_id_set_on_active_transition`

- [ ] **Step 6: Create `test_run_role_assignments_api.py` (7 tests)**

New file. Header = **HEADER**. Cut these functions verbatim — role-assignment
CRUD plus the assignment-gated transition/audit tests:

- `test_create_role_assignment`
- `test_get_role_assignments`
- `test_update_role_assignment`
- `test_delete_role_assignment`
- `test_transition_to_active_with_all_roles_assigned`
- `test_transition_to_active_without_all_roles_assigned`
- `test_assignment_operations_audit_logged`

- [ ] **Step 7: Append Protocols CRUD to `test_protocols_api.py` (10 tests)**

`test_protocols_api.py` already exists (it holds
`test_delete_sample_protocol_hard_deletes`). Its header already imports
`pytest`, `AsyncClient`, `select`, `AsyncSession`, `Organization`, `Project`,
`Protocol` — append `User` to the `app.models.iam` import and add
`from app.models.runs import Run` only if a moved test references `Run`
(none do — skip it). Append these functions verbatim to the end of the file:

- `test_create_protocol`
- `test_create_protocol_no_project_perm`
- `test_get_protocol_with_project_perm`
- `test_get_protocol_without_perm`
- `test_update_protocol_with_edit_perm`
- `test_update_protocol_view_only_forbidden`
- `test_list_protocols_for_project`
- `test_list_protocols_filters_archived_by_default`
- `test_list_protocols_surfaces_latest_draft_version`
- `test_get_protocol_surfaces_latest_draft_version`

Collision guard: none of these 10 names exist in `test_protocols_api.py`
(verified — its only test is `test_delete_sample_protocol_hard_deletes`). If a
future collision appears, `grep -nE '^async def NAME' test_protocols_api.py`
before appending; a same-name hit means Python would silently shadow the
earlier `def` — diff the two bodies, drop the move if identical, otherwise
rename the moved one and note the rename.

- [ ] **Step 8: Append Project Members to `test_projects_api.py` (2 tests)**

`test_projects_api.py` already exists with a full `app.models.iam` import
(`ObjectPermission`, `ObjectType`, `Organization`, `OrganizationMember`,
`PermissionLevel`, `PrincipalType`, `User`) and `from app.models.projects
import Project` — no header change needed. Append these functions verbatim:

- `test_get_project_members`
- `test_get_project_members_no_perm`

(Collision guard: neither name exists in `test_projects_api.py` — verified.)

- [ ] **Step 9: Delete the emptied umbrella test file**

`test_science_api.py` is now empty of test functions (only the header and
`# ---` comments remain). Delete it:

```bash
git rm backend/tests/integration/test_science_api.py
```

- [ ] **Step 10: Verify the test count and run the suite**

```bash
cd backend && source .venv/bin/activate
isort tests/integration && black tests/integration
pytest --collect-only -q tests/integration/test_unit_ops_api.py \
  tests/integration/test_protocol_roles_api.py \
  tests/integration/test_protocol_versions_api.py \
  tests/integration/test_runs_api.py \
  tests/integration/test_run_role_assignments_api.py \
  tests/integration/test_protocols_api.py \
  tests/integration/test_projects_api.py | tail -3
```

Expected: **59 tests collected** across the 7 destination files — the 47
moved tests, plus the 1 test already in `test_protocols_api.py`, plus the 11
already in `test_projects_api.py` (`47 + 1 + 11 = 59`). Per file:
`test_unit_ops_api.py` 3, `test_protocol_roles_api.py` 4,
`test_protocol_versions_api.py` 10, `test_runs_api.py` 11,
`test_run_role_assignments_api.py` 7, `test_protocols_api.py` 11,
`test_projects_api.py` 13. Then run the full suite:

Run: `pytest -q tests/integration`
Expected: PASS — identical pass/fail counts to before the split (no test body
changed). A `0 tests collected` for any new file means a decorator was left
behind; a failure means a function was split mid-body — re-check the cut.

- [ ] **Step 11: Commit**

```bash
git add backend/tests/integration/
git commit -m "test(TD-0083): split test_science_api into per-domain files

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Final verification and doc refresh

**Files:**
- Delete: `backend/scripts/split_science_imports.py`
- Modify: `.claude/rules/backend-models.md` (path reference), plus any other doc/rule referencing the old paths

- [ ] **Step 1: Delete the one-shot codemod**

```bash
git rm backend/scripts/split_science_imports.py
```

- [ ] **Step 2: Full backend verification**

Run: `cd backend && source .venv/bin/activate && pytest -q && mypy app && alembic check`
Expected: `pytest` PASS, `mypy` clean, `alembic check` reports no new migration needed (no schema drift — table names were untouched).

- [ ] **Step 3: Acceptance grep**

Run: `grep -rn "science" backend/app frontend/src`
Expected: only legitimate domain prose (e.g. UI copy, comments about lab science) — no module paths, import paths, or `/science/` URLs. Investigate every hit.

- [ ] **Step 4: Refresh project rules**

`grep -rn "science" .claude CLAUDE.md` and update stale references. Known one: `.claude/rules/backend-models.md` ends its polymorphic-FK note with `(see backend/app/models/science.py)` — change to `backend/app/models/signoffs.py`. Update any other path references found; do not pad the files.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(TD-0083): remove codemod, refresh path references

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

- [ ] **Step 6: Browser smoke check**

Frontend URLs changed, so `/implement-task` runs the `qa-verify` agent after this plan: load a project, open a protocol, open a run, confirm data loads (no `/science/` 404s in the network tab).

---

## Notes

- **No Alembic migration** — `__tablename__` values are unchanged; the refactor is Python-module-only.
- **Duplicated `RunStatus`/`ExperimentStatus` enums** (one pair in the model layer, one in the schema layer) are preserved as-is; deduping them is out of scope.
- **Transitional shims** in Tasks 1–3 keep the suite green between tasks and are deleted in Task 5 — they are not part of the final state.
- If the codemod (Task 4) reports an `unmapped symbol`, a class was added to the umbrella after this plan was written — add it to the correct map in `split_science_imports.py` and to the relevant shim/module, then re-run.
