# TD-0073 TemplateConvertModal Dialog Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-rolled full-viewport overlay in `TemplateConvertModal.svelte` with the shared `Dialog` primitive while preserving all current behavior (open/close flow, unsaved-changes confirm, nested save dialog stacking, resizable split-pane, and the three-step upload/processing/review state machine).

**Architecture:** One file changes. The outer `{#if open}<div class="fixed inset-0 z-50 …">…</div>{/if}` at `TemplateConvertModal.svelte:452-823` becomes `<Dialog.Root open={open}><Dialog.Content class="w-screen h-screen …" showCloseButton={false} onEscapeKeydown={…} interactOutsideBehavior="ignore">…</Dialog.Content></Dialog.Root>`. Inner content is preserved verbatim except for wrapping the title `<h2>` in `<Dialog.Title>` and adding a visually-hidden `<Dialog.Description>` for bits-ui a11y compliance.

**Tech Stack:** Svelte 5 (runes), @xyflow/svelte unrelated, shadcn-svelte `Dialog` (`frontend/src/lib/components/ui/dialog/`) built on bits-ui, Tailwind CSS 4.

**Spec:** `docs/superpowers/specs/2026-04-17-td-0073-template-convert-modal-dialog-migration-design.md`

**Worktree:** `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0073-template-convert-modal` on branch `td/td-0073-template-convert-modal`. All commands below assume this directory is the working directory.

---

## Pre-flight

### Task 0: Confirm baseline

**Files:**
- Read: `frontend/src/lib/components/TemplateConvertModal.svelte` (lines 452-834)
- Read: `frontend/src/lib/components/ui/dialog/dialog-content.svelte`
- Read: `frontend/src/lib/components/FieldModeLockScreen.svelte` (reference pattern)
- Read: `frontend/src/lib/components/settings/TemplatesTab.svelte:285-288`
- Read: `frontend/src/lib/components/project/SettingsTab.svelte:522-527`

- [ ] **Step 1: Verify working directory**

Run: `pwd && git branch --show-current`
Expected: `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0073-template-convert-modal` and `td/td-0073-template-convert-modal`.

- [ ] **Step 2: Record baseline check errors**

Run: `cd frontend && npm run check 2>&1 | tail -2`
Expected: `COMPLETED 8598 FILES 31 ERRORS 28 WARNINGS 19 FILES_WITH_PROBLEMS`. The 31 errors are all in `edra/` (unrelated rich-text editor). Write down the exact error count — Task 7 verifies it did not increase.

- [ ] **Step 3: Confirm Dialog primitive is already imported**

Run: `grep -n "import \* as Dialog" frontend/src/lib/components/TemplateConvertModal.svelte`
Expected: line 7 — `import * as Dialog from '$lib/components/ui/dialog';`. No new imports needed.

---

## Migration

### Task 1: Wrap shell in Dialog.Root / Dialog.Content

**Files:**
- Modify: `frontend/src/lib/components/TemplateConvertModal.svelte:452-823`

This is a structural replacement: swap the outer `{#if open}<div>…</div>{/if}` for `<Dialog.Root><Dialog.Content>…</Dialog.Content></Dialog.Root>`. Inner content is preserved verbatim in this task. Title/Description wrapping and nested-dialog verification happen in Task 2 and Task 3.

- [ ] **Step 1: Replace the opening wrapper**

Change line 452 from:

```svelte
{#if open}
<div class="fixed inset-0 z-50 flex flex-col bg-background">
```

to:

```svelte
<Dialog.Root open={open}>
    <Dialog.Content
        class="w-screen h-screen max-w-none max-h-none rounded-none border-0 p-0 bg-background flex flex-col overflow-hidden"
        showCloseButton={false}
        onEscapeKeydown={(e) => { e.preventDefault(); handleClose(); }}
        interactOutsideBehavior="ignore"
    >
```

- [ ] **Step 2: Replace the closing wrapper**

Change the end of the template (the `</div>` on line 823 followed by `{/if}` on line 824) from:

