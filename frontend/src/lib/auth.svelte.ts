import { API_BASE } from '$lib/config';

interface User {
    id: string;
    email: string;
    full_name: string | null;
    job_title: string | null;
    avatar_url: string | null;
    preferences: Record<string, string>;
    is_active: boolean;
}

interface Org {
    id: string;
    name: string;
    created_at: string;
    updated_at: string;
}

let user = $state<User | null>(null);
let token = $state<string | null>(localStorage.getItem('auth_token'));
let currentOrg = $state<Org | null>(null);
let orgs = $state<Org[]>([]);
let initialized = $state(false);

export function getToken(): string | null {
    return token;
}

export function isAuthenticated(): boolean {
    return token !== null && user !== null;
}

export function getUser(): User | null {
    return user;
}

export function getCurrentOrg(): Org | null {
    return currentOrg;
}

export function getOrgs(): Org[] {
    return orgs;
}

export function isInitialized(): boolean {
    return initialized;
}

export function getUserPreferences(): Record<string, string> {
    return user?.preferences ?? {};
}

export async function refreshUser(): Promise<void> {
    if (!token) return;
    try {
        user = await authFetch<User>('GET', '/auth/me');
        cacheAuthData();
    } catch {
        // ignore — keep existing data (could be offline)
    }
}

async function authFetch<T>(method: string, endpoint: string, body?: unknown): Promise<T> {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const config: RequestInit = { method, headers };
    if (body) {
        config.body = JSON.stringify(body);
    }

    const response = await fetch(`${API_BASE}${endpoint}`, config);

    if (!response.ok) {
        let message = 'An error occurred';
        try {
            const err = await response.json();
            message = err.detail || err.message || message;
        } catch {
            // ignore
        }
        throw new Error(message);
    }

    if (response.status === 204) return {} as T;
    return response.json();
}

/** Cache user and org data to localStorage for offline resilience. */
function cacheAuthData(): void {
    if (user) localStorage.setItem('cached_user', JSON.stringify(user));
    if (orgs.length > 0) localStorage.setItem('cached_orgs', JSON.stringify(orgs));
    if (currentOrg) localStorage.setItem('cached_current_org', JSON.stringify(currentOrg));
}

/** Load cached auth data from localStorage. Returns true if cache was found. */
function loadCachedAuthData(): boolean {
    try {
        const cachedUser = localStorage.getItem('cached_user');
        const cachedOrgs = localStorage.getItem('cached_orgs');
        const cachedCurrentOrg = localStorage.getItem('cached_current_org');
        if (cachedUser) {
            user = JSON.parse(cachedUser);
            orgs = cachedOrgs ? JSON.parse(cachedOrgs) : [];
            currentOrg = cachedCurrentOrg ? JSON.parse(cachedCurrentOrg) : orgs[0] ?? null;
            return true;
        }
    } catch {
        // Corrupted cache — ignore
    }
    return false;
}

/** Clear cached auth data on logout. */
function clearCachedAuthData(): void {
    localStorage.removeItem('cached_user');
    localStorage.removeItem('cached_orgs');
    localStorage.removeItem('cached_current_org');
}

/** Check if an error is a network failure (not a server response). */
function isNetworkError(err: unknown): boolean {
    if (err instanceof TypeError && err.message.includes('fetch')) return true;
    if (err instanceof TypeError && err.message.includes('network')) return true;
    if (err instanceof DOMException && err.name === 'AbortError') return true;
    // Check for generic "Failed to fetch" which happens when offline
    if (err instanceof TypeError && err.message === 'Failed to fetch') return true;
    return false;
}

export async function login(email: string, password: string): Promise<void> {
    const res = await authFetch<{ access_token: string }>('POST', '/auth/login', { email, password });
    token = res.access_token;
    localStorage.setItem('auth_token', token);

    // Load user profile and orgs
    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
    cacheAuthData();
}

export async function register(email: string, password: string, fullName: string): Promise<void> {
    const res = await authFetch<{ access_token: string }>('POST', '/auth/register', {
        email,
        password,
        full_name: fullName,
    });
    token = res.access_token;
    localStorage.setItem('auth_token', token);

    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
    cacheAuthData();
}

export function logout(): void {
    token = null;
    user = null;
    currentOrg = null;
    orgs = [];
    localStorage.removeItem('auth_token');
    clearCachedAuthData();
}

export function switchOrg(org: Org): void {
    currentOrg = org;
    localStorage.setItem('current_org_id', org.id);
    cacheAuthData();
}

async function loadOrgs(): Promise<void> {
    try {
        orgs = await authFetch<Org[]>('GET', '/iam/organizations');
        // Restore previously selected org or use first
        const savedOrgId = localStorage.getItem('current_org_id');
        const saved = orgs.find((o) => o.id === savedOrgId);
        currentOrg = saved ?? orgs[0] ?? null;
    } catch {
        orgs = [];
        currentOrg = null;
    }
}

export async function initialize(): Promise<void> {
    if (initialized) return;

    if (!token) {
        initialized = true;
        return;
    }

    try {
        user = await authFetch<User>('GET', '/auth/me');
        await loadOrgs();
        cacheAuthData();
    } catch (err) {
        if (isNetworkError(err)) {
            // Network failure — load cached data instead of logging out
            const hasCached = loadCachedAuthData();
            if (!hasCached) {
                // No cache available, can't recover
                logout();
            }
        } else {
            // Server responded with error (401, etc.) — token is invalid
            logout();
        }
    } finally {
        initialized = true;
    }
}
