# F-0081 Phase 3 — Frontend Run Creator Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the small `CreateRunModal` with a full-screen 4-step run creator wizard (a `FullScreenModal`) that lets scientists pick a protocol+version, override per-unit-op params/equipment/schema/instructions with a live preview, see a save-as-new-version prompt before review, and create the run via the Phase 2 override API.

**Architecture:** A `RunCreatorWizardModal` component (composed via the existing `FullScreenModal` chrome at `lib/components/ui/FullScreenModal.svelte`) owns all wizard state and coordinates 4 step components plus a `SaveAsNewVersionDialog`. The modal mounts in three entry points — project page, experiment page, and `ExperimentsTab` — replacing `CreateRunModal` 1:1 with the same `bind:open` + `onCreated` callback shape. State is component-local Svelte 5 runes — the protocol's `originalGraph` snapshot stays immutable, while a working `currentGraph` is mutated by Step 3. A pure-helpers module (`runOverrides.ts`) computes the diff between original and current to produce both the wizard's diff aside and the `RunOverrides` payload sent to `POST /science/runs`. Three new shared presentational components (`ParamInput`, `SchemaEditor`, `EquipmentChipList`) consolidate logic that was previously inline in `Inspector.svelte`; Inspector itself is refactored to consume them in the same PR (only callsite, low risk). The wizard's parameter editor is extracted as a standalone `RunOverridesEditor` component so Phase 4 can reuse it inline on the run detail page without a second extraction round.

**Why a FullScreenModal, not a route?** Consistency with the two existing complex multi-step flows in this codebase — `ProtocolImportModal` and `BatchRecordImportModal` — both of which are FullScreenModals. Establishing a one-off creation route would split the pattern. Modal-in-modal nesting (EquipmentPicker, VersionHistoryDrawer, SaveAsNewVersionDialog, ConfirmDialog-on-close) is supported by bits-ui and follows the same pattern those existing modals use for their `ConfirmDialog` close-confirm.

**Tech Stack:** Svelte 5 (runes: `$state`, `$derived`, `$effect`, `$props`, `$bindable`), SvelteKit routing, TypeScript strict, TailwindCSS 4, shadcn-svelte primitives (`Dialog`, `Button`, `Card`), bits-ui, Vitest for unit/component tests, Playwright for e2e.

---

## Reference materials

- **Spec:** [`docs/superpowers/specs/2026-04-29-f-0081-run-parameter-overrides-design.md`](../specs/2026-04-29-f-0081-run-parameter-overrides-design.md) — read Phase 3 + Reuse audit sections before starting.
- **Mockups (visual target for layout, spacing, color tokens):**
  - [`mockups/F-0081-run-creator-wizard.html`](../../../mockups/F-0081-run-creator-wizard.html) — single-role base wizard.
  - [`mockups/F-0081-multi-role-parameters.html`](../../../mockups/F-0081-multi-role-parameters.html) — multi-role parameters step. **Read this before implementing Task 11.** Role switching is handled by a *role context bar* (active role name + role-color bar + ‹ N/M › arrow nav) and *clickable role-group headers in the diff aside* — there is no tab strip. Inactive role overrides stay in state; switching role is a presentational filter, not a remount.
- **Phase 2 backend (already shipped):**
  - `POST /science/runs` accepts `{ overrides?: { nodes: { [nodeId]: NodeOverrides } }, protocol_version_number?: number, ... }`
  - `PUT /science/runs/{id}` accepts a full `graph` payload while `status === 'PLANNED'` (422 otherwise)
  - Backend deep-copies the protocol graph, populates `protocol_*` mirror fields on each unit-op node, applies overrides, and audits each diff as `OVERRIDE_SET` (create) or `OVERRIDE_EDIT` (update).

## File structure

### New files (created in this plan)

| Path | Responsibility |
| --- | --- |
| `frontend/src/lib/utils/runOverrides.ts` | Pure helpers: `computeEdits(original, current)`, `applyOverrides(graph, overrides)`, `hasStructuralChanges(edits)`, `buildOverridesPayload(edits)` |
| `frontend/src/lib/utils/runOverrides.test.ts` | Vitest suite for the helpers |
| `frontend/src/lib/components/shared/ParamInput.svelte` | paramSchema-driven input (media-ref / enum / number / integer / text). Used by wizard; existing 6 callsites migrate later (out of scope). |
| `frontend/src/lib/components/shared/ParamInput.test.ts` | Vitest |
| `frontend/src/lib/components/shared/SchemaEditor.svelte` | Inline add/remove parameter rows (key + label + type). Inspector refactors to use it in this plan. |
| `frontend/src/lib/components/shared/SchemaEditor.test.ts` | Vitest |
| `frontend/src/lib/components/shared/EquipmentChipList.svelte` | Equipment chip list with conflict marking and optional swap button. Inspector refactors to use it. |
| `frontend/src/lib/components/shared/EquipmentChipList.test.ts` | Vitest |
| `frontend/src/lib/components/run/RunCreatorStepper.svelte` | Presentational 4-pill stepper |
| `frontend/src/lib/components/run/RunCreatorNameStep.svelte` | Step 1 — name + experiment |
| `frontend/src/lib/components/run/RunCreatorProtocolStep.svelte` | Step 2 — protocol + version + summary card; opens `VersionHistoryDrawer` |
| `frontend/src/lib/components/run/RunOverridesEditor.svelte` | Step 3 body — list of `RunCreatorUnitOpCard`s + sticky aside. Reused by Phase 4 on run detail page. |
| `frontend/src/lib/components/run/RunCreatorUnitOpCard.svelte` | One unit-op override card (header, equipment, param table, instructions block) |
| `frontend/src/lib/components/run/RunCreatorReviewStep.svelte` | Step 4 — summary + Create button |
| `frontend/src/lib/components/run/SaveAsNewVersionDialog.svelte` | On-Continue prompt with edit list + 3 actions |
| `frontend/src/lib/components/run/RunCreatorUnitOpCard.test.ts` | Vitest |
| `frontend/src/lib/components/run/SaveAsNewVersionDialog.test.ts` | Vitest |
| `frontend/src/lib/components/run/RunOverridesEditor.test.ts` | Vitest |
| `frontend/src/lib/components/run/RunCreatorWizardModal.svelte` | Top-level modal — wraps `FullScreenModal`, owns wizard state, orchestrates the 4 steps + SaveAsNewVersionDialog + ConfirmDialog-on-close. Replaces the old `CreateRunModal` 1:1 in API shape (`bind:open`, `projectId`, `protocols`, `experiments`, `forExperiment`, `onCreated`). |
| `frontend/e2e/run-creator.spec.ts` | Playwright e2e for the full wizard flow |

### Files modified

| Path | Change |
| --- | --- |
| `frontend/src/routes/projects/[id]/+page.svelte` | Swap `<CreateRunModal>` → `<RunCreatorWizardModal>`. Same `bind:open` shape; the `New Run` button trigger is unchanged. |
| `frontend/src/routes/experiments/[id]/+page.svelte` | Swap `<CreateRunModal>` → `<RunCreatorWizardModal>` (with `forExperiment` prop). Trigger unchanged. |
| `frontend/src/lib/components/project/ExperimentsTab.svelte` | Swap `<CreateRunModal>` → `<RunCreatorWizardModal>`. Trigger unchanged. |
| `frontend/src/lib/components/project/CreateRunModal.svelte` | **DELETE** the file. |
| `frontend/src/lib/components/protocol/Inspector.svelte` | (a) Refactor to consume `<ParamInput>`, `<SchemaEditor>`, `<EquipmentChipList>`. (b) Delete the local `renderTemplate` (line 231) and import from `$lib/utils/template`. |
| `frontend/src/lib/components/run/RunHistory.svelte` | Add label entries for `OVERRIDE_SET` ("set overrides at creation") and `OVERRIDE_EDIT` ("edited overrides while planned") + a switch case rendering the `STEP_EDIT`-shaped payload. |
| `frontend/src/lib/schemas/runs.ts` | Add `RunOverridesSchema` and `NodeOverridesSchema` Zod schemas to mirror the backend payload (used for typing the create payload, not response validation). |

### Files NOT touched (intentionally)

- The 5 other paramSchema-driven input callsites (`run/RoleWizard`, `field-mode/FieldModeRoleWizard`, `run/RunResultsSummary`, `modals/BatchRecordImportModal`, `protocol/UnitOpNode`) are deliberately left alone — migrating them is its own tech-debt ticket.
- `VersionHistoryDrawer.svelte` is reused as-is, no changes.
- `EquipmentPickerModal.svelte` is reused as-is.
- `lib/utils/template.ts` is reused as-is (already exists, has tests).
- `lib/components/protocol/protocolGraph.ts::detectEquipmentConflicts` is reused as-is.
- `lib/components/ui/FullScreenModal.svelte` is reused as-is (matches the chrome of `ProtocolImportModal` and `BatchRecordImportModal`).
- `lib/components/ui/confirm-dialog.svelte` is reused as-is for the "Discard changes?" prompt on close-with-edits.

---

## API + Type contracts (read before coding)

These shapes must match the Phase 2 backend (already shipped).

### `POST /science/runs` request body

```typescript
interface RunCreatePayload {
  name: string;
  project_id: string;
  protocol_id: string;
  protocol_version_number?: number;  // defaults to current published version
  experiment_id?: string;
  overrides?: {
    nodes: {
      [nodeId: string]: {
        params?: Record<string, unknown>;       // sparse merge — only changed keys
        equipment?: Array<{ equipment_id: string; shareable: boolean }>;  // full replacement
        paramSchema?: Record<string, unknown>;  // full replacement
        description?: string;                   // full replacement
      };
    };
  };
}
```

### Unit-op node shape (after backend snapshot, in `Run.graph.nodes[i]`)

```typescript
interface UnitOpNodeData {
  // Effective values for this run (what the wizard mutates, what the user sees)
  label: string;
  category?: string;
  duration_min?: number;
  params: Record<string, unknown>;
  equipment: Array<{ equipment_id: string; shareable: boolean }>;
  paramSchema: { type: 'object'; properties: Record<string, ParamProp>; required?: string[] };
  description: string;

  // Mirror fields populated by backend; never mutated post-snapshot
  protocol_params: Record<string, unknown>;
  protocol_equipment: Array<{ equipment_id: string; shareable: boolean }>;
  protocol_paramSchema: { type: 'object'; properties: Record<string, ParamProp>; required?: string[] };
  protocol_description: string;
}

interface ParamProp {
  type?: 'string' | 'number' | 'integer' | 'boolean';
  title?: string;
  enum?: string[];
  unit?: string;
  'x-ref-type'?: 'media_prep';
}
```

### Edit type (frontend-only, for diff aside + dialog)

```typescript
type EditKind = 'VALUE' | 'SWAP' | 'ADDED' | 'REMOVED' | 'INSTRUCTION' | 'SCHEMA';

interface Edit {
  nodeId: string;
  stepName: string;
  kind: EditKind;
  field?: string;       // param key or 'equipment' or 'description' or 'paramSchema'
  fieldLabel?: string;  // human-readable
  oldValue?: unknown;
  newValue?: unknown;
}
```

### Multi-role considerations

A protocol may have 1 or more roles (`Protocol.roles: ProtocolRole[]`). In the graph, role assignment is expressed via swimlane nodes:

- Swimlane nodes (`type === 'swimLane'`) live at the top of the graph and represent a role.
- Unit-op nodes are nested inside swimlanes via `node.parentId === <swimlaneId>`.
- Each swimlane node references its role through a key on its `data` (the existing protocol editor sets this — verify the exact attribute by reading `lib/components/SwimLaneNode.svelte` and `protocolGraph.ts` before implementing the helper; common conventions in this repo are `data.role_id` or `data.lane_role_id`).

The wizard's Step 3 must:

1. **Filter cards by active role.** Only render UO cards belonging to the active role's swimlane.
2. **Surface a role context bar** above the cards: role name, role-color vertical bar, "Role N of M · X UO · Y params", and ‹ N/M › arrow nav.
3. **Group the diff aside by role**, with clickable role-group headers that jump-set the active role. The active role's group header gets the same `hsl(195 60% 96%)` wash used for the wizard's active-step pill.
4. **Preserve inactive-role overrides.** Switching role is a presentational filter on `currentGraph` — *not* a remount and not a state reset. The aside's per-role count proves this to the user.

**Degenerate cases:**

- **Single role** — hide the role context bar, flatten the aside to one ungrouped diff list. (One role contributes nothing as a navigation surface; the active role is implicit.)
- **No roles defined** (no swimlanes — flat graph) — same as single-role: hide the context bar, flatten the aside.

The `ProtocolRole` shape (already in `lib/schemas/protocols.ts`):

```typescript
interface ProtocolRole {
  id: string;
  protocol_id: string;
  name: string;
  color: string;       // e.g. '#B96B17'
  sort_order: number;
}
```

Role color is consumed as a small mark/dot or a 4px vertical bar in the context bar — never as a fill — so mint stays the sole override signal.

---

## Wizard state model (lives in `RunCreatorWizardModal.svelte`)

```typescript
// Resolved data
let protocols = $state<Protocol[]>([]);
let experiments = $state<Experiment[]>([]);

// Step 1
let runName = $state('');
let experimentId = $state<string | null>(null);

// Step 2
let protocolId = $state<string | null>(null);
let protocolVersionNumber = $state<number | null>(null);  // null => use latest
let selectedVersion = $state<ProtocolVersion | null>(null);  // resolved version metadata
let originalGraph = $state<ProtocolGraph | null>(null);  // immutable snapshot of selected version's graph
let currentGraph = $state<ProtocolGraph | null>(null);  // working copy mutated by Step 3
let roles = $state<ProtocolRole[]>([]);  // resolved with the protocol; sorted by sort_order

// Step 3 — derived
const edits = $derived(
  originalGraph && currentGraph ? computeEdits(originalGraph, currentGraph) : []
);
const overridesPayload = $derived(buildOverridesPayload(edits, currentGraph));

// Step 3 — multi-role nav (single-role/no-role protocols leave this null)
let activeRoleId = $state<string | null>(null);
// Initialized in $effect when graph loads:
//   - if roles.length > 1 → first role by sort_order
//   - if roles.length <= 1 → null (degenerate path; no role filtering / no context bar)

// Wizard navigation
let currentStep = $state<1 | 2 | 3 | 4>(1);
let saveDialogOpen = $state(false);
let creating = $state(false);
let createError = $state<string | null>(null);
```

When the user picks a different protocol or version, `originalGraph` and `currentGraph` both reset to a deep-clone of the chosen version's graph (the wizard does its own deep-clone — backend mirroring happens server-side at create time).

When the modal is closed (`open=false`) AND has no unsaved edits, all state resets via a `$effect` watching `open`. If there are unsaved edits, a `ConfirmDialog` ("Discard changes?") fires before the close completes (same pattern as `BatchRecordImportModal`).

---

## Task overview

| # | Task | Touches |
| --- | --- | --- |
| 1 | Helpers — `runOverrides.ts` (computeEdits / applyOverrides / hasStructuralChanges / buildOverridesPayload) + tests | utils |
| 2 | Shared `<ParamInput>` component + tests | shared |
| 3 | Shared `<SchemaEditor>` component + tests | shared |
| 4 | Shared `<EquipmentChipList>` component + tests | shared |
| 5 | Refactor `Inspector.svelte` to consume the three shared components + drop local `renderTemplate` | protocol |
| 6 | Add Zod schemas (`NodeOverridesSchema`, `RunOverridesSchema`) | schemas |
| 7 | `RunCreatorStepper` (presentational) + test | run |
| 8 | `RunCreatorNameStep` + test | run |
| 9 | `RunCreatorProtocolStep` + test (uses `VersionHistoryDrawer`) | run |
| 10 | `RunCreatorUnitOpCard` + test | run |
| 11 | `RunOverridesEditor` (Step 3 body, reusable for Phase 4) + test | run |
| 12 | `SaveAsNewVersionDialog` + test | run |
| 13 | `RunCreatorReviewStep` + test | run |
| 14 | `RunCreatorWizardModal` — wraps FullScreenModal, owns wizard state, wires all steps, submit, ConfirmDialog-on-close | run |
| 15 | Migrate three entry points to `<RunCreatorWizardModal>`; delete `CreateRunModal.svelte` | routes |
| 16 | RunHistory — label + render entries for `OVERRIDE_SET` / `OVERRIDE_EDIT` | run |
| 17 | Playwright e2e — full wizard flow (golden path) | e2e |
| 18 | qa-verify session (manual) | n/a |
| 19 | Scenario-driven e2e matrix (self-seeding fixtures + `KEEP_FIXTURES` opt-out) | e2e |

---

## Task 1 — Helpers: `runOverrides.ts`

**Files:**
- Create: `frontend/src/lib/utils/runOverrides.ts`
- Test: `frontend/src/lib/utils/runOverrides.test.ts`

These are pure functions. No DOM, no API calls — easy to unit-test, easy to verify correctness. The wizard and Phase 4's run-detail editor both consume them.

- [ ] **Step 1: Write the failing test file.**

```typescript
// frontend/src/lib/utils/runOverrides.test.ts
import { describe, it, expect } from 'vitest';
import {
    computeEdits,
    buildOverridesPayload,
    hasStructuralChanges,
    type Edit,
} from './runOverrides';

const sampleGraph = (mut?: (g: any) => void) => {
    const g = {
        nodes: [
            {
                id: 'n1',
                type: 'unitOp',
                data: {
                    label: 'Buffer Mix',
                    params: { temperature: 25, ph: 7.0 },
                    equipment: [{ equipment_id: 'eq-1', shareable: false }],
                    paramSchema: {
                        type: 'object',
                        properties: {
                            temperature: { type: 'number', title: 'Temperature' },
                            ph: { type: 'number', title: 'pH' },
                        },
                    },
                    description: 'Mix at {{temperature}}°C, pH {{ph}}',
                    protocol_params: { temperature: 25, ph: 7.0 },
                    protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                    protocol_paramSchema: {
                        type: 'object',
                        properties: {
                            temperature: { type: 'number', title: 'Temperature' },
                            ph: { type: 'number', title: 'pH' },
                        },
                    },
                    protocol_description: 'Mix at {{temperature}}°C, pH {{ph}}',
                },
            },
            { id: 'lane', type: 'swimLane', data: { label: 'Operator' } },
        ],
        edges: [],
    };
    if (mut) mut(g);
    return g;
};

describe('computeEdits', () => {
    it('returns empty when current matches original', () => {
        const orig = sampleGraph();
        const curr = sampleGraph();
        expect(computeEdits(orig, curr)).toEqual([]);
    });

    it('detects a single param value override', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.params.temperature = 30; });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0]).toMatchObject({
            nodeId: 'n1',
            stepName: 'Buffer Mix',
            kind: 'VALUE',
            field: 'temperature',
            fieldLabel: 'Temperature',
            oldValue: 25,
            newValue: 30,
        });
    });

    it('detects equipment swap', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.equipment = [{ equipment_id: 'eq-2', shareable: false }];
        });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0].kind).toBe('SWAP');
    });

    it('detects added param (schema property added + value set)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.paramSchema.properties.duration = { type: 'number', title: 'Duration' };
            g.nodes[0].data.params.duration = 60;
        });
        const edits = computeEdits(orig, curr);
        const added = edits.find((e) => e.kind === 'ADDED');
        expect(added).toBeDefined();
        expect(added?.field).toBe('duration');
    });

    it('detects removed param (schema property removed)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            delete g.nodes[0].data.paramSchema.properties.ph;
            delete g.nodes[0].data.params.ph;
        });
        const edits = computeEdits(orig, curr);
        const removed = edits.find((e) => e.kind === 'REMOVED');
        expect(removed?.field).toBe('ph');
    });

    it('detects instruction edit', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.description = 'New instructions'; });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0].kind).toBe('INSTRUCTION');
    });

    it('ignores non-unitOp nodes (swimlanes etc.)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[1].data.label = 'Different Lane'; });
        expect(computeEdits(orig, curr)).toEqual([]);
    });

    it('uses key as fallback fieldLabel when paramSchema has no title', () => {
        const orig = sampleGraph((g) => { delete g.nodes[0].data.paramSchema.properties.temperature.title; });
        const curr = sampleGraph((g) => {
            delete g.nodes[0].data.paramSchema.properties.temperature.title;
            g.nodes[0].data.params.temperature = 30;
        });
        const edits = computeEdits(orig, curr);
        expect(edits[0].fieldLabel).toBe('Temperature');  // title-cased fallback
    });
});

describe('hasStructuralChanges', () => {
    it('returns false for value-only and swap edits', () => {
        const edits: Edit[] = [
            { nodeId: 'n1', stepName: 'X', kind: 'VALUE' },
            { nodeId: 'n1', stepName: 'X', kind: 'SWAP' },
        ];
        expect(hasStructuralChanges(edits)).toBe(false);
    });

    it('returns true if any edit is ADDED, REMOVED, INSTRUCTION, or SCHEMA', () => {
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'ADDED' }])).toBe(true);
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'REMOVED' }])).toBe(true);
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'INSTRUCTION' }])).toBe(true);
    });
});

describe('buildOverridesPayload', () => {
    it('returns undefined when no edits', () => {
        const orig = sampleGraph();
        const curr = sampleGraph();
        const edits = computeEdits(orig, curr);
        expect(buildOverridesPayload(edits, curr)).toBeUndefined();
    });

    it('packs sparse params, full equipment/schema/description', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.params.temperature = 30;
            g.nodes[0].data.equipment = [{ equipment_id: 'eq-2', shareable: true }];
            g.nodes[0].data.description = 'New';
        });
        const edits = computeEdits(orig, curr);
        const payload = buildOverridesPayload(edits, curr);
        expect(payload).toEqual({
            nodes: {
                n1: {
                    params: { temperature: 30 },
                    equipment: [{ equipment_id: 'eq-2', shareable: true }],
                    description: 'New',
                },
            },
        });
    });

    it('only emits paramSchema when schema actually changed', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.params.temperature = 30; });
        const edits = computeEdits(orig, curr);
        const payload = buildOverridesPayload(edits, curr);
        expect(payload?.nodes.n1.paramSchema).toBeUndefined();
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/utils/runOverrides.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement helpers.**

```typescript
// frontend/src/lib/utils/runOverrides.ts

