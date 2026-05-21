# F-0095 — Settings navigation: grouped vertical sidenav

**Status:** Design approved
**Date:** 2026-05-21
**ClickUp:** [F-0095](https://app.clickup.com/t/86e1gn318) · Priority P2 · Scope: Frontend

## Problem

`frontend/src/routes/settings/+page.svelte` renders 10 destinations in a horizontal
tab bar (`<div class="flex border-b overflow-x-auto">`, lines 803–884). At today's
section count the bar overflow-scrolls, hiding tabs off-screen and degrading
scannability. The pattern does not scale as Settings keeps growing.

## Goal

Replace the horizontal tab bar with a grouped vertical sidenav (Variant A from the
`settings-nav-mockups.html` exploration): a ~232px left rail splitting sections into
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
import { Building2, Users, MapPin, Sparkles, FileText, CreditCard,
         User, Palette, Bell, ShieldCheck } from 'lucide-svelte';

export interface SettingsSection {
  id: string;
  label: string;
  group: 'workspace' | 'account';
  icon: typeof Building2;   // lucide-svelte component
  admin: boolean;           // true => "Admin" marker + hidden from non-admins
}

export const SECTIONS: readonly SettingsSection[] = [
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
] as const;

export const SETTINGS_TAB_IDS = SECTIONS.map((s) => s.id);
export type SettingsTabId =
  'organization' | 'teams' | 'sites' | 'profile' | 'appearance'
  | 'notifications' | 'ai' | 'templates' | 'billing' | 'legal';

export const GROUP_LABELS: Record<SettingsSection['group'], string> = {
  workspace: 'Workspace',
  account: 'Account',
};
```

The `SettingsTabId` union is declared explicitly (kept in sync with `SECTIONS` by a
type-level check, see Testing) so it can be used as a type by `+page.svelte`.

### `SettingsNav.svelte` — the rail

Props:

```ts
interface Props {
  activeTab: SettingsTabId;
  isAdmin: boolean;
  onNavigate: (id: SettingsTabId) => void;
}
```

- Renders two groups (`Workspace`, `Account`) each with a `DM Mono`-style uppercase
  group label and its items, in `SECTIONS` order.
- Items shown to a user = `SECTIONS` minus `admin: true` entries when `!isAdmin`.
  A group with zero visible items renders nothing (defensive — never happens with
  the current model since Workspace keeps 3 non-admin items).
- Each item: icon + label, optional "Admin" marker, `aria-current="page"` when active.
- Clicking an item calls `onNavigate(id)`.

### `+page.svelte` — wiring

- Replace `type TabName` / `const VALID_TABS` with imports of `SettingsTabId` /
  `SETTINGS_TAB_IDS` from the data module. The `activeTab` `$derived.by` body and
  `setTab()` are otherwise **unchanged** — same default (`'organization'`), same
  `goto('?tab=...')` call.
- Replace the `<div class="flex border-b overflow-x-auto">…</div>` block with:

  ```svelte
  <div class="flex gap-6 lg:gap-8 items-start">
    <SettingsNav {activeTab} isAdmin={isOrgAdmin} onNavigate={setTab} />
    <div class="flex-1 min-w-0">
      {#if activeTab === 'organization'} … {/if}
      … all 10 panels, contents untouched …
    </div>
  </div>
  ```

- `min-w-0` on the content column lets inner data tables shrink instead of forcing
  horizontal overflow.
- The notifications tab's old inline `loadChannels()` (in the removed tab `onclick`)
  is dropped; the existing `$effect` that auto-loads channels on
  `activeTab === 'notifications'` already covers it — no regression.

## Visual design

Lifted from `settings-nav-mockups.html` Variant A; shadcn/Tailwind tokens only, no
new colors or fonts.

- **Rail**: 232px wide at `lg`+; group label is uppercase, tracked, `text-muted-foreground`.
- **Item (inactive)**: `text-muted-foreground`, `hover:bg-muted hover:text-foreground`,
  rounded, `transition-colors`. Icon ~17px.
- **Item (active)**: `bg-card text-foreground font-semibold`, `shadow-sm`,
  `ring-1 ring-border`, plus a 3px `bg-primary` accent bar pinned to the left edge.
  Active icon tinted `text-primary`.
- **Admin marker**: a small uppercase `Admin` chip (`text-[9px]`, `border border-border`,
  `rounded`, `text-muted-foreground`) trailing the label.
- All clickable items use `cursor-pointer` and a `transition` (per
  `.claude/rules/frontend-components.md`).

## Responsive behavior

Breakpoint: Tailwind `lg` (1024px).

- **≥1024px**: rail fixed 232px, always expanded; labels + group headers visible;
  no toggle.
- **<1024px**: rail collapses to 60px icon-only. A toggle button pinned at the rail
  foot (`lg:hidden`) flips an internal `railExpanded` `$state`; expanded the rail
  width-transitions to ~218px and shows labels. Layout is inline flex — the content
  column reflows. `railExpanded` is ephemeral (resets on reload; persistence is YAGNI).
- **Tooltips**: when the rail is collapsed (`below-lg media query && !railExpanded`),
  each item is wrapped in the shadcn `Tooltip` with the label as content, so
  mouse users get labels on the icon-only rail. When labels are already visible the
  tooltip is not rendered (no redundancy).
- No `overflow-x` scroll at any viewport width.

The below-lg state is detected with `window.matchMedia('(max-width: 1023px)')`,
subscribed in `onMount` and cleaned up on destroy; `collapsed = belowLg && !railExpanded`.

## Admin gating

- `isOrgAdmin` in `+page.svelte` derives from the async-loaded `members` list. Before
  members resolve it is `false`, so the 3 admin items (`ai`, `templates`, `billing`)
  are absent on first paint and **pop in** once membership loads — an accepted brief
  flash, consistent with the panels themselves loading async. There is no pop-*out*
  (items never appear then vanish).
- Admin panels stay reachable by direct URL (`?tab=billing`) because the 10 panels are
  untouched and already gate their controls internally via `isAdmin` props. The nav
  only removes them from discovery for non-admins. This is a deliberate, in-scope
  boundary — not a security control (in-panel gating remains the control).

## Testing

`SettingsNav.test.ts` (Vitest + `@testing-library/svelte`, TDD red-green):

1. Renders all 10 sections in two labelled groups (`Workspace`, `Account`) when
   `isAdmin = true`.
2. Hides `AI Models`, `Templates`, `Billing` when `isAdmin = false` — 7 items render.
3. The item matching `activeTab` carries `aria-current="page"`; others do not.
4. Clicking an item invokes `onNavigate` with that section's `id`.
5. Admin sections render the "Admin" marker; non-admin sections do not.
6. The collapse toggle flips `railExpanded` (rendered state change observable).

A type-level assertion in the data module / test keeps `SettingsTabId` and the
`SECTIONS` ids in sync (e.g. `satisfies` check, or a runtime test asserting
`SETTINGS_TAB_IDS` equals the expected 10 ids).

CSS media-query collapse (the 60px ⇄ 232px width swap) is not unit-testable in
jsdom — it is verified in the browser-verification step of implement-task.

## Scope boundaries

- **Frontend only.** No backend, schema, migration, or API change. No validation
  tier (`.claude/rules/conventions.md` T1/T2/T3) — this is pure presentational nav.
- **Out of scope** (route to `/add_task` if desired): the `⌘K` "jump to setting"
  command palette floated as a bonus in the mockup; redirecting non-admins away from
  admin panels on direct URL access; persisting `railExpanded` across reloads.
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
  (per clarified decision: hidden, scoped to AI Models / Templates / Billing).
- [x] Below 1024px the rail collapses to a 60px icon-only form with a tap-to-expand
  toggle and tooltips; no overflow scroll at any width.
- [x] Built only from existing shadcn-svelte primitives + Tailwind tokens; no new
  colors or fonts.

## Decisions from brainstorming

- **Collapsed-rail interaction**: tap-to-expand toggle (not pure icon-only, not
  auto-expand) — touch users need a way to read labels since tooltips do not fire
  on touch.
- **Admin sections for non-admins**: hidden entirely from the nav.
- **Admin scope**: only AI Models, Templates, Billing are admin-only. Organization,
  Teams, Sites & Equipment remain visible to all users (non-admins read them today),
  so the default `?tab=organization` keeps resolving for everyone with no change to
  `activeTab` derivation.
