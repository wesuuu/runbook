import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunOverridesEditor from './RunOverridesEditor.svelte';

const flatGraph = () => ({
    nodes: [
        {
            id: 'n1', type: 'unitOp',
            data: {
                label: 'Buffer Mix', category: 'Media Prep',
                params: { temperature: 25 },
                equipment: [{ equipment_id: 'eq-1', shareable: false }],
                paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                description: 'Mix at {{temperature}}',
                protocol_params: { temperature: 25 },
                protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                protocol_paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                protocol_description: 'Mix at {{temperature}}',
            },
        },
        {
            id: 'n2', type: 'unitOp',
            data: {
                label: 'Centrifugation', category: 'Reaction',
                params: { rpm: 4000 },
                equipment: [],
                paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                description: 'Spin at {{rpm}} rpm',
                protocol_params: { rpm: 4000 },
                protocol_equipment: [],
                protocol_paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                protocol_description: 'Spin at {{rpm}} rpm',
            },
        },
    ],
    edges: [],
});

const multiRoleGraph = () => ({
    nodes: [
        { id: 'lane-op',  type: 'swimLane', data: { label: 'Operator',        roleId: 'role-op'  } },
        { id: 'lane-sup', type: 'swimLane', data: { label: 'Senior Operator', roleId: 'role-sup' } },
        {
            id: 'n1', type: 'unitOp', parentId: 'lane-op',
            data: {
                label: 'Buffer Mix', category: 'Media Prep',
                params: { temperature: 25 },
                equipment: [{ equipment_id: 'eq-1', shareable: false }],
                paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                description: 'Mix at {{temperature}}',
                protocol_params: { temperature: 25 },
                protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                protocol_paramSchema: { type: 'object', properties: { temperature: { type: 'number', title: 'Temp' } } },
                protocol_description: 'Mix at {{temperature}}',
            },
        },
        {
            id: 'n2', type: 'unitOp', parentId: 'lane-sup',
            data: {
                label: 'Centrifugation', category: 'Reaction',
                params: { rpm: 4000 },
                equipment: [],
                paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                description: 'Spin at {{rpm}} rpm',
                protocol_params: { rpm: 4000 },
                protocol_equipment: [],
                protocol_paramSchema: { type: 'object', properties: { rpm: { type: 'integer', title: 'RPM' } } },
                protocol_description: 'Spin at {{rpm}} rpm',
            },
        },
    ],
    edges: [],
});

const opRole  = { id: 'role-op',  protocol_id: 'p1', name: 'Operator',        color: '#B96B17', sort_order: 0 };
const supRole = { id: 'role-sup', protocol_id: 'p1', name: 'Senior Operator', color: '#5C6BC0', sort_order: 1 };

describe('RunOverridesEditor — single-role / no-role (degenerate)', () => {
    it('renders one card per unit-op node, ignoring swimLanes', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        const cards = container.querySelectorAll('article.uo-card');
        expect(cards.length).toBe(2);
    });

    it('does NOT render the role context bar when roles.length <= 1', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(container.querySelector('.role-context')).toBeNull();
    });

    it('renders a flat (ungrouped) diff list in the aside when no roles', () => {
        const orig = flatGraph();
        const curr = flatGraph();
        curr.nodes[0].data.params.temperature = 30;
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(container.querySelector('.role-group')).toBeNull();
    });

    it('emits onChange with patched graph when a card edits a param', async () => {
        let captured: { nodes: Array<{ data: { params: Record<string, unknown> } }> } | null = null;
        const { container } = render(RunOverridesEditor, {
            originalGraph: flatGraph(),
            currentGraph: flatGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: (next: { nodes: Array<{ data: { params: Record<string, unknown> } }> }) => { captured = next; },
            onRoleChange: () => {},
        });
        const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(numberInput, { target: { value: '30' } });
        expect(captured?.nodes[0].data.params.temperature).toBe(30);
    });

    it('shows live stat tiles in the aside', () => {
        const orig = flatGraph();
        const curr = flatGraph();
        curr.nodes[0].data.params.temperature = 30;
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        const labels = Array.from(container.querySelectorAll('.stats .stat-lbl')).map((el) => el.textContent);
        expect(labels).toContain('Value');
        expect(labels).toContain('Equipment');
    });

    it('renders empty state when graph has no unit ops', () => {
        const { getByText } = render(RunOverridesEditor, {
            originalGraph: { nodes: [], edges: [] },
            currentGraph: { nodes: [], edges: [] },
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [],
            activeRoleId: null,
            onChange: () => {},
            onRoleChange: () => {},
        });
        expect(getByText(/no unit ops/i)).toBeTruthy();
    });
});

describe('RunOverridesEditor — multi-role', () => {
    it('renders the role context bar with active role name + position', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const ctx = container.querySelector('.role-context');
        expect(ctx).not.toBeNull();
        expect(ctx?.querySelector('.rc-name')?.textContent).toBe('Operator');
        expect(ctx?.querySelector('.pos')?.textContent).toBe('1 / 2');
    });

    it('filters cards to only the active role', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const cards = container.querySelectorAll('article.uo-card');
        expect(cards.length).toBe(1);
    });

    it('arrow nav next/prev calls onRoleChange with the adjacent role', async () => {
        let nextRole: string | null = null;
        const { getByLabelText } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: (id: string) => { nextRole = id; },
        });
        await fireEvent.click(getByLabelText('Next role'));
        expect(nextRole).toBe('role-sup');
    });

    it('clicking an aside role-group head sets the active role', async () => {
        let nextRole: string | null = null;
        const orig = multiRoleGraph();
        const curr = multiRoleGraph();
        const target = curr.nodes.find((n) => n.id === 'n2');
        if (target) (target.data as { params: Record<string, number> }).params.rpm = 4500;
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: (id: string) => { nextRole = id; },
        });
        const supHead = Array.from(
            container.querySelectorAll<HTMLButtonElement>('.role-group-head'),
        ).find((b) => b.textContent?.includes('Senior Operator'));
        expect(supHead).toBeTruthy();
        await fireEvent.click(supHead!);
        expect(nextRole).toBe('role-sup');
    });

    it('aside is global — shows edits from BOTH the active role and inactive roles', () => {
        const orig = multiRoleGraph();
        const curr = multiRoleGraph();
        const n1 = curr.nodes.find((n) => n.id === 'n1');
        const n2 = curr.nodes.find((n) => n.id === 'n2');
        if (n1) (n1.data as { params: Record<string, number> }).params.temperature = 30;
        if (n2) (n2.data as { params: Record<string, number> }).params.rpm = 4500;
        const { container } = render(RunOverridesEditor, {
            originalGraph: orig,
            currentGraph: curr,
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-op',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const heads = container.querySelectorAll('.role-group-head');
        expect(heads.length).toBe(2);
    });

    it('marks the active role-group head with .active', () => {
        const { container } = render(RunOverridesEditor, {
            originalGraph: multiRoleGraph(),
            currentGraph: multiRoleGraph(),
            orgEquipment: [],
            mediaPrepNodes: [],
            roles: [opRole, supRole],
            activeRoleId: 'role-sup',
            onChange: () => {},
            onRoleChange: () => {},
        });
        const active = container.querySelector('.role-group-head.active');
        expect(active?.textContent).toContain('Senior Operator');
    });
});
