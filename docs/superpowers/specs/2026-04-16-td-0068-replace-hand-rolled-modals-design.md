# TD-0068 — Replace Hand-Rolled Modals with Shared `Dialog`

## Problem

Seven components use hand-rolled `fixed inset-0 z-50` overlay divs instead of the
shared `Dialog` primitive in `$lib/components/ui/dialog`. Each hand-rolled overlay
is missing focus trapping, escape-to-close, and aria attributes. On a tablet-first
LES used in cleanrooms, this is both an accessibility risk and an inconsistency
risk: screen-reader users and keyboard-only users get a different experience per
screen.

## Goals

- Every target uses the shared `Dialog` component where the primitive's focus
  trap and aria wiring are a net win.
- Dismissal behavior is preserved exactly where it should be preserved (true
  modals close on Escape / outside click) and explicitly locked where the
  product requires it (lock screen, expiry warning).
- Visual appearance matches the current design.
- No regressions in open/close behavior of any migrated component.

## Non-Goals

- Migrating the `TemplateConvertModal` main shell (line 444). It's a full-screen
  editor with header, resizable chat+preview panes, and its own unsaved-changes
  confirm flow — not a centered card. Wrapping it in `Dialog.Content` fights the
  primitive. Logged as a separate task.
- Touching `field/+page.svelte` (superseded TD-0067a scope). Out of scope for
  this task unless a follow-up task explicitly requests it.
- Changing modal content or behavior — this is a refactor only.

## Scope

Three categories across 7 targets (plus one deferred shell).

### Category A — True centered-card modals (5 targets)

Clean fit with `Dialog`. Migrate fully; use default Escape + outside-interaction
dismissal.

1. `frontend/src/lib/components/RoleWizard.svelte` (line 810) — `showTagSelector`
   overlay opened after image capture.
2. `frontend/src/lib/components/FieldModeRoleWizard.svelte` (line 600) —
   `showTagSelector` overlay, same pattern as above.
3. `frontend/src/lib/components/run/RunDocuments.svelte` (line 112) — document
   viewer modal. Currently has a clickable backdrop overlay; `Dialog`'s default
   `onInteractOutside` → close reproduces that behavior.
4. `frontend/src/lib/components/settings/TemplateUploadModal.svelte` (line 137)
   — two-step upload/preview. Today uses an `onClose` callback from
   `TemplatesTab.svelte`. Convert to the shadcn convention `bind:open` at the
   callsite; drop the `onClose` prop.
5. `frontend/src/lib/components/TemplateConvertModal.svelte` (line 786) — the
   *nested* save-to-library dialog. The `z-[60]` override stacks it above the
   Convert shell; bits-ui's portal handles stacking automatically so the manual
   `z-[60]` can be dropped.

### Category B — Forced, non-dismissible full-viewport UI (2 targets)

Migrate to `Dialog` with dismissal explicitly disabled. We gain focus trap and
aria without allowing Escape-to-close (which would be a product regression).

6. `frontend/src/lib/components/FieldModeLockScreen.svelte` (line 40) — session
   lock. Escape-to-close would defeat the lock. `open` is always true while the
   component is mounted; parent removes the component on successful unlock via
   the existing `onUnlock` callback.
7. `frontend/src/lib/components/ExpiryWarningBanner.svelte` (line 25) — critical
   branch only (the amber / red inline banners on lines 45–58 are not modals
   and stay untouched). Dismissal happens via the "I Understand" button setting
   `dismissed = true`; `open` is derived as
   `warningLevel === 'critical' && !dismissed`.

### Deferred (1 target) — logged as a separate task

8. `frontend/src/lib/components/TemplateConvertModal.svelte` (line 444, main
   shell). Not migrated in TD-0068. Logged via `/add_task`.

## Design

### Category A — pattern

```svelte
<Dialog.Root bind:open={showX}>
  <Dialog.Content class="<size override>">
    <!-- existing card content, minus the outer overlay div -->
    <!-- minus any custom close button (Dialog.Content ships an X) -->
  </Dialog.Content>
</Dialog.Root>
```

Per-file notes:

- **RoleWizard / FieldModeRoleWizard:** `bind:open={showTagSelector}`. Default
  `sm:max-w-lg` is sufficient for the tag selector.
- **RunDocuments:** `bind:open={showModal}`. Size override preserves today's
  document viewer width (match the existing `max-w-*` from the modal card).
- **TemplateUploadModal:** Change component API. Replace `onClose: () => void`
  with `open: boolean` (bindable). Callsite in `TemplatesTab.svelte` switches
  from `{#if showUpload}<TemplateUploadModal onClose={…} …/>{/if}` to
  `<TemplateUploadModal bind:open={showUpload} …/>`. Keep `onSuccess` callback
  unchanged (used to refresh the list). Size override preserves the current
  `max-w-5xl max-h-[85vh]`.