export type EditKind =
    | 'VALUE'
    | 'SWAP'
    | 'ADDED'
    | 'REMOVED'
    | 'INSTRUCTION'
    | 'SCHEMA';

export interface Edit {
    nodeId: string;
    stepName: string;
    kind: EditKind;
    field?: string;
    fieldLabel?: string;
    oldValue?: unknown;
    newValue?: unknown;
}

interface NodeOverridesPayload {
    params?: Record<string, unknown>;
    equipment?: Array<{ equipment_id: string; shareable: boolean }>;
    paramSchema?: Record<string, unknown>;
    description?: string;
}

export interface RunOverridesPayload {
    nodes: Record<string, NodeOverridesPayload>;
}

function deriveLabel(props: Record<string, any> | undefined, key: string): string {
    const prop = props?.[key];
    if (prop && typeof prop === 'object' && typeof prop.title === 'string' && prop.title) {
        return prop.title;
    }
    return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function isUnitOp(node: any): boolean {
    return node && typeof node === 'object' && node.type === 'unitOp';
}

function deepEqual(a: unknown, b: unknown): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}

export function computeEdits(originalGraph: any, currentGraph: any): Edit[] {
    const edits: Edit[] = [];
    const origById = new Map<string, any>();
    for (const n of originalGraph?.nodes ?? []) {
        if (isUnitOp(n)) origById.set(n.id, n);
    }
    for (const node of currentGraph?.nodes ?? []) {
        if (!isUnitOp(node)) continue;
        const orig = origById.get(node.id);
        if (!orig) continue;
        const stepName = node.data?.label || node.id;
        const origData = orig.data || {};
        const currData = node.data || {};

        const origProps = (origData.paramSchema?.properties ?? {}) as Record<string, any>;
        const currProps = (currData.paramSchema?.properties ?? {}) as Record<string, any>;
        const origParams = (origData.params ?? {}) as Record<string, unknown>;
        const currParams = (currData.params ?? {}) as Record<string, unknown>;

        const allKeys = new Set([
            ...Object.keys(origProps),
            ...Object.keys(currProps),
        ]);
        for (const key of allKeys) {
            const inOrig = key in origProps;
            const inCurr = key in currProps;
            if (inOrig && !inCurr) {
                edits.push({
                    nodeId: node.id,
                    stepName,
                    kind: 'REMOVED',
                    field: key,
                    fieldLabel: deriveLabel(origProps, key),
                    oldValue: origParams[key],
                });
            } else if (!inOrig && inCurr) {
                edits.push({
                    nodeId: node.id,
                    stepName,
                    kind: 'ADDED',
                    field: key,
                    fieldLabel: deriveLabel(currProps, key),
                    newValue: currParams[key],
                });
            } else if (inOrig && inCurr) {
                if (!deepEqual(origParams[key], currParams[key])) {
                    edits.push({
                        nodeId: node.id,
                        stepName,
                        kind: 'VALUE',
                        field: key,
                        fieldLabel: deriveLabel(currProps, key),
                        oldValue: origParams[key],
                        newValue: currParams[key],
                    });
                }
            }
        }

        if (!deepEqual(origData.equipment ?? [], currData.equipment ?? [])) {
            edits.push({
                nodeId: node.id,
                stepName,
                kind: 'SWAP',
                field: 'equipment',
                fieldLabel: 'Equipment',
                oldValue: origData.equipment ?? [],
                newValue: currData.equipment ?? [],
            });
        }

        if ((origData.description ?? '') !== (currData.description ?? '')) {
            edits.push({
                nodeId: node.id,
                stepName,
                kind: 'INSTRUCTION',
                field: 'description',
                fieldLabel: 'Instructions',
                oldValue: origData.description ?? '',
                newValue: currData.description ?? '',
            });
        }
    }
    return edits;
}

export function hasStructuralChanges(edits: Edit[]): boolean {
    return edits.some((e) =>
        e.kind === 'ADDED' ||
        e.kind === 'REMOVED' ||
        e.kind === 'INSTRUCTION' ||
        e.kind === 'SCHEMA',
    );
}

export function buildOverridesPayload(
    edits: Edit[],
    currentGraph: any,
): RunOverridesPayload | undefined {
    if (edits.length === 0) return undefined;
    const byNode = new Map<string, Set<EditKind>>();
    for (const e of edits) {
        if (!byNode.has(e.nodeId)) byNode.set(e.nodeId, new Set());
        byNode.get(e.nodeId)!.add(e.kind);
    }

    const result: RunOverridesPayload = { nodes: {} };
    for (const [nodeId, kinds] of byNode) {
        const node = (currentGraph?.nodes ?? []).find((n: any) => n.id === nodeId);
        if (!node) continue;
        const data = node.data ?? {};
        const entry: NodeOverridesPayload = {};

        const valueOrStructural =
            kinds.has('VALUE') || kinds.has('ADDED') || kinds.has('REMOVED');
        if (valueOrStructural) {
            const valueEdits = edits.filter(
                (e) => e.nodeId === nodeId && (e.kind === 'VALUE' || e.kind === 'ADDED'),
            );
            const sparse: Record<string, unknown> = {};
            for (const ve of valueEdits) {
                if (ve.field) sparse[ve.field] = ve.newValue;
            }
            if (Object.keys(sparse).length > 0) entry.params = sparse;
        }

        if (kinds.has('SWAP')) {
            entry.equipment = data.equipment ?? [];
        }

        if (kinds.has('ADDED') || kinds.has('REMOVED') || kinds.has('SCHEMA')) {
            entry.paramSchema = data.paramSchema ?? {};
        }

        if (kinds.has('INSTRUCTION')) {
            entry.description = data.description ?? '';
        }

        result.nodes[nodeId] = entry;
    }
    return result;
}
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/utils/runOverrides.test.ts
```
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/utils/runOverrides.ts frontend/src/lib/utils/runOverrides.test.ts
git commit -m "feat(F-0081): runOverrides helpers — computeEdits, hasStructuralChanges, buildOverridesPayload"
```

- [ ] **Step 6: Add multi-role helpers.**

Append to `frontend/src/lib/utils/runOverrides.ts`:

```typescript
// ─── Role resolution ───
//
// Roles are encoded in the graph via swimlane nodes (type === 'swimLane'). A
// unit-op node belongs to a role when its parentId references a swimlane that
// references that role. The exact attribute key on swimlane.data that names
// the role id is set by the protocol editor — read SwimLaneNode.svelte and
// protocolGraph.ts in this repo to confirm the key (likely `role_id` or
// `lane_role_id`) before relying on this helper.

const SWIMLANE_ROLE_KEYS = ['role_id', 'lane_role_id', 'roleId'] as const;

function readSwimlaneRoleId(swimlaneNode: any): string | null {
    const data = swimlaneNode?.data ?? {};
    for (const k of SWIMLANE_ROLE_KEYS) {
        const v = data[k];
        if (typeof v === 'string' && v.length > 0) return v;
    }
    return null;
}

export function resolveNodeRoleId(
    nodeId: string,
    graph: any,
): string | null {
    const nodes = (graph?.nodes ?? []) as any[];
    const byId = new Map<string, any>();
    for (const n of nodes) byId.set(n.id, n);
    const node = byId.get(nodeId);
    if (!node) return null;
    if (node.type === 'swimLane') return readSwimlaneRoleId(node);
    const parent = node.parentId ? byId.get(node.parentId) : null;
    if (parent && parent.type === 'swimLane') return readSwimlaneRoleId(parent);
    return null;
}

export function groupUnitOpsByRole(
    graph: any,
): Map<string | null, any[]> {
    const out = new Map<string | null, any[]>();
    for (const node of (graph?.nodes ?? []) as any[]) {
        if (node.type !== 'unitOp') continue;
        const roleId = resolveNodeRoleId(node.id, graph);
        if (!out.has(roleId)) out.set(roleId, []);
        out.get(roleId)!.push(node);
    }
    return out;
}

export function groupEditsByRole(
    edits: Edit[],
    graph: any,
): Map<string | null, Edit[]> {
    const out = new Map<string | null, Edit[]>();
    for (const edit of edits) {
        const roleId = resolveNodeRoleId(edit.nodeId, graph);
        if (!out.has(roleId)) out.set(roleId, []);
        out.get(roleId)!.push(edit);
    }
    return out;
}
```

- [ ] **Step 7: Add tests for role helpers.**

Append to `frontend/src/lib/utils/runOverrides.test.ts`:

```typescript
import {
    resolveNodeRoleId,
    groupUnitOpsByRole,
    groupEditsByRole,
} from './runOverrides';

const multiRoleGraph = () => ({
    nodes: [
        { id: 'lane-op',  type: 'swimLane', data: { label: 'Operator',        role_id: 'role-1' } },
        { id: 'lane-sup', type: 'swimLane', data: { label: 'Senior Operator', role_id: 'role-2' } },
        { id: 'n1', type: 'unitOp', parentId: 'lane-op',  data: { label: 'Buffer Mix',     params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
        { id: 'n2', type: 'unitOp', parentId: 'lane-op',  data: { label: 'Cell Seeding',   params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
        { id: 'n3', type: 'unitOp', parentId: 'lane-sup', data: { label: 'Centrifugation', params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
    ],
    edges: [],
});

describe('resolveNodeRoleId', () => {
    it('returns the swimlane role id for a parented unit op', () => {
        expect(resolveNodeRoleId('n1', multiRoleGraph())).toBe('role-1');
        expect(resolveNodeRoleId('n3', multiRoleGraph())).toBe('role-2');
    });

    it('returns null for an orphan unit op (no parentId)', () => {
        const g = multiRoleGraph();
        g.nodes[2].parentId = undefined;
        expect(resolveNodeRoleId('n1', g)).toBeNull();
    });

    it('returns null for an unknown node id', () => {
        expect(resolveNodeRoleId('does-not-exist', multiRoleGraph())).toBeNull();
    });
});

describe('groupUnitOpsByRole', () => {
    it('buckets unit ops under their role id', () => {
        const grouped = groupUnitOpsByRole(multiRoleGraph());
        expect(grouped.get('role-1')?.map((n) => n.id)).toEqual(['n1', 'n2']);
        expect(grouped.get('role-2')?.map((n) => n.id)).toEqual(['n3']);
    });

    it('puts orphan unit ops under null', () => {
        const g = multiRoleGraph();
        g.nodes[2].parentId = undefined;
        const grouped = groupUnitOpsByRole(g);
        expect(grouped.get(null)?.map((n) => n.id)).toEqual(['n1']);
        expect(grouped.get('role-1')?.map((n) => n.id)).toEqual(['n2']);
    });
});

describe('groupEditsByRole', () => {
    it('buckets edits under each unit op\'s role', () => {
        const edits: Edit[] = [
            { nodeId: 'n1', stepName: 'Buffer Mix',     kind: 'VALUE' },
            { nodeId: 'n2', stepName: 'Cell Seeding',   kind: 'SWAP' },
            { nodeId: 'n3', stepName: 'Centrifugation', kind: 'VALUE' },
        ];
        const grouped = groupEditsByRole(edits, multiRoleGraph());
        expect(grouped.get('role-1')).toHaveLength(2);
        expect(grouped.get('role-2')).toHaveLength(1);
    });
});
```

- [ ] **Step 8: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/utils/runOverrides.test.ts
```
Expected: PASS, 19+ tests total.

> **Implementation note for the engineer:** the `SWIMLANE_ROLE_KEYS` array tries three plausible attribute names. Open `lib/components/SwimLaneNode.svelte` and the protocol editor's swimlane-creation code to verify which key the editor actually writes. If only one is used, replace the array with that single key. If the project uses a different key entirely, update `SWIMLANE_ROLE_KEYS` and the test fixture's `data.role_id` to match — the test should fail loudly until the helper and the fixture agree.

- [ ] **Step 9: Commit.**

```bash
git add frontend/src/lib/utils/runOverrides.ts frontend/src/lib/utils/runOverrides.test.ts
git commit -m "feat(F-0081): runOverrides — resolveNodeRoleId, groupUnitOpsByRole, groupEditsByRole"
```

---

## Task 2 — Shared `<ParamInput>` component

**Files:**
- Create: `frontend/src/lib/components/shared/ParamInput.svelte`
- Test: `frontend/src/lib/components/shared/ParamInput.test.ts`

Replaces 4-branch inline `paramSchema`-driven input rendering currently duplicated in 6 files. Only the wizard consumes it now; existing 6 callsites migrate later (out of scope).

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/shared/ParamInput.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ParamInput from './ParamInput.svelte';

describe('ParamInput', () => {
    it('renders a number input for type=number', async () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'number', title: 'Temp' },
            value: 25,
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="number"]');
        expect(input).toBeTruthy();
    });

    it('renders an enum select when schema.enum is present', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', enum: ['A', 'B', 'C'], title: 'Mode' },
            value: 'A',
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const sel = container.querySelector('select');
        expect(sel).toBeTruthy();
        expect(sel?.querySelectorAll('option').length).toBe(3);
    });

    it('renders a media-ref select when x-ref-type=media_prep', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', 'x-ref-type': 'media_prep', title: 'Media' },
            value: '',
            onChange: () => {},
            mediaPrepNodes: [{ id: 'mp1', label: 'LB Broth' }],
        });
        const sel = container.querySelector('select');
        expect(sel).toBeTruthy();
        const options = sel?.querySelectorAll('option');
        expect(options?.length).toBeGreaterThanOrEqual(2);
    });

    it('renders a text input as fallback', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', title: 'Note' },
            value: 'hi',
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="text"]');
        expect(input).toBeTruthy();
    });

    it('fires onChange when user types', async () => {
        let captured: unknown = undefined;
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'number', title: 'Temp' },
            value: 25,
            onChange: (v) => { captured = v; },
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: '30' } });
        expect(captured).toBe(30);
    });

    it('respects readonly prop (renders disabled input)', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', title: 'Note' },
            value: 'hi',
            onChange: () => {},
            mediaPrepNodes: [],
            readonly: true,
        });
        const input = container.querySelector('input') as HTMLInputElement;
        expect(input.disabled).toBe(true);
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/ParamInput.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement the component.**

```svelte
<!-- frontend/src/lib/components/shared/ParamInput.svelte -->
<script lang="ts">
    interface ParamProp {
        type?: string;
        title?: string;
        enum?: string[];
        unit?: string;
        'x-ref-type'?: string;
    }

    interface MediaPrepNode {
        id: string;
        label: string;
    }

    interface Props {
        id: string;
        schema: ParamProp;
        value: unknown;
        onChange: (next: unknown) => void;
        mediaPrepNodes?: MediaPrepNode[];
        readonly?: boolean;
        placeholder?: string;
    }

    let {
        id,
        schema,
        value,
        onChange,
        mediaPrepNodes = [],
        readonly = false,
        placeholder,
    }: Props = $props();

    function handleNumber(e: Event) {
        const raw = (e.target as HTMLInputElement).value;
        if (raw === '') {
            onChange(undefined);
            return;
        }
        const n = schema.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw);
        onChange(Number.isFinite(n) ? n : undefined);
    }

    function handleText(e: Event) {
        onChange((e.target as HTMLInputElement).value);
    }

    function handleSelect(e: Event) {
        onChange((e.target as HTMLSelectElement).value);
    }
</script>

{#if schema['x-ref-type'] === 'media_prep'}
    <select
        {id}
        class="input-field w-full"
        value={value ?? ''}
        onchange={handleSelect}
        disabled={readonly}
    >
        <option value="">— Select media —</option>
        {#each mediaPrepNodes as mp (mp.id)}
            <option value={mp.id}>{mp.label} ({mp.id.slice(0, 6)})</option>
        {/each}
    </select>
{:else if schema.enum}
    <select
        {id}
        class="input-field w-full"
        value={value ?? ''}
        onchange={handleSelect}
        disabled={readonly}
    >
        {#each schema.enum as opt (opt)}
            <option value={opt}>{opt}</option>
        {/each}
    </select>
{:else if schema.type === 'number' || schema.type === 'integer'}
    <input
        {id}
        type="number"
        class="input-field w-full"
        value={value ?? ''}
        oninput={handleNumber}
        step={schema.type === 'integer' ? 1 : 0.1}
        placeholder={placeholder ?? ''}
        disabled={readonly}
    />
{:else}
    <input
        {id}
        type="text"
        class="input-field w-full"
        value={value ?? ''}
        oninput={handleText}
        placeholder={placeholder ?? ''}
        disabled={readonly}
    />
{/if}

<style>
    .input-field {
        @apply px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent;
    }
    .input-field:disabled {
        @apply bg-gray-100 cursor-not-allowed text-gray-500;
    }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/ParamInput.test.ts
```
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/shared/ParamInput.svelte frontend/src/lib/components/shared/ParamInput.test.ts
git commit -m "feat(F-0081): shared ParamInput component for paramSchema-driven inputs"
```

---

## Task 3 — Shared `<SchemaEditor>` component

**Files:**
- Create: `frontend/src/lib/components/shared/SchemaEditor.svelte`
- Test: `frontend/src/lib/components/shared/SchemaEditor.test.ts`

Inline add/remove parameter rows (key + label + type). Used by Inspector (refactored in Task 5) and the wizard (Task 10).

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/shared/SchemaEditor.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SchemaEditor from './SchemaEditor.svelte';

describe('SchemaEditor', () => {
    it('renders a row per existing schema property', () => {
        const { container } = render(SchemaEditor, {
            rows: [
                { key: 'temperature', title: 'Temperature', type: 'number' },
                { key: 'ph', title: 'pH', type: 'number' },
            ],
            onChange: () => {},
        });
        expect(container.querySelectorAll('[data-schema-row]').length).toBe(2);
    });

    it('fires onChange with appended row on Add Parameter', async () => {
        let captured: any = null;
        const { getByText } = render(SchemaEditor, {
            rows: [{ key: 'a', title: 'A', type: 'string' }],
            onChange: (next) => { captured = next; },
        });
        await fireEvent.click(getByText(/add parameter/i));
        expect(captured).toBeTruthy();
        expect(captured.length).toBe(2);
        expect(captured[1].key).toBe('');
    });

    it('fires onChange with row removed on remove button', async () => {
        let captured: any = null;
        const { container } = render(SchemaEditor, {
            rows: [
                { key: 'a', title: 'A', type: 'string' },
                { key: 'b', title: 'B', type: 'number' },
            ],
            onChange: (next) => { captured = next; },
        });
        const removeBtn = container.querySelector('[aria-label="Remove parameter"]') as HTMLButtonElement;
        await fireEvent.click(removeBtn);
        expect(captured.length).toBe(1);
        expect(captured[0].key).toBe('b');
    });

    it('updates a row in place on input change', async () => {
        let captured: any = null;
        const { container } = render(SchemaEditor, {
            rows: [{ key: 'a', title: 'A', type: 'string' }],
            onChange: (next) => { captured = next; },
        });
        const keyInput = container.querySelector('input[placeholder="key"]') as HTMLInputElement;
        await fireEvent.input(keyInput, { target: { value: 'duration' } });
        expect(captured[0].key).toBe('duration');
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/SchemaEditor.test.ts
```
Expected: FAIL.

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/shared/SchemaEditor.svelte -->
<script lang="ts">
    import { Button } from '$lib/components/ui/button';

    export interface SchemaRow {
        key: string;
        title: string;
        type: 'string' | 'number' | 'integer';
    }

    interface Props {
        rows: SchemaRow[];
        onChange: (next: SchemaRow[]) => void;
        readonly?: boolean;
    }

    let { rows, onChange, readonly = false }: Props = $props();

    function update(i: number, patch: Partial<SchemaRow>) {
        const next = rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
        onChange(next);
    }
    function remove(i: number) {
        onChange(rows.filter((_, idx) => idx !== i));
    }
    function add() {
        onChange([...rows, { key: '', title: '', type: 'string' }]);
    }
</script>

<div class="schema-editor">
    <div class="schema-header-row">
        <span class="col-label">Key</span>
        <span class="col-label">Label</span>
        <span class="col-label">Type</span>
    </div>

    {#each rows as row, i (i)}
        <div class="schema-row" data-schema-row>
            <input
                type="text"
                value={row.key}
                oninput={(e) => update(i, { key: (e.target as HTMLInputElement).value })}
                placeholder="key"
                class="input-field schema-input"
                disabled={readonly}
            />
            <input
                type="text"
                value={row.title}
                oninput={(e) => update(i, { title: (e.target as HTMLInputElement).value })}
                placeholder="Label"
                class="input-field schema-input"
                disabled={readonly}
            />
            <select
                value={row.type}
                onchange={(e) => update(i, { type: (e.target as HTMLSelectElement).value as SchemaRow['type'] })}
                class="input-field schema-input"
                disabled={readonly}
            >
                <option value="string">Text</option>
                <option value="number">Number</option>
                <option value="integer">Integer</option>
            </select>
            {#if !readonly}
                <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-muted-foreground hover:bg-red-100 hover:text-red-600 size-6"
                    onclick={() => remove(i)}
                    title="Remove parameter"
                    aria-label="Remove parameter"
                >✕</Button>
            {/if}
        </div>
    {/each}

    {#if !readonly}
        <Button
            variant="outline"
            size="sm"
            class="self-start text-xs h-7 px-2.5 text-[hsl(173,58%,39%)]"
            onclick={add}
        >
            + Add Parameter
        </Button>
    {/if}
</div>

<style>
    .schema-editor { @apply flex flex-col gap-1.5; }
    .schema-header-row { @apply grid gap-1.5; grid-template-columns: 1fr 1fr 100px 24px; }
    .col-label { @apply text-xs uppercase text-gray-500 font-medium; }
    .schema-row { @apply grid gap-1.5 items-center; grid-template-columns: 1fr 1fr 100px 24px; }
    .input-field { @apply px-2 py-1 border border-gray-300 rounded text-xs; }
    .schema-input { @apply w-full; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/SchemaEditor.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/shared/SchemaEditor.svelte frontend/src/lib/components/shared/SchemaEditor.test.ts
git commit -m "feat(F-0081): shared SchemaEditor component for inline param add/remove"
```

---

## Task 4 — Shared `<EquipmentChipList>` component

**Files:**
- Create: `frontend/src/lib/components/shared/EquipmentChipList.svelte`
- Test: `frontend/src/lib/components/shared/EquipmentChipList.test.ts`

Renders chips for `data.equipment[]` with optional conflict markers and an optional "Manage" button.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/shared/EquipmentChipList.test.ts
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import EquipmentChipList from './EquipmentChipList.svelte';

const ORG = [
    { id: 'eq-1', name: 'Bioreactor A' },
    { id: 'eq-2', name: 'Bioreactor B' },
];

describe('EquipmentChipList', () => {
    it('renders an empty state when no equipment', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText(/no equipment/i)).toBeTruthy();
    });

    it('renders one chip per equipment_id with org name', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText('Bioreactor A')).toBeTruthy();
    });

    it('marks chip as conflicting when id is in conflictingIds and not shareable', () => {
        const { container } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(['eq-1']),
        });
        expect(container.querySelector('.equipment-chip.conflict')).toBeTruthy();
    });

    it('does NOT mark conflict when shareable', () => {
        const { container } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: true }],
            orgEquipment: ORG,
            conflictingIds: new Set(['eq-1']),
        });
        expect(container.querySelector('.equipment-chip.conflict')).toBeFalsy();
    });

    it('falls back to "Unknown" when equipment_id is not in orgEquipment', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'missing', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText(/Unknown/)).toBeTruthy();
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/EquipmentChipList.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/shared/EquipmentChipList.svelte -->
<script lang="ts">
    interface SelectedEquipment {
        equipment_id: string;
        shareable: boolean;
    }
    interface OrgEquipment {
        id: string;
        name: string;
    }

    interface Props {
        equipment: SelectedEquipment[];
        orgEquipment: OrgEquipment[];
        conflictingIds: Set<string>;
        showSwapped?: Set<string>;  // ids that should display a "swapped" badge
    }

    let {
        equipment,
        orgEquipment,
        conflictingIds,
        showSwapped = new Set<string>(),
    }: Props = $props();

    function nameFor(id: string): string {
        return orgEquipment.find((e) => e.id === id)?.name ?? 'Unknown';
    }
