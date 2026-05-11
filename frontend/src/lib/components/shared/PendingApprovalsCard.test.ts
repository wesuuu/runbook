import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    getAwaitingMyApproval: vi.fn(),
}));

import PendingApprovalsCard from './PendingApprovalsCard.svelte';
import * as apiModule from '$lib/api';

beforeEach(() => {
    vi.clearAllMocks();
});

describe('PendingApprovalsCard', () => {
    it('renders nothing when the list is empty', async () => {
        (apiModule.getAwaitingMyApproval as any).mockResolvedValue([]);
        const { container, queryByTestId } = render(PendingApprovalsCard);
        await waitFor(() => {
            expect(apiModule.getAwaitingMyApproval).toHaveBeenCalled();
        });
        expect(queryByTestId('pending-approvals-card')).toBeNull();
        // Component renders only the (collapsed) wrapper if anything; assert no card
        expect(container.querySelector('h3')).toBeNull();
    });

    it('renders rows when populated', async () => {
        (apiModule.getAwaitingMyApproval as any).mockResolvedValue([
            {
                protocol_id: '11111111-1111-1111-1111-111111111111',
                name: 'Buffer SOP',
                project_id: '22222222-2222-2222-2222-222222222222',
                project_name: 'Project Alpha',
                organization_id: '33333333-3333-3333-3333-333333333333',
                submitted_at: '2026-05-10T12:00:00Z',
                submitted_by: {
                    id: '44444444-4444-4444-4444-444444444444',
                    name: 'Sarah Submitter',
                    email: 'sarah@x.com',
                },
            },
        ]);
        const { findByTestId, findByText } = render(PendingApprovalsCard);
        await findByTestId('pending-approvals-card');
        const row = await findByTestId('pending-approval-row');
        expect(row.textContent).toMatch(/Project Alpha/);
        expect(row.textContent).toMatch(/Buffer SOP/);
        expect(row.getAttribute('href')).toBe(
            '/protocols/11111111-1111-1111-1111-111111111111',
        );
        expect(await findByText(/Submitted by Sarah Submitter/)).toBeTruthy();
    });
});
