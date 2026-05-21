import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import RecentActivityWidget from './RecentActivityWidget.svelte';

function activity(id: string) {
    return {
        id,
        action: 'CREATE',
        entity_type: 'Run',
        entity_id: id,
        entity_name: `Run ${id}`,
        actor_name: 'Sam Scientist',
        changes: {},
        created_at: new Date().toISOString(),
    };
}

describe('RecentActivityWidget', () => {
    it('renders the empty state when there is no activity', () => {
        const { getByText } = render(RecentActivityWidget, { props: { activity: [] } });
        expect(getByText('No recent activity')).toBeTruthy();
    });

    it('renders activity rows', () => {
        const { getByText } = render(RecentActivityWidget, {
            props: { activity: [activity('a'), activity('b')] },
        });
        expect(getByText('Run a')).toBeTruthy();
        expect(getByText('Run b')).toBeTruthy();
    });

    it('hard-caps the number of visible rows', () => {
        const items = Array.from({ length: 12 }, (_, i) => activity(String(i)));
        const { container } = render(RecentActivityWidget, {
            props: { activity: items, cap: 6 },
        });
        expect(container.querySelectorAll('a').length).toBe(6);
    });
});
