import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        patch: vi.fn(),
    },
}));

vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: vi.fn(() => ({ id: 'org-1' })),
}));

import OrgProtocolApproversCard from './OrgProtocolApproversCard.svelte';
import * as apiModule from '$lib/api';

beforeEach(() => {
    vi.clearAllMocks();
});

function setupApi(members: any[], patchResult?: any) {
    (apiModule.api.get as any).mockResolvedValue(members);
    (apiModule.api.patch as any).mockResolvedValue(
        patchResult ?? { roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
    );
}

describe('OrgProtocolApproversCard', () => {
    it('shows members with PROTOCOL_APPROVER role and a badge', async () => {
        setupApi([
            { user_id: 'u-1', full_name: 'Alice', email: 'a@x.com', roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
            { user_id: 'u-2', full_name: 'Bob', email: 'b@x.com', roles: ['MEMBER'] },
        ]);
        const { findAllByTestId, getByText, getByTestId, queryByText } = render(
            OrgProtocolApproversCard,
            { canManage: true },
        );
        const rows = await findAllByTestId('approver-row');
        expect(rows.length).toBe(1);
        expect(getByText('Alice')).toBeTruthy();
        expect(getByTestId('approver-badge').textContent).toMatch(/Protocol approver/i);
        // Bob is a candidate in the select but not an approver-row
        const bobInRow = rows.some((r) => r.textContent?.includes('Bob'));
        expect(bobInRow).toBe(false);
        // suppress unused var
        void queryByText;
    });

    it('hides controls when canManage=false', async () => {
        setupApi([
            { user_id: 'u-1', full_name: 'Alice', email: 'a@x.com', roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
        ]);
        const { findAllByTestId, queryByTestId, queryByText } = render(
            OrgProtocolApproversCard,
            { canManage: false },
        );
        await findAllByTestId('approver-row');
        expect(queryByTestId('approver-select')).toBeNull();
        expect(queryByText(/^Remove$/)).toBeNull();
    });

    it('add approver flow', async () => {
        setupApi(
            [
                { user_id: 'u-2', full_name: 'Bob', email: 'b@x.com', roles: ['MEMBER'] },
            ],
            { roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
        );
        const { getByTestId, getByText } = render(OrgProtocolApproversCard, {
            canManage: true,
        });
        await waitFor(() => getByTestId('approver-select'));
        const select = getByTestId('approver-select') as HTMLSelectElement;
        await waitFor(() => {
            const opt = select.querySelector('option[value="u-2"]');
            expect(opt).toBeTruthy();
        });
        const opt = select.querySelector('option[value="u-2"]') as HTMLOptionElement;
        opt.selected = true;
        await fireEvent.change(select);
        await waitFor(() => {
            const btn = getByText(/^Add$/).closest('button') as HTMLButtonElement;
            expect(btn.disabled).toBe(false);
        });
        await fireEvent.click(getByText(/^Add$/));
        await waitFor(() => {
            expect(apiModule.api.patch).toHaveBeenCalledWith(
                '/iam/organizations/org-1/members/u-2',
                { roles: expect.arrayContaining(['MEMBER', 'PROTOCOL_APPROVER']) },
            );
        });
    });

    it('remove approver flow strips PROTOCOL_APPROVER but keeps MEMBER', async () => {
        setupApi(
            [
                { user_id: 'u-1', full_name: 'Alice', email: 'a@x.com', roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
            ],
            { roles: ['MEMBER'] },
        );
        const { findByText } = render(OrgProtocolApproversCard, {
            canManage: true,
        });
        const removeBtn = await findByText(/^Remove$/);
        await fireEvent.click(removeBtn);
        await waitFor(() => {
            expect(apiModule.api.patch).toHaveBeenCalledWith(
                '/iam/organizations/org-1/members/u-1',
                { roles: ['MEMBER'] },
            );
        });
    });
});
