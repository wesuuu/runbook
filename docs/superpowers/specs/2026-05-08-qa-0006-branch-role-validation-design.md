# QA-0006 — Hard-block save/run/PDF when branching nodes lack distinct role assignments

## Problem

A unit op node with multiple outgoing edges represents work that splits into parallel branches. Each branch must run as a distinct role; otherwise a single person would have to perform two steps simultaneously. The protocol editor surfaces a non-blocking yellow warning today but lets the user save, publish, run, and generate PDFs of an invalid graph. The ambiguity then leaks into runtime.

A second pre-existing bug compounds the issue: dragging a node between swimlanes does not update its `parentId`, so the existing warning fires on stale lane assignments and never clears. The user must be able to recover from the new hard-block by moving nodes; this fix is bundled.

## Out of Scope

- Subgraph-walk role comparison (we use immediate-target distinctness only — matches the task example).
- Subgraph-rollup time intervals (we use per-immediate-target intervals only).
- Blocking draft autosave (`saveDraft` / `?save_as_draft=true`). Drafts may legitimately be partial.
- Visual indicators on branch *target* nodes (we mark the source — the branching point — only).
- Rule UI on `processStart` nodes (rule applies to `unitOp` nodes only).

## Rule definition (single source of truth)

For each node `X` with `outDegree ≥ 2`:

1. Collect immediate target nodes (filter to `type === "unitOp"`).
2. Compute each target's `parentId`. The rule **fires (severity = "error")** if either:
   - Two or more targets share the same `parentId`, OR
   - Any target's `parentId` is `null` / `undefined`.
3. **Time-mode suppression**: when `graph.timeEnabled === true`, compute each immediate target's interval `[start_min, start_min + duration_min]`:
   - `start_min = position_axis / pixelsPerHour * 60` where `position_axis = layout === "horizontal" ? position.x : position.y`
   - `duration_min = data.duration_min ?? 30` (matches existing default in `totalHours`)
   - If every pair of intervals is disjoint (`a.end ≤ b.start || b.end ≤ a.start`), suppress the error. Otherwise, fire.

The rule applies identically on frontend and backend.

## Architecture

### Frontend

#### `protocolValidation.ts` — extend, don't fork

Every `BranchValidationError` is a hard-block error. No severity field — the type's existence implies blocking. Update `computeBranchValidationErrors`:

- Signature gains a third arg: `(nodes, edges, timeContext: { timeEnabled: boolean; pixelsPerHour: number; layout: "horizontal" | "vertical" })`.
- Same-lane detection unchanged (existing case).
- New case: any branch target with null `parentId` produces an error per branching source (`duplicateLane: null`, `targetNodeLabels` lists the unassigned targets).
- After detection, filter out errors that pass time-mode suppression (see Rule definition above).

Existing call site at `+page.svelte:357` updates to pass the time context.

#### Editor wiring (`+page.svelte`)

- Existing `branchInvalidNodeIds` derived already lists every offending source; reuse as-is.
- `setContext("branchValidation", ...)` unchanged in shape.
- Pre-flight in:
  - `saveAndPublish()` — if `branchValidationErrors().length > 0`, toast `"Cannot publish: <N> branching node(s) need distinct roles. See warnings."` and abort before the publish POST.
  - `openPdfPreview()` — same pre-flight, do not open drawer.
- `RunCreatorWizardModal.svelte` `createRun()` — same pre-flight. The modal already loads the protocol object (with `protocol.graph.nodes/edges/timeEnabled/pixelsPerHour/layout`); call `computeBranchValidationErrors` against that. Toast and abort if any error.

#### Per-node visual

`UnitOpNode.svelte` already reads `branchValidation.invalidNodeIds` and applies the existing amber `.invalid` ring to the offending source. Reuse as-is — no CSS changes. The behavior change (publish/run/PDF now blocked) is what makes the existing visual meaningful, not the color.

#### Inspector display

`Inspector.svelte`:

