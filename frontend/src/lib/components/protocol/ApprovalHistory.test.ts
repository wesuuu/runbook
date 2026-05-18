import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    getProtocolSignoffs: vi.fn(),
}));

import ApprovalHistory from './ApprovalHistory.svelte';
import * as apiModule from '$lib/api';
import type { GlpSignoffResponse } from '$lib/schemas/glpSignoff';

beforeEach(() => {
    vi.clearAllMocks();
});

describe('ApprovalHistory', () => {
    it('does not fetch on mount', () => {
        render(ApprovalHistory, { protocolId: 'p1' });
        expect(apiModule.getProtocolSignoffs).not.toHaveBeenCalled();
    });

    it('fetches once on first expand and not again on toggle', async () => {
        (apiModule.getProtocolSignoffs as any).mockResolvedValue([]);
        const { getByRole } = render(ApprovalHistory, { protocolId: 'p1' });
        const btn = getByRole('button');

        await fireEvent.click(btn); // expand
        await waitFor(() => {
            expect(apiModule.getProtocolSignoffs).toHaveBeenCalledTimes(1);
        });

        await fireEvent.click(btn); // collapse
        await fireEvent.click(btn); // re-expand
        // Should still be 1 (cached)
        expect(apiModule.getProtocolSignoffs).toHaveBeenCalledTimes(1);
    });

    it('renders empty state', async () => {
        (apiModule.getProtocolSignoffs as any).mockResolvedValue([]);
        const { getByRole, findByText } = render(ApprovalHistory, { protocolId: 'p1' });
        await fireEvent.click(getByRole('button'));
        expect(await findByText(/No signoffs yet/i)).toBeTruthy();
    });

    it('renders populated state', async () => {
        const signoffs: GlpSignoffResponse[] = [
            {
                id: '11111111-1111-1111-1111-111111111111',
                protocol_id: 'p1',
                run_id: null,
                role: 'STUDY_DIRECTOR',
                action: 'APPROVED',
                signer_id: '22222222-2222-2222-2222-222222222222',
                signer: {
                    id: '22222222-2222-2222-2222-222222222222',
                    name: 'Alice',
                    email: 'alice@example.com',
                },
                attestation: 'I have reviewed this',
                signed_at: '2026-05-10T12:00:00Z',
                signature_image_path: 'fixture/sig.png',
                signoff_request_id: null,
                invalidated_at: null,
                invalidated_reason: null,
                invalidated_by_id: null,
                created_at: '2026-05-10T12:00:00Z',
                updated_at: '2026-05-10T12:00:00Z',
            },
        ];
        (apiModule.getProtocolSignoffs as any).mockResolvedValue(signoffs);
        const { getByRole, findByText } = render(ApprovalHistory, { protocolId: 'p1' });
        await fireEvent.click(getByRole('button'));
        expect(await findByText('APPROVED')).toBeTruthy();
        expect(await findByText('STUDY_DIRECTOR')).toBeTruthy();
        expect(await findByText('Alice')).toBeTruthy();
        expect(await findByText(/I have reviewed this/)).toBeTruthy();
    });
});
