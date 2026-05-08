import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import MemberRolesPicker from './MemberRolesPicker.svelte';

describe('MemberRolesPicker', () => {
    it('renders a static Member chip with no edit button', () => {
        const { getAllByText } = render(MemberRolesPicker, {
            props: { roles: ['MEMBER', 'ADMIN'], onChange: () => {} },
        });
        const memberChips = getAllByText('Member');
        expect(memberChips.length).toBeGreaterThanOrEqual(1);
        const memberSpan = memberChips[0];
        expect(memberSpan.closest('button')).toBeNull();
    });

    it('renders an Admin chip when ADMIN is in roles', () => {
        const { getByText } = render(MemberRolesPicker, {
            props: { roles: ['MEMBER', 'ADMIN'], onChange: () => {} },
        });
        expect(getByText('Admin')).toBeTruthy();
    });

    it('hides the edit affordance when disabled', () => {
        const { queryByLabelText } = render(MemberRolesPicker, {
            props: {
                roles: ['MEMBER'],
                disabled: true,
                onChange: () => {},
            },
        });
        expect(queryByLabelText('Edit roles')).toBeNull();
    });

    it('exposes an Edit roles trigger when enabled', () => {
        const { getByLabelText } = render(MemberRolesPicker, {
            props: {
                roles: ['MEMBER'],
                disabled: false,
                onChange: vi.fn(),
            },
        });
        expect(getByLabelText('Edit roles')).toBeTruthy();
    });
});
