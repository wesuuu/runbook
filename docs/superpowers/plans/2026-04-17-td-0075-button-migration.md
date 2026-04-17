# TD-0075: Button Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every raw `<button>` in `frontend/src/routes` and `frontend/src/lib/components` with the shared `Button` component, extend the Button API with a `tab` variant and `rounded` prop, and collapse off-schema colors (teal/emerald/slate/amber) onto the design system unless there's a semantic reason.

**Architecture:** Work in a dedicated git worktree branched from `main`. Task 1 sets up the worktree. Task 2 extends the Button API. Tasks 3–10 migrate buttons grouped by directory with chunked commits for reviewability. Task 11 is cleanup/verification. No behavior changes — only styling and component-composition changes.

**Tech Stack:** Svelte 5 (runes), TypeScript, Tailwind CSS 4, tailwind-variants, bits-ui/shadcn-svelte, Vite, Vitest, svelte-check.

**Spec reference:** `docs/superpowers/specs/2026-04-17-td-0075-button-migration-design.md`

---

## Conventions Used Throughout

### Color-to-variant mapping (apply to every button you touch)

| Inline class pattern | Target |
|---|---|
| `bg-primary text-primary-foreground hover:bg-primary/90` | `variant="default"` |
| `bg-teal-600 text-white hover:bg-teal-700` | `variant="default"` (schema drift) |
| `bg-emerald-600 text-white` | `variant="default"` (schema drift) |
| `bg-slate-800 text-white` / `bg-slate-900 text-white` | `variant="default"` (schema drift) |
| `bg-red-*` or `text-red-*` on destructive action | `variant="destructive"` |
| `bg-destructive text-destructive-foreground` | `variant="destructive"` |
| `bg-secondary / bg-muted / bg-slate-100` (Cancel buttons) | `variant="secondary"` |
| `bg-background border ... hover:bg-accent` | `variant="outline"` |
| `hover:bg-accent` / `hover:bg-muted` text-only | `variant="ghost"` |
| `text-primary underline-offset-4 hover:underline` | `variant="link"` |
| Border-bottom tab pattern (`border-b-2 ...`) | `variant="tab"` |
| `rounded-full` pill/chip | variant + `rounded="full"` |

### Classes to STRIP (Button provides them)

Delete these from each migrated caller unless justified:
- `cursor-pointer`, `disabled:cursor-not-allowed`
- `disabled:opacity-50`, `disabled:pointer-events-none`
- `transition-all duration-150`, `transition-colors`
- `focus-visible:*` (ring/outline)
- `inline-flex items-center justify-center gap-2` (unless container semantics differ)
- `whitespace-nowrap`, `shrink-0`, `outline-none`
- `[&_svg]:pointer-events-none`, `[&_svg]:shrink-0`

### Classes to KEEP via `class=` prop

- Layout: `w-full`, `mt-2`, `self-end`, `flex-1`, `mx-auto`, grid/flex positioning
- Genuine one-off colors (documented in PR)
- Scoped-CSS class names that still express unique shape (will try to delete their `<style>` rules too if orphaned)

### Import statement (add to any .svelte file missing it)

```typescript
import { Button } from "$lib/components/ui/button";
```

### Keep-raw list

Leave these as `<button>`:
- `frontend/src/lib/components/ui/button/button.svelte` (the component itself)
- Full-card click targets in `frontend/src/routes/+page.svelte` (3 buttons: counter cards, "Needs Your Action" cards, "Active Runs" cards) — genuinely card-shaped
- Any button with a semantic warning color (`bg-amber-*`) — document in PR

---

## Task 1: Worktree setup and spec commit

**Files:**
- Worktree path: `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button`
- Branch: `tech-debt/td-0075-button-migration` (branched from `main`)

- [ ] **Step 1: Check main is up-to-date**

Run:
```bash
cd /home/wesuuu/Code/trellisbio
git fetch origin main
git log --oneline origin/main -1
```
Expected: recent commit SHA on main.

- [ ] **Step 2: Create worktree off main**

Run:
```bash
cd /home/wesuuu/Code/trellisbio
git worktree add .claude/worktrees/td-0075-button -b tech-debt/td-0075-button-migration origin/main
cd .claude/worktrees/td-0075-button
git status
```
Expected: on branch `tech-debt/td-0075-button-migration`, clean tree, HEAD at origin/main.

