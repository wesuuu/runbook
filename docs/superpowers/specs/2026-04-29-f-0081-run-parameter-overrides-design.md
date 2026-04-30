# F-0081 — Run Parameter Overrides & Multi-Step Run Creator

**Status:** Draft
**Author:** Wesley Uykimpang
**Date:** 2026-04-29
**ClickUp:** [86e15ctzd](https://app.clickup.com/t/86e15ctzd)
**Mockup:** [`mockups/F-0081-run-creator-wizard.html`](../../../mockups/F-0081-run-creator-wizard.html)

## Summary

Today, runs are created as a verbatim shallow-copy snapshot of `protocol.graph` — every unit op carries the protocol's default parameter values, with no way to vary them per run. This forces scientists optimizing a protocol (e.g., a DOE sweep over temperature, pH, residence time) to either fork the protocol or edit results post-hoc — neither captures the intent of the experiment.

This task replaces the small `CreateRunModal` with a full-page multi-step wizard. Scientists pick a protocol and version, override values where the science demands it, swap equipment, optionally add or remove parameters, see the rendered instruction text update live, and — if any edits are made — get a single dialog before review asking whether to save the changes as a new protocol version.

The data model and API are designed so a future "DOE batch" feature (generate N runs varying one or more params across a design matrix) can be layered on without rework.

## Goals

- Per-run parameter variation without forking protocols
- Per-run equipment swaps (different physical asset per run)
- Add/remove parameters per run, with an option to promote the change to a new protocol version
- Live-rendered instruction preview so scientists verify their overrides read correctly
- Editable while `PLANNED`; locks on transition to `ACTIVE` (existing GMP semantics)
- API shape that a future `POST /runs/batch` can consume without restructuring

## Non-goals

- Building the DOE batch generator (separate feature)
- Read-only `ProtocolEditor` canvas mode for version preview (level-3 preview is punted; level-2 compact UO list is sufficient)
- Backfilling descriptions on existing `ProtocolVersion` rows
- Server-side JSON Schema validation of param values (frontend pre-submit validation is sufficient for now; backend follow-up if needed)
- Run comparison view (F-0069) — coordinates with this design but is its own feature

## User Flows

**Create run from a protocol (default flow)**

1. From the project page, "New Run" navigates to `/projects/{projectId}/runs/new`
2. **Step 1 · Name** — run name, optional experiment
3. **Step 2 · Protocol & version** — pick protocol; version defaults to latest, with a "Compare versions" disclosure showing description + compact UO list
4. **Step 3 · Parameters** — per-unit-op cards with equipment chips, parameter table (with default + override columns), live instruction preview, `+ Add parameter` / `↺ revert` / `✕ remove`
5. On Continue, if any edits exist (value, swap, add/remove): single dialog asking "Save as new version?" with edits listed. Default focused button is **Just for this run · continue →**.
6. **Step 4 · Review** — summary of overrides, "Create run" → POSTs `/science/runs`, redirects to the run detail page
7. Skip override step at any time → run created identical to today's behavior

**Edit while PLANNED**

- On the run detail page, an `Overrides` section appears at the top while `status == PLANNED`. Same shape as the wizard's Step 3, inline.
- Editing posts `PUT /science/runs/{id}` with the updated graph.
- If new edits would be structural (add/remove param, equipment slot), the same save-as-version dialog can fire; otherwise a quiet save.

**Lock on ACTIVE**

- On transition to `ACTIVE`, the snapshot becomes immutable (existing behavior). `Overrides` section flips to read-only.

## Phasing

| Phase | What | Why first |
|---|---|---|
| **1** | Surface `ProtocolVersion.description` (already in DB) via the protocol editor's publish flow | Prerequisite — version picker in the wizard needs descriptions to be useful |
| **2** | Backend — extend run create / update to accept overrides; deep-copy graph snapshot; preserve originals; audit | Backend foundation for the wizard |
| **3** | Frontend — full-page wizard route + step components + save-as-version dialog | The user-facing feature |
| **4** | Run detail page integration — display + edit overrides while PLANNED | Closes the loop on the lifecycle |

Each phase is independently shippable behind partial UI: Phase 1 gives the protocol editor a description input. Phase 2 unlocks the API. Phase 3 lights up the wizard. Phase 4 lights up run-page editing.

---

## Phase 1 — Surface `ProtocolVersion.description`

### Backend

`ProtocolVersion.description` and `ProtocolVersion.change_summary` already exist as nullable strings (`backend/app/models/science.py:327`). The existing `POST /protocols/{id}/publish-draft` endpoint (`backend/app/api/endpoints/protocol_versions.py:380`) does **not** accept a description today.

**Change:** add an optional body to `publish-draft`:

```python
class PublishDraftRequest(BaseModel):
    description: Optional[str] = None
    change_summary: Optional[str] = None  # already in model

@router.post("/protocols/{protocol_id}/publish-draft")
async def publish_draft_version(
    protocol_id: UUID,
    version_number: int = Query(...),
    body: Optional[PublishDraftRequest] = None,
    ...
):
    ...
    draft.is_draft = False
    if body and body.description is not None:
        draft.description = body.description
    if body and body.change_summary is not None:
        draft.change_summary = body.change_summary
    protocol.graph = draft.graph
    protocol.version_number = version_number
    ...
```

The endpoint stays backwards-compatible: existing callers that don't send a body still work.

### Frontend

In `frontend/src/routes/protocols/[id]/+page.svelte:508`, `saveAndPublish()` currently does a draft save then publishes the draft with no metadata input. **Change:** before posting `publish-draft`, open a confirmation dialog (new component `PublishVersionDialog.svelte`) with:

- **Description** (textarea, optional, placeholder "What changed in this version?")
- **Change summary** (text input, optional, single line — for one-line changelog format if author wants)
- Cancel / Publish actions

Dialog component path: `frontend/src/lib/components/protocol/PublishVersionDialog.svelte` (lives next to `ProtocolSidebar.svelte`).

Submitting fires:

```typescript
await api.post(`/science/protocols/${protocol.id}/publish-draft?version_number=${draftVersionNumber}`, {
  description: trimmedDescription || undefined,
  change_summary: trimmedSummary || undefined,
});
```

### Tests

- Backend integration: `POST /protocols/{id}/publish-draft` with a description body persists it on the version; without a body still works (regression).
- Backend integration: `GET /protocols/{id}/versions` returns the description.
- Frontend Vitest: `PublishVersionDialog` — submit with empty description sends no field; with description sends the value; cancel closes.

### Out of scope (Phase 1)

- Backfilling descriptions on existing versions
- A standalone "edit version description" endpoint
- Markdown rendering in description display (plain text for now)

---

## Phase 2 — Backend: run override API

### Data model

Overrides themselves live entirely within `Run.graph` JSONB — no DB migration is required for the override storage. Per unit-op node in the snapshot:

| Field | Meaning |
|---|---|
| `node.data.params` | Effective values for this run (protocol defaults merged with overrides) |
| `node.data.protocol_params` | Original protocol defaults — preserved forever, never written by overrides |
| `node.data.equipment` | Effective equipment list for this run |
| `node.data.protocol_equipment` | Original protocol equipment — preserved forever |
| `node.data.paramSchema` | Effective schema for this run (reflects added/removed params) |
| `node.data.protocol_paramSchema` | Original protocol schema — preserved forever |
| `node.data.description` | Effective instruction template for this run (overridable) |
| `node.data.protocol_description` | Original protocol instruction template — preserved forever |

The "protocol_*" mirror fields make `effective vs. default` diffs trivial to compute downstream (relevant to F-0069 run comparison).

**One small migration:** add nullable `Run.parent_batch_id: Optional[uuid.UUID]` (no FK constraint yet — just a UUID column with an index). Anticipates DOE-batch grouping so the future batch task is purely additive on the API side and doesn't need to migrate the runs table at that point.

### API shape — `POST /science/runs`

```python
# backend/app/schemas/science.py

class NodeOverrides(BaseModel):
    """Sparse overrides applied to a single unit-op node in the run snapshot."""
    params: Optional[Dict[str, Any]] = None        # sparse: only the keys being overridden
    equipment: Optional[List[SelectedEquipment]] = None  # full replacement list (None = inherit)
    paramSchema: Optional[Dict[str, Any]] = None   # full schema if structurally modified
    description: Optional[str] = None              # full replacement of instruction template (None = inherit)

class RunOverrides(BaseModel):
    """Per-run edits to the protocol snapshot. Empty = use protocol defaults."""
    nodes: Dict[str, NodeOverrides] = Field(default_factory=dict)
    # nodeId -> NodeOverrides

class RunCreate(BaseModel):
    name: str
    project_id: UUID
    protocol_id: Optional[UUID] = None
    protocol_version_number: Optional[int] = None  # defaults to current protocol.version_number
    experiment_id: Optional[UUID] = None
    overrides: Optional[RunOverrides] = None
```

This shape per-run-keyed-by-nodeId is what a future `POST /science/runs/batch` consumes naturally:

```python
class RunBatchCreate(BaseModel):
    common: RunCommonFields  # name template, project_id, protocol_id, version
    runs: List[RunBatchItem]  # each with a unique name + RunOverrides

# A 32-arm DOE sweep is just a 32-element list.
```

Designing the batch endpoint is **not** in scope for F-0081, but the singleton shape must be batch-compatible — which it is.

### Run-creation logic

In `backend/app/api/endpoints/runs.py:53` (the existing `create_run`):

1. Resolve which `ProtocolVersion.graph` to snapshot:
   - If `protocol_version_number` is `None`, use `protocol.graph` (current published).
   - Else, load the matching `ProtocolVersion` and use its `graph`.
2. **Deep copy** the graph (`copy.deepcopy`) — current code does a shallow `protocol.graph.copy()` which would mutate the protocol on per-node overrides.
3. For each node in `graph["nodes"]` of type `unitOp`:
   - Capture originals into mirror fields: `protocol_params`, `protocol_equipment`, `protocol_paramSchema`, `protocol_description`.
   - If `overrides.nodes[node_id]` exists:
     - `params = {**protocol_params, **overrides.params}` (sparse merge)
     - `equipment = overrides.equipment or protocol_equipment`
     - `paramSchema = overrides.paramSchema or protocol_paramSchema`
     - `description = overrides.description if overrides.description is not None else protocol_description`
4. Persist `Run.graph` with the merged result.
5. **Audit log** one entry per overridden field, using a new audit action `OVERRIDE_SET` (creation-time). Payload mirrors the existing `STEP_EDIT` shape at `runs.py:282-303`:
   ```python
   await log_audit(
       db, user.id, "OVERRIDE_SET", "Run", run_obj.id,
       {"step_id": node_id, "step_name": label, "field": param_key,
        "field_label": prop_title, "old_value": protocol_default, "new_value": override_value},
   )
   ```
   Equipment swaps, schema add/remove, and instruction edits get the same action with `field` set to `"equipment"`, `"paramSchema.<key>"`, or `"description"` respectively.
6. Existing audit on run creation (`{"name": run_in.name}`) stays unchanged.

### API shape — `PUT /science/runs/{id}` (edit while PLANNED)

The endpoint already exists (`runs.py:153`) and accepts a full `graph` payload. **Change:** add a guard that rejects graph edits when `status != "PLANNED"`:

```python
if "graph" in changes and current_status != "PLANNED":
    raise HTTPException(
        status_code=422,
        detail="Cannot edit overrides after run has started"
    )
```

Two ways to express edits in `PUT`:
- **Option A (chosen):** client sends the full `graph` dict (current contract). Backend diffs against `Run.graph` to write audit entries, then replaces.
- Option B: dedicated `PUT /runs/{id}/overrides` with the same `RunOverrides` shape.

Reuse Option A to minimize endpoint sprawl. Audit-diff logic lives in a new helper `_audit_graph_overrides(db, user, run, old_graph, new_graph)` so the create and update paths share it.

### Tests (Phase 2)

Backend integration (`backend/tests/integration/api/test_runs_overrides.py`):

- `create_run` with no overrides → graph identical to today's behavior; `protocol_*` mirror fields populated
- `create_run` with sparse value overrides → merged values applied; defaults preserved in mirrors
- `create_run` with equipment swap → `node.data.equipment` reflects swap; `protocol_equipment` preserved
- `create_run` with `paramSchema` override (added param) → schema mutated; new key visible in `paramSchema.properties`
- `create_run` with `description` override → instruction template replaced; `protocol_description` mirror preserves original
- `create_run` with overrides → audit log has one `STEP_EDIT` entry per overridden field
- `update_run` with `graph` while `PLANNED` → 200, audit entries written
- `update_run` with `graph` while `ACTIVE` → 422
- `create_run` from non-current `protocol_version_number` → snapshots that version's graph, not current
- Deep-copy regression: mutating `Run.graph.nodes[...].data.params` does not mutate `Protocol.graph`

Backend unit:
- `_audit_graph_overrides` helper: produces correct entries for added/removed/modified fields

---

## Phase 3 — Frontend wizard

### Route + entry points

- New route: `frontend/src/routes/projects/[id]/runs/new/+page.svelte` — the wizard host.
- Entry: existing "New Run" buttons (project page, experiment detail) `goto('/projects/{id}/runs/new')` instead of opening `CreateRunModal`. Pass `experimentId` via query param when applicable.
- `CreateRunModal.svelte` → delete after migration. (No backwards-compat shim; the button targets change in the same PR.)

### Component layout

All new components live under `frontend/src/lib/components/run/` (existing domain bucket per `.claude/rules/conventions.md`). Wizard shell + step components:

```
run/
  RunCreatorPage.svelte          # the route page; holds wizard state, orchestrates
  RunCreatorStepper.svelte       # presentational stepper (4 pills)
  RunCreatorNameStep.svelte      # Step 1
  RunCreatorProtocolStep.svelte  # Step 2 — protocol + version + level-2 preview
  RunCreatorParametersStep.svelte# Step 3 — per-UO override editor
  RunCreatorReviewStep.svelte    # Step 4
  RunCreatorUnitOpCard.svelte    # one card inside ParametersStep
  SaveAsNewVersionDialog.svelte  # the on-Continue prompt
```

Shared UI:
- `frontend/src/lib/utils/template.ts` — extract `renderTemplate(template, params)` from `Inspector.svelte:231`. Both Inspector and `RunCreatorUnitOpCard` use it.
- `frontend/src/lib/utils/runOverrides.ts` — pure helpers: `computeEdits(originalGraph, currentGraph)`, `applyOverrides(graph, overrides)`, `hasStructuralChanges(edits)`.

### Step 2 · Protocol + version (level-2 preview)

- Protocol picker (existing `<select>` styling).
- Version picker — defaults to "latest". `<select>` listing `vN — created date — author`.
- Below: **Version summary card** showing `vN`, name + LATEST pill, stats line (`7 unit ops · 31 params · 4 equipment slots · created Apr 12 by Wesley`), description (or "No description").
- Disclosure `↳ Compare versions` reveals:
  - Version list: each row shows version_number + description + author + counts; clicking sets the picker.
  - **Unit ops at-a-glance** detail card for the selected version: ordered list of unit ops with `UO-NN · Name · category · N params · M equipment`. Pure data, no SvelteFlow render.
- (Future: a "View graph ↗" button could open a side sheet with read-only ProtocolEditor canvas. Not built in this task — listed in Phase 3 punts.)

### Step 3 · Parameters

- Each unit-op node in graph order renders as a `RunCreatorUnitOpCard`:
  - Header: UO num, name, category, badges (`N overridden`, `1 invalid`).
  - **Equipment row** — chips for each `data.equipment[i]` with name + serial + `swap` button. Swap opens existing `EquipmentPickerModal`. Swapped chips get a mint border + ◆. If swapped, show "protocol used: …" reminder text.
  - **Parameter table** (4 columns: Parameter, Default, Override for this run, Action). One row per `paramSchema.properties` key. Override input column varies by `prop.type` and `prop["x-ref-type"]` (mirroring Inspector at line 441-490).
  - **`+ Add parameter`** button at table foot opens an inline schema-row form (key + label + type) — reuses logic from Inspector's schema editor (`Inspector.svelte:518-562`). Added rows get an amber `+ ADDED` chip.
  - **Remove a row** (`✕`): marks the param as removed, shows struck-through with a `− REMOVED` chip. Removed rows stay visible (so the diff is readable). Restore via `↺`.
  - **Instructions** block: editable. Default state shows the rendered template (with `<mark>` highlighting on overridden values, muted-toned `<mark>` for defaults) and an `Edit instructions` link. Clicking reveals a textarea pre-filled with `node.data.description`; the rendered preview updates live below as the user types. A `↺ revert to protocol default` button restores the original. If the effective `description !== protocol_description`, the block shows a `◆ instructions modified` chip in the header and stays expanded by default. Uses the shared `renderTemplate()` util.
- Aside (sticky 320px column): live counts (Value overrides / Equipment swaps / Structural changes / Inheriting / Validation errors), diff preview list.
- Footer action bar: `Skip · use defaults` / `Back` / `Continue to review`.

### `SaveAsNewVersionDialog`

Triggered on `Continue to review` if `computeEdits(originalGraph, currentGraph).length > 0`.

- Lists every edit grouped by unit op: `VALUE` / `SWAP` / `ADDED` / `REMOVED` / `INSTRUCTION` tags + human-readable diff. (For `INSTRUCTION` the diff shows the first ~80 chars of old → new with ellipsis; full text on hover.)
- Description input: optional one-liner ("e.g. Reduced pH target for DOE arm 4; swapped to Bioreactor B").
- Three actions: `Cancel` / `Save as v{N+1}` (secondary) / **`Just for this run · continue →`** (primary, focused — Enter dismisses).
- If "Save as v{N+1}":
  1. POST `/science/protocols/{id}/publish-draft?version_number={N+1}` with description (Phase 1 wiring).
  2. Update wizard state: `protocol_version_number = N+1`.
  3. The run snapshot will now use the newly-saved version as the source — overrides reapply against the new defaults (most edits become no-ops, since they're now the protocol's values).
  4. Continue to Step 4.
- If "Just for this run": just continue.

### Frontend tests

Vitest:
- `template.ts` — `renderTemplate` substitution, missing keys, escaping
- `runOverrides.ts` — `computeEdits` value/equipment/schema diffs; `applyOverrides` merge; `hasStructuralChanges`
- `RunCreatorNameStep` — validation, experiment locking
- `RunCreatorProtocolStep` — version defaults to latest; selecting non-latest updates summary
- `RunCreatorParametersStep` — override merge, skip path, validation surfacing, add/remove param flow
- `SaveAsNewVersionDialog` — fires when edits exist, lists correct tags, primary action posts the right payload

Playwright (`frontend/tests/e2e/run-creator.spec.ts`):
- Full create flow: name → pick protocol/version → override two values + swap equipment + add a param → save-as-version dialog appears → "Just for this run" → review → create → land on run detail page with overrides visible
- PLANNED-state edit flow: open run, change an override, save, audit entry created, lock on ACTIVE

---

## Phase 4 — Run detail page integration

### Display

`frontend/src/routes/runs/[id]/+page.svelte` (1032 LOC today). Add an `Overrides` section near the top:

- Always visible. Empty-state message when no overrides ("This run uses every protocol default. Edit while in PLANNED to vary parameters.").
- When overrides exist: same shape as wizard Step 3's diff aside — grouped by unit op, with VALUE/SWAP/ADDED/REMOVED chips.
- When `status == "PLANNED"`: `Edit overrides` button → opens an inline editor modeled on `RunCreatorParametersStep` (extract a reusable `<RunOverridesEditor>` component for both surfaces).
- When `status >= "ACTIVE"`: read-only.

### Edit

- Reuse `RunCreatorParametersStep`'s child component as `<RunOverridesEditor mode="edit">`.
- Save: `PUT /science/runs/{id}` with the mutated graph. The Phase 2 audit-diff helper handles audit entries (writes `OVERRIDE_EDIT` actions).
- If the user introduces *any* new edit relative to the protocol's current graph (matching the wizard's behavior — value, swap, add, remove all qualify), the same `SaveAsNewVersionDialog` fires before save with the same primary action ("Just for this run · save"). This keeps the wizard and run-page editing experiences identical.

