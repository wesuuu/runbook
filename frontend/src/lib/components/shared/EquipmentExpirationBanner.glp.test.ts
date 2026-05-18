/**
 * Drift test: T3 equipment expiration banner.
 *
 * Per the GLP rule validation tiers table, an always-visible banner
 * renders on RunDetail when any linked equipment is in the IMMINENT
 * (< 14 days) or EXPIRED bucket. Pure derivation off the linked-equipment
 * list and "today".
 *
 * The banner component does not yet exist on this branch. This test
 * encodes the predicate the surface must follow when added so the
 * imminent / expired thresholds match the backend (see
 * ``conftest.py::imminent_equipment`` / ``expired_equipment``).
 */

import { describe, it, expect } from 'vitest';

interface LinkedEquipment {
    id: string;
    name: string;
    next_calibration_date: string | null;
}

type BannerLevel = 'none' | 'imminent' | 'expired';

function bannerLevelFor(
    linked: LinkedEquipment[],
    today: Date,
): BannerLevel {
    const msPerDay = 24 * 60 * 60 * 1000;
    let anyImminent = false;
    for (const eq of linked) {
        if (!eq.next_calibration_date) continue;
        const due = new Date(eq.next_calibration_date);
        const daysUntil = Math.floor(
            (due.getTime() - today.getTime()) / msPerDay,
        );
        if (daysUntil < 0) return 'expired'; // expired wins
        if (daysUntil <= 14) anyImminent = true;
    }
    return anyImminent ? 'imminent' : 'none';
}

describe('GLP drift: equipment expiration banner predicate', () => {
    const today = new Date('2026-05-18T00:00:00Z');

    it('returns none when only fresh equipment is linked', () => {
        const linked: LinkedEquipment[] = [
            {
                id: '1',
                name: 'Fresh Balance',
                next_calibration_date: '2026-11-15',
            },
        ];
        expect(bannerLevelFor(linked, today)).toBe('none');
    });

    it('returns imminent when any linked equipment is within 14 days', () => {
        const linked: LinkedEquipment[] = [
            {
                id: '1',
                name: 'Fresh Balance',
                next_calibration_date: '2026-11-15',
            },
            {
                id: '2',
                name: 'Imminent pH Meter',
                next_calibration_date: '2026-05-25',
            },
        ];
        expect(bannerLevelFor(linked, today)).toBe('imminent');
    });

    it('returns expired when any linked equipment is past due', () => {
        const linked: LinkedEquipment[] = [
            {
                id: '1',
                name: 'Imminent pH Meter',
                next_calibration_date: '2026-05-25',
            },
            {
                id: '2',
                name: 'Expired Bioreactor',
                next_calibration_date: '2026-04-18',
            },
        ];
        expect(bannerLevelFor(linked, today)).toBe('expired');
    });

    it('returns none when no linked equipment provides a date', () => {
        const linked: LinkedEquipment[] = [
            { id: '1', name: 'Stub', next_calibration_date: null },
        ];
        expect(bannerLevelFor(linked, today)).toBe('none');
    });

    it('returns none when nothing is linked', () => {
        expect(bannerLevelFor([], today)).toBe('none');
    });
});