- [ ] **Step 3: Install frontend deps in the worktree**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button/frontend
npm install
```
Expected: install completes without errors.

- [ ] **Step 4: Copy spec into worktree and commit**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button
cp /home/wesuuu/Code/trellisbio/docs/superpowers/specs/2026-04-17-td-0075-button-migration-design.md docs/superpowers/specs/
cp /home/wesuuu/Code/trellisbio/docs/superpowers/plans/2026-04-17-td-0075-button-migration.md docs/superpowers/plans/
git add docs/superpowers/specs/2026-04-17-td-0075-button-migration-design.md docs/superpowers/plans/2026-04-17-td-0075-button-migration.md
git commit -m "docs(td-0075): add button migration spec and plan [TD-0075]"
```
Expected: commit succeeds on `tech-debt/td-0075-button-migration`.

- [ ] **Step 5: Start backend and frontend on alternate ports**

Frontend dev server (background):
```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button/frontend
VITE_API_PORT=8000 npm run dev -- --port 5183
```
(Keep main backend on :8000 — no backend changes in this work.)
Expected: Vite serves on http://localhost:5183.

---

## Task 2: Extend Button component API

**Files:**
- Modify: `frontend/src/lib/components/ui/button/button.svelte`

### 2A. Add `tab` variant

- [ ] **Step 1: Read current Button component**

Run: `cat frontend/src/lib/components/ui/button/button.svelte`
Expected: see existing `tv()` definition with variants.

- [ ] **Step 2: Add `tab` variant to buttonVariants**

Edit `frontend/src/lib/components/ui/button/button.svelte`, inside the `variants.variant` object, add:

```typescript
tab: "border-b-2 border-transparent text-muted-foreground hover:text-foreground rounded-none shadow-none data-[active=true]:border-foreground data-[active=true]:text-foreground",
```

Note: uses `data-active` attribute for selected state because runtime conditional classes (`class:border-foreground={active}`) work fine but `data-active` is more idiomatic with shadcn. Both are supported.

- [ ] **Step 3: Verify with `npm run check`**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button/frontend
npm run check
```
Expected: passes (0 errors, 0 warnings in Button component).

### 2B. Add `rounded` prop

- [ ] **Step 4: Add `rounded` variant dimension**

Edit `frontend/src/lib/components/ui/button/button.svelte`:

1. Inside `variants:`, add a new dimension after `size`:
   ```typescript
   rounded: {
       default: "",
       full: "rounded-full",
   },
   ```
2. Inside `defaultVariants:`, add:
   ```typescript
   rounded: "default",
   ```
3. In the `<script lang="ts">` (instance) block, add `rounded = "default"` to the props destructure:
   ```typescript
   let {
       class: className,
       variant = "default",
       size = "default",
       rounded = "default",
       ref = $bindable(null),
       href = undefined,
       type = "button",
       disabled,
       children,
       ...restProps
   }: ButtonProps = $props();
   ```
4. Add `ButtonRounded` type export in the module block:
   ```typescript
   export type ButtonRounded = VariantProps<typeof buttonVariants>["rounded"];
   ```
5. Update `ButtonProps`:
   ```typescript
   export type ButtonProps = WithElementRef<HTMLButtonAttributes> &
       WithElementRef<HTMLAnchorAttributes> & {
           variant?: ButtonVariant;
           size?: ButtonSize;
           rounded?: ButtonRounded;
       };
   ```
6. Pass `rounded` into both `buttonVariants({...})` calls (the `<a>` and `<button>` branches):
   ```typescript
   class={cn(buttonVariants({ variant, size, rounded }), className)}
   ```

- [ ] **Step 5: Update the Button index barrel**

Edit `frontend/src/lib/components/ui/button/index.ts` and add `ButtonRounded` export alongside `ButtonSize` and `ButtonVariant`:

```typescript
import Root, {
    type ButtonProps,
    type ButtonRounded,
    type ButtonSize,
    type ButtonVariant,
    buttonVariants,
} from "./button.svelte";

