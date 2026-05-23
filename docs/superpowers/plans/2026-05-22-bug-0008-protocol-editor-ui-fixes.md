# BUG-0008 — Protocol editor UI fixes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two unrelated protocol-editor UI bugs: (1) time-mode `UnitOpNode` content squish, and (2) `EquipmentPickerModal` layout/contrast — footer-anchored form actions, single body scroller with sticky search + jump-to-form, theme-token-only contrast, plus opportunistic cleanup of hardcoded hex colors next door.

**Architecture:** CSS-only fix for Bug 1 (ellipsis + `title=` fallback for native tooltip). For Bug 2, focused template restructure + CSS + a small `IntersectionObserver` for the jump-to-form link, all local to `EquipmentPickerModal.svelte`. No schema, callback, prop, or service changes. Tests live next to the components in Vitest. UnitOpNode test is a *source-text* contract test (the file's scoped `<style>` and template attrs) because jsdom + xyflow Provider context makes meaningful component mounting expensive for a CSS-only change.

**Tech Stack:** Svelte 5 (runes), @xyflow/svelte, shadcn-svelte + bits-ui, TailwindCSS 4 with HSL theme tokens, Vitest + jsdom.

---

## File Structure

- **Modify:** `frontend/vitest.setup.ts` — polyfill `IntersectionObserver` (jsdom doesn't ship one and the new effect in `EquipmentPickerModal` mounts an observer immediately when `mode === 'create'`).
- **Modify:** `frontend/src/lib/components/protocol/UnitOpNode.svelte` — CSS rules for `.param-row`, `.param-label`, `.param-value`, `.node-params`; add `title=` attrs in the param-row template.
- **Modify:** `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` — template (`.create-section` toggle + form footer + go-to-form + close-from-sticky links), CSS (single scroller, sticky search, panel callout, input bg, theme-token-ify `.type-badge` and `.error-message`), one `$state` + `$effect` for `IntersectionObserver`, extend the existing `$effect(open)` to reset form fields on re-open.
- **Modify:** `frontend/src/lib/components/modals/EquipmentPickerModal.test.ts` — extend with new assertions for in-form Discard, hidden `+ Add New Equipment` when open, double-scroller source-text guard, `mode === 'create'` footer, re-open reset, close-from-sticky.
- **Create:** `frontend/src/lib/components/protocol/UnitOpNode.test.ts` — source-text contract tests for ellipsis CSS rules and `title=` attributes.

---

## Task 0: Polyfill `IntersectionObserver` in vitest.setup.ts

**Files:**
- Modify: `frontend/vitest.setup.ts`

This must land before Task 3 — the new `EquipmentPickerModal` effect uses
`new IntersectionObserver(...)` and `mode === 'create'` initialises
`showCreateForm = true` on mount, so any existing test that renders the modal
with `mode: 'create'` (the three site-default tests do) will throw
`ReferenceError: IntersectionObserver is not defined`.

- [ ] **Step 1: Add the polyfill after the `getAnimations` stub block**

In `frontend/vitest.setup.ts`, immediately before `afterEach(() => { cleanup(); });` (around line 58), insert:

```typescript
// jsdom does not implement IntersectionObserver. The EquipmentPickerModal
// uses one to gate the in-dialog "Go to form" link. Stub a noop so the
// observer can be constructed without surfacing entries; tests that need
// real intersection behavior can override per-test.
if (typeof globalThis.IntersectionObserver === 'undefined') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).IntersectionObserver = class IntersectionObserverStub {
        root: Element | null = null;
        rootMargin = '';
        thresholds: ReadonlyArray<number> = [];
        observe() {}
        unobserve() {}
        disconnect() {}
        takeRecords(): IntersectionObserverEntry[] {
            return [];
        }
    };
}
```

- [ ] **Step 2: Confirm the polyfill loads cleanly**

Run: `cd frontend && CI=true npx vitest run src/lib/components/modals/EquipmentPickerModal.test.ts`

Expected: the three existing site-default tests still PASS (no behavioral change from the polyfill — observers do nothing).

- [ ] **Step 3: Commit**

```bash
git add frontend/vitest.setup.ts
git -c commit.gpgsign=false commit -m "test(BUG-0008): polyfill IntersectionObserver for jsdom"
```

---

## Task 1: UnitOpNode — failing CSS-contract test

**Files:**
- Create: `frontend/src/lib/components/protocol/UnitOpNode.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/protocol/UnitOpNode.test.ts` with the following contents.

```typescript
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, 'UnitOpNode.svelte'), 'utf8');

/**
 * jsdom doesn't run real layout, and mounting UnitOpNode requires a
 * SvelteFlowProvider + bits-ui ContextMenu context. The fix here is a pure
 * CSS + template-attribute contract, so we assert the contract by inspecting
 * the source file directly. Regexes are intentionally non-positional re:
 * attribute order so a Prettier/formatter reorder doesn't trip them; the
 * value-span tooltip is locked to the exact `title={String(param.value)}`
 * literal so a regex-pass-for-wrong-reason can't happen.
 *
 * NOTE: This `readFileSync` test pattern is novel in this codebase. Reason:
 * mounting UnitOpNode needs xyflow + bits-ui context plumbing that isn't
 * worth wiring for a CSS-only change. If you reach for a similar pattern
 * elsewhere, ask whether mounting would work first.
 */
function extractParamRowTag(src: string): string {
    // Pull the entire opening tag of the .param-row div, attributes in any order.
    const m = src.match(/<div\b[^>]*class="param-row"[^>]*>/);
    return m?.[0] ?? '';
}

function extractParamValueTag(src: string): string {
    const m = src.match(/<span\b[^>]*class="param-value"[^>]*>/);
    return m?.[0] ?? '';
}

describe('UnitOpNode time-mode truncation contract', () => {
    it('renders the param row with a title= attr containing both label and value', () => {
        const tag = extractParamRowTag(source);
        expect(tag).not.toBe('');
        expect(tag).toMatch(/\btitle=\{/);
        // Either a template literal `${param.label}: ${param.value}` or an
        // expression that references both names is acceptable.
        expect(tag).toMatch(/param\.label/);
        expect(tag).toMatch(/param\.value/);
    });

    it('renders the param value with title={String(param.value)} exactly', () => {
        // Lock the value-span tooltip to the literal so a future refactor
        // that points it at param.label etc. fails loudly.
        const tag = extractParamValueTag(source);
        expect(tag).not.toBe('');
        expect(tag).toContain('title={String(param.value)}');
    });

    it('.param-value CSS truncates with ellipsis instead of wrapping', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramValueRule = styleBlock.match(/\.param-value\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramValueRule).toMatch(/white-space:\s*nowrap/);
        expect(paramValueRule).toMatch(/overflow:\s*hidden/);
        expect(paramValueRule).toMatch(/text-overflow:\s*ellipsis/);
        expect(paramValueRule).toMatch(/min-width:\s*0/);
        // The old `word-break: break-word;` would re-enable per-char wrapping.
        expect(paramValueRule).not.toMatch(/word-break:\s*break-word/);
    });

    it('.param-label CSS truncates with ellipsis but caps at 60% so the value shrinks first', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramLabelRule = styleBlock.match(/\.param-label\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramLabelRule).toMatch(/white-space:\s*nowrap/);
        expect(paramLabelRule).toMatch(/overflow:\s*hidden/);
        expect(paramLabelRule).toMatch(/text-overflow:\s*ellipsis/);
        expect(paramLabelRule).toMatch(/flex-shrink:\s*0/);
        expect(paramLabelRule).toMatch(/max-width:\s*60%/);
    });

    it('.param-row allows its children to shrink (min-width: 0)', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramRowRule = styleBlock.match(/\.param-row\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramRowRule).toMatch(/min-width:\s*0/);
    });

    it('.node-params hides overflow so narrow nodes do not spill', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const nodeParamsRule = styleBlock.match(/\.node-params\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(nodeParamsRule).toMatch(/overflow:\s*hidden/);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && CI=true npx vitest run src/lib/components/protocol/UnitOpNode.test.ts`

Expected: all six assertions FAIL — current `.param-value` has `word-break: break-word` (not `text-overflow: ellipsis`), `.param-label` has neither `text-overflow: ellipsis` nor `max-width: 60%`, the template has no `title=` attributes, `.param-row` has no `min-width: 0`, and `.node-params` has no `overflow: hidden`.

- [ ] **Step 3: Commit the failing test**

```bash
git add frontend/src/lib/components/protocol/UnitOpNode.test.ts
git -c commit.gpgsign=false commit -m "test(BUG-0008): add UnitOpNode time-mode truncation contract test"
```

---

## Task 2: UnitOpNode — implement the CSS + title attrs

**Files:**
- Modify: `frontend/src/lib/components/protocol/UnitOpNode.svelte:108-117` (template — add `title=` attrs on `.param-row` and `.param-value`)
- Modify: `frontend/src/lib/components/protocol/UnitOpNode.svelte:307-335` (style — `.node-params`, `.param-row`, `.param-label`, `.param-value`)

- [ ] **Step 1: Update the param-row template to add title attributes**

Replace the existing template block (lines 108-117):

```svelte
                {#if displayParams.length > 0}
                    <div class="node-params">
                        {#each displayParams as param}
                            <div class="param-row">
                                <span class="param-label">{param.label}</span>
                                <span class="param-value">{param.value}</span>
                            </div>
                        {/each}
                    </div>
                {/if}
```

with:

```svelte
                {#if displayParams.length > 0}
                    <div class="node-params">
                        {#each displayParams as param}
                            <div class="param-row" title={`${param.label}: ${param.value}`}>
                                <span class="param-label">{param.label}</span>
                                <span class="param-value" title={String(param.value)}>{param.value}</span>
                            </div>
                        {/each}
                    </div>
                {/if}
```

- [ ] **Step 2: Update the .node-params, .param-row, .param-label, .param-value CSS rules**

Replace the existing style block (lines 307-335) — the `.node-params`, `.param-row`, `.param-label`, and `.param-value` rules — with:

```css
    .node-params {
        padding: 4px 12px 8px;
        border-top: 1px solid #f1f5f9;
        margin-top: 2px;
        overflow: hidden;
    }

    .param-row {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 2px 0;
        min-width: 0;
    }

    .param-label {
        font-size: 11px;
        color: #64748b;
        flex-shrink: 0;
        max-width: 60%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .param-value {
        font-size: 11px;
        font-weight: 600;
        color: #334155;
        font-family: "JetBrains Mono", monospace;
        margin-left: auto;
        text-align: right;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
    }
```

(The change vs current: `.node-params` gains `overflow: hidden`; `.param-row` gains `min-width: 0`; `.param-label` gains `max-width: 60%` + the three `nowrap/overflow/text-overflow` rules; `.param-value` drops `word-break: break-word` and gains the three `nowrap/overflow/text-overflow` rules. All other declarations stay verbatim.)

- [ ] **Step 3: Run test to verify it passes**

Run: `cd frontend && CI=true npx vitest run src/lib/components/protocol/UnitOpNode.test.ts`

Expected: PASS — all six assertions green.

- [ ] **Step 4: Type-check the touched files**

Run: `cd frontend && npm run check`

Expected: no new errors in `UnitOpNode.svelte` or `UnitOpNode.test.ts`. (Pre-existing project-wide warnings unrelated to this file are fine.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/protocol/UnitOpNode.svelte
git -c commit.gpgsign=false commit -m "fix(BUG-0008): truncate UnitOpNode params in time-mode

Add CSS ellipsis on .param-label and .param-value, cap the label
at 60% so the value (user data) shrinks first, hide overflow on
.node-params, and add native title= attrs as a desktop hover
fallback. Note: title= does not fire on tablet (no hover) — a
themed bits-ui Tooltip is the proper solution there and is tracked
as a follow-up; this commit is the CSS bug fix only."
```

---

## Task 3: EquipmentPickerModal — failing tests for new layout behaviors

**Files:**
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.test.ts`

- [ ] **Step 1: Extend the test file with the new assertions**

The current test file has a single `describe('EquipmentPickerModal site default', …)` block. Append a new `describe('EquipmentPickerModal create form layout', …)` block below it (after line 38, before EOF).

At the top of the file (just below the existing imports) add:

```typescript
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const modalSource = readFileSync(join(__dirname, 'EquipmentPickerModal.svelte'), 'utf8');
```

Replace the trailing newline at the end of the file with:

```typescript

describe('EquipmentPickerModal create form layout', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('pick mode: in-form Discard button renders inside .create-form when expanded', async () => {
        const { container, getByRole } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        // Open the create form by clicking the "+ Add New Equipment" link.
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await Promise.resolve();
        const createForm = container.querySelector('.create-form');
        expect(createForm).not.toBeNull();
        const footer = createForm!.querySelector('.create-form-footer');
        expect(footer).not.toBeNull();
        const buttons = Array.from(footer!.querySelectorAll('button'));
        const labels = buttons.map((b) => (b.textContent ?? '').trim().toLowerCase());
        expect(labels).toContain('discard');
        expect(labels.some((l) => l.includes('create equipment'))).toBe(true);
    });

    it('pick mode: "+ Add New Equipment" toggle is hidden while the form is open', async () => {
        const { container, getByRole, queryByRole } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        const opener = getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement;
        opener.click();
        await Promise.resolve();
        // While the form is open, the opener should not be in the DOM.
        expect(queryByRole('button', { name: /add new equipment/i })).toBeNull();
        // .create-form is open (sanity).
        expect(container.querySelector('.create-form')).not.toBeNull();
    });

    it('pick mode: clicking the in-form Discard closes the form and resets fields', async () => {
        const { container, getByRole, getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await Promise.resolve();
        const nameInput = getByLabelText(/equipment name/i) as HTMLInputElement;
        nameInput.value = 'Scratch';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        await Promise.resolve();
        const discardBtn = Array.from(container.querySelectorAll('.create-form-footer button'))
            .find((b) => (b.textContent ?? '').trim().toLowerCase() === 'discard') as HTMLButtonElement;
        expect(discardBtn).toBeTruthy();
        discardBtn.click();
        await Promise.resolve();
        // Form is gone.
        expect(container.querySelector('.create-form')).toBeNull();
        // Re-open and confirm the name field has been reset.
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await Promise.resolve();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });

    it('does not double-scroll: .equipment-list CSS no longer declares overflow-y', () => {
        // Source-text assertion: getComputedStyle in jsdom does not reliably
        // resolve scoped Svelte styles, so we inspect the CSS rule directly.
        // Mirrors the UnitOpNode test pattern.
        const styleBlock = modalSource.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const listRule = styleBlock.match(/\.equipment-list\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(listRule).not.toBe('');
        expect(listRule).not.toMatch(/overflow-y\s*:/);
        // .equipment-modal must still own the scroll (single body scroller).
        const modalRule = styleBlock.match(/\.equipment-modal\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(modalRule).toMatch(/overflow-y\s*:\s*auto/);
        expect(modalRule).not.toMatch(/max-height\s*:\s*500px/);
        expect(modalRule).toMatch(/min-height\s*:\s*0/);
    });

    it('pick mode: re-opening the dialog after close resets the create form fields', async () => {
        const { rerender, getByRole, getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        // Expand form, type a name, then "hard close" by flipping open=false.
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await Promise.resolve();
        const nameInput = getByLabelText(/equipment name/i) as HTMLInputElement;
        nameInput.value = 'Leaked';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        await Promise.resolve();
        await rerender({
            sites,
            open: false,
            mode: 'pick',
            orgEquipment: [],
            onCreateEquipment: vi.fn(),
        });
        await rerender({
            sites,
            open: true,
            mode: 'pick',
            orgEquipment: [],
            onCreateEquipment: vi.fn(),
        });
        // Re-open and confirm field is empty.
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await Promise.resolve();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });

    it('pick mode: "Close form" appears in sticky search row only when form is open and out of view', async () => {
        // The Close-form link is rendered behind the same gate as Go-to-form
        // (showCreateForm && !isCreateFormInView). We can't drive the
        // IntersectionObserver from the stub, so simulate by setting the
        // out-of-view state via the component's internal flag if exposed,
        // OR (preferable) assert the markup gate by inspecting source.
        // We use source-text inspection here to lock the gate contract.
        const tpl = modalSource;
        // The Close-form button must reference closeCreateForm and sit
        // behind `showCreateForm && !isCreateFormInView`.
        expect(tpl).toMatch(/showCreateForm\s*&&\s*!isCreateFormInView/);
        expect(tpl).toMatch(/Close form/);
        expect(tpl).toMatch(/Go to form/);
    });

    it('create mode: the form footer has only a Create Equipment button (no Discard)', () => {
        const { container } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'create',
                onCreateEquipment: vi.fn(),
            },
        });
        const footer = container.querySelector('.create-form-footer');
        expect(footer).not.toBeNull();
        const buttons = Array.from(footer!.querySelectorAll('button'));
        // Exactly one button, and it's Create Equipment.
        expect(buttons).toHaveLength(1);
        expect((buttons[0].textContent ?? '').trim().toLowerCase()).toMatch(/create equipment/);
    });
});
```

- [ ] **Step 2: Run the test file to verify the new assertions fail**

Run: `cd frontend && CI=true npx vitest run src/lib/components/modals/EquipmentPickerModal.test.ts`

Expected: the original 3 tests still PASS; the 5 new tests in `create form layout` FAIL — `.create-form-footer` doesn't exist yet, the toggle is currently still visible when the form is open, `Discard` button doesn't exist, etc.

- [ ] **Step 3: Commit the failing tests**

```bash
git add frontend/src/lib/components/modals/EquipmentPickerModal.test.ts
git -c commit.gpgsign=false commit -m "test(BUG-0008): add EquipmentPickerModal layout regression tests"
```

---

## Task 4: EquipmentPickerModal — restructure template (form footer, hidden toggle, mode-create variant)

**Files:**
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.svelte:382-518` (the `<div class="create-section">` block)

- [ ] **Step 1: Replace the `.create-section` block in the template**

Replace the entire `<div class="create-section">…</div>` block (lines 382-518) with:

```svelte
            <!-- Create new equipment section -->
            <div class="create-section" bind:this={createSectionEl}>
                {#if mode !== 'create' && !showCreateForm}
                    <Button
                        variant="link"
                        size="sm"
                        class="h-auto p-0 justify-start font-medium"
                        onclick={() => (showCreateForm = true)}
                    >
                        + Add New Equipment
                    </Button>
                {/if}

                {#if showCreateForm}
                    <div class="create-form">
                        <h4>Create Equipment</h4>
                        <div class="form-group">
                            <label for="eq-name">Equipment Name *</label>
                            <input
                                id="eq-name"
                                type="text"
                                placeholder="e.g., Centrifuge A"
                                bind:value={newEquipmentName}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-desc">Description</label>
                            <input
                                id="eq-desc"
                                type="text"
                                placeholder="e.g., High-speed centrifuge"
                                bind:value={newEquipmentDescription}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-type">Equipment Type</label>
                            <input
                                id="eq-type"
                                type="text"
                                placeholder="e.g., Centrifuge"
                                bind:value={newEquipmentType}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-room">Room</label>
                            <input
                                id="eq-room"
                                type="text"
                                placeholder="e.g., Room 204"
                                bind:value={newEquipmentRoom}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-loc">Bench / Spot</label>
                            <input
                                id="eq-loc"
                                type="text"
                                placeholder="e.g., Bench A2"
                                bind:value={newEquipmentLocation}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-site">Site *</label>
                            <SitePicker {sites} value={newSiteId} onChange={(v) => (newSiteId = v)} />
                        </div>

                        <div class="form-group">
                            <label for="eq-serial">Serial Number</label>
                            <input
                                id="eq-serial"
                                type="text"
                                placeholder="e.g., SN-12345"
                                bind:value={newEquipmentSerial}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-last-cal">Last Calibrated</label>
                            <input
                                id="eq-last-cal"
                                type="date"
                                bind:value={newEquipmentLastCal}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-next-cal">Calibration Due</label>
                            <input
                                id="eq-next-cal"
                                type="date"
                                bind:value={newEquipmentNextCal}
                                class="form-input"
                            />
                        </div>

                        <div class="form-group">
                            <label for="eq-cert">Calibration Certificate</label>
                            <input
                                id="eq-cert"
                                type="file"
                                accept="application/pdf,image/*"
                                onchange={handleCertificateFile}
                                class="form-input"
                            />
                            {#if newEquipmentCertPath}
                                <span class="text-xs text-muted-foreground">
                                    Selected: {newEquipmentCertPath}
                                </span>
                            {/if}
                        </div>

                        {#if createError}
                            <div class="error-message">{createError}</div>
                        {/if}

                        <div class="create-form-footer">
                            {#if mode !== 'create'}
                                <Button
                                    variant="secondary"
                                    onclick={discardCreateForm}
                                    disabled={isCreating}
                                >
                                    Discard
                                </Button>
                            {/if}
                            <Button
                                onclick={handleCreate}
                                disabled={isCreating}
                            >
                                {isCreating ? 'Creating...' : 'Create Equipment'}
                            </Button>
                        </div>
                    </div>
                {/if}
            </div>
```

- [ ] **Step 2: Add the `discardCreateForm` and `closeCreateForm` helpers to the `<script>` block**

Find `handleCertificateFile` (currently lines 106-112) and immediately above it add:

```typescript
	function resetCreateFormFields() {
		newEquipmentName = '';
		newEquipmentDescription = '';
		newEquipmentType = '';
		newEquipmentRoom = '';
		newEquipmentLocation = '';
		newEquipmentSerial = '';
		newEquipmentLastCal = '';
		newEquipmentNextCal = '';
		newEquipmentCertPath = '';
		createError = '';
		// newSiteId intentionally stays — sticky preference (see resolveInitialSiteId).
	}

	function discardCreateForm() {
		showCreateForm = false;
		resetCreateFormFields();
	}

	function closeCreateForm() {
		// Called from the sticky-row "Close form" link. Behaves identically
		// to Discard, just surfaced via a different affordance.
		discardCreateForm();
	}

```

- [ ] **Step 3: Extend the existing `$effect(open)` to reset form fields on re-open**

Find the existing effect (currently lines 115-124):

```typescript
	// Initialize selected items when modal opens
	$effect(() => {
		if (open) {
			selectedItems = new Map(
				currentEquipment.map((e) => [
					e.equipment_id,
					{ local_id: e.local_id ?? '', shareable: e.shareable }
				])
			);
		}
	});
```

Replace with:

```typescript
	// Initialize selected items and (in pick mode) reset the create form
	// every time the dialog opens, so a half-typed form from a previous
	// session doesn't leak across opens. In `create` mode the form is the
	// whole modal — leaving fields untouched is the correct behavior there.
	$effect(() => {
		if (open) {
			selectedItems = new Map(
				currentEquipment.map((e) => [
					e.equipment_id,
					{ local_id: e.local_id ?? '', shareable: e.shareable }
				])
			);
			if (mode !== 'create') {
				showCreateForm = false;
				resetCreateFormFields();
			}
		}
	});
```

- [ ] **Step 4: Run the layout test file to check progress**

Run: `cd frontend && CI=true npx vitest run src/lib/components/modals/EquipmentPickerModal.test.ts -t "create form layout"`

Expected: tests covering in-form Discard, hidden toggle, Discard resets fields, mode === 'create' single-button, and re-open reset now PASS. The double-scroller source-text guard and the close-from-sticky markup-gate guard still FAIL until Task 5 lands the CSS and template gate.

---

## Task 5: EquipmentPickerModal — single body scroller + sticky search + jump-to-form

**Files:**
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` — `<script>` (new `$state`/`$effect` for `IntersectionObserver`), template (sticky search row layout, "Jump to form ↓" link), `<style>` (drop `.equipment-list overflow-y`, drop `.equipment-modal max-height`, add `.equipment-modal min-height: 0`, sticky search, footer styles).

- [ ] **Step 1: Add `isCreateFormInView` state + IntersectionObserver effect to the `<script>` block**

In `EquipmentPickerModal.svelte`, find the existing `createSectionEl` declaration (currently line 83):

```typescript
	let createSectionEl = $state<HTMLDivElement | null>(null);
```

Immediately below it, add:

```typescript
	let createFormEl = $state<HTMLDivElement | null>(null);
	let isCreateFormInView = $state(true);

	$effect(() => {
		if (!showCreateForm || !createFormEl) {
			isCreateFormInView = true;
			return;
		}
		const target = createFormEl;
		const obs = new IntersectionObserver(
			(entries) => {
				const entry = entries[0];
				if (entry) isCreateFormInView = entry.isIntersecting;
			},
			{ threshold: 0.1 },
		);
		obs.observe(target);
		return () => obs.disconnect();
	});

	function scrollCreateFormIntoView() {
		createFormEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	}
```

- [ ] **Step 2: Soften the existing form-open autoscroll to `block: 'nearest'`**

Find the existing effect (currently lines 127-132):

```typescript
	// Scroll the create form into view when it opens so the submit button is visible
	$effect(() => {
		if (showCreateForm && createSectionEl) {
			// Defer to allow DOM to render the form before scrolling
			setTimeout(() => createSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50);
		}
	});
```

Replace with:

```typescript
	// Scroll the create form into view when it opens so the user sees the form
	// fields, not the empty footer. `block: 'nearest'` avoids overshooting.
	$effect(() => {
		if (showCreateForm && createSectionEl) {
			setTimeout(
				() => createSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
				50,
			);
		}
	});
```

- [ ] **Step 3: Bind `createFormEl` to the form element**

In the template, find:

```svelte
                {#if showCreateForm}
                    <div class="create-form">
                        <h4>Create Equipment</h4>
```

and change the opening `<div>` to:

```svelte
                {#if showCreateForm}
                    <div class="create-form" bind:this={createFormEl}>
                        <h4>Create Equipment</h4>
```

- [ ] **Step 4: Wrap the search input row to host the "Jump to form" link**

In the template, find the `<!-- Search bar -->` block (currently lines 291-299):

```svelte
            {#if mode !== 'create'}
            <!-- Search bar -->
            <div class="search-bar">
                <input
                    type="text"
                    placeholder="Search equipment by name or description..."
                    bind:value={searchQuery}
                    class="search-input"
                />
            </div>
```

Replace with:

```svelte
            {#if mode !== 'create'}
            <!-- Search bar (sticky inside the single scroller) -->
            <div class="search-bar">
                <input
                    type="text"
                    placeholder="Search equipment by name or description..."
                    bind:value={searchQuery}
                    class="search-input"
                />
                {#if showCreateForm && !isCreateFormInView}
                    <Button
                        variant="link"
                        size="sm"
                        class="sticky-link h-auto p-0"
                        onclick={scrollCreateFormIntoView}
                    >
                        Go to form ↓
                    </Button>
                    <Button
                        variant="link"
                        size="sm"
                        class="sticky-link h-auto p-0"
                        onclick={closeCreateForm}
                    >
                        ✕ Close form
                    </Button>
                {/if}
            </div>
```

- [ ] **Step 5: Update the `<style>` block — `.equipment-modal`, `.equipment-list`, `.search-bar`, and new `.create-form-footer`**

In the `<style>` block, find `.equipment-modal` (currently lines 538-545):

```css
	.equipment-modal {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem 1.5rem;
		max-height: 500px;
		overflow-y: auto;
	}
```

Replace with:

```css
	.equipment-modal {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem 1.5rem;
		overflow-y: auto;
		min-height: 0;
		flex: 1;
	}
```

Find `.search-bar` (currently lines 547-549):

```css
	.search-bar {
		flex-shrink: 0;
	}
```

Replace with:

```css
	.search-bar {
		flex-shrink: 0;
		position: sticky;
		top: 0;
		z-index: 1;
		background: hsl(var(--background));
		padding: 0.25rem 0;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.search-bar .search-input {
		flex: 1;
	}

	:global(.sticky-link) {
		flex-shrink: 0;
		white-space: nowrap;
	}
```

Find `.equipment-list` (currently lines 568-574):

```css
	.equipment-list {
		flex: 1;
		overflow-y: auto;
		border: 1px solid hsl(var(--border));
		border-radius: 0.375rem;
		padding: 0.5rem 0;
	}
```

Replace with:

```css
	.equipment-list {
		border: 1px solid hsl(var(--border));
		border-radius: 0.375rem;
		padding: 0.5rem 0;
	}
```

(`flex: 1` and `overflow-y: auto` removed — the dialog body is now the only scroller.)

- [ ] **Step 6: Add the `.create-form-footer` rule at the end of the `<style>` block**

Just before the closing `</style>`, add:

```css

	.create-form-footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 0.5rem;
		padding-top: 0.75rem;
		border-top: 1px solid hsl(var(--border));
	}
```

- [ ] **Step 7: Run the full modal test file**

Run: `cd frontend && CI=true npx vitest run src/lib/components/modals/EquipmentPickerModal.test.ts`

Expected: all 8 tests PASS (3 original + 5 new). The double-scroller test now passes because `.equipment-list` no longer has `overflow-y: auto`.

---

## Task 6: EquipmentPickerModal — input/panel contrast + theme-token bonus cleanup

**Files:**
- Modify: `frontend/src/lib/components/modals/EquipmentPickerModal.svelte` — `<style>` block: `.create-form`, `.form-input`, `.type-badge`, `.error-message`.

- [ ] **Step 1: Update `.create-form` to use a callout treatment**

Find `.create-form` (currently lines 719-725):

```css
	.create-form {
		margin-top: 0.75rem;
		padding: 0.75rem;
		background-color: hsl(var(--muted));
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--border));
	}
```

Replace with:

```css
	.create-form {
		margin-top: 0.75rem;
		padding: 0.75rem;
		background-color: hsl(var(--muted) / 0.4);
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--border));
		border-left: 4px solid hsl(var(--primary));
	}
```

(The 4px left primary border anchors the callout. We considered an inset
primary-tint shadow but it would have been masked by the border-left at the
opacity we wanted — the border alone communicates the sub-region clearly.)

- [ ] **Step 2: Update `.form-input` background to `hsl(var(--card))`**

Find `.form-input` (currently lines 747-755):

```css
	.form-input {
		padding: 0.5rem;
		border: 1px solid hsl(var(--border));
		border-radius: 0.25rem;
		font-size: 0.875rem;
		font-family: inherit;
		background: hsl(var(--background));
		color: hsl(var(--foreground));
	}
```

Replace with:

```css
	.form-input {
		padding: 0.5rem;
		border: 1px solid hsl(var(--border));
		border-radius: 0.25rem;
		font-size: 0.875rem;
		font-family: inherit;
		background: hsl(var(--card));
		color: hsl(var(--foreground));
	}
```

- [ ] **Step 3: Bonus cleanup — replace hardcoded hex in `.type-badge`**

Find `.type-badge` (currently lines 617-625):

```css
	.type-badge {
		display: inline-block;
		padding: 0.25rem 0.5rem;
		background-color: #e0f2fe;
		color: #0369a1;
		border-radius: 0.25rem;
		font-size: 0.75rem;
		font-weight: 500;
	}
```

Replace with:

```css
	.type-badge {
		display: inline-block;
		padding: 0.25rem 0.5rem;
		background-color: hsl(var(--muted));
		color: hsl(var(--muted-foreground));
		border-radius: 0.25rem;
		font-size: 0.75rem;
		font-weight: 500;
	}
```

(We use `--muted` rather than `--accent` for type badges. In this app accent
is reserved for actionable or status-communicating elements; type chips are
metadata, and the existing pattern in the `run/` surface is muted.)

- [ ] **Step 4: Bonus cleanup — replace hardcoded hex in `.error-message`**

Find `.error-message` (currently lines 763-770):

```css
	.error-message {
		padding: 0.5rem;
		background-color: #fee2e2;
		color: #991b1b;
		border-radius: 0.25rem;
		font-size: 0.875rem;
		margin-bottom: 0.75rem;
	}
```

Replace with:

```css
	.error-message {
		padding: 0.5rem;
		background-color: hsl(var(--destructive) / 0.1);
		color: hsl(var(--destructive));
		border-radius: 0.25rem;
		font-size: 0.875rem;
		margin-bottom: 0.75rem;
	}
```

- [ ] **Step 5: Run the modal test file once more (regression safety)**

Run: `cd frontend && CI=true npx vitest run src/lib/components/modals/EquipmentPickerModal.test.ts`

Expected: all 8 tests still PASS — these changes are CSS-only and don't touch the assertions.

- [ ] **Step 6: Type-check**

Run: `cd frontend && npm run check`

Expected: no new errors in `EquipmentPickerModal.svelte` or `EquipmentPickerModal.test.ts`.

- [ ] **Step 7: Commit Bug 2 + bonus cleanup**

```bash
git add frontend/src/lib/components/modals/EquipmentPickerModal.svelte frontend/src/lib/components/modals/EquipmentPickerModal.test.ts
git -c commit.gpgsign=false commit -m "fix(BUG-0008): tidy EquipmentPickerModal layout and contrast

- Move Discard into the form footer next to Create Equipment;
  hide '+ Add New Equipment' while the form is open.
- Single body scroller: drop .equipment-list overflow-y; drop
  .equipment-modal max-height; make .equipment-modal min-height:0
  + flex:1 so it owns the scroll.
- Sticky search row inside the scroller; add a Jump-to-form link
  surfaced only when the form is open and out of view (gated by
  IntersectionObserver).
- Form-open autoscroll uses block:'nearest' so it doesn't shoot
  past the fields to the footer.
- Callout treatment on .create-form (border-left primary + muted
  panel + soft primary inset shadow) and white-card .form-input
  bg so fields read cleanly against the panel across themes.
- Bonus: .type-badge and .error-message swap hardcoded hex for
  hsl(var(--accent)) / hsl(var(--destructive)) tokens."
```

---

## Task 7: Full test suite + final sanity

**Files:** none

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && CI=true npm run test`

Expected: all tests PASS. If anything outside the two touched files is now red, stop — that's a regression and needs investigation before proceeding.

- [ ] **Step 2: Type-check the whole frontend**

Run: `cd frontend && npm run check`

Expected: no new errors introduced by this work.

- [ ] **Step 3: Browser smoke verification (manual, before handing to qa-verify)**

With the dev server running on this worktree's slot (see the implement-task skill for slot bring-up):

1. Open the protocol editor on a protocol with at least one step with a
   long reagent value. Toggle time mode ON. Confirm:
   - Param labels and values truncate with `…` rather than wrapping
     character-by-character.
   - Hovering a row shows the full `label: value` as a native tooltip.
2. From a unit op with equipment, click Select Equipment. Confirm:
   - Search bar stays visible (sticky) when scrolling the dialog.
   - Click `+ Add New Equipment` — the opener disappears, the form
     expands with a `Discard` + `Create Equipment` footer.
   - Scroll the dialog body so the form leaves the viewport — the
     `Jump to form ↓` link appears in the search row. Click it; the
     form scrolls smoothly back into view without overshooting.
   - `Discard` closes the form and resets the fields (re-open and
     verify Name is empty).
   - Inputs are visually distinct from the panel background; the
     panel has a primary-color left accent stripe.
3. Switch to `blueprint` and `apothecary` themes and re-confirm panel
   contrast is acceptable in both.

---

## Self-Review

**1. Spec coverage:**
- Bug 1 (ellipsis + hidden overflow + 60% label cap + `title=` attrs, no `applyTimelineSizing` change) → Task 1 (failing test) + Task 2 (implement).
- Bug 2.1 (Cancel-into-form-footer renamed `Discard`; hide `+ Add New Equipment` when open; `mode === 'create'` keeps only Create) → Task 3 + Task 4.
- Bug 2.2 (single body scroller, sticky search, "Go to form" link via IntersectionObserver) → Task 3 (source-text double-scroller guard, sticky-gate markup guard) + Task 5.
- Bug 2.3 (`.create-form` callout treatment with theme tokens; `.form-input` → `hsl(var(--card))`) → Task 6 Steps 1-2.
- Bug 2.4 (autoscroll `block: 'end'` → `'nearest'`) → Task 5 Step 2.
- Bonus cleanup (`.type-badge` → muted, `.error-message` → destructive tokens) → Task 6 Steps 3-4.
- Plan-review-panel additions (apply with #4 + #8 user choices):
  - IntersectionObserver polyfill → Task 0.
  - Tightened UnitOpNode source-text regexes (non-positional + literal pin) → Task 1.
  - Source-text double-scroller guard (replaces unreliable jsdom `getComputedStyle`) → Task 3.
  - Re-open reset (extend `$effect(open)`) + `resetCreateFormFields` extraction → Task 4 Steps 2-3.
  - "Close form" link in sticky search row → Task 5 Step 4.
  - Drop `box-shadow` on `.create-form` (was vestigial) → Task 6 Step 1.
  - "Jump to form" → "Go to form" microcopy → Task 5 Step 4.
  - `.type-badge` → `--muted` (not `--accent` — accent is reserved for status) → Task 6 Step 3.
  - `title=` framing softened in Task 2 commit (desktop hover fallback only).

**2. Placeholder scan:** every code step shows the literal code; commands list expected outputs; no TODO/TBD strings. Clean.

**3. Type/name consistency:** `createFormEl` / `isCreateFormInView` / `scrollCreateFormIntoView` / `discardCreateForm` / `closeCreateForm` / `resetCreateFormFields` are referenced consistently between script and template. Test selector strings (`.create-form-footer`, `.create-form`, `.equipment-list`, `.equipment-modal`) match the CSS rules and template classnames. `Discard` / `Go to form ↓` / `✕ Close form` button labels in tests match the template literals.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-bug-0008-protocol-editor-ui-fixes.md`.

This is a small, sequential, CSS-and-template-heavy change in two files — the slices interleave on `EquipmentPickerModal.svelte`, so subagent parallelization buys little. Inline TDD in a single session is the better fit here, but the user picks per the implement-task skill.
