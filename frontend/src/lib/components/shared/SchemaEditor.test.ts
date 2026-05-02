import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SchemaEditor from './SchemaEditor.svelte';

describe('SchemaEditor', () => {
    it('renders a row per existing schema property', () => {
        const { container } = render(SchemaEditor, {
            rows: [
                { key: 'temperature', title: 'Temperature', type: 'number' },
                { key: 'ph', title: 'pH', type: 'number' },
            ],
            onChange: () => {},
        });
        expect(container.querySelectorAll('[data-schema-row]').length).toBe(2);
    });

    it('fires onChange with appended row on Add Parameter', async () => {
        let captured: any = null;
        const { getByText } = render(SchemaEditor, {
            rows: [{ key: 'a', title: 'A', type: 'string' }],
            onChange: (next) => { captured = next; },
        });
        await fireEvent.click(getByText(/add parameter/i));
        expect(captured).toBeTruthy();
        expect(captured.length).toBe(2);
        expect(captured[1].key).toBe('');
    });

    it('fires onChange with row removed on remove button', async () => {
        let captured: any = null;
        const { container } = render(SchemaEditor, {
            rows: [
                { key: 'a', title: 'A', type: 'string' },
                { key: 'b', title: 'B', type: 'number' },
            ],
            onChange: (next) => { captured = next; },
        });
        const removeBtn = container.querySelector('[aria-label="Remove parameter"]') as HTMLButtonElement;
        await fireEvent.click(removeBtn);
        expect(captured.length).toBe(1);
        expect(captured[0].key).toBe('b');
    });

    it('updates a row in place on input change', async () => {
        let captured: any = null;
        const { container } = render(SchemaEditor, {
            rows: [{ key: 'a', title: 'A', type: 'string' }],
            onChange: (next) => { captured = next; },
        });
        const keyInput = container.querySelector('input[placeholder="key"]') as HTMLInputElement;
        await fireEvent.input(keyInput, { target: { value: 'duration' } });
        expect(captured[0].key).toBe('duration');
    });
});
