import { describe, it, expect } from 'vitest';
import { resolveToast } from './toast';

describe('resolveToast', () => {
    it('passes a normal message through unchanged', () => {
        expect(resolveToast('success', 'Saved', undefined)).toEqual({
            message: 'Saved',
        });
    });

    it('keeps both message and description when both are present', () => {
        expect(resolveToast('error', 'Upload failed', 'Try again')).toEqual({
            message: 'Upload failed',
            description: 'Try again',
        });
    });

    it('promotes the description when the message is empty (#14)', () => {
        expect(resolveToast('success', '', 'Protocol published')).toEqual({
            message: 'Protocol published',
        });
        expect(resolveToast('success', '   ', 'Protocol published')).toEqual({
            message: 'Protocol published',
        });
    });

    it('falls back to a per-level label when nothing is supplied (#14)', () => {
        // A toast must never render an empty body.
        expect(resolveToast('success', '', '')).toEqual({ message: 'Done' });
        expect(resolveToast('error', undefined, undefined)).toEqual({
            message: 'Something went wrong',
        });
        expect(resolveToast('warning', null, null)).toEqual({
            message: 'Warning',
        });
        expect(resolveToast('info', '', undefined)).toEqual({
            message: 'Notice',
        });
    });

    it('drops a blank description rather than passing empty text', () => {
        expect(resolveToast('info', 'Heads up', '   ')).toEqual({
            message: 'Heads up',
        });
    });
});
