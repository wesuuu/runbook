import { describe, it, expect } from 'vitest';
import { renderTemplate } from './template';

describe('renderTemplate', () => {
    it('substitutes placeholders with string values', () => {
        expect(renderTemplate('Hello {{name}}', { name: 'World' })).toBe('Hello World');
    });

    it('formats numbers as strings', () => {
        expect(renderTemplate('Add {{volume_L}}L', { volume_L: 2.5 })).toBe('Add 2.5L');
    });

    it('leaves raw placeholder when value is missing / empty', () => {
        expect(renderTemplate('{{a}}-{{b}}', { a: 'x' })).toBe('x-{{b}}');
        expect(renderTemplate('{{a}}', { a: null })).toBe('{{a}}');
        expect(renderTemplate('{{a}}', { a: '' })).toBe('{{a}}');
        expect(renderTemplate('{{a}}', { a: [] })).toBe('{{a}}');
    });

    it('formats booleans as Yes/No', () => {
        expect(renderTemplate('filter: {{f}}', { f: true })).toBe('filter: Yes');
        expect(renderTemplate('filter: {{f}}', { f: false })).toBe('filter: No');
    });

    it('joins array values with comma', () => {
        expect(renderTemplate('{{xs}}', { xs: ['a', 'b', 'c'] })).toBe('a, b, c');
    });

    it('handles the full media-prep example', () => {
        const tpl = 'Reconstitute {{volume_L}}L of {{media_name}} using {{basal_medium}}.';
        const out = renderTemplate(tpl, {
            volume_L: 2,
            media_name: 'CHO media',
            basal_medium: 'DMEM',
        });
        expect(out).toBe('Reconstitute 2L of CHO media using DMEM.');
    });

    it('returns template unchanged when params is null/undefined', () => {
        expect(renderTemplate('{{a}}', null)).toBe('{{a}}');
        expect(renderTemplate('{{a}}', undefined)).toBe('{{a}}');
    });

    it('returns empty string for empty template', () => {
        expect(renderTemplate('', { a: 1 })).toBe('');
    });
});
