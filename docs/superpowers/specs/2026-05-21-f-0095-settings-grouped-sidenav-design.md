# F-0095 — Settings navigation: grouped vertical sidenav

**Status:** Design approved (hardened after review panel)
**Date:** 2026-05-21
**ClickUp:** [F-0095](https://app.clickup.com/t/86e1gn318) · Priority P2 · Scope: Frontend

## Problem

`frontend/src/routes/settings/+page.svelte` renders 10 destinations in a horizontal
tab bar (`<div class="flex border-b overflow-x-auto">`, lines 803–884). At today's
section count the bar overflow-scrolls, hiding tabs off-screen and degrading
scannability. The pattern does not scale as Settings keeps growing.

## Goal

Replace the horizontal tab bar with a grouped vertical sidenav (Variant A from the
`settings-nav-mockups.html` exploration): a 232px left rail splitting sections into
**Workspace** and **Account** groups, each item with an icon, label, and an "Admin"
marker where applicable. The existing `activeTab` / `setTab()` URL-param logic is
reused — only the navigation markup is swapped and the panels are re-parented into a
content column.

## Architecture

| File | Change |
| --- | --- |
| `frontend/src/lib/components/settings/settingsSections.ts` | **New** — data module |
| `frontend/src/lib/components/settings/SettingsNav.svelte` | **New** — grouped vertical rail |
| `frontend/src/lib/components/settings/SettingsNav.test.ts` | **New** — Vitest component tests |
| `frontend/src/routes/settings/+page.svelte` | **Modified** — swap tab bar, wrap panels |

### `settingsSections.ts` — single source of truth

A plain data module (not a component) so both the nav and the page import one list,
eliminating drift between the nav and the page's tab-id validation.

```ts
import type { Component } from 'svelte';
import { Building2, Users, MapPin, Sparkles, FileText, CreditCard,
         User, Palette, Bell, ShieldCheck } from '@lucide/svelte';

export interface SettingsSection {
  id: string;
  label: string;
  group: 'workspace' | 'account';
  icon: Component;          // lucide-svelte component (Svelte 5 Component type)
  admin: boolean;           // true => "Admin" marker + hidden from non-admins
}

export const SECTIONS = [
  { id: 'organization',  label: 'Organization',      group: 'workspace', icon: Building2,   admin: false },
  { id: 'teams',         label: 'Teams',             group: 'workspace', icon: Users,       admin: false },
  { id: 'sites',         label: 'Sites & Equipment', group: 'workspace', icon: MapPin,      admin: false },
  { id: 'ai',            label: 'AI Models',         group: 'workspace', icon: Sparkles,    admin: true  },
  { id: 'templates',     label: 'Templates',         group: 'workspace', icon: FileText,    admin: true  },
  { id: 'billing',       label: 'Billing',           group: 'workspace', icon: CreditCard,  admin: true  },
  { id: 'profile',       label: 'Profile',           group: 'account',   icon: User,        admin: false },
  { id: 'appearance',    label: 'Appearance',        group: 'account',   icon: Palette,     admin: false },
  { id: 'notifications', label: 'Notifications',     group: 'account',   icon: Bell,        admin: false },
  { id: 'legal',         label: 'Legal',             group: 'account',   icon: ShieldCheck, admin: false },
] as const satisfies readonly SettingsSection[];

// Type and id-list are DERIVED from SECTIONS — no hand-written parallel union.
export type SettingsTabId = (typeof SECTIONS)[number]['id'];
export const SETTINGS_TAB_IDS: readonly SettingsTabId[] = SECTIONS.map((s) => s.id);
export const ADMIN_TAB_IDS: readonly SettingsTabId[] =
  SECTIONS.filter((s) => s.admin).map((s) => s.id);

export const GROUP_LABELS: Record<SettingsSection['group'], string> = {
  workspace: 'Workspace',
  account: 'Account',
};
export const DEFAULT_TAB: SettingsTabId = 'organization';
```

`as const satisfies readonly SettingsSection[]` gives both compile-time field
validation and exact string-literal id inference, so `SettingsTabId` cannot drift
from `SECTIONS`. The `icon` type must pass `svelte-check`; if `Component` does not
resolve cleanly for `@lucide/svelte` icons, fall back to that package's exported
`Icon` type — verified during implementation.

### `SettingsNav.svelte` — the rail

Props:

```ts
interface Props {
  activeTab: SettingsTabId;
  isAdmin: boolean;
  onNavigate: (id: SettingsTabId) => void;
}
```

- A `<nav aria-label="Settings sections">` root.
- Renders two groups (`Workspace`, `Account`), each with an uppercase, tracked
  `font-mono` group label and its items in `SECTIONS` order.
- Items shown to a user = `SECTIONS` minus `admin: true` entries when `!isAdmin`.
  A group with zero visible items renders nothing (defensive — never happens with
  the current model since Workspace keeps 3 non-admin items).
- Each item is rendered with the shadcn `Button` primitive (low-emphasis `ghost`
  variant) so focus-visible ring, hover state, and `cursor-pointer` come from the
  design system; the active "card-chip" treatment is layered via `class` + `cn()`.
- Each item's `<span>` label text is **always in the DOM** (visually hidden with
  `sr-only` when the rail is collapsed) so the button keeps an accessible name at
  every viewport — touch users and screen readers are never left with a bare icon.
