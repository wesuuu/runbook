# F-0095 — Settings grouped vertical sidenav — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 10-destination horizontal overflow-scrolling tab bar on the Settings page with a grouped vertical sidenav (Workspace / Account groups) driven by the existing `?tab=` URL param.

**Architecture:** A plain data module (`settingsSections.ts`) is the single source of truth for the section list, its derived tab-id union, and the admin set. A new `SettingsNav.svelte` renders the rail from that data. `+page.svelte` swaps its tab-bar markup for `<SettingsNav>`, re-parents the 10 untouched panels into a content column, and adds one `$effect` that redirects non-admins away from admin-only deep links. No backend, schema, or API change.

**Tech Stack:** Svelte 5 runes, SvelteKit, shadcn-svelte (`Button`, `Badge`, `Tooltip`), Tailwind 4, `@lucide/svelte` icons, Vitest + `@testing-library/svelte`.

**Spec:** `docs/superpowers/specs/2026-05-21-f-0095-settings-grouped-sidenav-design.md`

---

## File Structure

| File | Responsibility |
| --- | --- |
| `frontend/src/lib/components/settings/settingsSections.ts` | **New.** Section list, derived `SettingsTabId` type, `SETTINGS_TAB_IDS`, `ADMIN_TAB_IDS`, `GROUP_LABELS`, `DEFAULT_TAB`. |
| `frontend/src/lib/components/settings/SettingsNav.svelte` | **New.** Grouped vertical rail: groups, items, active state, admin filter, collapse toggle, tooltips. |
| `frontend/src/lib/components/settings/SettingsNav.test.ts` | **New.** Vitest tests for the data module and the component. |
| `frontend/src/routes/settings/+page.svelte` | **Modified.** Swap tab bar for `<SettingsNav>`, wrap panels in a content column, add non-admin deep-link guard. |

Each task's commands run from `frontend/` unless stated otherwise.

---

## Task 1: Section data module

**Files:**
- Create: `frontend/src/lib/components/settings/settingsSections.ts`
- Create: `frontend/src/lib/components/settings/SettingsNav.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/settings/SettingsNav.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { SETTINGS_TAB_IDS, ADMIN_TAB_IDS } from './settingsSections';

describe('settingsSections data module', () => {
    it('exposes all 10 tab ids in display order', () => {
        expect([...SETTINGS_TAB_IDS]).toEqual([
            'organization',
            'teams',
            'sites',
            'ai',
            'templates',
            'billing',
            'profile',
            'appearance',
            'notifications',
            'legal',
        ]);
    });

    it('marks exactly AI Models, Templates and Billing as admin-only', () => {
        expect([...ADMIN_TAB_IDS]).toEqual(['ai', 'templates', 'billing']);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: FAIL — cannot resolve `./settingsSections`.

- [ ] **Step 3: Create the data module**

Create `frontend/src/lib/components/settings/settingsSections.ts`:

```ts
import type { Component } from 'svelte';
import {
    Building2,
    Users,
    MapPin,
    Sparkles,
    FileText,
    CreditCard,
    User,
    Palette,
    Bell,
    ShieldCheck,
} from '@lucide/svelte';

export interface SettingsSection {
    id: string;
    label: string;
    group: 'workspace' | 'account';
    icon: Component;
    admin: boolean;
}

// SECTIONS is the single source of truth. `as const satisfies` gives both
// field-shape validation and exact string-literal id inference, so the
// SettingsTabId type below cannot drift from this list.
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

export type SettingsTabId = (typeof SECTIONS)[number]['id'];

export const SETTINGS_TAB_IDS: readonly SettingsTabId[] = SECTIONS.map(
    (s) => s.id,
);

export const ADMIN_TAB_IDS: readonly SettingsTabId[] = SECTIONS.filter(
    (s) => s.admin,
).map((s) => s.id);

export const GROUP_LABELS: Record<SettingsSection['group'], string> = {
    workspace: 'Workspace',
    account: 'Account',
};

export const DEFAULT_TAB: SettingsTabId = 'organization';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: PASS — 2 tests.

- [ ] **Step 5: Verify the icon type compiles**

Run: `npm run check 2>&1 | grep -E 'ERROR|ERRORS [0-9]'`

The repo has a pre-existing `npm run check` baseline of **54 errors** — none in files this plan creates, and exactly **2** in `routes/settings/+page.svelte`. `svelte-check` prints each error as `ERROR "<path>" <line>:<col> "<message>"`, so filter by file path, never by line number. After this step: **no `ERROR` line may reference `settingsSections.ts`**, and the `ERRORS` total must stay at 54.

If `icon: Component` produces a type error against `@lucide/svelte` icons, change the import to `import type { Icon } from '@lucide/svelte';` and the field to `icon: typeof Icon;`, then re-run. Stop and use whichever compiles.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/settings/settingsSections.ts \
        frontend/src/lib/components/settings/SettingsNav.test.ts
