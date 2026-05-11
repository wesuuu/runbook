import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api', () => ({
    designateProtocolApproval: vi.fn(),
}));

import ApprovalDesignator from './ApprovalDesignator.svelte';
import * as apiModule from '$lib/api';

const baseProps = {
    protocolId: 'p1',
    requiresApproval: false,
    status: 'DRAFT',
    canManage: true,
    projectSettingEnabled: true,
    onChanged: () => {},
};

beforeEach(() => {
    vi.clearAllMocks();
});

describe('ApprovalDesignator', () => {
    it('toggle is enabled when DRAFT, canManage, and project setting on', () => {
        const { getByRole } = render(ApprovalDesignator, baseProps);
        const sw = getByRole('switch') as HTMLButtonElement;
        expect(sw.disabled).toBe(false);
    });

    it('disabled when status is not DRAFT', () => {
        const { getByRole, getByText } = render(ApprovalDesignator, {
            ...baseProps,
            status: 'PENDING_APPROVAL',
        });
        const sw = getByRole('switch') as HTMLButtonElement;
        expect(sw.disabled).toBe(true);
        expect(getByText(/Can only change while status is DRAFT/i)).toBeTruthy();
    });

    it('disabled when canManage is false', () => {
        const { getByRole, getByText } = render(ApprovalDesignator, {
            ...baseProps,
            canManage: false,
        });
        const sw = getByRole('switch') as HTMLButtonElement;
        expect(sw.disabled).toBe(true);
        expect(getByText(/Only the protocol creator or a project admin/i)).toBeTruthy();
    });

    it('disabled when project setting off', () => {
        const { getByRole, getByText } = render(ApprovalDesignator, {
            ...baseProps,
            projectSettingEnabled: false,
        });
        const sw = getByRole('switch') as HTMLButtonElement;
        expect(sw.disabled).toBe(true);
        expect(getByText(/Enable Project Settings/i)).toBeTruthy();
    });

    it('calls API and onChanged when toggled', async () => {
        const onChanged = vi.fn();
        (apiModule.designateProtocolApproval as any).mockResolvedValueOnce({});
        const { getByRole } = render(ApprovalDesignator, {
            ...baseProps,
            onChanged,
        });
        const sw = getByRole('switch') as HTMLButtonElement;
        await fireEvent.click(sw);
        await waitFor(() => {
            expect(apiModule.designateProtocolApproval).toHaveBeenCalledWith('p1', true);
            expect(onChanged).toHaveBeenCalledWith(true);
        });
    });
});
