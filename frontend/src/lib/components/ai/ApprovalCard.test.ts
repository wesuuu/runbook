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
        project_name: 'Cell Culture',
        step_count: 7,
        duration_min_total: 110,
        license: 'CC BY-SA 3.0',
        deviations: [],
        steps: [
            { text: 'Grow seed culture in LB to saturation.', duration_min: null },
            { text: 'Incubate on ice for 10 min.', duration_min: 10 },
            { text: 'Spin down at 3000 rpm, decant supernatant.', duration_min: null },
        ],
    },
    onApprove: () => {},
    onReject: () => {},
};

describe('ApprovalCard (F-0084 inline edit)', () => {
    it('renders the title, step count, and source host', () => {
        render(ApprovalCard, { props: baseProps });
        expect(screen.getByText(/Heat-shock transformation/)).toBeTruthy();
        expect(screen.getByText(/openwetware\.org/)).toBeTruthy();
    });

    it('renders the destination project name when present', () => {
        render(ApprovalCard, { props: baseProps });
        expect(screen.getByText('Cell Culture')).toBeTruthy();
        expect(screen.getByText(/project/i)).toBeTruthy();
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

    it('calls onApprove with toolCallId and no submission when steps are unchanged', async () => {
        const onApprove = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onApprove } });
        const approve = screen.getByRole('button', { name: /approve/i });
        await fireEvent.click(approve);
        expect(onApprove).toHaveBeenCalledTimes(1);
        expect(onApprove).toHaveBeenCalledWith('call_abc', undefined);
    });

    it('calls onReject directly with no reason (single click)', async () => {
        const onReject = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onReject } });
        const reject = screen.getByRole('button', { name: /^reject$/i });
        await fireEvent.click(reject);
        expect(onReject).toHaveBeenCalledTimes(1);
        expect(onReject).toHaveBeenCalledWith('call_abc');
    });

    it('hides the procedure toggle when no steps are provided', () => {
        render(ApprovalCard, {
            props: {
                ...baseProps,
                payloadPreview: { ...baseProps.payloadPreview, steps: [] },
            },
        });
        expect(screen.queryByRole('button', { name: /review.*procedure/i })).toBeNull();
    });

    it('reveals an editable step list with textareas and remove buttons when toggled', async () => {
        render(ApprovalCard, { props: baseProps });
        // Collapsed by default.
        expect(screen.queryByText(/Grow seed culture/)).toBeNull();
        const toggle = screen.getByRole('button', { name: /review.*procedure/i });
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        await fireEvent.click(toggle);
        // Each step is now an editable textarea.
        const ta1 = screen.getByLabelText('Step 1 text') as HTMLTextAreaElement;
        const ta2 = screen.getByLabelText('Step 2 text') as HTMLTextAreaElement;
        const ta3 = screen.getByLabelText('Step 3 text') as HTMLTextAreaElement;
        expect(ta1.value).toMatch(/Grow seed culture/);
        expect(ta2.value).toMatch(/Incubate on ice/);
        expect(ta3.value).toMatch(/Spin down at 3000 rpm/);
        // Remove buttons exist.
        expect(screen.getByRole('button', { name: /remove step 1/i })).toBeTruthy();
        expect(screen.getByRole('button', { name: /remove step 2/i })).toBeTruthy();
        // Toggle label flips.
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
    });

    it('removing a step emits a "Removed step" deviation on approve', async () => {
        const onApprove = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onApprove } });
        await fireEvent.click(screen.getByRole('button', { name: /review.*procedure/i }));
        await fireEvent.click(screen.getByRole('button', { name: /remove step 2/i }));
        await fireEvent.click(screen.getByRole('button', { name: /approve/i }));
        expect(onApprove).toHaveBeenCalledTimes(1);
        const [tcid, submission] = onApprove.mock.calls[0];
        expect(tcid).toBe('call_abc');
        expect(submission.editedSteps).toHaveLength(2);
        expect(submission.deviations).toEqual([
            'Removed step: Incubate on ice for 10 min.',
        ]);
    });

    it('editing a step text emits an "Edited step" deviation with strikethrough', async () => {
        const onApprove = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onApprove } });
        await fireEvent.click(screen.getByRole('button', { name: /review.*procedure/i }));
        const ta2 = screen.getByLabelText('Step 2 text') as HTMLTextAreaElement;
        await fireEvent.input(ta2, { target: { value: 'Incubate on ice for 5 min.' } });
        await fireEvent.click(screen.getByRole('button', { name: /approve/i }));
        const submission = onApprove.mock.calls[0][1];
        expect(submission.deviations).toEqual([
            'Edited step: ~~Incubate on ice for 10 min.~~ Incubate on ice for 5 min.',
        ]);
    });

    it('adding a step emits an "Added step" deviation on approve', async () => {
        const onApprove = vi.fn();
        render(ApprovalCard, { props: { ...baseProps, onApprove } });
        await fireEvent.click(screen.getByRole('button', { name: /review.*procedure/i }));
        await fireEvent.click(screen.getByRole('button', { name: /add step/i }));
        const newRow = screen.getByLabelText('Step 4 text') as HTMLTextAreaElement;
        await fireEvent.input(newRow, { target: { value: 'Plate on LB-Amp.' } });
        await fireEvent.click(screen.getByRole('button', { name: /approve/i }));
        const submission = onApprove.mock.calls[0][1];
        expect(submission.deviations).toEqual(['Added step: Plate on LB-Amp.']);
        expect(submission.editedSteps).toHaveLength(4);
    });

    it('reset-to-original restores the unedited step list and hides the reset button', async () => {
        render(ApprovalCard, { props: baseProps });
        await fireEvent.click(screen.getByRole('button', { name: /review.*procedure/i }));
        // No reset button visible while clean.
        expect(screen.queryByRole('button', { name: /reset.*to original/i })).toBeNull();
        await fireEvent.click(screen.getByRole('button', { name: /remove step 1/i }));
        const resetBtn = screen.getByRole('button', { name: /reset.*to original/i });
        await fireEvent.click(resetBtn);
        // Step 1 textarea is back with original content.
        const ta1 = screen.getByLabelText('Step 1 text') as HTMLTextAreaElement;
        expect(ta1.value).toMatch(/Grow seed culture/);
        expect(screen.queryByRole('button', { name: /reset.*to original/i })).toBeNull();
    });

    it('disables approve when all steps have been removed', async () => {
        render(ApprovalCard, { props: baseProps });
        await fireEvent.click(screen.getByRole('button', { name: /review.*procedure/i }));
        await fireEvent.click(screen.getByRole('button', { name: /remove step 1/i }));
        await fireEvent.click(screen.getByRole('button', { name: /remove step 1/i }));
        await fireEvent.click(screen.getByRole('button', { name: /remove step 1/i }));
        const approve = screen.getByRole('button', { name: /approve/i }) as HTMLButtonElement;
        expect(approve.disabled).toBe(true);
    });

    it('disables both buttons when `pending` prop is true', () => {
        render(ApprovalCard, { props: { ...baseProps, pending: true } });
        const approve = screen.getByRole('button', { name: /approve/i });
        const reject = screen.getByRole('button', { name: /^reject$/i });
        expect((approve as HTMLButtonElement).disabled).toBe(true);
        expect((reject as HTMLButtonElement).disabled).toBe(true);
    });
});
