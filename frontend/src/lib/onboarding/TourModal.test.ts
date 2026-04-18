import { render, screen, fireEvent } from '@testing-library/svelte';
import { describe, it, expect, vi } from 'vitest';
import TourModal from './TourModal.svelte';

describe('TourModal', () => {
    it('renders title and both labels', () => {
        render(TourModal, {
            open: true,
            title: 'Welcome',
            primaryLabel: 'Take tour',
            secondaryLabel: 'Dismiss',
            onPrimary: () => {},
            onSecondary: () => {},
        });

        expect(screen.getByText('Welcome')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Take tour' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
    });

    it('fires onPrimary when primary button clicked', async () => {
        const onPrimary = vi.fn();
        render(TourModal, {
            open: true,
            title: 'T',
            primaryLabel: 'Go',
            secondaryLabel: 'No',
            onPrimary,
            onSecondary: () => {},
        });
        await fireEvent.click(screen.getByRole('button', { name: 'Go' }));
        expect(onPrimary).toHaveBeenCalledOnce();
    });

    it('fires onSecondary when secondary button clicked', async () => {
        const onSecondary = vi.fn();
        render(TourModal, {
            open: true,
            title: 'T',
            primaryLabel: 'Go',
            secondaryLabel: 'No',
            onPrimary: () => {},
            onSecondary,
        });
        await fireEvent.click(screen.getByRole('button', { name: 'No' }));
        expect(onSecondary).toHaveBeenCalledOnce();
    });
});
