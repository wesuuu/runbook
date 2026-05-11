# QA-0007 — Equipment ID interpolation in instruction generator

## Problem

The instruction generator only interpolates `{{param_name}}` placeholders. Users want to reference equipment assigned to a unit op via short, human-readable IDs in template text:

```
Set up the {{E-001_name}} ({{E-001_description}}) and calibrate using the {{E-002_name}}.
```

Today these tokens pass through as raw text because (a) the regex `\{\{(\w+)\}\}` doesn't match the hyphen and (b) there's no equipment resolver in the render pass. Unit op nodes also lack a stable short ID for each assigned equipment — `SelectedEquipment` only stores `{equipment_id: UUID, shareable: boolean}`.

## Goals

- Resolve `{{<local_id>_name}}` and `{{<local_id>_description}}` against equipment assigned anywhere in the protocol graph.
- Give the Inspector a way to assign and edit the short local ID per equipment, with uniqueness enforced within the protocol.
- Surface unresolved IDs as a warning to the caller while leaving the raw `{{...}}` in the rendered text (mirrors the existing behavior for unfilled params).
- No regression in current `{{param}}` interpolation.

## Non-goals

- No server-side uniqueness validation on save — the protocol JSONB is persisted as-is today, and adding a backend uniqueness check is broader than this fix. Client-side enforcement is sufficient for this iteration.
- No template-side syntax change. Sticking with `{{...}}` (not `{{equipment.E-001.name}}` or similar) keeps the user-facing surface flat and consistent with existing params.
- No retroactive migration of existing protocols — `local_id` is optional on the schema and only becomes required when the user wants to reference the equipment from a template. Existing equipment assignments keep working.

## Data shape

Extend `SelectedEquipment` (frontend Zod schema + the JSONB it serializes into):

```ts
SelectedEquipment {
  equipment_id: string;   // existing — Equipment UUID
  local_id?: string;      // NEW — short, unique-within-protocol, user-editable
  shareable: boolean;     // existing
}
```

`local_id` is optional. When the user adds an equipment item via the Inspector, the picker auto-suggests the next free `E-NNN` token (scanning all unit op nodes in the protocol graph, taking the max `\d+` suffix among `E-*` IDs, incrementing). The user can edit it inline. Uniqueness is validated across the whole graph; a duplicate blocks save with an inline field error.

## Backend interpolation

Two files carry the substitution logic today: `backend/app/services/documents/pdf_base.py` (the regex pass) and `backend/app/services/protocols/template_engine.py` (the per-step caller). The render function stays equipment-agnostic — the caller flattens equipment fields into the params dict before invoking it.

### `pdf_base._render_template`

- Signature: `_render_template(template, params) -> tuple[str, list[str]]` (only change is returning the unresolved-token list alongside the rendered text).
- Regex changes from `\{\{(\w+)\}\}` to `\{\{([A-Za-z][\w-]*)\}\}` so hyphens in `E-001` are matched.
- Resolution per match: token is a key in `params` and value is truthy/non-empty → substitute; otherwise leave literal `{{token}}` and add `token` to the unresolved list (deduped, order of first appearance).

### `template_engine`

Before each `_render_template` call, build a flat equipment-context dict and merge it into the params namespace passed to the renderer:

1. Walk the protocol graph once (including swimlane children), collect every `(local_id, equipment_id)` pair with a non-empty `local_id`.
2. Fetch the matching `Equipment` rows in one org-scoped query.
3. Build `equipment_context: dict[str, str]` like `{"E-001_name": "Sartorius Bioreactor", "E-001_description": "5L stirred-tank, …", "E-002_name": …, …}`.
4. Pass `{**equipment_context, **step_params}` as `params` to `_render_template`. Step params win on key collision so a deliberately-named `E-001_name` param could still override (edge case, but cheap to define).

If two assignments share a `local_id`, the first wins in the dict and the duplicate is logged + recorded as a render warning so the issue isn't hidden (defense in depth even though the frontend blocks duplicates).

