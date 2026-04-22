# TD-0080 Components Reorg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every root-level file in `frontend/src/lib/components/` into a domain subdirectory and update all imports so the build stays green.

**Architecture:** Pure rename refactor. One commit per bucket (bucket dir + `git mv` of files + import updates for that bucket's files). No behavioral changes, no new abstractions. `npm run check` is the gate between each commit.

**Tech Stack:** Svelte 5, Vite, TypeScript (`$lib` path alias to `src/lib`), Vitest.

**Spec:** [`docs/superpowers/specs/2026-04-22-td-0080-components-reorg-design.md`](../specs/2026-04-22-td-0080-components-reorg-design.md)

---

## General conventions for every task

- All paths are relative to the repo root unless noted.
- Run all `npm` commands from `frontend/`.
- All file moves use `git mv` (preserves history; rename detection).
- All **absolute** import updates rewrite `$lib/components/<Name>.svelte` to `$lib/components/<bucket>/<Name>.svelte`.
- For **relative** imports (`./X.svelte`) inside a component that's being moved, rewrite them to **absolute** `$lib/components/<targetBucket>/X.svelte` even when both files end up in the same bucket. This makes every import self-describing.
- After each task's edits, run `cd frontend && npm run check`. Any error → stop and fix before committing.
- Commit messages use the `refactor(scope): <desc> (TD-0080)` format.

---

## Task 1: Extend `protocol/` with editor components

**Files:**
- Move: `frontend/src/lib/components/Inspector.svelte` → `frontend/src/lib/components/protocol/Inspector.svelte`
- Move: `frontend/src/lib/components/UnitOpNode.svelte` → `frontend/src/lib/components/protocol/UnitOpNode.svelte`
- Move: `frontend/src/lib/components/SwimLaneNode.svelte` → `frontend/src/lib/components/protocol/SwimLaneNode.svelte`
- Move: `frontend/src/lib/components/ProcessStartNode.svelte` → `frontend/src/lib/components/protocol/ProcessStartNode.svelte`
- Move: `frontend/src/lib/components/ProcessStartInspector.svelte` → `frontend/src/lib/components/protocol/ProcessStartInspector.svelte`
- Move: `frontend/src/lib/components/TimeAxis.svelte` → `frontend/src/lib/components/protocol/TimeAxis.svelte`
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte` (update 6 imports)

- [ ] **Step 1: Move files with `git mv`**

```bash
cd frontend/src/lib/components
git mv Inspector.svelte protocol/Inspector.svelte
git mv UnitOpNode.svelte protocol/UnitOpNode.svelte
git mv SwimLaneNode.svelte protocol/SwimLaneNode.svelte
git mv ProcessStartNode.svelte protocol/ProcessStartNode.svelte
git mv ProcessStartInspector.svelte protocol/ProcessStartInspector.svelte
git mv TimeAxis.svelte protocol/TimeAxis.svelte
```

- [ ] **Step 2: Update absolute imports in `routes/protocols/[id]/+page.svelte` (lines 56–64, except the CreateUnitOpModal/VersionHistoryDrawer/PdfPreviewDrawer lines — those are for later tasks)**

Replace each of the 6 lines:

```svelte
import UnitOpNode from "$lib/components/UnitOpNode.svelte";
import SwimLaneNode from "$lib/components/SwimLaneNode.svelte";
import ProcessStartNode from "$lib/components/ProcessStartNode.svelte";
import Inspector from "$lib/components/Inspector.svelte";
import ProcessStartInspector from "$lib/components/ProcessStartInspector.svelte";
import TimeAxis from "$lib/components/TimeAxis.svelte";
```

with:

```svelte
import UnitOpNode from "$lib/components/protocol/UnitOpNode.svelte";
import SwimLaneNode from "$lib/components/protocol/SwimLaneNode.svelte";
import ProcessStartNode from "$lib/components/protocol/ProcessStartNode.svelte";
import Inspector from "$lib/components/protocol/Inspector.svelte";
import ProcessStartInspector from "$lib/components/protocol/ProcessStartInspector.svelte";
import TimeAxis from "$lib/components/protocol/TimeAxis.svelte";
```

- [ ] **Step 3: Update the relative import inside the moved `Inspector.svelte`**

`frontend/src/lib/components/protocol/Inspector.svelte` currently has (line 6):

```svelte
import EquipmentPickerModal from "./EquipmentPickerModal.svelte";
```

Change to (EquipmentPickerModal will move to `modals/` in Task 5 — we leave it pointing at the future home and the build will be briefly broken until Task 5; instead, temporarily point at the current root location):

```svelte
import EquipmentPickerModal from "$lib/components/EquipmentPickerModal.svelte";
```

- [ ] **Step 4: Grep for any missed references**

Run: `grep -rn '\$lib/components/\(Inspector\|UnitOpNode\|SwimLaneNode\|ProcessStartNode\|ProcessStartInspector\|TimeAxis\)\.svelte' frontend/src/`
Expected: no output.

- [ ] **Step 5: Run `npm run check`**

Run: `cd frontend && npm run check`
Expected: 0 errors, 0 warnings (or same baseline as before).

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): move protocol-editor components into protocol/ (TD-0080)"
```

---

## Task 2: Extend `run/` with RoleWizard

**Files:**
- Move: `frontend/src/lib/components/RoleWizard.svelte` → `frontend/src/lib/components/run/RoleWizard.svelte`
- Modify: `frontend/src/routes/runs/[id]/+page.svelte:6`
- Modify: `frontend/src/lib/components/run/RunEditMode.svelte:2`

- [ ] **Step 1: Move file**

```bash
cd frontend/src/lib/components
git mv RoleWizard.svelte run/RoleWizard.svelte
```

- [ ] **Step 2: Update imports**

In `frontend/src/routes/runs/[id]/+page.svelte` line 6, replace:

```svelte
import RoleWizard from "$lib/components/RoleWizard.svelte";
```

with:

```svelte
import RoleWizard from "$lib/components/run/RoleWizard.svelte";
```

In `frontend/src/lib/components/run/RunEditMode.svelte` line 2, make the same replacement.

- [ ] **Step 3: Update relative imports inside the moved `RoleWizard.svelte`**

`frontend/src/lib/components/run/RoleWizard.svelte` currently has (lines 8, 10, 11):

```svelte
import BarcodeScanner from "./BarcodeScanner.svelte";
import ImageAnalysisDialog from "./ImageAnalysisDialog.svelte";
import ImageGallery from "./ImageGallery.svelte";
```

Change to (these files still live at root; they move in later tasks, but we use absolute paths from the start — point them at their CURRENT location for now):

```svelte
import BarcodeScanner from "$lib/components/BarcodeScanner.svelte";
import ImageAnalysisDialog from "$lib/components/ImageAnalysisDialog.svelte";
import ImageGallery from "$lib/components/ImageGallery.svelte";
```

- [ ] **Step 4: Verify**

Run: `grep -rn '\$lib/components/RoleWizard\.svelte' frontend/src/`
Expected: no output.

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): move RoleWizard into run/ (TD-0080)"
```

---

## Task 3: Extend `settings/` with AiSettingsTab

**Files:**
- Move: `frontend/src/lib/components/AiSettingsTab.svelte` → `frontend/src/lib/components/settings/AiSettingsTab.svelte`
- Modify: `frontend/src/routes/settings/+page.svelte:20`

- [ ] **Step 1: Move file**

```bash
git mv frontend/src/lib/components/AiSettingsTab.svelte frontend/src/lib/components/settings/AiSettingsTab.svelte
```

- [ ] **Step 2: Update import**

In `frontend/src/routes/settings/+page.svelte` line 20, replace:

```svelte
import AiSettingsTab from '$lib/components/AiSettingsTab.svelte';
```

with:

```svelte
import AiSettingsTab from '$lib/components/settings/AiSettingsTab.svelte';
```

- [ ] **Step 3: Verify**

Run: `grep -rn "components/AiSettingsTab" frontend/src/`
Expected: only the updated line in `settings/+page.svelte` and the new file path.

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): move AiSettingsTab into settings/ (TD-0080)"
```

