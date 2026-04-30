const STORAGE_KEY = 'batchrite.current_project_id';

function loadInitial(): string | null {
    if (typeof localStorage === 'undefined') return null;
    try {
        return localStorage.getItem(STORAGE_KEY);
    } catch {
        return null;
    }
}

let currentProjectId = $state<string | null>(loadInitial());

export function getCurrentProjectId(): string | null {
    return currentProjectId;
}

export function setCurrentProjectId(id: string | null): void {
    currentProjectId = id;
    try {
        if (id) {
            localStorage.setItem(STORAGE_KEY, id);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    } catch {
        // private mode / quota — non-fatal
    }
}

export function clearCurrentProjectId(): void {
    setCurrentProjectId(null);
}