```svelte
        {/if}
    </div>
    </div>
</div>
{/if}

<ConfirmDialog
```

to:

```svelte
        {/if}
    </div>
    </div>
    </Dialog.Content>
</Dialog.Root>

<ConfirmDialog
```

Note: the two inner `</div>` closers stay (they close the inner content-wrapper divs at lines 476 and 477). Only the outermost `<div>` and its `{#if open}`/`{/if}` bookends are replaced.

- [ ] **Step 3: Verify structure parses**

Run: `cd frontend && npx svelte-check --threshold error 2>&1 | grep -E "TemplateConvertModal|Error:" | head -20`
Expected: No errors specific to `TemplateConvertModal.svelte`. If errors appear, inspect the diff — the most likely cause is an unbalanced `<div>` / `</div>` pair from Step 2.

### Task 2: Add Dialog.Title and Dialog.Description for a11y

**Files:**
- Modify: `frontend/src/lib/components/TemplateConvertModal.svelte` (header block, currently lines 455-473)

bits-ui logs a warning in dev mode if `Dialog.Content` is missing either a `Dialog.Title` or an `aria-labelledby`, and separately if it is missing a `Dialog.Description` or `aria-describedby`. Fix both.

- [ ] **Step 1: Wrap the h2 in Dialog.Title**

In the header block, change:

```svelte
<h2 class="text-lg font-semibold">Convert Document to Template</h2>
```

to:

```svelte
<Dialog.Title class="text-lg font-semibold">Convert Document to Template</Dialog.Title>
<Dialog.Description class="sr-only">
    Upload a completed document and convert it into a reusable template.
</Dialog.Description>
```

The `Dialog.Title` and `Dialog.Description` primitives are already available on the namespace-imported `* as Dialog` on line 7. `Dialog.Title` renders an `h2` by default and accepts the same `class` prop, preserving the existing `text-lg font-semibold` styling.

- [ ] **Step 2: Verify no duplicate labelling**

Confirm that the `<h2>` does not appear again anywhere in the file (it was a single instance). Running:

Run: `grep -n "Convert Document to Template" frontend/src/lib/components/TemplateConvertModal.svelte`
Expected: exactly one match, inside `<Dialog.Title>`.

### Task 3: Spot-check preserved inner structure

**Files:**
- Read: `frontend/src/lib/components/TemplateConvertModal.svelte`

This is a read-only verification task. No edits.

- [ ] **Step 1: Confirm unchanged inner elements**

Run each of the following; each must still match:

```bash
grep -n 'step === '\''upload'\''' frontend/src/lib/components/TemplateConvertModal.svelte
grep -n 'step === '\''processing'\''' frontend/src/lib/components/TemplateConvertModal.svelte
grep -n 'step === '\''review'\''' frontend/src/lib/components/TemplateConvertModal.svelte
grep -n 'cursor-col-resize' frontend/src/lib/components/TemplateConvertModal.svelte
grep -n 'bind:open={showSaveDialog}' frontend/src/lib/components/TemplateConvertModal.svelte
grep -n 'bind:open={discardConfirmOpen}' frontend/src/lib/components/TemplateConvertModal.svelte
```

All six greps should return one or more lines — indicating the step state machine, resize handle, nested save dialog, and discard confirm dialog are all still wired up.

- [ ] **Step 2: Confirm removal of hand-rolled overlay**

Run: `grep -n "fixed inset-0 z-50" frontend/src/lib/components/TemplateConvertModal.svelte`
Expected: **no matches**. (Earlier the match was on line 453.)

### Task 4: Verify callsites still work (no prop contract change)

**Files:**
- Read: `frontend/src/lib/components/settings/TemplatesTab.svelte:285-288`
- Read: `frontend/src/lib/components/project/SettingsTab.svelte:522-527`

Read-only. The `open` prop remains `$bindable(false)`, `projectId` is optional, `onSuccess` is optional. No callsite changes.

- [ ] **Step 1: Confirm prop signature unchanged**

Run: `grep -n "let { open = " frontend/src/lib/components/TemplateConvertModal.svelte`
Expected: line 40 — `let { open = $bindable(false), projectId, onSuccess }: Props = $props();`.

