import { driver } from 'driver.js';
import 'driver.js/dist/driver.css';
import { markCompleted, markDismissed } from '../tourStore.svelte';

/** Event the protocol editor listens to. Selects a specific sample node by id. */
export const SELECT_SAMPLE_NODE_EVENT = 'onboarding:select-sample-node';
/** Event that clears any programmatic selection made during the tour. */
export const CLEAR_SAMPLE_NODE_EVENT = 'onboarding:clear-sample-node';
/** Event the Inspector listens to — expands the Edit Schema collapsible. */
export const EXPAND_SCHEMA_EDITOR_EVENT = 'onboarding:expand-schema-editor';
/** Event the Inspector listens to — sets the instruction textarea content. */
export const SET_INSTRUCTION_EVENT = 'onboarding:set-instruction';
/** Event the editor listens to — triggers saveDraft. */
export const SAVE_PROTOCOL_EVENT = 'onboarding:save-protocol';
/** Event the editor listens to — opens the PDF preview drawer. */
export const OPEN_PDF_PREVIEW_EVENT = 'onboarding:open-pdf-preview';
/** Event the editor listens to — closes the PDF preview drawer. */
export const CLOSE_PDF_PREVIEW_EVENT = 'onboarding:close-pdf-preview';

const SAMPLE_INSTRUCTION =
    'Prepare {{volume_L}}L of {{buffer_name}} buffer, adjusting to pH {{ph}} with HCl.';

function fire(event: string, detail?: unknown): void {
    window.dispatchEvent(new CustomEvent(event, { detail }));
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
                        fire(SELECT_SAMPLE_NODE_EVENT, { nodeId: 'sample-buffer' });
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
                element: '[data-tour="inspector-schema"]',
                popover: {
                    title: 'Edit Schema',
                    description:
                        'Expand this section to shape the unit op\'s parameters. Use "+ Add Parameter" to add new fields (key, label, type). They immediately show up as inputs above and become available as {{variables}} in the instruction.',
                },
                onHighlightStarted: () => {
                    fire(EXPAND_SCHEMA_EDITOR_EVENT);
                },
            },
            {
                element: '[data-tour="inspector-instruction"]',
                popover: {
                    title: 'Write an Instruction',
                    description:
                        "Let's write the operator instruction. Watch — we'll type one that references the parameters you just saw.",
                    onNextClick: async () => {
                        fire(SET_INSTRUCTION_EVENT, { text: SAMPLE_INSTRUCTION });
                        await new Promise((resolve) => setTimeout(resolve, 150));
                        d.moveNext();
                    },
                },
            },
            {
                element: '[data-tour="inspector-instruction-preview"]',
                popover: {
                    title: 'Rendered Preview',
                    description:
                        'Every {{variable}} in the instruction is replaced by its live value below. This is exactly what the operator sees at run time.',
                },
            },
            {
                element: '[data-tour="protocol-save"]',
                popover: {
                    title: 'Save',
                    description:
                        "Let's save what we just edited so the final document can be generated from it.",
                    onNextClick: async () => {
                        fire(SAVE_PROTOCOL_EVENT);
                        // Give the save request a moment to kick off before opening the preview.
                        await new Promise((resolve) => setTimeout(resolve, 600));
                        d.moveNext();
                    },
                },
            },
            {
                element: '[data-tour="pdf-preview"]',
                popover: {
                    title: 'Preview Documents',
                    description:
                        'Here is the SOP rendered from the protocol you just edited. The instruction is merged with the live parameter values — same templating you saw in the Inspector preview.',
                    onPrevClick: () => {
                        fire(CLOSE_PDF_PREVIEW_EVENT);
                        d.movePrevious();
                    },
                    onNextClick: () => {
                        fire(CLOSE_PDF_PREVIEW_EVENT);
                        d.moveNext();
                    },
                },
                onHighlightStarted: async () => {
                    fire(OPEN_PDF_PREVIEW_EVENT);
                    // Drawer mounts and the modal wrapper needs a beat to paint.
                    await new Promise((resolve) => setTimeout(resolve, 400));
                },
            },
        ],
        onDestroyStarted: async () => {
            const completed = d.isActive() && d.isLastStep();
            // Clean up any tour-driven state so nothing lingers after the tour.
            fire(CLEAR_SAMPLE_NODE_EVENT);
            fire(CLOSE_PDF_PREVIEW_EVENT);
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