### Tests (Phase 4)

- Vitest: `RunOverridesEditor` mounts in both wizard and run-page contexts; reset / save behavior
- Playwright: edit-while-PLANNED end-to-end; lock-after-ACTIVE blocks edit

---

## Audit log

Every override write emits one audit entry per `(node_id, field)` tuple. Two new audit actions are introduced (alongside the existing `STEP_EDIT`):

| Action | When | Payload |
|---|---|---|
| `OVERRIDE_SET` | Override applied at run creation | `step_id`, `step_name`, `field`, `field_label`, `old_value` (protocol default), `new_value` |
| `OVERRIDE_EDIT` | Override edited while `PLANNED` | Same shape; `old_value` is the previous override value |
| `STEP_EDIT` (existing) | Post-completion edits in `EDITED` status | Unchanged |

The Run history view (existing `RunHistory.svelte`) iterates audit entries by entity_id; the new actions need render-time labels ("Set at creation", "Edited while planned") added to the existing label map.

---

## Open questions / risks

| Question | Resolution |
|---|---|
| Server-side `paramSchema` validation? | **No** — frontend pre-submit validation is the contract today. Server accepts whatever shape it gets. Revisit if scientists hit edge cases. |
| Equipment conflict logic in the wizard? | Equipment shareable/conflict logic exists in `Inspector.svelte` via `equipmentConflicts: Map`. Need to extract or replicate for the wizard. Adds ~half a day; in scope for Phase 3. |
| What happens to overrides if the source `ProtocolVersion` is deleted? | `protocol_version_number` on the run is just an int, not an FK. The mirror fields preserve the originals — losing the ProtocolVersion row is recoverable from any run that snapshotted it. Acceptable. |
| Schema validation server-side: enforce `enum`, `minimum`, `maximum`? | Out of scope for F-0081. Add follow-up task if needed. |
| Should `Run.parent_batch_id` ship in this task or as part of the future batch task? | **Ship in F-0081** as a nullable column (small, decoupled migration). Means the future batch task is purely additive — no run-table migration at that point. |

