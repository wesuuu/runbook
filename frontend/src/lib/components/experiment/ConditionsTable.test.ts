import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import ConditionsTable from '$lib/components/experiment/ConditionsTable.svelte';

const runs: any[] = [
    {id: 'r1', name: 'RUN-1', graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 6}}}]}},
    {id: 'r2', name: 'RUN-2', graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 8}}}]}},
];

describe('ConditionsTable', () => {
    it('renders varied rows only by default', () => {
        const { getByText } = render(ConditionsTable, { props: { runs } });
        expect(getByText('Feed')).toBeTruthy();
        expect(getByText('glucose')).toBeTruthy();
    });

    it('first column is sticky', () => {
        const { container } = render(ConditionsTable, { props: { runs } });
        const firstCol = container.querySelector('th.sticky-left');
        expect(firstCol).toBeTruthy();
    });
});