- New prop: `branchErrors: BranchValidationError[]` (a single branching node may have multiple errors — one per target group).
- When non-empty and selected node is the branching source, render a small red callout above the parameter form: one line per error, e.g. `"This step branches to <targets> in the same role — assign distinct roles, or enable time mode and stagger them."`
- Editor passes the matching errors from `branchValidationErrors()` filtered by `sourceNodeId === selectedNodeId`.

#### `ValidationBanners.svelte`

No styling changes. Existing amber banner is reused for branch errors. Inspector callout (next section) and the toast on save/publish/run/PDF carry the "this blocks publish" message.

#### Drag-stop reassignment fix (prerequisite bundled)

Add `onnodedragstop={handleNodeDragStop}` to the `<SvelteFlow>` element. The handler:

1. Receives the dragged node from the event.
2. Calls `findSwimLaneParent(nodes, node.position)` to determine which (if any) swimlane the new position falls inside.
3. If `result.parentId !== node.parentId`, push undo snapshot, update the node's `parentId`, and adjust position relative to the new parent (subtract parent's absolute position to keep the node's screen position stable, mirroring how `createUnitOpNode` handles `adjustedPosition`).
4. Re-assign `nodes` (full array reassignment) so `$derived` recomputes branch validation.

A small `reparentNode(nodes, nodeId, position)` helper goes in `protocolGraph.ts` for testability.

### Backend

#### `services/protocols/validation.py`

Add a new rule inside `validate_protocol_graph`:

```python
def _branch_role_issues(nodes, edges, graph) -> list[ValidationIssue]:
    # Build outgoing edge map.
    # For each unitOp node with ≥2 unitOp targets:
    #   collect parentIds; fire if any duplicate or any null;
    #   if graph.get("timeEnabled"), compute intervals from
    #   position-axis (per layout) / pixelsPerHour * 60 + duration_min;
    #   suppress when pairwise disjoint.
    ...
```

Issue shape: `severity="error"`, `code="branch_requires_distinct_roles"`, `node_id=<source>`, `message=f"Step '{label}' branches to {targets} which share or lack distinct role assignments. Assign each branch target to a different role, or enable time mode and stagger the branches."`

The `validate_protocol_graph` function signature is unchanged externally — `graph` already carries `timeEnabled`, `pixelsPerHour`, and `layout`.

#### Endpoint enforcement

Add a small helper in the validation module:

```python
def assert_no_branch_errors(graph, unit_ops) -> None:
    """Raise HTTPException(400) if branch_requires_distinct_roles fires."""
    result = validate_protocol_graph(graph, unit_ops)
    blocking = [i for i in result.issues
                if i.code == "branch_requires_distinct_roles"]
    if blocking:
        raise HTTPException(
            status_code=400,
            detail={"error": "branch_requires_distinct_roles",
                    "issues": [i.model_dump() for i in blocking]},
        )
```

Wired into:

- `POST /protocols/{id}/publish-draft` — `protocol_versions.py:413`. Validate the draft version's graph before flipping status.
- `POST /runs` — `runs.py:58`. Validate the resolved protocol's graph before creating the run.
- `GET /protocols/{id}/pdf/sop` and `GET /protocols/{id}/pdf/batch-record` — `protocol_pdfs.py:49, 103`. Validate before rendering.
- `POST /protocols/{id}/pdf/sop` and `POST /protocols/{id}/pdf/batch-record` — same module, lines 163 and 219. Same check.

`PUT /protocols/{id}` (with or without `save_as_draft=true`) is intentionally **not** gated — drafts must remain savable.

## Data flow

```
nodes/edges/timeContext (Svelte runes)
  ↓
computeBranchValidationErrors(nodes, edges, timeContext)
  ↓
branchValidationErrors  →  ValidationBanners (red banner UI)
                       →  branchInvalidNodeIds (red ring on source)
                       →  Inspector (per-node detail when source selected)
                       →  saveAndPublish / openPdfPreview / createRun (pre-flight, abort if any)
                       
Backend graph dict
  ↓
validate_protocol_graph(graph, unit_ops)
  ↓
ValidationResult.issues[code=branch_requires_distinct_roles]
  ↓
assert_no_branch_errors → 400 in publish-draft, /runs, /pdf/* endpoints
```

