import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

/** Event the protocol editor listens to. Selects a specific sample node by id. */
export const SELECT_SAMPLE_NODE_EVENT = 'onboarding:select-sample-node';
/** Event that clears any programmatic selection made during the tour. */
export const CLEAR_SAMPLE_NODE_EVENT = 'onboarding:clear-sample-node';
/** Event the Inspector listens to — expands the Edit Schema collapsible. */
export const EXPAND_SCHEMA_EDITOR_EVENT = 'onboarding:expand-schema-editor';

function selectSampleNode(nodeId: string): void {
    window.dispatchEvent(
        new CustomEvent(SELECT_SAMPLE_NODE_EVENT, { detail: { nodeId } }),
    );
}

function clearSampleNode(): void {
    window.dispatchEvent(new CustomEvent(CLEAR_SAMPLE_NODE_EVENT));
}

function expandSchemaEditor(): void {
    window.dispatchEvent(new CustomEvent(EXPAND_SCHEMA_EDITOR_EVENT));
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
                        // Select the first unit op so the Inspector mounts for the next step.
                        selectSampleNode('sample-buffer');
                        await new Promise((resolve) => setTimeout(resolve, 250));
                        d.moveNext();
                    },
                },
            },
            {
                element: '[data-id="sample-buffer"]',
                popover: {
                    title: 'Selected Node',
                    description:
                        "We've selected the Buffer Prep node for you. Selecting any node opens the Inspector on the right with its editable fields.",
                },
            },
            {
                element: '[data-tour="inspector-instruction"]',
                popover: {
                    title: 'Instruction (with templating)',
                    description:
                        'Write what the operator should do. Reference any parameter with double curly braces — e.g. {{volume_L}} — and the preview below updates live with the filled-in value.',
                },
            },
            {
                element: '[data-tour="inspector-schema"]',
                popover: {
                    title: 'Edit Schema',
                    description:
                        'Expand this section to shape the unit op\'s parameters. Use "+ Add Parameter" to introduce new fields (key, label, type) — they immediately show up as inputs above and become available as {{variables}} in the instruction.',
                    onPrevClick: () => {
                        d.movePrevious();
                    },
                    onNextClick: () => {
                        clearSampleNode();
                        d.moveNext();
                    },
                },
                onHighlightStarted: () => {
                    // Open the collapsible so the user can see the schema editor contents.
                    expandSchemaEditor();
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
