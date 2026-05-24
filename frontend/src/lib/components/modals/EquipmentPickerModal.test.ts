import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { tick } from 'svelte';
import EquipmentPickerModal from './EquipmentPickerModal.svelte';

const __dirname = dirname(fileURLToPath(import.meta.url));
const modalSource = readFileSync(join(__dirname, 'EquipmentPickerModal.svelte'), 'utf8');

const sites = [
    { id: 'default', organization_id: 'o', name: 'Default Site', is_default: true, archived_at: null, created_at: '', updated_at: '' },
    { id: 'cached', organization_id: 'o', name: 'San Diego HQ', is_default: false, archived_at: null, created_at: '', updated_at: '' },
    { id: 'archived-cached', organization_id: 'o', name: 'Old Lab', is_default: false, archived_at: null, created_at: '', updated_at: '' },
];

describe('EquipmentPickerModal site default', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    // Site default tests use mode: 'create' so the form (and its SitePicker
    // combobox) is mounted immediately. In 'pick' mode the create form
    // lives behind the "New equipment" tab and isn't in the DOM at open.
    it('uses localStorage site id when present and active', () => {
        localStorage.setItem('f0088:lastSiteId', 'cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('cached');
    });

    it('falls back to is_default when cached site is archived', () => {
        const archivedSites = [
            { id: 'default', organization_id: 'o', name: 'Default Site', is_default: true, archived_at: null, created_at: '', updated_at: '' },
            { id: 'archived-cached', organization_id: 'o', name: 'Old Lab', is_default: false, archived_at: '2026-01-01', created_at: '', updated_at: '' },
        ];
        localStorage.setItem('f0088:lastSiteId', 'archived-cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites: archivedSites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('default');
    });

    it('falls back to is_default when cached site not in list', () => {
        localStorage.setItem('f0088:lastSiteId', 'unknown');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('default');
    });
});

describe('EquipmentPickerModal tabs (pick mode)', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('opens on Browse tab by default in pick mode', () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        // bits-ui Dialog portals into <body>, so query the document.
        const browseTab = document.querySelector('[role="tab"][aria-selected="true"]');
        expect(browseTab?.textContent?.toLowerCase()).toContain('browse');
    });

    it('clicking the "New equipment" tab swaps to the create form', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        const newTab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
            (t.textContent ?? '').toLowerCase().includes('new equipment'),
        ) as HTMLButtonElement;
        expect(newTab).toBeTruthy();
        newTab.click();
        await tick();
        expect(document.querySelector('.create-form')).not.toBeNull();
        expect(newTab.getAttribute('aria-selected')).toBe('true');
    });

    it('pick mode: Discard in the form returns to Browse and resets fields', async () => {
        const { getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        const newTab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
            (t.textContent ?? '').toLowerCase().includes('new equipment'),
        ) as HTMLButtonElement;
        newTab.click();
        await tick();
        const nameInput = getByLabelText(/equipment name/i) as HTMLInputElement;
        nameInput.value = 'Scratch';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        await tick();

        const discardBtn = Array.from(document.querySelectorAll('.create-form-footer button')).find(
            (b) => (b.textContent ?? '').trim().toLowerCase() === 'discard',
        ) as HTMLButtonElement;
        expect(discardBtn).toBeTruthy();
        discardBtn.click();
        await tick();

        // Back on Browse tab; form is gone.
        expect(document.querySelector('.create-form')).toBeNull();
        const activeTab = document.querySelector('[role="tab"][aria-selected="true"]');
        expect(activeTab?.textContent?.toLowerCase()).toContain('browse');

        // Re-open form; fields are cleared.
        newTab.click();
        await tick();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });

    it('re-opening the dialog after close resets the create form fields', async () => {
        const { rerender, getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        let newTab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
            (t.textContent ?? '').toLowerCase().includes('new equipment'),
        ) as HTMLButtonElement;
        newTab.click();
        await tick();
        const nameInput = getByLabelText(/equipment name/i) as HTMLInputElement;
        nameInput.value = 'Leaked';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        await tick();
        await rerender({
            sites,
            open: false,
            mode: 'pick',
            orgEquipment: [],
            onCreateEquipment: vi.fn(),
        });
        await rerender({
            sites,
            open: true,
            mode: 'pick',
            orgEquipment: [],
            onCreateEquipment: vi.fn(),
        });
        newTab = Array.from(document.querySelectorAll('[role="tab"]')).find((t) =>
            (t.textContent ?? '').toLowerCase().includes('new equipment'),
        ) as HTMLButtonElement;
        newTab.click();
        await tick();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });
});

describe('EquipmentPickerModal create mode', () => {
    it('create mode: the form footer has only a Create equipment button (no Discard)', () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'create',
                onCreateEquipment: vi.fn(),
            },
        });
        const footer = document.querySelector('.create-form-footer');
        expect(footer).not.toBeNull();
        const buttons = Array.from(footer!.querySelectorAll('button'));
        expect(buttons).toHaveLength(1);
        expect((buttons[0].textContent ?? '').trim().toLowerCase()).toMatch(/create equipment/);
    });

    it('create mode: no tabs render (the form is the whole modal)', () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'create',
                onCreateEquipment: vi.fn(),
            },
        });
        expect(document.querySelector('[role="tab"]')).toBeNull();
    });
});

