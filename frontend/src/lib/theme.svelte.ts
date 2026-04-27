export const THEMES = ['lab-glass', 'blueprint', 'apothecary'] as const;
export type Theme = typeof THEMES[number];
export const DEFAULT_THEME: Theme = 'lab-glass';

const STORAGE_KEY = 'batchrite.theme';

let current = $state<Theme>(DEFAULT_THEME);

export function isTheme(value: unknown): value is Theme {
    return typeof value === 'string' && (THEMES as readonly string[]).includes(value);
}

export function getTheme(): Theme {
    return current;
}

export function applyThemeFromCache(): void {
    let stored: string | null = null;
    try {
        stored = localStorage.getItem(STORAGE_KEY);
    } catch {
        stored = null;
    }
    const next = isTheme(stored) ? stored : DEFAULT_THEME;
    current = next;
    document.documentElement.dataset.theme = next;
}

export async function setTheme(
    next: Theme,
    persist?: (theme: Theme) => Promise<void>,
): Promise<void> {
    if (!isTheme(next)) {
        throw new Error(`Unknown theme: ${next}`);
    }
    current = next;
    document.documentElement.dataset.theme = next;
    try {
        localStorage.setItem(STORAGE_KEY, next);
    } catch {
        // private mode / quota — non-fatal
    }
    if (persist) {
        await persist(next);
    }
}

/** Sync from server preferences (called after refreshUser). Server is source of truth. */
export function syncThemeFromServer(prefs: Record<string, string> | null | undefined): void {
    const serverTheme = prefs?.theme;
    if (isTheme(serverTheme) && serverTheme !== current) {
        current = serverTheme;
        document.documentElement.dataset.theme = serverTheme;
        try {
            localStorage.setItem(STORAGE_KEY, serverTheme);
        } catch {
            /* non-fatal */
        }
    }
}