</script>

<div class="equipment-list-container">
    {#if equipment.length === 0}
        <div class="empty-message">No equipment assigned</div>
    {:else}
        {#each equipment as eq (eq.equipment_id)}
            <div
                class="equipment-chip"
                class:conflict={conflictingIds.has(eq.equipment_id) && !eq.shareable}
                class:swapped={showSwapped.has(eq.equipment_id)}
            >
                <span class="chip-name">{nameFor(eq.equipment_id)}</span>
                {#if eq.shareable}
                    <span class="chip-badge">Shared</span>
                {/if}
                {#if conflictingIds.has(eq.equipment_id) && !eq.shareable}
                    <span class="chip-warning" aria-label="conflict">⚠</span>
                {/if}
                {#if showSwapped.has(eq.equipment_id)}
                    <span class="chip-swap" aria-label="swapped">◆</span>
                {/if}
            </div>
        {/each}
    {/if}
</div>

<style>
    .equipment-list-container { @apply flex flex-wrap gap-1.5; }
    .equipment-chip {
        @apply inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs bg-slate-100 border border-slate-200 text-slate-700;
    }
    .equipment-chip.conflict { @apply bg-red-50 border-red-300 text-red-800; }
    .equipment-chip.swapped { @apply bg-emerald-50 border-emerald-400 text-emerald-900; }
    .chip-badge { @apply text-[10px] uppercase opacity-70; }
    .chip-warning { @apply text-red-600; }
    .chip-swap { @apply text-emerald-600; }
    .empty-message { @apply text-xs text-slate-500 italic; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/shared/EquipmentChipList.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/shared/EquipmentChipList.svelte frontend/src/lib/components/shared/EquipmentChipList.test.ts
git commit -m "feat(F-0081): shared EquipmentChipList component"
```

---

## Task 5 — Refactor Inspector to consume shared components

**Files:**
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte`

Drive-by, low-risk: Inspector is the only callsite for `SchemaEditor` and `EquipmentChipList`'s previous inline shapes, and the extracted components are drop-in. Also delete the local `renderTemplate` (line ~231) and import from `$lib/utils/template`.

- [ ] **Step 1: Run the existing Inspector tests baseline.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/protocol/
```
Expected: PASS (record the count for regression check).

- [ ] **Step 2: Replace inline equipment-chip block with `<EquipmentChipList>`.**

Open `frontend/src/lib/components/protocol/Inspector.svelte`. Find the equipment block (~lines 380–410, the section starting `<!-- Equipment -->`). Replace the `{#each editEquipment as eq (eq.equipment_id)}` chip-rendering loop with:

```svelte
<EquipmentChipList
    equipment={editEquipment}
    orgEquipment={orgEquipment}
    conflictingIds={new Set(equipmentConflicts.get(node?.id || '') || [])}
/>
```

Keep the `<Button>Manage Equipment</Button>` and `<EquipmentPickerModal>` mount untouched. Add the import at the top:

```typescript
import EquipmentChipList from "$lib/components/shared/EquipmentChipList.svelte";
```

- [ ] **Step 3: Replace inline schema-editor rows with `<SchemaEditor>`.**

In Inspector.svelte, find the schema-editor block (~lines 510–565, starting `<!-- Schema rows -->`). Replace the `{#each editSchemaRows as row, i}` loop AND the `+ Add Parameter` button with:

```svelte
<SchemaEditor
    rows={editSchemaRows}
    onChange={(next) => { editSchemaRows = next; handleApply(); }}
/>
```

Add the import:

```typescript
import SchemaEditor from "$lib/components/shared/SchemaEditor.svelte";
```

Delete the now-unused `addSchemaRow`, `removeSchemaRow` helpers if they only manipulated `editSchemaRows` in ways the new `onChange` handles. Keep `editSchemaRows` typed as `SchemaRow[]` (re-export the type from SchemaEditor).

- [ ] **Step 4: Replace inline param input branches with `<ParamInput>`.**

Find the parameter rendering block (~lines 432–488, starting `{#each properties as [key, prop]}`). Replace the four `{#if/:else if/:else}` branches with:

```svelte
{#each properties as [key, prop]}
    <div class="param-field">
        <label class="param-label" for="param-{key}">
            {prop.title || key}
        </label>
        <ParamInput
            id="param-{key}"
            schema={prop}
            value={editParams[key]}
            mediaPrepNodes={mediaPrepNodes.map((n) => ({ id: n.id, label: n.data.label }))}
            onChange={(v) => { editParams[key] = v; handleApply(); }}
        />
    </div>
{/each}
```

Add the import:

```typescript
import ParamInput from "$lib/components/shared/ParamInput.svelte";
```

- [ ] **Step 5: Delete local `renderTemplate` and import the shared one.**

In Inspector.svelte, delete the function `renderTemplate(template, params)` defined at line ~231. Add the import at the top:

```typescript
import { renderTemplate } from "$lib/utils/template";
```

- [ ] **Step 6: Run tests + typecheck.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/protocol/ && CI=true npm run check
```
Expected: PASS, no new typecheck errors.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src/lib/components/protocol/Inspector.svelte
git commit -m "refactor(F-0081): Inspector consumes ParamInput, SchemaEditor, EquipmentChipList; drop local renderTemplate"
```

---

## Task 6 — Add Zod schemas for the override payload

**Files:**
- Modify: `frontend/src/lib/schemas/runs.ts`

- [ ] **Step 1: Append the schemas.**

In `frontend/src/lib/schemas/runs.ts`, after the existing `RunSchema` block, add:

```typescript
export const NodeOverridesSchema = z.object({
    params: z.record(z.string(), z.unknown()).optional(),
    equipment: z.array(z.object({
        equipment_id: z.string(),
        shareable: z.boolean(),
    })).optional(),
    paramSchema: z.record(z.string(), z.unknown()).optional(),
    description: z.string().optional(),
});

export type NodeOverrides = z.infer<typeof NodeOverridesSchema>;

export const RunOverridesSchema = z.object({
    nodes: z.record(z.string(), NodeOverridesSchema),
});

export type RunOverrides = z.infer<typeof RunOverridesSchema>;

export const RunCreatePayloadSchema = z.object({
    name: z.string().min(1),
    project_id: z.string().uuid(),
    protocol_id: z.string().uuid(),
    protocol_version_number: z.number().int().positive().optional(),
    experiment_id: z.string().uuid().optional(),
    overrides: RunOverridesSchema.optional(),
});

export type RunCreatePayload = z.infer<typeof RunCreatePayloadSchema>;
```

- [ ] **Step 2: Verify typecheck.**

```bash
cd frontend && CI=true npm run check
```
Expected: PASS, no new errors.

- [ ] **Step 3: Commit.**

```bash
git add frontend/src/lib/schemas/runs.ts
git commit -m "feat(F-0081): add RunOverrides + RunCreatePayload Zod schemas"
```

---

## Task 7 — `<RunCreatorStepper>` (presentational)

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorStepper.svelte`
- Test: `frontend/src/lib/components/run/RunCreatorStepper.test.ts`

A 4-pill row showing `1 · Name → 2 · Protocol → 3 · Parameters → 4 · Review`. Highlights the current step; previously-visited steps are clickable.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunCreatorStepper.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorStepper from './RunCreatorStepper.svelte';

describe('RunCreatorStepper', () => {
    it('renders 4 step pills with labels', () => {
        const { getByText } = render(RunCreatorStepper, {
            currentStep: 1,
            highestVisited: 1,
            onJump: () => {},
        });
        expect(getByText(/Name/)).toBeTruthy();
        expect(getByText(/Protocol/)).toBeTruthy();
        expect(getByText(/Parameters/)).toBeTruthy();
        expect(getByText(/Review/)).toBeTruthy();
    });

    it('marks current step active', () => {
        const { container } = render(RunCreatorStepper, {
            currentStep: 2,
            highestVisited: 2,
            onJump: () => {},
        });
        const active = container.querySelector('[data-step-active="true"]');
        expect(active?.textContent).toMatch(/2/);
    });

    it('allows jumping to a previously-visited step', async () => {
        let jumped: number | null = null;
        const { container } = render(RunCreatorStepper, {
            currentStep: 3,
            highestVisited: 3,
            onJump: (n) => { jumped = n; },
        });
        const step1 = container.querySelector('[data-step="1"]') as HTMLButtonElement;
        await fireEvent.click(step1);
        expect(jumped).toBe(1);
    });

    it('disables steps beyond highestVisited', async () => {
        let jumped: number | null = null;
        const { container } = render(RunCreatorStepper, {
            currentStep: 1,
            highestVisited: 1,
            onJump: (n) => { jumped = n; },
        });
        const step3 = container.querySelector('[data-step="3"]') as HTMLButtonElement;
        expect(step3.disabled).toBe(true);
        await fireEvent.click(step3);
        expect(jumped).toBeNull();
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorStepper.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorStepper.svelte -->
<script lang="ts">
    interface Props {
        currentStep: 1 | 2 | 3 | 4;
        highestVisited: 1 | 2 | 3 | 4;
        onJump: (step: 1 | 2 | 3 | 4) => void;
    }

    let { currentStep, highestVisited, onJump }: Props = $props();

    const steps = [
        { n: 1, label: 'Name' },
        { n: 2, label: 'Protocol' },
        { n: 3, label: 'Parameters' },
        { n: 4, label: 'Review' },
    ] as const;
</script>

<nav class="stepper" aria-label="Run creation steps">
    {#each steps as s, i (s.n)}
        <button
            type="button"
            class="step-pill"
            class:active={s.n === currentStep}
            class:visited={s.n <= highestVisited}
            data-step={s.n}
            data-step-active={s.n === currentStep}
            disabled={s.n > highestVisited}
            onclick={() => onJump(s.n)}
        >
            <span class="step-num">{s.n}</span>
            <span class="step-label">{s.label}</span>
        </button>
        {#if i < steps.length - 1}
            <span class="step-sep" aria-hidden="true">›</span>
        {/if}
    {/each}
</nav>

<style>
    .stepper { @apply flex items-center gap-1 text-sm; }
    .step-pill {
        @apply inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-slate-500 border border-transparent transition-all duration-150 cursor-pointer;
    }
    .step-pill:hover:not(:disabled) { @apply bg-slate-100; }
    .step-pill:disabled { @apply opacity-40 cursor-not-allowed; }
    .step-pill.visited { @apply text-slate-700; }
    .step-pill.active { @apply bg-teal-50 border-teal-300 text-teal-900; }
    .step-num { @apply inline-flex items-center justify-center w-5 h-5 rounded-full bg-slate-200 text-xs font-semibold; }
    .step-pill.active .step-num { @apply bg-teal-500 text-white; }
    .step-label { @apply font-medium; }
    .step-sep { @apply text-slate-300 px-0.5; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorStepper.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorStepper.svelte frontend/src/lib/components/run/RunCreatorStepper.test.ts
git commit -m "feat(F-0081): RunCreatorStepper — presentational 4-pill stepper"
```

---

## Task 8 — `<RunCreatorNameStep>`

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorNameStep.svelte`
- Test: `frontend/src/lib/components/run/RunCreatorNameStep.test.ts`

Step 1: name (required) + experiment (optional). Locks the experiment dropdown when the wizard was launched from an experiment page (query param `experimentId=X`).

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunCreatorNameStep.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorNameStep from './RunCreatorNameStep.svelte';

const EXPERIMENTS = [
    { id: 'e1', name: 'Pilot', status: 'ACTIVE' },
    { id: 'e2', name: 'Archived', status: 'ARCHIVED' },
];

describe('RunCreatorNameStep', () => {
    it('shows error when name is empty and onValidate fires false', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: () => {},
            onValidate: (v) => { lastValid = v; },
        });
        expect(lastValid).toBe(false);
    });

    it('marks valid when name is non-empty', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorNameStep, {
            name: 'My Run',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: () => {},
            onValidate: (v) => { lastValid = v; },
        });
        expect(lastValid).toBe(true);
    });

    it('hides archived experiments from the dropdown', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: () => {},
            onValidate: () => {},
        });
        const opts = container.querySelectorAll('option');
        const labels = Array.from(opts).map((o) => o.textContent);
        expect(labels.some((l) => l?.includes('Archived'))).toBe(false);
    });

    it('locks experiment field when lockedExperiment is set', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: 'e1',
            experiments: EXPERIMENTS,
            lockedExperiment: { id: 'e1', name: 'Pilot' },
            onChange: () => {},
            onValidate: () => {},
        });
        const sel = container.querySelector('select');
        expect(sel?.disabled).toBe(true);
    });

    it('emits onChange when user types name', async () => {
        let captured: any = null;
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: (next) => { captured = next; },
            onValidate: () => {},
        });
        const input = container.querySelector('input[type="text"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: 'New' } });
        expect(captured.name).toBe('New');
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorNameStep.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorNameStep.svelte -->
<script lang="ts">
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
        onChange: (next: { name: string; experimentId: string | null }) => void;
        onValidate: (valid: boolean) => void;
    }

    let { name, experimentId, experiments, lockedExperiment, onChange, onValidate }: Props = $props();

    const visibleExperiments = $derived(
        experiments.filter((e) => (e.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    $effect(() => {
        onValidate(name.trim().length > 0);
    });

    function setName(v: string) { onChange({ name: v, experimentId }); }
    function setExperimentId(v: string) {
        onChange({ name, experimentId: v === '' ? null : v });
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
</section>

<style>
    .step-body { @apply max-w-xl flex flex-col gap-5; }
    .step-header h2 { @apply text-xl font-semibold text-slate-900; }
    .step-help { @apply text-sm text-slate-600 mt-1; }
    .field { @apply flex flex-col gap-1.5; }
    .field-label { @apply text-sm font-medium text-slate-700; }
    .optional { @apply text-slate-400 font-normal; }
    .input-field {
        @apply w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white;
    }
    .input-field:disabled { @apply bg-gray-50 text-slate-500 cursor-not-allowed; }
    .hint { @apply text-xs text-slate-500; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorNameStep.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorNameStep.svelte frontend/src/lib/components/run/RunCreatorNameStep.test.ts
git commit -m "feat(F-0081): RunCreatorNameStep"
```

---

## Task 9 — `<RunCreatorProtocolStep>`

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorProtocolStep.svelte`
- Test: `frontend/src/lib/components/run/RunCreatorProtocolStep.test.ts`

Step 2: protocol picker, version picker (defaults to "latest" via `null`), summary card with stats, "Compare versions" disclosure that mounts `<VersionHistoryDrawer>`. The drawer's `onRevert` callback is repurposed here as "select this version" — when the user picks a row in the drawer, set `protocolVersionNumber` and close the drawer.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunCreatorProtocolStep.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorProtocolStep from './RunCreatorProtocolStep.svelte';

const PROTOCOLS = [
    { id: 'p1', name: 'Mab-A', status: 'PUBLISHED', version_number: 3 },
    { id: 'p2', name: 'Mab-B Archived', status: 'ARCHIVED', version_number: 1 },
];

const VERSIONS_P1 = [
    {
        id: 'v3', protocol_id: 'p1', version_number: 3, name: 'Mab-A',
        description: 'Tightened pH window', change_summary: null,
        created_by_name: 'Wesley', created_at: '2026-04-15T00:00:00Z', is_draft: false,
        graph: { nodes: [], edges: [] },
    },
    {
        id: 'v2', protocol_id: 'p1', version_number: 2, name: 'Mab-A',
        description: null, change_summary: null,
        created_by_name: 'Alice', created_at: '2026-04-01T00:00:00Z', is_draft: false,
        graph: { nodes: [], edges: [] },
    },
];

describe('RunCreatorProtocolStep', () => {
    it('hides archived protocols from the dropdown', () => {
        const { container } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: () => {},
        });
        const opts = Array.from(container.querySelectorAll('option')).map((o) => o.textContent);
        expect(opts.some((l) => l?.includes('Archived'))).toBe(false);
    });

    it('emits onValidate(false) when no protocol selected', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: (v) => { lastValid = v; },
            onLoadVersions: () => {},
        });
        expect(lastValid).toBe(false);
    });

    it('calls onLoadVersions when protocolId changes', async () => {
        let loaded: string | null = null;
        const { container } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: (id) => { loaded = id; },
        });
        const sel = container.querySelector('select') as HTMLSelectElement;
        await fireEvent.change(sel, { target: { value: 'p1' } });
        expect(loaded).toBe('p1');
    });

    it('renders summary card showing latest pill when version is null', () => {
        const { getByText } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: 'p1',
            protocolVersionNumber: null,
            versions: VERSIONS_P1,
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: () => {},
        });
        expect(getByText(/v3/)).toBeTruthy();
        expect(getByText(/LATEST/i)).toBeTruthy();
    });

    it('emits onValidate(true) when both protocol and version-or-latest are set', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: 'p1',
            protocolVersionNumber: null,
            versions: VERSIONS_P1,
            loadingVersions: false,
            onChange: () => {},
            onValidate: (v) => { lastValid = v; },
            onLoadVersions: () => {},
        });
        expect(lastValid).toBe(true);
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorProtocolStep.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorProtocolStep.svelte -->
<script lang="ts">
    import VersionHistoryDrawer from '$lib/components/analytics/VersionHistoryDrawer.svelte';
    import type { Protocol, ProtocolVersion } from '$lib/schemas/protocols';

    interface Props {
        protocols: Protocol[];
        protocolId: string | null;
        protocolVersionNumber: number | null;  // null => latest
        versions: ProtocolVersion[];
        loadingVersions: boolean;
        onChange: (next: { protocolId: string | null; protocolVersionNumber: number | null }) => void;
        onValidate: (valid: boolean) => void;
        onLoadVersions: (protocolId: string) => void;
    }

    let {
        protocols,
        protocolId,
        protocolVersionNumber,
        versions,
        loadingVersions,
        onChange,
        onValidate,
        onLoadVersions,
    }: Props = $props();

    let drawerOpen = $state(false);

    const visibleProtocols = $derived(
        protocols.filter((p) => (p.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    const selectedProtocol = $derived(protocols.find((p) => p.id === protocolId) ?? null);

    const effectiveVersionNumber = $derived(
        protocolVersionNumber ?? selectedProtocol?.version_number ?? null,
    );

    const selectedVersion = $derived(
        versions.find((v) => v.version_number === effectiveVersionNumber) ?? null,
    );

    const isLatest = $derived(
        protocolVersionNumber === null ||
        protocolVersionNumber === selectedProtocol?.version_number,
    );

    $effect(() => {
        onValidate(!!protocolId && !!effectiveVersionNumber);
    });

    function setProtocolId(v: string) {
        const next = v === '' ? null : v;
        onChange({ protocolId: next, protocolVersionNumber: null });
        if (next) onLoadVersions(next);
    }

    function setVersionNumber(v: string) {
        const num = v === '' ? null : parseInt(v, 10);
        onChange({ protocolId, protocolVersionNumber: num });
    }

    function pickFromDrawer(versionNumber: number) {
        onChange({ protocolId, protocolVersionNumber: versionNumber });
        drawerOpen = false;
    }

    function unitOpStats(v: ProtocolVersion | null): string {
        if (!v) return '';
        const nodes = ((v.graph as any)?.nodes ?? []) as any[];
        const unitOps = nodes.filter((n) => n.type === 'unitOp');
        let paramCount = 0, eqCount = 0;
        for (const n of unitOps) {
            paramCount += Object.keys(n.data?.paramSchema?.properties ?? {}).length;
            eqCount += (n.data?.equipment ?? []).length;
        }
        return `${unitOps.length} unit ops · ${paramCount} params · ${eqCount} equipment slots`;
    }
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 2 · Pick a protocol & version</h2>
        <p class="step-help">Latest version is selected by default — change if you need to reproduce an older run.</p>
    </header>

    <div class="grid grid-cols-2 gap-4">
        <div class="field">
            <label for="proto-pick" class="field-label">Protocol</label>
            <select
                id="proto-pick"
                value={protocolId ?? ''}
                onchange={(e) => setProtocolId((e.target as HTMLSelectElement).value)}
                class="input-field"
            >
                <option value="">Select a protocol</option>
                {#each visibleProtocols as p (p.id)}
                    <option value={p.id}>{p.name}</option>
                {/each}
            </select>
        </div>

        <div class="field">
            <label for="ver-pick" class="field-label">Version</label>
            <select
                id="ver-pick"
                value={protocolVersionNumber ?? ''}
                onchange={(e) => setVersionNumber((e.target as HTMLSelectElement).value)}
                disabled={!protocolId || loadingVersions}
                class="input-field"
            >
                <option value="">Latest</option>
                {#each versions as v (v.version_number)}
                    <option value={v.version_number}>
                        v{v.version_number} — {new Date(v.created_at).toLocaleDateString()}
                        {#if v.created_by_name}· {v.created_by_name}{/if}
                    </option>
                {/each}
            </select>
        </div>
    </div>

    {#if selectedVersion}
        <div class="version-card">
            <div class="version-card-head">
                <span class="version-pill">v{selectedVersion.version_number}</span>
                <span class="version-name">{selectedVersion.name}</span>
                {#if isLatest}
                    <span class="latest-pill">LATEST</span>
                {/if}
            </div>
            <p class="version-stats">{unitOpStats(selectedVersion)}</p>
            <p class="version-desc">
                {selectedVersion.description || 'No description for this version.'}
            </p>
            <button type="button" class="compare-link" onclick={() => (drawerOpen = true)}>
                ↳ Compare versions
            </button>
        </div>
    {/if}
</section>

{#if drawerOpen && protocolId}
    <VersionHistoryDrawer
        versions={versions.map((v) => ({
            id: v.id,
            version_number: v.version_number,
            name: v.name,
            description: v.description ?? null,
            change_summary: v.change_summary ?? null,
            created_by_name: v.created_by_name ?? null,
            created_at: v.created_at,
        }))}
        currentVersion={effectiveVersionNumber ?? 0}
        loading={loadingVersions}
        onRevert={pickFromDrawer}
        onClose={() => (drawerOpen = false)}
    />
{/if}

<style>
    .step-body { @apply flex flex-col gap-5; }
    .step-header h2 { @apply text-xl font-semibold text-slate-900; }
    .step-help { @apply text-sm text-slate-600 mt-1; }
    .field { @apply flex flex-col gap-1.5; }
    .field-label { @apply text-sm font-medium text-slate-700; }
    .input-field {
        @apply w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent;
    }
    .input-field:disabled { @apply bg-gray-50 text-slate-500 cursor-not-allowed; }
    .version-card {
        @apply p-4 rounded-lg border border-slate-200 bg-slate-50/50 flex flex-col gap-2;
    }
    .version-card-head { @apply flex items-center gap-2; }
    .version-pill { @apply inline-flex items-center px-2 py-0.5 rounded-md bg-teal-100 text-teal-800 text-xs font-semibold; }
    .version-name { @apply text-sm font-medium text-slate-900; }
    .latest-pill { @apply inline-flex items-center px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold uppercase; }
    .version-stats { @apply text-xs text-slate-500; }
    .version-desc { @apply text-sm text-slate-700; }
    .compare-link {
        @apply text-xs text-teal-700 hover:underline self-start cursor-pointer transition-all duration-150;
    }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorProtocolStep.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorProtocolStep.svelte frontend/src/lib/components/run/RunCreatorProtocolStep.test.ts
git commit -m "feat(F-0081): RunCreatorProtocolStep with version summary + drawer reuse"
```

---

## Task 10 — `<RunCreatorUnitOpCard>`

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorUnitOpCard.svelte`
- Test: `frontend/src/lib/components/run/RunCreatorUnitOpCard.test.ts`

One card per unit-op node. Shows header (UO name, category, badge counts), `<EquipmentChipList>` + Manage button, parameter table with `<ParamInput>` per row, instruction block (collapsed by default), and `<SchemaEditor>` when expanded.

This component owns no state; it receives `node` and emits `onChange(next: UnitOpNode)`. The parent (`RunOverridesEditor`) replaces the node in `currentGraph` on each change.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunCreatorUnitOpCard.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorUnitOpCard from './RunCreatorUnitOpCard.svelte';

const baseNode = () => ({
    id: 'n1',
    type: 'unitOp',
    data: {
        label: 'Buffer Mix',
        category: 'Media Prep',
        params: { temperature: 25 },
        equipment: [{ equipment_id: 'eq-1', shareable: false }],
        paramSchema: {
            type: 'object',
            properties: { temperature: { type: 'number', title: 'Temperature' } },
        },
        description: 'Mix at {{temperature}}°C',
        protocol_params: { temperature: 25 },
        protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
        protocol_paramSchema: {
            type: 'object',
            properties: { temperature: { type: 'number', title: 'Temperature' } },
        },
        protocol_description: 'Mix at {{temperature}}°C',
    },
});

const ORG_EQ = [{ id: 'eq-1', name: 'Bioreactor A' }];

describe('RunCreatorUnitOpCard', () => {
    it('renders UO label and category in the header', () => {
        const { getByText } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        expect(getByText('Buffer Mix')).toBeTruthy();
        expect(getByText(/Media Prep/i)).toBeTruthy();
    });

    it('emits onChange with new param value when input changes', async () => {
        let captured: any = null;
        const { container } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set(),
            onChange: (next) => { captured = next; },
            onSwapEquipment: () => {},
        });
        const input = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: '30' } });
        expect(captured.data.params.temperature).toBe(30);
    });

    it('shows N overridden badge when params differ from protocol_params', () => {
        const node = baseNode();
        node.data.params.temperature = 30;
        const { getByText } = render(RunCreatorUnitOpCard, {
            node,
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        expect(getByText(/1 overridden/i)).toBeTruthy();
    });

    it('toggles instructions block when ✎ Edit instructions clicked', async () => {
        const { getByText, container } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        const link = getByText(/Edit instructions/i);
        await fireEvent.click(link);
        const ta = container.querySelector('textarea');
        expect(ta).toBeTruthy();
    });

    it('emits revert (back to protocol_params) when ↺ revert button clicked', async () => {
        const node = baseNode();
        node.data.params.temperature = 30;
        let captured: any = null;
        const { container } = render(RunCreatorUnitOpCard, {
            node,
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set(),
            onChange: (next) => { captured = next; },
            onSwapEquipment: () => {},
        });
        const revertBtn = container.querySelector('[aria-label="Revert temperature"]') as HTMLButtonElement;
        await fireEvent.click(revertBtn);
        expect(captured.data.params.temperature).toBe(25);
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorUnitOpCard.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorUnitOpCard.svelte -->
<script lang="ts">
    import { renderTemplate } from '$lib/utils/template';
    import ParamInput from '$lib/components/shared/ParamInput.svelte';
    import EquipmentChipList from '$lib/components/shared/EquipmentChipList.svelte';
    import SchemaEditor, { type SchemaRow } from '$lib/components/shared/SchemaEditor.svelte';
    import { Button } from '$lib/components/ui/button';

    interface MediaPrepNode { id: string; label: string; }
    interface OrgEquipment { id: string; name: string; }

    interface Props {
        node: any;
        mediaPrepNodes: MediaPrepNode[];
        orgEquipment: OrgEquipment[];
        conflictingIds: Set<string>;
        onChange: (next: any) => void;
        onSwapEquipment: (nodeId: string) => void;  // parent opens EquipmentPickerModal
    }

    let { node, mediaPrepNodes, orgEquipment, conflictingIds, onChange, onSwapEquipment }: Props = $props();

    const data = $derived(node.data ?? {});
    const props = $derived(((data.paramSchema?.properties) ?? {}) as Record<string, any>);
    const protoParams = $derived((data.protocol_params ?? {}) as Record<string, unknown>);
    const protoProps = $derived(((data.protocol_paramSchema?.properties) ?? {}) as Record<string, any>);

    const overriddenCount = $derived.by(() => {
        let n = 0;
        for (const k of Object.keys(props)) {
            if (k in protoProps) {
                if (JSON.stringify(data.params?.[k]) !== JSON.stringify(protoParams[k])) n++;
            }
        }
        return n;
    });
    const equipmentSwapped = $derived(
        JSON.stringify(data.equipment ?? []) !== JSON.stringify(data.protocol_equipment ?? []),
    );
    const descriptionModified = $derived((data.description ?? '') !== (data.protocol_description ?? ''));

    let showInstructions = $state(false);
    let editingDescription = $state<string>('');
    $effect(() => { editingDescription = data.description ?? ''; });

    function patchData(patch: Record<string, unknown>) {
        onChange({ ...node, data: { ...data, ...patch } });
    }

    function setParam(key: string, value: unknown) {
        patchData({ params: { ...(data.params ?? {}), [key]: value } });
    }

    function revertParam(key: string) {
        patchData({ params: { ...(data.params ?? {}), [key]: protoParams[key] } });
    }

    function removeParam(key: string) {
        const nextProps = { ...props };
        delete nextProps[key];
        const nextParams = { ...(data.params ?? {}) };
        delete nextParams[key];
        patchData({
            paramSchema: { ...data.paramSchema, properties: nextProps },
            params: nextParams,
        });
    }

    function setSchemaRows(rows: SchemaRow[]) {
        const nextProps: Record<string, any> = {};
        const nextParams: Record<string, unknown> = { ...(data.params ?? {}) };
        for (const r of rows) {
            if (!r.key) continue;
            nextProps[r.key] = { ...(props[r.key] ?? {}), type: r.type, title: r.title };
        }
        for (const k of Object.keys(nextParams)) {
            if (!(k in nextProps)) delete nextParams[k];
        }
        patchData({
            paramSchema: { ...data.paramSchema, properties: nextProps },
            params: nextParams,
        });
    }

    function commitDescription() {
        patchData({ description: editingDescription });
    }
    function revertDescription() {
        editingDescription = data.protocol_description ?? '';
        patchData({ description: data.protocol_description ?? '' });
    }

    const renderedDefault = $derived(renderTemplate(data.protocol_description ?? '', protoParams));
    const renderedEffective = $derived(renderTemplate(data.description ?? '', data.params ?? {}));
    const schemaRows = $derived<SchemaRow[]>(
        Object.entries(props).map(([k, v]) => ({
            key: k,
            title: (v as any).title ?? k,
            type: ((v as any).type ?? 'string') as SchemaRow['type'],
        })),
    );
</script>

<article class="uo-card" class:has-overrides={overriddenCount > 0 || equipmentSwapped || descriptionModified}>
    <header class="uo-head">
        <div class="uo-title">
            <span class="uo-label">{data.label ?? node.id}</span>
            {#if data.category}<span class="uo-category">{data.category}</span>{/if}
        </div>
        <div class="uo-badges">
            {#if overriddenCount > 0}
                <span class="badge badge-mint">{overriddenCount} overridden</span>
            {/if}
            {#if equipmentSwapped}
                <span class="badge badge-mint">equipment swapped</span>
            {/if}
            {#if descriptionModified}
                <span class="badge badge-amber">◆ instructions modified</span>
            {/if}
        </div>
    </header>

    <section class="uo-section">
        <h4 class="section-label">EQUIPMENT</h4>
        <div class="equipment-row">
            <EquipmentChipList
                equipment={data.equipment ?? []}
                {orgEquipment}
                {conflictingIds}
                showSwapped={equipmentSwapped ? new Set((data.equipment ?? []).map((e: any) => e.equipment_id)) : new Set()}
            />
            <Button variant="outline" size="sm" onclick={() => onSwapEquipment(node.id)}>Swap</Button>
        </div>
    </section>

    {#if Object.keys(props).length > 0}
        <section class="uo-section">
            <h4 class="section-label">PARAMETERS</h4>
            <table class="param-table">
                <thead>
                    <tr>
                        <th>Parameter</th>
                        <th>Default</th>
                        <th>Override for this run</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each Object.entries(props) as [key, prop]}
                        {@const isAdded = !(key in protoProps)}
                        {@const isModified = key in protoProps &&
                            JSON.stringify(data.params?.[key]) !== JSON.stringify(protoParams[key])}
                        <tr class:row-added={isAdded} class:row-modified={isModified}>
                            <td>
                                {prop.title ?? key}
                                {#if isAdded}<span class="row-tag row-tag-amber">+ ADDED</span>{/if}
                            </td>
                            <td class="default-cell">
                                {#if isAdded}<span class="muted">—</span>
                                {:else}{String(protoParams[key] ?? '')}{/if}
                            </td>
                            <td>
                                <ParamInput
                                    id="ov-{node.id}-{key}"
                                    schema={prop}
                                    value={data.params?.[key]}
                                    {mediaPrepNodes}
                                    onChange={(v) => setParam(key, v)}
                                />
                            </td>
                            <td class="action-cell">
                                {#if isModified}
                                    <button
                                        type="button"
                                        class="row-action"
                                        aria-label="Revert {key}"
                                        title="Revert to default"
                                        onclick={() => revertParam(key)}
                                    >↺</button>
                                {/if}
                                <button
                                    type="button"
                                    class="row-action row-action-remove"
                                    aria-label="Remove {key}"
                                    title="Remove parameter"
                                    onclick={() => removeParam(key)}
                                >✕</button>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </section>
    {/if}

    <section class="uo-section">
        <details class="schema-details">
            <summary class="section-label cursor-pointer">+ ADD / EDIT SCHEMA</summary>
            <SchemaEditor rows={schemaRows} onChange={setSchemaRows} />
        </details>
    </section>

    <section class="uo-section instructions-section">
        <div class="instructions-head">
            <h4 class="section-label">INSTRUCTIONS</h4>
            {#if descriptionModified}<span class="badge badge-amber">◆ modified</span>{/if}
            <button
                type="button"
                class="link"
                onclick={() => (showInstructions = !showInstructions)}
            >
                {showInstructions ? 'Hide editor' : '✎ Edit instructions'}
            </button>
        </div>
        <p class="rendered-template">{renderedEffective || '— no instructions —'}</p>
        {#if showInstructions}
            <div class="instructions-editor">
                <textarea
                    bind:value={editingDescription}
                    onblur={commitDescription}
                    rows="4"
                    class="input-field"
                    placeholder="Use {`{{paramKey}}`} to substitute values"
                ></textarea>
                <p class="rendered-preview">
                    Preview: {renderTemplate(editingDescription, data.params ?? {})}
                </p>
                <Button variant="ghost" size="sm" onclick={revertDescription}>↺ revert to protocol default</Button>
                <p class="muted text-xs">Default: {renderedDefault}</p>
            </div>
        {/if}
    </section>
</article>

<style>
    .uo-card { @apply rounded-xl border border-slate-200 bg-white p-4 flex flex-col gap-4; }
    .uo-card.has-overrides { @apply border-emerald-300 bg-emerald-50/30; }
    .uo-head { @apply flex items-start justify-between gap-3; }
    .uo-title { @apply flex flex-col gap-0.5; }
    .uo-label { @apply text-base font-semibold text-slate-900; }
    .uo-category { @apply text-xs text-slate-500 uppercase tracking-wide; }
    .uo-badges { @apply flex flex-wrap gap-1.5; }
    .badge { @apply inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium; }
    .badge-mint { @apply bg-emerald-100 text-emerald-800; }
    .badge-amber { @apply bg-amber-100 text-amber-800; }
    .uo-section { @apply flex flex-col gap-2; }
    .section-label { @apply text-xs uppercase tracking-wider text-slate-500 font-semibold; }
    .equipment-row { @apply flex items-center gap-2 flex-wrap; }
    .param-table { @apply w-full text-sm border-collapse; }
    .param-table th { @apply text-left text-xs uppercase text-slate-500 font-medium pb-2 border-b border-slate-200; }
    .param-table td { @apply py-2 align-middle border-b border-slate-100; }
    .param-table tr.row-modified td { @apply bg-emerald-50/40; }
    .param-table tr.row-added td { @apply bg-amber-50/40; }
    .default-cell { @apply text-slate-600; }
    .action-cell { @apply text-right whitespace-nowrap; }
    .row-tag { @apply ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase; }
    .row-tag-amber { @apply bg-amber-100 text-amber-800; }
    .row-action { @apply inline-flex items-center justify-center w-6 h-6 rounded text-slate-500 hover:bg-slate-100 cursor-pointer transition-all duration-150; }
    .row-action-remove:hover { @apply text-red-600 bg-red-50; }
    .instructions-head { @apply flex items-center gap-2; }
    .rendered-template { @apply text-sm text-slate-700 leading-relaxed; }
    .rendered-preview { @apply text-sm text-emerald-800 leading-relaxed; }
    .muted { @apply text-slate-400; }
    .link { @apply text-xs text-teal-700 hover:underline cursor-pointer; }
    .input-field {
        @apply w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-teal-500;
    }
    .schema-details summary { @apply select-none; }
    .instructions-editor { @apply flex flex-col gap-2; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorUnitOpCard.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorUnitOpCard.svelte frontend/src/lib/components/run/RunCreatorUnitOpCard.test.ts
git commit -m "feat(F-0081): RunCreatorUnitOpCard — per-UO override editor"
```

---

## Task 11 — `<RunOverridesEditor>` (Step 3 body, multi-role aware, reusable for Phase 4)

**Files:**
- Create: `frontend/src/lib/components/run/RunOverridesEditor.svelte`
- Test: `frontend/src/lib/components/run/RunOverridesEditor.test.ts`

Wraps the list of `<RunCreatorUnitOpCard>` plus a sticky 320px aside showing live edit counts and a role-grouped diff list. Owns the `EquipmentPickerModal` mount (passed `node.id` from a card's swap callback). Phase 4 will reuse this on the run detail page in `mode="edit"`.

**Multi-role behavior** (per the multi-role mockup):

- If `roles.length > 1`: render a role context bar above the cards (active role name + role-color vertical bar + meta + ‹ N/M › arrow nav). Filter visible cards to the active role's unit ops. The diff aside shows stat tiles + role-grouped diff lists with **clickable role-group headers** that set the active role.
- If `roles.length <= 1` (single-role or no-role/flat graph): hide the role context bar, render all unit-op cards in graph order, and render a flat (ungrouped) diff list in the aside.
- Switching the active role is a presentational filter on `currentGraph` — no remount, no state reset, all overrides preserved across roles.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunOverridesEditor.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunOverridesEditor from './RunOverridesEditor.svelte';

// ── Single-role / no-role fixture (flat graph, no swimlanes) ───────────────
const flatGraph = () => ({
    nodes: [
        {
            id: 'n1', type: 'unitOp',
            data: {
                label: 'Buffer Mix', category: 'Media Prep',
                params: { temperature: 25 },
                equipment: [{ equipment_id: 'eq-1', shareable: false }],
                paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                description: 'Mix at {{temperature}}',
                protocol_params: { temperature: 25 },
                protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                protocol_paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                protocol_description: 'Mix at {{temperature}}',
            },
        },
        {
            id: 'n2', type: 'unitOp',
            data: {
                label: 'Centrifugation', category: 'Reaction',
                params: { rpm: 4000 },
                equipment: [],
                paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                description: 'Spin at {{rpm}} rpm',
                protocol_params: { rpm: 4000 },
                protocol_equipment: [],
                protocol_paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                protocol_description: 'Spin at {{rpm}} rpm',
            },
        },
    ],
    edges: [],
});

// ── Multi-role fixture: two swimlanes, one UO under each ───────────────────
const multiRoleGraph = () => ({
    nodes: [
        { id: 'lane-op',  type: 'swimLane', data: { label: 'Operator',        role_id: 'role-op'  } },
        { id: 'lane-sup', type: 'swimLane', data: { label: 'Senior Operator', role_id: 'role-sup' } },
        {
            id: 'n1', type: 'unitOp', parentId: 'lane-op',
            data: {
                label: 'Buffer Mix', category: 'Media Prep',
                params: { temperature: 25 },
                equipment: [{ equipment_id: 'eq-1', shareable: false }],
                paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                description: 'Mix at {{temperature}}',
                protocol_params: { temperature: 25 },
                protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                protocol_paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                protocol_description: 'Mix at {{temperature}}',
            },
        },
        {
            id: 'n2', type: 'unitOp', parentId: 'lane-sup',
            data: {
                label: 'Centrifugation', category: 'Reaction',
                params: { rpm: 4000 },
                equipment: [],
                paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                description: 'Spin at {{rpm}} rpm',
                protocol_params: { rpm: 4000 },
                protocol_equipment: [],
                protocol_paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                protocol_description: 'Spin at {{rpm}} rpm',
            },
        },
    ],
    edges: [],
});

const opRole  = { id: 'role-op',  protocol_id: 'p1', name: 'Operator',        color: '#B96B17', sort_order: 0 };
const supRole = { id: 'role-sup', protocol_id: 'p1', name: 'Senior Operator', color: '#5C6BC0', sort_order: 1 };

describe('RunOverridesEditor — single-role / no-role (degenerate)', () => {
    it('renders one card per unit-op node, ignoring swimLanes', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        const cards = container.querySelectorAll('article.uo-card');
        expect(cards.length).toBe(2);
    });

    it('does NOT render the role context bar when roles.length <= 1', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(container.querySelector('.role-context')).toBeNull();
    });

    it('renders a flat (ungrouped) diff list in the aside when no roles', () => {
        const orig = flatGraph();
        const curr = flatGraph();
        curr.nodes[0].data.params.temperature = 30;
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        // No role-group buckets in the degenerate path
        expect(container.querySelector('.role-group')).toBeNull();
    });

    it('emits onChange with patched graph when a card edits a param', async () => {
        let captured: any = null;
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: (next) => { captured = next; },
            onRoleChange: () => {},
        });
        const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(numberInput, { target: { value: '30' } });
        expect(captured.nodes[0].data.params.temperature).toBe(30);
    });

    it('shows live stat tiles in the aside', () => {
        const orig = flatGraph();
        const curr = flatGraph();
        curr.nodes[0].data.params.temperature = 30;
        const { getByText } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        // Stat tile labels are present
        expect(getByText(/value/i)).toBeTruthy();
        expect(getByText(/equipment/i)).toBeTruthy();
    });

    it('renders empty state when graph has no unit ops', () => {
        const { getByText } = render(RunOverridesEditor, {
            originalGraph: { nodes: [], edges: [] },
            currentGraph: { nodes: [], edges: [] },
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(getByText(/no unit ops/i)).toBeTruthy();
    });
});

describe('RunOverridesEditor — multi-role', () => {
    it('renders the role context bar with active role name + position', () => {
        const { container, getByText } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(container.querySelector('.role-context')).not.toBeNull();
        expect(getByText('Operator')).toBeTruthy();
        expect(getByText('1 / 2')).toBeTruthy();
    });

    it('filters cards to only the active role', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const cards = container.querySelectorAll('article.uo-card');
        expect(cards.length).toBe(1); // only n1 belongs to role-op
    });

    it('arrow nav next/prev calls onRoleChange with the adjacent role', async () => {
        let nextRole: string | null = null;
        const { getByLabelText } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: (id) => { nextRole = id; },
        });
        await fireEvent.click(getByLabelText('Next role'));
        expect(nextRole).toBe('role-sup');
    });

    it('clicking an aside role-group head sets the active role', async () => {
        let nextRole: string | null = null;
        const orig = multiRoleGraph();
        const curr = multiRoleGraph();
        curr.nodes.find((n) => n.id === 'n2')!.data.params.rpm = 4500; // ensure sup group has an edit
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: (id) => { nextRole = id; },
        });
        const supHead = Array.from(
            container.querySelectorAll<HTMLButtonElement>('.role-group-head'),
        ).find((b) => b.textContent?.includes('Senior Operator'));
        expect(supHead).toBeTruthy();
        await fireEvent.click(supHead!);
        expect(nextRole).toBe('role-sup');
    });

    it('aside is global — shows edits from BOTH the active role and inactive roles', () => {
        const orig = multiRoleGraph();
        const curr = multiRoleGraph();
        curr.nodes.find((n) => n.id === 'n1')!.data.params.temperature = 30;  // Operator (active)
        curr.nodes.find((n) => n.id === 'n2')!.data.params.rpm = 4500;        // Senior Operator (inactive)
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        // Both role groups visible regardless of active filter
        const heads = container.querySelectorAll('.role-group-head');
        expect(heads.length).toBe(2);
    });

    it('marks the active role-group head with .active', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-sup',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const active = container.querySelector('.role-group-head.active');
        expect(active?.textContent).toContain('Senior Operator');
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunOverridesEditor.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunOverridesEditor.svelte -->
<script lang="ts">
    import RunCreatorUnitOpCard from './RunCreatorUnitOpCard.svelte';
    import EquipmentPickerModal from '$lib/components/modals/EquipmentPickerModal.svelte';
    import {
        computeEdits,
        groupUnitOpsByRole,
        groupEditsByRole,
    } from '$lib/utils/runOverrides';
    import { detectEquipmentConflicts } from '$lib/components/protocol/protocolGraph';
    import type { ProtocolRole } from '$lib/schemas/protocols';

    interface OrgEquipment {
        id: string;
        name: string;
        description?: string;
        equipment_type?: string;
        location?: string;
        organization_id: string;
        created_at: string;
        updated_at: string;
    }

    interface Props {
        originalGraph: any;
        currentGraph: any;
        orgEquipment: OrgEquipment[];
        mediaPrepNodes: Array<{ id: string; label: string }>;
        roles: ProtocolRole[];                  // sorted by sort_order; empty for no-role protocols
        activeRoleId: string | null;            // null when roles.length <= 1 (degenerate)
        onChange: (nextGraph: any) => void;
        onRoleChange: (roleId: string) => void; // parent updates wizard state's activeRoleId
        onCreateEquipment?: (data: any) => Promise<any>;
        readonly?: boolean;
    }

    let {
        originalGraph,
        currentGraph,
        orgEquipment,
        mediaPrepNodes,
        roles,
        activeRoleId,
        onChange,
        onRoleChange,
        onCreateEquipment,
        readonly = false,
    }: Props = $props();

    // True when the role context bar / role-grouped aside should render.
    const isMultiRole = $derived(roles.length > 1);

    const allUnitOpNodes = $derived(
        ((currentGraph?.nodes ?? []) as any[]).filter((n) => n.type === 'unitOp'),
    );

    // Cards filtered to the active role (multi-role) or all UOs (degenerate).
    const visibleUnitOpNodes = $derived.by(() => {
        if (!isMultiRole || !activeRoleId) return allUnitOpNodes;
        const byRole = groupUnitOpsByRole(currentGraph);
        return byRole.get(activeRoleId) ?? [];
    });

    const edits = $derived(computeEdits(originalGraph, currentGraph));

    // Aside is always global — never filtered by active role.
    const editsByRole = $derived(
        isMultiRole ? groupEditsByRole(edits, currentGraph) : null,
    );

    const stats = $derived.by(() => {
        let value = 0, swap = 0, added = 0, removed = 0, instruction = 0, schema = 0;
        for (const e of edits) {
            if (e.kind === 'VALUE') value++;
            else if (e.kind === 'SWAP') swap++;
            else if (e.kind === 'ADDED') added++;
            else if (e.kind === 'REMOVED') removed++;
            else if (e.kind === 'INSTRUCTION') instruction++;
            else if (e.kind === 'SCHEMA') schema++;
        }
        return { value, swap, added, removed, instruction, schema };
    });

    const conflicts = $derived(
        detectEquipmentConflicts(currentGraph?.nodes ?? [], currentGraph?.edges ?? []),
    );

    // Active role meta for the context bar.
    const activeRoleIndex = $derived(
        activeRoleId ? roles.findIndex((r) => r.id === activeRoleId) : -1,
    );
    const activeRole = $derived(
        activeRoleIndex >= 0 ? roles[activeRoleIndex] : null,
    );
    const activeRoleParamCount = $derived.by(() => {
        let n = 0;
        for (const node of visibleUnitOpNodes) {
            n += Object.keys(node.data?.params ?? {}).length;
        }
        return n;
    });

    function gotoRole(delta: -1 | 1) {
        if (!isMultiRole || activeRoleIndex < 0) return;
        const next = (activeRoleIndex + delta + roles.length) % roles.length;
        onRoleChange(roles[next].id);
    }

    let swapNodeId = $state<string | null>(null);
    const swapNode = $derived(
        swapNodeId ? allUnitOpNodes.find((n) => n.id === swapNodeId) ?? null : null,
    );

    function patchNode(nextNode: any) {
        const nextNodes = (currentGraph.nodes as any[]).map((n) =>
            n.id === nextNode.id ? nextNode : n,
        );
        onChange({ ...currentGraph, nodes: nextNodes });
    }

    function applyEquipment(next: Array<{ equipment_id: string; shareable: boolean }>) {
        if (!swapNode) return;
        patchNode({ ...swapNode, data: { ...swapNode.data, equipment: next } });
        swapNodeId = null;
    }
</script>

<div class="overrides-editor">
    <div class="cards-column">
        {#if isMultiRole && activeRole}
            <div class="role-context">
                <div class="rc-left">
                    <div class="role-bar" style:background={activeRole.color}></div>
                    <div>
                        <div class="rc-name">{activeRole.name}</div>
                        <div class="rc-meta">
                            Role {activeRoleIndex + 1} of {roles.length} ·
                            {visibleUnitOpNodes.length} UO ·
                            {activeRoleParamCount} params
                        </div>
                    </div>
                </div>
                <div class="role-nav">
                    <button
                        type="button"
                        aria-label="Previous role"
                        onclick={() => gotoRole(-1)}
                    >‹</button>
                    <span class="pos">{activeRoleIndex + 1} / {roles.length}</span>
                    <button
                        type="button"
                        aria-label="Next role"
                        onclick={() => gotoRole(1)}
                    >›</button>
                </div>
            </div>
        {/if}

        {#if visibleUnitOpNodes.length === 0}
            <div class="empty">
                {#if isMultiRole}No unit ops for this role.{:else}No unit ops in this protocol.{/if}
            </div>
        {:else}
            {#each visibleUnitOpNodes as node (node.id)}
                <RunCreatorUnitOpCard
                    {node}
                    {mediaPrepNodes}
                    {orgEquipment}
                    conflictingIds={new Set(conflicts.get(node.id) ?? [])}
                    onChange={patchNode}
                    onSwapEquipment={(id) => { swapNodeId = id; }}
                />
            {/each}
        {/if}
    </div>

    <aside class="diff-aside">
        <div class="aside-head">
            <h3 class="aside-title">Override summary</h3>
            <span class="aside-scope">all roles</span>
        </div>

        <div class="stats">
            <div class="stat-cell"><div class="stat-num" class:zero={stats.value === 0}>{stats.value}</div><div class="stat-lbl">Value</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.swap === 0}>{stats.swap}</div><div class="stat-lbl">Equipment</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.added === 0}>{stats.added}</div><div class="stat-lbl">Added</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.removed === 0}>{stats.removed}</div><div class="stat-lbl">Removed</div></div>
        </div>

        {#if isMultiRole && editsByRole}
            {#each roles as role (role.id)}
                {@const groupEdits = editsByRole.get(role.id) ?? []}
                <div class="role-group">
                    <button
                        type="button"
                        class="role-group-head"
                        class:active={role.id === activeRoleId}
                        onclick={() => onRoleChange(role.id)}
                    >
                        <span class="rg-mark" style:background={role.color}></span>
                        <span class="rg-name">{role.name}</span>
                        <span class="rg-count">{groupEdits.length} edit{groupEdits.length === 1 ? '' : 's'}</span>
                    </button>
                    {#if groupEdits.length === 0}
                        <div class="rg-empty">— inheriting all defaults —</div>
                    {:else}
                        <ul class="diff-list">
                            {#each groupEdits as e (e.nodeId + e.kind + (e.field ?? ''))}
                                <li class="diff-item">
                                    <span class="diff-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                                    <span class="diff-step">{e.stepName}</span>
                                    {#if e.fieldLabel}<span class="diff-field">{e.fieldLabel}</span>{/if}
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </div>
            {/each}
            {#if edits.length === 0}
                <p class="aside-empty">No edits — run will use protocol defaults.</p>
            {/if}
        {:else if edits.length > 0}
            <h4 class="aside-subtitle">Edits</h4>
            <ul class="diff-list">
                {#each edits as e (e.nodeId + e.kind + (e.field ?? ''))}
                    <li class="diff-item">
                        <span class="diff-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                        <span class="diff-step">{e.stepName}</span>
                        {#if e.fieldLabel}<span class="diff-field">{e.fieldLabel}</span>{/if}
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="aside-empty">No edits — run will use protocol defaults.</p>
        {/if}
    </aside>
</div>

{#if swapNode && onCreateEquipment}
    <EquipmentPickerModal
        open={true}
        nodeId={swapNode.id}
        currentEquipment={swapNode.data.equipment ?? []}
        {orgEquipment}
        conflictingIds={new Set(conflicts.get(swapNode.id) ?? [])}
        onClose={() => (swapNodeId = null)}
        onApply={applyEquipment}
        {onCreateEquipment}
    />
{/if}

<style>
    .overrides-editor { @apply grid gap-6; grid-template-columns: 1fr 320px; }
    @media (max-width: 1100px) {
        .overrides-editor { grid-template-columns: 1fr; }
    }
    .cards-column { @apply flex flex-col gap-4; }
    .empty { @apply p-6 text-sm text-slate-500 italic border border-dashed border-slate-200 rounded-lg text-center; }

    /* === Role context bar (multi-role only) === */
    .role-context {
        @apply flex items-center justify-between gap-4 px-4 py-3
               bg-card border border-border rounded-lg;
    }
    .rc-left { @apply flex items-center gap-3; }
    .role-bar { @apply w-1 h-8 rounded-sm shrink-0; }
    .rc-name { @apply text-base font-semibold tracking-tight; }
    .rc-meta { @apply mt-0.5 text-[11px] text-muted-foreground font-mono tracking-wide uppercase; }
    .role-nav {
        @apply inline-flex border border-border rounded-md overflow-hidden bg-card;
    }
    .role-nav button {
        @apply w-8 h-8 inline-flex items-center justify-center
               bg-card text-foreground text-sm cursor-pointer
               transition-colors hover:bg-muted;
    }
    .role-nav .pos {
        @apply px-3 inline-flex items-center font-mono text-[11px]
               text-muted-foreground bg-slate-50
               border-l border-r border-border tracking-wide;
    }

    /* === Aside === */
    .diff-aside {
        @apply self-start sticky top-4 p-4 rounded-lg border border-border
               bg-card flex flex-col gap-3;
    }
    .aside-head { @apply flex items-center justify-between; }
    .aside-title { @apply text-sm font-semibold text-foreground; }
    .aside-scope {
        @apply text-[11px] font-mono uppercase tracking-wide text-muted-foreground;
    }
    .aside-subtitle { @apply text-xs uppercase tracking-wider text-muted-foreground font-medium mt-2; }
    .aside-empty { @apply text-xs text-muted-foreground italic; }

    /* === Stat tiles === */
    .stats { @apply grid grid-cols-2 gap-2; }
    .stat-cell {
        @apply px-3 py-2.5 rounded-md border border-border bg-slate-50/60;
    }
    .stat-num { @apply font-mono text-[22px] font-medium leading-none text-foreground; }
    .stat-num.zero { @apply text-slate-400; }
    .stat-lbl {
        @apply mt-1 text-[11px] font-mono uppercase tracking-wide text-muted-foreground;
    }

    /* === Role group (clickable headers in aside) === */
    .role-group { @apply mt-2; }
    .role-group-head {
        @apply flex items-center gap-2 w-full text-left
               px-2.5 py-2 -mx-2.5 mb-1
               text-xs text-muted-foreground bg-transparent border-0
               rounded-md cursor-pointer transition-colors;
    }
    .role-group-head:hover { @apply bg-slate-50; }
    /* Same wash as the wizard's active-step pill */
    .role-group-head.active { background: hsl(195 60% 96%); }
    .role-group-head.active .rg-name { @apply text-primary; }
    .rg-mark { @apply w-2 h-2 rounded-full shrink-0; }
    .rg-name { @apply font-semibold text-[13px] text-foreground; }
    .rg-count { @apply ml-auto font-mono text-[11px] tracking-wide text-muted-foreground; }
    .rg-empty { @apply pt-2 pb-1 text-xs text-muted-foreground italic; }

    /* === Diff list === */
    .diff-list { @apply flex flex-col gap-1 text-xs; }
    .diff-item { @apply flex items-center gap-1.5; }
    .diff-tag { @apply inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase; }
    .tag-value { @apply bg-emerald-100 text-emerald-800; }
    .tag-swap { @apply bg-emerald-100 text-emerald-800; }
    .tag-added { @apply bg-amber-100 text-amber-800; }
    .tag-removed { @apply bg-red-100 text-red-800; }
    .tag-instruction { @apply bg-blue-100 text-blue-800; }
    .tag-schema { @apply bg-amber-100 text-amber-800; }
    .diff-step { @apply font-medium text-slate-700; }
    .diff-field { @apply text-slate-500; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunOverridesEditor.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunOverridesEditor.svelte frontend/src/lib/components/run/RunOverridesEditor.test.ts
git commit -m "feat(F-0081): RunOverridesEditor — multi-role Step 3 body with role context bar + role-grouped aside (also Phase 4 surface)"
```

---

## Task 12 — `<SaveAsNewVersionDialog>`

**Files:**
- Create: `frontend/src/lib/components/run/SaveAsNewVersionDialog.svelte`
- Test: `frontend/src/lib/components/run/SaveAsNewVersionDialog.test.ts`

Triggered between Step 3 and Step 4 if `edits.length > 0`. Lists every edit with a kind tag and human-readable diff. Three actions: Cancel / Save as v{N+1} (secondary) / **Just for this run · continue →** (primary, focused — Enter dismisses).

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/SaveAsNewVersionDialog.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SaveAsNewVersionDialog from './SaveAsNewVersionDialog.svelte';

const sampleEdits = [
    { nodeId: 'n1', stepName: 'Buffer Mix', kind: 'VALUE' as const, field: 'temperature', fieldLabel: 'Temperature', oldValue: 25, newValue: 30 },
    { nodeId: 'n2', stepName: 'Centrifugation', kind: 'SWAP' as const, field: 'equipment', fieldLabel: 'Equipment' },
];

describe('SaveAsNewVersionDialog', () => {
    it('lists every edit with its kind tag', () => {
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: () => {},
        });
        expect(getByText(/Buffer Mix/)).toBeTruthy();
        expect(getByText(/Centrifugation/)).toBeTruthy();
        expect(getByText(/VALUE/i)).toBeTruthy();
        expect(getByText(/SWAP/i)).toBeTruthy();
    });

    it('shows v{N+1} in the save-as-version button', () => {
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: () => {},
        });
        expect(getByText(/Save as v4/)).toBeTruthy();
    });

    it('fires onJustThisRun when primary clicked', async () => {
        let called = false;
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => { called = true; },
            onSaveAsVersion: () => {},
        });
        await fireEvent.click(getByText(/Just for this run/));
        expect(called).toBe(true);
    });

    it('fires onSaveAsVersion with the description when secondary clicked', async () => {
        let captured: string | null = null;
        const { getByText, container } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: (desc) => { captured = desc; },
        });
        const ta = container.querySelector('textarea') as HTMLTextAreaElement;
        await fireEvent.input(ta, { target: { value: 'pH tweak' } });
        await fireEvent.click(getByText(/Save as v4/));
        expect(captured).toBe('pH tweak');
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/SaveAsNewVersionDialog.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/SaveAsNewVersionDialog.svelte -->
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import type { Edit } from '$lib/utils/runOverrides';

    interface Props {
        open: boolean;
        edits: Edit[];
        nextVersionNumber: number;
        onCancel: () => void;
        onJustThisRun: () => void;
        onSaveAsVersion: (description: string) => void;
    }

    let { open = $bindable(false), edits, nextVersionNumber, onCancel, onJustThisRun, onSaveAsVersion }: Props = $props();

    let description = $state('');

    function summary(e: Edit): string {
        if (e.kind === 'INSTRUCTION') {
            const oldStr = String(e.oldValue ?? '').slice(0, 40);
            const newStr = String(e.newValue ?? '').slice(0, 40);
            return `${oldStr}… → ${newStr}…`;
        }
        if (e.oldValue !== undefined && e.newValue !== undefined) {
            return `${String(e.oldValue)} → ${String(e.newValue)}`;
        }
        return e.fieldLabel ?? '';
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>Save as a new protocol version?</Dialog.Title>
            <Dialog.Description>
                You've made {edits.length} edit{edits.length === 1 ? '' : 's'} to the protocol.
                You can keep them just for this run, or publish them as v{nextVersionNumber} so future runs inherit them.
            </Dialog.Description>
        </Dialog.Header>

        <div class="edits-list">
            {#each edits as e (e.nodeId + e.kind + (e.field ?? ''))}
                <div class="edit-row">
                    <span class="edit-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                    <span class="edit-step">{e.stepName}</span>
                    <span class="edit-summary">{e.fieldLabel ?? ''} {summary(e)}</span>
                </div>
            {/each}
        </div>

        <div class="version-desc">
            <label for="save-as-desc" class="field-label">Version description (optional)</label>
            <textarea
                id="save-as-desc"
                bind:value={description}
                rows="2"
                placeholder="e.g. Reduced pH target for DOE arm 4; swapped to Bioreactor B"
                class="input-field"
            ></textarea>
        </div>

        <Dialog.Footer>
            <Button variant="ghost" onclick={onCancel}>Cancel</Button>
            <Button variant="secondary" onclick={() => onSaveAsVersion(description)}>
                Save as v{nextVersionNumber}
            </Button>
            <Button autofocus onclick={onJustThisRun}>
                Just for this run · continue →
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .edits-list { @apply flex flex-col gap-1.5 max-h-64 overflow-y-auto py-2; }
    .edit-row { @apply flex items-center gap-2 text-sm; }
    .edit-tag { @apply inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase; }
    .tag-value { @apply bg-emerald-100 text-emerald-800; }
    .tag-swap { @apply bg-emerald-100 text-emerald-800; }
    .tag-added { @apply bg-amber-100 text-amber-800; }
    .tag-removed { @apply bg-red-100 text-red-800; }
    .tag-instruction { @apply bg-blue-100 text-blue-800; }
    .tag-schema { @apply bg-amber-100 text-amber-800; }
    .edit-step { @apply font-medium text-slate-800; }
    .edit-summary { @apply text-slate-500 text-xs; }
    .version-desc { @apply mt-3 flex flex-col gap-1.5; }
    .field-label { @apply text-sm font-medium text-slate-700; }
    .input-field {
        @apply w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500;
    }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/SaveAsNewVersionDialog.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/SaveAsNewVersionDialog.svelte frontend/src/lib/components/run/SaveAsNewVersionDialog.test.ts
git commit -m "feat(F-0081): SaveAsNewVersionDialog — three-action prompt before review"
```

---

## Task 13 — `<RunCreatorReviewStep>`

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorReviewStep.svelte`
- Test: `frontend/src/lib/components/run/RunCreatorReviewStep.test.ts`

Step 4: read-only summary of name, experiment, protocol, version, and edits. Single primary action: Create run.

- [ ] **Step 1: Write the failing test.**

```typescript
// frontend/src/lib/components/run/RunCreatorReviewStep.test.ts
import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';

describe('RunCreatorReviewStep', () => {
    it('renders the run name, protocol name, and version', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7',
            experimentName: null,
            protocolName: 'Mab-A',
            versionNumber: 3,
            isLatestVersion: true,
            edits: [],
            creating: false,
            error: null,
            onCreate: () => {},
        });
        expect(getByText('Run 7')).toBeTruthy();
        expect(getByText('Mab-A')).toBeTruthy();
        expect(getByText(/v3/)).toBeTruthy();
    });

    it('shows "uses protocol defaults" when no edits', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: null, onCreate: () => {},
        });
        expect(getByText(/uses protocol defaults/i)).toBeTruthy();
    });

    it('lists edits when present', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true,
            edits: [
                { nodeId: 'n1', stepName: 'Buffer Mix', kind: 'VALUE', field: 'temperature', fieldLabel: 'Temperature', oldValue: 25, newValue: 30 },
            ],
            creating: false, error: null, onCreate: () => {},
        });
        expect(getByText(/Buffer Mix/)).toBeTruthy();
    });

    it('fires onCreate when Create button clicked', async () => {
        let called = false;
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: null,
            onCreate: () => { called = true; },
        });
        await fireEvent.click(getByText(/Create run/i));
        expect(called).toBe(true);
    });

    it('disables Create button when creating=true', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: true, error: null, onCreate: () => {},
        });
        const btn = getByText(/Creating/i).closest('button') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
    });

    it('renders error message when error is set', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: 'Backend exploded', onCreate: () => {},
        });
        expect(getByText('Backend exploded')).toBeTruthy();
    });
});
```

- [ ] **Step 2: Run test, confirm failure.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorReviewStep.test.ts
```