Unresolved tokens are aggregated across all step renders for the protocol/run and returned in the response payload alongside the rendered document.

### API surface

The PDF/instructions generation response (already returned to the Inspector / PDF preview path) gains an `unresolved_placeholders: string[]` field. The frontend shows this in the same warning banner used by existing render-warning flows (the QA-0006 pattern already established a banner channel — we reuse it).

## Frontend Inspector

The equipment section already exists at `frontend/src/lib/components/protocol/Inspector.svelte` (~lines 373–405) and renders via `EquipmentChipList` + `EquipmentPickerModal`.

Changes:

- `EquipmentChipList`: each chip gains an inline editable `local_id` field (text input, ~6 chars wide) next to the equipment name. Default value comes from the suggester. On blur, validate uniqueness against the full protocol graph; mark the field invalid on collision.
- `EquipmentPickerModal`: when adding a new equipment row, populate `local_id` with the next-available `E-NNN`. User can edit before confirming.
- Template hint at Inspector.svelte ~line 301: extend the existing `Available: {{param_key}}` line so that when equipment is assigned to the current unit op, it also lists `{{<local_id>_name}}  {{<local_id>_description}}` for each.
- Save is blocked (existing `hasUnsavedChanges` + a new derived `hasLocalIdConflicts`) when any duplicate is present.

A small helper `lib/protocol/equipmentIds.ts`:
- `suggestNextLocalId(graph): string` — scans nodes, returns next `E-NNN`.
- `findLocalIdConflicts(graph): Map<localId, nodeIds[]>` — used by the Inspector validator and (optionally) by the protocol-level save guard.

## Warning surface

Unresolved placeholders flow back via the existing PDF/instructions response. The PDF preview and the run "Generate Instructions" flow both already render a warning banner for render issues (per QA-0006's `assert_no_<rule>_errors` channel). We append unresolved equipment IDs and unresolved params to that banner with the message "Unresolved template variables: E-009_name, my_missing_param".

## Tests (TDD)

### Backend unit (`backend/tests/unit/test_template_engine.py` + new cases)

- `{{E-001_name}}` resolves to `equipment.name`.
- `{{E-001_description}}` resolves to `equipment.description`.
- `{{E-009_name}}` (unassigned) stays as literal `{{E-009_name}}` and appears in the unresolved list.
- `{{my_param}}` continues to resolve from params (regression).
- Mixed template: params + equipment + unresolved all in one input, all three behaviors observed.
- Equipment-context builder walks nested swimlane children and produces flat `{<local_id>_name, <local_id>_description}` keys.
- Duplicate `local_id` across nodes: first wins in the dict, duplicate logged as warning.

### Frontend unit

- `suggestNextLocalId` returns `E-001` for empty graph, increments past highest existing `E-NNN`.
- `findLocalIdConflicts` returns `{}` for unique IDs, populated map for collisions.
- Inspector renders `{{E-001_name}}` and `{{E-001_description}}` in the hint line when one equipment item is assigned.
- Inspector blocks save when a duplicate `local_id` is entered.

### Browser (qa-verify)

- Add a unit op, assign one equipment item, confirm hint shows `{{E-001_name}}`.
- Author a step instruction using `{{E-001_name}} ({{E-001_description}})`.
- Generate / preview instructions, verify text reads `Sartorius Bioreactor (5L stirred-tank, single-use)` (or whatever the seeded equipment values are).
- Type `{{E-999_name}}` in a step, regenerate, verify warning banner lists `E-999_name` and the raw token stays in the doc.
- Existing `{{param}}` interpolation still works (smoke a known param step).

## Rollout & risk

- Pure additive: `local_id` is optional, new regex is a superset of the old one (every old token still matches), and unresolved behavior mirrors current behavior.
- No DB migration. `local_id` lives in the existing protocol-graph JSONB.
- No feature flag — risk is contained and the failure mode (token left literal) is the existing failure mode.
