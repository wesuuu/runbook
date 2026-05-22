import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import NotificationRow from './NotificationRow.svelte';
import type { NotificationItem } from '$lib/schemas';

const UUID = '33333333-3333-3333-3333-333333333333';

function makeItem(over: Partial<NotificationItem> = {}): NotificationItem {
    return {
        id: '1',
        user_id: 'u',
        event_type: 'RUN_STARTED',
        entity_type: 'run',
        entity_id: UUID,
        title: 'Run started',
        message: 'CHO-042 started by Alice',
        read_at: null,
        created_at: new Date().toISOString(),
        url: '/acme/projects/p1/runs/cho-042',
        ...over,
    };
}

describe('NotificationRow', () => {
    it('renders an <a> with the deep link when item.url is set', () => {
        const { container } = render(NotificationRow, {
            props: { item: makeItem(), compact: true, onSelect: vi.fn() },
        });
        const link = container.querySelector('a');
        expect(link).not.toBeNull();
        expect(link?.getAttribute('href')).toBe(
            '/acme/projects/p1/runs/cho-042',
        );
    });

    it('renders a <button> when item.url is null', () => {
        const { container } = render(NotificationRow, {
            props: {
                item: makeItem({ url: null }),
                compact: true,
                onSelect: vi.fn(),
            },
        });
        expect(container.querySelector('a')).toBeNull();
        expect(container.querySelector('button')).not.toBeNull();
    });

    it('fires onSelect on click (deep-linkable row)', async () => {
        const onSelect = vi.fn();
        const { getByTestId } = render(NotificationRow, {
            props: { item: makeItem(), compact: false, onSelect },
        });
        await fireEvent.click(getByTestId('notification-row'));
        expect(onSelect).toHaveBeenCalledOnce();
    });

    it('fires onSelect on click (non-linkable row)', async () => {
        const onSelect = vi.fn();
        const { getByTestId } = render(NotificationRow, {
            props: {
                item: makeItem({ url: null }),
                compact: false,
                onSelect,
            },
        });
        await fireEvent.click(getByTestId('notification-row'));
        expect(onSelect).toHaveBeenCalledOnce();
    });

    it('shows the title and message', () => {
        const { getByText } = render(NotificationRow, {
            props: { item: makeItem(), compact: true, onSelect: vi.fn() },
        });
        expect(getByText('Run started')).toBeInTheDocument();
        expect(getByText('CHO-042 started by Alice')).toBeInTheDocument();
    });
});
