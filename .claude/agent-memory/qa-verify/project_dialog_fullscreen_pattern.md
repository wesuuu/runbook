---
name: Dialog full-screen override pattern
description: How to make Dialog.Content full-viewport in Batchrite — the base component hard-codes centering and sm:max-w-lg which must be explicitly overridden
type: project
---

The `dialog-content.svelte` component at `frontend/src/lib/components/ui/dialog/dialog-content.svelte` has two constraints that prevent simple Tailwind class overrides from making a dialog full-viewport:

1. Hard-coded inline `style="top: 50%; left: 50%; translate: -50% -50%"` — cannot be overridden by class props alone; Svelte inline styles win over Tailwind
2. Responsive `sm:max-w-lg` in the base class — `tailwind-merge` (via `cn()`) does NOT remove responsive-prefixed utilities when only the base variant is countered (e.g., `max-w-none` alone doesn't remove `sm:max-w-lg`)

**Fix applied in TD-0073 (commit d7933cf):**
- `dialog-content.svelte` now accepts an optional `style` prop via `styleProp ?? "top: 50%; ..."` — callers can override positioning without touching the shared component defaults
- Full-screen callers (like `TemplateConvertModal`) must pass:
  - `style="top: 0; left: 0; translate: none"` — eliminates the centering transform
  - `sm:max-w-none` — explicitly counters `sm:max-w-lg` at the sm breakpoint
  - `overflow-y-visible` — counters `overflow-y-auto` (otherwise inner flex layout is clipped)
  - `gap-0` — counters `gap-4` (the default Dialog grid gap adds unwanted spacing in a flex shell)

**Why:** The `Dialog.Content` is a Bits UI `DialogPrimitive.Content` rendered as a `fixed` div. Standard shadcn style is centered card. Full-viewport shells need `fixed; top:0; left:0; width:100vw; height:100vh`.

**How to apply:** Any future full-viewport dialog/drawer shell should use the same pattern. Do not attempt to override only with class props — the inline style must also be overridden.
