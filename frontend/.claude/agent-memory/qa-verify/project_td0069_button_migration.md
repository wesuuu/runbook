---
name: TD-0069 Button Migration Patterns and Pitfalls
description: What was done in TD-0069 (raw button → Button component), what was missed, and recurring issues found
type: project
---

TD-0069 migrated ~25 raw `<button>` elements to the shared Button component and replaced 4 `window.confirm()` calls with ConfirmDialog.

## What was done correctly
- Inspector.svelte / ProcessStartInspector.svelte — ghost icon-sm close X buttons
- VersionHistoryDrawer.svelte — ghost icon-sm close X button
- PdfPreviewDrawer.svelte — ghost icon-sm close X + Retry outline sm button
- ValidationBanners.svelte — sm Button for Unarchive/Restore/Back actions
- CreateUnitOpModal.svelte — outline sm "+ Add" param button
- BatchRecordImportModal.svelte — Accept/Reject/Restore with inline class overrides; link variant for Remove/Undo
- ActivityTab.svelte — link variant Button for empty-state "Clear all filters"
- RunsTab.svelte / ProtocolsTab.svelte — ghost Button for mobile card click-through
- RunAttachmentsTab.svelte — ghost Button for image download preview
- ExpiryWarningBanner.svelte — destructive variant "I Understand"; ghost icon-sm dismiss X
- RunDocuments.svelte — outline/default Button in download modal footer
- ConfirmDialog added to ProtocolsTab, ProtocolImportModal, TemplateConvertModal, BatchRecordImportModal

## Bugs found and fixed

### 1. ActivityTab filter-bar "Clear filters" raw button not migrated
**File**: `src/lib/components/project/ActivityTab.svelte` line 138
**Was**: `<button class="text-xs text-slate-400 hover:text-slate-600 underline">Clear filters</button>`
**Fixed to**: `<Button variant="link" size="sm" class="h-auto p-0 text-xs text-slate-400 hover:text-slate-600">Clear filters</Button>`
Only the empty-state "Clear all filters" (Button variant="link") was migrated; the filter-bar one was missed.

### 2. ProtocolSidebar name-display and description-display whitespace regression
**File**: `src/lib/components/protocol/ProtocolSidebar.svelte`
Button base class enforces `whitespace-nowrap`. Both `.name-display` and `.description-display` wrap protocol name/description text that must wrap onto multiple lines. Fixed by adding `white-space: normal; overflow: visible;` to both `:global(...)` CSS blocks.

## Recurring anti-pattern to watch
When using `<Button>` with custom `:global(...)` CSS overrides, always add `white-space: normal` if the button contains wrapping text. The Button base has `whitespace-nowrap` from tailwind-variants.

**Why:** Button's `tv()` base class sets `whitespace-nowrap` for all variants. Text-content buttons that aren't single-label must override this.
**How to apply:** Any time a Button wraps a multi-word or potentially long text node in a sidebar/card context, check that the `:global(.my-class)` override includes `white-space: normal`.