export {
    Root,
    type ButtonProps as Props,
    //
    Root as Button,
    buttonVariants,
    type ButtonProps,
    type ButtonRounded,
    type ButtonSize,
    type ButtonVariant,
};
```

- [ ] **Step 6: Verify with `npm run check`**

Run:
```bash
npm run check
```
Expected: 0 errors.

- [ ] **Step 7: Commit Button API changes**

```bash
git add frontend/src/lib/components/ui/button/button.svelte frontend/src/lib/components/ui/button/index.ts
git commit -m "feat(button): add tab variant and rounded prop [TD-0075]"
```

---

## Task 3: Migrate UI primitives

**Files:**
- Modify: `frontend/src/lib/components/ui/FullScreenModal.svelte` (1 button)
- Modify: `frontend/src/lib/components/ui/confirm-dialog.svelte` (2 buttons)

### 3A. FullScreenModal

- [ ] **Step 1: Read the file**

Run: `cat frontend/src/lib/components/ui/FullScreenModal.svelte`
Locate the raw `<button>` (around line 25 — the X close icon).

- [ ] **Step 2: Replace the close button**

Pattern (current):
```svelte
<button
    onclick={onClose}
    class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors ..."
    aria-label="Close"
>
    <X class="h-4 w-4" />
</button>
```

Replace with:
```svelte
<Button
    variant="ghost"
    size="icon-sm"
    onclick={onClose}
    aria-label="Close"
>
    <X class="h-4 w-4" />
</Button>
```

Add the import near the top of the `<script>`:
```typescript
import { Button } from "$lib/components/ui/button";
```

- [ ] **Step 3: Verify typecheck**

Run: `npm run check`
Expected: 0 errors.

### 3B. confirm-dialog

- [ ] **Step 4: Read the file**

Run: `cat frontend/src/lib/components/ui/confirm-dialog.svelte`
Locate the 2 raw `<button>` elements (Cancel + Confirm).

- [ ] **Step 5: Replace both buttons**

Cancel button — replace the raw `<button>` with:
```svelte
<Button variant="secondary" onclick={handleCancel}>
    {cancelText}
</Button>
```

Confirm button — replace with (respect `destructive` prop if the dialog has one):
```svelte
<Button
    variant={destructive ? "destructive" : "default"}
    onclick={handleConfirm}
>
    {confirmText}
</Button>
```

Add `import { Button } from "$lib/components/ui/button";` to the script block if missing.

- [ ] **Step 6: Verify typecheck and test run**

Run:
```bash
npm run check
npm run test -- --run
```
Expected: no errors from these files.

- [ ] **Step 7: Smoke test in browser**

Open http://localhost:5183, trigger any confirm dialog (e.g., delete protocol in a project). Verify buttons look correct and still close the dialog.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/components/ui/FullScreenModal.svelte frontend/src/lib/components/ui/confirm-dialog.svelte
git commit -m "refactor(ui): migrate FullScreenModal and confirm-dialog to Button [TD-0075]"
```

---

## Task 4: Migrate `frontend/src/routes/+layout.svelte` and `+page.svelte`

**Files:**
- Modify: `frontend/src/routes/+layout.svelte` (1 button)
- Modify: `frontend/src/routes/+page.svelte` (8 buttons — 3 are KEEP-RAW card containers)

### 4A. +layout.svelte

- [ ] **Step 1: Open the file, find the raw button**

Run: `rg -n '<button' frontend/src/routes/+layout.svelte`

- [ ] **Step 2: Migrate**

Apply the color-to-variant mapping from "Conventions" above. Strip Button-provided classes. Add `import { Button } from "$lib/components/ui/button"` if needed.

- [ ] **Step 3: `npm run check`**

Expected: 0 errors.

### 4B. +page.svelte

- [ ] **Step 4: Locate all 8 raw buttons**

Run: `rg -n '<button' frontend/src/routes/+page.svelte`
Expected lines: 276, 307, 350, (and others).

- [ ] **Step 5: KEEP the three card-clickable buttons RAW**

These are the full-card click targets. Leave as `<button>` but verify they retain:
- `cursor-pointer`
- Visible hover state
- `type="button"` if inside a form context
- Accessible focus ring

Card buttons identified:
- Line 276–288: counter cards (grid on dashboard)
- Line 350–388 (approximate): "Needs Your Action" run cards
- Line 393+ (approximate): "Active Runs" cards

Do not touch these aside from optionally adding `type="button"` for safety.

- [ ] **Step 6: Migrate the remaining ~5 buttons**