- `aria-current="page"` on the item whose id equals `activeTab`.
- Clicking an item calls `onNavigate(id)`.
- The whole nav is wrapped in one `Tooltip.Provider` (bits-ui `Tooltip` requires a
  provider ancestor; the global layout has none).

### `+page.svelte` — wiring

- Replace `type TabName` / `const VALID_TABS` with imports of `SettingsTabId` /
  `SETTINGS_TAB_IDS` from the data module. The `activeTab` `$derived.by` body and
  `setTab()` keep identical behavior — same default (`DEFAULT_TAB = 'organization'`),
  same `goto('?tab=...')` call.
- The nav's `isAdmin` is sourced **synchronously** from
  `getCurrentOrgRoles().includes('ADMIN')` (exported by `auth.svelte`, already used
  for `canManageSite`). Because org roles are resolved during auth init — before the
  route renders — the 3 admin items render correctly on first paint with **no
  pop-in flash**. (The page's existing `members`-derived `isOrgAdmin` stays as-is for
  in-panel gating; panels are untouched.)
- Replace the `<div class="flex border-b overflow-x-auto">…</div>` block with:

  ```svelte
  <div class="flex gap-6 lg:gap-8 items-start">
    <SettingsNav {activeTab} isAdmin={navIsAdmin} onNavigate={setTab} />
    {#key activeTab}
      <div class="flex-1 min-w-0" in:fade={{ duration: 150 }}>
        {#if activeTab === 'organization'} … {/if}
        … all 10 panels, contents untouched …
      </div>
    {/key}
  </div>
  ```

- `min-w-0` on the content column lets inner data tables shrink instead of forcing
  horizontal overflow. The `{#key activeTab}` + `fade` gives a soft section-switch
  transition (per `.claude/rules/frontend-components.md`, which mandates Svelte
  transitions on content swaps).
- The notifications tab's old inline `loadChannels()` (in the removed tab `onclick`)
  is dropped; the existing `$effect` that auto-loads channels on
  `activeTab === 'notifications'` already covers it — no regression.

### Non-admin deep-link guard

Hiding admin sections from the nav would otherwise leave a "ghost" state: a non-admin
who opens `?tab=billing` directly sees the panel but no highlighted nav item. To
close this — the natural completion of the "hidden entirely" decision — `+page.svelte`
adds one `$effect`:

```
if getCurrentOrgRoles().length > 0      // roles resolved (a member always has ≥1 role)
   && !navIsAdmin
   && ADMIN_TAB_IDS.includes(activeTab):
     goto('?tab=organization', { replaceState: true, ... });
     toast.info('That section requires admin access');
```

The roles-length guard prevents a false redirect before roles resolve. This is the
only logic added to the page beyond the markup swap; it does not modify the panels.

## Visual design

Lifted from `settings-nav-mockups.html` Variant A; shadcn/Tailwind tokens only, no
new colors or fonts.

- **Rail**: 232px wide at `lg`+; group label uppercase, tracked, `font-mono`,
  `text-muted-foreground`.
- **Item (inactive)**: `Button` ghost — `text-muted-foreground`,
  `hover:bg-muted hover:text-foreground`, rounded, `transition-colors`. Icon ~17px.
