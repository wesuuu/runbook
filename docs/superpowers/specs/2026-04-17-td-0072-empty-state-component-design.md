# TD-0072 — Shared EmptyState Component

**Status:** Approved (2026-04-17)
**Task:** [TD-0072] Extract shared EmptyState component
**Scope:** Frontend

## Problem

5+ pages duplicate empty-state markup (icon + title + description + optional action) with inconsistent styling. Each page rolls its own — from one-line text to 18-line custom layouts.

## Solution

New `EmptyState` component in `$lib/components/ui/empty-state/`, following the shadcn-svelte folder pattern. All identified empty-state sites (8) refactor to use it, producing a consistent visual treatment across the app.

## Component Design

### Location

```
frontend/src/lib/components/ui/empty-state/
  empty-state.svelte
  index.ts              # re-exports EmptyState
```

### API

```ts
interface Props {
    icon?: Snippet;           // optional icon slot
    title: string;            // required
    description?: string;     // optional
    actionLabel?: string;     // optional — renders a Button if present
    onAction?: () => void;    // called when action clicked
    class?: string;           // passthrough for spacing overrides
}
```

`icon` is a Snippet — idiomatic Svelte 5, letting callers pass any lucide icon or inline SVG.

### Visual Treatment

- Centered flex column: `flex flex-col items-center text-center`
- Muted text: `text-muted-foreground` for description, `text-foreground font-semibold` for title
- `transition:fade` on mount (`duration={200}`)
- Default padding `py-10`; callers override via `class` prop
- Icon wrapper: `w-16 h-16 rounded-2xl bg-muted flex items-center justify-center` (matches the current dashboard pattern)
- Action uses existing `Button` component with `variant="outline" size="sm"`

## Refactor Scope (8 sites)

1. `routes/+page.svelte:487-504` — dashboard "No runs yet" (icon + action)
2. `routes/+page.svelte:511-514` — dashboard "No recent activity"
3. `routes/projects/+page.svelte:64-67` — "No projects found"
4. `routes/library/+page.svelte:230-233` — "No matching documents found"
5. `routes/library/+page.svelte:277-283` — description-only "Upload your SOPs..."
6. `routes/chat/+page.svelte:95-98` — "No chats yet"
7. `routes/export/+page.svelte:401-408` — "No runs specified" with Go back
8. `routes/export/+page.svelte:409-412` — "No data to export"

Out-of-scope (poor API fit; leave for a follow-up):
- `routes/library/[id]/+page.svelte:517-524` — status-dependent text
- `routes/settings/+page.svelte` — 4 empty states, one inside a DataTable snippet

## Testing

Vitest component tests in `empty-state.test.ts`:

- Renders title
- Renders description when provided; omits when not
- Renders icon snippet when provided
- Renders action button when `actionLabel` provided; clicking calls `onAction`
- Omits button when `actionLabel` absent

## Acceptance Criteria (from task)

- [x] New EmptyState component in `$lib/components/ui/empty-state/`
- [x] Props: `icon?`, `title`, `description?`, `actionLabel?`, `onAction?`
- [x] All 5+ pages refactored
- [x] Consistent visual treatment: centered, muted text, optional icon + CTA
- [x] `transition:fade` on mount
