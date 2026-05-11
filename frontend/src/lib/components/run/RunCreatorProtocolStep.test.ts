import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorProtocolStep from './RunCreatorProtocolStep.svelte';

const PROTOCOLS = [
    { id: 'p1', name: 'Mab-A', status: 'PUBLISHED', version_number: 3 },
    { id: 'p2', name: 'Mab-B Archived', status: 'ARCHIVED', version_number: 1 },
];

const VERSIONS_P1 = [
    {
        id: 'v3', protocol_id: 'p1', version_number: 3, name: 'Mab-A',
        description: 'Tightened pH window', change_summary: null,
        created_by_name: 'Wesley', created_at: '2026-04-15T00:00:00Z', is_draft: false,
        graph: { nodes: [], edges: [] },
    },
    {
        id: 'v2', protocol_id: 'p1', version_number: 2, name: 'Mab-A',
        description: null, change_summary: null,
        created_by_name: 'Alice', created_at: '2026-04-01T00:00:00Z', is_draft: false,
        graph: { nodes: [], edges: [] },
    },
];

describe('RunCreatorProtocolStep', () => {
    it('hides archived protocols from the dropdown', () => {
        const { container } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: () => {},
        });
        const opts = Array.from(container.querySelectorAll('option')).map((o) => o.textContent);
        expect(opts.some((l) => l?.includes('Archived'))).toBe(false);
    });

    it('emits onValidate(false) when no protocol selected', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: (v: boolean) => { lastValid = v; },
            onLoadVersions: () => {},
        });
        expect(lastValid).toBe(false);
    });

    it('calls onLoadVersions when protocolId changes', async () => {
        let loaded: string | null = null;
        const { container } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: null,
            protocolVersionNumber: null,
            versions: [],
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: (id: string) => { loaded = id; },
        });
        const sel = container.querySelector('select') as HTMLSelectElement;
        await fireEvent.change(sel, { target: { value: 'p1' } });
        expect(loaded).toBe('p1');
    });

    it('renders summary card showing latest pill when version is null', () => {
        const { container } = render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: 'p1',
            protocolVersionNumber: null,
            versions: VERSIONS_P1,
            loadingVersions: false,
            onChange: () => {},
            onValidate: () => {},
            onLoadVersions: () => {},
        });
        const card = container.querySelector('.version-card');
        expect(card).toBeTruthy();
        expect(card?.textContent).toMatch(/v3/);
        expect(card?.textContent).toMatch(/LATEST/i);
    });

    it('emits onValidate(true) when both protocol and version-or-latest are set', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorProtocolStep, {
            protocols: PROTOCOLS,
            protocolId: 'p1',
            protocolVersionNumber: null,
            versions: VERSIONS_P1,
            loadingVersions: false,
            onChange: () => {},
            onValidate: (v: boolean) => { lastValid = v; },
            onLoadVersions: () => {},
        });
        expect(lastValid).toBe(true);
    });
});
