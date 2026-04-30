---
name: Dialog Migration Patterns (TD-0068)
description: How the 7 hand-rolled overlay migrations were structured; Category A vs B; critical prop patterns for locked dialogs
type: project
---

Seven `fixed inset-0 z-50` divs replaced with shared `Dialog` from `$lib/components/ui/dialog`.

**Category A (standard, closeable):** RoleWizard, FieldModeRoleWizard, RunDocuments, TemplateUploadModal, TemplateConvertModal nested save dialog.
- Use `bind:open={someState}` on `Dialog.Root`
- `showCloseButton` defaults to true — X button auto-present
- `escapeKeydownBehavior` and `interactOutsideBehavior` default to close behavior

**Category B (locked, must NOT close):** FieldModeLockScreen, ExpiryWarningBanner critical branch.
- Use `open={true}` (static, not bound) on `Dialog.Root` — no close reactivity flows back
- `showCloseButton={false}` on `Dialog.Content` — no X button rendered
- `escapeKeydownBehavior="ignore"` on `Dialog.Content` — Escape does nothing
- `interactOutsideBehavior="ignore"` on `Dialog.Content` — backdrop click does nothing
- These props are valid on bits-ui `Dialog.Content` (come from EscapeLayerProps + DismissibleLayerProps)

**TemplateConvertModal:** Outer shell intentionally NOT migrated (remains `fixed inset-0 z-50` hand-rolled). Only the inner "Save to Library" nested dialog was migrated. Portal-based stacking (same z-50, later DOM order) puts inner dialog correctly above the outer shell.

**TemplateUploadModal:** API changed from `onClose` callback prop to `bind:open`. Callsite in `TemplatesTab.svelte` updated.

**Why:** Gain focus trap + ARIA wiring from bits-ui Dialog while preserving visual design.

**How to apply:** When adding new modal overlays, always use `Dialog` from `$lib/components/ui/dialog` — never hand-rolled `fixed inset-0 z-50` divs. Use `escapeKeydownBehavior="ignore" interactOutsideBehavior="ignore" showCloseButton={false}` for security-critical lock screens.
