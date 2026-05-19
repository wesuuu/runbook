# TD-0083 — Rename and split the backend "science" module

**Date:** 2026-05-19
**Ticket:** TD-0083 (TECH_DEBT, P2)
**Scope:** Full stack — backend models/schemas/services/routing + frontend URL refs

## Problem

The `science` namespace is a grab-bag with no domain meaning. It bundles
Projects, Protocols, Runs/Experiments, Unit Ops, Equipment, Sites, and GLP
sign-offs under one `models/science.py` (819 lines, 22 classes), mirrors that
in `schemas/science.py` (682 lines, 62 classes), and uses `/science/` as the
API prefix for 10 unrelated routers. The umbrella hides domain boundaries.

This task splits the umbrella by domain and drops the `/science/` API prefix.
It is a mechanical refactor: **no behavior change, no DB schema change, no
Alembic migration** (table names are untouched).

## Survey (re-run 2026-05-19)

Counts have grown well past the ticket's estimates:

| Item | Ticket estimate | Actual |
| --- | --- | --- |
| `models/science.py` | ~360 lines | 819 lines, 22 classes |
| `schemas/science.py` | ~415 lines | 682 lines, 62 classes |
| Backend `app/` import sites | ~52 | 75 |
| Backend `tests/` import sites | (uncounted) | 114 |
| Frontend `/science/` URL refs | ~81 | 115 |

Two domains exist that the ticket's 4-way split did not anticipate: **GLP
sign-offs** and **Sites**. The split is therefore 6 domains, not 4.

Domain `services/` subdirectories (`protocols/`, `runs/`, `sites/`,
`signoffs/`, `equipment/`) and domain schema files (`schemas/equipment.py`,
`schemas/sites.py`, `schemas/project.py`) already exist — the new model and
schema modules mirror that structure.

## Design

### 1. Models — `models/science.py` → 6 new files

All six target files are new; no merge collisions.

| File | Classes |
| --- | --- |
| `models/protocols.py` | `Protocol`, `ProtocolRole`, `ProtocolVersion`, `UnitOpDefinition`, `UnitOpLibrarySubscription` |
| `models/runs.py` | `Run`, `RunStatus`, `RunRoleAssignment`, `RunOutcome`, `Experiment`, `ExperimentStatus` |
| `models/projects.py` | `Project` |
| `models/equipment.py` | `Equipment`, `EquipmentAttachment`, `EquipmentStatus` |
| `models/sites.py` | `Site`, `SiteManagerGrant` |
| `models/signoffs.py` | `GlpSignoff`, `GlpSignoffRequest`, `GlpRole`, `GlpSignoffAction`, `GlpSignoffRequestStatus` |

Cross-module relationships (Protocol↔Run, Project↔Experiment, Run↔GlpSignoff)
already use string targets — `ForeignKey("runs.id")`, `relationship("Run")` —
so they survive the split unchanged. Add `TYPE_CHECKING` imports where
`Mapped[...]` annotations reference a class in another module. All six modules
must be imported before mapper configuration; `db/base.py` already does this
for Alembic and will import all six.

### 2. Schemas — `schemas/science.py` → 3 new files

`schemas/equipment.py`, `schemas/sites.py`, and `schemas/project.py` already
exist; `schemas/science.py` contains no Project or Site schemas, so only three
new files are created:

| File | Classes |
| --- | --- |
| `schemas/protocols.py` | `UnitOpDefinition*`, `ProtocolRole*`, `Protocol*`, `ProtocolVersion*`, approval-workflow requests (`PublishDraftRequest`, `DesignateApprovalRequest`, `SubmitForApprovalRequest`, `ApproveProtocolRequest`, `RejectProtocolRequest`, `ApprovalActorRef`, `AwaitingApprovalItem`), `GraphPayload`, protocol-import schemas (`StepProposalSchema`, `ProtocolImportProposalResponse`, `ProtocolRefineRequest`, `ProtocolImportFinalizeRequest`) |
| `schemas/runs.py` | `Experiment*`, `Run*`, `RunRoleAssignment*`, `NodeOverrides`, `RunOverrides`, `SuggestLotNumber*`, `CheckLotNumberResponse`, `RunCompleteRequest`, `RunReopenRequest`, schema-side `RunStatus`/`ExperimentStatus` enums |
| `schemas/signoffs.py` | `GlpSignoffCreate`, `GlpSignoffResponse` |

