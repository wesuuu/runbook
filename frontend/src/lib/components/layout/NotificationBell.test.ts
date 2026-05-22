import { render, fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/auth.svelte', () => ({ isAuthenticated: () => true }));
vi.mock('$lib/api', () => ({ api: { get: vi.fn(), put: vi.fn() } }));
vi.mock('$lib/toast', () => ({
    toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import { api } from '$lib/api';
import { toast } from '$lib/toast';
import NotificationBell from './NotificationBell.svelte';

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

/** Default api.get mock: branches on the endpoint. */
function mockApi(opts: {
    count?: number;
    items?: ReturnType<typeof makeItem>[];
} = {}) {
    vi.mocked(api.get).mockImplementation((endpoint: string) => {
        if (endpoint.includes('unread-count')) {
            return Promise.resolve({ count: opts.count ?? 0 });
        }
        return Promise.resolve({ items: opts.items ?? [], total: 0 });
    });
}

function deferred<T>() {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => {
        resolve = r;
    });
    return { promise, resolve };
}

describe('NotificationBell', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers();
        vi.mocked(api.put).mockResolvedValue({});
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('renders the unread badge from unread-count', async () => {
        mockApi({ count: 4 });
        render(NotificationBell);
        await vi.waitFor(() => {
            expect(screen.getByText('4')).toBeInTheDocument();
        });
    });

    it('fetches the list when the dropdown opens', async () => {
        mockApi({ count: 0, items: [makeItem()] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        expect(api.get).toHaveBeenCalledWith(
            expect.stringContaining('/notifications/?limit=20'),
            expect.anything(),
        );
    });

    it('refetches list and count on a poll tick while open', async () => {
        mockApi({ count: 0, items: [makeItem()] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        const before = vi.mocked(api.get).mock.calls.length;
        await vi.advanceTimersByTimeAsync(30000);
        const after = vi.mocked(api.get).mock.calls.length;
        // count + list = 2 more calls
        expect(after).toBeGreaterThanOrEqual(before + 2);
    });

    it('does not toast when a background count-poll fails', async () => {
        vi.mocked(api.get).mockRejectedValue(new Error('network'));
        render(NotificationBell);
        await vi.advanceTimersByTimeAsync(30000);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('toasts when opening the dropdown fails', async () => {
        vi.mocked(api.get).mockRejectedValue(new Error('network'));
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await vi.waitFor(() => {
            expect(toast.error).toHaveBeenCalled();
        });
    });

    it('ignores a stale (out-of-sequence) list response', async () => {
        const first = deferred<unknown>();
        const second = deferred<unknown>();
        let listCall = 0;
        vi.mocked(api.get).mockImplementation((endpoint: string) => {
            if (endpoint.includes('unread-count')) {
                return Promise.resolve({ count: 0 });
            }
            listCall += 1;
            return listCall === 1 ? first.promise : second.promise;
        });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications')); // list #1
        await tick();
        await vi.advanceTimersByTimeAsync(30000); // list #2
        // newer response lands first
        second.resolve({ items: [makeItem({ id: 'n', title: 'Newer' })], total: 0 });
        await tick();
        // older response lands last — must be discarded
        first.resolve({ items: [makeItem({ id: 'o', title: 'Older' })], total: 0 });
        await tick();
        expect(screen.getByText('Newer')).toBeInTheDocument();
        expect(screen.queryByText('Older')).not.toBeInTheDocument();
    });

    it('marks all read and clears the badge', async () => {
        mockApi({ count: 2, items: [makeItem(), makeItem({ id: '2' })] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        await fireEvent.click(screen.getByText('Mark all read'));
        await tick();
        expect(api.put).toHaveBeenCalledWith('/notifications/read-all', {});
    });

    it('marks a row read on select and PUTs to the server', async () => {
        const item = makeItem();
        mockApi({ count: 1, items: [item] });
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        await fireEvent.click(screen.getByTestId('notification-row'));
        await tick();
        expect(api.put).toHaveBeenCalledWith(`/notifications/${item.id}/read`, {});
    });

    it('rolls back the optimistic read on a failed mark-read', async () => {
        const item = makeItem();
        mockApi({ count: 1, items: [item] });
        vi.mocked(api.put).mockRejectedValueOnce(new Error('network'));
        render(NotificationBell);
        await vi.waitFor(() => {
            expect(screen.getByText('1')).toBeInTheDocument();
        });
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        await fireEvent.click(screen.getByTestId('notification-row'));
        await vi.waitFor(() => {
            expect(toast.error).toHaveBeenCalled();
        });
        expect(screen.getByText('1')).toBeInTheDocument();
    });

    it('rolls back mark-all-read when the server rejects', async () => {
        mockApi({ count: 2, items: [makeItem(), makeItem({ id: '2' })] });
        vi.mocked(api.put).mockRejectedValueOnce(new Error('network'));
        render(NotificationBell);
        await fireEvent.click(screen.getByLabelText('Notifications'));
        await tick();
        await fireEvent.click(screen.getByText('Mark all read'));
        await vi.waitFor(() => {
            expect(toast.error).toHaveBeenCalled();
        });
        expect(screen.getByText('2')).toBeInTheDocument();
    });
});
