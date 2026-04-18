import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

/** Event the protocol editor listens to. Selects a specific sample node by id. */
export const SELECT_SAMPLE_NODE_EVENT = 'onboarding:select-sample-node';
/** Event that clears any programmatic selection made during the tour. */
export const CLEAR_SAMPLE_NODE_EVENT = 'onboarding:clear-sample-node';

function selectSampleNode(nodeId: string): void {
    window.dispatchEvent(
        new CustomEvent(SELECT_SAMPLE_NODE_EVENT, { detail: { nodeId } }),
    );
}

function clearSampleNode(): void {
    window.dispatchEvent(new CustomEvent(CLEAR_SAMPLE_NODE_EVENT));
}

export function runProtocolTour(onFinish: () => void): void {
    const d = driver({
        showProgress: true,
        allowClose: true,
        steps: [
            {
                element: '[data-tour="protocol-canvas"]',
                popover: {
                    title: 'Canvas',
                    description:
                        'This is where you visually build the protocol. Each box is a step; edges between boxes define the order.',
                },
            },
            {
                element: '[data-id="sample-start"]',
                popover: {
                    title: 'Process Start',
                    description:
                        'Every protocol begins with a Process Start node. It marks where the workflow kicks off and anchors the rest of the graph.',
                },
            },
            {
                element: '[data-tour="protocol-sidebar"]',
                popover: {
                    title: 'Unit Ops',
                    description:
                        'Drag unit operations from here onto the canvas to add new steps after Process Start.',
                    onNextClick: async () => {
                        // Programmatically select the first unit op so the Inspector mounts
                        // before we try to spotlight it.
                        selectSampleNode('sample-buffer');
                        await new Promise((resolve) => setTimeout(resolve, 250));
                        d.moveNext();
                    },
                },
            },
            {
                element: '[data-tour="protocol-inspector"]',
                popover: {
                    title: 'Inspector',
                    description:
                        'With a node selected, use this panel to edit its name, parameters, duration, role, and equipment.',
                    onPrevClick: () => {
                        clearSampleNode();
                        d.movePrevious();
                    },
                    onNextClick: () => {
                        clearSampleNode();
                        d.moveNext();
                    },
                },
            },
            {
                element: '[data-tour="protocol-save"]',
                popover: {
                    title: 'Save',
                    description: "Save your changes — nothing is persisted until you click here.",
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.isLastStep();
            // Always clear tour-driven selection so the inspector doesn't linger.
            clearSampleNode();
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