---

## Task 4: Create `field-mode/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/field-mode/`
- Move: `FieldModeHeader.svelte`, `FieldModeLockScreen.svelte`, `FieldModeRoleWizard.svelte` into `field-mode/`
- Modify: `frontend/src/routes/field/+page.svelte` lines 23, 24, 25

- [ ] **Step 1: Move files**

```bash
mkdir -p frontend/src/lib/components/field-mode
cd frontend/src/lib/components
git mv FieldModeHeader.svelte field-mode/FieldModeHeader.svelte
git mv FieldModeLockScreen.svelte field-mode/FieldModeLockScreen.svelte
git mv FieldModeRoleWizard.svelte field-mode/FieldModeRoleWizard.svelte
```

- [ ] **Step 2: Update absolute imports in `routes/field/+page.svelte` (lines 23–25)**

Replace:

```svelte
import FieldModeHeader from '$lib/components/FieldModeHeader.svelte';
import FieldModeRoleWizard from '$lib/components/FieldModeRoleWizard.svelte';
import FieldModeLockScreen from '$lib/components/FieldModeLockScreen.svelte';
```

with:

```svelte
import FieldModeHeader from '$lib/components/field-mode/FieldModeHeader.svelte';
import FieldModeRoleWizard from '$lib/components/field-mode/FieldModeRoleWizard.svelte';
import FieldModeLockScreen from '$lib/components/field-mode/FieldModeLockScreen.svelte';
```

