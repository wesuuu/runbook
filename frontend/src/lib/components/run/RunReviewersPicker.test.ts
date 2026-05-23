import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import RunReviewersPicker from './RunReviewersPicker.svelte';

const members = [
    { id: 'u1', full_name: 'Dana Director', email: 'dana@x.com' },
    { id: 'u2', full_name: 'Quinn QAU', email: 'quinn@x.com' },
];

describe('RunReviewersPicker', () => {
    it('renders SD and QAU pickers', () => {
        const { getByLabelText } = render(RunReviewersPicker, {
            studyDirectorId: 'u1',
            qauReviewerId: null,
            members,
            disabled: false,
            onChange: vi.fn(),
        });
        expect(getByLabelText(/Study Director/i)).toBeTruthy();
        expect(getByLabelText(/QAU/i)).toBeTruthy();
    });

    it('shows the QAU pool hint when QAU is unset', () => {
        const { getByText } = render(RunReviewersPicker, {
            studyDirectorId: 'u1',
            qauReviewerId: null,
            members,
            disabled: false,
            onChange: vi.fn(),
        });
        expect(getByText(/QAU team/i)).toBeTruthy();
    });

    it('disables selects when disabled', () => {
        const { getByLabelText } = render(RunReviewersPicker, {
            studyDirectorId: 'u1',
            qauReviewerId: 'u2',
            members,
            disabled: true,
            onChange: vi.fn(),
        });
        expect((getByLabelText(/Study Director/i) as HTMLSelectElement).disabled).toBe(true);
    });
});
