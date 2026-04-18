import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

export function runProtocolTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="protocol-canvas"]',
                popover: {
                    title: 'Canvas',
                    description: 'This is where you visually build the protocol. Each box is a step; edges between boxes define the order.',
                },
            },
            {
                element: '[data-id="sample-start"]',
                popover: {
                    title: 'Process Start',
                    description: 'Every protocol begins with a Process Start node. It marks where the workflow kicks off and anchors the rest of the graph.',
                },
            },
            {
                element: '[data-tour="protocol-sidebar"]',
                popover: {
                    title: 'Unit Ops',
                    description: 'Drag unit operations from here onto the canvas to add new steps after Process Start.',
                },
            },
            {
                element: '[data-tour="protocol-inspector"]',
                popover: {
                    title: 'Inspector',
                    description: 'Click any node to edit its parameters in this panel.',
                },
            },
            {
                element: '[data-tour="protocol-save"]',
                popover: {
                    title: 'Save',
                    description: 'Save your changes — nothing is persisted until you click here.',
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.isLastStep();
            if (completed) {
                await markCompleted('protocol');
            } else {
                await markDismissed('protocol');
            }
            d.destroy();
            onFinish();
        },
    });
    d.drive();
}
