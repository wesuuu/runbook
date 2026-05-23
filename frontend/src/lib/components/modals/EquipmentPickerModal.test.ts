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
    { id: 'archived-cached', organization_id: 'o', name: 'Old Lab', is_default: false, archived_at: '2026-01-01', created_at: '', updated_at: '' },
];

describe('EquipmentPickerModal site default', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('uses localStorage site id when present and active', () => {
        localStorage.setItem('f0088:lastSiteId', 'cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
        });
        expect((getByRole('combobox') as HTMLSelectElement).value).toBe('cached');
    });

    it('falls back to is_default when cached site is archived', () => {
        localStorage.setItem('f0088:lastSiteId', 'archived-cached');
        const { getByRole } = render(EquipmentPickerModal, {
            props: { sites, open: true, mode: 'create', onCreateEquipment: vi.fn() },
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

describe('EquipmentPickerModal create form layout', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('pick mode: in-form Discard button renders inside .create-form when expanded', async () => {
        const { getByRole } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await tick();
        // bits-ui Dialog portals into <body>, so query the document.
        const createForm = document.querySelector('.create-form');
        expect(createForm).not.toBeNull();
        const footer = createForm!.querySelector('.create-form-footer');
        expect(footer).not.toBeNull();
        const buttons = Array.from(footer!.querySelectorAll('button'));
        const labels = buttons.map((b) => (b.textContent ?? '').trim().toLowerCase());
        expect(labels).toContain('discard');
        expect(labels.some((l) => l.includes('create equipment'))).toBe(true);
    });

    it('pick mode: "+ Add New Equipment" toggle is hidden while the form is open', async () => {
        const { getByRole, queryByRole } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        const opener = getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement;
        opener.click();
        await tick();
        expect(queryByRole('button', { name: /add new equipment/i })).toBeNull();
        expect(document.querySelector('.create-form')).not.toBeNull();
    });

    it('pick mode: clicking the in-form Discard closes the form and resets fields', async () => {
        const { getByRole, getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await tick();
        const nameInput = getByLabelText(/equipment name/i) as HTMLInputElement;
        nameInput.value = 'Scratch';
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
        await tick();
        const discardBtn = Array.from(document.querySelectorAll('.create-form-footer button'))
            .find((b) => (b.textContent ?? '').trim().toLowerCase() === 'discard') as HTMLButtonElement;
        expect(discardBtn).toBeTruthy();
        discardBtn.click();
        await tick();
        expect(document.querySelector('.create-form')).toBeNull();
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await tick();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });

    it('does not double-scroll: .equipment-list CSS no longer declares overflow-y', () => {
        const styleBlock = modalSource.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const listRule = styleBlock.match(/\.equipment-list\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(listRule).not.toBe('');
        expect(listRule).not.toMatch(/overflow-y\s*:/);
        const modalRule = styleBlock.match(/\.equipment-modal\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(modalRule).toMatch(/overflow-y\s*:\s*auto/);
        expect(modalRule).not.toMatch(/max-height\s*:\s*500px/);
        expect(modalRule).toMatch(/min-height\s*:\s*0/);
    });

    it('pick mode: re-opening the dialog after close resets the create form fields', async () => {
        const { rerender, getByRole, getByLabelText } = render(EquipmentPickerModal, {
            props: {
                sites,
                open: true,
                mode: 'pick',
                orgEquipment: [],
                onCreateEquipment: vi.fn(),
            },
        });
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
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
        (getByRole('button', { name: /add new equipment/i }) as HTMLButtonElement).click();
        await tick();
        const reopened = getByLabelText(/equipment name/i) as HTMLInputElement;
        expect(reopened.value).toBe('');
    });

    it('pick mode: "Go to form" appears in sticky search row only when form is open and out of view', () => {
        const tpl = modalSource;
        expect(tpl).toMatch(/showCreateForm\s*&&\s*!isCreateFormInView/);
        expect(tpl).toMatch(/Go to form/);
        // The sticky "Close form" was removed: the in-form Discard button
        // and the outer dialog Cancel cover that affordance, and a
        // data-loss tap next to a nav tap in the same row was a UX risk.
        expect(tpl).not.toMatch(/Close form/);
    });

    it('create mode: the form footer has only a Create Equipment button (no Discard)', () => {
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
});
