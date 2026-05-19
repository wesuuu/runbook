import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import TagsInput from './TagsInput.svelte';

describe('TagsInput', () => {
    it('emits onChange with normalized tag on Enter', async () => {
        const onChange = vi.fn();
        const { getByPlaceholderText } = render(TagsInput, {
            props: { value: [], suggestions: [], onChange },
        });
        const input = getByPlaceholderText(/add tag/i);
        await fireEvent.input(input, { target: { value: 'GLP / QC' } });
        await fireEvent.keyDown(input, { key: 'Enter' });
        expect(onChange).toHaveBeenCalledWith(['glp-qc']);
    });

    it('removes a tag', async () => {
        const onChange = vi.fn();
        const { getByLabelText } = render(TagsInput, {
            props: { value: ['glp'], suggestions: [], onChange },
        });
        await fireEvent.click(getByLabelText(/remove glp/i));
        expect(onChange).toHaveBeenCalledWith([]);
    });
});