- [ ] **Step 2: Confirm callsites use `bind:open` unchanged**

Run: `grep -n "<TemplateConvertModal" frontend/src/lib/components/**/*.svelte -A 2`
Expected: Both callsites use `bind:open={showConvert}`. No modifications.

---

## Verification

### Task 5: Static type + lint verification

**Files:** none modified in this task.

- [ ] **Step 1: Run svelte-check**

Run: `cd frontend && npm run check 2>&1 | tail -2`
Expected: `COMPLETED 8598 FILES 31 ERRORS …` — error count must be exactly 31 (unchanged from baseline in Task 0 Step 2). If the count has increased, filter for the new errors:

Run: `cd frontend && npm run check 2>&1 | grep -E "ERROR \"src/lib/components/TemplateConvertModal"`
Expected: no output.

- [ ] **Step 2: Run production build**

Run: `cd frontend && npm run build 2>&1 | tail -10`
Expected: build succeeds with `✓ built` — no errors. Warnings about chunk size are OK.

### Task 6: Commit the migration

- [ ] **Step 1: Review diff**

Run: `git diff frontend/src/lib/components/TemplateConvertModal.svelte`
Expected: Changes limited to:
1. Opening wrapper replacement (one `{#if open}<div class="fixed inset-0 z-50 ...">` → `<Dialog.Root><Dialog.Content class="w-screen h-screen ..." …>`).
2. Closing wrapper replacement (`</div>{/if}` → `</Dialog.Content></Dialog.Root>`).
3. `<h2>` → `<Dialog.Title>` with an added `<Dialog.Description class="sr-only">`.

No other changes. If other lines appear in the diff (whitespace reformatting, unrelated edits), revert them before committing.

- [ ] **Step 2: Stage and commit**

Run:
```bash
git add frontend/src/lib/components/TemplateConvertModal.svelte
git commit -m "refactor(frontend): migrate TemplateConvertModal shell to Dialog [TD-0073]

Replaces the hand-rolled fixed-inset overlay with Dialog.Root/Dialog.Content
using full-viewport class overrides. Escape now routes through handleClose
so the unsaved-changes confirm fires on keyboard dismissal. Finishes
TD-0068's migration of the last hand-rolled modal."
```

- [ ] **Step 3: Verify commit**

Run: `git log -1 --stat`
Expected: one commit, one file changed, roughly +10/−5 line count.

### Task 7: Commit spec and plan

The spec and plan docs were written before implementation but not yet
committed. Commit them now so the branch carries its own design history.

- [ ] **Step 1: Stage docs**

Run:
```bash
git add docs/superpowers/specs/2026-04-17-td-0073-template-convert-modal-dialog-migration-design.md
git add docs/superpowers/plans/2026-04-17-td-0073-template-convert-modal-dialog-migration.md
```

- [ ] **Step 2: Commit**

Run:
```bash
git commit -m "docs(spec,plan): TD-0073 TemplateConvertModal Dialog migration"
```

### Task 8: Browser QA (qa-verify agent)

**Files:** none modified in this task.

- [ ] **Step 1: Start dev servers on worktree ports**

Worktree port convention (see `.claude/rules/conventions.md`): backend :8010, frontend :5183, `VITE_API_PORT=8010`.

Run backend:
```bash
cd backend
source .venv/bin/activate 2>/dev/null || (python -m venv .venv && source .venv/bin/activate && pip install poetry && poetry install --no-root)
uvicorn app.main:app --reload --port 8010
```

Run frontend (separate shell, also in the worktree):
```bash
cd frontend
VITE_API_PORT=8010 npm run dev -- --port 5183
```

Verify both ports respond: `curl -s http://localhost:8010/health && curl -s http://localhost:5183/ >/dev/null && echo up`.

- [ ] **Step 2: Launch qa-verify agent**

Brief the agent with:

