export type ColumnDef = { key: string; label: string; group: string };
export type ExportLayout = 'long' | 'wide';
export type ExportFormat = 'csv' | 'xlsx' | 'json';

export type ExportPreset = {
    label: string;
    description: string;
    format: ExportFormat;
    layout: ExportLayout;
    columnGroups: string[];
};

export type SavedSettings = {
    format: ExportFormat;
    layout: ExportLayout;
    columnKeys: string[];
};

export const STORAGE_KEY = 'export_last_settings';

export const PRESETS: ExportPreset[] = [
    {
        label: 'Prism-Friendly',
        description: 'Wide layout, CSV, step + data columns',
        format: 'csv',
        layout: 'wide',
        columnGroups: ['step', 'data'],
    },
    {
        label: 'SAS-Friendly',
        description: 'Long layout, CSV, all columns',
        format: 'csv',
        layout: 'long',
        columnGroups: ['metadata', 'step', 'data', 'audit'],
    },
];

/**
 * Build tab-separated text from rows and selected columns.
 * Column order follows the columns array, not the selected set.
 */
export function buildTsv(
    columns: ColumnDef[],
    rows: Record<string, unknown>[],
    selectedKeys: Set<string>,
): string {
    const cols = columns.filter((c) => selectedKeys.has(c.key));
    if (cols.length === 0) return '';

    const header = cols.map((c) => c.label).join('\t');
    const body = rows
        .map((row) =>
            cols.map((c) => String(row[c.key] ?? '')).join('\t'),
        )
        .join('\n');

    return rows.length > 0 ? header + '\n' + body : header;
}

/**
 * Save current export settings to localStorage.
 */
export function saveExportSettings(
    format: ExportFormat,
    layout: ExportLayout,
    columnKeys: string[],
): void {
    const settings: SavedSettings = { format, layout, columnKeys };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

/**
 * Load saved export settings from localStorage.
 * Returns null if nothing saved or data is corrupt.
 */
export function loadExportSettings(): SavedSettings | null {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
        return JSON.parse(raw) as SavedSettings;
    } catch {
        return null;
    }
}

/**
 * Intersect saved column keys with currently available columns.
 * Returns a Set of matching keys, or null if no matches (caller should
 * fall back to select-all).
 */
export function applyRestoredColumns(
    savedKeys: string[],
    availableColumns: ColumnDef[],
): Set<string> | null {
    if (savedKeys.length === 0) return null;
    const available = new Set(availableColumns.map((c) => c.key));
    const restored = savedKeys.filter((k) => available.has(k));
    return restored.length > 0 ? new Set(restored) : null;
}