git commit -m "feat(F-0095): add settings section data module"
```

---

## Task 2: SettingsNav rail — groups, items, active state, navigation

Builds the static (always-expanded) rail. The collapse/responsive layer is added in Task 3.

**Files:**
- Create: `frontend/src/lib/components/settings/SettingsNav.svelte`
- Modify: `frontend/src/lib/components/settings/SettingsNav.test.ts`

- [ ] **Step 1: Write the failing component tests**

Append to `frontend/src/lib/components/settings/SettingsNav.test.ts` (keep the existing data-module `describe`; add the imports below to the top, merging with the existing import line):

```ts
import { render, fireEvent } from '@testing-library/svelte';
import { vi } from 'vitest';
import SettingsNav from './SettingsNav.svelte';

const ALL_LABELS = [
    'Organization',
    'Teams',
    'Sites & Equipment',
    'AI Models',
    'Templates',
    'Billing',
    'Profile',
    'Appearance',
    'Notifications',
    'Legal',
];

describe('SettingsNav', () => {
    it('renders all 10 sections in the Workspace and Account groups for an admin', () => {
        const { getByText } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate: vi.fn() },
        });
        expect(getByText('Workspace')).toBeTruthy();
        expect(getByText('Account')).toBeTruthy();
        for (const label of ALL_LABELS) {
            expect(getByText(label)).toBeTruthy();
        }
    });

    it('hides AI Models, Templates and Billing from a non-admin', () => {
        const { getByText, queryByText } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: false, onNavigate: vi.fn() },
        });
        expect(getByText('Organization')).toBeTruthy();
        expect(queryByText('AI Models')).toBeNull();
        expect(queryByText('Templates')).toBeNull();
        expect(queryByText('Billing')).toBeNull();
    });

    it('marks the active section with aria-current="page" and no others', () => {
        const { getByRole } = render(SettingsNav, {
            props: { activeTab: 'teams', isAdmin: true, onNavigate: vi.fn() },
        });
        expect(getByRole('button', { name: /Teams/ })).toHaveAttribute(
            'aria-current',
            'page',
        );
        expect(
            getByRole('button', { name: /Organization/ }),
        ).not.toHaveAttribute('aria-current');
    });

    it('calls onNavigate with the section id when an item is clicked', async () => {
        const onNavigate = vi.fn();
        const { getByRole } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate },
        });
        await fireEvent.click(getByRole('button', { name: /Teams/ }));
        expect(onNavigate).toHaveBeenCalledWith('teams');
    });

    it('renders an "Admin" marker on each admin-only section', () => {
        const { getAllByText } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate: vi.fn() },
        });
        expect(getAllByText('Admin')).toHaveLength(3);
    });

    it('gives every nav item a non-empty accessible name', () => {
        const { getByRole } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate: vi.fn() },
        });
        for (const label of ALL_LABELS) {
            expect(getByRole('button', { name: new RegExp(label) })).toBeTruthy();
        }
    });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: FAIL — cannot resolve `./SettingsNav.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/settings/SettingsNav.svelte`:

```svelte
<script lang="ts">
    import { cn } from '$lib/utils';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import {
        SECTIONS,
        GROUP_LABELS,
        type SettingsTabId,
    } from './settingsSections';

    interface Props {
        activeTab: SettingsTabId;
        isAdmin: boolean;
        onNavigate: (id: SettingsTabId) => void;
    }
    let { activeTab, isAdmin, onNavigate }: Props = $props();

    const visibleSections = $derived(
        isAdmin ? SECTIONS : SECTIONS.filter((s) => !s.admin),
    );

    // Two ordered groups; a group with no visible items renders nothing.
    const groups = $derived(
        (['workspace', 'account'] as const)
            .map((group) => ({
                group,
                label: GROUP_LABELS[group],
                items: visibleSections.filter((s) => s.group === group),
            }))
            .filter((g) => g.items.length > 0),
    );
</script>

<nav aria-label="Settings sections" class="shrink-0 w-[232px]">
    <div class="flex flex-col gap-6">
        {#each groups as group (group.group)}
            <div class="flex flex-col gap-1">
                <span
                    class="px-3 pb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground"
                >
                    {group.label}
                </span>
                {#each group.items as section (section.id)}
                    {@const isActive = section.id === activeTab}
                    {@const Icon = section.icon}
                    <Button
                        variant="ghost"
                        onclick={() => onNavigate(section.id)}
                        aria-current={isActive ? 'page' : undefined}
                        class={cn(
                            'relative w-full justify-start gap-3 min-h-11 px-3 font-normal',
                            'text-muted-foreground hover:bg-muted hover:text-foreground',
                            isActive &&
                                'bg-card text-foreground font-semibold ring-1 ring-border',
                        )}
                    >
                        {#if isActive}
                            <span
                                aria-hidden="true"
                                class="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded bg-primary"
                            ></span>
                        {/if}
                        <Icon
                            class={cn(
                                'size-[17px] shrink-0',
                                isActive && 'text-primary',
                            )}
                        />
                        <span class="flex-1 truncate text-left">
                            {section.label}
                        </span>
                        {#if section.admin}
                            <Badge variant="outline">Admin</Badge>
                        {/if}
                    </Button>
                {/each}
            </div>
        {/each}
    </div>
</nav>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: PASS — 8 tests (2 data-module + 6 component).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/settings/SettingsNav.svelte \
        frontend/src/lib/components/settings/SettingsNav.test.ts
git commit -m "feat(F-0095): add SettingsNav grouped rail"
```

