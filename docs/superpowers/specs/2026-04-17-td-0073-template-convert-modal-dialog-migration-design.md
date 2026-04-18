# TD-0073 — Migrate TemplateConvertModal Main Shell to Shared `Dialog`

## Problem

`frontend/src/lib/components/TemplateConvertModal.svelte:452-823` renders a
hand-rolled full-viewport overlay (`<div class="fixed inset-0 z-50 flex flex-col
bg-background">`). It is the last hand-rolled modal in the codebase — the seven
other overlays plus the nested save dialog in this same file were migrated to
the shared `Dialog` primitive in TD-0068. The shell was deferred because it is
not a centered card: it is a full-screen editor with header, resizable
chat+preview panes, and an unsaved-changes confirmation flow.

Keeping the hand-rolled overlay costs:

- No focus trap. Keyboard users can Tab out of the modal into background
  controls on the underlying Settings page.
- No `role="dialog"` / `aria-modal` / `aria-labelledby`. Screen readers do not
  announce the shell as a dialog.
- No Escape-to-dismiss. Users relying on keyboard must mouse to the X button.
- Inconsistent with the seven other migrated overlays. New contributors will
  reach for `fixed inset-0 z-50` because this file normalizes that pattern.

## Goals

- Replace the hand-rolled overlay with `Dialog.Root` / `Dialog.Content` using
  full-viewport class overrides.
- Preserve all current behavior exactly: the unsaved-changes `ConfirmDialog`
  fires on every close path; the nested save `Dialog` stacks above the shell;
  both callsites (Settings → Templates tab, Project → Settings tab) continue
  to work via `bind:open`.
- Gain focus trap + aria wiring + Escape-to-close (with confirm) for free.
- Zero visual regressions.

## Non-Goals

- Converting to a routed `/templates/convert` page. Rejected during brainstorming —
  larger effort, UX change, requires threading `projectId` through the route.
- Refactoring the inner step machine (`upload` / `processing` / `review`),
  chat refinement, or preview mode logic. Out of scope.
- Changing the nested save dialog (already migrated in TD-0068).
- Changing the `ConfirmDialog` invocation for discard (already a separate
  shared primitive).

## Scope

Single file: `frontend/src/lib/components/TemplateConvertModal.svelte`.

No changes to callsites (`settings/TemplatesTab.svelte`, `project/SettingsTab.svelte`) —
the `open` prop contract is preserved (still `$bindable(false)`).

## Design

### Wrapper structure

Replace lines 452 and 823 (the `{#if open}<div class="fixed inset-0 z-50 flex
flex-col bg-background">…</div>{/if}` wrapper) with a `Dialog.Root` /
`Dialog.Content` pair. All inner content (header, step body, bottom bar, nested
save dialog) is unchanged.

```svelte
<Dialog.Root open={open}>
  <Dialog.Content
    class="w-screen h-screen max-w-none max-h-none rounded-none border-0 p-0 bg-background flex flex-col overflow-hidden"
    showCloseButton={false}
    onEscapeKeydown={(e) => { e.preventDefault(); handleClose(); }}
    interactOutsideBehavior="ignore"
  >
    <!-- existing header, content, bottom bar, nested save dialog -->
  </Dialog.Content>
</Dialog.Root>
```

### Close-path unification

Every dismissal path routes through `handleClose()` so the unsaved-changes
`ConfirmDialog` is guaranteed to fire when a conversion is in progress.

| Path | Mechanism | Behavior |
|---|---|---|
| X button in header | existing `onclick={handleClose}` | unchanged |
| Cancel button in bottom bar | existing `onclick={handleClose}` | unchanged |
| Escape key | `onEscapeKeydown={(e) => { e.preventDefault(); handleClose(); }}` | **new** — previously Escape did nothing |
| Click outside | `interactOutsideBehavior="ignore"` | no-op. Full-viewport shell has no "outside"; explicit ignore guards against portal-sibling clicks |
| Programmatic close after save | `open = false` in `handleSave()` | unchanged — one-way prop drive, bits-ui respects the prop change |
| Programmatic close after discard-confirm | `open = false` in `confirmDiscardConversion()` | unchanged |

### Why one-way `open` (not `onOpenChange` round-trip)