- [ ] **Step 3: Update the relative import inside moved `FieldModeRoleWizard.svelte`**

`frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte` line 2:

```svelte
import BarcodeScanner from './BarcodeScanner.svelte';
```

Change to (still at root until Task 6):

```svelte
import BarcodeScanner from '$lib/components/BarcodeScanner.svelte';
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create field-mode/ bucket (TD-0080)"
```

---

## Task 5: Create `modals/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/modals/`
- Move: `CreateUnitOpModal`, `EquipmentPickerModal`, `ProtocolImportModal`, `TemplateConvertModal`, `BatchRecordImportModal`, `ImageAnalysisDialog`, `DocumentUploadDialog` (all `.svelte`) into `modals/`
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte:62` (CreateUnitOpModal)
- Modify: `frontend/src/routes/projects/[id]/+page.svelte:24, 26` (ProtocolImportModal, BatchRecordImportModal)
- Modify: `frontend/src/lib/components/project/SettingsTab.svelte:9` (TemplateConvertModal)
- Modify: `frontend/src/lib/components/settings/TemplatesTab.svelte:14` (TemplateConvertModal)
- Modify: `frontend/src/routes/library/+page.svelte:16` (DocumentUploadDialog)
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte` (EquipmentPickerModal — updated in Task 1)
- Modify: `frontend/src/lib/components/run/RoleWizard.svelte` (ImageAnalysisDialog — updated in Task 2)

- [ ] **Step 1: Move files**

```bash
mkdir -p frontend/src/lib/components/modals
cd frontend/src/lib/components
git mv CreateUnitOpModal.svelte modals/CreateUnitOpModal.svelte
git mv EquipmentPickerModal.svelte modals/EquipmentPickerModal.svelte
git mv ProtocolImportModal.svelte modals/ProtocolImportModal.svelte
git mv TemplateConvertModal.svelte modals/TemplateConvertModal.svelte
git mv BatchRecordImportModal.svelte modals/BatchRecordImportModal.svelte
git mv ImageAnalysisDialog.svelte modals/ImageAnalysisDialog.svelte
git mv DocumentUploadDialog.svelte modals/DocumentUploadDialog.svelte
```

- [ ] **Step 2: Update all imports**

Rewrite each of these imports across the tree. Use the repo-wide `grep` output to find and replace each site exactly once.

| Find | Replace with |
|------|--------------|
| `$lib/components/CreateUnitOpModal.svelte` | `$lib/components/modals/CreateUnitOpModal.svelte` |
| `$lib/components/EquipmentPickerModal.svelte` | `$lib/components/modals/EquipmentPickerModal.svelte` |
| `$lib/components/ProtocolImportModal.svelte` | `$lib/components/modals/ProtocolImportModal.svelte` |
| `$lib/components/TemplateConvertModal.svelte` | `$lib/components/modals/TemplateConvertModal.svelte` |
| `$lib/components/BatchRecordImportModal.svelte` | `$lib/components/modals/BatchRecordImportModal.svelte` |
| `$lib/components/ImageAnalysisDialog.svelte` | `$lib/components/modals/ImageAnalysisDialog.svelte` |
| `$lib/components/DocumentUploadDialog.svelte` | `$lib/components/modals/DocumentUploadDialog.svelte` |

One-shot shell command from `frontend/`:

```bash
cd frontend
for name in CreateUnitOpModal EquipmentPickerModal ProtocolImportModal TemplateConvertModal BatchRecordImportModal ImageAnalysisDialog DocumentUploadDialog; do
  grep -rl "\$lib/components/${name}\.svelte" src/ | xargs sed -i "s|\$lib/components/${name}\.svelte|\$lib/components/modals/${name}.svelte|g"
done
```