- **Item (active)**: `bg-card text-foreground font-semibold`, `shadow-sm`,
  `ring-1 ring-border`, plus a 3px `bg-primary` accent bar as an
  `absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded` child span — positioned
  **inside** the item's left edge (no negative offset, so no `overflow` hack
  needed). Active icon tinted `text-primary`. The item is `relative` for the bar.
- **Admin marker**: the shared `Badge` primitive (`variant="outline"`), label
  `Admin`, trailing the section label. No one-off hardcoded font-size span.
- All clickable elements use `cursor-pointer` and a `transition` (per
  `.claude/rules/frontend-components.md`); focus-visible ring inherited from `Button`.

## Responsive behavior

Breakpoint: Tailwind `lg` (1024px).

- **≥1024px**: rail fixed 232px, always expanded; labels + group headers visible;
  toggle hidden (`lg:hidden`).
- **<1024px**: rail collapses to 60px icon-only. A toggle button pinned at the rail
  foot flips an internal `railExpanded` `$state`; expanded the rail width-transitions
  to 232px and shows labels. The width is driven by Tailwind classes
  (`w-[60px]`, `railExpanded && 'w-[232px]'`, `lg:w-[232px]`) — **pure CSS + one
  boolean**, so there is no JS-timing flash on the width itself.
- The toggle has an `aria-label` in both states (`Expand navigation` /
  `Collapse navigation`) and a ≥44×44px tap target (`min-h-11 min-w-11`) for the
  tablet/gloved-hand context.
- **Tooltips**: rendered only when the rail is collapsed
  (`belowLg && !railExpanded`) so mouse users get labels on the icon-only rail
  without redundant tooltips when labels are visible. A single conditional `Tooltip`
  wrapper lives **inside** the `{#each}` loop (not duplicated per item).
- `belowLg` is read from `window.matchMedia('(max-width: 1023px)')`, SSR-guarded
  (`browser` from `$app/environment`; initial value `false` on the server). It
  governs **only** tooltip rendering — never the rail width — so the brief
  hydration-time uncertainty is invisible. The `change` listener is registered in
  `onMount` and removed via the `onMount` cleanup return. When the viewport crosses
  to ≥1024px the listener also resets `railExpanded = false` so stale toggle state
  cannot leak back when the viewport returns below the breakpoint.
- No `overflow-x` scroll at any viewport width.
- `railExpanded` is component-local `$state` — it survives tab switches within
  Settings (SettingsNav is outside the panel `{#if}` block) and resets only on a
  full route change/reload. Cross-session persistence is YAGNI.

## Admin gating

- `navIsAdmin = getCurrentOrgRoles().includes('ADMIN')` — synchronous, resolved
  before render, so admin items neither pop in nor pop out.
- Admin panels stay reachable in the DOM, but a non-admin who deep-links to one is
  redirected to `?tab=organization` by the guard `$effect` above. In-panel `isAdmin`
  gating remains the real security control; the nav hide + redirect are UX, not a
  security boundary.

## Testing

`SettingsNav.test.ts` (Vitest + `@testing-library/svelte`, TDD red-green):

1. Renders all 10 sections in two labelled groups (`Workspace`, `Account`) when
   `isAdmin = true`.
2. Hides `AI Models`, `Templates`, `Billing` when `isAdmin = false` — 7 items render.
3. The item matching `activeTab` carries `aria-current="page"`; others do not.
4. Clicking an item invokes `onNavigate` with that section's `id`.
5. Admin sections render the "Admin" marker; non-admin sections do not.
6. The collapse toggle button has an `aria-label` and, when clicked, flips
   `railExpanded` (observable state change).
7. Every item has a non-empty accessible name even when collapsed (label kept in DOM
   as `sr-only`).
8. A data-module test asserts `SETTINGS_TAB_IDS` is the expected 10 ids and
   `ADMIN_TAB_IDS` is exactly `['ai','templates','billing']` — drift guard.

`SettingsTabId` cannot drift from `SECTIONS` by construction (`as const satisfies`),
so no separate type-sync test is needed beyond #8.

CSS media-query collapse (the 60px ⇄ 232px width swap) and the non-admin redirect are
verified in the browser-verification step of implement-task — jsdom does not evaluate
media queries.