- **Login:** any email on localhost:5183 with password `postgres` works in dev (any password accepted).
- **Feature under test:** the Convert Document to Template modal (full-viewport editor with three steps: upload → processing → review).
- **Entry points:**
  - Settings → Templates tab → "Convert Document" button (callsite 1).
  - Project → Settings tab → Templates section → "Convert Document" button (callsite 2).
- **What to verify:**
  1. **Open / close (no conversion in progress):** X button closes, Cancel button (bottom bar) closes, Escape closes. All three paths close instantly without the discard confirm dialog.
  2. **Open / close (conversion in progress):** Upload a `.docx`, wait for processing to start, then attempt each close path (X, Cancel, Escape). Each must trigger the "Discard conversion?" confirm dialog. Clicking "Discard" closes the shell and resets state; clicking "Cancel" on the confirm keeps the shell open with the conversion still running.
  3. **Save flow:** Complete a conversion, open Save to Library, fill name, click Save. Shell must close automatically without the discard confirm appearing.
  4. **Nested save dialog stacking:** The "Save Template to Library" dialog must visually render above the shell content and be interactable. Its own Escape-key dismissal and outside-click dismissal must still work (not suppressed by the shell's handlers).
  5. **Focus trap:** While the shell is open, pressing Tab must cycle focus only within the shell — it must not move focus into the underlying Settings page controls.
  6. **Visual parity:** Side-by-side the modal against `git stash` of the change (or a fresh session on `main` in the main workspace at :5173). Header row, chat pane width, resize handle, three preview modes (Original/Rendered/Template), and bottom-bar action buttons must render identically.
  7. **Resize handle:** Drag the vertical divider between preview and chat pane. Width must change smoothly in the 280-700 px range.
  8. **File picker interaction:** On the upload step, click the drop zone. The native OS file picker must open, and after selecting a file (or cancelling) focus must return cleanly to the shell without losing the focus trap.
- **Edge cases to probe:**
  - Click on the dim backdrop area immediately after the shell's zoom-in animation — must not dismiss (overlay is fully covered by `w-screen h-screen` content; if any pixel of the overlay is clickable, the `interactOutsideBehavior="ignore"` setting must still prevent dismissal).
  - Rapid Escape presses during the processing step — must not cause the shell to close without the discard confirm.

Launch:

```
Agent({
  description: "QA TD-0073 TemplateConvertModal shell",
  subagent_type: "qa-verify",
  prompt: "<above briefing>"
})
```

- [ ] **Step 3: Address any FAIL / POLISH findings**

If qa-verify reports failures, fix them in the worktree before proceeding. If the fix is substantial (more than trivial class tweaks), loop back to writing-plans to update this document before continuing.

### Task 9: Present for user sign-off

**Files:** none modified.

- [ ] **Step 1: Summary**

Produce a short summary to the user:
- What was migrated and why (one sentence).
- Confirmation of the eight qa-verify checks.
- File diff stats.
- ClickUp task URL.

- [ ] **Step 2: Wait for explicit approval**

Do not proceed to Task 10 without the user saying "yes", "approved", "ship it", or equivalent. If the user requests changes, fix them and re-run qa-verify.

### Task 10: Close the ClickUp task

- [ ] **Step 1: Post summary comment**

Use `clickup_create_task_comment` on task `86e0ynqkp` with:
- What changed (TemplateConvertModal shell migrated to Dialog primitive).
- Files modified (one file + spec/plan docs).
- Tests (none added — static + browser QA per TD-0068 precedent).
- Link to commit(s) on branch `td/td-0073-template-convert-modal`.

- [ ] **Step 2: Set status to complete**

Use `clickup_update_task` on task `86e0ynqkp` with `status: "complete"`.

- [ ] **Step 3: Offer branch-finishing options**

Invoke `superpowers:finishing-a-development-branch` to decide whether to merge the worktree back to main, open a PR, or clean up.

---

## Rollback plan

If qa-verify finds a blocker that cannot be fixed within the scope of this plan:

```bash
git reset --hard HEAD~1   # undo the implementation commit, keep spec/plan
```

…and update the spec with the discovered constraint before attempting a new approach.

## Open questions

None.
