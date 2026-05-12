import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ApprovalCard from './ApprovalCard.svelte';

const baseProps = {
    toolCallId: 'call_abc',
    toolName: 'create_protocol_from_external_source',
    title: 'Sauer: Heat-shock transformation of competent E. coli',
    sourceUrl:
        'https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli',
    payloadPreview: {
        title: 'Sauer: Heat-shock transformation of competent E. coli',
        source_url:
            'https://openwetware.org/wiki/Sauer:Heat_shock_transformation_of_E._coli',
        step_count: 7,
        duration_min_total: 110,
        license: 'CC BY-SA 3.0',
        deviations: [],
    },
    onApprove: () => {},
    onReject: () => {},
};

describe('ApprovalCard (F-0084)', () => {
    it('renders the title, step count, and source host', () => {
        render(ApprovalCard, { props: baseProps });
        expect(screen.getByText(/Heat-shock transformation/)).toBeTruthy();
        expect(screen.getByText('7')).toBeTruthy();
        expect(screen.getByText(/openwetware\.org/)).toBeTruthy();
    });

    it('renders the license and total duration', () => {
        render(ApprovalCard, { props: baseProps });
        expect(screen.getByText('CC BY-SA 3.0')).toBeTruthy();
        expect(screen.getByText(/110/)).toBeTruthy();
    });

    it('shows "None — copied verbatim" when there are no deviations', () => {
        render(ApprovalCard, { props: baseProps });
        expect(screen.getByText(/None.*copied verbatim/i)).toBeTruthy();
    });

    it('renders deviation chips when provided', () => {
        render(ApprovalCard, {
            props: {
                ...baseProps,
                payloadPreview: {
                    ...baseProps.payloadPreview,
                    deviations: ['Skipped optional step 4', 'Lowered heat-shock to 30s'],
                },
            },
        });
        expect(screen.getByText(/Skipped optional step 4/)).toBeTruthy();
        expect(screen.getByText(/Lowered heat-shock to 30s/)).toBeTruthy();
    });

    it('calls onApprove with toolCallId when the approve button is clicked', async () => {
        const onApprove = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onApprove } });
        const approve = screen.getByRole('button', { name: /approve/i });
        await fireEvent.click(approve);
        expect(onApprove).toHaveBeenCalledTimes(1);
        expect(onApprove).toHaveBeenCalledWith('call_abc');
    });

    it('calls onReject with toolCallId when the reject button is clicked', async () => {
        const onReject = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onReject } });
        const reject = screen.getByRole('button', { name: /reject/i });
        await fireEvent.click(reject);
        expect(onReject).toHaveBeenCalledTimes(1);
        expect(onReject).toHaveBeenCalledWith('call_abc');
    });

    it('disables both buttons when `pending` prop is true', () => {
        render(ApprovalCard, { props: { ...baseProps, pending: true } });
        const approve = screen.getByRole('button', { name: /approve/i });
        const reject = screen.getByRole('button', { name: /reject/i });
        expect((approve as HTMLButtonElement).disabled).toBe(true);
        expect((reject as HTMLButtonElement).disabled).toBe(true);
    });
});
