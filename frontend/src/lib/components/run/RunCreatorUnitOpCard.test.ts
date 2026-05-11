import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorUnitOpCard from './RunCreatorUnitOpCard.svelte';

const baseNode = () => ({
    id: 'n1',
    type: 'unitOp',
    data: {
        label: 'Buffer Mix',
        category: 'Media Prep',
        params: { temperature: 25 },
        equipment: [{ equipment_id: 'eq-1', shareable: false }],
        paramSchema: {
            type: 'object',
            properties: { temperature: { type: 'number', title: 'Temperature' } },
        },
        description: 'Mix at {{temperature}}°C',
        protocol_params: { temperature: 25 },
        protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
        protocol_paramSchema: {
            type: 'object',
            properties: { temperature: { type: 'number', title: 'Temperature' } },
        },
        protocol_description: 'Mix at {{temperature}}°C',
    },
});

const ORG_EQ = [{ id: 'eq-1', name: 'Bioreactor A' }];

describe('RunCreatorUnitOpCard', () => {
    it('renders UO label and category in the header', () => {
        const { getByText } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set<string>(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        expect(getByText('Buffer Mix')).toBeTruthy();
        expect(getByText(/Media Prep/i)).toBeTruthy();
    });

    it('emits onChange with new param value when input changes', async () => {
        let captured: { data: { params: Record<string, unknown> } } | null = null;
        const { container } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set<string>(),
            onChange: (next: { data: { params: Record<string, unknown> } }) => { captured = next; },
            onSwapEquipment: () => {},
        });
        const input = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: '30' } });
        expect(captured?.data.params.temperature).toBe(30);
    });

    it('shows N overridden badge when params differ from protocol_params', () => {
        const node = baseNode();
        node.data.params.temperature = 30;
        const { getByText } = render(RunCreatorUnitOpCard, {
            node,
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set<string>(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        expect(getByText(/1 overridden/i)).toBeTruthy();
    });

    it('toggles instructions block when ✎ Edit instructions clicked', async () => {
        const { getByText, container } = render(RunCreatorUnitOpCard, {
            node: baseNode(),
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set<string>(),
            onChange: () => {},
            onSwapEquipment: () => {},
        });
        const link = getByText(/Edit instructions/i);
        await fireEvent.click(link);
        const ta = container.querySelector('textarea');
        expect(ta).toBeTruthy();
    });

    it('emits revert (back to protocol_params) when ↺ revert button clicked', async () => {
        const node = baseNode();
        node.data.params.temperature = 30;
        let captured: { data: { params: Record<string, unknown> } } | null = null;
        const { container } = render(RunCreatorUnitOpCard, {
            node,
            mediaPrepNodes: [],
            orgEquipment: ORG_EQ,
            conflictingIds: new Set<string>(),
            onChange: (next: { data: { params: Record<string, unknown> } }) => { captured = next; },
            onSwapEquipment: () => {},
        });
        const revertBtn = container.querySelector('[aria-label="Revert temperature"]') as HTMLButtonElement;
        await fireEvent.click(revertBtn);
        expect(captured?.data.params.temperature).toBe(25);
    });
});