- **TemplateConvertModal save dialog:** `bind:open={showSaveDialog}`. Default
  width fits. Drop the manual `z-[60]` — portal stacking handles it.

### Category B — pattern

```svelte
<Dialog.Root open={shouldShow}>
  <Dialog.Content
    class="w-screen h-screen max-w-none max-h-none rounded-none border-0 p-0 …"
    showCloseButton={false}
    escapeKeydownBehavior="ignore"
    interactOutsideBehavior="ignore"
  >
    <!-- existing content -->
  </Dialog.Content>
</Dialog.Root>
```

With `escapeKeydownBehavior="ignore"` + `interactOutsideBehavior="ignore"`,
`bits-ui` suppresses the auto-dismiss paths entirely, so `onOpenChange` never
fires for these cases and can be omitted.

Per-file notes:

- **FieldModeLockScreen:** `open={true}` while mounted. The `bg-slate-900`
  styling currently on the overlay moves onto `Dialog.Content`'s `class`.
  `onUnlock` stays as a prop — parent unmounts the component on success.
- **ExpiryWarningBanner:** `open={warningLevel === 'critical' && !dismissed}`.
  "I Understand" button toggles `dismissed`. The amber/red inline banner
  branches (non-modal) are untouched.

### Stacking considerations

- Only `TemplateConvertModal` has nested modals (shell → save dialog). Since
  the shell is not migrated in this task, the save dialog's bits-ui portal
  renders at the document body level, above the still-present fixed-position
  shell. Verify in qa-verify that the save dialog sits above the shell content
  visually.

### What happens to the existing custom close buttons

Several migrated files render their own `×` or close button inside the card.
`Dialog.Content` ships a close button (top-right, X icon). When migrating:

- If the file had its own close button in the card header, remove it (avoid
  duplicate close affordances).
- If the file's custom close needs a confirmation step (none of these five do
  today), pass `showCloseButton={false}` and wire Dialog's
  `onOpenChange` to the existing handler.

### Dependency review

The shared `Dialog` components are already in use elsewhere in the codebase.
No new dependencies. `bits-ui` already provides `escapeKeydownBehavior` and
`interactOutsideBehavior` on `Dialog.Content`.

## Testing

The frontend's current Vitest setup is Node-only (no `jsdom`/`happy-dom`, no
Svelte plugin registered for vitest, no setup file). Existing `.test.ts` files
only cover pure utility functions and schemas. Standing up Svelte 5 component
testing for 7 files of refactor work is disproportionate to the behavior risk
— this task explicitly preserves behavior rather than introducing new logic.

**Strategy:**
- **Static verification** — `npm run check` (svelte-check + tsc) must pass,
  catching template-level and type-level regressions across all migrated files.
- **Build verification** — `npm run build` must succeed.
- **Browser verification (qa-verify)** — primary correctness signal. The
  qa-verify agent exercises every migrated modal in the running dev server and
  must confirm:
  - Each Category A modal opens when its flag is set, closes on the X button,
    closes on Escape, and closes on outside-click.
  - The lock screen does **not** close on Escape or outside-click (security
    regression guard). Only password unlock dismisses it.
  - The ExpiryWarningBanner critical branch closes only when the "I Understand"
    button is clicked, and the amber/red inline branches still render.
  - Visual parity with current `main` (no layout / styling regressions).

If behavior regressions are found and a future task wants to codify them,
that's the right time to invest in Svelte component test infrastructure —
out of scope here.

## Risks

- **Portal stacking:** bits-ui portals the content to document body. If any
  page uses its own CSS stacking context that masks portaled content, it will
  become obvious in qa-verify. Mitigation: explicit z-index override on
  `Dialog.Content` if portal siblings conflict.
- **RunDocuments backdrop-click currently resets `showModal`** directly. The
  migration drops the manual backdrop div and relies on Dialog's
  `onInteractOutside` — behavior equivalent but exercise this in tests.
- **TemplateUploadModal callsite API change:** Touching the component's prop
  contract is a mini-breaking change. Only one callsite exists
  (`TemplatesTab.svelte`), so the blast radius is contained.
- **Custom close button removal:** Removing a header close button may alter
  perceived layout. Before/after screenshots in qa-verify catch this.

## Follow-ups

- `/add_task`: Migrate `TemplateConvertModal` main shell (line 444) to a
  cleaner primitive or keep as full-page route, TBD in brainstorming for
  that task.
