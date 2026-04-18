import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { api } from '$lib/api';
import { markCompleted, markDismissed } from '../tourStore.svelte';

async function cleanupSampleRun(): Promise<void> {
    try {
        await api.post('/onboarding/tour/run/end', {});
    } catch {
        // Idempotent on the server; swallow errors.
    }
}

export function runRunTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="run-role-panel"]',
                popover: {
                    title: 'Roles',
                    description: 'Assign team members to the roles this protocol needs.',
                },
            },
            {
                element: '[data-tour="run-step-list"]',
                popover: {
                    title: 'Steps',
                    description: 'Work through the steps in order.',
                },
            },
            {
                element: '[data-tour="run-step-complete"]',
                popover: {
                    title: 'Complete a step',
                    description: 'Check each step off as you go.',
                },
            },
            {
                element: '[data-tour="run-results"]',
                popover: {
                    title: 'Results',
                    description: 'See run status and results summary here.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.isLastStep();
            if (completed) {
                await markCompleted('run');
            } else {
                await markDismissed('run');
            }
            await cleanupSampleRun();
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