## Acceptance criteria mapping

(From the ClickUp task description.)

| AC | Where addressed |
|---|---|
| Run creator is a multi-step form (name → protocol → params → review) | Phase 3 |
| Override step lists each unit op with default + override | Phase 3 (`RunCreatorParametersStep`) |
| Visual indicator for overridden vs. inherited | Phase 3 (mint row tint, `2 overridden` badge) |
| Skipping override step → run identical to today | Phase 3 (skip button bypasses overrides; backend with no overrides uses defaults) |
| Param schema validation surfaces inline errors | Phase 3 (frontend uses existing `paramSchema` validators) |
| `POST /science/runs` accepts overrides | Phase 2 |
| Overrides merged into `Run.graph` at creation | Phase 2 |
| Original protocol values preserved on the run | Phase 2 (`protocol_*` mirror fields) |
| Audit log entry on run creation records overrides | Phase 2 (`OVERRIDE_SET` per field) |
| `PUT /science/runs/{id}` allows updating overrides while PLANNED | Phase 2 (existing endpoint + new guard) |
| Returns 422 on `ACTIVE`/`COMPLETED`/`EDITED`/`ARCHIVED` | Phase 2 (new guard) |
| Edits append to AuditLog | Phase 2 (`OVERRIDE_EDIT` per field) |
| Run page displays overrides; PLANNED-editable | Phase 4 |
| API shape expresses N runs × M overrides without rework | Phase 2 (`RunOverrides.nodes` is sparse and per-run) |
| Optional `Run.parent_batch_id` for future grouping | Phase 2 (small migration) |
| Backend tests | Phase 2 |
| Frontend tests | Phases 3, 4 |
| Playwright e2e | Phases 3, 4 |