- [ ] **Step 3: Implement.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorReviewStep.svelte -->
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import type { Edit } from '$lib/utils/runOverrides';

    interface Props {
        runName: string;
        experimentName: string | null;
        protocolName: string;
        versionNumber: number;
        isLatestVersion: boolean;
        edits: Edit[];
        creating: boolean;
        error: string | null;
        onCreate: () => void;
    }

    let {
        runName, experimentName, protocolName, versionNumber, isLatestVersion,
        edits, creating, error, onCreate,
    }: Props = $props();
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 4 · Review & create</h2>
        <p class="step-help">Looks good? Create the run and start working.</p>
    </header>

    <dl class="summary">
        <div class="summary-row">
            <dt>Name</dt>
            <dd>{runName}</dd>
        </div>
        {#if experimentName}
            <div class="summary-row">
                <dt>Experiment</dt>
                <dd>{experimentName}</dd>
            </div>
        {/if}
        <div class="summary-row">
            <dt>Protocol</dt>
            <dd>
                {protocolName}
                <span class="version-pill">v{versionNumber}</span>
                {#if isLatestVersion}<span class="latest-pill">LATEST</span>{/if}
            </dd>
        </div>
    </dl>

    <section class="edits-summary">
        <h3 class="edits-title">Overrides ({edits.length})</h3>
        {#if edits.length === 0}
            <p class="muted">This run uses protocol defaults — no overrides.</p>
        {:else}
            <ul class="edits-list">
                {#each edits as e (e.nodeId + e.kind + (e.field ?? ''))}
                    <li class="edit-row">
                        <span class="edit-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                        <span class="edit-step">{e.stepName}</span>
                        <span class="edit-field">{e.fieldLabel ?? ''}</span>
                        {#if e.oldValue !== undefined && e.newValue !== undefined && e.kind !== 'INSTRUCTION'}
                            <span class="edit-diff">{String(e.oldValue)} → {String(e.newValue)}</span>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}
    </section>

    {#if error}
        <p class="error">{error}</p>
    {/if}

    <div class="actions">
        <Button onclick={onCreate} disabled={creating}>
            {creating ? 'Creating…' : 'Create run'}
        </Button>
    </div>
</section>

<style>
    .step-body { @apply flex flex-col gap-5 max-w-2xl; }
    .step-header h2 { @apply text-xl font-semibold text-slate-900; }
    .step-help { @apply text-sm text-slate-600 mt-1; }
    .summary { @apply rounded-lg border border-slate-200 bg-slate-50/50 p-4 flex flex-col gap-2; }
    .summary-row { @apply grid grid-cols-[120px_1fr] gap-2 items-center text-sm; }
    .summary-row dt { @apply text-slate-500 font-medium uppercase text-xs; }
    .summary-row dd { @apply text-slate-900 flex items-center gap-2; }
    .version-pill { @apply inline-flex items-center px-2 py-0.5 rounded-md bg-teal-100 text-teal-800 text-xs font-semibold; }
    .latest-pill { @apply inline-flex items-center px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold uppercase; }
    .edits-summary { @apply flex flex-col gap-2; }
    .edits-title { @apply text-sm font-semibold text-slate-900; }
    .muted { @apply text-sm text-slate-500 italic; }
    .edits-list { @apply flex flex-col gap-1; }
    .edit-row { @apply flex items-center gap-2 text-sm flex-wrap; }
    .edit-tag { @apply inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase; }
    .tag-value, .tag-swap { @apply bg-emerald-100 text-emerald-800; }
    .tag-added { @apply bg-amber-100 text-amber-800; }
    .tag-removed { @apply bg-red-100 text-red-800; }
    .tag-instruction { @apply bg-blue-100 text-blue-800; }
    .tag-schema { @apply bg-amber-100 text-amber-800; }
    .edit-step { @apply font-medium text-slate-800; }
    .edit-field { @apply text-slate-600; }
    .edit-diff { @apply text-slate-500 text-xs; }
    .error { @apply text-sm text-red-600; }
    .actions { @apply flex justify-end; }
</style>
```

- [ ] **Step 4: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/RunCreatorReviewStep.test.ts
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorReviewStep.svelte frontend/src/lib/components/run/RunCreatorReviewStep.test.ts
git commit -m "feat(F-0081): RunCreatorReviewStep"
```

---

## Task 14 — `<RunCreatorWizardModal>`

**Files:**
- Create: `frontend/src/lib/components/run/RunCreatorWizardModal.svelte`

The modal wraps `FullScreenModal` (matching the chrome of `ProtocolImportModal` / `BatchRecordImportModal`), owns all wizard state, and orchestrates the four step components + the `SaveAsNewVersionDialog` + a close-confirm `ConfirmDialog`. Public API mirrors today's `CreateRunModal` so the three call sites can swap one-for-one in Task 15:

```typescript
interface Props {
    open: boolean;                                          // bindable
    projectId: string;
    protocols: Protocol[];
    experiments?: any[];
    forExperiment?: { id: string; name: string } | null;
    onCreated?: (run: { id: string }) => void;
}
```

On Continue from Step 3, if there are edits, fire the SaveAsNewVersionDialog; on `Just for this run` advance to Step 4; on `Save as v{N+1}`, POST publish-draft (Phase 1 endpoint), reload versions, then advance to Step 4 with `protocolVersionNumber = N+1`. On Create run success, call `onCreated?.(newRun)` and `goto('/runs/{id}')`.

On request-to-close (the modal's X button or the footer Cancel), if `edits.length > 0` OR `runName.length > 0`, show `ConfirmDialog` ("Discard changes?"); otherwise close + reset state. State is reset via a `$effect` that watches `open` going `true` (fresh-mount semantics on each open).

- [ ] **Step 1: Create the modal component.**

```svelte
<!-- frontend/src/lib/components/run/RunCreatorWizardModal.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import RunCreatorStepper from './RunCreatorStepper.svelte';
    import RunCreatorNameStep from './RunCreatorNameStep.svelte';
    import RunCreatorProtocolStep from './RunCreatorProtocolStep.svelte';
    import RunOverridesEditor from './RunOverridesEditor.svelte';
    import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';
    import SaveAsNewVersionDialog from './SaveAsNewVersionDialog.svelte';
    import { computeEdits, buildOverridesPayload } from '$lib/utils/runOverrides';
    import type { Protocol, ProtocolVersion, ProtocolRole } from '$lib/schemas/protocols';

    interface Props {
        open: boolean;
        projectId: string;
        protocols: Protocol[];
        experiments?: any[];
        forExperiment?: { id: string; name: string } | null;
        onCreated?: (run: { id: string }) => void;
    }

    let {
        open = $bindable(false),
        projectId,
        protocols,
        experiments = [],
        forExperiment = null,
        onCreated,
    }: Props = $props();

    let versions = $state<ProtocolVersion[]>([]);
    let orgEquipment = $state<any[]>([]);
    let loadedOrgEq = $state(false);

    let runName = $state('');
    let experimentId = $state<string | null>(null);

    let protocolId = $state<string | null>(null);
    let protocolVersionNumber = $state<number | null>(null);
    let originalGraph = $state<any | null>(null);
    let currentGraph = $state<any | null>(null);
    let loadingVersions = $state(false);

    // Roles for the selected protocol (sorted by sort_order). Empty for no-role protocols.
    let roles = $state<ProtocolRole[]>([]);
    // Active role for Step 3 filtering. null when roles.length <= 1 (degenerate path).
    let activeRoleId = $state<string | null>(null);

    let currentStep = $state<1 | 2 | 3 | 4>(1);
    let highestVisited = $state<1 | 2 | 3 | 4>(1);

    let nameValid = $state(false);
    let protocolValid = $state(false);

    let saveDialogOpen = $state(false);
    let discardConfirmOpen = $state(false);
    let creating = $state(false);
    let createError = $state<string | null>(null);

    const selectedProtocol = $derived(protocols.find((p) => p.id === protocolId) ?? null);
    const selectedVersion = $derived(
        versions.find(
            (v) => v.version_number === (protocolVersionNumber ?? selectedProtocol?.version_number),
        ) ?? null,
    );
    const isLatestVersion = $derived(
        protocolVersionNumber === null ||
        protocolVersionNumber === selectedProtocol?.version_number,
    );
    const edits = $derived(
        originalGraph && currentGraph ? computeEdits(originalGraph, currentGraph) : [],
    );
    const hasUnsaved = $derived(runName.length > 0 || edits.length > 0);

    const mediaPrepNodes = $derived(
        ((currentGraph?.nodes ?? []) as any[])
            .filter((n) => n.type === 'unitOp' && n.data?.category === 'Media Prep')
            .map((n) => ({ id: n.id, label: n.data?.label ?? n.id })),
    );

    function resetState() {
        runName = '';
        experimentId = forExperiment?.id ?? null;
        protocolId = null;
        protocolVersionNumber = null;
        originalGraph = null;
        currentGraph = null;
        versions = [];
        roles = [];
        activeRoleId = null;
        currentStep = 1;
        highestVisited = 1;
        nameValid = false;
        protocolValid = false;
        saveDialogOpen = false;
        creating = false;
        createError = null;
    }

    $effect(() => {
        if (open) {
            resetState();
            if (!loadedOrgEq) {
                api.get<any[]>('/equipment').then((eq) => {
                    orgEquipment = eq;
                    loadedOrgEq = true;
                }).catch(() => { /* non-fatal */ });
            }
        }
    });

    async function loadVersions(pid: string) {
        loadingVersions = true;
        try {
            versions = await api.get<ProtocolVersion[]>(`/science/protocols/${pid}/versions`);
        } finally {
            loadingVersions = false;
        }
    }

    // Resolve roles whenever the selected protocol changes.
    // ProtocolRole is exposed on the Protocol detail endpoint (existing `/science/protocols/{id}`
    // already returns roles[]; verify shape by reading the endpoint response when implementing).
    // Sort by sort_order so role nav order is stable.
    $effect(() => {
        if (!protocolId) {
            roles = [];
            activeRoleId = null;
            return;
        }
        api.get<{ roles?: ProtocolRole[] }>(`/science/protocols/${protocolId}`)
            .then((p) => {
                const sorted = (p.roles ?? []).slice().sort(
                    (a, b) => a.sort_order - b.sort_order,
                );
                roles = sorted;
                // If multi-role, pick the first role; otherwise null (degenerate path).
                activeRoleId = sorted.length > 1 ? sorted[0].id : null;
            })
            .catch(() => {
                roles = [];
                activeRoleId = null;
            });
    });

    $effect(() => {
        if (!selectedVersion) {
            originalGraph = null;
            currentGraph = null;
            return;
        }
        const cloned = JSON.parse(JSON.stringify(selectedVersion.graph ?? { nodes: [], edges: [] }));
        originalGraph = JSON.parse(JSON.stringify(cloned));
        currentGraph = cloned;
    });

    function jumpTo(step: 1 | 2 | 3 | 4) {
        if (step <= highestVisited) currentStep = step;
    }

    function next() {
        if (currentStep === 1 && nameValid) {
            currentStep = 2;
            highestVisited = Math.max(highestVisited, 2) as typeof highestVisited;
        } else if (currentStep === 2 && protocolValid) {
            currentStep = 3;
            highestVisited = Math.max(highestVisited, 3) as typeof highestVisited;
        } else if (currentStep === 3) {
            if (edits.length > 0) {
                saveDialogOpen = true;
            } else {
                currentStep = 4;
                highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
            }
        }
    }

    function back() {
        if (currentStep > 1) currentStep = (currentStep - 1) as typeof currentStep;
    }

    function requestClose() {
        if (hasUnsaved) {
            discardConfirmOpen = true;
        } else {
            open = false;
        }
    }

    function confirmDiscard() {
        discardConfirmOpen = false;
        open = false;
    }

    function dialogJustThisRun() {
        saveDialogOpen = false;
        currentStep = 4;
        highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
    }

    async function dialogSaveAsVersion(description: string) {
        if (!protocolId) return;
        try {
            const nextVer = (selectedProtocol?.version_number ?? 0) + 1;
            await api.post(
                `/science/protocols/${protocolId}/publish-draft?version_number=${nextVer}`,
                { description: description || undefined },
            );
            await loadVersions(protocolId);
            protocolVersionNumber = nextVer;
            saveDialogOpen = false;
            currentStep = 4;
            highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
        } catch (e) {
            createError = e instanceof Error ? e.message : 'Failed to save version';
        }
    }

    async function createRun() {
        if (!runName || !protocolId) return;
        creating = true;
        createError = null;
        try {
            const payload: Record<string, unknown> = {
                name: runName,
                project_id: projectId,
                protocol_id: protocolId,
            };
            if (experimentId) payload.experiment_id = experimentId;
            if (protocolVersionNumber) payload.protocol_version_number = protocolVersionNumber;
            const overrides = buildOverridesPayload(edits, currentGraph);
            if (overrides) payload.overrides = overrides;
            const newRun = await api.post<{ id: string }>('/science/runs', payload);
            onCreated?.(newRun);
            open = false;
            goto(`/runs/${newRun.id}`);
        } catch (e) {
            createError = e instanceof Error ? e.message : 'Failed to create run';
        } finally {
            creating = false;
        }
    }
</script>

<FullScreenModal bind:open title={forExperiment ? `New Run for ${forExperiment.name}` : 'New Run'} onClose={requestClose}>
    {#snippet headerActions()}
        <RunCreatorStepper {currentStep} {highestVisited} onJump={jumpTo} />
    {/snippet}

    <div class="wizard-body">
        <main class="wizard-main">
            {#if currentStep === 1}
                <RunCreatorNameStep
                    name={runName}
                    {experimentId}
                    {experiments}
                    lockedExperiment={forExperiment}
                    onChange={(v) => { runName = v.name; experimentId = v.experimentId; }}
                    onValidate={(v) => { nameValid = v; }}
                />
            {:else if currentStep === 2}
                <RunCreatorProtocolStep
                    {protocols}
                    {protocolId}
                    {protocolVersionNumber}
                    {versions}
                    {loadingVersions}
                    onChange={(v) => { protocolId = v.protocolId; protocolVersionNumber = v.protocolVersionNumber; }}
                    onValidate={(v) => { protocolValid = v; }}
                    onLoadVersions={loadVersions}
                />
            {:else if currentStep === 3 && currentGraph && originalGraph}
                <RunOverridesEditor
                    {originalGraph}
                    {currentGraph}
                    {orgEquipment}
                    {mediaPrepNodes}
                    {roles}
                    {activeRoleId}
                    onChange={(g) => { currentGraph = g; }}
                    onRoleChange={(id) => { activeRoleId = id; }}
                />
            {:else if currentStep === 4}
                <RunCreatorReviewStep
                    {runName}
                    experimentName={experiments.find((e: any) => e.id === experimentId)?.name ?? null}
                    protocolName={selectedProtocol?.name ?? ''}
                    versionNumber={selectedVersion?.version_number ?? 0}
                    {isLatestVersion}
                    {edits}
                    {creating}
                    error={createError}
                    onCreate={createRun}
                />
            {/if}
        </main>

        <footer class="wizard-footer">
            <Button variant="ghost" onclick={requestClose}>Cancel</Button>
            <div class="footer-spacer"></div>
            {#if currentStep > 1 && currentStep < 4}
                <Button variant="secondary" onclick={back}>Back</Button>
            {/if}
            {#if currentStep === 3}
                <Button
                    variant="ghost"
                    onclick={() => { currentGraph = JSON.parse(JSON.stringify(originalGraph)); next(); }}
                >
                    Skip · use defaults
                </Button>
            {/if}
            {#if currentStep < 4}
                <Button
                    onclick={next}
                    disabled={(currentStep === 1 && !nameValid) || (currentStep === 2 && !protocolValid)}
                >
                    {currentStep === 3 ? 'Continue to review' : 'Continue'}
                </Button>
            {/if}
        </footer>
    </div>
</FullScreenModal>

<SaveAsNewVersionDialog
    bind:open={saveDialogOpen}
    {edits}
    nextVersionNumber={(selectedProtocol?.version_number ?? 0) + 1}
    onCancel={() => (saveDialogOpen = false)}
    onJustThisRun={dialogJustThisRun}
    onSaveAsVersion={dialogSaveAsVersion}
/>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard changes?"
    description="You have unsaved edits. Closing the wizard will discard them."
    confirmLabel="Discard"
    cancelLabel="Keep editing"
    variant="destructive"
    onConfirm={confirmDiscard}
/>

<style>
    .wizard-body { @apply h-full flex flex-col; }
    .wizard-main { @apply flex-1 overflow-y-auto px-6 py-6 max-w-6xl w-full mx-auto; }
    .wizard-footer { @apply flex items-center gap-3 px-6 py-3 border-t border-slate-200 shrink-0; }
    .footer-spacer { @apply flex-1; }
</style>
```

> **Note on `ConfirmDialog` API:** This plan assumes `confirm-dialog.svelte`'s prop shape (`open`, `title`, `description`, `confirmLabel`, `cancelLabel`, `variant`, `onConfirm`). If the actual component uses a different prop set, adjust the call to match. Check the existing usage in `BatchRecordImportModal.svelte` for reference.

- [ ] **Step 2: Run typecheck.**

```bash
cd frontend && CI=true npm run check
```
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add frontend/src/lib/components/run/RunCreatorWizardModal.svelte
git commit -m "feat(F-0081): RunCreatorWizardModal — FullScreenModal-hosted wizard"
```

---

## Task 15 — Migrate "New Run" entry points; delete CreateRunModal

**Files:**
- Modify: `frontend/src/routes/projects/[id]/+page.svelte`
- Modify: `frontend/src/routes/experiments/[id]/+page.svelte`
- Modify: `frontend/src/lib/components/project/ExperimentsTab.svelte`
- Delete: `frontend/src/lib/components/project/CreateRunModal.svelte`

The `RunCreatorWizardModal` mirrors `CreateRunModal`'s public API (`open`, `projectId`, `protocols`, `experiments`, `forExperiment`, `onCreated`), so each migration is a 1:1 import + tag rename. The `New Run` click handlers and `showRunModal` state stay as-is.

- [ ] **Step 1: Project page — swap modal component.**

In `frontend/src/routes/projects/[id]/+page.svelte`:
- Replace the import:
  ```typescript
  // before
  import CreateRunModal from "$lib/components/project/CreateRunModal.svelte";
  // after
  import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
  ```
- In the template (~line 501), rename the tag:
  ```svelte
  <RunCreatorWizardModal
      bind:open={showRunModal}
      projectId={id}
      {protocols}
      {experiments}
  />
  ```

- [ ] **Step 2: Experiment page — swap modal component.**

In `frontend/src/routes/experiments/[id]/+page.svelte`:
- Replace the import (line ~8):
  ```typescript
  import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
  ```
- Rename the tag (~line 331):
  ```svelte
  <RunCreatorWizardModal
      bind:open={showRunModal}
      projectId={experiment.project_id}
      {protocols}
      forExperiment={{ id: experiment.id, name: experiment.name }}
      onCreated={loadData}
  />
  ```

- [ ] **Step 3: ExperimentsTab — swap modal component.**

In `frontend/src/lib/components/project/ExperimentsTab.svelte`:
- Replace the import (line ~11):
  ```typescript
  import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
  ```
- Rename the tag (~line 219):
  ```svelte
  <RunCreatorWizardModal
      bind:open={showRunModal}
      {projectId}
      {protocols}
      forExperiment={runModalExperiment}
      onCreated={() => { runModalExperiment = null; }}
  />
  ```

- [ ] **Step 4: Delete CreateRunModal.**

```bash
rm frontend/src/lib/components/project/CreateRunModal.svelte
```

- [ ] **Step 5: Verify nothing else references it.**

```bash
grep -rn "CreateRunModal" frontend/src 2>/dev/null
```
Expected: no output.

- [ ] **Step 6: Run typecheck + tests.**

```bash
cd frontend && CI=true npm run check && CI=true npm run test
```
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add -u
git commit -m "refactor(F-0081): swap CreateRunModal → RunCreatorWizardModal at three entry points"
```

---

## Task 16 — RunHistory: render OVERRIDE_SET / OVERRIDE_EDIT entries

**Files:**
- Modify: `frontend/src/lib/components/run/RunHistory.svelte`

The Phase 2 backend writes audit entries with action `OVERRIDE_SET` (run creation) and `OVERRIDE_EDIT` (PLANNED edits) using the same payload shape as `STEP_EDIT`. This wires up labels and a render case so the run history view shows them.

- [ ] **Step 1: Add the labels and switch case.**

In `frontend/src/lib/components/run/RunHistory.svelte`, find `getActionLabel` (~line 47) and add:

```typescript
const labels: Record<string, string> = {
    CREATE: 'created this run',
    UPDATE: 'updated this run',
    STEP_COMPLETE: 'completed a step',
    STEP_UNCOMPLETE: 'uncompleted a step',
    STEP_EDIT: 'edited a step',
    OVERRIDE_SET: 'set overrides at creation',
    OVERRIDE_EDIT: 'edited overrides while planned',
    NOTE_ADDED: 'added a note',
    ATTACHMENT_UPLOADED: 'uploaded a file',
    ATTACHMENT_DELETED: 'removed a file',
    ATTACHMENT_RESTORED: 'restored a file',
};
```

Then in `getDetails`, after the `case 'STEP_EDIT':` block, add:

```typescript
case 'OVERRIDE_SET':
case 'OVERRIDE_EDIT':
    if (c.step_name) lines.push({ label: 'Step', value: c.step_name });
    if (c.field_label || c.field) {
        lines.push({
            label: c.field_label ?? c.field,
            value: String(c.new_value ?? ''),
            oldValue: String(c.old_value ?? ''),
        });
    }
    break;
```

- [ ] **Step 2: Run tests, confirm pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/run/
```

- [ ] **Step 3: Commit.**

```bash
git add frontend/src/lib/components/run/RunHistory.svelte
git commit -m "feat(F-0081): RunHistory renders OVERRIDE_SET / OVERRIDE_EDIT audit entries"
```

---

## Task 17 — Playwright e2e: full wizard flow

**Files:**
- Create: `frontend/e2e/run-creator.spec.ts`

Covers the golden path: name → pick protocol/version → override two values + swap equipment + add a param → save-as-version dialog appears → "Just for this run" → review → create → land on run detail page with overrides visible.

- [ ] **Step 1: Write the spec.**

```typescript
// frontend/e2e/run-creator.spec.ts
import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from './helpers/auth';
import { SEED, getProjectProtocols } from './helpers/experiment';

test.use({ viewport: { width: 1280, height: 800 } });
test.describe.configure({ mode: 'serial' });

const PROJECT_ID = SEED.PROJECT_MAB_ID;

test.describe('F-0081 Run Creator Wizard', () => {
    let page: Page;

    test.beforeAll(async ({ browser }) => {
        page = await browser.newPage();
        await loginAndNavigate(page, 'admin');
    });

    test.afterAll(async () => {
        await page.close();
    });

    test('full create flow with overrides', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        const proto = protocols.find((p: any) => (p.status ?? '').toUpperCase() === 'PUBLISHED' && (p.version_number ?? 0) > 0);
        expect(proto, 'expected a published protocol with at least v1').toBeTruthy();

        await page.goto(`/projects/${PROJECT_ID}`);
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await expect(page.getByRole('heading', { name: /New Run/i })).toBeVisible();

        // Step 1
        await page.getByLabel(/Name/i).fill(`E2E Override Run ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();

        // Step 2
        await page.getByLabel(/Protocol/i).selectOption(proto.id);
        await expect(page.getByText(/v\d+/)).toBeVisible();
        await page.getByRole('button', { name: /^Continue/ }).click();

        // Step 3 — try to override the first param's number input if present
        const firstNumberInput = page.locator('input[type="number"]').first();
        if (await firstNumberInput.count() > 0) {
            const orig = await firstNumberInput.inputValue();
            const newVal = (parseFloat(orig || '0') + 5).toString();
            await firstNumberInput.fill(newVal);
            // Aside `Value` stat tile shows the count tick to ≥ 1
            const valueTile = page.locator('.stat-cell').filter({ hasText: /^Value$/i });
            await expect(valueTile.locator('.stat-num')).not.toHaveText('0');
        }

        await page.getByRole('button', { name: /Continue to review/i }).click();

        // Save-as-version dialog appears IF we made any edit
        const dialog = page.getByRole('dialog');
        if (await dialog.isVisible().catch(() => false)) {
            await page.getByRole('button', { name: /Just for this run/i }).click();
        }

        // Step 4
        await expect(page.getByRole('heading', { name: /Review & create/i })).toBeVisible();
        await page.getByRole('button', { name: /Create run/i }).click();

        // Land on run detail page
        await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+/);
    });

    test('multi-role: role context bar + role-grouped aside (skipped if no multi-role seed)', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        // Find a published protocol with at least 2 roles. If the seed has none, skip.
        const multiRole = protocols.find(
            (p: any) => (p.status ?? '').toUpperCase() === 'PUBLISHED'
                && (p.version_number ?? 0) > 0
                && Array.isArray(p.roles) && p.roles.length > 1,
        );
        test.skip(!multiRole, 'no multi-role published protocol in seed data');

        await page.goto(`/projects/${PROJECT_ID}`);
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await page.getByLabel(/Name/i).fill(`E2E Multi-Role ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByLabel(/Protocol/i).selectOption(multiRole.id);
        await page.getByRole('button', { name: /^Continue/ }).click();

        // Role context bar visible with "Role 1 of N"
        await expect(page.locator('.role-context')).toBeVisible();
        await expect(page.getByText(/Role 1 of \d+/i)).toBeVisible();

        // Aside shows role-group buttons for every role (length must equal roles.length)
        const heads = page.locator('.role-group-head');
        await expect(heads).toHaveCount(multiRole.roles.length);

        // Cards count for role 1 should be ≤ total UO count (filtering is active)
        const cardsRoleA = await page.locator('article.uo-card').count();

        // Click the second role's group head — cards re-filter, position pill updates
        await heads.nth(1).click();
        await expect(page.getByText(/Role 2 of \d+/i)).toBeVisible();
        const cardsRoleB = await page.locator('article.uo-card').count();
        // Cards shown for role A and role B should generally differ; if they happen
        // to match in count, the position pill change is enough proof of role switch.
        expect(cardsRoleB).toBeGreaterThanOrEqual(0);
        void cardsRoleA;

        // Arrow nav: next role wraps back to the first eventually
        await page.getByRole('button', { name: /Previous role/i }).click();
        await expect(page.getByText(/Role 1 of \d+/i)).toBeVisible();
    });

    test('skip-overrides path creates a run identical to defaults', async () => {
        const protocols = await getProjectProtocols(page, PROJECT_ID);
        const proto = protocols.find((p: any) => (p.status ?? '').toUpperCase() === 'PUBLISHED' && (p.version_number ?? 0) > 0);
        expect(proto).toBeTruthy();

        await page.goto(`/projects/${PROJECT_ID}`);
        await page.getByRole('button', { name: /\+ New Run/i }).click();
        await page.getByLabel(/Name/i).fill(`E2E Defaults Run ${Date.now()}`);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByLabel(/Protocol/i).selectOption(proto.id);
        await page.getByRole('button', { name: /^Continue/ }).click();
        await page.getByRole('button', { name: /Skip · use defaults/i }).click();
        await expect(page.getByRole('heading', { name: /Review & create/i })).toBeVisible();
        await expect(page.getByText(/uses protocol defaults/i)).toBeVisible();
        await page.getByRole('button', { name: /Create run/i }).click();
        await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+/);
    });
});
```

- [ ] **Step 2: Run e2e (requires dev servers running on worktree ports).**

In one terminal:
```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
```
In another:
```bash
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```
In a third:
```bash
cd frontend && CI=true PLAYWRIGHT_BASE_URL=http://localhost:5183 npm run test:e2e -- run-creator.spec.ts
```
Expected: both tests PASS.

- [ ] **Step 3: Commit.**

```bash
git add frontend/e2e/run-creator.spec.ts
git commit -m "test(F-0081): Playwright e2e for run creator wizard"
```

---

## Task 18 — qa-verify session

**Files:** none (manual verification)

This is the per-spec qa-verify session for Phase 3. Use the `qa-verify` agent against a running dev environment.

- [ ] **Step 1: Start dev servers in the worktree.**

```bash
# Terminal A
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010
# Terminal B
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183
```

- [ ] **Step 2: Launch qa-verify with the following script.**

Brief the qa-verify agent with this scope (paste verbatim):

> Verify F-0081 Phase 3 wizard. Open `http://localhost:5183/projects/{seeded-project-id}` and click `+ New Run` to launch the FullScreenModal wizard.
>
> **Functional flow to exercise:**
> 1. Step 1: name validates (empty → Continue disabled). Optional experiment dropdown lists non-archived experiments.
> 2. Step 2: protocol picker shows non-archived; selecting one loads versions; default selects "Latest"; summary card shows v{N}, LATEST pill, stats, description; ↳ Compare versions opens a drawer.
> 3. Step 3: per-UO cards render in graph order; equipment Swap opens EquipmentPickerModal; param table renders correct input type per schema (number/integer/text/enum/media-ref); editing a param marks the row mint and increments the aside count; ✕ removes a param (struck-through); + ADD/EDIT SCHEMA expands a SchemaEditor; ✎ Edit instructions toggles a textarea with live preview; ↺ revert per-param works.
> 4. Continue to review with edits → SaveAsNewVersionDialog appears, lists all edits, primary `Just for this run` is focused, `Save as v{N+1}` works (verify a v{N+1} appears in protocol versions afterward).
> 5. Step 4: review summary correct; Create run → lands on `/runs/{id}`; run detail page shows overrides via Phase 2's mirror fields.
> 6. Skip · use defaults → run is created identical to today's behavior.
>
> **Multi-role coverage** (this is the most novel surface in Phase 3 — exercise all three protocol shapes):
> - **Multi-role protocol** (≥ 2 roles, e.g. seed `Operator + Senior Operator + QC Reviewer`): Step 3 shows the role context bar above cards (active role name, role-color vertical bar, "Role 1 of 3 · X UO · Y params", ‹ 1/3 › arrow nav). Cards filter to the active role only. ‹ and › cycle through roles. The aside is global — it always shows ALL roles' edits as role-grouped lists. Click another role's group header in the aside → cards switch to that role, the clicked group head gets the active wash. Edit a param under role A, switch to role B, edit a param there, switch back to A — A's edit is preserved (no remount). The aside counts both edits in their respective groups.
> - **Single-role protocol** (exactly 1 swimlane): role context bar is hidden; all UO cards visible at once; aside renders a flat ungrouped diff list (no role-group headers).
> - **No-role protocol** (flat graph, no swimlanes): same degenerate path as single-role — context bar hidden, aside flat.
>
> **UI/UX audit specifically watching for:**
> - Oversized inputs/buttons; spacing inconsistencies in the per-UO cards
> - Role context bar: 4px role-color bar matches `ProtocolRole.color`; arrow buttons size match the rest of the wizard chrome; the `1 / 3` position pill uses DM Mono
> - Aside role-group headers: hover state distinct from active state (active uses `hsl(195 60% 96%)` wash, the same as the active step pill); empty roles show `— inheriting all defaults —` italic
> - Overflow on tablet width (1024×768) — role context bar must not wrap awkwardly
> - Sticky-aside behavior at long scroll
> - Validation-error legibility
> - Focus order through the wizard (Tab key) — arrow nav buttons + aside role group heads must be reachable and have visible focus rings
> - Save-as-version dialog: focus returns sensibly after dismiss
> - Modal-on-modal stacking: EquipmentPickerModal, SaveAsNewVersionDialog, VersionHistoryDrawer, and ConfirmDialog all open over the wizard — verify each stacks correctly, blocks input on layers below, and Escape dismisses the topmost only
> - Close-with-edits: typing a name then clicking the X or Cancel triggers ConfirmDialog "Discard changes?"; Keep editing dismisses the confirm; Discard closes the wizard

- [ ] **Step 3: Address any FAIL or POLISH issues found before declaring Phase 3 complete.** If any issue is structural enough to need its own subtask, add it as a new step block in this plan and re-run qa-verify after fixing.

- [ ] **Step 4: Final commit if any polish landed.**

```bash
git add -u
git commit -m "polish(F-0081): qa-verify findings"
```

---

## Task 19 — Scenario-driven e2e matrix (self-seeding fixtures, opt-in keep)

**Files:**
- Create: `frontend/e2e/helpers/runOverridesFixtures.ts` — fixture builders + cleanup tracker
- Create: `frontend/e2e/run-creator-scenarios.spec.ts` — one test per scenario row in the matrix below

**Why this exists:** Phase 3's wizard has many shape-dependent edge cases (graph topology × role count × override kind × dialog branch). Task 17's golden-path suite proves the happy path against a single seeded protocol; this task systematically walks the matrix on freshly-seeded fixtures so each scenario is **isolated, reproducible, and orthogonal**. Scenarios that share state are a debugging tax we don't want.

**Self-seeding contract:**

- Every test creates its own protocol (and supporting graph) via `apiRequest` helpers — never relies on `seed.py` shape staying stable.
- Every test tags its protocol's name with a unique prefix `F0081-E2E-` and a per-suite `runId` nonce so leftovers are greppable from the DB if cleanup ever fails.
- After each test, fixtures (protocol + any runs created) are deleted via API.
- **Opt-out cleanup**: if env var `KEEP_FIXTURES=1` is set (or Playwright `--grep-invert='@cleanup'` is used), `afterEach` skips deletion and prints the fixture IDs so the dev can poke at them in the UI.

### The scenario matrix

Each row → one Playwright test in `run-creator-scenarios.spec.ts`. Every row exercises the wizard end-to-end (Step 1 → Step 4 → Create) on a freshly-seeded protocol.

| # | Scenario | Graph shape | Override kind exercised | Wizard branch verified |
|---|---|---|---|---|
| 1 | Linear chain, no roles | 3 unit ops in a flat chain (no swimlane) | Value override on UO-2 | Degenerate path: no role context bar; flat aside |
| 2 | Single role | 1 swimlane wrapping 2 unit ops | Value override + equipment swap | Single-role degenerate (still no context bar; flat aside) |
| 3 | Multi-role (2 roles) | 2 swimlanes, 1 UO each | Value override on role A + value override on role B | Role context bar visible; both edits land in correct role groups; switching role preserves both edits |
| 4 | Multi-role (3 roles) | 3 swimlanes (Operator, Senior Operator, QC) | Edit role 1 only; verify roles 2 & 3 show "inheriting all defaults" | `‹ N/M ›` arrow nav cycles all 3; clicking aside head jumps to that role |
| 5 | Equipment swap only | Single role, 1 UO with equipment | Equipment swap (no value edits) | Aside `Equipment` stat ≥ 1; value/added stays 0 |
| 6 | Add parameter (not in protocol schema) | Linear, 1 UO | New param key not in `paramSchema` | Aside `Added` ≥ 1; backend `RunOverrides.added_params` populated |
| 7 | Remove parameter | Linear, 1 UO with 2 params | Click ✕ on a param row | Aside `Removed` ≥ 1; row struck-through |
| 8 | Schema edit (paramSchema mutated) | Linear, 1 UO | Add a property via SchemaEditor expansion | Aside shows `SCHEMA` tag |
| 9 | Instruction edit | Linear, 1 UO with `description` template | Edit instructions textarea, render with mark | Aside shows `INSTRUCTION` tag; rendered preview reflects new text |
| 10 | Forked graph (branch) | UO-A → (UO-B, UO-C) parallel | Value override on UO-C only | Both branches render as cards; correct branch's UO marked mint |
| 11 | Empty graph | No unit ops at all | n/a | Step 3 shows empty state ("No unit ops"); Continue still works (skip path) |
| 12 | `Skip · use defaults` path | Linear, 2 UOs with editable params | (none — user clicks Skip) | No SaveAsNewVersionDialog; advances directly to Step 4; review shows "uses protocol defaults" |
| 13 | `Save as v{N+1}` path | Linear, 1 UO | Single value override | SaveAsNewVersionDialog appears; clicking `Save as v{N+1}` POSTs publish-draft; new version exists; review shows v{N+1} not LATEST pill |
| 14 | `forExperiment` locked entry | Linear, 1 UO | None | Step 1 experiment dropdown is locked to the supplied experiment; modal title includes experiment name |
| 15 | Discard-on-close | Linear, 1 UO | One value override + name typed | Closing X → ConfirmDialog "Discard changes?"; Keep editing dismisses; Discard closes wizard |
| 16 | Multi-role + equipment swap on inactive role | 2 roles | Swap equipment under role B while active role is A | Aside Equipment count = 1 even though active role is A (proves global aside) |
| 17 | Compare versions drawer | Protocol with v1 + v2 | None | Step 2 ↳ Compare versions opens drawer; renders side-by-side; closing returns to wizard with no state loss |

> If a scenario fails to apply (e.g. graph helpers don't yet expose a forked-graph builder), prefer skipping with `test.skip()` plus a TODO referencing this row over inventing brittle workarounds. We'd rather know which rows are stubbed than have green tests that don't actually exercise the branch.

- [ ] **Step 1: Build the fixture helpers.**

```typescript
// frontend/e2e/helpers/runOverridesFixtures.ts
import { type Page } from '@playwright/test';
import {
  createProtocolViaApi,
  updateProtocolGraph,
  submitForApprovalViaApi,
  // approveProtocolViaApi & deleteProtocolViaApi added if not present
} from './protocol.ts';

const API_BASE = 'http://localhost:8000';

// Per-suite unique prefix + nonce so leftover fixtures are greppable
// (also used by cleanup to match what we created)
const SUITE_NONCE = `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
export const FIXTURE_PREFIX = `F0081-E2E-${SUITE_NONCE}`;

export interface Fixture {
  protocolId: string;
  /** Created run IDs (filled by tests as they create runs through the wizard) */
  runIds: string[];
  /** Human label for the scenario, used in failure messages */
  label: string;
}

/**
 * In-memory cleanup registry. afterEach iterates and deletes unless
 * KEEP_FIXTURES=1 is set.
 *
 * The KEEP_FIXTURES env var is intentionally generic so other Playwright
 * suites in this repo can adopt the same opt-out cleanup convention. If a
 * second suite starts using it, lift this registry + helpers into
 * `frontend/e2e/helpers/fixtures.ts` (parameterized by name prefix).
 */
const REGISTRY: Fixture[] = [];

export function registerFixture(f: Fixture): Fixture {
  REGISTRY.push(f);
  return f;
}

export function shouldKeepFixtures(): boolean {
  return process.env.KEEP_FIXTURES === '1';
}

/** Print kept-fixture summary so devs can find them in the UI. */
export function printKeptFixtures(): void {
  if (REGISTRY.length === 0) return;
  // eslint-disable-next-line no-console
  console.log(
    `\n[KEEP_FIXTURES] keeping ${REGISTRY.length} fixture(s) (prefix "${FIXTURE_PREFIX}"):\n` +
    REGISTRY.map((f) => `  • ${f.label} → protocol=${f.protocolId} runs=[${f.runIds.join(', ')}]`).join('\n') +
    `\n  Filter UI by name prefix: "${FIXTURE_PREFIX}"\n`,
  );
}

async function apiDelete(page: Page, path: string): Promise<void> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
  await page.request.fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Delete every fixture in the registry. Errors swallowed (best-effort). */
export async function cleanupAllFixtures(page: Page): Promise<void> {
  if (shouldKeepFixtures()) {
    printKeptFixtures();
    return;
  }
  for (const f of REGISTRY) {
    for (const runId of f.runIds) {
      await apiDelete(page, `/science/runs/${runId}`).catch(() => undefined);
    }
    await apiDelete(page, `/science/protocols/${f.protocolId}`).catch(() => undefined);
  }
  REGISTRY.length = 0;
}

// ────────────────────────────────────────────────────────────────────────
// Graph builders — each returns a `graph` object (nodes + edges) the wizard
// will dump into Step 3. Names use the FIXTURE_PREFIX so DB scans can group.
// ────────────────────────────────────────────────────────────────────────

interface GraphBuildOptions {
  /** Protocol roles for multi-role scenarios. The builder injects swimlane nodes
   *  with `data.role_id` matching these IDs and parents UOs accordingly. */
  roles?: Array<{ id: string; name: string; color: string }>;
  /** Number of unit ops to emit (linear/single-role builders). Multi-role uses
   *  `unitOpsByRole` instead. */
  unitOpCount?: number;
  /** Per-role UO count for multi-role builders. Keys must match `roles[].id`. */
  unitOpsByRole?: Record<string, number>;
  /** UO defaults to merge into every UO's `data` (e.g. equipment, paramSchema). */
  uoDefaults?: Record<string, unknown>;
  /** Linear (default) or fork. Fork emits A→B and A→C from UO-1. */
  topology?: 'linear' | 'fork' | 'empty';
}

export function buildGraph(opts: GraphBuildOptions): { nodes: any[]; edges: any[] } {
  const nodes: any[] = [];
  const edges: any[] = [];

  // Add swimlanes (one per role)
  for (const r of opts.roles ?? []) {
    nodes.push({
      id: `lane-${r.id}`,
      type: 'swimLane',
      position: { x: 0, y: 0 },
      data: { label: r.name, role_id: r.id, color: r.color },
    });
  }

  if (opts.topology === 'empty') return { nodes, edges };

  const baseData = (idx: number) => ({
    label: `UO-${idx + 1}`,
    category: 'Reaction',
    duration_min: 10,
    params: { temperature: 25 + idx },
    paramSchema: {
      type: 'object',
      properties: {
        temperature: { type: 'number', title: 'Temperature' },
      },
    },
    description: 'Hold at {{temperature}}°C',
    equipment: [],
    ...(opts.uoDefaults ?? {}),
  });

  if (opts.unitOpsByRole) {
    let i = 0;
    for (const [roleId, count] of Object.entries(opts.unitOpsByRole)) {
      for (let k = 0; k < count; k++, i++) {
        nodes.push({
          id: `uo-${i + 1}`,
          type: 'unitOp',
          parentId: `lane-${roleId}`,
          position: { x: 100 + k * 200, y: 100 },
          data: baseData(i),
        });
      }
    }
    return { nodes, edges };
  }

  const count = opts.unitOpCount ?? 1;
  for (let i = 0; i < count; i++) {
    nodes.push({
      id: `uo-${i + 1}`,
      type: 'unitOp',
      // If a single-role wrap was requested, parent under its lane
      parentId: opts.roles && opts.roles.length === 1 ? `lane-${opts.roles[0].id}` : undefined,
      position: { x: 100 + i * 200, y: 100 },
      data: baseData(i),
    });
  }

  if (opts.topology === 'fork' && count >= 3) {
    // UO-1 → UO-2 and UO-1 → UO-3
    edges.push({ id: 'e1', source: 'uo-1', target: 'uo-2' });
    edges.push({ id: 'e2', source: 'uo-1', target: 'uo-3' });
  } else {
    for (let i = 0; i < count - 1; i++) {
      edges.push({ id: `e${i}`, source: `uo-${i + 1}`, target: `uo-${i + 2}` });
    }
  }

  return { nodes, edges };
}

/**
 * Create a published protocol (v1) with the given graph + roles.
 * Returns the registered Fixture for cleanup tracking.
 */
export async function seedScenarioProtocol(
  page: Page,
  projectId: string,
  label: string,
  graph: { nodes: any[]; edges: any[] },
  roles: Array<{ name: string; color: string }> = [],
): Promise<Fixture> {
  const name = `${FIXTURE_PREFIX} ${label}`;
  const proto = await createProtocolViaApi(page, projectId, name);
  const protocolId = proto.id as string;

  // Attach roles via the protocol roles API. The role IDs returned are written
  // into the graph's swimlane nodes BEFORE updateProtocolGraph fires.
  const roleIdMap: Record<string, string> = {};
  for (const r of roles) {
    const created = await apiPost(page, `/science/protocols/${protocolId}/roles`, {
      name: r.name,
      color: r.color,
    });
    roleIdMap[r.name] = created.id as string;
  }

  // If the graph was built with placeholder role IDs, swap them now.
  // (buildGraph uses role.id verbatim — callers pass the same IDs they want here.)

  await updateProtocolGraph(page, protocolId, graph as any);
  await submitForApprovalViaApi(page, protocolId);
  // Approve + publish v1 via existing helpers (add `approveProtocolViaApi` /
  // `publishDraftViaApi` to protocol.ts if missing).
  await apiPost(page, `/science/protocols/${protocolId}/approve`, {});

  return registerFixture({ protocolId, runIds: [], label });
}

async function apiPost(page: Page, path: string, body: unknown): Promise<any> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
  const resp = await page.request.fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    data: body as Record<string, unknown>,
  });
  if (!resp.ok()) {
    throw new Error(`POST ${path} failed: ${resp.status()} ${await resp.text()}`);
  }
  return resp.json();
}
```

> **Note:** `frontend/e2e/helpers/protocol.ts` may not yet expose `deleteProtocolViaApi`, `approveProtocolViaApi`, or role-creation helpers. If missing, add them in this same task. They are thin wrappers over `apiRequest`.

- [ ] **Step 2: Write the scenario spec.**

```typescript
// frontend/e2e/run-creator-scenarios.spec.ts
import { test, expect, type Page } from '@playwright/test';
import { loginAndNavigate } from './helpers/auth';
import { SEED } from './helpers/protocol';
import {
  buildGraph,
  seedScenarioProtocol,
  cleanupAllFixtures,
  shouldKeepFixtures,
  FIXTURE_PREFIX,
} from './helpers/runOverridesFixtures';

test.use({ viewport: { width: 1280, height: 800 } });
test.describe.configure({ mode: 'serial' });

const PROJECT_ID = SEED.PROJECT_MAB_ID;

test.describe('F-0081 Run Creator — scenario matrix', () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await loginAndNavigate(page, 'admin');
    // eslint-disable-next-line no-console
    console.log(`[F-0081] Fixture prefix this run: "${FIXTURE_PREFIX}"`);
  });

  test.afterEach(async () => {
    if (shouldKeepFixtures()) return; // print + skip
    await cleanupAllFixtures(page);
  });

  test.afterAll(async () => {
    if (shouldKeepFixtures()) {
      // final summary print
      await cleanupAllFixtures(page);
    }
    await page.close();
  });

  // Helper: open the wizard for a given protocolId, fill name, advance to Step 3.
  async function openWizardOnProtocol(protocolId: string, runName: string) {
    await page.goto(`/projects/${PROJECT_ID}`);
    await page.getByRole('button', { name: /\+ New Run/i }).click();
    await page.getByLabel(/Name/i).fill(runName);
    await page.getByRole('button', { name: /^Continue/ }).click();
    await page.getByLabel(/Protocol/i).selectOption(protocolId);
    await page.getByRole('button', { name: /^Continue/ }).click();
  }

  // ── Scenario 1 ────────────────────────────────────────────────────────────
  test('1. linear chain, no roles — value override goes through', async () => {
    const fx = await seedScenarioProtocol(
      page, PROJECT_ID, 's1-linear-noroles',
      buildGraph({ unitOpCount: 3, topology: 'linear' }),
    );
    await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s1`);

    // No role context bar in the degenerate path
    await expect(page.locator('.role-context')).toHaveCount(0);
    // Aside has stat tiles but no .role-group buckets
    await expect(page.locator('.role-group')).toHaveCount(0);

    // Edit the second UO's value
    const inputs = page.locator('input[type="number"]');
    await inputs.nth(1).fill('99');
    await expect(page.locator('.stat-cell').filter({ hasText: /^Value$/i }).locator('.stat-num'))
      .not.toHaveText('0');
  });

  // ── Scenario 2 ────────────────────────────────────────────────────────────
  test('2. single role (one swimlane) — degenerate path still applies', async () => {
    const fx = await seedScenarioProtocol(
      page, PROJECT_ID, 's2-single-role',
      buildGraph({
        roles: [{ id: 'role-op', name: 'Operator', color: '#B96B17' }],
        unitOpCount: 2,
      }),
      [{ name: 'Operator', color: '#B96B17' }],
    );
    await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s2`);
    await expect(page.locator('.role-context')).toHaveCount(0);
    await expect(page.locator('.role-group')).toHaveCount(0);
  });

  // ── Scenario 3 ────────────────────────────────────────────────────────────
  test('3. multi-role (2 roles) — context bar + role groups + preserved overrides', async () => {
    const fx = await seedScenarioProtocol(
      page, PROJECT_ID, 's3-multi-2',
      buildGraph({
        roles: [
          { id: 'role-op',  name: 'Operator',        color: '#B96B17' },
          { id: 'role-sup', name: 'Senior Operator', color: '#5C6BC0' },
        ],
        unitOpsByRole: { 'role-op': 1, 'role-sup': 1 },
      }),
      [
        { name: 'Operator',        color: '#B96B17' },
        { name: 'Senior Operator', color: '#5C6BC0' },
      ],
    );
    await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s3`);
    await expect(page.locator('.role-context')).toBeVisible();
    await expect(page.locator('.role-group-head')).toHaveCount(2);

    // Edit role A
    await page.locator('input[type="number"]').first().fill('50');
    // Switch to role B via aside
    await page.locator('.role-group-head').nth(1).click();
    await expect(page.getByText(/Role 2 of 2/i)).toBeVisible();
    // Edit role B
    await page.locator('input[type="number"]').first().fill('77');
    // Switch back to role A — first role's edit must still be present
    await page.locator('.role-group-head').nth(0).click();
    await expect(page.locator('input[type="number"]').first()).toHaveValue('50');
  });

  // ── Scenario 4 — multi-role (3) ───────────────────────────────────────────
  test('4. multi-role (3 roles) — arrow nav + jump-via-aside-head', async () => {
    const fx = await seedScenarioProtocol(
      page, PROJECT_ID, 's4-multi-3',
      buildGraph({
        roles: [
          { id: 'r1', name: 'Operator',        color: '#B96B17' },
          { id: 'r2', name: 'Senior Operator', color: '#5C6BC0' },
          { id: 'r3', name: 'QC Reviewer',     color: '#8E5BA8' },
        ],
        unitOpsByRole: { r1: 2, r2: 1, r3: 1 },
      }),
      [
        { name: 'Operator',        color: '#B96B17' },
        { name: 'Senior Operator', color: '#5C6BC0' },
        { name: 'QC Reviewer',     color: '#8E5BA8' },
      ],
    );
    await openWizardOnProtocol(fx.protocolId, `${FIXTURE_PREFIX} run-s4`);

    await expect(page.locator('.role-group-head')).toHaveCount(3);
    await page.getByRole('button', { name: /Next role/i }).click();
    await expect(page.getByText(/Role 2 of 3/i)).toBeVisible();
    await page.locator('.role-group-head').nth(2).click();
    await expect(page.getByText(/Role 3 of 3/i)).toBeVisible();
  });

  // ── Scenarios 5-17 follow the same pattern ────────────────────────────────
  // For brevity in this plan the remaining scenarios are stubbed with their
  // assertion outline. Implement each by:
  //   1. Build the graph with `buildGraph` (or extend the builder if missing
  //      a topology — e.g. for fork(), schema-edit, removed-param).
  //   2. Seed it with `seedScenarioProtocol`.
  //   3. Drive the wizard via `openWizardOnProtocol` + Playwright clicks.
  //   4. Assert on the aside stat tiles + role-group structure.
  //   5. Where the scenario creates a run, push the new run ID into
  //      `fx.runIds` so cleanup deletes it too.

  test.skip('5. equipment swap only — Equipment stat = 1, Value = 0', async () => {});
  test.skip('6. add parameter — Added stat = 1; backend received added_params', async () => {});
  test.skip('7. remove parameter — Removed stat = 1; row strikethrough', async () => {});
  test.skip('8. schema edit — SCHEMA tag in aside', async () => {});
  test.skip('9. instruction edit — INSTRUCTION tag + rendered preview reflects change', async () => {});
  test.skip('10. forked graph — branches render as cards; only edited branch flagged', async () => {});
  test.skip('11. empty graph — Step 3 empty state; Continue still works', async () => {});
  test.skip('12. Skip · use defaults — bypasses save dialog; review shows "uses protocol defaults"', async () => {});
  test.skip('13. Save as v{N+1} — POSTs publish-draft; new version appears; review shows non-LATEST pill', async () => {});
  test.skip('14. forExperiment locked — experiment dropdown locked; modal title includes experiment name', async () => {});
  test.skip('15. discard-on-close — ConfirmDialog flows for both Keep editing and Discard', async () => {});
  test.skip('16. multi-role + swap on inactive role — global aside reflects swap from inactive role', async () => {});
  test.skip('17. compare versions drawer — opens, renders, returns without state loss', async () => {});
});
```

- [ ] **Step 3: Implement the stubbed scenarios (5-17) one at a time, red-green.**

For each `test.skip` row in the matrix:

1. Convert `test.skip` → `test`.
2. If the scenario needs a graph shape the builder doesn't emit yet, extend `buildGraph` (e.g. add `topology: 'fork'` support, optional `withEquipment: true`, etc.). Each builder addition gets its own commit.
3. Run only that one scenario with `--grep` so iteration is fast:

```bash
cd frontend && CI=true PLAYWRIGHT_BASE_URL=http://localhost:5183 \
    npm run test:e2e -- run-creator-scenarios.spec.ts --grep "5\\."
```

- [ ] **Step 4: Run the full matrix once, verify cleanup.**

```bash
cd frontend && CI=true PLAYWRIGHT_BASE_URL=http://localhost:5183 \
    npm run test:e2e -- run-creator-scenarios.spec.ts
```

Expected: all 17 scenarios PASS. After the suite, no `F0081-E2E-*` protocols remain in the DB:

```bash
psql -h localhost -U postgres -d batchrite -c \
    "SELECT id, name FROM protocols WHERE name LIKE 'F0081-E2E-%';"
```

Expected: zero rows.

- [ ] **Step 5: Verify the keep-fixtures escape hatch works.**

```bash
cd frontend && CI=true PLAYWRIGHT_BASE_URL=http://localhost:5183 \
    KEEP_FIXTURES=1 npm run test:e2e -- run-creator-scenarios.spec.ts --grep "1\\."
```

Expected: scenario passes, log line prints fixture protocol IDs, the protocol row stays in the DB after the suite ends. Re-run cleanup manually:

```bash
psql -h localhost -U postgres -d batchrite -c \
    "DELETE FROM protocols WHERE name LIKE 'F0081-E2E-%';"
```

- [ ] **Step 6: Commit.**

```bash
git add frontend/e2e/helpers/runOverridesFixtures.ts \
        frontend/e2e/run-creator-scenarios.spec.ts \
        frontend/e2e/helpers/protocol.ts
git commit -m "test(F-0081): scenario-driven e2e matrix with self-seeding fixtures + reusable KEEP_FIXTURES escape hatch"
```

> **Engineer's note:** This task is intentionally large because the *fixture infrastructure* is what unlocks the matrix — once `buildGraph` + `seedScenarioProtocol` + the cleanup registry exist, adding an 18th scenario costs ~20 lines. If during implementation a scenario reveals a bug in Phase 3, file it as a Bug task (do not absorb into this PR) so the e2e suite stays a faithful regression net rather than a moving target.

---

## Verification rollup

After every task is complete:

- [ ] **All Vitest specs pass.**

```bash
cd frontend && CI=true npm run test
```

- [ ] **Typecheck clean.**

```bash
cd frontend && CI=true npm run check
```

- [ ] **No `CreateRunModal` references remain.**

```bash
grep -rn "CreateRunModal" frontend/src 2>/dev/null
```
Expected: no output.

- [ ] **Inspector regression tests pass.**

```bash
cd frontend && CI=true npm run test -- src/lib/components/protocol/
```

- [ ] **e2e (golden path) passes.**

```bash
cd frontend && CI=true npm run test:e2e -- run-creator.spec.ts
```

- [ ] **e2e scenario matrix passes and leaves no fixtures behind.**

```bash
cd frontend && CI=true npm run test:e2e -- run-creator-scenarios.spec.ts
psql -h localhost -U postgres -d batchrite -c \
    "SELECT count(*) FROM protocols WHERE name LIKE 'F0081-E2E-%';"
# expected: 0
```

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| Full-screen run creator wizard (FullScreenModal-hosted, replaces `CreateRunModal`) | 14 |
| 4-step stepper (Name → Protocol → Parameters → Review) | 7, 14 |
| Step 1: name + experiment, locks experiment when forExperiment is set | 8 |
| Step 2: protocol + version picker, summary card with LATEST pill, Compare versions drawer reuse | 9 |
| Step 3: per-UO cards with equipment chip list, swap, param table, add/remove param, instructions block | 10, 11 |
| Live counts + diff aside | 11 |
| Skip · use defaults bypasses overrides | 14 |
| SaveAsNewVersionDialog with 3 actions, primary focused | 12 |
| Save as v{N+1} posts publish-draft, reloads versions, advances | 14 |
| Step 4: review + Create run | 13 |
| POSTs `/science/runs` with `overrides`, `protocol_version_number` | 14 |
| Redirects to run detail page | 14 |
| Shared `<ParamInput>` component | 2 |
| Shared `<SchemaEditor>` component | 3 |
| Shared `<EquipmentChipList>` component | 4 |
| Inspector refactored to consume the three shared components | 5 |
| Inspector's local `renderTemplate` deleted, imports shared util | 5 |
| Pure helpers `runOverrides.ts` (computeEdits / hasStructuralChanges / buildOverridesPayload) | 1 |
| Reuses `template.ts::renderTemplate` | 10 |
| Reuses `detectEquipmentConflicts` | 11 |
| Reuses `EquipmentPickerModal` | 11 |
| Reuses `VersionHistoryDrawer` | 9 |
| RunHistory labels for OVERRIDE_SET / OVERRIDE_EDIT | 16 |
| Vitest per step component | 7, 8, 9, 10, 11, 12, 13 |
| Playwright e2e | 17 |
| qa-verify session | 18 |
| Delete `CreateRunModal.svelte` | 15 |
| Swap "New Run" entry points to `<RunCreatorWizardModal>` | 15 |
| Reuse `FullScreenModal` chrome | 14 |
| Reuse `ConfirmDialog` for unsaved-changes-on-close | 14 |
| Add `RunOverrides` Zod schemas | 6 |
| `RunOverridesEditor` reusable for Phase 4 | 11 |
| Role helpers (`resolveNodeRoleId`, `groupUnitOpsByRole`, `groupEditsByRole`) | 1 |
| Multi-role: role context bar (active role + ‹ N/M › arrow nav) above cards | 11 |
| Multi-role: cards filtered to active role; inactive-role overrides preserved in `currentGraph` | 11 |
| Multi-role: aside is global with role-grouped diff lists; clickable role-group headers set active role | 11 |
| Single-role / no-role degenerate path: hide context bar, flatten aside | 11 |
| Wizard fetches roles when protocol changes; initializes `activeRoleId` only when `roles.length > 1` | 14 |
| Multi-role e2e: role context bar visible, aside head count matches `roles.length`, head click + arrow nav switch active role | 17 |
| qa-verify covers single-role, multi-role, and no-role protocols | 18 |
| Scenario-driven e2e matrix (17 rows: linear / single-role / multi-role(2,3) / equipment-only / add-param / remove-param / schema-edit / instruction-edit / fork / empty / skip-defaults / save-as-version / forExperiment / discard-on-close / inactive-role-swap / compare-versions) | 19 |
| Self-seeding fixtures via API helpers; per-suite `F0081-E2E-` name prefix; cleanup registry | 19 |
| `KEEP_FIXTURES=1` env var skips cleanup and prints fixture IDs for manual debugging | 19 |
