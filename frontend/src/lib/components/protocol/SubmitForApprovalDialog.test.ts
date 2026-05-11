import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
    },
    submitProtocolForApproval: vi.fn(),
}));

vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: vi.fn(() => ({ id: 'org-1', name: 'Org', subscription_tier: 'PRO' })),
}));

import SubmitForApprovalDialog from './SubmitForApprovalDialog.svelte';
import * as apiModule from '$lib/api';

beforeEach(() => {
    vi.clearAllMocks();
});

function setupApi(opts: { project?: any[]; members?: any[] } = {}) {
    (apiModule.api.get as any).mockImplementation((url: string) => {
        if (url.includes('/approvers')) {
            return Promise.resolve(opts.project ?? []);
        }
        if (url.includes('/members')) {
            return Promise.resolve(opts.members ?? []);
        }
        return Promise.resolve([]);
    });
}

const baseProps = {
    open: true,
    protocolId: 'p1',
    projectId: 'proj-1',
};

describe('SubmitForApprovalDialog', () => {
    it('submit disabled when zero selected', async () => {
        setupApi({ project: [], members: [] });
        const { getByRole, findByText } = render(SubmitForApprovalDialog, baseProps);
        await findByText(/No project approvers/i);
        const btn = getByRole('button', { name: /Submit/ }) as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
    });

    it('groups project and org approvers separately', async () => {
        setupApi({
            project: [
                { id: 'perm-1', principal_type: 'USER', principal_id: 'u-proj', name: 'Pat Project', email: 'pat@x.com' },
            ],
            members: [
                { user_id: 'u-org', full_name: 'Olive Org', email: 'olive@x.com', roles: ['MEMBER', 'PROTOCOL_APPROVER'] },
                { user_id: 'u-noise', full_name: 'Nora Noise', email: 'nora@x.com', roles: ['MEMBER'] },
            ],
        });
        const { findByTestId, queryByTestId } = render(SubmitForApprovalDialog, baseProps);
        await findByTestId('approver-u-proj');
        await findByTestId('approver-u-org');
        expect(queryByTestId('approver-u-noise')).toBeNull();
    });

    it('dedupes hybrid users (project + org)', async () => {
        setupApi({
            project: [
                { id: 'perm-1', principal_type: 'USER', principal_id: 'u-hybrid', name: 'Hybrid User', email: 'hy@x.com' },
            ],
            members: [
                { user_id: 'u-hybrid', full_name: 'Hybrid User', email: 'hy@x.com', roles: ['PROTOCOL_APPROVER'] },
            ],
        });
        const { findAllByTestId } = render(SubmitForApprovalDialog, baseProps);
        const checkboxes = await findAllByTestId('approver-u-hybrid');
        // Only one checkbox, not two
        expect(checkboxes.length).toBe(1);
    });

    it('enables submit and calls API when an approver is selected', async () => {
        setupApi({
            project: [
                { id: 'perm-1', principal_type: 'USER', principal_id: 'u-proj', name: 'Pat', email: 'pat@x.com' },
            ],
            members: [],
        });
        (apiModule.submitProtocolForApproval as any).mockResolvedValueOnce({ id: 'p1' });
        const onSuccess = vi.fn();
        const { findByTestId, getByRole } = render(SubmitForApprovalDialog, {
            ...baseProps,
            onSuccess,
        });
        const cb = await findByTestId('approver-u-proj');
        await fireEvent.click(cb);
        const btn = getByRole('button', { name: /Submit/ }) as HTMLButtonElement;
        expect(btn.disabled).toBe(false);
        await fireEvent.click(btn);
        await waitFor(() => {
            expect(apiModule.submitProtocolForApproval).toHaveBeenCalledWith('p1', ['u-proj']);
            expect(onSuccess).toHaveBeenCalled();
        });
    });
});
