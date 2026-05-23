import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import BlockerTag from './BlockerTag.svelte';

describe('BlockerTag', () => {
    it('renders the blocker label text', () => {
        const { getByTestId } = render(BlockerTag, {
            props: { blocker: { code: 'LANES_UNASSIGNED', label: '2 roles unassigned' } },
        });
        expect(getByTestId('blocker-tag').textContent).toContain('2 roles unassigned');
    });

    it('escapes HTML metacharacters in the label', () => {
        const { getByTestId, container } = render(BlockerTag, {
            props: { blocker: { code: 'X', label: '<img src=x onerror=alert(1)>' } },
        });
        // rendered as text, not parsed as an element
        expect(container.querySelector('img')).toBeNull();
        expect(getByTestId('blocker-tag').textContent).toContain('<img src=x');
    });
});
