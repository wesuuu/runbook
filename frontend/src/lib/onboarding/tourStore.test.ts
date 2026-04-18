import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as api from '$lib/api';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        patch: vi.fn(),
    },
}));

import {
    hydrateTourState,
    isCompleted,
    isDismissed,
    shouldShowDot,
    markCompleted,
    markDismissed,
    resetTourState,
} from './tourStore.svelte';

beforeEach(() => {
    resetTourState();
    vi.clearAllMocks();
});

describe('tourStore', () => {
    it('hydrates from /onboarding/state', async () => {
        (api.api.get as any).mockResolvedValue({
            completed: ['project'],
            dismissed: ['run'],
        });
        await hydrateTourState();

        expect(isCompleted('project')).toBe(true);
        expect(isDismissed('run')).toBe(true);
        expect(isDismissed('project')).toBe(false);
    });

    it('shouldShowDot is true only when neither completed nor dismissed', async () => {
        (api.api.get as any).mockResolvedValue({
            completed: ['project'],
            dismissed: ['run'],
        });
        await hydrateTourState();

        expect(shouldShowDot('project')).toBe(false);
        expect(shouldShowDot('run')).toBe(false);
        expect(shouldShowDot('protocol')).toBe(true);
    });

    it('markCompleted sends PATCH and updates local state', async () => {
        (api.api.patch as any).mockResolvedValue({
            completed: ['protocol'],
            dismissed: [],
        });
        await markCompleted('protocol');

        expect(api.api.patch).toHaveBeenCalledWith(
            '/onboarding/state',
            { segment: 'protocol', status: 'completed' },
        );
        expect(isCompleted('protocol')).toBe(true);
    });

    it('markDismissed sends PATCH and updates local state', async () => {
        (api.api.patch as any).mockResolvedValue({
            completed: [],
            dismissed: ['project'],
        });
        await markDismissed('project');

        expect(isDismissed('project')).toBe(true);
    });
});