- [ ] **Step 3: Check for relative imports inside moved modal files**

Run:

```bash
grep -nE "from ['\"]\\./[A-Z]" frontend/src/lib/components/modals/*.svelte
```

Expected: no output (BatchRecordImportModal has an import from `$lib/components/ConfidenceBadge.svelte` which is absolute and will be remapped in Task 10; everything else internal to modals/ has no cross-component relative imports).

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create modals/ bucket (TD-0080)"
```

---

## Task 6: Create `media/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/media/`
- Move: `BarcodeScanner.svelte`, `BarcodeScanner.test.ts`, `barcodeScannerUtils.ts`, `ImageGallery.svelte`, `PdfPreviewDrawer.svelte` → `media/`
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte` (PdfPreviewDrawer import at line 64)
- Modify: `frontend/src/lib/components/field-mode/FieldModeRoleWizard.svelte` (BarcodeScanner — updated in Task 4)
- Modify: `frontend/src/lib/components/run/RoleWizard.svelte` (BarcodeScanner, ImageGallery — updated in Task 2)

- [ ] **Step 1: Move files**

```bash
mkdir -p frontend/src/lib/components/media
cd frontend/src/lib/components
git mv BarcodeScanner.svelte media/BarcodeScanner.svelte
git mv BarcodeScanner.test.ts media/BarcodeScanner.test.ts
git mv barcodeScannerUtils.ts media/barcodeScannerUtils.ts
git mv ImageGallery.svelte media/ImageGallery.svelte
git mv PdfPreviewDrawer.svelte media/PdfPreviewDrawer.svelte
```

- [ ] **Step 2: Update absolute imports**

```bash
cd frontend
for name in BarcodeScanner ImageGallery PdfPreviewDrawer; do
  grep -rl "\$lib/components/${name}\.svelte" src/ | xargs sed -i "s|\$lib/components/${name}\.svelte|\$lib/components/media/${name}.svelte|g"
done
```

- [ ] **Step 3: Update the relative import from `BarcodeScanner.svelte` and its test to `barcodeScannerUtils`**

Already correct (both source and util moved together into `media/`, so `./barcodeScannerUtils` still resolves). Verify:

```bash
grep -n "barcodeScannerUtils" frontend/src/lib/components/media/
```

Expected: the existing `./barcodeScannerUtils` lines in `BarcodeScanner.svelte:7` and `BarcodeScanner.test.ts:37` — no change required.

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run check && npm run test -- --run src/lib/components/media/BarcodeScanner.test.ts`
Expected: check passes, BarcodeScanner test suite passes.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create media/ bucket (TD-0080)"
```

---

## Task 7: Create `analytics/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/analytics/`
- Move: `CompletionChart.svelte`, `AuditTimeline.svelte`, `VersionHistoryDrawer.svelte` → `analytics/`
- Modify: `frontend/src/routes/+page.svelte:8` (CompletionChart)
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte:63` (VersionHistoryDrawer)
- Modify: `frontend/src/lib/components/project/ActivityTab.svelte:3, 8` (AuditTimeline — both the default import and the type import)
- Modify: `frontend/src/lib/components/run/RunHistory.svelte:3, 4` (AuditTimeline default + type import)

- [ ] **Step 1: Move files**

```bash
cd frontend/src/lib/components
mkdir -p analytics
git mv CompletionChart.svelte analytics/CompletionChart.svelte
git mv AuditTimeline.svelte analytics/AuditTimeline.svelte
git mv VersionHistoryDrawer.svelte analytics/VersionHistoryDrawer.svelte
```

- [ ] **Step 2: Update absolute imports**

```bash
cd frontend
for name in CompletionChart AuditTimeline VersionHistoryDrawer; do
  grep -rl "\$lib/components/${name}\.svelte" src/ | xargs sed -i "s|\$lib/components/${name}\.svelte|\$lib/components/analytics/${name}.svelte|g"
done
```

This catches both the default imports and the `type { ... } from "$lib/components/AuditTimeline.svelte"` lines.

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create analytics/ bucket (TD-0080)"
```

---

## Task 8: Create `ai/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/ai/`
- Move: `ChatPanel.svelte`, `ChatSkillButtons.svelte` → `ai/`
- Modify: `frontend/src/routes/+layout.svelte:17` (ChatPanel)

- [ ] **Step 1: Move files**

```bash
cd frontend/src/lib/components
mkdir -p ai
git mv ChatPanel.svelte ai/ChatPanel.svelte
git mv ChatSkillButtons.svelte ai/ChatSkillButtons.svelte
```