## Scope boundaries

- **Frontend only.** No backend, schema, migration, or API change. No validation
  tier (`.claude/rules/conventions.md` T1/T2/T3) — this is presentational nav plus a
  client-side convenience redirect.
- **In scope, beyond the pure markup swap**: the non-admin deep-link redirect
  `$effect` and the `{#key}`/`fade` content transition — both are direct
  consequences of, respectively, the "hide admin sections" decision and the
  frontend transition rule.
- **Out of scope** — route to `/add_task`:
  - `⌘K` "jump to setting" command palette (mockup bonus idea).
  - The projects-page horizontal tab bar (`routes/projects/[id]/+page.svelte`) has
    the same overflow problem; a shared `VerticalNav` extraction is future work.
  - `isOrgAdmin`/role load failing silently (a real admin would see a non-admin nav);
    pre-existing data-load fragility, not introduced here.
  - Persisting `railExpanded` across reloads/sessions.
- The 10 settings panels' internal contents are not modified — only re-parented into
  the content column.

## Acceptance criteria (from ClickUp F-0095)

- [x] `SettingsNav.svelte` lives in `frontend/src/lib/components/settings/`, fed by a
  `sections` array (id, label, group, icon, admin flag).
- [x] Sections render in two labelled groups; active item shows a `bg-primary` accent
  bar + card-chip state per the lab-glass theme.
- [x] Nav drives the existing `?tab=` URL param via `setTab()`; `activeTab` derivation
  and all 10 content panels resolve unchanged.
- [x] Admin-only sections carry a subtle "Admin" marker; non-admins do not see them
  (clarified: hidden, scoped to AI Models / Templates / Billing).
- [x] Below 1024px the rail collapses to a 60px icon-only form with a tap-to-expand
  toggle and tooltips; no overflow scroll at any width.
- [x] Built only from existing shadcn-svelte primitives + Tailwind tokens; no new
  colors or fonts.

## Decisions from brainstorming

- **Collapsed-rail interaction**: tap-to-expand toggle (not pure icon-only, not
  auto-expand) — touch users need a way to read labels since tooltips do not fire
  on touch.
- **Admin sections for non-admins**: hidden entirely from the nav, with a redirect
  guard for direct URL access.
- **Admin scope**: only AI Models, Templates, Billing are admin-only. Organization,
  Teams, Sites & Equipment remain visible to all users, so the default
  `?tab=organization` keeps resolving for everyone with no change to `activeTab`
  derivation.

## Changes from review panel (2026-05-21)

Hardened after the adversarial / production-ops / DRY / UI-UX review panel:

- **Icon library** pinned to `@lucide/svelte`; `icon` typed as `Component`
  (verify with `svelte-check`).
- **`SettingsTabId` derived** from `SECTIONS` via `as const satisfies` — removed the
  hand-written parallel union and its ordering-drift risk.
- **Pop-in flash eliminated**: nav `isAdmin` now comes from the synchronous
  `getCurrentOrgRoles()` instead of the async `members` list.
- **Non-admin deep-link guard** added — redirect + toast instead of a "ghost" nav
  with no active item.
- **Accessibility**: real `<button>`s via the shadcn `Button` primitive (focus-visible
  ring), `<nav aria-label>`, label text always in the DOM (`sr-only` when collapsed)
  for a stable accessible name, toggle `aria-label` + 44px tap target.
- **Tooltip provider**: SettingsNav renders its own `Tooltip.Provider`; one
  conditional Tooltip inside the `{#each}` loop, not per-item duplication.
- **Accent bar** repositioned inside the item (`left-0`, no negative offset) — no
  `overflow:hidden` hack.
- **Admin marker** uses the shared `Badge` primitive, not a one-off span.
- **`matchMedia`** SSR-guarded, governs only tooltip rendering, listener cleaned up,
  and `railExpanded` reset when crossing the breakpoint.
- **Rail width** unified to 232px expanded (dropped the 218px asymmetry).
- **Group labels** use the `font-mono` token, not a hardcoded `DM Mono` family.
- **Content swap** wrapped in `{#key activeTab}` + `fade`.
- Out-of-scope items (`⌘K` palette, projects-page tab bar, role-load failure,
  `railExpanded` persistence) recorded as `/add_task` follow-ups.
