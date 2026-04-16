# TD-0068 — Replace Hand-Rolled Modals with Shared `Dialog` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 7 hand-rolled `fixed inset-0 z-50` overlays with the shared `Dialog` component from `$lib/components/ui/dialog`, gaining focus trap + aria support while preserving existing visual design and dismissal behavior.

**Architecture:** Two migration patterns.
- Category A (5 true modals): `Dialog.Root bind:open={…}` + `Dialog.Content class="<size override>"`. Default Escape + outside-click dismissal.
- Category B (2 forced-UI components): same `Dialog.Root` wrapping, but `showCloseButton={false}`, `escapeKeydownBehavior="ignore"`, `interactOutsideBehavior="ignore"`, and a full-viewport `class` override.

**Tech Stack:** Svelte 5 (runes), bits-ui 2.x, TailwindCSS 4, shadcn-svelte `Dialog` primitives.

**Spec:** [`docs/superpowers/specs/2026-04-16-td-0068-replace-hand-rolled-modals-design.md`](../specs/2026-04-16-td-0068-replace-hand-rolled-modals-design.md)

## Background — things to know before starting

- **Dialog imports.** Every file imports like this:
  ```ts
  import * as Dialog from '$lib/components/ui/dialog';
  ```
  This gives you `Dialog.Root`, `Dialog.Content`, `Dialog.Title`, `Dialog.Description`, etc. (See `frontend/src/lib/components/ui/dialog/index.ts`.)
