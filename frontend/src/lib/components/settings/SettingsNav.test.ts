import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { SETTINGS_TAB_IDS, ADMIN_TAB_IDS } from './settingsSections';
import SettingsNav from './SettingsNav.svelte';

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
});