Example: the "Sync Now" button at line 307-313:
```svelte
<!-- before -->
<button
    onclick={syncOrphaned}
    disabled={syncingOrphans}
    class="px-3 py-1.5 bg-teal-600 text-white rounded-lg text-xs font-medium hover:bg-teal-700 transition-colors duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
>
    {syncingOrphans ? 'Syncing...' : 'Sync Now'}
</button>

<!-- after (teal-600 is off-schema → map to default) -->
<Button
    variant="default"
    size="sm"
    onclick={syncOrphaned}
    disabled={syncingOrphans}
>
    {syncingOrphans ? 'Syncing...' : 'Sync Now'}
</Button>
```

Apply the same pattern-matching to each remaining button on this page.

- [ ] **Step 7: `npm run check`**

Expected: 0 errors.

- [ ] **Step 8: Browser smoke test**

Open `http://localhost:5183/`. Verify:
- Counter cards still clickable and navigate correctly
- "Sync Now" button (if any orphaned runs) still triggers
- Action-required cards still clickable
- Styles look correct

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/+layout.svelte frontend/src/routes/+page.svelte
git commit -m "refactor(routes): migrate root layout and landing buttons to Button [TD-0075]"
```

---

## Task 5: Migrate route buttons — `/chat`, `/export`, `/field`

**Files:**
- Modify: `frontend/src/routes/chat/+page.svelte` (8 buttons)
- Modify: `frontend/src/routes/export/+page.svelte` (18 buttons)
- Modify: `frontend/src/routes/field/+page.svelte` (1 button)

- [ ] **Step 1: Locate all buttons per file**

```bash
rg -n '<button' frontend/src/routes/chat/+page.svelte frontend/src/routes/export/+page.svelte frontend/src/routes/field/+page.svelte
```

- [ ] **Step 2: Migrate chat page buttons**

Applying color-to-variant mapping to the 8 buttons:
- New chat ("+" button) — `variant="default" size="sm"`
- Send message (arrow icon) — `variant="default" size="icon-sm"`
- Thread item close/delete X — `variant="ghost" size="icon-sm"`
- Delete chat — `variant="destructive" size="sm"`
- "Start a conversation" empty state — `variant="default"`
- Thread list entry (clickable row) — assess: if it's a full row click, keep raw; if it's a sub-button, migrate
- Any other primary CTAs — `variant="default"`

Add `import { Button } from "$lib/components/ui/button";` to the top of `<script>`.

- [ ] **Step 3: Migrate export page buttons**

This is the highest button count (18). Export page has:
- Column group toggle chips (Input, Process, Output) — `variant="outline" size="sm" rounded="full"` (use `class="data-[active=true]:bg-foreground data-[active=true]:text-background"` or equivalent per-state class)
- Preset dropdown toggles — `variant="ghost" size="sm"`
- Column visibility toggles — `variant="ghost" size="sm"`
- Export/download primary action — `variant="default"`
- Reset/clear — `variant="ghost"` or `variant="link"`
- Retry on error — `variant="link"`

Apply mapping file-wide. Preserve every `onclick`/`bind:`/`aria-*` attribute.

- [ ] **Step 4: Migrate field page**

1 button; apply mapping.

- [ ] **Step 5: `npm run check`**

Expected: 0 errors.

- [ ] **Step 6: Browser smoke test**

- `http://localhost:5183/chat` — send a message, create new chat, delete chat
- `http://localhost:5183/export` — toggle filters, export button
- `http://localhost:5183/field` — smoke check

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/chat/+page.svelte frontend/src/routes/export/+page.svelte frontend/src/routes/field/+page.svelte
git commit -m "refactor(routes): migrate chat/export/field buttons to Button [TD-0075]"
```

---

## Task 6: Migrate route buttons — `/runs`, `/projects`, `/library`, `/experiments`, `/settings`

**Files:**
- Modify: `frontend/src/routes/runs/[id]/+page.svelte` (6 buttons)
- Modify: `frontend/src/routes/projects/[id]/+page.svelte` (8 buttons)
- Modify: `frontend/src/routes/library/[id]/+page.svelte` (4 buttons)
- Modify: `frontend/src/routes/library/+page.svelte` (1 button)
- Modify: `frontend/src/routes/experiments/[id]/+page.svelte` (3 buttons)
- Modify: `frontend/src/routes/settings/+page.svelte` (11 buttons)

- [ ] **Step 1: Locate all buttons**

```bash
rg -n '<button' frontend/src/routes/runs frontend/src/routes/projects frontend/src/routes/library frontend/src/routes/experiments frontend/src/routes/settings
```

- [ ] **Step 2: Migrate runs/[id]/+page.svelte**

6 buttons — likely mix of primary actions (Start Run, Finish Run), status toggles, icon actions. Apply mapping.

- [ ] **Step 3: Migrate projects/[id]/+page.svelte**

8 buttons. Tabs on this page use the border-bottom pattern — migrate those to `variant="tab"` with `data-active={activeTab === "runs"}` (or equivalent logic). Example:

```svelte
<!-- before -->
<button
    class="px-4 py-2.5 border-b-2 -mb-px {activeTab === 'runs' ? 'border-foreground text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}"
    onclick={() => setTab('runs')}
