import { describe, it, expect } from 'vitest';
import {
    statusLabel,
    statusClasses,
    publishedProtocolCount,
} from './projectUtils';

describe('statusLabel', () => {
    it('maps the backend ACTIVE run status to "Running" (#20)', () => {
        // The run detail page shows "Running"; the runs table and History
        // tab must agree rather than showing the raw "ACTIVE" enum value.
        expect(statusLabel('ACTIVE')).toBe('Running');
    });

    it('maps legacy RUNNING / IN_PROGRESS aliases to "Running"', () => {
        expect(statusLabel('RUNNING')).toBe('Running');
        expect(statusLabel('IN_PROGRESS')).toBe('Running');
    });

    it('is case-insensitive', () => {
        expect(statusLabel('active')).toBe('Running');
    });

    it('maps COMPLETED, EDITED, ARCHIVED, PLANNED, DRAFT', () => {
        expect(statusLabel('COMPLETED')).toBe('Completed');
        expect(statusLabel('EDITED')).toBe('Edited');
        expect(statusLabel('ARCHIVED')).toBe('Archived');
        expect(statusLabel('PLANNED')).toBe('Planned');
        expect(statusLabel('DRAFT')).toBe('Draft');
    });

    it('falls back to the raw value for unknown statuses', () => {
        expect(statusLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW');
    });
});

describe('statusClasses', () => {
    it('styles ACTIVE the same as the legacy RUNNING alias (#20)', () => {
        expect(statusClasses('ACTIVE')).toBe(statusClasses('RUNNING'));
    });

    it('gives EDITED a distinct amber style', () => {
        const cls = statusClasses('EDITED');
        expect(cls).toContain('amber');
    });
});

describe('publishedProtocolCount', () => {
    it('counts only APPROVED protocols, not DRAFT ones (#10)', () => {
        const protocols = [
            { status: 'APPROVED' },
            { status: 'DRAFT' },
            { status: 'PENDING_APPROVAL' },
            { status: 'ARCHIVED' },
        ];
        expect(publishedProtocolCount(protocols)).toBe(1);
    });

    it('is case-insensitive', () => {
        expect(publishedProtocolCount([{ status: 'approved' }])).toBe(1);
    });

    it('is 0 for an empty list or missing statuses', () => {
        expect(publishedProtocolCount([])).toBe(0);
        expect(publishedProtocolCount([{ status: null }, {}])).toBe(0);
    });
});
