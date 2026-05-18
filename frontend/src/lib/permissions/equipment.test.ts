import { describe, expect, it } from 'vitest';
import { canManageEquipmentLifecycle } from './equipment';

const SITE_A = 'aaaaaaaa-0000-0000-0000-000000000001';
const SITE_B = 'bbbbbbbb-0000-0000-0000-000000000002';

describe('canManageEquipmentLifecycle', () => {
    it('admin bypasses grant check', () => {
        expect(canManageEquipmentLifecycle({roles: ['ADMIN'], managedSiteIds: [], siteId: SITE_A})).toBe(true);
    });
    it('site_manager with grant on this site returns true', () => {
        expect(canManageEquipmentLifecycle({roles: ['MEMBER', 'SITE_MANAGER'], managedSiteIds: [SITE_A], siteId: SITE_A})).toBe(true);
    });
    it('site_manager without grant on this site returns false', () => {
        expect(canManageEquipmentLifecycle({roles: ['MEMBER', 'SITE_MANAGER'], managedSiteIds: [SITE_B], siteId: SITE_A})).toBe(false);
    });
    it('member without site_manager bit returns false', () => {
        expect(canManageEquipmentLifecycle({roles: ['MEMBER'], managedSiteIds: [SITE_A], siteId: SITE_A})).toBe(false);
    });
});
