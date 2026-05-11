import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RevertOnEditConfirmDialog from './RevertOnEditConfirmDialog.svelte';

describe('RevertOnEditConfirmDialog', () => {
    it('renders the body text', () => {
        const { getByText } = render(RevertOnEditConfirmDialog, {
            open: true,
            onConfirm: vi.fn(),
            onCancel: vi.fn(),
        });
        expect(
            getByText(/revert it from APPROVED to DRAFT/i),
        ).toBeTruthy();
    });

    it('fires onConfirm when continue clicked', async () => {
        const onConfirm = vi.fn();
        const { getByText } = render(RevertOnEditConfirmDialog, {
            open: true,
            onConfirm,
            onCancel: vi.fn(),
        });
        await fireEvent.click(getByText(/Continue editing/i));
        expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it('fires onCancel when cancel clicked', async () => {
        const onCancel = vi.fn();
        const { getByText } = render(RevertOnEditConfirmDialog, {
            open: true,
            onConfirm: vi.fn(),
            onCancel,
        });
        await fireEvent.click(getByText(/^Cancel$/i));
        expect(onCancel).toHaveBeenCalledTimes(1);
    });
});
