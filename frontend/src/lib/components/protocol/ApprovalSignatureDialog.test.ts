import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    approveProtocol: vi.fn(),
    rejectProtocol: vi.fn(),
}));

vi.mock('$lib/auth.svelte', () => ({
    getUser: vi.fn(),
    getToken: vi.fn(() => 'test-token'),
}));

vi.mock('$lib/config', () => ({
    API_BASE: 'http://api.test',
}));

import ApprovalSignatureDialog from './ApprovalSignatureDialog.svelte';
import * as apiModule from '$lib/api';
import * as authModule from '$lib/auth.svelte';

beforeEach(() => {
    vi.clearAllMocks();
    (authModule.getUser as any).mockReturnValue({
        id: 'u1',
        email: 'alice@example.com',
        full_name: 'Alice',
        signature_full_url: null,
    });
});

describe('ApprovalSignatureDialog', () => {
    it('reject mode disables submit until comment is provided', async () => {
        const { getByRole } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'reject',
            protocolId: 'p1',
        });
        const rejectBtn = getByRole('button', { name: /^Reject$/i }) as HTMLButtonElement;
        expect(rejectBtn.disabled).toBe(true);

        const ta = document.querySelector('#approval-comment') as HTMLTextAreaElement;
        await fireEvent.input(ta, { target: { value: 'Needs cleanup' } });
        expect(rejectBtn.disabled).toBe(false);
    });

    it('approve mode enables submit immediately', () => {
        const { getByRole } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'approve',
            protocolId: 'p1',
        });
        const btn = getByRole('button', { name: /^Approve$/i }) as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
    });

    it('preview src uses signature_full_url when present', () => {
        (authModule.getUser as any).mockReturnValue({
            id: 'u1',
            email: 'alice@example.com',
            full_name: 'Alice',
            signature_full_url: '/storage/sig.png',
        });
        const { getByTestId } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'approve',
            protocolId: 'p1',
        });
        const preview = getByTestId('approval-signature-preview') as HTMLImageElement;
        expect(preview.tagName).toBe('IMG');
        expect(preview.src).toContain('/storage/sig.png');
        expect(preview.src).toContain('token=test-token');
    });

    it('falls back to cursive name when no signature is saved', () => {
        const { getByTestId } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'approve',
            protocolId: 'p1',
        });
        const preview = getByTestId('approval-signature-preview');
        expect(preview.tagName).not.toBe('IMG');
        expect(preview.classList.contains('signature-cursive')).toBe(true);
        expect(preview.textContent?.trim()).toBe('Alice');
    });

    it('calls approveProtocol on confirm', async () => {
        (apiModule.approveProtocol as any).mockResolvedValueOnce({ id: 'p1' });
        const onSuccess = vi.fn();
        const { getByRole } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'approve',
            protocolId: 'p1',
            onSuccess,
        });
        await fireEvent.click(getByRole('button', { name: /^Approve$/i }));
        await waitFor(() => {
            expect(apiModule.approveProtocol).toHaveBeenCalledWith('p1', {
                signature_statement: undefined,
            });
            expect(onSuccess).toHaveBeenCalled();
        });
    });

    it('calls rejectProtocol with comment on confirm', async () => {
        (apiModule.rejectProtocol as any).mockResolvedValueOnce({ id: 'p1' });
        const { getByRole } = render(ApprovalSignatureDialog, {
            open: true,
            mode: 'reject',
            protocolId: 'p1',
        });
        const ta = document.querySelector('#approval-comment') as HTMLTextAreaElement;
        await fireEvent.input(ta, { target: { value: 'Fix this' } });
        await fireEvent.click(getByRole('button', { name: /^Reject$/i }));
        await waitFor(() => {
            expect(apiModule.rejectProtocol).toHaveBeenCalledWith('p1', {
                comment: 'Fix this',
                signature_statement: undefined,
            });
        });
    });
});
