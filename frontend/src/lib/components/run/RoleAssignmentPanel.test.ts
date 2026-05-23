import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('$lib/auth.svelte', () => ({
    getUser: vi.fn(() => null),
}));

import RoleAssignmentPanel from './RoleAssignmentPanel.svelte';

const noop = (): void => {};

function baseProps(roleNodes: unknown[]) {
    return {
        roleNodes,
        roleAssignments: [],
        projectMembers: [],
        assignmentChanges: {},
        onUpdateAssignment: noop,
        onAssignmentChange: noop,
        onShowGoOffline: noop,
    };
}

describe('RoleAssignmentPanel', () => {
    it('renders a role node missing its data object without crashing', () => {
        // A malformed or legacy swimLane graph node with no `data` must not
        // white-screen the run detail page.
        const { getByText } = render(RoleAssignmentPanel, {
            props: baseProps([{ id: 'lane-1', type: 'swimLane' }]),
        });
        expect(getByText('Unnamed role')).toBeTruthy();
    });

    it('renders the role label when data is present', () => {
        const { getByText } = render(RoleAssignmentPanel, {
            props: baseProps([
                { id: 'lane-1', type: 'swimLane', data: { label: 'Operator' } },
            ]),
        });
        expect(getByText('Operator')).toBeTruthy();
    });
});
