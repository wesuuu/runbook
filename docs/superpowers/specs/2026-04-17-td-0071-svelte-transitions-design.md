# TD-0071 — Svelte Transitions Across Frontend

## Problem

Only 2 of 60+ frontend files use `svelte/transition`. Page navigation, loading/error/empty state swaps, and list updates hard-pop across 17 pages. Our convention in `.claude/rules/frontend-components.md` requires Svelte transitions for:
- Page-level content wrappers (`fade` / `fly`)
- Loading/error/empty state transitions (`transition:fade`)
- List reorder + entry (`animate:flip` + `in:fade`)

Dashboard (`routes/+page.svelte`) uses inline CSS `@keyframes fadeSlideUp`, violating the Svelte-first convention.

## Goals

1. Every page fades in on navigation, subtly but noticeably.
2. Loading-to-content swaps feel smooth, not jarring.
3. Key lists animate entry and reorder.
4. Respect `prefers-reduced-motion`.
5. Durations live in one place for easy tuning.

## Non-Goals

- No transitions on modals/dropdowns — `bits-ui`/shadcn-svelte already handle these.
- No changes to `ProjectDataTable.svelte` — already uses `animate:flip`.
- No new UI features.

## Architecture

### Shared transitions module — `frontend/src/lib/transitions.ts`

Single source of truth for durations. Exports:

```ts
export const PAGE_MS = 150;
export const BLOCK_MS = 120;   // {#if} loading/error/empty
export const LIST_MS = 150;    // {#each} enter + animate:flip

export function prefersReducedMotion(): boolean {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export const pageDuration = () => (prefersReducedMotion() ? 0 : PAGE_MS);
export const blockDuration = () => (prefersReducedMotion() ? 0 : BLOCK_MS);
export const listDuration = () => (prefersReducedMotion() ? 0 : LIST_MS);
```

### Page-level transition in `+layout.svelte`

Wrap the two `{@render children()}` invocations with `{#key $page.url.pathname}` + `<div in:fade>`. Every route change triggers a fresh fade-in. No per-page changes needed for page-entry.

### Dashboard CSS keyframe replacement

Remove `@keyframes fadeSlideUp` and every `style="animation: fadeSlideUp ..."` in `routes/+page.svelte`. Replace with `in:fly={{ y: 12, duration: blockDuration(), delay: i * 60 }}` to preserve staggered feel using Svelte primitives.

### Conditional block transitions

For every `{#if loading}` / `{#if error}` / `{#if items.length === 0}` / empty-state `{#if}` on pages, wrap inner content with `transition:fade={{ duration: blockDuration() }}`. Only touch state-swap conditionals; leave permission/feature-toggle conditionals alone.

### List transitions

For key lists (dashboard activity, counter cards, chat sessions, chat messages, library documents, export rows, run lists):
- `animate:flip={{ duration: listDuration() }}` on each item (keyed)
- `in:fade={{ duration: listDuration() }}` on entry

Skip static lists (settings preferences, etc.) where reorder/entry is rare.

## Scope — Pages to Touch

1. `routes/+layout.svelte` — page-level transition wrapper
2. `routes/+page.svelte` — dashboard keyframes replacement + conditional blocks + list items
3. `routes/login/+page.svelte` — conditional blocks
4. `routes/register/+page.svelte` — conditional blocks
5. `routes/check-email/+page.svelte` — conditional blocks
6. `routes/projects/+page.svelte` — conditional blocks + list items
7. `routes/projects/[id]/+page.svelte` — conditional blocks
8. `routes/library/+page.svelte` — conditional blocks + list items
9. `routes/library/[id]/+page.svelte` — conditional blocks
10. `routes/runs/[id]/+page.svelte` — conditional blocks + list items
11. `routes/protocols/[id]/+page.svelte` — conditional blocks
12. `routes/experiments/[id]/+page.svelte` — conditional blocks
13. `routes/chat/+page.svelte` — conditional blocks + list items (sessions, messages)
14. `routes/field/+page.svelte` — conditional blocks
15. `routes/settings/+page.svelte` — conditional blocks
16. `routes/export/+page.svelte` — conditional blocks + list items

## Testing

- **Unit test** `transitions.test.ts`:
  - Constants are positive numbers
  - `prefersReducedMotion()` returns `false` when `matchMedia` reports `matches: false`
  - `prefersReducedMotion()` returns `true` when `matchMedia` reports `matches: true`
  - `pageDuration()` / `blockDuration()` / `listDuration()` return `0` when reduced-motion is on, constant value when off
- **No E2E**: transitions are visual; verify manually via `qa-verify` agent.
- `npm run check` and `npm run test` must pass.

## Acceptance Criteria (from task)

- [x] All 17 pages have a top-level fade/fly on their content wrapper — handled by shared layout wrapper
- [ ] All `{#if}` blocks for loading/error/empty states use `transition:fade` — per page
- [ ] Key `{#each}` lists use `animate:flip` + `in:fade` — per list
- [ ] Loading-to-content swaps feel smooth — verified via qa-verify

## Risks

- **`{#key}` full re-mount**: switching `{#key $page.url.pathname}` re-runs page scripts. For pages that call `onMount` fetches, this is fine (we *want* a reload on route change). For pages holding expensive client state across navigation, it would be wrong — but SvelteKit already unmounts pages on route change, so this is effectively a no-op.
- **Reduced-motion SSR**: `window.matchMedia` doesn't exist server-side. The function guards with `typeof window === 'undefined'` returning `false`. Initial render uses full duration; after hydration it recomputes.
- **Counter stagger**: CSS `animation-delay` with many cards can feel "stuttery" if replaced with Svelte `delay` since Svelte transitions begin at mount, not on animation-fill. Mitigated by using per-item `delay: i * 60`.
