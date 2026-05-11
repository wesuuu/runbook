import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        post: vi.fn(),
        delete: vi.fn(),
    },
}));

vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: vi.fn(() => ({ id: 'org-1' })),
}));

import ProjectProtocolApproversCard from './ProjectProtocolApproversCard.svelte';
import * as apiModule from '$lib/api';

beforeEach(() => {
    vi.clearAllMocks();
});

function setupApi(opts: {
    approvers?: any[];
    members?: any[];
    addResult?: any;
} = {}) {
    (apiModule.api.get as any).mockImplementation((url: string) => {
        if (url.includes('/approvers')) {
            return Promise.resolve(opts.approvers ?? []);
        }
        if (url.includes('/members')) {
            return Promise.resolve(opts.members ?? []);
        }
        return Promise.resolve([]);
    });
    (apiModule.api.post as any).mockResolvedValue(
        opts.addResult ?? {
            id: 'perm-new',
            principal_type: 'USER',
            principal_id: 'u-new',
            name: 'New User',
            email: 'new@x.com',
        },
    );
    (apiModule.api.delete as any).mockResolvedValue(undefined);
}

describe('ProjectProtocolApproversCard', () => {
    it('hides controls when canManage=false', async () => {
        setupApi({ approvers: [], members: [] });
        const { queryByTestId, queryByText } = render(
            ProjectProtocolApproversCard,
            { projectId: 'proj-1', canManage: false },
        );
        await waitFor(() => {
            expect(queryByText(/Loading/i)).toBeNull();
        });
        expect(queryByTestId('approver-select')).toBeNull();
    });

    it('add approver flow', async () => {
        setupApi({
            approvers: [],
            members: [
                { user_id: 'u-new', full_name: 'New User', email: 'new@x.com' },
            ],
        });
        const { getByTestId, getByText } = render(
            ProjectProtocolApproversCard,
            { projectId: 'proj-1', canManage: true },
        );
        await waitFor(() => getByTestId('approver-select'));
        const select = getByTestId('approver-select') as HTMLSelectElement;
        // Wait until the user option is rendered
        await waitFor(() => {
            const opt = select.querySelector('option[value="u-new"]');
            expect(opt).toBeTruthy();
        });
        const option = select.querySelector('option[value="u-new"]') as HTMLOptionElement;
        option.selected = true;
        await fireEvent.change(select);
        await waitFor(() => {
            const btn = getByText(/^Add$/).closest('button') as HTMLButtonElement;
            expect(btn.disabled).toBe(false);
        });
        await fireEvent.click(getByText(/^Add$/));
        await waitFor(() => {
            expect(apiModule.api.post).toHaveBeenCalledWith(
                '/projects/proj-1/approvers',
                { principal_type: 'USER', principal_id: 'u-new' },
            );
        });
    });

    it('remove approver flow', async () => {
        setupApi({
            approvers: [
                {
                    id: 'perm-1',
                    principal_type: 'USER',
                    principal_id: 'u-1',
                    name: 'Pat',
                    email: 'pat@x.com',
                },
            ],
            members: [],
        });
        const { findByText } = render(ProjectProtocolApproversCard, {
            projectId: 'proj-1',
            canManage: true,
        });
        const removeBtn = await findByText(/Remove/);
        await fireEvent.click(removeBtn);
        await waitFor(() => {
            expect(apiModule.api.delete).toHaveBeenCalledWith(
                '/projects/proj-1/approvers/perm-1',
            );
        });
    });
});
