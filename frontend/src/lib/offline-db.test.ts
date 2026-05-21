import { describe, it, expect } from 'vitest';
import { OFFLINE_ENABLED } from './feature-flags';
import { getOrphanedActions, getUnsyncedCount } from './offline-db';

// These tests cover the offline-disabled path. VITE_OFFLINE_ENABLED is unset
// under vitest, so OFFLINE_ENABLED is false — the dashboard must read an
// empty queue without opening (or warning about) the disabled IndexedDB (#6).
describe('offline-db with offline mode disabled', () => {
    it('OFFLINE_ENABLED is false in the test environment', () => {
        expect(OFFLINE_ENABLED).toBe(false);
    });

    it('getOrphanedActions resolves to an empty map, not a rejection (#6)', async () => {
        const grouped = await getOrphanedActions();
        expect(grouped).toBeInstanceOf(Map);
        expect(grouped.size).toBe(0);
    });

    it('getUnsyncedCount resolves to zero, not a rejection (#6)', async () => {
        await expect(getUnsyncedCount()).resolves.toBe(0);
    });
});
