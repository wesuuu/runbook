import { render, fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('$lib/toast', () => ({
    toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { goto } from '$app/navigation';
import { api } from '$lib/api';
import { toast } from '$lib/toast';
import { load } from './+page';
import NotificationsPage from './+page.svelte';

const UUID = '33333333-3333-3333-3333-333333333333';

function makeItem(over: Record<string, unknown> = {}) {
    return {
        id: '1',
        user_id: 'u',
        event_type: 'RUN_STARTED',
        entity_type: 'run',
        entity_id: UUID,
        title: 'Run started',
        message: 'CHO-042 started',
        read_at: null,
        created_at: new Date().toISOString(),
        url: '/acme/projects/p1/runs/cho-042',
        ...over,
    };
}

describe('/notifications +page.ts load', () => {
    it('reads offset from the URL', () => {
        const data = load({
            url: new URL('http://x/notifications?offset=50'),
        } as Parameters<typeof load>[0]);
        expect(data).toEqual({ offset: 50 });
    });

    it('clamps a missing or invalid offset to 0', () => {
        const a = load({
            url: new URL('http://x/notifications'),
        } as Parameters<typeof load>[0]);
        const b = load({
            url: new URL('http://x/notifications?offset=-9'),
        } as Parameters<typeof load>[0]);
        expect(a).toEqual({ offset: 0 });
        expect(b).toEqual({ offset: 0 });
    });
});

describe('/notifications page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(api.put).mockResolvedValue({});
    });
    it('loads the first page on mount', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 1 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('offset=0'),
            expect.anything(),
        );
        await screen.findByText('Run started');
    });

    it('requests the offset from page data', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [], total: 100 });
        render(NotificationsPage, { props: { data: { offset: 25 } } });
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('offset=25'),
            expect.anything(),
        );
    });

    it('Next navigates to the following offset', async () => {
        vi.mocked(api.get).mockResolvedValue({
            items: [makeItem()],
            total: 100,
        });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByText('Next'));
        expect(goto).toHaveBeenCalledWith(
            '/notifications?offset=25',
            expect.objectContaining({ keepFocus: true, noScroll: true }),
        );
    });

    it('shows the empty state when there are no notifications', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [], total: 0 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('No notifications');
    });

    it('mark all read calls the API and refetches', async () => {
        vi.mocked(api.get).mockResolvedValue({
            items: [makeItem()],
            total: 1,
        });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        const callsBefore = vi.mocked(api.get).mock.calls.length;
        await fireEvent.click(screen.getByText('Mark all read'));
        await tick();
        expect(api.put).toHaveBeenCalledWith('/notifications/read-all', {});
        await vi.waitFor(() => {
            expect(vi.mocked(api.get).mock.calls.length).toBeGreaterThan(
                callsBefore,
            );
        });
    });

    it('marks a row read on select and PUTs to the server', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 1 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByTestId('notification-row'));
        await tick();
        expect(api.put).toHaveBeenCalledWith('/notifications/1/read', {});
    });

    it('rolls back the optimistic read on a failed mark-read', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 1 });
        vi.mocked(api.put).mockRejectedValueOnce(new Error('network'));
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByTestId('notification-row'));
        await vi.waitFor(() => {
            expect(toast.error).toHaveBeenCalled();
        });
        await tick();
        // The single row's read was rolled back, so it is unread again and
        // the "Mark all read" affordance is still shown.
        expect(screen.getByText('Mark all read')).toBeInTheDocument();
    });

    it('Prev navigates to the preceding offset', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 100 });
        render(NotificationsPage, { props: { data: { offset: 50 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByText('Prev'));
        expect(goto).toHaveBeenCalledWith(
            '/notifications?offset=25',
            expect.objectContaining({ keepFocus: true, noScroll: true }),
        );
    });

    it('Prev button is disabled at offset 0', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 100 });
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        expect((screen.getByText('Prev').closest('button'))?.disabled).toBe(true);
    });

    it('toasts an error when loadPage fails', async () => {
        vi.mocked(api.get).mockRejectedValue(new Error('network'));
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
    });

    it('disables Prev/Next while a page fetch is in flight', async () => {
        // First load resolves so the pager renders; the offset-change fetch
        // stays pending so `loading` is true with rows still on screen.
        vi.mocked(api.get)
            .mockResolvedValueOnce({ items: [makeItem()], total: 100 })
            .mockReturnValueOnce(new Promise(() => {}));
        const { rerender } = render(NotificationsPage, {
            props: { data: { offset: 25 } },
        });
        await screen.findByText('Run started');
        await rerender({ data: { offset: 50 } });
        await tick();
        // hasPrev/hasNext are both true at offset 50 of 100 — only the
        // in-flight guard should disable the buttons.
        expect(screen.getByText('Next').closest('button')?.disabled).toBe(true);
        expect(screen.getByText('Prev').closest('button')?.disabled).toBe(true);
    });

    it('disables "Mark all read" while the request is in flight', async () => {
        vi.mocked(api.get).mockResolvedValue({ items: [makeItem()], total: 1 });
        vi.mocked(api.put).mockReturnValueOnce(new Promise(() => {}));
        render(NotificationsPage, { props: { data: { offset: 0 } } });
        await screen.findByText('Run started');
        await fireEvent.click(screen.getByText('Mark all read'));
        await tick();
        expect(
            screen.getByText('Mark all read').closest('button')?.disabled,
        ).toBe(true);
    });
});