>
    Runs
</button>

<!-- after -->
<Button
    variant="tab"
    data-active={activeTab === 'runs'}
    onclick={() => setTab('runs')}
>
    Runs
</Button>
```

- [ ] **Step 4: Migrate library pages**

Apply mapping.

- [ ] **Step 5: Migrate experiments/[id]/+page.svelte**

Apply mapping.

- [ ] **Step 6: Migrate settings/+page.svelte**

11 buttons including the 6 top-level tabs (organization/teams/profile/notifications/ai/templates). Use `variant="tab"` for those.

- [ ] **Step 7: `npm run check`**

Expected: 0 errors.

- [ ] **Step 8: Browser smoke test**

For each page, open in browser and verify:
- `/runs/[some-id]` — action buttons work, no visual regression
- `/projects/[some-id]` — tabs switch correctly, styling matches
- `/library` + `/library/[some-id]` — delete/navigate buttons work
- `/experiments/[some-id]` — buttons functional
- `/settings` — all 6 tabs switch, form submissions work

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/runs frontend/src/routes/projects frontend/src/routes/library frontend/src/routes/experiments frontend/src/routes/settings
git commit -m "refactor(routes): migrate run/project/library/settings buttons to Button [TD-0075]"
```

---

## Task 7: Migrate top-level `lib/components/*.svelte`

**Files (top-level, not in a subdirectory):**
- `BatchRecordImportModal.svelte` (5)
- `ChatPanel.svelte` (4)
- `ChatSkillButtons.svelte` (4)
- `CompletionChart.svelte` (1)
- `CreateUnitOpModal.svelte` (3)
- `DocumentUploadDialog.svelte` (2)
- `EquipmentPickerModal.svelte` (4)
- `FieldModeHeader.svelte` (2)
- `FieldModeLockScreen.svelte` (1)
- `FieldModeRoleWizard.svelte` (9)
- `GoOfflineDialog.svelte` (2)
- `ImageAnalysisDialog.svelte` (6)
- `ImageGallery.svelte` (2)
- `Inspector.svelte` (7)
- `MobileNav.svelte` (1)
- `NotificationBell.svelte` (3)
- `PdfPreviewDrawer.svelte` (2)
- `ProjectsDropdown.svelte` (1)
- `ProtocolImportModal.svelte` (2)
- `RoleWizard.svelte` (10)
- `TemplateConvertModal.svelte` (6)
- `UserMenu.svelte` (1)
- `VersionHistoryDrawer.svelte` (1)
- `AiSettingsTab.svelte` (6)
- `AuditTimeline.svelte` (2)
- `BarcodeScanner.svelte` (1)

Lib/Counter.svelte — demo/example file (1 button); migrate or leave — migrate if it references the app's design system, otherwise leave. **Leave it** (it's a demo; not in user flow).

- [ ] **Step 1: Batch-process these files**

For each file, execute this micro-loop:

1. `rg -n '<button' <path>` — list all raw buttons.
2. For each button, apply the color-to-variant mapping. Strip Button-provided classes. Migrate to `<Button variant=... size=... [rounded=...] class=...>`.
3. Add `import { Button } from "$lib/components/ui/button"` to the `<script>` block if missing.
4. If the file has a `<style>` block with class rules that now have no consumer (e.g., `.schema-add-btn { ... }` after removing the `class="schema-add-btn"`), delete those rules.
5. Verify with `npm run check` after each 3–5 files to catch regressions early.

