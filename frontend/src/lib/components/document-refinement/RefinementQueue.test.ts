import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type { RefinementFlag } from '$lib/schemas/documents';
import RefinementQueue from './RefinementQueue.svelte';

const FLAGS: RefinementFlag[] = [
    {
        id: 'flag-001',
        kind: 'low_confidence_ocr',
        confidence: 0.31,
        block_anchor: 'table-1.row-1.col-2',
        source_text: 'NaHzPO4119.98',
        page: 1,
    },
    {
        id: 'flag-002',
        kind: 'low_confidence_ocr',
        confidence: 0.48,
        source_text: 'Prepare0.8Lofwater',
        page: 2,
    },
];

describe('RefinementQueue', () => {
    it('renders the empty state when there are no flags', () => {
        render(RefinementQueue, {
            props: { flags: [], activeFlagId: null, onFlagClick: vi.fn() },
        });
        expect(screen.getByText(/no flags/i)).toBeTruthy();
    });

    it('renders one item per flag with the flag count', () => {
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: null, onFlagClick: vi.fn() },
        });
        expect(screen.getByText('2')).toBeTruthy();
        expect(screen.getByText('NaHzPO4119.98')).toBeTruthy();
        expect(screen.getByText('Prepare0.8Lofwater')).toBeTruthy();
    });

    it('calls onFlagClick with the flag when an item is clicked', async () => {
        const onFlagClick = vi.fn();
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: null, onFlagClick },
        });
        await fireEvent.click(screen.getByText('NaHzPO4119.98'));
        expect(onFlagClick).toHaveBeenCalledWith(FLAGS[0]);
    });

    it('marks the active flag', () => {
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: 'flag-002', onFlagClick: vi.fn() },
        });
        const active = screen.getByText('Prepare0.8Lofwater').closest('button');
        expect(active?.getAttribute('data-active')).toBe('true');
    });
});
