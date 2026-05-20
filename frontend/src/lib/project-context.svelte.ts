const STORAGE_KEY = 'batchrite.current_project_slug';

function loadInitial(): string | null {
    if (typeof localStorage === 'undefined') return null;
    try {
        return localStorage.getItem(STORAGE_KEY);
    } catch {
        return null;
    }
}

let currentProjectSlug = $state<string | null>(loadInitial());

export function getCurrentProjectSlug(): string | null {
    return currentProjectSlug;
}

export function setCurrentProjectSlug(slug: string | null): void {
    currentProjectSlug = slug;
    try {
        if (slug) {
            localStorage.setItem(STORAGE_KEY, slug);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    } catch {
        // private mode / quota — non-fatal
    }
}

export function clearCurrentProjectSlug(): void {
    setCurrentProjectSlug(null);
}
