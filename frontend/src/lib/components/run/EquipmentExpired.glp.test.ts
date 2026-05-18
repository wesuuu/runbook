/**
 * Drift test: T2 EQUIPMENT_EXPIRED — frontend preflight.
 *
 * Companion to the pytest integration test
 * (backend/tests/integration/glp/test_equipment_expired_drift.py).
 *
 * Per grilling decision #4, when a GLP-enabled run is linked to Equipment
 * past its ``next_calibration_date`` the Start Run flow MUST surface a
 * ConfirmDialog instead of starting silently. The user's confirmation
 * sends ``confirmed_expired_equipment: True`` to the backend; the run is
 * locked to outcome ``COMPLETED_WITH_DEVIATIONS`` at start.
 *
 * Today neither the backend predicate nor the frontend ConfirmDialog
 * exists in this branch — see the xfail in the companion pytest and the
 * DONE report for Task 41a. This test exercises the *predicate* a future
 * implementation must follow so we have a green guardrail to attach the
 * dialog logic to when it lands.
 */

import { describe, it, expect } from 'vitest';

interface LinkedEquipment {
    id: string;
    name: string;
    next_calibration_date: string | null;
}

type ExpiryState = 'fresh' | 'imminent' | 'expired';

function equipmentExpiryState(
    eq: LinkedEquipment,
    today: Date = new Date(),
): ExpiryState {
    if (!eq.next_calibration_date) return 'fresh';
    const due = new Date(eq.next_calibration_date);
    const msPerDay = 24 * 60 * 60 * 1000;
    const daysUntil = Math.floor(
        (due.getTime() - today.getTime()) / msPerDay,
    );
    if (daysUntil < 0) return 'expired';
    if (daysUntil <= 14) return 'imminent';
    return 'fresh';
}

function startBlockedByEquipment(
    linkedEquipment: LinkedEquipment[],
    glpEnabled: boolean,
    today: Date = new Date(),
): { confirmRequired: boolean; expiredNames: string[] } {
    if (!glpEnabled) return { confirmRequired: false, expiredNames: [] };
    const expired = linkedEquipment.filter(
        (eq) => equipmentExpiryState(eq, today) === 'expired',
    );
    return {
        confirmRequired: expired.length > 0,
        expiredNames: expired.map((e) => e.name),
    };
}

describe('GLP drift: EQUIPMENT_EXPIRED preflight', () => {
    const today = new Date('2026-05-18T00:00:00Z');

    const fresh: LinkedEquipment = {
        id: 'eq-fresh',
        name: 'Fresh Balance',
        next_calibration_date: '2026-11-15',
    };
    const imminent: LinkedEquipment = {
        id: 'eq-imminent',
        name: 'Imminent pH Meter',
        next_calibration_date: '2026-05-25',
    };
    const expired: LinkedEquipment = {
        id: 'eq-expired',
        name: 'Expired Bioreactor',
        next_calibration_date: '2026-04-18',
    };

    it('classifies fresh / imminent / expired correctly', () => {
        expect(equipmentExpiryState(fresh, today)).toBe('fresh');
        expect(equipmentExpiryState(imminent, today)).toBe('imminent');
        expect(equipmentExpiryState(expired, today)).toBe('expired');
    });

    it('requires ConfirmDialog when GLP run links expired equipment', () => {
        const r = startBlockedByEquipment([fresh, expired], true, today);
        expect(r.confirmRequired).toBe(true);
        expect(r.expiredNames).toEqual(['Expired Bioreactor']);
    });

    it('does NOT require ConfirmDialog for imminent-only (banner is T3)', () => {
        const r = startBlockedByEquipment([fresh, imminent], true, today);
        expect(r.confirmRequired).toBe(false);
        expect(r.expiredNames).toEqual([]);
    });

    it('ignores equipment expiry when GLP is disabled', () => {
        const r = startBlockedByEquipment([expired], false, today);
        expect(r.confirmRequired).toBe(false);
        expect(r.expiredNames).toEqual([]);
    });

    it('passes when no equipment is linked', () => {
        const r = startBlockedByEquipment([], true, today);
        expect(r.confirmRequired).toBe(false);
    });
});
