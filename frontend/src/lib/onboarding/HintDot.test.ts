import { render, screen, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi } from 'vitest';
import HintDot from './HintDot.svelte';

describe('HintDot', () => {
    it('renders when visible is true', () => {
        render(HintDot, { visible: true, ariaLabel: 'take tour', onClick: () => {} });
        expect(screen.getByLabelText('take tour')).toBeInTheDocument();
    });

    it('renders nothing when visible is false', () => {
        render(HintDot, { visible: false, ariaLabel: 'take tour', onClick: () => {} });
        expect(screen.queryByLabelText('take tour')).toBeNull();
    });

    it('fires onClick when clicked', async () => {
        const onClick = vi.fn();
        render(HintDot, { visible: true, ariaLabel: 'take tour', onClick });
        await fireEvent.click(screen.getByLabelText('take tour'));
        expect(onClick).toHaveBeenCalledOnce();
    });
});