- [ ] **Step 2: Specific guidance for high-churn files**

- **Inspector.svelte (7 buttons)** — schema editor row remove/add, save-as-new, cancel, etc. Most are `variant="ghost"` or `variant="secondary"`. Remove `.schema-add-btn`, `.schema-toggle`, etc. from `<style>` block afterward.
- **RoleWizard.svelte (10 buttons)** — step navigation, role chips. Role chips may be `variant="outline" rounded="full"` or `variant="secondary" rounded="full"` depending on pattern.
- **ChatPanel.svelte (4 buttons)** — send, close, thread actions. Per chat page patterns.
- **AiSettingsTab.svelte (6 buttons)** — settings form actions + link-style toggles. Use `default`/`secondary`/`link` as appropriate.
- **TemplateConvertModal.svelte (6 buttons)** — modal close + action buttons.

- [ ] **Step 3: `npm run check` after each ~10 files**

Expected: 0 errors.

- [ ] **Step 4: Browser smoke test on the heavy flows**

- Open a run → Inspector → edit params → use schema editor
- Open role wizard → step through
- Open chat panel (if reachable in UI)
- Open settings tabs → AI settings
- Open protocol import modal

- [ ] **Step 5: Commit in 2 chunks if needed**

First chunk (roughly half):
```bash
git add <files>
git commit -m "refactor(components): migrate modals and panels to Button [TD-0075]"
```
Second chunk:
```bash
git add <files>
git commit -m "refactor(components): migrate wizards and toolbars to Button [TD-0075]"
```

---

## Task 8: Migrate `lib/components/protocol/`

**Files:**
- `CanvasToolbar.svelte` (10 buttons — toolbar heavy)
- `ProtocolSidebar.svelte` (7 buttons)

- [ ] **Step 1: Locate buttons**

```bash
rg -n '<button' frontend/src/lib/components/protocol
```

- [ ] **Step 2: Migrate CanvasToolbar.svelte**

10 buttons for the protocol editor canvas toolbar. Most are `variant="ghost" size="icon-sm"` (Undo/Redo/Zoom/Fit) with version nav buttons likely `variant="ghost" size="sm"`. Remove `.toolbar-btn` CSS rules from the `<style>` block if they become orphaned.

- [ ] **Step 3: Migrate ProtocolSidebar.svelte**

7 buttons — add-category, drag-handle buttons, action items. Apply mapping.

- [ ] **Step 4: `npm run check`**

Expected: 0 errors.

- [ ] **Step 5: Browser smoke test**

Open `/library/[id]` (protocol editor). Test:
- Toolbar (undo/redo/zoom/fit/handles/layout toggle)
- Sidebar category expansion
- Drag a unit op to canvas
- Right-click for context menu

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol
git commit -m "refactor(protocol): migrate canvas toolbar and sidebar buttons to Button [TD-0075]"
```

---

## Task 9: Migrate `lib/components/run/` and `lib/components/settings/`

**Files:**
- `run/RunAttachmentsTab.svelte` (2)
- `run/RunDocuments.svelte` (4)
- `run/RunEditMode.svelte` (2)
- `run/RunNotes.svelte` (1)
- `run/RoleAssignmentPanel.svelte` (5)
- `settings/TemplatesTab.svelte` (7)

- [ ] **Step 1: Locate buttons**

```bash
rg -n '<button' frontend/src/lib/components/run frontend/src/lib/components/settings
```

- [ ] **Step 2: Migrate run/ files**

Common patterns here:
- Upload/attach → `variant="default"` or `variant="secondary"` + icon
- Delete attachment → `variant="ghost" size="icon-sm"` (red on hover) or `variant="destructive" size="sm"`
- Note add/save → `variant="default" size="sm"`
- Role assign dropdown trigger → `variant="outline" size="sm"`

- [ ] **Step 3: Migrate settings/TemplatesTab.svelte**

7 buttons — upload, delete, set-default actions. Apply mapping.

- [ ] **Step 4: `npm run check`**

Expected: 0 errors.

- [ ] **Step 5: Browser smoke test**

- Open a run → Documents tab (upload, delete)
- Open a run → Notes tab
- Open a run → Role assignments
- Open settings → Templates tab

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/run frontend/src/lib/components/settings
git commit -m "refactor(run,settings): migrate run and templates tab buttons to Button [TD-0075]"
```