describe('EquipmentPickerModal card grid', () => {
    const baseEquipment = {
        organization_id: 'o',
        created_at: '2026-01-01',
        updated_at: '2026-01-01',
    };

    it('renders one .equipment-item per org equipment', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [
                    { ...baseEquipment, id: 'a', name: 'Centrifuge A' },
                    { ...baseEquipment, id: 'b', name: 'Balance B' },
                ],
                onCreateEquipment: vi.fn(),
            },
        });
        await tick();
        const items = document.querySelectorAll('.equipment-item');
        expect(items.length).toBe(2);
    });

    it('list re-renders when orgEquipment prop changes (parent push after create)', async () => {
        const { rerender } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [{ ...baseEquipment, id: 'a', name: 'Centrifuge A' }],
                onCreateEquipment: vi.fn(),
            },
        });
        expect(document.querySelectorAll('.equipment-item').length).toBe(1);
        await rerender({
            sites,
            open: true,
            mode: 'pick',
            orgEquipment: [
                { ...baseEquipment, id: 'a', name: 'Centrifuge A' },
                { ...baseEquipment, id: 'b', name: 'Balance B' },
            ],
            onCreateEquipment: vi.fn(),
        });
        await tick();
        const names = Array.from(document.querySelectorAll('.equipment-name')).map(
            (n) => (n.textContent ?? '').trim().split(/\s+/)[0],
        );
        expect(names).toContain('Centrifuge');
        expect(names).toContain('Balance');
    });

    it('cards are buttons with .is-selected toggled when picked', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [{ ...baseEquipment, id: 'a', name: 'Centrifuge A' }],
                onCreateEquipment: vi.fn(),
            },
        });
        await tick();
        const card = document.querySelector('.equipment-item') as HTMLButtonElement;
        expect(card.tagName).toBe('BUTTON');
        expect(card.classList.contains('is-selected')).toBe(false);
        card.click();
        await tick();
        expect(card.classList.contains('is-selected')).toBe(true);
    });
});

describe('EquipmentPickerModal selection dock', () => {
    const baseEquipment = {
        organization_id: 'o',
        created_at: '2026-01-01',
        updated_at: '2026-01-01',
    };

    it('hides the dock until something is selected', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [{ ...baseEquipment, id: 'a', name: 'Centrifuge A' }],
                onCreateEquipment: vi.fn(),
            },
        });
        await tick();
        expect(document.querySelector('.dock')).toBeNull();
        (document.querySelector('.equipment-item') as HTMLButtonElement).click();
        await tick();
        expect(document.querySelector('.dock')).not.toBeNull();
    });

    it('removing a selection from the dock clears the card and hides the dock', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [{ ...baseEquipment, id: 'a', name: 'Centrifuge A' }],
                onCreateEquipment: vi.fn(),
            },
        });
        await tick();
        const card = document.querySelector('.equipment-item') as HTMLButtonElement;
        card.click();
        await tick();
        const remove = document.querySelector('.dock-remove') as HTMLButtonElement;
        expect(remove).toBeTruthy();
        remove.click();
        await tick();
        expect(card.classList.contains('is-selected')).toBe(false);
        expect(document.querySelector('.dock')).toBeNull();
    });

    it('ID inputs live in the dock (not in the card row)', async () => {
        render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [{ ...baseEquipment, id: 'a', name: 'Centrifuge A' }],
                onCreateEquipment: vi.fn(),
            },
        });
        await tick();
        (document.querySelector('.equipment-item') as HTMLButtonElement).click();
        await tick();
        // Card has no input inside.
        expect(document.querySelector('.equipment-item input')).toBeNull();
        // Dock has the ID input.
        expect(document.querySelector('.dock-id-input')).not.toBeNull();
    });
});

describe('EquipmentPickerModal Shareable concept hidden', () => {
    // Decision: the shareable concept confused more than it helped, so the
    // toggle and conflict badge are hidden in the picker. The data model is
    // preserved (selections still write shareable=true) so we can re-expose
    // the affordance later without a schema change.
    it('does not render a Shareable toggle anywhere in the source', () => {
        expect(modalSource).not.toMatch(/shareable-label/);
        expect(modalSource).not.toMatch(/shareable-checkbox/);
        expect(modalSource).not.toMatch(/>Shareable</);
    });

    it('does not render the parallel-step Conflict badge', () => {
        // The dock duplicate-ID flag stays (typo guard), but the
        // parallel-step "Conflict" badge is gone.
        expect(modalSource).not.toMatch(/⚠ Conflict</);
        expect(modalSource).not.toMatch(/hasConflict\(/);
    });

    it('defaults shareable to true so existing conflict plumbing stays quiet', () => {
        // toggleEquipment + handleCreate both create new selection state.
        // Both should default shareable: true now.
        const literals = modalSource.match(/shareable:\s*(true|false)/g) ?? [];
        expect(literals.length).toBeGreaterThanOrEqual(2);
        for (const lit of literals) {
            expect(lit).toMatch(/shareable:\s*true/);
        }
    });
});

describe('EquipmentPickerModal layout invariants', () => {
    it('single scroll region: .equipment-modal scrolls, .equipment-list does not', () => {
        const styleBlock = modalSource.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const listRule = styleBlock.match(/\.equipment-list\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(listRule).not.toBe('');
        expect(listRule).not.toMatch(/overflow-y\s*:/);
        const modalRule = styleBlock.match(/\.equipment-modal\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(modalRule).toMatch(/overflow-y\s*:\s*auto/);
        expect(modalRule).toMatch(/min-height\s*:\s*0/);
    });

    it('card grid is 2 columns', () => {
        const styleBlock = modalSource.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const listRule = styleBlock.match(/\.equipment-list\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(listRule).toMatch(/grid-template-columns:\s*1fr\s+1fr/);
    });
});