Using `onOpenChange={(v) => { if (!v) handleClose(); }}` would re-invoke
`handleClose()` when the programmatic paths (`handleSave`,
`confirmDiscardConversion`) set `open = false` — introducing re-entry risk and
potentially re-triggering the discard confirm inside the confirm-accepted path.

One-way `open={open}` with explicit handlers is simpler:
- bits-ui does not fire `onOpenChange` for external prop changes.
- Escape is routed manually via `onEscapeKeydown` + `preventDefault` before
  bits-ui's internal close state machine runs.
- Outside-click is suppressed via `interactOutsideBehavior="ignore"`.
- Programmatic closes just mutate `open`.

No re-entry guard flag is required.

### Accessibility

- Wrap the existing `<h2>Convert Document to Template</h2>` in `<Dialog.Title>`
  and keep the same `text-lg font-semibold` classes. This gives bits-ui an
  `aria-labelledby` anchor.
- Add a visually-hidden `<Dialog.Description class="sr-only">Upload a completed
  document and convert it into a reusable template.</Dialog.Description>` next
  to the title. Required by bits-ui's dialog contract (warns in dev without).
- Keep the custom X button's `aria-label="Close"`.

### Z-index / portal stacking

Both the shell and the nested save dialog are now `Dialog.Root` components.
bits-ui portals both to document body; the later-opened save dialog stacks on
top automatically. The manual `z-[60]` was already dropped from the save dialog
in TD-0068. The discard `ConfirmDialog` is also a portal-based primitive and
stacks above the shell.

The shell's Dialog.Overlay will render a dim backdrop under the full-viewport
content. Since the content class uses `w-screen h-screen` with `bg-background`,
the overlay is never visible — it is fully covered. Acceptable.

### Files touched

- `frontend/src/lib/components/TemplateConvertModal.svelte` — template-only
  change. `Dialog` imports already present (used by the nested save dialog at
  line 793).

## Testing

Consistent with TD-0068's precedent — no Svelte 5 component test framework is
registered in this codebase. Standing one up for a one-file refactor is
disproportionate.

**Strategy:**
- **Static verification** — `npm run check` (svelte-check + tsc) must not add
  new errors. 31 pre-existing errors exist in `edra/` (unrelated rich-text
  editor); baseline must be preserved.
- **Build verification** — `npm run build` must succeed.
- **Browser verification (qa-verify)** — primary correctness signal. qa-verify
  agent exercises the migrated shell in the running dev server and confirms:
  - X button closes the shell when no conversion is in progress.
  - X button triggers discard confirm when a conversion is in progress;
    confirm → closes, cancel → stays open.
  - Cancel button in bottom bar behaves identically to X button.
  - Escape key triggers the same paths as X button.
  - Save → shell closes automatically (existing behavior); no stray confirm.
  - Nested save dialog stacks above the shell and its own Escape/outside-click
    dismissal works (not suppressed).
  - Focus trap: Tab from inside the shell cycles within the shell, does not
    escape to the Settings page background.
  - Visual parity with `main`: header, chat pane width, resize handle,
    preview iframe all render identically at both callsites.

## Risks

- **`Dialog.Overlay` peeking:** If the full-viewport `Dialog.Content` for any
  reason does not fully cover the overlay (e.g., future CSS change reduces
  content size), the overlay's dim fill would show. Low risk given `w-screen
  h-screen`. Caught by qa-verify visual check.
- **Portal siblings:** Browser extensions or dev tools may portal nodes at
  document body. `interactOutsideBehavior="ignore"` prevents accidental
  dismissal from those clicks.
- **Focus trap vs. file picker:** The upload step triggers
  `document.getElementById('convert-file-input')?.click()` to open the system
  file picker. The native file dialog takes focus out of the browser, then
  returns. bits-ui's focus trap re-captures on return. qa-verify to exercise
  this flow.
- **Animation timing:** bits-ui's `data-[state=open]:zoom-in-95 fade-in-0`
  animations apply to `Dialog.Content` by default. Override is already in the
  content class via `p-0`. The zoom-in animation on a full-viewport surface
  may look subtly different from the current instant-open. Acceptable — same
  animation as `FieldModeLockScreen`.

## Follow-ups

None. TD-0068's `Non-Goals` note and `Follow-ups` section are resolved by this
task.
