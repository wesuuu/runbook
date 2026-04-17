import { describe, it, expect, beforeEach } from 'vitest';
import {
    buildTsv,
    saveExportSettings,
    loadExportSettings,
    applyRestoredColumns,
    PRESETS,
    STORAGE_KEY,
} from './export-utils';
import type { ColumnDef } from './export-utils';

// Mock localStorage for Node test environment
const store: Record<string, string> = {};
const localStorageMock = {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
};
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

describe('buildTsv', () => {
    const columns: ColumnDef[] = [
        { key: 'name', label: 'Name', group: 'metadata' },
        { key: 'value', label: 'Value', group: 'data' },
        { key: 'status', label: 'Status', group: 'metadata' },
    ];

    const rows = [
        { name: 'Run A', value: '42', status: 'COMPLETED' },
        { name: 'Run B', value: '99', status: 'EDITED' },
    ];

    it('builds TSV with header and all rows for selected columns', () => {
        const selected = new Set(['name', 'value']);
        const result = buildTsv(columns, rows, selected);
        expect(result).toBe('Name\tValue\nRun A\t42\nRun B\t99');
    });

    it('includes all columns when all are selected', () => {
        const selected = new Set(['name', 'value', 'status']);
        const result = buildTsv(columns, rows, selected);
        expect(result).toBe(
            'Name\tValue\tStatus\nRun A\t42\tCOMPLETED\nRun B\t99\tEDITED'
        );
    });

    it('returns empty string when no columns selected', () => {
        const result = buildTsv(columns, rows, new Set());
        expect(result).toBe('');
    });

    it('returns header only when rows are empty', () => {
        const selected = new Set(['name']);
        const result = buildTsv(columns, [], selected);
        expect(result).toBe('Name');
    });

    it('handles null/undefined cell values as empty string', () => {
        const rowsWithNulls = [
            { name: 'Run A', value: null, status: undefined },
        ];
        const selected = new Set(['name', 'value', 'status']);
        const result = buildTsv(columns, rowsWithNulls, selected);
        expect(result).toBe('Name\tValue\tStatus\nRun A\t\t');
    });

    it('preserves column order from columns array, not selected set', () => {
        // Select in reverse order — output should still follow columns array order
        const selected = new Set(['status', 'name']);
        const result = buildTsv(columns, rows, selected);
        const headerLine = result.split('\n')[0];
        expect(headerLine).toBe('Name\tStatus');
    });
});

describe('saveExportSettings / loadExportSettings', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('saves and restores format, layout, and column keys', () => {
        saveExportSettings('xlsx', 'wide', ['name', 'value']);
        const restored = loadExportSettings();
        expect(restored).toEqual({
            format: 'xlsx',
            layout: 'wide',
            columnKeys: ['name', 'value'],
        });
    });

    it('returns null when nothing is saved', () => {
        expect(loadExportSettings()).toBeNull();
    });

    it('returns null for corrupt localStorage data', () => {
        localStorage.setItem(STORAGE_KEY, 'not-json{{{');
        expect(loadExportSettings()).toBeNull();
    });

    it('overwrites previous settings on save', () => {
        saveExportSettings('csv', 'long', ['a']);
        saveExportSettings('json', 'wide', ['b', 'c']);
        const restored = loadExportSettings();
        expect(restored?.format).toBe('json');
        expect(restored?.layout).toBe('wide');
        expect(restored?.columnKeys).toEqual(['b', 'c']);
    });
});

describe('applyRestoredColumns', () => {
    const availableColumns: ColumnDef[] = [
        { key: 'name', label: 'Name', group: 'metadata' },
        { key: 'value', label: 'Value', group: 'data' },
        { key: 'status', label: 'Status', group: 'metadata' },
    ];

    it('returns intersection of saved keys and available columns', () => {
        const savedKeys = ['name', 'value', 'nonexistent_param'];
        const result = applyRestoredColumns(savedKeys, availableColumns);
        expect(result).toEqual(new Set(['name', 'value']));
    });

    it('returns null (select-all fallback) when no saved keys match', () => {
        const savedKeys = ['old_param_1', 'old_param_2'];
        const result = applyRestoredColumns(savedKeys, availableColumns);
        expect(result).toBeNull();
    });

    it('returns null for empty saved keys', () => {
        const result = applyRestoredColumns([], availableColumns);
        expect(result).toBeNull();
    });

    it('returns all keys when all saved keys match', () => {
        const savedKeys = ['name', 'value', 'status'];
        const result = applyRestoredColumns(savedKeys, availableColumns);
        expect(result).toEqual(new Set(['name', 'value', 'status']));
    });
});

describe('PRESETS', () => {
    it('has Prism-Friendly preset with correct config', () => {
        const prism = PRESETS.find((p) => p.label === 'Prism-Friendly');
        expect(prism).toBeDefined();
        expect(prism!.format).toBe('csv');
        expect(prism!.layout).toBe('wide');
        expect(prism!.columnGroups).toEqual(['step', 'data']);
    });

    it('has SAS-Friendly preset with correct config', () => {
        const sas = PRESETS.find((p) => p.label === 'SAS-Friendly');
        expect(sas).toBeDefined();
        expect(sas!.format).toBe('csv');
        expect(sas!.layout).toBe('long');
        expect(sas!.columnGroups).toEqual(['metadata', 'step', 'data', 'audit']);
    });

    it('each preset has label, description, format, layout, and columnGroups', () => {
        for (const preset of PRESETS) {
            expect(preset.label).toBeTruthy();
            expect(preset.description).toBeTruthy();
            expect(['csv', 'xlsx', 'json']).toContain(preset.format);
            expect(['long', 'wide']).toContain(preset.layout);
            expect(preset.columnGroups.length).toBeGreaterThan(0);
        }
    });
});