---

## Task 10: Migrate `lib/components/project/`

**Files:**
- `ActivityTab.svelte` (2)
- `AddExistingRunModal.svelte` (2)
- `AssignToExperimentModal.svelte` (2)
- `CreateRunModal.svelte` (2)
- `ExperimentsTab.svelte` (2)
- `ProjectDataTable.svelte` (2)
- `ProtocolsTab.svelte` (4)
- `RunsTab.svelte` (2)
- `SettingsTab.svelte` (9)

- [ ] **Step 1: Locate buttons**

```bash
rg -n '<button' frontend/src/lib/components/project
```

- [ ] **Step 2: Migrate all 9 files**

Common patterns:
- Modal action footer (Cancel/Confirm pair) → `secondary` + `default`
- Tab switcher inside a tab — follow `variant="tab"` pattern if border-bottom; otherwise segmented control (may need `rounded="full"` per-segment or `class` override)
- Add/create action → `variant="default" size="sm"`
- Delete row → `variant="destructive" size="sm"` or `variant="ghost" size="icon-sm"` with red-on-hover

SettingsTab.svelte (9) has segmented controls — these are tricky. For a 2–3 segment on/off toggle, prefer:

```svelte
<!-- before -->
<button class="px-2 py-1.5 rounded-l border {cond ? 'bg-primary text-primary-foreground' : 'bg-background'}">...</button>

<!-- after -->
<Button
    variant={cond ? "default" : "outline"}
    size="sm"
    class="rounded-l rounded-r-none"
>...</Button>
```

The inner `class` prop merges with the variant's classes via `cn()`, so `rounded-l rounded-r-none` overrides the default `rounded-md`. If this gets ugly, fall back to keeping the button raw and document it.

- [ ] **Step 3: `npm run check`**

Expected: 0 errors.

- [ ] **Step 4: Browser smoke test**

- Open project → each tab (Runs/Experiments/Protocols/Activity/Settings)
- Create-run modal flow
- Assign-to-experiment modal
- Protocols delete action

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/project
git commit -m "refactor(project): migrate project tab buttons to Button [TD-0075]"
```

---

## Task 11: Cleanup, audit, and final verification

- [ ] **Step 1: Final grep — should be minimal**

Run:
```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button
rg -n '<button' frontend/src/routes frontend/src/lib/components --glob '!frontend/src/lib/components/ui/button/button.svelte'
```

Expected: ≤10 matches. Each remaining match must be justified:
- The 3 card-clickable buttons in `routes/+page.svelte`
- Any button inside `ui/` primitives that must stay raw (Button itself — filtered by the glob)
- Any documented exception (semantic amber/warning button, etc.)

- [ ] **Step 2: Verify orphaned scoped CSS is cleaned up**

For each Svelte file with a `<style>` block that previously defined button-related classes (like `.schema-add-btn`, `.toolbar-btn`, `.btn-primary`), grep for remaining usages:

```bash
rg 'class="[^"]*\bschema-add-btn\b' frontend/src
rg 'class="[^"]*\btoolbar-btn\b' frontend/src
```

Expected: no matches. Delete the corresponding CSS rules.

- [ ] **Step 3: Run full typecheck**

```bash
cd frontend
npm run check
```
Expected: 0 errors, 0 warnings (pre-existing warnings are fine; no new ones).

- [ ] **Step 4: Run full unit tests**

```bash
npm run test -- --run
```
Expected: all tests pass.

- [ ] **Step 5: Run production build**

```bash
npm run build
```
Expected: build succeeds.

- [ ] **Step 6: Run Playwright e2e if available**

```bash
npm run test:e2e
```
Expected: all tests pass (or ignore if not set up locally).

- [ ] **Step 7: Final commit of any cleanup**

```bash
git add -A
git commit -m "chore(td-0075): clean up orphaned button styles [TD-0075]" || echo "nothing to commit"
```

- [ ] **Step 8: Summarize remaining raw buttons**

Write a paragraph for the PR description enumerating every remaining `<button>` in routes/components with its rationale. Save to `/tmp/td-0075-pr-notes.md` for reuse in the PR body.

---

## Task 12: QA verification

- [ ] **Step 1: Launch qa-verify agent**

Use the `qa-verify` agent (Agent tool, subagent_type=qa-verify) with:
- Login: wesu07@gmail.com / any password
- Feature: Button component migration — raw `<button>` replaced with shared Button across all routes and components
- Pages to check: `/` landing, `/runs/[id]`, `/projects/[id]`, `/library/[id]`, `/settings`, `/export`, `/chat`, `/experiments/[id]`
- Edge cases: tab buttons (settings, project detail, document upload), chip/pill (export filters), confirm dialogs, full-card click targets on landing, icon-only close buttons in modals/drawers

qa-verify must fix any FAIL/POLISH issues before returning.

- [ ] **Step 2: Address any issues returned**

If qa-verify returns with items to fix, resolve them and commit:
```bash
git commit -am "fix(td-0075): address qa-verify findings [TD-0075]"
```

---

## Task 13: User manual verification

**Blocker before any push or PR. Do not skip.**

- [ ] **Step 1: Summarize work for the user**

Provide a concise summary to the user:
- Number of files migrated and number of buttons replaced
- Button API changes (`tab` variant, `rounded` prop)
- Any exceptions (buttons left raw) with rationale
- Color-schema violations fixed (e.g., teal-600 → default, emerald-600 → default)
- Dev server URL for manual testing: `http://localhost:5183`

