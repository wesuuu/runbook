import { describe, it, expect } from 'vitest';
import { SETTINGS_TAB_IDS, ADMIN_TAB_IDS } from './settingsSections';

describe('settingsSections data module', () => {
    it('exposes all 10 tab ids in display order', () => {
        expect([...SETTINGS_TAB_IDS]).toEqual([
            'organization',
            'teams',
            'sites',
            'ai',
            'templates',
            'billing',
            'profile',
            'appearance',
            'notifications',
            'legal',
        ]);
    });

    it('marks exactly AI Models, Templates and Billing as admin-only', () => {
        expect([...ADMIN_TAB_IDS]).toEqual(['ai', 'templates', 'billing']);
    });
});
