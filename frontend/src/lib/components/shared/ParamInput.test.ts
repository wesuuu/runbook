import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ParamInput from './ParamInput.svelte';

describe('ParamInput', () => {
    it('renders a number input for type=number', async () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'number', title: 'Temp' },
            value: 25,
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="number"]');
        expect(input).toBeTruthy();
    });

    it('renders an enum select when schema.enum is present', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', enum: ['A', 'B', 'C'], title: 'Mode' },
            value: 'A',
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const sel = container.querySelector('select');
        expect(sel).toBeTruthy();
        expect(sel?.querySelectorAll('option').length).toBe(3);
    });

    it('renders a media-ref select when x-ref-type=media_prep', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', 'x-ref-type': 'media_prep', title: 'Media' },
            value: '',
            onChange: () => {},
            mediaPrepNodes: [{ id: 'mp1', label: 'LB Broth' }],
        });
        const sel = container.querySelector('select');
        expect(sel).toBeTruthy();
        const options = sel?.querySelectorAll('option');
        expect(options?.length).toBeGreaterThanOrEqual(2);
    });

    it('renders a text input as fallback', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', title: 'Note' },
            value: 'hi',
            onChange: () => {},
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="text"]');
        expect(input).toBeTruthy();
    });

    it('fires onChange when user types', async () => {
        let captured: unknown = undefined;
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'number', title: 'Temp' },
            value: 25,
            onChange: (v) => { captured = v; },
            mediaPrepNodes: [],
        });
        const input = container.querySelector('input[type="number"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: '30' } });
        expect(captured).toBe(30);
    });

    it('respects readonly prop (renders disabled input)', () => {
        const { container } = render(ParamInput, {
            id: 'p',
            schema: { type: 'string', title: 'Note' },
            value: 'hi',
            onChange: () => {},
            mediaPrepNodes: [],
            readonly: true,
        });
        const input = container.querySelector('input') as HTMLInputElement;
        expect(input.disabled).toBe(true);
    });
});
