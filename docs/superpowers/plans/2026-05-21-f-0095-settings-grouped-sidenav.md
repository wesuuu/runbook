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

Run: `npx svelte-check --tsconfig ./tsconfig.json --threshold error 2>&1 | grep -E 'settingsSections|error' | head`
Expected: no error referencing `settingsSections.ts`.
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
                    class="px-3 pb-1 font-mono text-xs uppercase tracking-wider text-muted-foreground"
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
                                'bg-card text-foreground font-semibold shadow-sm ring-1 ring-border',
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
                            <Badge variant="outline" class="text-[10px]">
                                Admin
                            </Badge>
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

- [ ] **Step 1: Write the failing test for the collapse toggle**

In `frontend/src/lib/components/settings/SettingsNav.test.ts`, add a `matchMedia` stub and the toggle test. Add `beforeEach`/`afterEach` to the vitest import, and insert the `beforeEach`/`afterEach` and the new `it` block **inside** the existing `describe('SettingsNav', ...)`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
```

```ts
    // jsdom has no matchMedia; SettingsNav reads it in onMount.
    beforeEach(() => {
        vi.stubGlobal(
            'matchMedia',
            vi.fn((query: string) => ({
                matches: false,
                media: query,
                onchange: null,
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                addListener: vi.fn(),
                removeListener: vi.fn(),
                dispatchEvent: vi.fn(),
            })),
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
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `npx vitest run src/lib/components/settings/SettingsNav.test.ts`
Expected: FAIL — `Unable to find a label with the text of: Expand navigation`. The 8 prior tests still PASS.

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
                'bg-card text-foreground font-semibold shadow-sm ring-1 ring-border',
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
                class={cn('text-[10px]', !railExpanded && 'hidden lg:inline-flex')}
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
                            'px-3 pb-1 font-mono text-xs uppercase tracking-wider text-muted-foreground',
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
Expected: PASS — 9 tests.

- [ ] **Step 5: Type-check the component**

Run: `npx svelte-check --tsconfig ./tsconfig.json --threshold error 2>&1 | grep -E 'SettingsNav|error TS' | head`
Expected: no error referencing `SettingsNav.svelte`. If the `Tooltip.Trigger` `child` snippet errors, confirm `props` is destructured as `{#snippet child({ props })}` and that the snippet spreads `triggerProps` onto `<Button>`.

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

Replace the current block (lines 36–46):

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
    const activeTab = $derived.by<SettingsTabId>(() => {
        const t = $page.url.searchParams.get('tab');
        return SETTINGS_TAB_IDS.includes(t as SettingsTabId)
            ? (t as SettingsTabId)
            : DEFAULT_TAB;
    });

    function setTab(tab: SettingsTabId) {
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }

    // Synchronous: org roles resolve during auth init, before this route
    // renders, so admin items never pop in or out on first paint.
    const navIsAdmin = $derived(getCurrentOrgRoles().includes('ADMIN'));
```

- [ ] **Step 3: Replace the tab-bar markup and open the content column**

Replace the `<!-- Tabs -->` block (lines 802–884 — the comment plus the entire `<div class="flex border-b border-border overflow-x-auto"> … </div>`) with:

```svelte
    <div class="flex gap-6 lg:gap-8 items-start">
        <SettingsNav {activeTab} isAdmin={navIsAdmin} onNavigate={setTab} />
        {#key activeTab}
            <div class="flex-1 min-w-0" in:fade={{ duration: 150 }}>
```

Leave the `<!-- Organization Tab -->` comment and everything from `{#if activeTab === 'organization'}` onward exactly as-is.

- [ ] **Step 4: Close the content column, key block, and flex wrapper**

The panels currently end with `{/if}` (line 1520) followed by `</div>` (line 1521, which closes `max-w-6xl`). Change that closing region from:

```svelte
    {/if}
</div>
```

to:

```svelte
    {/if}
            </div>
        {/key}
    </div>
</div>
```

This closes, in order: the content column, the `{#key}` block, the `flex gap-6` wrapper, and the original `max-w-6xl` container.

- [ ] **Step 5: Type-check and confirm the page compiles**

Run: `npx svelte-check --tsconfig ./tsconfig.json --threshold error 2>&1 | grep -E 'settings/\+page|error TS' | head`
Expected: no error referencing `routes/settings/+page.svelte`. If `TabName` is still referenced anywhere in the file, replace each remaining `TabName` with `SettingsTabId` (the type is structurally identical).

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

In `frontend/src/routes/settings/+page.svelte`, immediately after the existing notifications auto-load `$effect` (the block ending at line ~793, just before `</script>`), add:

```ts
    // Non-admin deep-link guard: admin-only sections are hidden from the nav,
    // so a non-admin who deep-links to one (e.g. ?tab=billing) would see a
    // panel with no active nav item. Redirect them to the default tab.
    // The roles-length check prevents a false redirect before roles resolve.
    $effect(() => {
        if (
            getCurrentOrgRoles().length > 0 &&
            !navIsAdmin &&
            ADMIN_TAB_IDS.includes(activeTab)
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

`getCurrentOrgRoles`, `navIsAdmin`, `ADMIN_TAB_IDS`, `activeTab`, `goto`, and `toast` are all already imported/declared from Task 4 and the existing file.

- [ ] **Step 2: Type-check**

Run: `npx svelte-check --tsconfig ./tsconfig.json --threshold error 2>&1 | grep -E 'settings/\+page|error TS' | head`
Expected: no error referencing `routes/settings/+page.svelte`.

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

Run: `npm run check`
Expected: 0 errors. Fix any error this plan introduced before continuing.

- [ ] **Step 2: Run the full test suite**

Run: `npm run test`
Expected: all tests PASS, including the 9 in `SettingsNav.test.ts`.

- [ ] **Step 3: Production build**

Run: `npm run build`
Expected: build succeeds with no errors.

- [ ] **Step 4: Note browser-only checks**

The following are CSS / navigation behaviors that jsdom cannot evaluate; they are verified in the browser-verification step of `/implement-task`, not by unit tests:
- The 60px ⇄ 232px rail width swap at the 1024px breakpoint, and the toggle appearing only below it.
- Tooltips appearing on the collapsed icon-only rail.
- The non-admin deep-link redirect (`?tab=billing` → `?tab=organization` + toast).
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
- All 8 spec test cases → Tasks 1–3 (tests 1–5,7 in Task 2; test 6 in Task 3; test 8 in Task 1).
- The notifications inline `loadChannels()` is dropped with the tab bar; the existing `$effect` covers it (spec §"+page.svelte — wiring") → Task 4 removes the markup; no extra step needed.

**Placeholder scan:** No "TBD"/"TODO"/vague steps — every code step shows complete code; every command shows expected output.

**Type consistency:** `SettingsTabId`, `SettingsSection`, `SECTIONS`, `SETTINGS_TAB_IDS`, `ADMIN_TAB_IDS`, `GROUP_LABELS`, `DEFAULT_TAB` defined in Task 1 and used unchanged in Tasks 2–5. `SettingsNav` props (`activeTab`, `isAdmin`, `onNavigate`) identical in the component (Tasks 2–3) and the call site (Task 4). The `navItem` snippet signature `(section, isActive, triggerProps)` is used consistently in both the tooltip and non-tooltip branches in Task 3.

**Out of scope** (route to `/add_task`, per spec §"Scope boundaries"): ⌘K command palette; projects-page tab bar / shared `VerticalNav` extraction; silent role-load failure; persisting `railExpanded` across reloads.

## Changes from review panel (2026-05-21)

_To be appended after the implementation-plan review panel runs._