---

## Task 3: SettingsNav — collapse toggle, responsive width, tooltips

Adds the `<1024px` behavior: a 60px icon-only rail, a tap-to-expand toggle, and tooltips on the collapsed rail.

**Files:**
- Modify: `frontend/src/lib/components/settings/SettingsNav.svelte`
- Modify: `frontend/src/lib/components/settings/SettingsNav.test.ts`

- [ ] **Step 1: Write the failing tests for the responsive layer**

Two new tests: the collapse toggle, and one that exercises the collapsed (`belowLg`) branch. The existing `matchMedia` stub returns `matches: false`, so without a dedicated `matches: true` test the entire tooltip/collapse code path is never executed (a "false green" — a crash there would pass CI).

In `frontend/src/lib/components/settings/SettingsNav.test.ts`: change the vitest import to add `beforeEach`/`afterEach`, add a `tick` import from `svelte`, and insert the `beforeEach`/`afterEach` and the two new `it` blocks **inside** the existing `describe('SettingsNav', ...)`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { tick } from 'svelte';
```

```ts
    // Factory for a jsdom matchMedia stub: jsdom has neither matchMedia
    // (SettingsNav reads it in onMount) nor ResizeObserver (bits-ui Tooltip).
    function stubMatchMedia(matches: boolean) {
        vi.stubGlobal(
            'matchMedia',
            vi.fn((query: string) => ({
                matches,
                media: query,
                onchange: null,
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                addListener: vi.fn(),
                removeListener: vi.fn(),
                dispatchEvent: vi.fn(),
            })),
        );
    }

    beforeEach(() => {
        stubMatchMedia(false);
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe() {}
                unobserve() {}
                disconnect() {}
            },
        );
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('toggles the collapse state via the labelled toggle button', async () => {
        const { getByLabelText } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate: vi.fn() },
        });
        const expand = getByLabelText('Expand navigation');
        expect(expand).toBeTruthy();
        await fireEvent.click(expand);
        expect(getByLabelText('Collapse navigation')).toBeTruthy();
    });

    it('collapses group labels and renders items via the tooltip branch below the lg breakpoint', async () => {
        stubMatchMedia(true); // viewport < 1024px
        const { getByText, getByRole } = render(SettingsNav, {
            props: { activeTab: 'organization', isAdmin: true, onNavigate: vi.fn() },
        });
        await tick(); // let onMount set belowLg and derivations settle
        // On the collapsed icon-only rail the group label is visually hidden...
        expect(getByText('Workspace').className).toContain('sr-only');
        // ...but every item still renders (inside the {#if showTooltips} branch).
        expect(getByRole('button', { name: /Teams/ })).toBeTruthy();
    });
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: both new tests FAIL — the toggle test with `Unable to find a label with the text of: Expand navigation`, and the collapsed-branch test because the Task 2 component's `Workspace` label has no `sr-only` class. The 8 prior tests still PASS.

- [ ] **Step 3: Replace the component with the responsive version**

Overwrite `frontend/src/lib/components/settings/SettingsNav.svelte` with:

