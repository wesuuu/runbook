import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    getProtocolApprovalHistory: vi.fn(),
}));

import ApprovalHistory from './ApprovalHistory.svelte';
import * as apiModule from '$lib/api';
import type { ProtocolApprovalEvent } from '$lib/schemas/protocolApproval';

beforeEach(() => {
    vi.clearAllMocks();
});

describe('ApprovalHistory', () => {
    it('does not fetch on mount', () => {
        render(ApprovalHistory, { protocolId: 'p1' });
        expect(apiModule.getProtocolApprovalHistory).not.toHaveBeenCalled();
    });

    it('fetches once on first expand and not again on toggle', async () => {
        (apiModule.getProtocolApprovalHistory as any).mockResolvedValue([]);
        const { getByRole } = render(ApprovalHistory, { protocolId: 'p1' });
        const btn = getByRole('button');

        await fireEvent.click(btn); // expand
        await waitFor(() => {
            expect(apiModule.getProtocolApprovalHistory).toHaveBeenCalledTimes(1);
        });

        await fireEvent.click(btn); // collapse
        await fireEvent.click(btn); // re-expand
        // Should still be 1 (cached)
        expect(apiModule.getProtocolApprovalHistory).toHaveBeenCalledTimes(1);
    });

    it('renders empty state', async () => {
        (apiModule.getProtocolApprovalHistory as any).mockResolvedValue([]);
        const { getByRole, findByText } = render(ApprovalHistory, { protocolId: 'p1' });
        await fireEvent.click(getByRole('button'));
        expect(await findByText(/No events yet/i)).toBeTruthy();
    });

    it('renders populated state', async () => {
        const events: ProtocolApprovalEvent[] = [
            {
                id: '11111111-1111-1111-1111-111111111111',
                action: 'APPROVED',
                comment: 'Looks good',
                signature_statement: 'I have reviewed this',
                actor: {
                    id: '22222222-2222-2222-2222-222222222222',
                    name: 'Alice',
                    email: 'alice@example.com',
                },
                protocol_version: { id: '33333333-3333-3333-3333-333333333333', version_number: 2 },
                created_at: '2026-05-10T12:00:00Z',
            },
        ];
        (apiModule.getProtocolApprovalHistory as any).mockResolvedValue(events);
        const { getByRole, findByText } = render(ApprovalHistory, { protocolId: 'p1' });
        await fireEvent.click(getByRole('button'));
        expect(await findByText('APPROVED')).toBeTruthy();
        expect(await findByText('Alice')).toBeTruthy();
        expect(await findByText(/Looks good/)).toBeTruthy();
        expect(await findByText(/I have reviewed this/)).toBeTruthy();
    });
});
