import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ReviewQueueList from './ReviewQueueList.svelte';
import type { SignoffRequestItem } from '$lib/schemas/signoffRequests';

const runItem: SignoffRequestItem = {
    type: 'run',
    request_id: 'r1',
    target_id: 't1',
    target_name: 'Run Alpha',
    role: 'QAU',
    assigned: false,
    requested_by: null,
    created_at: '2026-05-20T10:00:00Z',
};

describe('ReviewQueueList', () => {
    it('renders rows', () => {
        const { getByText } = render(ReviewQueueList, { props: { items: [runItem] } });
        expect(getByText('Run Alpha')).toBeTruthy();
    });

    it('shows the empty state', () => {
        const { getByText } = render(ReviewQueueList, { props: { items: [] } });
        expect(getByText(/all caught up/i)).toBeTruthy();
    });

    it('marks unassigned QAU rows as pool requests', () => {
        const { getByText } = render(ReviewQueueList, { props: { items: [runItem] } });
        expect(getByText(/any org QAU/i)).toBeTruthy();
    });
});