## Tests

### Frontend (`protocolValidation.test.ts` — new)

Cases:
- linear chain, no branching → no errors.
- branching with all distinct non-null parentIds → no errors.
- branching with two targets in same parentId → severity=error.
- branching with one null parentId target → severity=error.
- timeEnabled + horizontal layout + disjoint intervals on two same-lane branches → suppressed.
- timeEnabled + overlapping intervals on two same-lane branches → fires.
- timeEnabled + vertical layout + disjoint intervals → suppressed (axis check).
- nested branching (chain a→b→(c,d) where c→(e,f)) — both branching points evaluated independently.

### Frontend (`reparentNode` test in protocolGraph.test.ts or new file)

- node moved into a different swimlane → parentId updated, position adjusted relative to new parent.
- node moved out of all swimlanes → parentId cleared.
- node moved within same swimlane → parentId unchanged, position unchanged from input.

### Backend (`test_protocols_validation.py` — extend)

Cases:
- same-parentId branch targets → branch_requires_distinct_roles error.
- distinct-parentId branch targets → ok.
- null parentId branch target → error.
- timeEnabled + disjoint intervals → suppressed.
- timeEnabled + overlapping intervals → error.
- non-branching graphs → no error.

### Backend endpoint tests

- `POST /protocols/{id}/publish-draft` with branching graph that violates rule → 400.
- `POST /runs` against same protocol → 400.
- `GET /protocols/{id}/pdf/sop` against same protocol → 400.
- All four endpoints with valid graph → 200/201 as appropriate.

## Failure / edge cases

- **Branching point itself has no parentId**: rule still applies — only target parentIds matter.
- **Self-loop edges**: ignored; targets must be `unitOp` and not the source itself (not currently allowed by `isValidConnection`, but the validator doesn't assume).
- **Process Start as branch target**: filtered out at the rule level (only unitOp targets evaluated).
- **Branch into a deleted lane node**: `parentId` references a non-existent lane id. Treated as a real parentId for distinctness purposes (it's still a unique string), so won't false-positive. The orphaned-lane case is handled elsewhere.
- **Time mode with `duration_min === 0`**: zero-length interval. Two zero-length intervals at the same start_min are NOT disjoint → fires; at different start_min ARE disjoint → suppressed. Acceptable.
- **Concurrent draft edits**: not addressed (out of scope).
- **Pre-existing published protocols that violate the new rule**: deploying this change can retroactively block PDF generation and run-start for protocols that were valid before the rule existed but contain branching + same-role targets. Acceptable: the rule is correct in flagging them; the recovery path is creating a new draft and fixing the branching. Alternative considered (suppress the rule when status === "APPROVED" on the affected protocol) — rejected because it would let invalid published protocols continue being run.

## Migration

None — no schema or data migration. The change is pure validation logic plus UI wiring.

## Files touched

Frontend:
- `frontend/src/lib/components/protocol/protocolValidation.ts` — extend rule, add time-mode arg
- `frontend/src/lib/components/protocol/protocolGraph.ts` — add `reparentNode` helper
- `frontend/src/lib/components/protocol/Inspector.svelte` — branch-error callout for selected node
- `frontend/src/routes/protocols/[id]/+page.svelte` — pre-flight in publish/PDF, drag-stop handler, pass time context
- `frontend/src/lib/components/run/RunCreatorWizardModal.svelte` — pre-flight before createRun
- New: `frontend/src/lib/components/protocol/protocolValidation.test.ts`

(`UnitOpNode.svelte` and `ValidationBanners.svelte` are *not* touched — existing amber styling is reused.)

Backend:
- `backend/app/services/protocols/validation.py` — new rule + assert helper
- `backend/app/api/endpoints/protocol_versions.py` — gate publish-draft
- `backend/app/api/endpoints/runs.py` — gate /runs
- `backend/app/api/endpoints/protocol_pdfs.py` — gate four PDF endpoints
- `backend/tests/unit/test_protocols_validation.py` — new cases
- New / extend: integration tests for the four gated endpoints
