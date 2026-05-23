import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import KeyResultsChart from '$lib/components/experiment/KeyResultsChart.svelte';

const runs: any[] = [
    {id: 'r1', name: 'RUN-1', key_result_value: 4.2,
     graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 6}}}]}},
    {id: 'r2', name: 'RUN-2', key_result_value: 5.0,
     graph: {nodes: [{type: 'unitOp', data: {label: 'Feed', params: {glucose: 8}}}]}},
];

describe('KeyResultsChart', () => {
    it('renders one circle per run with key_result_value', () => {
        const { container } = render(KeyResultsChart, { props: { runs, experimentId: 'e1' } });
        expect(container.querySelectorAll('circle').length).toBe(2);
    });

    it('best run has accent class', () => {
        const { container } = render(KeyResultsChart, { props: { runs, experimentId: 'e1' } });
        expect(container.querySelector('circle.best')).toBeTruthy();
    });

    it('each circle has a <title> for tap-to-identify', () => {
        const { container } = render(KeyResultsChart, { props: { runs, experimentId: 'e1' } });
        const titles = container.querySelectorAll('circle title');
        expect(titles.length).toBe(2);
    });
});
