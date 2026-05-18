import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import EquipmentPickerModal from './EquipmentPickerModal.svelte';

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