- [ ] **Step 2: Update absolute imports**

```bash
cd frontend
sed -i 's|\$lib/components/ChatPanel\.svelte|\$lib/components/ai/ChatPanel.svelte|g' src/routes/+layout.svelte
```

- [ ] **Step 3: Update the relative import inside `ChatPanel.svelte`**

`frontend/src/lib/components/ai/ChatPanel.svelte` line 5:

```svelte
import ChatSkillButtons from "$lib/components/ChatSkillButtons.svelte";
```

Change to:

```svelte
import ChatSkillButtons from "$lib/components/ai/ChatSkillButtons.svelte";
```

- [ ] **Step 4: Verify**

Run: `cd frontend && grep -rn 'ChatPanel\|ChatSkillButtons' src/ | grep -v 'components/ai/'`
Expected: no stale references.

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create ai/ bucket (TD-0080)"
```

---

## Task 9: Create `layout/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/layout/`
- Move: `MobileNav.svelte`, `UserMenu.svelte`, `NotificationBell.svelte`, `Logo.svelte`, `ProjectsDropdown.svelte` → `layout/`
- Modify: `frontend/src/routes/+layout.svelte` lines 10–14, and line 22 (the secondary `Logo` import for the no-user layout)
- Modify: `frontend/src/routes/login/+page.svelte:11` (Logo)
- Modify: `frontend/src/lib/components/layout/MobileNav.svelte:4` (was `$lib/components/Logo.svelte`)

- [ ] **Step 1: Move files**

```bash
cd frontend/src/lib/components
mkdir -p layout
git mv MobileNav.svelte layout/MobileNav.svelte
git mv UserMenu.svelte layout/UserMenu.svelte
git mv NotificationBell.svelte layout/NotificationBell.svelte
git mv Logo.svelte layout/Logo.svelte
git mv ProjectsDropdown.svelte layout/ProjectsDropdown.svelte
```

- [ ] **Step 2: Update absolute imports**

```bash
cd frontend
for name in MobileNav UserMenu NotificationBell Logo ProjectsDropdown; do
  grep -rl "\$lib/components/${name}\.svelte" src/ | xargs sed -i "s|\$lib/components/${name}\.svelte|\$lib/components/layout/${name}.svelte|g"
done
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run check`
Expected: 0 new errors.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create layout/ bucket (TD-0080)"
```

---

## Task 10: Create `shared/` bucket

**Files:**
- Create dir: `frontend/src/lib/components/shared/`
- Move: `ConnectivityBanner.svelte`, `ExpiryWarningBanner.svelte`, `ConfidenceBadge.svelte`, `MarkdownRenderer.svelte`, `ResponsiveTable.svelte`, `GoOfflineDialog.svelte` → `shared/`
- Modify: `frontend/src/routes/+layout.svelte:13` (ConnectivityBanner — already touched in Task 9)
- Modify: `frontend/src/routes/field/+page.svelte:26` (ExpiryWarningBanner)
- Modify: `frontend/src/lib/components/modals/BatchRecordImportModal.svelte:5` (ConfidenceBadge)
- Modify: `frontend/src/routes/library/[id]/+page.svelte:34` (MarkdownRenderer)
- Modify: `frontend/src/routes/runs/[id]/+page.svelte:7` (GoOfflineDialog)

- [ ] **Step 1: Move files**

```bash
cd frontend/src/lib/components
mkdir -p shared
git mv ConnectivityBanner.svelte shared/ConnectivityBanner.svelte
git mv ExpiryWarningBanner.svelte shared/ExpiryWarningBanner.svelte
git mv ConfidenceBadge.svelte shared/ConfidenceBadge.svelte
git mv MarkdownRenderer.svelte shared/MarkdownRenderer.svelte
git mv ResponsiveTable.svelte shared/ResponsiveTable.svelte
git mv GoOfflineDialog.svelte shared/GoOfflineDialog.svelte
```

- [ ] **Step 2: Update absolute imports**

```bash
cd frontend
for name in ConnectivityBanner ExpiryWarningBanner ConfidenceBadge MarkdownRenderer ResponsiveTable GoOfflineDialog; do
  grep -rl "\$lib/components/${name}\.svelte" src/ | xargs sed -i "s|\$lib/components/${name}\.svelte|\$lib/components/shared/${name}.svelte|g"
done
```

