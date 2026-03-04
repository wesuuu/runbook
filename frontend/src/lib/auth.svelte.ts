import { API_BASE } from '$lib/config';

interface User {
    id: string;
    email: string;
    full_name: string | null;
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

export async function login(email: string, password: string): Promise<void> {
    const res = await authFetch<{ access_token: string }>('POST', '/auth/login', { email, password });
    token = res.access_token;
    localStorage.setItem('auth_token', token);

    // Load user profile and orgs
    user = await authFetch<User>('GET', '/auth/me');
    await loadOrgs();
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
}

export function logout(): void {
    token = null;
    user = null;
    currentOrg = null;
    orgs = [];
    localStorage.removeItem('auth_token');
}

export function switchOrg(org: Org): void {
    currentOrg = org;
    localStorage.setItem('current_org_id', org.id);
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
    } catch {
        // Token is invalid — clear it
        logout();
    } finally {
        initialized = true;
    }
}
