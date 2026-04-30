---
name: UI Conventions — Dialog and Modal Patterns
description: shadcn-svelte Dialog usage patterns, z-index stacking rules, bits-ui API for locked/undismissable modals
type: project
---

## Dialog Component

Located at `$lib/components/ui/dialog` (shadcn-svelte pattern wrapping bits-ui).

Key components: `Dialog.Root`, `Dialog.Content`, `Dialog.Overlay`, `Dialog.Title`, `Dialog.Description`, `Dialog.Header`, `Dialog.Footer`, `Dialog.Close`, `Dialog.Portal`.

`dialog-content.svelte` auto-includes a Portal → Overlay → Content stack. It adds a built-in X close button (via `DialogPrimitive.Close`) at `position: absolute; right: 1rem; top: 1rem` unless `showCloseButton={false}`.

Base class on Content: `w-11/12 max-h-[90vh] overflow-y-auto gap-4 rounded-lg border p-6 shadow-lg sm:max-w-lg` — override with className.

## Bits-UI Dialog Props (valid on Dialog.Content via ...restProps)

- `escapeKeydownBehavior="ignore"` — prevents Escape from triggering close
- `interactOutsideBehavior="ignore"` — prevents outside click from triggering close
- `showCloseButton={false}` — hides the auto-rendered X button (custom to our wrapper)

## Z-Index Stacking

All Dialog overlays and content use `z-50`. Portal renders to `<body>`, appended after page content. Within the same z-index, later DOM position = on top. So a portaled dialog always stacks above non-portaled `fixed z-50` shells (like TemplateConvertModal's outer shell).

## Pattern for p-0 Dialogs

Custom-header dialogs pass `class="... p-0 flex flex-col"` to override the default `p-6`. Internal padding is then handled by the custom header/body/footer sections. The built-in X button is absolutely positioned so it still appears at `right: 1rem; top: 1rem` regardless of padding.

## No Custom Modals

Never build `fixed inset-0 z-50 bg-black/50` from scratch. Always use `Dialog`. For lock screens, use the Category B pattern above.