- [ ] **Step 3: Confirm zero root-level `.svelte` files remain**

Run: `ls frontend/src/lib/components/*.svelte 2>/dev/null`
Expected: no output (all `.svelte` files have been moved into subdirectories).

Run: `ls frontend/src/lib/components/*.ts 2>/dev/null`
Expected: no output.

- [ ] **Step 4: Verify build + all tests**

Run: `cd frontend && npm run check && npm run test -- --run`
Expected: check passes, all Vitest tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(components): create shared/ bucket (TD-0080)"
```

---

## Task 11: Add component placement guidelines to `.claude/rules/conventions.md`

**Files:**
- Modify: `.claude/rules/conventions.md` (append a subsection under "## DRY")

- [ ] **Step 1: Add the new subsection**

Immediately after the existing "## DRY" section (which ends with the `lib/components/` paragraph), add:

```markdown
### Component placement

New Svelte components under `frontend/src/lib/components/` MUST go in a domain subdirectory, not at the root. Choose the most specific existing bucket before creating a new one.

- `ui/` — shadcn-svelte primitives only (buttons, inputs, dialogs, etc.)
- `edra/` — rich-text editor (edra integration)
- `protocol/` — protocol-editor canvas pieces, nodes, inspector, sidebar
- `project/` — project page tabs and project-scoped dialogs
- `run/` — run execution surfaces (edit mode, attachments, history, role wizard)
- `settings/` — settings page tabs and their modals
- `field-mode/` — tablet/field-mode flows
- `modals/` — heavy dialogs wrapping a form, import, or picker flow (contrast with lightweight confirmation dialogs, which go in `shared/`)
- `media/` — camera, image, PDF, barcode scanning
- `analytics/` — charts, audit trails, version history
- `ai/` — chat and agent UX
- `layout/` — global app chrome (nav, user menu, logo, banners that live in `+layout.svelte`)
- `shared/` — small cross-cutting presentational pieces (badges, small banners, markdown rendering, generic tables)

If a component is used by only one domain's routes, prefer that domain's bucket over `modals/` or `shared/`.
```

- [ ] **Step 2: Verify the file parses as markdown (no syntax issues)**

Run: `grep -c '^## ' .claude/rules/conventions.md`
Expected: matches the number of `##` headings before (+0 since we added an `###`, not `##`).

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/conventions.md
git commit -m "docs(conventions): document component placement guidelines (TD-0080)"
```

---

## Task 12: Final sanity pass

- [ ] **Step 1: Confirm no stale root-level component imports remain anywhere**

Run:

```bash
cd /home/wesuuu/Code/trellisbio/.claude/worktrees/td-0080-components-reorg
grep -rnE '\$lib/components/[A-Z][A-Za-z]+\.svelte' frontend/src/ | grep -vE '\$lib/components/(ui|edra|protocol|project|run|settings|field-mode|modals|media|analytics|ai|layout|shared)/'
```

Expected: no output.

- [ ] **Step 2: Build, check, and test**

Run: `cd frontend && npm run check && npm run test -- --run && npm run build`
Expected: all green.

- [ ] **Step 3: Browser smoke-test (handled by the qa-verify agent per /implement-task)**

Pages to exercise:
- `/` — main dashboard (CompletionChart, layout nav, ChatPanel)
- `/projects/[id]` — ProtocolImportModal, BatchRecordImportModal
- `/protocols/[id]` — full protocol editor (Inspector, nodes, TimeAxis, VersionHistoryDrawer, PdfPreviewDrawer, CreateUnitOpModal)
- `/runs/[id]` — RoleWizard, GoOfflineDialog
- `/field` — FieldMode flows, BarcodeScanner inside FieldModeRoleWizard
- `/library` — DocumentUploadDialog, MarkdownRenderer
- `/settings` — AiSettingsTab, TemplateConvertModal

No commit; the qa-verify agent will fix any regressions in-place and commit their fix.

---

## Self-review notes

- **Spec coverage:** Every file in the spec's mapping table is moved in exactly one task. The conventions rule is added in Task 11.
- **Placeholders:** none — every import rewrite shows the exact `find` / `replace` strings.
- **Type consistency:** no type signatures or renames — pure file moves.
- **Order hazard:** tasks are ordered so that cross-bucket relative imports always resolve. When a moved file references a file that hasn't moved yet, the plan rewrites the relative import to an absolute path pointing at the *current* (root) location; that import gets rewritten again when the target file moves in a later task via the bucket's `sed` loop.