- [ ] **Step 2: Request manual walk-through**

Ask the user to verify key flows themselves in the browser (in addition to qa-verify's automated check):
- Landing dashboard: counter cards still clickable, dashboard action cards
- Protocol editor: toolbar (undo/redo/zoom/fit), sidebar (drag unit op), inspector (edit params, schema editor, save-as-new)
- Runs: action buttons (start/finish), documents tab, notes, role assignments
- Settings: all tabs switch, AI settings forms, templates tab
- Chat: send message, new chat, delete chat
- Export: filter toggles, preset, export action
- Confirm dialogs: any delete action shows dialog with styled Cancel/Confirm
- Full-screen modals: close X icon works

Explicitly wait for the user to confirm "looks good" before proceeding. If they flag regressions, fix them and re-run qa-verify + manual verification loop.

- [ ] **Step 3: User sign-off captured**

Do not proceed to Task 14 until the user explicitly confirms they've verified and are happy with the migration.

---

## Task 14: Push branch and open PR

- [ ] **Step 1: Push branch**

```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0075-button
git push -u origin tech-debt/td-0075-button-migration
```

- [ ] **Step 2: Open PR to main**

Use `gh pr create`:
```bash
gh pr create --title "refactor: migrate raw <button> elements to shared Button [TD-0075]" --body "$(cat <<'EOF'
## Summary
- Replaces 200+ raw <button> elements across routes and lib/components with the shared Button component
- Adds `tab` variant and `rounded` prop to Button
- Collapses off-schema colors (teal/emerald/slate) onto design system variants
- Closes TD-0070 (cursor-pointer audit) for all migrated sites

## Test plan
- [x] `npm run check` passes
- [x] `npm run test` passes
- [x] `npm run build` succeeds
- [x] qa-verify agent smoke tested landing/runs/projects/library/settings/export/chat
- [x] Remaining raw <button> elements documented with rationale

## Remaining raw <button> (intentional)
[paste contents from /tmp/td-0075-pr-notes.md]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Report PR URL**

Copy PR URL and report back to user.

---

## Self-Review Notes

**Spec coverage:**
- Goal 1 (every raw button migrated unless genuinely unique): Tasks 3–10 cover all 58 files. Task 11 final grep enforces.
- Goal 2 (Button owns container + behavior): Task 2 extends API; Tasks 3–10 strip caller-owned classes.
- Goal 3 (off-schema colors → schema): Color-to-variant mapping at top of plan.
- Goal 4 (closes TD-0070): covered by class-stripping rule (removes redundant `cursor-pointer`).

**Placeholder scan:** no TBDs. All code samples concrete. File paths exact.

**Type consistency:** `ButtonVariant`, `ButtonSize`, `ButtonRounded` defined in Task 2 and exported via index barrel. All subsequent tasks reference `variant=`, `size=`, `rounded=` props consistently.

**Scope:** single migration; no cross-subsystem dependencies. Ready to execute as one plan.
