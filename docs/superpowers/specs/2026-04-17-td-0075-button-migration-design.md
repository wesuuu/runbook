# TD-0075: Migrate raw `<button>` elements to shared Button component

**ClickUp:** [TD-0075](https://app.clickup.com/t/86e0z4e4x) · **Priority:** P2 · **Effort:** XL
**Date:** 2026-04-17 · **Author:** Wesley Uykimpang + Claude

## Context

Raw `<button>` elements with ad-hoc Tailwind styling are sprinkled across the frontend — 226 occurrences across 58 files (excluding `button.svelte` itself). Each one re-implements variants of what the shared Button component (`frontend/src/lib/components/ui/button/button.svelte`) already provides. This duplication makes visual consistency fragile: a hover/focus/disabled/cursor tweak to the Button component doesn't propagate, and style drift has already occurred (TD-0070 was filed for missing `cursor-pointer` on interactive elements).

Beyond inconsistency, a color-schema audit during brainstorming showed that many raw buttons reach outside the design system (`bg-teal-*`, `bg-emerald-*`, `bg-slate-*`, `bg-amber-*`) when a semantic schema color (`primary`, `secondary`, `destructive`, `accent`, `muted`) would do. Migrating to the Button component is the right moment to collapse that drift back to the schema.

## Goals

1. Every raw `<button>` outside `lib/components/ui/` primitives becomes a `<Button>` unless it has a genuinely unique shape that no variant can express.
2. The Button component owns container + behavior: padding, height, cursor, hover/focus rings, disabled, transitions. Callers stop re-declaring these classes.
3. Off-schema colors (teal, emerald, slate, amber in button contexts) are collapsed to schema variants unless there's a documented semantic reason.
4. Closes TD-0070 (cursor-pointer audit) for every migrated site as a natural consequence.

## Non-Goals

- No behavioral changes (click handlers, hrefs, state logic untouched).
- No navigation/routing changes.
- No migration of `<a>` tags that already look like buttons (out of scope — separate audit).
- No redesign of the Button component's core API beyond two additions (see below).
- Not converting the 3 full-card `<button>` containers into Button — they remain raw, semantic cards.

## Button API Changes

Two additions to `frontend/src/lib/components/ui/button/button.svelte`:

### 1. New variant: `tab`

Bottom-border-indicator tab pattern, used in settings, project pages, and document-upload dialog. Appears in 9 sites today.

Active state:
- Bottom border 2px, `border-foreground`
- Text color: `text-foreground`
- No background fill on hover (to avoid conflicting with `ghost`)

Inactive state:
- Bottom border 2px transparent
- Text color: `text-muted-foreground`
- `hover:text-foreground`

Size `default` keeps `h-9 px-4 py-2`. Tab buttons currently use `px-4 py-2.5` — we'll align to `default` (`py-2`) for consistency; the visual delta is half a pixel and acceptable.

### 2. New prop: `rounded`

Controls border radius independently of `variant`:

```svelte
rounded?: "default" | "full"  // default = current rounded-md behavior
```

`rounded="full"` gives `rounded-full` for chip/pill shapes. Implemented as a separate `tv()` variant dimension. Keep `default` as the default so all existing call sites are unaffected.

### Intentionally NOT Added

- **`color` prop** — would force enumerating every color ever used and fight the `tv()` variant system. Off-schema colors go through the `class` prop escape hatch, and anything appearing 3+ times is a signal that either (a) it should become a variant, or (b) it should move to the schema. Not adding this prop.
- **`chip` variant** — only 3 sites and their stylings don't actually match each other. `rounded="full"` + an appropriate existing variant (`outline`/`ghost`/`secondary`) covers them.

## Migration Strategy

### Classification buckets (226 buttons)

| Bucket | Count | Target |
|---|---|---|
| Primary CTA (main form submit, new-thing button) | ~40 | `variant="default"` |
| Ghost-text (toolbar/menu/dropdown items) | ~32 | `variant="ghost"` or `"link"` |
| Secondary (Cancel) | ~19 | `variant="secondary"` or `"outline"` |
| Toolbar icon | ~11 | `variant="ghost"` + `size="icon-sm"` |
| Tab (border-bottom indicator) | 9 | `variant="tab"` |
| Destructive (delete/remove) | 7 | `variant="destructive"` |
| Close-X (modal/drawer) | 5 | `variant="ghost"` + `size="icon-sm"` |
| Chip/pill (filter toggle) | ~3 | closest variant + `rounded="full"` |
| Card-clickable (full card container) | 3 | **KEEP RAW** |
| One-off / scoped CSS (`toolbar-btn`, `schema-add-btn`, etc.) | ~66 | case-by-case; most migrate via `Button + class prop` |
| UI primitive internals (`confirm-dialog.svelte`, `FullScreenModal.svelte`) | 2 | migrate to `<Button>` |

Target end state: ~5–10 raw `<button>` elements remain (the 3 card-clickable containers + any genuine unique shapes that survive review).

### Color unification rules

For each migrated button:

1. **Schema-compatible colors** (primary/secondary/muted/accent/destructive/foreground/background) — map directly to the matching variant.
2. **Off-schema colors** — collapse to the closest schema variant unless there's a semantic reason to keep them. Common cases:
   - `bg-teal-600 text-white hover:bg-teal-700` → `variant="default"` (primary brand)
   - `bg-emerald-600 text-white` → `variant="default"` (no semantic difference from primary)
   - `bg-slate-800 text-white` → `variant="default"` (dark fill — use primary)
   - `bg-amber-*` on a warning banner's action → KEEP (semantic warning)
   - `bg-red-*` on a delete action → `variant="destructive"`
3. **Document exceptions** in the PR description with a one-liner per exception.

### Chunking / commit strategy

Single PR but chunked commits for reviewability:

1. Button component API additions (`tab` variant, `rounded` prop) + unit tests if any.
2. UI primitives internals (`confirm-dialog.svelte`, `FullScreenModal.svelte`).
3. Routes (`src/routes/**/*.svelte` — 7 files, ~60 buttons).
4. Top-level components (`src/lib/components/*.svelte`).
5. Feature subdirectories (`src/lib/components/{run,protocol,project,settings}/**`).
6. Cleanup pass: any remaining raw buttons, documented exceptions, color-schema audit.

### Removal of redundant classes

While migrating, strip inline classes already handled by Button:
- `cursor-pointer`
- `transition-all duration-150` (or similar)
- `disabled:opacity-50`, `disabled:cursor-not-allowed`, `disabled:pointer-events-none`
- `focus-visible:*` (ring/outline)
- `inline-flex items-center justify-center gap-2`

Callers keep only classes that express layout (`w-full`, `self-end`), one-off colors (when justified), and semantic one-offs.

## Testing / Verification

- **`npm run check`** (svelte-check + tsc) — must pass.
- **`npm run test`** (Vitest) — must pass.
- **`npm run build`** — must succeed.
- **`qa-verify` agent** — browser walk-through of key pages:
  - `/` (landing dashboard cards)
  - `/runs/[id]` (action buttons, role assignment, documents tab)
  - `/settings` (tabs + forms)
  - `/export` (filters, column toggles, presets)
  - `/chat` (thread list, send, delete)
  - `/projects/[id]` (tab navigation, protocol/run/experiment/activity/settings tabs)
  - `/library/[id]` and protocol editor (toolbar, inspector schema editing)
- **Grep acceptance criterion:**
  - `rg '<button' frontend/src/routes frontend/src/lib/components` should return ≤10 matches after migration.
  - Every remaining match documented in PR description with rationale.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Visual regression from style changes | qa-verify walk-through + screenshots; review each page manually |
| New `tab` variant styling doesn't match existing tab buttons | Lift pattern from `routes/settings/+page.svelte:601` as the reference implementation |
| `rounded="full"` + `size="icon-sm"` produces a too-small hit target | Test in browser; keep original padding if needed via `class` prop |
| Scoped CSS rules (`<style>` blocks) become dead after removing a raw button's class | Grep for dead class names after each file migration; delete orphaned styles |
| Large PR review burden | Chunked commits by directory; clear commit messages |
| Svelte 5 runes compatibility | Button is already a Svelte 5 component — no issue |

## Out-of-Scope Followups

- Audit `<a class="btn ...">` anchor-styled buttons — separate tech-debt task if worth doing.
- Consolidate any remaining scoped CSS button rules (`.toolbar-btn`, `.schema-add-btn`, etc.) into shared utilities — may be obviated by this migration anyway.
- Close TD-0070 once this lands.

## Open Questions

None at design time. Decisions made inline:

- **Color prop?** No — use `class` override.
- **Chip variant?** No — `rounded="full"` + existing variant covers it.
- **Branch from main vs. current?** Main — merge target is main and F-0057 is unrelated.