**Dead code deleted:** `EquipmentBase`, `EquipmentCreate`, `EquipmentUpdate`,
`EquipmentResponse` in `schemas/science.py` have zero importers anywhere —
they are superseded by the F-0088 `schemas/equipment.py` registry schemas
(which carry `site_id`, `tags`, `status`, `manufacturer`, …). They are deleted
rather than moved: there is no consumer and no sensible home, and
`schemas/science.py` must cease to exist.

### 3. Services

Move `services/science/library_registry.py` → `services/protocols/library_registry.py`.
Delete the `services/science/` directory.

### 4. Import migration — 189 backend sites

A one-shot Python codemod rewrites every import of `app.models.science`,
`app.schemas.science`, and `app.services.science` across `backend/app` (75)
and `backend/tests` (114). It must:

- Parse parenthesised multi-line imports and indented function-level imports.
- Map each imported symbol via a deterministic symbol→module table derived
  from sections 1–3, exploding one multi-symbol import into up to six.
- Rewrite `from app.services.science import library_registry` →
  `from app.services.protocols import library_registry`.

Run `isort` + `black` afterwards. `db/base.py` (imports all models for
Alembic) and `db/seed.py` are updated by the same codemod. Codemod output is
reviewed before commit; the test suite is the correctness backstop.

### 5. API routing — drop the `/science/` umbrella

In `main.py`, remove `prefix="/science"` from the 10 routers mounted under it
(`unit_ops`, `protocol_versions`, `protocols`, `protocol_pdfs`, `runs`,
`experiments`, `batch_record_import`, `export_data`, `project_members`,
`template_convert`) and retag each with a domain tag. Route decorators are
**not** changed: routers already declare full resource paths internally
(`protocols.py` → `/protocols/{id}`, `runs.py` → `/runs/{id}`), and some span
multiple resource roots (`experiments.py` has `/experiments` *and*
`/projects/{id}/experiments`), so collapsing each into a single mount prefix
is not coherent. Dropping the prefix changes URLs from `/science/protocols/x`
to `/protocols/x` with no other change.

`sites.router` and `equipment.router` are already mounted with their own
prefixes — untouched.

### 6. Frontend — 115 URL refs

A codemod replaces the `/science/` path segment with `/` across `lib/api.ts`
and components (115 occurrences). All occurrences are URL path prefixes;
output is grep-verified for false positives.

## Testing & verification

- Full `pytest` suite passes. Behavior assertions are unchanged; only URL
  fixtures and import paths are updated. The 114 test import sites are
  migrated by the same codemod as app code.
- `mypy app` clean.
- `alembic check` confirms no schema drift — no migration is generated.
- Frontend `npm run check` (svelte-check + tsc) clean.

## Acceptance criteria (from ticket)

- [x] Prerequisite survey completed; new domains (sign-offs, sites) accounted for.
- [ ] `models/science.py`, `schemas/science.py`, `services/science/` no longer exist.
- [ ] No router uses `prefix="/science"`; each router serves a domain-specific path.
- [ ] No frontend code references `/science/` URL paths.
- [ ] All existing tests pass without changes to behavior assertions.
- [ ] No Alembic migration required.
- [ ] `grep -r "science" backend/app frontend/src` returns only legitimate
      domain text, not module/path references.

## Out of scope

- Deduping the `RunStatus` / `ExperimentStatus` enums that exist in both the
  model and schema layers today — preserved as-is.
- Any behavior, endpoint contract, or DB schema change.
- Unrelated refactoring of the routers being remounted.
