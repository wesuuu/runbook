import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import PublishVersionDialog from './PublishVersionDialog.svelte';

describe('PublishVersionDialog', () => {
    it('renders with empty fields when opened', () => {
        const { getByLabelText, getByText } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm: vi.fn(),
        });

        expect(getByText(/Publish version 4/i)).toBeTruthy();
        const desc = getByLabelText(/Description/i) as HTMLTextAreaElement;
        const summary = getByLabelText(/Change summary/i) as HTMLInputElement;
        expect(desc.value).toBe('');
        expect(summary.value).toBe('');
    });

    it('calls onConfirm with trimmed values when Publish is clicked', async () => {
        const onConfirm = vi.fn();
        const { getByLabelText, getByRole } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm,
        });

        const desc = getByLabelText(/Description/i) as HTMLTextAreaElement;
        const summary = getByLabelText(/Change summary/i) as HTMLInputElement;

        await fireEvent.input(desc, { target: { value: '  Switched to TBS\n' } });
        await fireEvent.input(summary, { target: { value: '  TBS swap  ' } });

        const publishBtn = getByRole('button', { name: /^Publish$/i });
        await fireEvent.click(publishBtn);

        expect(onConfirm).toHaveBeenCalledTimes(1);
        expect(onConfirm).toHaveBeenCalledWith({
            description: 'Switched to TBS',
            change_summary: 'TBS swap',
        });
    });

    it('passes undefined for empty fields rather than empty strings', async () => {
        const onConfirm = vi.fn();
        const { getByRole } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm,
        });

        const publishBtn = getByRole('button', { name: /^Publish$/i });
        await fireEvent.click(publishBtn);

        expect(onConfirm).toHaveBeenCalledWith({
            description: undefined,
            change_summary: undefined,
        });
    });
});