```svelte
<script lang="ts">
    import { onMount } from 'svelte';
    import { cn } from '$lib/utils';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import * as Tooltip from '$lib/components/ui/tooltip';
    import { PanelLeftOpen, PanelLeftClose } from '@lucide/svelte';
    import {
        SECTIONS,
        GROUP_LABELS,
        type SettingsSection,
        type SettingsTabId,
    } from './settingsSections';

    interface Props {
        activeTab: SettingsTabId;
        isAdmin: boolean;
        onNavigate: (id: SettingsTabId) => void;
    }
    let { activeTab, isAdmin, onNavigate }: Props = $props();

    // Collapse state — only meaningful below the lg breakpoint.
    let railExpanded = $state(false);
    // belowLg governs ONLY tooltip rendering, never rail width.
    let belowLg = $state(false);

    onMount(() => {
        // onMount never runs during SSR, so window is always defined here.
        if (typeof window.matchMedia !== 'function') return;
        const mq = window.matchMedia('(max-width: 1023px)');
        belowLg = mq.matches;
        const onChange = (e: MediaQueryListEvent) => {
            belowLg = e.matches;
            // Reset stale toggle state when returning to the desktop layout.
            if (!e.matches) railExpanded = false;
        };
        mq.addEventListener('change', onChange);
        return () => mq.removeEventListener('change', onChange);
    });

    const visibleSections = $derived(
        isAdmin ? SECTIONS : SECTIONS.filter((s) => !s.admin),
    );

    // Two ordered groups; a group with no visible items renders nothing.
    const groups = $derived(
        (['workspace', 'account'] as const)
            .map((group) => ({
                group,
                label: GROUP_LABELS[group],
                items: visibleSections.filter((s) => s.group === group),
            }))
            .filter((g) => g.items.length > 0),
    );

    // Tooltips appear only on the collapsed icon-only rail.
    const showTooltips = $derived(belowLg && !railExpanded);
</script>

{#snippet navItem(
    section: SettingsSection,
    isActive: boolean,
    triggerProps: Record<string, unknown>,
)}
    {@const Icon = section.icon}
    <Button
        variant="ghost"
        {...triggerProps}
        onclick={() => onNavigate(section.id)}
        aria-current={isActive ? 'page' : undefined}
        class={cn(
            'relative w-full justify-start gap-3 min-h-11 px-3 font-normal',
            'text-muted-foreground hover:bg-muted hover:text-foreground',
            isActive &&
                'bg-card text-foreground font-semibold ring-1 ring-border',
        )}
    >
        {#if isActive}
            <span
                aria-hidden="true"
                class="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded bg-primary"
            ></span>
        {/if}
        <Icon class={cn('size-[17px] shrink-0', isActive && 'text-primary')} />
        <span
            class={cn(
                'flex-1 truncate text-left',
                !railExpanded && 'sr-only lg:not-sr-only',
            )}
        >
            {section.label}
        </span>
        {#if section.admin}
            <Badge
                variant="outline"
                class={cn(!railExpanded && 'hidden lg:inline-flex')}
            >
                Admin
            </Badge>
        {/if}
    </Button>
{/snippet}

<nav
    aria-label="Settings sections"
    class={cn(
        'shrink-0 transition-[width] duration-200',
        'w-[60px]',
        railExpanded && 'w-[232px]',
        'lg:w-[232px]',
    )}
>
    <Tooltip.Provider delayDuration={150}>
        <div class="flex flex-col gap-6">
            {#each groups as group (group.group)}
                <div class="flex flex-col gap-1">
                    <span
                        class={cn(
                            'px-3 pb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground',
                            !railExpanded && 'sr-only lg:not-sr-only',
                        )}
                    >
                        {group.label}
                    </span>
                    {#each group.items as section (section.id)}
                        {@const isActive = section.id === activeTab}
                        {#if showTooltips}
                            <Tooltip.Root>
                                <Tooltip.Trigger>
                                    {#snippet child({ props })}
                                        {@render navItem(
                                            section,
                                            isActive,
                                            props,
                                        )}
                                    {/snippet}
                                </Tooltip.Trigger>
                                <Tooltip.Content side="right">
                                    {section.label}
                                </Tooltip.Content>
                            </Tooltip.Root>
                        {:else}
                            {@render navItem(section, isActive, {})}
                        {/if}
                    {/each}
                </div>
            {/each}
        </div>
    </Tooltip.Provider>

    <!-- Collapse toggle — only below the lg breakpoint. -->
    <div class="mt-6 lg:hidden">
        <Button
            variant="ghost"
            onclick={() => (railExpanded = !railExpanded)}
            aria-label={railExpanded
                ? 'Collapse navigation'
                : 'Expand navigation'}
            class="w-full justify-start gap-3 min-h-11 min-w-11 px-3 text-muted-foreground"
        >
            {#if railExpanded}
                <PanelLeftClose class="size-[17px] shrink-0" />
            {:else}
                <PanelLeftOpen class="size-[17px] shrink-0" />
            {/if}
            <span class={cn('truncate', !railExpanded && 'sr-only')}>
                {railExpanded ? 'Collapse' : 'Expand'}
            </span>
        </Button>
    </div>
</nav>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: PASS — 10 tests (2 data-module + 6 from Task 2 + 2 from Task 3).

- [ ] **Step 5: Type-check the component**

Run: `npm run check 2>&1 | grep -E 'ERROR|ERRORS [0-9]'`
Expected: **no `ERROR` line referencing `SettingsNav.svelte`**; the `ERRORS` total stays at the 54-error baseline (see Task 1 Step 5). If the `Tooltip.Trigger` `child` snippet errors, confirm `props` is destructured as `{#snippet child({ props })}` and that the snippet spreads `triggerProps` onto `<Button>`.

The `Tooltip.Trigger` + `{#snippet child({ props })}` + `<Button>` composition is the canonical bits-ui v2 pattern (the same `child` mechanism is used by `ContextMenu.Trigger` in `UnitOpNode.svelte`), and `<Button>` forwards `...restProps` to its `<button>` so the tooltip anchor binds. Type-checking confirms the wiring; that the tooltip *visually anchors* on the collapsed rail is confirmed in browser verification (Task 6 Step 4).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/settings/SettingsNav.svelte \
        frontend/src/lib/components/settings/SettingsNav.test.ts
git commit -m "feat(F-0095): add collapse toggle and tooltips to SettingsNav"
```

---

## Task 4: Wire SettingsNav into the Settings page

Swap the horizontal tab bar for `<SettingsNav>` and re-parent the 10 panels into a content column. Panel contents are untouched.

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Add imports**

In `frontend/src/routes/settings/+page.svelte`, change the existing auth import (line 6) to add `getCurrentOrgRoles`:

```ts
import { getUser, getCurrentOrg, getOrgs, refreshUser, getUserPreferences, getToken, getCurrentOrgRoles } from '$lib/auth.svelte';
```

Add two new imports next to the other `settings` component imports (after the `OrgProtocolApproversCard` import, ~line 27):

```ts
import SettingsNav from '$lib/components/settings/SettingsNav.svelte';
import {
    SETTINGS_TAB_IDS,
    ADMIN_TAB_IDS,
    DEFAULT_TAB,
    type SettingsTabId,
} from '$lib/components/settings/settingsSections';
```

- [ ] **Step 2: Replace the tab-id type, validation list, and `activeTab` derivation**

Step 1 added import lines, so line numbers have shifted — anchor on content. Replace the block that begins with `type TabName =` and ends with the closing brace of the `setTab` function:

```ts
    type TabName = 'organization' | 'teams' | 'sites' | 'profile' | 'appearance' | 'notifications' | 'ai' | 'templates' | 'billing' | 'legal';
    const VALID_TABS: TabName[] = ['organization', 'teams', 'sites', 'profile', 'appearance', 'notifications', 'ai', 'templates', 'billing', 'legal'];

    const activeTab = $derived.by<TabName>(() => {
        const t = $page.url.searchParams.get('tab');
        return VALID_TABS.includes(t as TabName) ? (t as TabName) : 'organization';
    });

    function setTab(tab: TabName) {
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }
```

with:

```ts
    // requestedTab is the raw, validated ?tab= value from the URL.
    const requestedTab = $derived.by<SettingsTabId>(() => {
        const t = $page.url.searchParams.get('tab');
        return SETTINGS_TAB_IDS.includes(t as SettingsTabId)
            ? (t as SettingsTabId)
            : DEFAULT_TAB;
    });

    function setTab(tab: SettingsTabId) {
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }

    // navIsAdmin is the nav's admin gate. It is intentionally SEPARATE from
    // the existing `isOrgAdmin` (defined later in this file): `isOrgAdmin`
    // derives from the async-loaded `members` list and is false until that
    // fetch lands — fine for the Organization tab's member UI, which renders
    // only after the load. The nav must decide which sections to show on
    // first paint, so it uses getCurrentOrgRoles(): auth resolves org roles
    // before the root layout lets this route render (it gates on
    // isInitialized()), so admin items never pop in or out.
    const navIsAdmin = $derived(getCurrentOrgRoles().includes('ADMIN'));

    // activeTab is the *effective* tab actually rendered. A non-admin who
    // deep-links to an admin-only section (e.g. ?tab=billing) is shown the
    // default tab instead, so admin panels never mount for them and the
    // {#key} content transition never double-fires. The URL itself is
    // corrected separately by the guard $effect added in Task 5.
    const activeTab = $derived(
        !navIsAdmin && ADMIN_TAB_IDS.includes(requestedTab)
            ? DEFAULT_TAB
            : requestedTab,
    );
```

- [ ] **Step 3: Replace the tab-bar markup and open the content column**

Line numbers in this file shift as earlier steps edit it, so **anchor this edit on unique strings, not line numbers.** The tab bar is a single block: it starts with the comment line `<!-- Tabs -->` and ends with the `</div>` that closes `<div class="flex border-b border-border overflow-x-auto">` — that closing `</div>` is immediately followed by the unique comment `<!-- Organization Tab -->`.

Replace the entire region **from `<!-- Tabs -->` up to (but not including) `<!-- Organization Tab -->`** with exactly:

```svelte
    <div class="flex gap-6 lg:gap-8 items-start">
        <SettingsNav {activeTab} isAdmin={navIsAdmin} onNavigate={setTab} />
        {#key activeTab}
            <div class="flex-1 min-w-0" in:fade={{ duration: blockDuration() }}>
```

`blockDuration` is already imported in this file (alongside `listDuration` from `$lib/transitions`); it returns `0` when the user has `prefers-reduced-motion`, so the content transition respects that setting. Leave the `<!-- Organization Tab -->` comment and everything from `{#if activeTab === 'organization'}` onward exactly as-is.

- [ ] **Step 4: Close the content column, key block, and flex wrapper**

Anchor on unique strings, not line numbers. The 10-panel `{#if}`/`{:else if}` chain ends with a single `{/if}`, immediately followed by the `</div>` that closes the page container `<div class="max-w-6xl mx-auto space-y-8">`. That `</div>` is in turn immediately followed by the `<ConfirmDialog` element. So the `{/if}` + `</div>` + `<ConfirmDialog` sequence is unique — **include the `<ConfirmDialog …>` opening line in the `old_string` for uniqueness, and leave it unchanged in `new_string`.**

Change:

```svelte
    {/if}
</div>

<ConfirmDialog
```

to:

```svelte
    {/if}
            </div>
        {/key}
    </div>
</div>

<ConfirmDialog
```

This closes, in order: the content column, the `{#key}` block, the `flex gap-6` wrapper, and the original `max-w-6xl` container. (Match the exact existing indentation of the `{/if}`, `</div>`, and `<ConfirmDialog` lines when forming `old_string`.)

- [ ] **Step 5: Type-check and confirm the page compiles**

Run: `npm run check 2>&1 | grep -E 'ERROR|ERRORS [0-9]'`

`routes/settings/+page.svelte` has exactly **2** pre-existing `ERROR` lines in the 54-error baseline (a `Property 'roles' does not exist` pair, unrelated to this work). After this task it must still show **exactly 2** `ERROR` lines for that file — count them; do not match on line numbers, which shift. If a 3rd appears, this task introduced it — most likely a leftover `TabName` reference. Replace every remaining `TabName` in the file with `SettingsTabId` (structurally identical) and re-run. The `ERRORS` total must stay at 54.

- [ ] **Step 6: Run the existing frontend test suite**

Run: `npm run test`
Expected: PASS — no regressions; `SettingsNav.test.ts` included.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(F-0095): replace settings tab bar with SettingsNav"
```

---

## Task 5: Non-admin deep-link guard

A non-admin who opens `?tab=billing` directly would see the panel with no matching nav item (admin items are hidden). Redirect them to the default tab.

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Add the guard `$effect`**

The `requestedTab`/`activeTab` split from Task 4 already prevents an admin panel from *rendering* for a non-admin (`activeTab` falls back to the default). This `$effect` does the remaining job — correcting the URL so it no longer reads `?tab=billing`. It must therefore test `requestedTab` (the raw URL value); testing `activeTab` would never be true, since `activeTab` is already the sanitized effective tab.

In `frontend/src/routes/settings/+page.svelte`, locate the existing notifications auto-load `$effect` (anchor on its body — it calls the channel loader when `activeTab === 'notifications'`) and add this new `$effect` immediately after it, still inside `<script>`:

```ts
    // Non-admin deep-link guard. activeTab already falls back to the default
    // tab when a non-admin deep-links to an admin-only section, so the correct
    // panel renders — but the URL still says e.g. ?tab=billing. Rewrite it.
    // After the redirect requestedTab becomes 'organization', so this effect
    // re-runs once, finds the condition false, and does not re-fire the toast.
    $effect(() => {
        if (
            getCurrentOrgRoles().length > 0 &&
            !navIsAdmin &&
            ADMIN_TAB_IDS.includes(requestedTab)
        ) {
            goto('?tab=organization', {
                replaceState: true,
                keepFocus: true,
                noScroll: true,
            });
            toast.info('That section requires admin access');
        }
    });
```

`getCurrentOrgRoles`, `navIsAdmin`, `ADMIN_TAB_IDS`, `requestedTab`, `goto`, and `toast` are all already imported or declared (Task 4 and the existing file).

- [ ] **Step 2: Type-check**

Run: `npm run check 2>&1 | grep -E 'ERROR|ERRORS [0-9]'`
`routes/settings/+page.svelte` must still show **exactly 2** `ERROR` lines (the baseline pair), and the `ERRORS` total must stay at 54. A 3rd error in that file means this step introduced it — fix before continuing.

- [ ] **Step 3: Run the frontend test suite**

Run: `npm run test`
Expected: PASS — no regressions.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(F-0095): redirect non-admins away from admin-only settings deep links"
```

---

## Task 6: Full verification

**Files:** none — verification only.

- [ ] **Step 1: Run the full check (svelte-check + tsc)**

Run: `npm run check 2>&1 | tail -3`
The repo has a pre-existing baseline of **54 errors / 47 warnings** (`svelte-check` ends with `COMPLETED … ERRORS 54 WARNINGS 47`). Expected after this plan: still **`ERRORS 54`** — no new errors. Specifically: zero `ERROR` lines referencing `settingsSections.ts`, `SettingsNav.svelte`, or `SettingsNav.test.ts`, and still exactly 2 for `routes/settings/+page.svelte`. Fix any error this plan introduced before continuing.

- [ ] **Step 2: Run the full test suite**

Run: `npm run test`
Expected: all tests PASS, including the 10 in `SettingsNav.test.ts`.

- [ ] **Step 3: Production build**

Run: `npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 4: Note browser-only checks**

The following are CSS / navigation / interaction behaviors that jsdom cannot evaluate; they are verified in the browser-verification step of `/implement-task`, not by unit tests:
- The 60px ⇄ 232px rail width swap at the 1024px breakpoint, and the toggle appearing only below it.
- Tooltips appearing on the collapsed icon-only rail, anchored to the correct trigger button (confirms the `Tooltip.Trigger` + `child` snippet wiring).
- The non-admin deep-link redirect (`?tab=billing` → `?tab=organization` + toast), firing exactly once.
- No horizontal overflow scroll at any viewport width.

No commit — this task only confirms green state.

---

## Self-Review

**Spec coverage:**
- `settingsSections.ts` data module (spec §"settingsSections.ts") → Task 1.
- `SettingsNav.svelte` rail, groups, items, active card-chip + accent bar, admin marker, `Button` primitive, `<nav aria-label>`, `aria-current` (spec §"SettingsNav.svelte", §"Visual design") → Tasks 2–3.
- Admin filtering — hidden from non-admins (spec §"Admin gating") → Task 2.
- Collapse toggle, 60px/232px responsive width, tooltips, `matchMedia` SSR-safe + cleanup + breakpoint reset, `Tooltip.Provider` (spec §"Responsive behavior") → Task 3.
- `+page.svelte` import swap, derived `SettingsTabId`, `navIsAdmin` synchronous, layout swap, `{#key}` + `fade` content transition (spec §"+page.svelte — wiring") → Task 4.
- Non-admin deep-link guard `$effect` (spec §"Non-admin deep-link guard") → Task 5.
- Test coverage → **10 tests**: 2 data-module (Task 1), 6 component — sections, admin filter, `aria-current`, navigation callback, Admin marker, accessible names (Task 2), and 2 responsive — collapse toggle plus the collapsed-`belowLg` branch (Task 3). The collapsed-branch test is a review-panel addition that closes a "false green" gap (the `matchMedia` stub previously never exercised the tooltip/collapse path).
- The notifications inline `loadChannels()` is dropped with the tab bar; the existing `$effect` covers it (spec §"+page.svelte — wiring") → Task 4 removes the markup; no extra step needed.

**Placeholder scan:** No "TBD"/"TODO"/vague steps — every code step shows complete code; every command shows expected output.

**Type consistency:** `SettingsTabId`, `SettingsSection`, `SECTIONS`, `SETTINGS_TAB_IDS`, `ADMIN_TAB_IDS`, `GROUP_LABELS`, `DEFAULT_TAB` defined in Task 1 and used unchanged in Tasks 2–5. `SettingsNav` props (`activeTab`, `isAdmin`, `onNavigate`) identical in the component (Tasks 2–3) and the call site (Task 4). The `navItem` snippet signature `(section, isActive, triggerProps)` is used consistently in both the tooltip and non-tooltip branches in Task 3.

**Out of scope** (route to `/add_task`, per spec §"Scope boundaries"): ⌘K command palette; projects-page tab bar / shared `VerticalNav` extraction; silent role-load failure; persisting `railExpanded` across reloads.

## Changes from review panel (2026-05-21)

The implementation-plan review panel ran four agents (`adversarial-risk-auditor`, `production-ops-reviewer`, `dry-reuse-auditor`, `uiux-design-reviewer`; `db-scalability-reviewer` skipped — no DB impact). Findings were verified against the codebase before applying. Changes made to the plan:

**Applied — correctness:**
- **Effective-tab split (adversarial H2).** Task 4 now derives `requestedTab` (raw URL value) *and* `activeTab` (effective: a non-admin's admin-only deep link falls back to `DEFAULT_TAB`). Previously a single `activeTab` followed the URL, so a non-admin opening `?tab=billing` would *mount the billing panel*, then the guard `$effect` would redirect — a double `{#key}` fade and a brief admin-panel mount. Now admin panels never mount for non-admins and the transition fires once. Task 5's guard `$effect` correspondingly tests `requestedTab`, not `activeTab` (testing `activeTab` could never be true post-split, making the guard dead code).
- **Type-check baseline (adversarial H6).** The repo is **not** check-clean: `npm run check` reports a baseline of **54 errors / 47 warnings**, including 2 pre-existing errors in `routes/settings/+page.svelte`. Every per-task type-check step replaced its fragile `grep 'error TS'` (which misses Svelte-template errors) with `npm run check` filtered on the reliable `ERROR "<path>"` output format, asserting against the 54-error baseline and a per-file `ERROR`-line count. Task 6 Step 1 corrected from "Expected: 0 errors" to "Expected: `ERRORS 54`."
- **String-anchored edits (adversarial H5).** Task 4 Steps 3–4 edit `+page.svelte` after earlier steps have already shifted its line numbers. Both steps now anchor on unique strings (`<!-- Tabs -->`, `<!-- Organization Tab -->`, the `<ConfirmDialog>` opening) instead of absolute line numbers.
- **Collapsed-branch test (adversarial H3 / production-ops Finding 4).** The `matchMedia` stub only ever returned `matches: false`, so the entire collapse/tooltip code path was never executed in tests (a crash there would pass CI). Task 3 adds a second test that stubs `matches: true` and asserts the collapsed rail renders (group labels `sr-only`, items still reachable). Test total: 9 → 10.

**Applied — UX polish (uiux-design-reviewer):**
- **`prefers-reduced-motion` (blocking #2).** The content-column transition changed from `in:fade={{ duration: 150 }}` (a hardcoded literal that ignores reduced-motion) to `in:fade={{ duration: blockDuration() }}`, matching the eight existing `fade` usages already in `+page.svelte`. `blockDuration()` returns `0` under `prefers-reduced-motion`.
- **Active-state noise.** Dropped `shadow-sm` from the active nav item — the teal accent bar + `bg-card` + `ring-1` already give a clear card-chip; the shadow was a fifth redundant signal on a flat rail.
- **Admin badge legibility.** Removed the `text-[10px]` override (below the theme's smallest type token); the `Badge` primitive's default `text-xs` is used instead.
- **Group-label spacing.** Group-label bottom padding `pb-1` → `pb-2`.

**Verified and rejected (recorded so they are not re-raised):**
- **Roles not synchronous (adversarial B1, "blocker").** *False.* `frontend/src/routes/+layout.svelte` gates all route rendering behind `{#if !isInitialized()}`, and `initialize()` awaits `loadOrgs()` → `refreshCurrentOrgRoles()`. Org roles are fully resolved before the settings route renders, so the spec's synchronous `getCurrentOrgRoles()` admin gate has no pop-in flash. No change.
- **Ghost-variant green hover flash (uiux blocking #1).** *Non-issue.* `cn()` (clsx + tailwind-merge) dedupes conflicting `hover:bg-*` utilities — the nav item's `hover:bg-muted` wins over the ghost variant's `hover:bg-accent`. No change.
- **Icon package — switch to `lucide-svelte` (production-ops Finding 1).** *Rejected.* Both packages are installed, but `@lucide/svelte` is the modern Svelte 5 package, the majority in-repo usage (25 files vs 16), and what the shadcn-svelte primitives themselves import (`dropdown-menu-radio-item.svelte` → `@lucide/svelte/icons/circle`). Both `panel-left-open` and `panel-left-close` exist there. Plan keeps `@lucide/svelte`.
- **Two admin flags (production-ops Finding 3 / dry-reuse).** Kept `navIsAdmin` separate from the existing `isOrgAdmin` rather than consolidating: `isOrgAdmin` derives from the async-loaded `members` list (false until that fetch lands — would pop-in), and re-pointing it at `getCurrentOrgRoles()` would change the Organization tab's self-role-change reactivity — out of scope. Resolved with an explicit explanatory comment at the `navIsAdmin` declaration (Task 4 Step 2).

**Considered, no change:**
- `child`-snippet Tooltip wiring (adversarial H4 / production-ops Finding 2): the `Tooltip.Trigger` + `{#snippet child({ props })}` + `<Button>` composition is the canonical bits-ui v2 pattern — the same `child` mechanism is proven in-repo (`ContextMenu.Trigger` in `UnitOpNode.svelte`), and `<Button>` forwards `...restProps` to its `<button>`. Kept; Task 6 Step 4 adds an explicit browser check that the tooltip anchors correctly.
- `triggerProps: Record<string, unknown>` (dry-reuse, optional): left as-is — bits-ui exposes no cleaner public type for the `child` snippet's `props`.
- Collapse toggle `mt-auto` bottom-anchoring (uiux): `mt-6` kept — bottom-anchoring needs the rail to stretch, which conflicts with the `items-start` content layout for marginal benefit. Browser verification (Task 6 Step 4) confirms placement reads acceptably.

**Routed out of scope (unchanged from spec):** ⌘K command palette, shared `VerticalNav` extraction for the projects page, silent role-load failure handling, persisting `railExpanded` across reloads — all already listed under the plan's Self-Review "Out of scope" and the spec's scope boundaries.