- **Dialog.Content default styling** (from `frontend/src/lib/components/ui/dialog/dialog-content.svelte`) already includes: fixed positioning, centering via `top:50%; left:50%; translate:-50% -50%`, `bg-background`, `rounded-lg border`, `p-6`, `shadow-lg`, `max-h-[90vh] overflow-y-auto`, `sm:max-w-lg`, and a fade+zoom animation. When you pass a `class` prop it **merges** via `cn()` — later classes override earlier ones.
- **Overriding default max-width and padding.** To go wider than `sm:max-w-lg`, include `max-w-*` or `sm:max-w-*` in your class override. To drop rounding/borders/padding (Category B), explicitly pass `rounded-none border-0 p-0` because the defaults will otherwise apply.
- **bits-ui dismissal props.** `Dialog.Content` accepts `escapeKeydownBehavior` and `interactOutsideBehavior`. Set them to `"ignore"` for Category B to suppress both paths. (`bits-ui` v2 API — already the project's version per `frontend/package.json`.)
- **Portal and stacking.** `Dialog.Content` uses a `DialogPortal` that renders content at the document body. Z-index is fixed at `z-50` in the default class. For the save dialog nested inside `TemplateConvertModal`, the old `z-[60]` manual override can go away — portal ordering handles stacking.
- **Close button.** The Dialog's built-in X close button appears top-right when `showCloseButton` is true (default). If the existing component renders its own close button inside the card, remove the custom one during migration to avoid duplicates. If `showCloseButton={false}` is set (Category B), no X renders.
- **`onSuccess` callback (TemplateUploadModal).** This callback currently does `showUpload = false; loadTemplates();`. After the API change, the callsite must still close the modal on success by setting `showUpload = false`, because with `bind:open` the parent owns that state.
- **Don't touch `field/+page.svelte`.** It's NOT in the 7 targets (TD-0067a was superseded — field/+page.svelte is outside this task).
- **Don't touch `TemplateConvertModal.svelte` line 444 main shell.** Only the nested save dialog at line 786 gets migrated in this task. The main shell is logged as a follow-up.

## File Structure

No new files created. All changes are edits to existing files.

**Files modified:**

| File | Change |
|---|---|
| `frontend/src/lib/components/RoleWizard.svelte` | Tag selector overlay → `Dialog.Root`/`Dialog.Content` |
| `frontend/src/lib/components/FieldModeRoleWizard.svelte` | Tag selector overlay → `Dialog.Root`/`Dialog.Content` |
| `frontend/src/lib/components/run/RunDocuments.svelte` | Download options modal → `Dialog.Root`/`Dialog.Content` |
| `frontend/src/lib/components/settings/TemplateUploadModal.svelte` | Overlay → `Dialog.Root`/`Dialog.Content`; replace `onClose` prop with `bind:open` |
| `frontend/src/lib/components/settings/TemplatesTab.svelte` | Callsite update: bind `showUpload`, drop `{#if}` wrapper, update `onSuccess` body |
| `frontend/src/lib/components/TemplateConvertModal.svelte` | Nested save dialog (line 786) → `Dialog.Root`/`Dialog.Content` |
| `frontend/src/lib/components/FieldModeLockScreen.svelte` | Full-viewport overlay → `Dialog.Root`/`Dialog.Content` with dismissal locked |
| `frontend/src/lib/components/ExpiryWarningBanner.svelte` | Critical branch overlay → `Dialog.Root`/`Dialog.Content` with dismissal via button only |

## Task 1: Prep — verify baseline

**Files:** none (verification only)

- [ ] **Step 1: Verify you're on the task branch**

Run: `git branch --show-current`
Expected: some branch ≠ `main`. If on `main`, stop and switch.

- [ ] **Step 2: Confirm starting state builds and type-checks**

Run: `cd frontend && npm run check`
Expected: 0 errors. (Warnings are fine; this is the "before" baseline.)

- [ ] **Step 3: Confirm the 7 hand-rolled overlays still exist in current code**

Run (from repo root):
```bash
grep -n "fixed inset-0 z-50" \
  frontend/src/lib/components/RoleWizard.svelte \
  frontend/src/lib/components/FieldModeRoleWizard.svelte \
  frontend/src/lib/components/FieldModeLockScreen.svelte \
  frontend/src/lib/components/run/RunDocuments.svelte \
  frontend/src/lib/components/settings/TemplateUploadModal.svelte \
  frontend/src/lib/components/ExpiryWarningBanner.svelte \
  frontend/src/lib/components/TemplateConvertModal.svelte
```
Expected: at least one hit per file. If any file has zero hits, the line number drifted — investigate before continuing.

No commit in this task.

---

## Task 2: Migrate `RoleWizard.svelte` tag selector

**Files:**
- Modify: `frontend/src/lib/components/RoleWizard.svelte` (lines ~808–862 — the `{#if showTagSelector && currentStep}` block)

- [ ] **Step 1: Find the `<script>` import block**

Look at the top of the file. There will already be imports like `import ImageAnalysisDialog from …;` and `import BarcodeScanner from …;`. You're adding a new line.

- [ ] **Step 2: Add the Dialog import**

Add this import alongside the other component imports in the `<script lang="ts">` block (alphabetical placement preferred but not required):

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 3: Replace the tag selector overlay block**

Find this existing block (around line 808):

```svelte
    <!-- Parameter Tag Selector (shown after image capture) -->
    {#if showTagSelector && currentStep}
        <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div class="bg-white rounded-xl shadow-2xl w-[95%] max-w-md max-h-[90vh] flex flex-col overflow-hidden">
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200">
                    <div>
                        <h3 class="text-lg font-semibold text-slate-900">Tag Image Parameters</h3>
                        <p class="text-sm text-slate-500">Select which parameters this image captures</p>
                    </div>
                </div>
                <!-- Body -->
                <div class="px-6 py-4 overflow-y-auto">
                    ... (keep body unchanged) ...
                </div>
                <!-- Footer -->
                <div class="px-6 py-4 border-t border-slate-200">
                    ... (keep footer unchanged) ...
                </div>
            </div>
        </div>
    {/if}
```

Replace it with:

```svelte
    <!-- Parameter Tag Selector (shown after image capture) -->
    {#if currentStep}
        <Dialog.Root bind:open={showTagSelector}>
            <Dialog.Content
                class="w-[95%] max-w-md max-h-[90vh] p-0 flex flex-col overflow-hidden"
            >
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200">
                    <div>
                        <Dialog.Title class="text-lg font-semibold text-slate-900">Tag Image Parameters</Dialog.Title>
                        <Dialog.Description class="text-sm text-slate-500">Select which parameters this image captures</Dialog.Description>
                    </div>
                </div>
                <!-- Body -->
                <div class="px-6 py-4 overflow-y-auto">
                    ... (keep body unchanged — the inner {#if editableFields.length > 0} block, the {#each} loop, and the {:else} branch exactly as they were) ...
                </div>
                <!-- Footer -->
                <div class="px-6 py-4 border-t border-slate-200">
                    ... (keep footer unchanged — the `Tag (…)` button block exactly as it was) ...
                </div>
            </Dialog.Content>
        </Dialog.Root>
    {/if}
```

Changes to notice:
- The `{#if showTagSelector && currentStep}` becomes `{#if currentStep}` — showTagSelector now controls the Dialog via `bind:open` rather than conditionally rendering the element. We still guard on `currentStep` because the body references `currentStep` indirectly via `editableFields`.
- The outer `fixed inset-0 z-50 …` overlay div is gone (Dialog provides it).
- The inner `bg-white rounded-xl shadow-2xl w-[95%] max-w-md max-h-[90vh] flex flex-col overflow-hidden` wrapper is gone. Its sizing moves onto `Dialog.Content`'s `class`. The `bg-white` is dropped because `Dialog.Content` ships `bg-background`; if qa-verify flags a visual difference vs. the current bright-white card, swap `bg-background` → `bg-white` via the class.
- `<h3>` becomes `<Dialog.Title>` and the sibling `<p>` becomes `<Dialog.Description>` for accessibility.
- The default Dialog close X is now shown in the top-right (there was no custom close button previously, so nothing to remove).

- [ ] **Step 4: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced by this file. (Pre-existing warnings fine.)

- [ ] **Step 5: Smoke-check in the dev server (optional but encouraged)**

If the dev server is already running, navigate to a run → click a step → capture an image. Confirm the tag selector opens, closes on Escape, closes on backdrop click, applies tags correctly. If the dev server isn't running, skip to Step 6 — qa-verify will exercise this later.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/RoleWizard.svelte
git commit -m "refactor(ui): migrate RoleWizard tag selector to Dialog [TD-0068]"
```

---

## Task 3: Migrate `FieldModeRoleWizard.svelte` tag selector

**Files:**
- Modify: `frontend/src/lib/components/FieldModeRoleWizard.svelte` (lines ~598–646)

- [ ] **Step 1: Add the Dialog import**

In the `<script lang="ts">` block, add:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 2: Replace the tag selector overlay block**

Find (around line 598):

```svelte
    <!-- Parameter Tag Selector (after capture) -->
    {#if showTagSelector && currentStep}
        <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
            <div class="bg-white rounded-xl shadow-2xl w-[95%] max-w-md max-h-[90vh] flex flex-col overflow-hidden">
                <div class="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <div>
                        <h3 class="text-base font-semibold text-slate-900">Tag Image Parameters</h3>
                        <p class="text-xs text-slate-500">Which parameters does this image capture?</p>
                    </div>
                </div>
                <div class="px-5 py-3 overflow-y-auto">
                    ... (tag list) ...
                </div>
                <div class="px-5 py-3 border-t border-slate-200">
                    ... (queue button) ...
                </div>
            </div>
        </div>
    {/if}
```

Replace with:

```svelte
    <!-- Parameter Tag Selector (after capture) -->
    {#if currentStep}
        <Dialog.Root bind:open={showTagSelector}>
            <Dialog.Content
                class="w-[95%] max-w-md max-h-[90vh] p-0 flex flex-col overflow-hidden"
            >
                <div class="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <div>
                        <Dialog.Title class="text-base font-semibold text-slate-900">Tag Image Parameters</Dialog.Title>
                        <Dialog.Description class="text-xs text-slate-500">Which parameters does this image capture?</Dialog.Description>
                    </div>
                </div>
                <div class="px-5 py-3 overflow-y-auto">
                    ... (tag list — unchanged: the {#if editableFields.length > 0} ... {:else} block) ...
                </div>
                <div class="px-5 py-3 border-t border-slate-200">
                    ... (queue button — unchanged) ...
                </div>
            </Dialog.Content>
        </Dialog.Root>
    {/if}
```

- [ ] **Step 3: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced by this file.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/FieldModeRoleWizard.svelte
git commit -m "refactor(ui): migrate FieldModeRoleWizard tag selector to Dialog [TD-0068]"
```

---

## Task 4: Migrate `run/RunDocuments.svelte` download options modal

**Files:**
- Modify: `frontend/src/lib/components/run/RunDocuments.svelte` (lines ~110–153)

- [ ] **Step 1: Add the Dialog import**

In the `<script lang="ts">` block, add:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 2: Replace the download options modal block**

Find (around line 110):

```svelte
<!-- Download Options Modal -->
{#if showModal}
    <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="fixed inset-0" onclick={() => showModal = false}></div>
        <div class="bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-xl relative z-10">
            <h3 class="text-lg font-semibold text-foreground mb-1">Batch Record Options</h3>
            <p class="text-sm text-muted-foreground mb-4">
                Choose what to include in your download.
            </p>

            <div class="space-y-3">
                ... (two checkboxes) ...
            </div>

            <div class="flex gap-3 mt-6">
                <button onclick={() => showModal = false}
                    class="flex-1 px-4 py-2 border border-border rounded-lg text-sm font-medium hover:bg-muted transition-colors">
                    Cancel
                </button>
                <button onclick={confirmDownload}
                    class="flex-1 px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors">
                    Download
                </button>
            </div>
        </div>
    </div>
{/if}
```

Replace with:

```svelte
<!-- Download Options Modal -->
<Dialog.Root bind:open={showModal}>
    <Dialog.Content class="max-w-sm">
        <Dialog.Header>
            <Dialog.Title class="text-lg font-semibold text-foreground">Batch Record Options</Dialog.Title>
            <Dialog.Description class="text-sm text-muted-foreground">
                Choose what to include in your download.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3">
            ... (two checkboxes — unchanged) ...
        </div>

        <div class="flex gap-3 mt-6">
            <button onclick={() => showModal = false}
                class="flex-1 px-4 py-2 border border-border rounded-lg text-sm font-medium hover:bg-muted transition-colors cursor-pointer">
                Cancel
            </button>
            <button onclick={confirmDownload}
                class="flex-1 px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors cursor-pointer">
                Download
            </button>
        </div>
    </Dialog.Content>
</Dialog.Root>
```

Changes:
- Drop the hand-rolled overlay + separate clickable backdrop div. `Dialog.Root` handles backdrop click-to-close via `onInteractOutside` default.
- Drop the manual `bg-white rounded-xl p-6 …` card wrapper — `Dialog.Content` provides `bg-background rounded-lg border p-6 shadow-lg`. Width override is `max-w-sm`.
- Keep the Cancel / Download buttons as plain styled buttons (no change to their handlers). Added `cursor-pointer` to conform with `.claude/rules/frontend-components.md` since we're touching them.
- Added `<Dialog.Header>` wrapping the title + description for the shadcn convention.

- [ ] **Step 3: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/run/RunDocuments.svelte
git commit -m "refactor(ui): migrate RunDocuments download modal to Dialog [TD-0068]"
```

---

## Task 5: Migrate `TemplateUploadModal.svelte` and its callsite

This task changes the component's prop API from `onClose: () => void` to `open: boolean` (bindable). Both the component and its single callsite (`settings/TemplatesTab.svelte`) change in one commit to keep the tree buildable.

**Files:**
- Modify: `frontend/src/lib/components/settings/TemplateUploadModal.svelte` (props at line ~10–16; overlay at line ~136–319)
- Modify: `frontend/src/lib/components/settings/TemplatesTab.svelte` (callsite at line ~276–284)

- [ ] **Step 1: Add the Dialog import to TemplateUploadModal**

At the top of the `<script lang="ts">` block in `TemplateUploadModal.svelte`, add:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 2: Update the Props interface in TemplateUploadModal**

Find (around line 10):

```svelte
    let {
        onClose,
        onSuccess,
    }: {
        onClose: () => void;
        onSuccess: () => void;
    } = $props();
```

Replace with:

```svelte
    let {
        open = $bindable(false),
        onSuccess,
    }: {
        open?: boolean;
        onSuccess: () => void;
    } = $props();
```

- [ ] **Step 3: Replace all in-file references to `onClose`**

Search for `onClose` in the template section of `TemplateUploadModal.svelte` (should be 3 references: the backdrop div click, the backdrop div keydown-Escape, the header X button, and the Cancel button — ~4 references total).

Each `onClose` or `onClose()` in an event handler becomes `() => (open = false)` or `open = false`, respectively. Specifically:

- `onclick={onClose}` → `onclick={() => (open = false)}`
- `onkeydown={(e) => e.key === 'Escape' && onClose()}` → delete this binding entirely (Dialog handles Escape natively).
- `<button class="…" onclick={onClose}>&times;</button>` → delete this entire button (Dialog ships its own X close button).
- `<Button variant="outline" onclick={onClose}>Cancel</Button>` → `<Button variant="outline" onclick={() => (open = false)}>Cancel</Button>`

- [ ] **Step 4: Replace the overlay wrapper in TemplateUploadModal**

Find (around line 136):

```svelte
<!-- Modal overlay -->
<div class="fixed inset-0 z-50 flex items-center justify-center">
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
        class="absolute inset-0 bg-black/50"
        onclick={onClose}
        onkeydown={(e) => e.key === 'Escape' && onClose()}
    ></div>
    <div
        class="relative bg-background rounded-lg shadow-xl w-full max-w-5xl max-h-[85vh] flex flex-col"
    >
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b">
            <h2 class="text-lg font-semibold">
                {step === 1 ? 'Upload Template' : 'Preview Template'}
            </h2>
            <button class="text-muted-foreground hover:text-foreground text-lg" onclick={onClose}>
                &times;
            </button>
        </div>
        ... (body + footer) ...
    </div>
</div>
```

Replace with:

```svelte
<!-- Modal -->
<Dialog.Root bind:open>
    <Dialog.Content class="w-full max-w-5xl max-h-[85vh] p-0 flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b">
            <Dialog.Title class="text-lg font-semibold">
                {step === 1 ? 'Upload Template' : 'Preview Template'}
            </Dialog.Title>
        </div>
        ... (body + footer — unchanged from current) ...
    </Dialog.Content>
</Dialog.Root>
```

Changes to notice:
- Root changes from `<div class="fixed inset-0 …">` to `<Dialog.Root bind:open>`.
- Inner card div is replaced by `<Dialog.Content class="…">`. Sizing preserved: `w-full max-w-5xl max-h-[85vh]`. We add `p-0` so the existing `px-6 py-4` header/body continues to drive the padding (Dialog.Content defaults to `p-6`).
- The custom `&times;` header close button is removed. Dialog ships a top-right X.
- The hand-rolled backdrop div (with the click-to-close and keydown-Escape) is gone. Dialog handles both natively.
- The `<h2>` becomes `<Dialog.Title>` for aria labelling.

- [ ] **Step 5: Update the callsite in TemplatesTab.svelte**

Find (around line 275):

```svelte
<!-- Upload Modal -->
{#if showUpload}
    <TemplateUploadModal
        onClose={() => (showUpload = false)}
        onSuccess={() => {
            showUpload = false;
            loadTemplates();
        }}
    />
{/if}
```

Replace with:

```svelte
<!-- Upload Modal -->
<TemplateUploadModal
    bind:open={showUpload}
    onSuccess={() => {
        showUpload = false;
        loadTemplates();
    }}
/>
```

Changes:
- `{#if showUpload} … {/if}` wrapper removed — Dialog handles open/closed itself.
- `onClose` prop dropped.
- `bind:open={showUpload}` replaces it.
- `onSuccess` callback unchanged — still sets `showUpload = false` (which with the bind flows back into the Dialog and closes it) and refreshes the list.

- [ ] **Step 6: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced. (A TS error on the `TemplateUploadModal` callsite here is the signal that Steps 2 and 5 are out of sync — fix before moving on.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/components/settings/TemplateUploadModal.svelte frontend/src/lib/components/settings/TemplatesTab.svelte
git commit -m "refactor(ui): migrate TemplateUploadModal to Dialog with bind:open API [TD-0068]"
```

---

## Task 6: Migrate nested save dialog in `TemplateConvertModal.svelte`

Note: We are ONLY migrating the nested save dialog (around line 786), not the main shell at line 444. That shell is explicitly out of scope for TD-0068.

**Files:**
- Modify: `frontend/src/lib/components/TemplateConvertModal.svelte` (lines ~784–811)

- [ ] **Step 1: Add the Dialog import**

If not already present, add to the `<script lang="ts">` block:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

(If there's already an aliased import of Dialog internals elsewhere in this file, use `Dialog` directly without re-import — verify with a file-local search.)

- [ ] **Step 2: Replace the save dialog block**

Find (around line 784):

```svelte
            <!-- Save dialog (inline) -->
            {#if showSaveDialog}
                <div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
                    <div class="bg-background rounded-lg border shadow-lg p-6 w-full max-w-md space-y-4">
                        <h3 class="text-lg font-semibold">Save Template to Library</h3>
                        <div>
                            <Label for="save-name">Template Name</Label>
                            <Input id="save-name" bind:value={saveName} class="mt-1" />
                        </div>
                        <div>
                            <Label for="save-desc">Description (optional)</Label>
                            <Input id="save-desc" bind:value={saveDescription} class="mt-1" />
                        </div>
                        <div>
                            <Label>Type</Label>
                            <p class="text-sm text-muted-foreground mt-1">
                                {templateType === 'SOP' ? 'Protocol' : 'Batch Record'}
                            </p>
                        </div>
                        <div class="flex justify-end gap-2">
                            <Button variant="outline" onclick={() => (showSaveDialog = false)}>Cancel</Button>
                            <Button onclick={handleSave} disabled={!saveName.trim() || saving}>
                                {saving ? 'Saving...' : 'Save'}
                            </Button>
                        </div>
                    </div>
                </div>
            {/if}
```

Replace with:

```svelte
            <!-- Save dialog -->
            <Dialog.Root bind:open={showSaveDialog}>
                <Dialog.Content class="max-w-md space-y-4">
                    <Dialog.Header>
                        <Dialog.Title class="text-lg font-semibold">Save Template to Library</Dialog.Title>
                    </Dialog.Header>
                    <div>
                        <Label for="save-name">Template Name</Label>
                        <Input id="save-name" bind:value={saveName} class="mt-1" />
                    </div>
                    <div>
                        <Label for="save-desc">Description (optional)</Label>
                        <Input id="save-desc" bind:value={saveDescription} class="mt-1" />
                    </div>
                    <div>
                        <Label>Type</Label>
                        <p class="text-sm text-muted-foreground mt-1">
                            {templateType === 'SOP' ? 'Protocol' : 'Batch Record'}
                        </p>
                    </div>
                    <div class="flex justify-end gap-2">
                        <Button variant="outline" onclick={() => (showSaveDialog = false)}>Cancel</Button>
                        <Button onclick={handleSave} disabled={!saveName.trim() || saving}>
                            {saving ? 'Saving...' : 'Save'}
                        </Button>
                    </div>
                </Dialog.Content>
            </Dialog.Root>
```

Changes:
- Drop `{#if showSaveDialog}` wrapper; Dialog manages visibility via `bind:open`.
- Drop the hand-rolled `fixed inset-0 z-[60] …` overlay. Portal handles stacking above the still-present main shell.
- Drop the inner `bg-background rounded-lg border shadow-lg p-6 …` card wrapper — Dialog.Content provides these styles. `max-w-md space-y-4` preserves width + child spacing.

Note on stacking: the main shell at line 444 is a normal DOM element with `z-50`. The Dialog.Content portals to the document body with `z-50` too. Because portal children render after the main shell in document order, the save dialog sits visually above it. Verify in qa-verify.

- [ ] **Step 3: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/TemplateConvertModal.svelte
git commit -m "refactor(ui): migrate TemplateConvertModal save dialog to Dialog [TD-0068]"
```

---

## Task 7: Migrate `FieldModeLockScreen.svelte` (Category B — locked dismissal)

**Files:**
- Modify: `frontend/src/lib/components/FieldModeLockScreen.svelte` (entire template block, lines ~40–87)

- [ ] **Step 1: Add the Dialog import**

In the `<script lang="ts">` block at the top of `FieldModeLockScreen.svelte`, add:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 2: Replace the full-viewport overlay with Dialog**

Find (around line 40, the entire template after the `</script>` tag):

```svelte
<div class="fixed inset-0 z-50 bg-slate-900 flex items-center justify-center">
    <div class="w-[95%] max-w-sm text-center">
        <!-- Lock icon -->
        <div class="w-16 h-16 rounded-full bg-slate-800 border-2 border-slate-600 flex items-center justify-center mx-auto mb-6">
            ... (svg) ...
        </div>

        <h2 class="text-lg font-semibold text-white mb-1">Session Locked</h2>
        <p class="text-sm text-slate-400 mb-1">{runName}</p>
        <p class="text-xs text-slate-500 mb-6">{timeRemaining}</p>

        <!-- User info -->
        <p class="text-xs text-slate-400 mb-3">{userEmail}</p>

        <!-- Password input -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="space-y-3" onkeydown={handleKeydown}>
            ... (input + error + unlock button) ...
        </div>

        <!-- Queue status -->
        {#if queueCount > 0}
            <p class="mt-4 text-xs text-slate-500">
                {queueCount} item{queueCount !== 1 ? 's' : ''} queued for sync
            </p>
        {/if}
    </div>
</div>
```

Replace with:

```svelte
<Dialog.Root open={true}>
    <Dialog.Content
        class="w-screen h-screen max-w-none max-h-none rounded-none border-0 p-0 bg-slate-900 flex items-center justify-center"
        showCloseButton={false}
        escapeKeydownBehavior="ignore"
        interactOutsideBehavior="ignore"
    >
        <div class="w-[95%] max-w-sm text-center">
            <!-- Lock icon -->
            <div class="w-16 h-16 rounded-full bg-slate-800 border-2 border-slate-600 flex items-center justify-center mx-auto mb-6">
                ... (svg — unchanged) ...
            </div>

            <Dialog.Title class="text-lg font-semibold text-white mb-1">Session Locked</Dialog.Title>
            <Dialog.Description class="text-sm text-slate-400 mb-1">{runName}</Dialog.Description>
            <p class="text-xs text-slate-500 mb-6">{timeRemaining}</p>

            <!-- User info -->
            <p class="text-xs text-slate-400 mb-3">{userEmail}</p>

            <!-- Password input -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="space-y-3" onkeydown={handleKeydown}>
                ... (input + error + unlock button — unchanged) ...
            </div>

            <!-- Queue status -->
            {#if queueCount > 0}
                <p class="mt-4 text-xs text-slate-500">
                    {queueCount} item{queueCount !== 1 ? 's' : ''} queued for sync
                </p>
            {/if}
        </div>
    </Dialog.Content>
</Dialog.Root>
```

Changes to notice:
- `<div class="fixed inset-0 z-50 bg-slate-900 …">` becomes `<Dialog.Root open={true}><Dialog.Content class="…">`.
- Dialog.Content class explicitly overrides every default we don't want:
  - `w-screen h-screen max-w-none max-h-none` — full viewport
  - `rounded-none border-0` — no card rounding/border
  - `p-0` — no default padding; inner card drives layout
  - `bg-slate-900 flex items-center justify-center` — preserves the original styling
- `showCloseButton={false}` — no X escape hatch.
- `escapeKeydownBehavior="ignore"` + `interactOutsideBehavior="ignore"` — Escape and outside-click cannot dismiss the lock.
- `<h2>` becomes `<Dialog.Title>` and the primary `<p>` becomes `<Dialog.Description>` for screen reader wiring. `Dialog.Title` is required for aria-labelledby.

- [ ] **Step 3: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/FieldModeLockScreen.svelte
git commit -m "refactor(ui): migrate FieldModeLockScreen to Dialog with locked dismissal [TD-0068]"
```

---

## Task 8: Migrate `ExpiryWarningBanner.svelte` critical branch (Category B)

Only the `warningLevel === 'critical' && !dismissed` branch (lines ~23–44) is a full-screen modal. The amber/red inline banners (lines ~45–58) are NOT modals and must be left untouched.

**Files:**
- Modify: `frontend/src/lib/components/ExpiryWarningBanner.svelte` (lines ~23–44)

- [ ] **Step 1: Add the Dialog import**

In the `<script lang="ts">` block at the top, add:

```ts
import * as Dialog from '$lib/components/ui/dialog';
```

- [ ] **Step 2: Replace the critical-branch overlay**

Find (around line 23):

```svelte
{#if warningLevel === 'critical' && !dismissed}
    <!-- Full-screen modal for critical (<1h) -->
    <div class="fixed inset-0 z-50 bg-red-900/80 backdrop-blur-sm flex items-center justify-center">
        <div class="bg-white rounded-xl shadow-2xl p-8 max-w-sm text-center">
            <div class="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                ... (svg) ...
            </div>
            <h3 class="text-lg font-bold text-slate-900 mb-2">Session Expiring Soon</h3>
            <p class="text-sm text-slate-600 mb-2">{timeRemaining}</p>
            <p class="text-sm text-slate-500 mb-6">
                Your offline session is about to expire. Connect to the internet and sync your data now to avoid losing queued items.
            </p>
            <button
                onclick={() => (dismissed = true)}
                class="px-6 py-2.5 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors"
            >
                I Understand
            </button>
        </div>
    </div>
{:else if (warningLevel === 'amber' || warningLevel === 'red') && !dismissed}
    ... (leave inline banner untouched) ...
{/if}
```

Replace only the critical branch body with:

```svelte
{#if warningLevel === 'critical' && !dismissed}
    <!-- Full-screen modal for critical (<1h) -->
    <Dialog.Root open={true}>
        <Dialog.Content
            class="max-w-sm text-center p-8 bg-white rounded-xl shadow-2xl"
            showCloseButton={false}
            escapeKeydownBehavior="ignore"
            interactOutsideBehavior="ignore"
        >
            <div class="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                ... (svg — unchanged) ...
            </div>
            <Dialog.Title class="text-lg font-bold text-slate-900 mb-2">Session Expiring Soon</Dialog.Title>
            <Dialog.Description class="text-sm text-slate-600 mb-2">{timeRemaining}</Dialog.Description>
            <p class="text-sm text-slate-500 mb-6">
                Your offline session is about to expire. Connect to the internet and sync your data now to avoid losing queued items.
            </p>
            <button
                onclick={() => (dismissed = true)}
                class="px-6 py-2.5 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors cursor-pointer"
            >
                I Understand
            </button>
        </Dialog.Content>
    </Dialog.Root>
{:else if (warningLevel === 'amber' || warningLevel === 'red') && !dismissed}
    ... (inline amber/red banner — leave unchanged) ...
{/if}
```

Changes to notice:
- Only the critical branch changes. The amber/red inline banner code stays exactly as-is.
- `open={true}` combined with the outer `{#if warningLevel === 'critical' && !dismissed}` gives us the right semantics: the component renders only during critical + non-dismissed, and while rendered the Dialog is open. When user clicks "I Understand", `dismissed` flips and the outer `{#if}` tears the whole Dialog out of the tree.
- The `bg-red-900/80 backdrop-blur-sm` that was on the original overlay is dropped. The shared `Dialog.Overlay` uses `bg-black/50` via the default overlay component — close-enough visual parity for a critical-warning scrim. If qa-verify flags the color change as a regression, we can revisit by styling the overlay; for now, accept the shared scrim.
- `escapeKeydownBehavior="ignore"` + `interactOutsideBehavior="ignore"` + `showCloseButton={false}` — the only dismissal path is the "I Understand" button.

- [ ] **Step 3: Run svelte-check**

Run: `cd frontend && npm run check`
Expected: 0 errors introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/ExpiryWarningBanner.svelte
git commit -m "refactor(ui): migrate ExpiryWarningBanner critical branch to Dialog [TD-0068]"
```

---

## Task 9: Full-repo verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm no stale `fixed inset-0 z-50` overlays remain in the 7 migrated files**

Run:
```bash
grep -n "fixed inset-0 z-50\|fixed inset-0 z-\[60\]" \
  frontend/src/lib/components/RoleWizard.svelte \
  frontend/src/lib/components/FieldModeRoleWizard.svelte \
  frontend/src/lib/components/FieldModeLockScreen.svelte \
  frontend/src/lib/components/run/RunDocuments.svelte \
  frontend/src/lib/components/settings/TemplateUploadModal.svelte \
  frontend/src/lib/components/ExpiryWarningBanner.svelte
```
Expected: **no matches.**

For `TemplateConvertModal.svelte`, one `fixed inset-0 z-50` is expected to remain (the main shell at line 444 which is explicitly out of scope). Verify that exactly:
```bash
grep -cn "fixed inset-0 z-50" frontend/src/lib/components/TemplateConvertModal.svelte
```
Expected: `1` (one remaining — the main shell). If `2` or more, Task 6 missed the nested save dialog.

- [ ] **Step 2: Run svelte-check across the whole frontend**

Run: `cd frontend && npm run check`
Expected: 0 errors. (Warnings are acceptable if they were present before TD-0068.)

- [ ] **Step 3: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: build completes without errors.

- [ ] **Step 4: Run the existing Vitest suite**

Run: `cd frontend && npm run test`
Expected: all pre-existing tests still pass. (No new tests added in TD-0068 per the spec's testing strategy.)

- [ ] **Step 5: Start the dev servers and hand off to qa-verify**

Start backend + frontend dev servers per the root `CLAUDE.md` commands. Then dispatch the `qa-verify` agent with:

- Login instructions: admin credentials at `localhost:5173/login` (any password works in dev).
- Feature: "TD-0068 replaced 7 hand-rolled modal overlays with the shared Dialog component."
- Pages/features to check:
  1. Run step detail → capture image → "Tag Image Parameters" dialog (from RoleWizard).
  2. Field Mode run → capture image → "Tag Image Parameters" dialog (from FieldModeRoleWizard).
  3. Field Mode session lock (simulate lock / force via devtools) — Escape must NOT dismiss.
  4. Run detail → Export → "Batch Record Options" download dialog (RunDocuments).
  5. Settings → Templates tab → "Upload Template" button (TemplateUploadModal).
  6. Settings → Templates tab → "Convert" flow → save dialog (nested TemplateConvertModal save).
  7. Expiry warning critical branch — Escape must NOT dismiss; only "I Understand" closes it.
- Required regression checks:
  - Each Category A modal closes on Escape and on outside-click.
  - Lock screen + critical expiry warning do NOT close on Escape or outside-click.
  - Visual parity: each modal's sizing and colors match current main.
  - No duplicate close buttons visible.
  - For Convert flow: save dialog stacks above the main shell.

- [ ] **Step 6: No commit**

This task is verification-only.

---

## Task 10: Log follow-up task and close out

**Files:** none

- [ ] **Step 1: Log the follow-up ClickUp task**

Use `/add_task` to create a TECH_DEBT task:

- Title: `Migrate TemplateConvertModal main shell (line 444) away from hand-rolled overlay`
- Description: Full-screen editor with chat + resizable preview was left untouched by TD-0068. Decide whether to migrate to Dialog with full-viewport overrides (similar pattern to FieldModeLockScreen), convert to a routed page, or keep as-is. Link to TD-0068 spec.
- Priority: P3 (Low). No accessibility gap since focus doesn't escape a full-viewport editor in the same way a centered card does; this is an architectural tidy-up, not a safety issue.

- [ ] **Step 2: Summarize for the user**

Present:
- What changed: 7 hand-rolled modal overlays → shared `Dialog` (5 true-modal, 2 locked-dismissal).
- Acceptance criteria status: all 3 criteria met (Dialog used, focus trap + escape-to-close work where appropriate, visual parity per qa-verify).
- Deferred: TemplateConvertModal main shell (tracked as new task).
- Ask the user to verify.

- [ ] **Step 3: After user sign-off**

Post a comment on ClickUp task `86e0w0bam` with:
- Files changed (list)
- Behavior preserved (lock screen + critical expiry undismissable)
- Link to follow-up TECH_DEBT task for the main shell

Then update the task status to `complete` via `clickup_update_task`.

---

## Self-Review Notes

- **Spec coverage:** All 7 targets covered. The spec's "deferred" 8th (TemplateConvertModal main shell) is handled by Task 10 logging a follow-up.
- **Type consistency:** Prop names used consistently — `showTagSelector`, `showModal`, `showUpload`, `showSaveDialog`, `showUpload` at callsite, all match current state in each file. `open` is the new prop name for `TemplateUploadModal` (formerly `onClose` → gone).
- **Scope discipline:** `field/+page.svelte` (superseded TD-0067a) and `TemplateConvertModal` main shell are explicitly out of scope and called out multiple times.
- **Stacking risk:** Called out in Task 6 and flagged for qa-verify.
- **Visual parity risk:** Called out for `ExpiryWarningBanner` (red-tinted scrim → black scrim) and `RoleWizard` (bg-white → bg-background). Both flagged for qa-verify with a revert path if necessary.
