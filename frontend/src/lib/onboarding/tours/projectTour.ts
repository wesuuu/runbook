import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

export function runProjectTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="project-tab-protocols"]',
                popover: {
                    title: 'Protocols',
                    description: 'Protocols are the recipes your team runs.',
                },
            },
            {
                element: '[data-tour="project-tab-experiments"]',
                popover: {
                    title: 'Experiments',
                    description: 'Experiments group related runs and snapshot a protocol at a point in time.',
                },
            },
            {
                element: '[data-tour="project-tab-runs"]',
                popover: {
                    title: 'Runs',
                    description: 'Runs are active or completed executions.',
                },
            },
            {
                element: '[data-tour="project-tab-activity"]',
                popover: {
                    title: 'Activity',
                    description: 'See a feed of everything happening in this project.',
                },
            },
            {
                element: '[data-tour="project-tab-settings"]',
                popover: {
                    title: 'Settings',
                    description: 'Manage project members and templates here.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.isLastStep();
            if (completed) {
                await markCompleted('project');
            } else {
                await markDismissed('project');
            }
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
